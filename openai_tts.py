"""
openai_tts.py — OpenAI cloud TTS for Luna (same interface the old Piper engine had).

Same shape as the Piper engine so text_to_speech.py doesn't care which one is
plugged in:  tts.speak(text, on_audio_start=callback)

  OpenAI (response_format="pcm": 24 kHz, s16le, mono, streamed)
        |
        v
  python pump  ->  TTS_PLAYER (raw PCM on stdin, blocks until played)

Playback starts on the first streamed chunk, and on_audio_start fires at that
exact moment so the mouth animation begins in sync with the sound. The player
subprocess blocks until the audio has actually finished, which is what keeps
the mic-blocking / echo protection in text_to_speech.py correct.

Short lines she has said before ("Dobrze, budzik na siódmą.", "Proszę bardzo,
oto lusterko.") are kept as audio in DATA_DIR/tts_cache (the newest
CACHE_MAX_FILES) and played from there: no network round trip, no cost — and
the local commands can still answer out loud when the internet is down.
"""

import json
import os
import queue
import subprocess
import threading
import time

import numpy as np

import settings
import themes
import tts_fx
from voicecheck import pitch

from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TTS_SPEED,
    OPENAI_TTS_INSTRUCTIONS,
    OPENAI_TTS_TIMEOUT,
    TTS_PREBUFFER_SECS,
    TTS_STREAM_PREBUFFER_SECS,
    AUDIO_PERSISTENT,
    AUDIO_AHEAD_SECS,
    AUDIO_PREBUFFER_SECS,
    TTS_LEADIN_SECS,
    TTS_PLAYER,
    AUDIO_OUTPUT_DEVICE,
    LIPSYNC_FRAME_MS,
    LIPSYNC_RMS_FULL,
)

PCM_RATE = 24000   # fixed by the API for response_format="pcm"
# read the stream in small pieces: playback starts once AUDIO_PREBUFFER_SECS
# (16.8 kB) is in, and 16 kB reads made it wait for a second whole piece
TTS_READ_BYTES = 4096
# The speech API usually starts in ~0.75 s, but one request in six took over
# 1 s (up to 2.2 s, and 3.9 s once in real use) — the answers that feel slow.
# No audio after this long: the same request again, whichever starts first
# plays, the other one stops (6 Oct: "more snappy").
TTS_HEDGE_AFTER = 1.5          # (was 1.0: on 7 Oct it fired for 13 of 29 lines and the
                               # second request won only 3 times — the first was just late)


def speech_speed():
    """Her speech rate for whoever is in front of her: "mów szybciej" said by
    Emilka is Emilka's (settings "tts_speed_by"), else the house setting."""
    try:
        from shared_state import state
        with state.lock:
            who = state.person[0] if state.person else None
    except Exception:
        who = None
    by = settings.get("tts_speed_by", {}) or {}
    v = by.get(who) or settings.get("tts_speed", OPENAI_TTS_SPEED)
    th = themes.get()
    if th.get("speed"):
        v = v * th["speed"] / OPENAI_TTS_SPEED
    return round(v * tts_fx.speed_factor(th.get("fx")), 2)   # Ice: stretched back here


def voice_kwargs(style=""):
    """The voice and its instructions: Luna's (+ this line's emotion), or the
    theme's own (themes.py) — her emotion styles say "keep the high voice"."""
    th = themes.get()
    if th.get("voice"):
        return {"voice": th["voice"], "instructions": th["tts"]}
    out = {"voice": OPENAI_TTS_VOICE}
    instructions = "\n".join(x for x in (OPENAI_TTS_INSTRUCTIONS, style) if x)
    if instructions:
        out["instructions"] = instructions
    return out


def deep_hz():
    """Below this a take is the voice drifting deep — not for a man's voice."""
    return 0 if themes.male() else DEEP_HZ

CACHE_MAX_CHARS = 140
STEADY_SECS = 0.6              # speech held back to check its pitch (_steady)
DEEP_HZ = 145                  # her voice sits ~175–255 Hz; a take below is the drift
HEAD_BYTES = int(STEADY_SECS * PCM_RATE * 2)

CACHE_STATS = [0, 0]           # hits, misses since start
CACHE_MAX_FILES = 400          # ~3 s each at 48 kB/s: about 60 MB at most


def _cache_dir():
    from config import DATA_DIR
    return os.path.join(DATA_DIR, "tts_cache")


def _cache_key(text, kwargs):
    import hashlib
    blob = json.dumps([text, kwargs.get("model"), kwargs.get("voice"), kwargs.get("speed"),
                       kwargs.get("instructions", ""), themes.get().get("fx")],
                      ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def cache_get(key):
    path = os.path.join(_cache_dir(), key + ".pcm")
    try:
        with open(path, "rb") as f:
            pcm = f.read()
        low = pitch(pcm[:HEAD_BYTES])                # (the head: a drift is the whole take)
        if low and low < deep_hz():                  # a deep take kept before 11 Oct
            os.remove(path)
            return None
        os.utime(path)                               # recently used: kept longer
        return pcm or None
    except OSError:
        return None


def cache_put(key, pcm):
    d = _cache_dir()
    try:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, key + ".tmp")
        with open(tmp, "wb") as f:
            f.write(pcm)
        os.replace(tmp, os.path.join(d, key + ".pcm"))
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".pcm")]
        if len(files) > CACHE_MAX_FILES:
            files.sort(key=os.path.getmtime)
            for old in files[:len(files) - CACHE_MAX_FILES]:
                os.remove(old)
    except OSError as e:
        print(f"[TTS] cache write failed ({e})", flush=True)

# LUNA_SPEAKER aliases → substrings of the PipeWire sink's node.name
_SINK_ALIASES = {
    "jack":       ["mailbox", "headphones"],   # Pi's 3.5 mm output
    "headphones": ["mailbox", "headphones"],
    "hdmi":       ["hdmi"],
    "bluetooth":  ["bluez_output"],
    "bt":         ["bluez_output"],
}


def _resolve_sink(spec):
    """Turn LUNA_SPEAKER into a PipeWire node name for pw-play --target.
    Returns None for "default" (follow the desktop's default output)."""
    if not spec or spec.lower() == "default":
        return None
    try:
        dump  = subprocess.run(["pw-dump"], capture_output=True, text=True,
                               timeout=5).stdout
        sinks = [o["info"]["props"] for o in json.loads(dump)
                 if o.get("info", {}).get("props", {}).get("media.class") == "Audio/Sink"]
    except Exception as e:
        print(f"[TTS] pw-dump failed ({e}) — using {spec!r} as-is")
        return spec
    names = [s.get("node.name", "") for s in sinks]
    if spec in names:
        return spec
    for needle in _SINK_ALIASES.get(spec.lower(), [spec.lower()]):
        for s in sinks:
            hay = (s.get("node.name", "") + " " + s.get("node.description", "")).lower()
            if needle in hay:
                return s["node.name"]
    print(f"[TTS] No PipeWire sink matches LUNA_SPEAKER={spec!r} "
          f"(have: {', '.join(names) or 'none'}) — using default output")
    return None


class Envelope:
    """Loudness-over-time of the audio currently being played, for lip sync.

    feed() is called with every PCM chunk in playback order; frames of
    LIPSYNC_FRAME_MS are reduced to a 0..1 energy. start() stamps the wall
    clock when the player began consuming byte 0, so energy_at(now) can
    look up what the speaker is producing right now."""

    FRAME = int(24000 * LIPSYNC_FRAME_MS / 1000)   # samples per frame

    def __init__(self):
        self.lock     = threading.Lock()
        self.frames   = []          # energy per frame, playback order
        self.shape    = []          # (brightness, zero-crossing rate) per frame
        self.t0       = None        # wall-clock time byte 0 hit the player
        self._carry   = b""

    def reset(self):
        with self.lock:
            self.frames = []
            self.shape  = []
            self.t0     = None
            self._carry = b""

    def start(self):
        with self.lock:
            self.t0 = time.time()

    def start_at(self, t):
        """Byte 0 will be heard at wall-clock time t (the persistent player
        knows this in advance)."""
        with self.lock:
            self.t0 = t

    def feed(self, pcm):
        data = self._carry + pcm
        n    = (len(data) // 2 // self.FRAME) * self.FRAME * 2
        if n == 0:
            self._carry = data
            return
        self._carry = data[n:]
        a = np.frombuffer(data[:n], dtype=np.int16).astype(np.float32)
        a = a.reshape(-1, self.FRAME)
        rms = np.sqrt(np.mean(a * a, axis=1))
        e   = np.clip(rms / LIPSYNC_RMS_FULL, 0.0, 1.0) ** 0.7   # perceptual-ish
        # the shape of the sound, for the mouth's shape: brightness (the
        # slope's loudness over the loudness — her "o/u" ~0.06, "e/i" ~0.2,
        # "s/sz/cz" 0.8+) and how often the wave crosses zero (hiss: high)
        d   = np.diff(a, axis=1)
        br  = np.sqrt(np.mean(d * d, axis=1)) / (rms + 1e-3)
        zc  = np.mean(np.abs(np.diff(np.sign(a), axis=1)) > 0, axis=1)
        with self.lock:
            self.frames.extend(e.tolist())
            self.shape.extend(zip(br.tolist(), zc.tolist()))

    def energy_at(self, t):
        """Energy of the frame playing at wall-clock time t (None = not
        playing / no data yet)."""
        with self.lock:
            if self.t0 is None:
                return None
            i = int((t - self.t0) * 1000 / LIPSYNC_FRAME_MS)
            if i < 0:
                return 0.0
            if i >= len(self.frames):
                return None if self.frames else 0.0
            return self.frames[i]

    def shape_at(self, t):
        """(brightness, zero-crossings) of the frame playing at t, or None."""
        with self.lock:
            if self.t0 is None:
                return None
            i = int((t - self.t0) * 1000 / LIPSYNC_FRAME_MS)
            return self.shape[i] if 0 <= i < len(self.shape) else None


envelope = Envelope()


class OpenAITTS:

    def __init__(self):
        self.lock    = threading.Lock()
        self._cut    = threading.Event()     # stop() → abandon the current line
        self._player = None
        self._client = (OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TTS_TIMEOUT,
                               max_retries=1)
                        if OPENAI_API_KEY else None)
        self._sink    = _resolve_sink(AUDIO_OUTPUT_DEVICE)
        self._raw_cmd = self._build_raw_player_cmd()
        self._out     = None
        if AUDIO_PERSISTENT and self._raw_cmd:
            from audio_out import AudioOut
            self._out = AudioOut(self._raw_cmd, envelope, AUDIO_AHEAD_SECS)
        if self._client is None:
            print("[TTS] No OPENAI_API_KEY — replies will be printed, not spoken")
        elif self._raw_cmd is None:
            print(f"[TTS] TTS_PLAYER={TTS_PLAYER!r} can't take raw PCM on stdin — "
                  "use aplay, ffplay, pw-play or paplay")
        else:
            print(f"[TTS] OpenAI {OPENAI_TTS_MODEL}/{OPENAI_TTS_VOICE} "
                  f"→ {os.path.basename(TTS_PLAYER)} @ {PCM_RATE} Hz "
                  f"→ {self._sink or 'default output'}")

    # ── player command for raw PCM on stdin ─────────────────────────────────
    def _build_raw_player_cmd(self):
        player = os.path.basename(TTS_PLAYER).lower()
        if player.startswith("paplay"):
            return [TTS_PLAYER, "--raw", f"--rate={PCM_RATE}",
                    "--format=s16le", "--channels=1"]
        if player.startswith("pw-play") or player.startswith("pw-cat"):
            cmd = [TTS_PLAYER, "--playback", "--raw", f"--rate={PCM_RATE}",
                   "--format=s16", "--channels=1"]
            if self._sink:
                cmd += ["--target", self._sink]   # only pw-play can pick a sink
            return cmd + ["-"]
        if player.startswith("aplay"):
            return [TTS_PLAYER, "-q", "-r", str(PCM_RATE),
                    "-f", "S16_LE", "-c", "1", "-t", "raw", "-"]
        if player.startswith("ffplay"):
            return [TTS_PLAYER, "-autoexit", "-nodisp", "-loglevel", "quiet",
                    "-f", "s16le", "-ar", str(PCM_RATE), "-ac", "1", "-"]
        return None

    # ── public ──────────────────────────────────────────────────────────────
    def speak(self, text, on_audio_start=None, style=""):
        """style: extra delivery instructions for this line only (the
        reply's emotion — see TTS_EMOTION_STYLE)."""
        with self.lock:
            if self._client is None or self._raw_cmd is None:
                # no voice available — keep the caller's state machine
                # consistent (mouth/mic logic keys off on_audio_start)
                if on_audio_start:
                    on_audio_start()
                return
            if self._out:
                self._speak_persistent(text, on_audio_start, style)
            else:
                self._speak_streaming(text, on_audio_start, style)

    def _hedged(self, text, kwargs):
        """The audio of `text`, chunk by chunk — from a second request when
        the first one hasn't started within TTS_HEDGE_AFTER. Raises the
        error when no request produced any audio."""
        q, lock, first = queue.Queue(), threading.Lock(), threading.Event()
        owner, gone = [None], threading.Event()    # gone: the caller dropped this take
        try:                                   # "7006652" → words the voice reads well
            from polish import spoken_numbers
            text = spoken_numbers(text)
        except Exception:
            pass
        try:                                   # "Jasne, Andrzeju." said in one breath
            import faces
            from polish import flowing_names
            text = flowing_names(text, faces.vocatives())
        except Exception:
            pass

        def attempt(n):
            try:
                with self._client.audio.speech.with_streaming_response.create(
                        input=text, **kwargs) as resp:
                    for chunk in resp.iter_bytes(chunk_size=TTS_READ_BYTES):
                        if self._cut.is_set() or not chunk:
                            if self._cut.is_set():
                                break
                            continue
                        with lock:
                            if owner[0] is None:
                                owner[0] = n
                            mine = owner[0] == n
                        if not mine or gone.is_set():
                            break                      # the other one was faster
                        first.set()
                        q.put(("data", chunk))
            except Exception as e:
                q.put(("error", e))
            finally:
                q.put(("end", n))

        import timing
        timing.mark("tts")
        threading.Thread(target=attempt, args=(0,), daemon=True, name="tts-a").start()
        started = 1
        if not first.wait(TTS_HEDGE_AFTER) and not self._cut.is_set():
            print(f"[TTS] no audio after {TTS_HEDGE_AFTER:.1f}s — asking again", flush=True)
            threading.Thread(target=attempt, args=(1,), daemon=True, name="tts-b").start()
            started = 2
        errors = []
        deadline = time.time() + 60            # one sentence's audio: never forever (10 Oct)
        try:
            yield from self._drain(q, owner, started, deadline, errors)
        finally:
            gone.set()

    def _drain(self, q, owner, started, deadline, errors):
        import timing
        ended = 0
        while ended < started:
            try:
                kind, val = q.get(timeout=max(0.1, min(5.0, deadline - time.time())))
            except queue.Empty:
                if self._cut.is_set() or time.time() >= deadline:
                    print("[TTS] audio stream still open — given up", flush=True)
                    break
                continue
            if kind == "data":
                timing.mark("audio")
                yield val
            elif kind == "error":
                errors.append(val)
            else:
                ended += 1
                if owner[0] == val:
                    break                              # the winner is done
        if owner[0] == 1:
            print("[TTS] the second request won", flush=True)
        if owner[0] is None and errors:
            raise errors[0]

    def _steady(self, text, kwargs):
        """_hedged(), but a take in a man's register is thrown away and asked
        for once more (11 Oct: "her voice sometimes goes weirdly deep, almost a
        man's voice" — the voice model drifts now and then; one cached clip
        sat at 119 Hz against her usual ~195). The first STEADY_SECS of speech
        are held back to check, then everything flows as before."""
        need = HEAD_BYTES
        for attempt in (0, 1):
            head, stream = [], self._hedged(text, kwargs)
            for chunk in stream:
                head.append(chunk)
                if sum(map(len, head)) >= need:
                    break
            pcm = b"".join(head)
            low = pitch(pcm)
            if attempt == 0 and low and low < deep_hz() and not self._cut.is_set():
                print(f"[TTS] deep take ({low:.0f} Hz) — asked again: {text[:40]!r}",
                      flush=True)
                stream.close()
                continue
            fx = tts_fx.Chain(themes.get().get("fx"))      # HAL's robot, Ice's depth
            if pcm:
                yield fx.process(pcm)
            for chunk in stream:
                out = fx.process(chunk)
                if out:
                    yield out
            return

    def _tts_kwargs(self, style):
        kwargs = dict(model=OPENAI_TTS_MODEL, response_format="pcm",
                      speed=speech_speed(), **voice_kwargs(style))
        return kwargs

    def _speak_persistent(self, text, on_audio_start, style=""):
        """speak() through the always-open player (a short line said before
        comes from the cache instead of the cloud)."""
        out = self._out
        self._cut.clear()
        kwargs = self._tts_kwargs(style)
        key = _cache_key(text, kwargs) if len(text) <= CACHE_MAX_CHARS else None
        cached = cache_get(key) if key else None
        if key:
            CACHE_STATS[0 if cached else 1] += 1     # hits, misses (status screen)
        out.begin(on_start=on_audio_start, prebuffer=0.0 if cached else AUDIO_PREBUFFER_SECS,
                  record=True)
        ok = wrote = False
        if cached:
            out.write(cached)
        else:
            try:
                # a take far longer than its words is the voice model rambling
                # (14 Oct: "Hej, hej!" played 4 s of something else, and the
                # family said "stop", "cicho") — cut it off
                limit, got, runaway = int((2.5 + 0.15 * len(text)) * 48000), 0, False
                for chunk in self._steady(text, kwargs):
                    if self._cut.is_set():
                        break
                    got += len(chunk)
                    if got > limit:
                        runaway = True
                        print(f"[TTS] runaway take ({got / 48000:.1f}s for {len(text)} chars) — "
                              f"cut: {text[:40]!r}", flush=True)
                        break
                    out.write(chunk)
                    wrote = True
                ok = not self._cut.is_set() and not runaway
            except Exception as e:
                if not self._cut.is_set():
                    print(f"[TTS] streaming error: {e}")
                    if not wrote:
                        self._say_offline(out)
        played = out.finish(self._cut)
        if not played and on_audio_start:
            on_audio_start()             # never leave the caller waiting
        # (a stream that ended early without an error must not be kept: at
        # least ~0.03 s of audio per character)
        if ok and key and played and len(out.last_utterance) >= len(text) * 1500:
            low = pitch(out.last_utterance[:HEAD_BYTES])
            if not (low and low < deep_hz()):
                self._cache_if_clear(key, text, out.last_utterance)

    def _cache_if_clear(self, key, text, pcm):
        """Keep the take only if it can be heard as the text: short lines now
        and then come out half Slovak ("Súham", "Dobre, začíname deň", "Juž
        presuja chvílka") — 13 of 147 cached clips (11 Oct), each then said
        that way every time. Checked by a transcription in the background
        (after she has spoken: no delay)."""
        def run():
            try:
                import voicecheck
                heard = voicecheck.transcribe(self._client, pcm)
                if voicecheck.sounds_like(text, heard):
                    cache_put(key, pcm)
                else:
                    print(f"[TTS] not cached — heard {heard[:50]!r} for {text[:50]!r}",
                          flush=True)
            except Exception as e:
                print(f"[TTS] cache check failed ({e!r}) — not cached", flush=True)
        threading.Thread(target=run, daemon=True, name="tts-check").start()

    _offline_said = 0.0

    def _say_offline(self, out):
        """The cloud voice failed before a word: a recorded line instead of
        silence (at most once a minute — not after every sentence)."""
        if time.time() - OpenAITTS._offline_said < 60:
            return
        try:
            import sounds
            pcm = sounds.get("offline_done")
        except Exception:
            pcm = None
        if pcm:
            OpenAITTS._offline_said = time.time()
            out.write(pcm)

    def replay_last(self, on_audio_start=None):
        """Play her last answer again from the audio already played. Returns
        False when there is none (or no persistent player)."""
        with self.lock:
            if not self._out or not self._out.last_utterance:
                return False
            self._cut.clear()
            pcm = self._out.last_utterance
            self._out.begin(on_start=on_audio_start, prebuffer=0.0)
            self._out.write(pcm)
            self._out.finish(self._cut)
            return True

    def stop(self):
        """Cut whatever is playing now (called from another thread — a tap on
        the screen). The speaking call then returns as if it had finished."""
        self._cut.set()
        if self._out:
            self._out.cut()
        p = self._player
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def play_pcm(self, pcm, on_audio_start=None):
        """Play a ready 24 kHz s16 mono clip (non-verbal sounds) through the
        same player and sink as speech, with lip sync. Blocks until played."""
        with self.lock:
            if self._raw_cmd is None:
                return
            if self._out:
                self._cut.clear()
                self._out.begin(on_start=on_audio_start, prebuffer=0.0)
                self._out.write(pcm)
                self._out.finish(self._cut)
                return
            self._cut.clear()
            leadin = bytes(int(TTS_LEADIN_SECS * PCM_RATE) * 2)   # the jack pops
            data = leadin + pcm
            envelope.reset()
            envelope.feed(data)
            player = None
            try:
                player = subprocess.Popen(self._raw_cmd, stdin=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL)
                self._player = player
                envelope.start()
                if on_audio_start:
                    on_audio_start()
                player.stdin.write(data)
                player.stdin.close()
                player.wait()
            except Exception as e:
                if not self._cut.is_set():
                    print(f"[TTS] sound playback error: {e}")
                if player and player.poll() is None:
                    player.kill()
            finally:
                self._player = None
                envelope.reset()

    # ── streaming: OpenAI pcm → (python pump) → player(raw stdin) ───────────
    def _speak_streaming(self, text, on_audio_start, style=""):
        player  = None
        started = False
        self._cut.clear()
        try:
            kwargs = dict(model=OPENAI_TTS_MODEL, input=text, response_format="pcm",
                          speed=speech_speed(), **voice_kwargs(style))

            # Prebuffer: hold back the first TTS_PREBUFFER_SECS of audio before
            # the player starts, so a network stutter drains the buffer instead
            # of underrunning the sink (audible as crackle/gaps).
            # Lead-in silence: the Pi's analog output pops when a stream
            # opens; let that happen before the first spoken sample.
            leadin   = bytes(int(TTS_LEADIN_SECS * PCM_RATE) * 2)
            prebuf   = [leadin] if leadin else []
            prebuf_n = 0
            need     = int(TTS_PREBUFFER_SECS * PCM_RATE * 2)   # s16 mono
            envelope.reset()
            if leadin:
                envelope.feed(leadin)

            fx = tts_fx.Chain(themes.get().get("fx"))
            with self._client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                for chunk in map(fx.process, resp.iter_bytes(chunk_size=TTS_READ_BYTES)):
                    if self._cut.is_set():
                        break                      # tapped: stop downloading
                    if not chunk:
                        continue
                    envelope.feed(chunk)
                    if player is None:
                        prebuf.append(chunk)
                        prebuf_n += len(chunk)
                        if prebuf_n < need:
                            continue
                        player = subprocess.Popen(self._raw_cmd, stdin=subprocess.PIPE,
                                                  stderr=subprocess.DEVNULL)
                        self._player = player
                        envelope.start()
                        started = True
                        if on_audio_start:
                            on_audio_start()
                        player.stdin.write(b"".join(prebuf))
                        prebuf = []
                        continue
                    player.stdin.write(chunk)

            if player is None and prebuf and not self._cut.is_set():
                # short reply: under the prebuffer
                player = subprocess.Popen(self._raw_cmd, stdin=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL)
                self._player = player
                envelope.start()
                started = True
                if on_audio_start:
                    on_audio_start()
                player.stdin.write(b"".join(prebuf))

            if player is not None:
                if self._cut.is_set():
                    player.kill()
                else:
                    player.stdin.close()
                player.wait()
            envelope.reset()
        except Exception as e:
            if not self._cut.is_set():
                print(f"[TTS] streaming error: {e}")
            try:
                if player and player.poll() is None:
                    player.kill()
            except Exception:
                pass
        finally:
            self._player = None
            if not started and on_audio_start:
                on_audio_start()   # never leave the caller waiting for sync

    # ── a reply that arrives sentence by sentence ───────────────────────────
    def start_stream(self, sentences, style=""):
        """Start fetching the audio of sentences as they come — no lock, so it
        can begin while something else is still playing (a "hmm" filler held
        the answer's voice request back ~0.5 s, 6 Oct). Returns the queue of
        per-sentence chunk queues for speak_stream(parts=…), or None when
        there is no voice."""
        if self._client is None or self._raw_cmd is None:
            return None
        self._cut.clear()
        kwargs = dict(model=OPENAI_TTS_MODEL, response_format="pcm",
                      speed=speech_speed(), **voice_kwargs(style))

        parts = queue.Queue()        # one chunk queue per sentence, in order

        def fetch(text, q):
            try:
                for chunk in self._steady(text, kwargs):
                    if self._cut.is_set():
                        break
                    q.put(chunk)
            except Exception as e:
                if not self._cut.is_set():
                    print(f"[TTS] streaming error: {e}")
            finally:
                q.put(None)

        def feeder():
            try:
                for text in sentences:
                    if self._cut.is_set():
                        continue             # drain the producer quietly
                    q = queue.Queue()
                    parts.put(q)
                    threading.Thread(target=fetch, args=(text, q),
                                     daemon=True).start()
            finally:
                parts.put(None)

        threading.Thread(target=feeder, daemon=True).start()
        return parts

    def speak_stream(self, sentences, on_audio_start=None, style="", parts=None):
        """Speak sentences as they come (an iterator that blocks until the
        next one is ready). ONE player for the whole reply; each sentence's
        audio is fetched in its own thread the moment the sentence exists, so
        sentence 2 downloads while sentence 1 plays. If the next audio is not
        there yet, short silence keeps the player fed — an underrun would
        crackle — and that shows up as a natural pause. parts: already
        started with start_stream()."""
        with self.lock:
            if self._client is None or self._raw_cmd is None:
                for _ in sentences:
                    pass
                if on_audio_start:
                    on_audio_start()
                return
            if parts is None:
                parts = self.start_stream(sentences, style)

            if self._out:
                # the persistent player fills any wait with silence itself
                out = self._out
                out.begin(on_start=on_audio_start, prebuffer=AUDIO_PREBUFFER_SECS,
                          record=True)

                def take(qq):
                    """The next item, or None once she is cut off — a blocking
                    get() outlived a touch on 10 Oct (stuck "speaking")."""
                    while not self._cut.is_set():
                        try:
                            return qq.get(timeout=0.2)
                        except queue.Empty:
                            continue
                    return None
                while not self._cut.is_set():
                    q = take(parts)
                    if q is None:
                        break
                    while not self._cut.is_set():
                        chunk = take(q)
                        if chunk is None:
                            break
                        out.write(chunk)
                if not out.finish(self._cut) and on_audio_start:
                    on_audio_start()
                return

            leadin  = bytes(int(TTS_LEADIN_SECS * PCM_RATE) * 2)
            need    = int(TTS_STREAM_PREBUFFER_SECS * PCM_RATE * 2)
            gap     = bytes(int(0.05 * PCM_RATE) * 2)
            prebuf  = [leadin] if leadin else []
            player  = None
            started = False
            written = 0                  # bytes handed to the player
            t0      = 0.0
            envelope.reset()

            def start_player():
                nonlocal player, started, t0, written
                player = subprocess.Popen(self._raw_cmd, stdin=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL)
                self._player = player
                data = b"".join(prebuf)
                for c in prebuf:
                    envelope.feed(c)
                envelope.start()
                t0, started = time.time(), True
                if on_audio_start:
                    on_audio_start()
                player.stdin.write(data)
                written = len(data)
                prebuf.clear()

            def write(chunk):
                nonlocal written
                if player is None:
                    prebuf.append(chunk)
                    if sum(len(c) for c in prebuf) >= need:
                        start_player()
                    return
                envelope.feed(chunk)
                player.stdin.write(chunk)
                written += len(chunk)

            def get(q):
                """Next item of q; while waiting, keep a started player fed."""
                while True:
                    try:
                        return q.get(timeout=0.03)
                    except queue.Empty:
                        if self._cut.is_set():
                            return None
                        if player is not None:
                            ahead = written / (PCM_RATE * 2) - (time.time() - t0)
                            if ahead < 0.12:
                                write(gap)

            try:
                while not self._cut.is_set():
                    q = get(parts)
                    if q is None:
                        break
                    while not self._cut.is_set():
                        chunk = get(q)
                        if chunk is None:
                            break
                        write(chunk)
                if player is None and prebuf and not self._cut.is_set():
                    if sum(len(c) for c in prebuf) > len(leadin):
                        start_player()           # short reply: under the prebuffer
                if player is not None:
                    if self._cut.is_set():
                        player.kill()
                    else:
                        player.stdin.close()
                    player.wait()
            except Exception as e:
                if not self._cut.is_set():
                    print(f"[TTS] stream playback error: {e}")
                if player is not None and player.poll() is None:
                    player.kill()
            finally:
                self._player = None
                envelope.reset()
                if not started and on_audio_start:
                    on_audio_start()


tts = OpenAITTS()
