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
"""

import json
import os
import queue
import subprocess
import threading
import time

import numpy as np

import settings

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
    TTS_LEADIN_SECS,
    TTS_PLAYER,
    AUDIO_OUTPUT_DEVICE,
    LIPSYNC_FRAME_MS,
    LIPSYNC_RMS_FULL,
)

PCM_RATE = 24000   # fixed by the API for response_format="pcm"

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
        self.t0       = None        # wall-clock time byte 0 hit the player
        self._carry   = b""

    def reset(self):
        with self.lock:
            self.frames = []
            self.t0     = None
            self._carry = b""

    def start(self):
        with self.lock:
            self.t0 = time.time()

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
        with self.lock:
            self.frames.extend(e.tolist())

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
            self._speak_streaming(text, on_audio_start, style)

    def stop(self):
        """Cut whatever is playing now (called from another thread — a tap on
        the screen). The speaking call then returns as if it had finished."""
        self._cut.set()
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
            kwargs = dict(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                          input=text, response_format="pcm",
                          speed=settings.get("tts_speed", OPENAI_TTS_SPEED))
            instructions = "\n".join(x for x in (OPENAI_TTS_INSTRUCTIONS, style) if x)
            if instructions:
                kwargs["instructions"] = instructions

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

            with self._client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                for chunk in resp.iter_bytes(chunk_size=16384):
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
    def speak_stream(self, sentences, on_audio_start=None, style=""):
        """Speak sentences as they come (an iterator that blocks until the
        next one is ready). ONE player for the whole reply; each sentence's
        audio is fetched in its own thread the moment the sentence exists, so
        sentence 2 downloads while sentence 1 plays. If the next audio is not
        there yet, short silence keeps the player fed — an underrun would
        crackle — and that shows up as a natural pause."""
        with self.lock:
            if self._client is None or self._raw_cmd is None:
                for _ in sentences:
                    pass
                if on_audio_start:
                    on_audio_start()
                return
            self._cut.clear()
            kwargs = dict(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                          response_format="pcm",
                          speed=settings.get("tts_speed", OPENAI_TTS_SPEED))
            instructions = "\n".join(x for x in (OPENAI_TTS_INSTRUCTIONS, style) if x)
            if instructions:
                kwargs["instructions"] = instructions

            parts = queue.Queue()        # one chunk queue per sentence, in order

            def fetch(text, q):
                try:
                    with self._client.audio.speech.with_streaming_response.create(
                            input=text, **kwargs) as resp:
                        for chunk in resp.iter_bytes(chunk_size=16384):
                            if self._cut.is_set():
                                break
                            if chunk:
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
