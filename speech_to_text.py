# speech_to_text.py
"""
speech_to_text.py — Vosk gating/endpointing + OpenAI cloud transcription.

Vosk (small local model) runs on every audio block and does the cheap, always-on
work: adaptive energy gate, wake-word spotting, utterance endpointing and
confidence-based noise rejection. Once an utterance passes those gates, the
buffered 16 kHz audio of that utterance is sent to OpenAI (CLOUD_STT_MODEL)
and the cloud transcript replaces Vosk's text — far better accuracy, and
Polish/English mixed speech is auto-detected. If the cloud call fails, Vosk's
own text is used so Luna still answers offline-ish.

Improvements over the old version:
  • Persistent input stream (opened once, not per-listen) — lower latency,
    no device re-open glitches between turns.
  • Auto-detects the mic's native sample rate and resamples to 16 kHz for
    Vosk with numpy interpolation — works with 16k/32k/44.1k/48k mics.
  • Graceful "microphone not found" handling: Luna keeps running (face,
    vision) and retries the mic every 5 seconds instead of crashing.
  • Multiple wake words (WAKE_WORDS in config), matched on word boundaries.
  • Respects state.mic_unblock_time — never listens while Luna speaks.
"""

import io
import os
import re
import queue
import json
import subprocess
import time
import wave
import difflib
import threading
import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer

from shared_state import state
from config import (
    WAKE_WORDS,
    AUDIO_INPUT_DEVICE,
    VOSK_MODEL_PATH,
    MIC_SAMPLE_RATE,
    VOSK_SAMPLE_RATE,
    CONVO_TIMEOUT,
    CONVO_GRACE,
    POST_SPEAK_DELAY,
    DOUBLE_FLUSH,
    MIC_GAIN,
    MIC_ENERGY_THRESHOLD,
    MIC_GATE_FACTOR,
    MIC_GATE_MAX,
    STT_CONFIDENCE_THRESHOLD,
    STT_MIN_UTTERANCE_CHARS,
    STT_DEBUG_AUDIO,
    WAKE_CONFIDENCE_THRESHOLD,
    WAKE_FUZZY_RATIO,
    REQUIRE_FACE_TO_TALK,
    FACE_RECENT_SECS,
    CLOUD_STT,
    CLOUD_STT_MODEL,
    CLOUD_STT_LANGUAGE,
    CLOUD_STT_PROMPT,
    CLOUD_STT_TIMEOUT,
    CLOUD_STT_MAX_SECS,
    STT_END_SILENCE,
    STT_END_SILENCE_SHORT,
    BARGE_IN,
    STT_SAVE_UTTERANCES,
    CLOUD_WAKE_CHECK,
    CLOUD_WAKE_MIN_INTERVAL,
    CLOUD_WAKE_MAX_PER_HOUR,
    OPENAI_API_KEY,
)

_model = Model(VOSK_MODEL_PATH)
_q     = queue.Queue(maxsize=50)   # bounded — audio can't pile up unbounded

_mic_rate     = None    # actual sample rate the stream runs at
_mic_ok       = False
_stream       = None
_help_printed = False

# Sentinel returned by listen() when a wake word was heard with no question
# attached ("Luna!") — main.py answers with a short acknowledgement.
WAKE_ACK = "__WAKE_ACK__"


# ── Device + sample rate detection ────────────────────────────────────────────

def _resolve_input_device(spec):
    """AUDIO_INPUT_DEVICE may be an index or a case-insensitive substring of
    the device name (LUNA_MIC=C270). Returns an index or None."""
    if spec is None or isinstance(spec, int):
        return spec
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and spec.lower() in dev["name"].lower():
            return i
    print(f"[STT] No input device matching {spec!r} — falling back to auto-detect")
    return None


def _pick_input_device():
    """Return (device_index_or_None, sample_rate) or (None, None) if no mic."""
    wanted = _resolve_input_device(AUDIO_INPUT_DEVICE)
    if wanted is not None:
        try:
            dev = sd.query_devices(wanted)
            if dev["max_input_channels"] > 0:
                rate = MIC_SAMPLE_RATE or int(dev["default_samplerate"])
                print(f"[STT] Using configured device {wanted}: "
                      f"{dev['name']} @ {rate} Hz")
                return wanted, rate
            print(f"[STT] Configured device {wanted} has no "
                  f"input channels — falling back to auto-detect")
        except Exception as e:
            print(f"[STT] Configured device {wanted} error: {e} "
                  f"— falling back to auto-detect")

    # auto-detect: prefer the system default input, then any input device
    candidates = []
    try:
        default_in = sd.default.device[0]
        if default_in is not None and default_in >= 0:
            candidates.append(default_in)
    except Exception:
        pass

    try:
        devices = sd.query_devices()
    except Exception as e:
        print(f"[STT] Could not query audio devices: {e}")
        return None, None

    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0 and i not in candidates:
            candidates.append(i)

    for i in candidates:
        try:
            dev  = sd.query_devices(i)
            rate = MIC_SAMPLE_RATE or int(dev["default_samplerate"])
            # verify the device actually accepts this configuration
            sd.check_input_settings(device=i, samplerate=rate,
                                    channels=1, dtype="int16")
            print(f"[STT] Auto-detected input device {i}: "
                  f"{dev['name']} @ {rate} Hz")
            return i, rate
        except Exception:
            # try the device's own default rate before giving up on it
            try:
                dev  = sd.query_devices(i)
                rate = int(dev["default_samplerate"])
                sd.check_input_settings(device=i, samplerate=rate,
                                        channels=1, dtype="int16")
                print(f"[STT] Auto-detected input device {i}: "
                      f"{dev['name']} @ {rate} Hz (device default)")
                return i, rate
            except Exception:
                continue

    return None, None


def _print_mic_help():
    global _help_printed
    if _help_printed:
        return
    _help_printed = True
    print("=" * 60)
    print("[STT] NO MICROPHONE FOUND — voice input disabled.")
    print("[STT] Luna keeps running (face + vision).")
    print("[STT] Will retry the microphone every 5 seconds.")
    print("[STT] To fix, see the Troubleshooting section in README.md:")
    print("[STT]   python3 -c \"import sounddevice as sd; print(sd.query_devices())\"")
    print("[STT]   then set AUDIO_INPUT_DEVICE in config.py")
    print("=" * 60)


# ── Persistent stream (background thread) ─────────────────────────────────────

_bq = queue.Queue(maxsize=100)    # her speech time: blocks for bargein.py
_blocked = [False]


def _callback(indata, frames, time_info, status):
    data = bytes(indata)
    # while she speaks (and a moment after: the echo) the listener gets nothing
    # — it used to collect it and throw it away later, along with the first
    # words said right after her (6 Oct); her speech time goes to barge-in
    speaking = state.speaking
    if speaking or time.time() < state.mic_unblock_time:
        if not _blocked[0]:
            _blocked[0] = True
            _flush_queue()                 # what was before her speech is stale
        if speaking and BARGE_IN:
            try:
                _bq.put_nowait(data)
            except queue.Full:
                pass
        return
    _blocked[0] = False
    try:
        _q.put_nowait(data)
    except queue.Full:
        pass   # drop oldest-style: consumer is behind, losing a block is fine


def _barge_loop():
    """"stop!" / "Luna!" while she speaks: she stops and listens (bargein.py)."""
    det, was = None, False
    while True:
        data = _bq.get()
        try:
            if not state.speaking:
                if was and det is not None:
                    print(f"[barge] her voice in the mic: median level {det.echo_level():.0f}",
                          flush=True)
                    det.reset()
                was = False
                continue
            was = True
            if det is None:                  # (imported late: not at module import)
                import bargein
                det = bargein.Detector(_model, VOSK_SAMPLE_RATE)
            data = _resample_to_16k(data)
            if not data:
                continue
            import text_to_speech
            word = det.feed(_apply_gain(data), text_to_speech.current_text(), _energy_gate())
            if word and BARGE_IN == "log":
                det.reset()
                print(f"[barge] (log only) would stop on {word!r}", flush=True)
            elif word:
                det.reset()
                text_to_speech.stop_speaking(who=f"voice ({word!r})")
                with state.lock:               # listen at once, no "Luna" needed
                    state.conversation_active = True
                    state.last_activity_time = time.time()
                    state.mic_unblock_time = time.time()
        except Exception as e:
            print(f"[barge] error: {e}", flush=True)


if BARGE_IN:
    threading.Thread(target=_barge_loop, daemon=True, name="barge-in").start()


def _pw_record(node):
    """LUNA_MIC=pw:<node>: the microphone through PipeWire (pw-record) — e.g.
    the echo-cancelled source of pi/60-luna-echo-cancel.conf, which the plain
    ALSA stream can't reach. Blocks while the recorder runs."""
    global _mic_ok, _mic_rate
    rate = VOSK_SAMPLE_RATE
    cmd = ["pw-record", "--raw", "--target", node, "--rate", str(rate), "--channels", "1",
           "--format", "s16", "--latency", "100ms", "-"]   # (50 ms: a 800-sample
    # quantum next to the AEC nodes' 1024 — xruns; 100 ms ran clean in the trial)
    def die_with_luna():
        # if Luna exits, the recorder must too: on 7 Oct a leftover pw-record
        # (its node gone) fell back to the webcam mic, PipeWire held it, and
        # the next Luna found no microphone at all
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").prctl(1, 9)        # PR_SET_PDEATHSIG, SIGKILL
        except Exception:
            pass
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                preexec_fn=die_with_luna)
    except Exception as e:
        print(f"[STT] pw-record failed to start ({e}) — retrying in 5s", flush=True)
        time.sleep(5.0)
        return
    _mic_rate, _mic_ok = rate, True
    with state.lock:
        state.mic_ok = True
    print(f"[STT] Microphone stream running @ {rate} Hz (PipeWire node {node})", flush=True)
    block = int(rate * 0.25) * 2                    # 250 ms, like the ALSA stream
    try:
        while True:
            data = proc.stdout.read(block)
            if not data:
                break
            _callback(data, len(data) // 2, None, None)
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        _mic_ok = False
        with state.lock:
            state.mic_ok = False
        print("[STT] pw-record stopped — retrying in 5s", flush=True)
        time.sleep(5.0)


def _stream_keeper():
    """Keeps a mic stream open forever; retries every 5 s if the mic vanishes."""
    global _stream, _mic_ok, _mic_rate, _help_printed

    while True:
        if isinstance(AUDIO_INPUT_DEVICE, str) and AUDIO_INPUT_DEVICE.startswith("pw:"):
            _pw_record(AUDIO_INPUT_DEVICE[3:])
            continue
        if _mic_ok:
            time.sleep(1.0)
            continue

        device, rate = _pick_input_device()
        if device is None and rate is None:
            _print_mic_help()
            with state.lock:
                state.mic_ok = False
            time.sleep(5.0)
            continue

        try:
            stream = sd.RawInputStream(
                samplerate=rate,
                blocksize=int(rate * 0.25),   # 250 ms blocks
                dtype="int16",
                channels=1,
                callback=_callback,
                device=device,
            )
            stream.start()
            _stream       = stream
            _mic_rate     = rate
            _mic_ok       = True
            _help_printed = False
            with state.lock:
                state.mic_ok = True
            print(f"[STT] Microphone stream running @ {rate} Hz")
        except Exception as e:
            print(f"[STT] Could not open microphone: {e} — retrying in 5s")
            _print_mic_help()
            with state.lock:
                state.mic_ok = False
            time.sleep(5.0)


threading.Thread(target=_stream_keeper, daemon=True, name="mic").start()


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _resample_to_16k(raw_bytes):
    """Resample int16 mono audio from _mic_rate to VOSK_SAMPLE_RATE."""
    audio = np.frombuffer(raw_bytes, dtype=np.int16)
    if _mic_rate == VOSK_SAMPLE_RATE or _mic_rate is None:
        return raw_bytes
    ratio   = VOSK_SAMPLE_RATE / _mic_rate
    n_out   = int(len(audio) * ratio)
    if n_out == 0:
        return b""
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out,      endpoint=False)
    resampled = np.interp(x_new, x_old, audio).astype(np.int16)
    return resampled.tobytes()


def _apply_gain(raw_bytes):
    """Software mic gain (int16, clipped)."""
    if MIC_GAIN == 1.0:
        return raw_bytes
    a = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) * MIC_GAIN
    return np.clip(a, -32768, 32767).astype(np.int16).tobytes()


def _block_rms(raw_bytes):
    """RMS loudness of an int16 audio block (0–32767 scale)."""
    audio = np.frombuffer(raw_bytes, dtype=np.int16)
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


# ── Adaptive noise floor ──────────────────────────────────────────────────────
# Tracks ambient room loudness so the energy gate follows the environment:
# rises fast when the room gets quieter, creeps up slowly through loud stretches
# (so bursts of real speech barely move it, but a persistently noisy room lifts
# the gate above its noise). Classic asymmetric EMA.
_noise_floor = 150.0


def _update_noise_floor(rms):
    global _noise_floor
    alpha = 0.10 if rms < _noise_floor else 0.02
    _noise_floor += alpha * (rms - _noise_floor)


def _energy_gate():
    """Current RMS gate: noise_floor × factor, clamped to [threshold, max]."""
    return min(max(MIC_ENERGY_THRESHOLD, _noise_floor * MIC_GATE_FACTOR),
               MIC_GATE_MAX)


def _avg_confidence(result):
    """Mean Vosk per-word confidence for a final result (1.0 if unavailable)."""
    words = result.get("result", [])
    if not words:
        return 1.0   # no per-word info — don't reject on confidence alone
    return sum(w.get("conf", 1.0) for w in words) / len(words)


def _flush_queue():
    while True:
        try:
            _q.get_nowait()
        except queue.Empty:
            break


def _find_wake_word(words):
    """Locate a wake word/phrase in the token list.

    Returns (start_index, n_tokens, exact) or None. Longest wake phrase is
    tried first, so "hey luna ..." strips the whole phrase instead of leaving
    a stray "hey" in the question. If no exact match, single-word wake words
    (≥ 4 chars) are matched fuzzily so Vosk near-misses on poor capture
    (e.g. "lunar" for "luna") still summon her — the caller applies a stricter
    confidence bar to fuzzy hits so this never fires from noise."""
    for wake in sorted(WAKE_WORDS, key=lambda w: -len(w.split())):
        wake_parts = wake.split()
        n = len(wake_parts)
        for i in range(len(words) - n + 1):
            if words[i:i + n] == wake_parts:
                return i, n, True

    for wake in WAKE_WORDS:
        if " " in wake or len(wake) < 4:
            continue
        for i, w in enumerate(words):
            if (len(w) >= 4 and
                    difflib.SequenceMatcher(None, w, wake).ratio()
                    >= WAKE_FUZZY_RATIO):
                return i, 1, False
    return None


def _wake_confidence(result, words, start, n):
    """Mean Vosk confidence of just the wake tokens (1.0 if unavailable)."""
    infos = result.get("result", [])
    if len(infos) != len(words):   # tokenisation mismatch — don't guess
        return 1.0
    confs = [w.get("conf", 1.0) for w in infos[start:start + n]]
    return sum(confs) / len(confs) if confs else 1.0


# ── Cloud transcription (OpenAI) ──────────────────────────────────────────────
_cloud = None
if CLOUD_STT and OPENAI_API_KEY:
    from openai import OpenAI
    _cloud = OpenAI(api_key=OPENAI_API_KEY, timeout=CLOUD_STT_TIMEOUT, max_retries=0)
    print(f"[STT] Cloud transcription: {CLOUD_STT_MODEL} "
          f"({CLOUD_STT_LANGUAGE or 'auto language'})")
elif CLOUD_STT:
    print("[STT] CLOUD_STT enabled but no OPENAI_API_KEY — using Vosk text only")


def _wav_bytes(pcm16k):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(VOSK_SAMPLE_RATE)
        w.writeframes(pcm16k)
    buf.seek(0)
    buf.name = "utterance.wav"   # the SDK needs a filename to pick the MIME type
    return buf


# ── Speculative transcription ────────────────────────────────────────────────
# The utterance ends after STT_END_SILENCE of silence, and only then went to
# the cloud (~0.9 s). Now, once SPEC_AFTER of that silence has passed (and the
# words may be for her), the audio so far is sent at once; if nothing more is
# said it IS the utterance, and the answer is already on its way — about
# 0.3 s sooner (6 Oct: "more snappy"). Speech that goes on cancels it.
SPEC_AFTER = 0.3
_spec_lock = threading.Lock()
_spec = None          # {"pcm": bytes, "done": Event, "result": ...} or None


def short_lang(words):
    """"pl" for one or two words: there the cloud's language guess tips over
    ("Nie." → "Me.", "makaron" → "Макарон.", 7 Oct); longer speech keeps the
    automatic guess, which English side talk relies on."""
    return "pl" if 0 < len(words) <= 2 and not CLOUD_STT_LANGUAGE else None


def _speculate(pcm16k, lang=None):
    global _spec
    job = {"pcm": pcm16k, "done": threading.Event(), "result": None}
    with _spec_lock:
        _spec = job

    def run():
        try:
            job["result"] = _cloud_transcribe_now(pcm16k, lang)
        finally:
            job["done"].set()
    threading.Thread(target=run, daemon=True, name="stt-spec").start()


def _spec_cancel():
    global _spec
    with _spec_lock:
        _spec = None


def _spec_take(pcm16k):
    """The speculative result for this utterance, if it was started on the
    same audio (the utterance only added silence since); else None."""
    global _spec
    with _spec_lock:
        job, _spec = _spec, None
    if not job or not pcm16k.startswith(job["pcm"]):
        return None
    if not job["done"].wait(12):
        return None
    return job


def _cloud_transcribe(pcm16k, lang=None):
    """Transcribe an utterance — from the speculative request when one was
    started on this audio (see SPEC_AFTER), else now."""
    job = _spec_take(pcm16k) if pcm16k else None
    if job is not None:
        print(f"[STT] speculative transcript used ({len(pcm16k) - len(job['pcm'])} "
              "bytes of silence later)", flush=True)
        return job["result"]
    return _cloud_transcribe_now(pcm16k, lang)


STT_HEDGE_AFTER = 1.8    # no transcript yet: the same request again


def _stt_request(pcm16k, kwargs):
    """One transcription, hedged: 89 % come back within 1.5 s, but one in
    twenty took 2–5 s (6 Oct) — and with a slow model on top, that is the
    "she hangs mid-conversation" silence. Not back after STT_HEDGE_AFTER (or
    failed at once) → the same request again; the first answer wins. Raises
    when no request succeeded."""
    q = queue.Queue()

    def attempt():
        try:
            q.put((True, _cloud.audio.transcriptions.create(
                **dict(kwargs, file=_wav_bytes(pcm16k)))))
        except Exception as e:
            q.put((False, e))

    def start():
        threading.Thread(target=attempt, daemon=True, name="stt-req").start()

    start()
    started, failed, last_err = 1, 0, None
    hedge_at = time.time() + STT_HEDGE_AFTER
    deadline = time.time() + CLOUD_STT_TIMEOUT + 1
    while True:
        wait = (hedge_at if started == 1 else deadline) - time.time()
        try:
            ok, val = q.get(timeout=max(0.0, wait))
        except queue.Empty:
            if started == 1:
                print(f"[STT] no transcript after {STT_HEDGE_AFTER:.1f}s — asking again",
                      flush=True)
                start()
                started = 2
                continue
            raise TimeoutError("no transcript") from last_err
        if ok:
            return val
        failed, last_err = failed + 1, val
        if started == 1:                  # failed at once: one more try
            start()
            started = 2
        elif failed >= started:
            raise last_err


def _cloud_transcribe_now(pcm16k, lang=None):
    """Transcribe an utterance (16 kHz int16 mono bytes).

    Returns the text, "" when the cloud heard no speech, or None when the
    cloud could not be asked (no key, network, timeout). The difference
    matters: "" means Vosk's guess was noise and must be dropped, None means
    Vosk's guess is the best we have."""
    if _cloud is None or not pcm16k:
        return None
    try:
        t0 = time.time()
        kwargs = dict(model=CLOUD_STT_MODEL, file=_wav_bytes(pcm16k),
                      response_format="text")
        if CLOUD_STT_LANGUAGE or lang:
            kwargs["language"] = CLOUD_STT_LANGUAGE or lang
        if CLOUD_STT_PROMPT:
            kwargs["prompt"] = stt_prompt()
        r = _stt_request(pcm16k, kwargs)
        text = (r if isinstance(r, str) else getattr(r, "text", "")).strip()
        if STT_DEBUG_AUDIO:
            print(f"[STT] cloud ({time.time() - t0:.1f}s): \"{text}\"")
        if foreign_script(text) and "language" not in kwargs:
            # auto-detect heard Russian in mumbled Polish ("Лунавон шламка.")
            kwargs["language"] = "pl"
            kwargs["file"] = _wav_bytes(pcm16k)
            r = _cloud.audio.transcriptions.create(**kwargs)
            text = (r if isinstance(r, str) else getattr(r, "text", "")).strip()
            print(f"[STT] cloud again as Polish: \"{text}\"", flush=True)
            if foreign_script(text):
                return None                  # Vosk's guess is the best we have
        if _is_prompt_echo(text):
            print("[STT] cloud echoed its prompt — treating as no speech")
            return ""
        return text
    except Exception as e:
        print(f"[STT] cloud transcription failed ({e}) — using Vosk text")
        return None


def stt_prompt():
    """The transcriber's hint, with the household's names (faces.py), so
    "Mai", "Emilko" come out spelled as they are."""
    try:
        import faces
        names = faces.names()
    except Exception:
        names = []
    return CLOUD_STT_PROMPT + (f" Domownicy: {', '.join(names)}." if names else "")


# Short commands Vosk hears reliably: when it is sure (FAST_CONF), the cloud
# round trip (~0.8 s) is skipped — "ciszej" acts at once. Only exact phrases:
# anything else, or a less sure Vosk, goes through the cloud as before.
FAST_CONF = 0.95
FAST_COMMANDS = {
    "ciszej", "głośniej", "która godzina", "która jest godzina", "jaki dziś dzień",
    "powtórz", "dalej", "koniec", "stop", "wyłącz radio", "włącz radio",
    "następna stacja", "zmień stację", "pokaż zegar", "dobranoc", "wyłącz lampkę",
    "włącz lampkę", "wyłącz szum", "mów wolniej", "mów szybciej", "mów ciszej",
    "mów głośniej", "drzemka", "jeszcze pięć minut", "wyłącz minutnik", "jeszcze raz",
    "pokaż plan dnia", "pokaż listę zakupów", "gotowe", "wyłącz napisy", "włącz napisy",
}
# A lone "Nie." comes back from the cloud as "Me." now and then (its language
# guess tips to English on one short word — 7 Oct, gpt-transcribe). Short
# answers still go through the cloud (Vosk, "sure" of "tak"/"nie", disagreed
# with it 13 times out of 22 — background talk, English, cut sentences); only
# these known mishearings of a "nie" Vosk was sure of are put right.
_NIE_MISHEARD = {"me", "ni", "nee", "knee", "nay", "nye", "nie"}


def fix_lone_nie(cloud, vosk_text, conf):
    """"Me." → "Nie." when Vosk heard exactly "nie" and was sure of it."""
    word = re.sub(r"[^\w]", "", (cloud or "").lower())
    if (vosk_text.strip().lower() == "nie" and conf >= FAST_CONF
            and len((cloud or "").split()) == 1 and word in _NIE_MISHEARD and word != "nie"):
        print(f"[STT] cloud heard {cloud!r} for Vosk's sure \"nie\" — using \"Nie.\"", flush=True)
        return "Nie."
    return cloud


def fast_command(text, conf):
    """The text itself when it is a short command Vosk was sure of, else None."""
    t = " ".join(text.lower().split())
    if conf < FAST_CONF or t not in FAST_COMMANDS:
        return None
    try:
        import messages
        import voicefx
        if messages.armed() or voicefx.armed() or messages_armed():
            return None                            # its audio / words are what counts
    except Exception:
        pass
    return t


_EN_WORDS = {"the", "and", "is", "are", "it", "to", "of", "we", "you", "that", "this", "if",
             "so", "do", "be", "on", "in", "for", "with", "there", "they", "what", "have",
             "just", "then", "need", "want", "can", "will", "not", "yeah", "basically", "like"}


def english_side_talk(text):
    """An English sentence with no "Luna" in it, while she isn't translating:
    the family speaks Polish to her, so it is someone's call or a video."""
    words = re.findall(r"[a-ząćęłńóśźż']+", text.lower())
    if len(words) < 3 or any(w in ("luna", "luno") for w in words):
        return False
    if re.search(r"[ąćęłńóśźż]", text.lower()):
        return False
    try:
        import brain
        if brain.translator():
            return False                       # interpreting: English is expected
    except Exception:
        pass
    return sum(w in _EN_WORDS for w in words) >= max(2, len(words) // 4)


_side = []                             # times of sentences not said to her


def note_side_speech(now=None):
    now = now or time.time()
    _side.append(now)
    del _side[:-20]


def people_talking(now=None, window=120, count=4):
    """Several sentences in the last two minutes that weren't for her: a call,
    or people talking to each other — no time for an unprompted hello."""
    now = now or time.time()
    return sum(1 for t in _side if now - t < window) >= count


def messages_armed():
    """A voice message is being recorded, or a child reads aloud
    (reading.py): every sentence counts as it is — no holding, no filters."""
    try:
        import messages
        import reading
        return messages.armed() or reading.armed()
    except Exception:
        return False


def foreign_script(text):
    """Letters outside the Latin script (Cyrillic, Greek, CJK…) — nobody here
    speaks those; it is the transcriber guessing the language wrong."""
    return any(c.isalpha() and ord(c) > 0x24F for c in text or "")


def _words(s):
    return re.findall(r"\w+", s.lower())


def _is_prompt_echo(text):
    """On audio with no words the transcriber sometimes returns its own
    prompt ("Rozmowa po polsku z małym robotem…"). Three or more words lifted
    verbatim from the prompt are that, not something anyone said; a lone
    "Luna" is kept."""
    if not CLOUD_STT_PROMPT or not text:
        return False
    heard, prompt = _words(text), _words(stt_prompt())
    if len(heard) < 3:
        return False
    sm = difflib.SequenceMatcher(None, heard, prompt, autojunk=False)
    run = sm.find_longest_match(0, len(heard), 0, len(prompt)).size
    return run >= 3 and run >= 0.6 * len(heard)


# Wake words as they appear in a CLOUD transcript. Fuzzy matching is only for
# Vosk's mishearings; on correctly spelled text it ate real words ("lina",
# "luka", "lupa" are 0.75 similar to "luna") and flattened the sentence to
# lowercase with no punctuation, losing the question mark the LLM uses.
_WAKE_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(w) for w in
                           sorted(WAKE_WORDS, key=len, reverse=True))
    + r")(?!\w)", re.IGNORECASE)


def _cloud_has_wake(cloud_text):
    return bool(_WAKE_RE.search(cloud_text or ""))


def _strip_wake_from_cloud(cloud_text):
    """Remove the first wake word from the cloud transcript, keeping its
    casing and punctuation: "Luna, która godzina?" -> "Która godzina?",
    "Co to jest, Luno?" -> "Co to jest?", "Luna." -> ""."""
    m = _WAKE_RE.search(cloud_text)
    if m is None:
        return cloud_text
    before = cloud_text[:m.start()].rstrip(" ,")
    after  = cloud_text[m.end():].lstrip()
    if after[:1] in (",", ":", ";", "-") or (not before and after[:1] in (".", "!", "?")):
        after = after[1:].lstrip()          # the comma after "Luna"
    if not before:
        out = after
    elif not after or after[:1] in ".!?":
        out = before + after                # "..., Luno?" keeps its "?"
    else:
        out = before + " " + after
    out = out.strip()
    return out[:1].upper() + out[1:]


_last_cloud_wake_check = 0.0


_wake_checks = []                      # times of recent cloud wake checks
last_utterance_pcm = b""               # the audio of the last answered utterance
# a sentence the transcriber marked as cut off ("…żeby to wyk...") — the
# speaker only paused: wait HELD_SECS for the rest and answer the two as one
_held = None                           # (text, time)
HELD_SECS = 4.0          # (was 2.5: "No więc ja słyszałem, że są takie
                         # mikrofony..." got answered while Andrzej was thinking)


def cut_off(text):
    """The cloud ends a transcript with "..." when the audio stops mid-word."""
    return bool(text) and bool(re.search(r"(?:\.\.\.|…)\s*$", text))


def join_held(text):
    """The held first half + this one ("Zrób przyn..." + "przynajmniej listę")."""
    global _held
    if not _held:
        return text
    first = re.sub(r"(?:\.\.\.|…)\s*$", "", _held[0]).rstrip()
    _held = None
    return f"{first} {text}".strip()
                                       # (a voice message is saved from it)


def _face_invites(words):
    """Someone is in front of her camera right now and said a short sentence:
    worth a cloud look for "Luna" even when Vosk's words look nothing like it
    (6 Oct 18:43: "Luna, w czym możesz pomóc?" → Vosk "woda w czym możesz
    pomóc"). Not during a call or people's own talk — they face her too."""
    if len(words) > 10:
        return False
    with state.lock:
        seen = time.time() - state.last_face_time < 2.0
        muted = time.time() < state.proactive_muted_until    # a call, "cicho"
    return seen and not muted and not people_talking()


def _maybe_wake(words):
    """Worth paying the cloud to look for "Luna" in this? Only when one of
    the first three words sounds a bit like it (people call her at the start)
    or the utterance is very short. On sample TV-like sentences this lets
    2 of 9 through instead of all 9, and every Vosk mishearing of "Luna" we
    tried ("luną", "lona", "una", "łuna")."""
    singles = [w for w in WAKE_WORDS if " " not in w]
    for w in words[:3]:
        if len(w) >= 3 and max(difflib.SequenceMatcher(None, w, k).ratio()
                               for k in singles) >= 0.5:
            return True
    return len(words) <= 2


_en_heard = []                         # times the wake check came back English
_call_until = 0.0
CALL_EN_COUNT, CALL_EN_WINDOW, CALL_PAUSE = 3, 300, 600


def _note_wake_check_result(cloud, now=None):
    """English with no "Luna" three times in five minutes: someone's call or
    video — stop sending the room to the cloud for 10 minutes (each further
    English sentence extends it). 7 Oct 14:29–15:26, Andrzej's English work
    call: 63 transcriptions in an hour, no answer; Vosk's own wake word
    still works meanwhile."""
    global _call_until
    now = now or time.time()
    if not cloud or not english_side_talk(cloud):
        return
    _en_heard.append(now)
    _en_heard[:] = [t for t in _en_heard if now - t < CALL_EN_WINDOW]
    if len(_en_heard) >= CALL_EN_COUNT:
        if now >= _call_until:
            print(f"[STT] English call/video in the room — no cloud wake checks for "
                  f"{CALL_PAUSE // 60} min (Vosk still hears \"Luna\")", flush=True)
        _call_until = now + CALL_PAUSE


def call_pause(now=None):
    return (now or time.time()) < _call_until


def _wake_check_worth(words):
    """Might these (passive-mode) words hold a misheard "Luna"?"""
    if not CLOUD_WAKE_CHECK or _cloud is None or call_pause():
        return False
    return words is None or _maybe_wake(words) or _face_invites(words)


def _wake_budget():
    """One more cloud wake check allowed now? (spends it) — a room with the TV
    on would otherwise send every sentence to the cloud."""
    global _last_cloud_wake_check
    now = time.time()
    if now - _last_cloud_wake_check < CLOUD_WAKE_MIN_INTERVAL:
        return False
    _wake_checks[:] = [t for t in _wake_checks if now - t < 3600]
    if len(_wake_checks) >= CLOUD_WAKE_MAX_PER_HOUR:
        return False
    _wake_checks.append(now)
    _last_cloud_wake_check = now
    return True


_WAKE_EXTRA_WORDS = 3


def _cloud_wake_plausible(cloud, words):
    """A wake found only by the cloud is believed when its sentence is about
    as long as what Vosk heard: the transcriber (primed with "Luna" in its
    prompt) sometimes writes a whole addressed sentence over faint sound —
    7 Oct: Vosk "usa" (conf 0.24) → "Luna, wstań z łóżka, ty zdychasz.";
    "tak tak" → "Luna, pomyślałam, że żyjesz. Tak, tak, żyję."; nobody had
    spoken to her. Real ones match: "ilona która godzina" → "Cześć Luna,
    która godzina?" (26 cloud wakes in the log)."""
    if not words:
        return True
    rest = re.findall(r"\w+", _strip_wake_from_cloud(cloud) or "")
    if len(rest) > len(words) + _WAKE_EXTRA_WORDS:
        print(f"[STT] cloud wake not believed: {cloud!r} over Vosk's "
              f"{' '.join(words)!r} — likely made up", flush=True)
        return False
    return True


def _cloud_wake_check(pcm16k, words=None):
    """Vosk heard speech but no wake word: ask the cloud whether the wake
    word is actually in there. Returns (found, cleaned_text). Rationed: a
    room with the TV on would otherwise send every sentence to the cloud."""
    job = _spec_take(pcm16k) if pcm16k else None
    if job is not None:
        # already transcribed on the pause (Vosk's partial words had her name,
        # its final ones lost it: 6 Oct 18:36 "Luna, jakie stacje radiowe
        # masz?" heard as "no jakie stacje…" — and ignored); free to use
        cloud = job["result"]
        _note_wake_check_result(cloud)
        if not cloud or not _cloud_has_wake(cloud) or not _cloud_wake_plausible(cloud, words):
            return False, None
        return True, _strip_wake_from_cloud(cloud)
    if not _wake_check_worth(words) or not _wake_budget():
        return False, None
    cloud = _cloud_transcribe(pcm16k)
    _note_wake_check_result(cloud)
    if not cloud or not _cloud_has_wake(cloud) or not _cloud_wake_plausible(cloud, words):
        return False, None
    return True, _strip_wake_from_cloud(cloud)


# ── Optional utterance log (review misrecognitions) ─────────────────────────
_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stt_log")


def _save_utterance(pcm16k, vosk_text, cloud_text, final):
    """Keep the audio that was sent and what each recogniser made of it."""
    if not STT_SAVE_UTTERANCES or not pcm16k:
        return
    try:
        os.makedirs(_SAVE_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with open(os.path.join(_SAVE_DIR, stamp + ".wav"), "wb") as f:
            f.write(_wav_bytes(pcm16k).getvalue())
        cloud_txt = "<unreachable>" if cloud_text is None else cloud_text
        with open(os.path.join(_SAVE_DIR, "index.tsv"), "a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{vosk_text}\t{cloud_txt}\t{final}\n")
        wavs = sorted(n for n in os.listdir(_SAVE_DIR) if n.endswith(".wav"))
        for old in wavs[:-STT_SAVE_UTTERANCES]:
            os.remove(os.path.join(_SAVE_DIR, old))
    except OSError as e:
        print(f"[STT] could not save utterance: {e}")


# ── Recognizer — created once, Reset() between turns (cheap on the Pi) ────────
_rec = None


def _get_recognizer():
    global _rec
    if _rec is None:
        _rec = KaldiRecognizer(_model, VOSK_SAMPLE_RATE)
        _rec.SetWords(True)   # emit per-word confidence for the noise gate
    else:
        _rec.Reset()
    return _rec


def _addressed_to_luna():
    """True when the speech we just heard was plausibly directed AT Luna.

    Uses the camera: someone talking to Luna faces her, so a face must have
    been seen within FACE_RECENT_SECS. People chatting with each other in
    front of Luna (any language) usually aren't facing her — their speech is
    ignored instead of answered. Fails open when the camera is unavailable
    (mic-only setups keep working) or the gate is disabled in config."""
    if not REQUIRE_FACE_TO_TALK:
        return True
    with state.lock:
        camera_ok = state.camera_ok
        last_face = state.last_face_time
    if not camera_ok:
        return True
    return (time.time() - last_face) <= FACE_RECENT_SECS


def _started_in_window(t):
    """Did speech beginning at t start inside the last conversation window
    (or just after it)? Never while the radio plays — then every command
    needs "Luna"."""
    with state.lock:
        ended = state.convo_expired_time
        hard = state.convo_closed_hard
    if not ended or hard or time.time() - ended > 60:
        return False
    try:
        import radio
        if radio.playing():
            return False
    except Exception:
        pass
    return t <= ended + CONVO_GRACE


def _muted():
    with state.lock:
        return time.time() < state.mic_muted_until


def _expire_conversation():
    """Conversation window ran out — back to wake-word mode.
    Stamps convo_expired_time so the face can play its subtle 'rest' cue."""
    print(f"[STT] {time.strftime('%H:%M:%S')} Conversation timed out — waiting for wake word")
    with state.lock:
        state.conversation_active = False
        state.convo_expired_time  = time.time()
        state.convo_closed_hard   = False      # timed out: a late start still counts
        state.listening           = False


# ── Main listen ───────────────────────────────────────────────────────────────

def listen():
    """
    Waits until the mic is allowed (Luna not speaking, echo-guard passed),
    then listens. In conversation mode no wake word is needed until timeout.
    Returns WAKE_ACK when a wake word was heard alone, the recognised text
    when actionable, "" otherwise.
    """

    # no mic? — don't spin, just idle politely (keeper thread is retrying)
    if not _mic_ok:
        time.sleep(1.0)
        return ""

    # "Luna, nie słuchaj": the audio is thrown away unheard — no Vosk, no cloud
    if _muted():
        _flush_queue()
        with state.lock:
            state.listening = False
        time.sleep(0.5)
        return ""

    # ── Wait until mic is allowed ─────────────────────────────────────────────
    was_blocked = False
    while True:
        with state.lock:
            speaking     = state.speaking
            unblock_time = state.mic_unblock_time
        now = time.time()

        if speaking or now < unblock_time:
            was_blocked = True
            remaining = unblock_time - now
            time.sleep(min(0.1, remaining) if remaining > 0 else 0.05)
            continue
        break

    # nothing to flush or wait for after she spoke: the microphone callback
    # kept her speech (and its echo) out of the queue already

    rec = _get_recognizer()

    # check conversation timeout
    with state.lock:
        active        = state.conversation_active
        last_activity = state.last_activity_time

    if active and (time.time() - last_activity) > CONVO_TIMEOUT:
        _expire_conversation()
        active = False

    # "listening" (blue pulse on the face) means attentive conversation mode;
    # passively waiting for a wake word stays visually idle
    with state.lock:
        state.listening = active
        state.luna_mode = "listening" if active else "idle"

    msg_parts    = []    # Vosk segments of a voice message being recorded
    voiced       = False # real speech heard in the current utterance
    silent_run   = 0.0   # seconds of gated silence since the last speech
    utt_peak_rms = 0.0   # loudest block in the utterance being accumulated
    utt_audio    = []    # raw (ungated) 16 kHz blocks of the current utterance
    utt_bytes    = 0
    utt_max      = int(CLOUD_STT_MAX_SECS * VOSK_SAMPLE_RATE * 2)
    utt_t0       = None  # when the current utterance's speech began
    spec_tried   = False # this pause already sent ahead (see SPEC_AFTER)

    while True:
        try:
            data = _q.get(timeout=0.5)
        except queue.Empty:
            # mic may have vanished mid-listen
            if not _mic_ok:
                with state.lock:
                    state.listening = False
                    state.luna_mode = "idle"
                return ""
            # conversation window can also run out mid-silence
            if active and (time.time() - last_activity) > CONVO_TIMEOUT:
                _expire_conversation()
                active = False
                with state.lock:
                    state.luna_mode = "idle"
            continue

        # if Luna started speaking, abort this listen (mic gets flushed after);
        # and if the conversation was opened from outside (finger held on
        # the screen) restart as an active listen — no wake word needed
        with state.lock:
            if state.speaking:
                state.listening = False
                state.luna_mode = "idle"
                return ""
            if state.conversation_active and not active:
                return ""

        if _muted():                       # muted in the middle of a listen
            return ""
        global _held
        if _held and time.time() - _held[1] > HELD_SECS:
            text, _held = _held[0], None   # nothing more came: answer what there is
            print(f"[STT] no continuation — answering \"{text}\"", flush=True)
            return text
        data = _resample_to_16k(data)
        if not data:
            continue
        data = _apply_gain(data)

        # Energy gate (VAD): silence out ambient-level blocks so Vosk never
        # transcribes background noise into words. The gate adapts to the
        # room's noise floor (see _update_noise_floor) — rising in noisy rooms,
        # falling in quiet ones. Gated blocks are fed as digital silence so
        # utterances still get clean pauses/endpoints.
        rms = _block_rms(data)
        _update_noise_floor(rms)
        utt_peak_rms = max(utt_peak_rms, rms)
        # keep the real audio for the cloud even when the gate silences it
        # for Vosk (a quiet word at the edge of the gate is still a word)
        if utt_bytes < utt_max:
            utt_audio.append(data)
            utt_bytes += len(data)
        gated = rms < _energy_gate()
        if gated:
            data = bytes(len(data))
            silent_run += len(data) / (VOSK_SAMPLE_RATE * 2)
        else:
            if not voiced and utt_t0 is None:
                utt_t0 = time.time() - len(data) / (VOSK_SAMPLE_RATE * 2)
            if silent_run >= SPEC_AFTER and _spec is not None:
                _spec_cancel()                   # they went on: it wasn't the end
            voiced, silent_run, spec_tried = True, 0.0, False

        # Vosk only calls the utterance finished after ~1.05 s of silence
        # (measured). Ours is quicker: STT_END_SILENCE of gated silence after
        # real speech — a third of a second sooner to the answer.
        final = rec.AcceptWaveform(data)
        import messages                  # a voice message may have pauses
        recording = messages.armed()
        end_after = 2.0 if recording else STT_END_SILENCE
        if (voiced and not recording and silent_run >= STT_END_SILENCE
                and silent_run < STT_END_SILENCE_SHORT):
            # one or two words so far: probably the start of a thought
            if len(json.loads(rec.PartialResult()).get("partial", "").split()) <= 2:
                end_after = STT_END_SILENCE_SHORT
        if (voiced and not recording and not final and _cloud is not None
                and silent_run >= SPEC_AFTER and not spec_tried):
            spec_tried = True                    # once per pause
            words = json.loads(rec.PartialResult()).get("partial", "").split()
            if (active or _find_wake_word(words) is not None
                    or (utt_peak_rms >= 2.0 * _energy_gate() and len(words) >= 2
                        and _wake_check_worth(words) and _wake_budget())):
                # (passive: only clear, loud speech — room noise sent ahead ate
                # the 2 s wake budget on 6 Oct 19:00, and "Luna, śpisz?" waited)
                # (the last: the end-of-utterance wake check would ask the
                # cloud anyway — 6 Oct 18:49 "runda jeśli" was "Luna, nie śpij!")
                _speculate(b"".join(utt_audio), short_lang(words) if active else None)
        if final and recording and silent_run < end_after:
            # Vosk thinks you're done (~1 s pause) but a message may go on:
            # keep its text, keep the audio, keep listening
            seg = json.loads(rec.Result()).get("text", "").strip()
            if seg:
                msg_parts.append(seg)
            print(f"[STT] message: pause after {seg!r}, still recording "
                  f"(silence {silent_run:.2f}s)", flush=True)
            final = False
        early = not final and voiced and silent_run >= end_after
        if (final or early) and voiced:
            with state.lock:                 # the speech itself ended this long ago
                state.heard_at = time.time() - silent_run
            import timing
            timing.reset()                   # a new utterance: new stage marks
        if final or early:
            result   = json.loads(rec.FinalResult() if early else rec.Result())
            if msg_parts:                # a recorded message: all its parts
                result = {"text": " ".join(msg_parts + [result.get("text", "")]).strip()}
                msg_parts = []
            voiced, silent_run, spec_tried = False, 0.0, False
            started, utt_t0 = utt_t0, None
            text     = result.get("text", "").strip()
            peak_rms = utt_peak_rms
            utt_peak_rms = 0.0   # reset for the next utterance
            utt_pcm   = b"".join(utt_audio)
            utt_audio = []
            utt_bytes = 0

            with state.lock:
                state.listening  = False
                state.luna_mode  = "processing"
                state.heard_text = text

            if not text:
                # silence chunk — also the spot to notice a timed-out window
                if active and (time.time() - last_activity) > CONVO_TIMEOUT:
                    _expire_conversation()
                    active = False
                with state.lock:
                    state.luna_mode = "idle" if not active else "listening"
                    state.listening = active
                continue   # keep listening — don't restart the whole cycle

            # The window closed while you were thinking — but this sentence
            # began inside it (or within CONVO_GRACE after): still for her.
            if not active and started is not None and _started_in_window(started):
                print(f"[STT] began {started - state.convo_expired_time:+.1f}s from the "
                      "window's end — answering", flush=True)
                active = True
                with state.lock:
                    state.conversation_active = True
                    state.last_activity_time = time.time()

            words   = text.split()
            wake    = _find_wake_word(words)
            cleaned = None

            # A wake word only counts when the wake tokens THEMSELVES were
            # heard confidently — so noise hallucinated as "luna" never wakes
            # her, but a clearly spoken wake word still cuts through a noisy
            # room without needing the rest of the phrase to be clean.
            # Fuzzy (misheard) wake words get a stricter bar than exact ones.
            if wake is not None:
                start, n, exact = wake
                wake_conf = _wake_confidence(result, words, start, n)
                need = (WAKE_CONFIDENCE_THRESHOLD if exact
                        else max(WAKE_CONFIDENCE_THRESHOLD,
                                 STT_CONFIDENCE_THRESHOLD))
                if wake_conf >= need:
                    cleaned = " ".join(words[:start] + words[start + n:]).strip()
                else:
                    if STT_DEBUG_AUDIO:
                        print(f"[STT] Wake ignored (conf {wake_conf:.2f} < "
                              f"{need:.2f}): \"{text}\"")
                    wake = None

            # Noise gates for everything that isn't a confident wake — must
            # look like real, confident, addressed speech before it reaches
            # the brain, so hallucinated noise-words are never answered.
            if cleaned is None:
                conf = _avg_confidence(result)
                if STT_DEBUG_AUDIO:
                    print(f"[STT] heard=\"{text}\" conf={conf:.2f} "
                          f"peak_rms={peak_rms:.0f} gate={_energy_gate():.0f}")
                # (and the rest of a sentence cut off mid-word: 6 Oct 21:52 "…Co
                # napisać, jaki..." + "To jest mikrofon?" — Vosk 0.37, dropped)
                capture = ((messages_armed() or _held is not None)
                           and peak_rms >= 1.5 * _energy_gate())
                if (conf < STT_CONFIDENCE_THRESHOLD
                        or len(text) < STT_MIN_UTTERANCE_CHARS) and not capture:
                    # (a child reading aloud, slowly, scores low with Vosk —
                    # while she listens to reading, loud speech goes to the cloud)
                    # A garbled low-confidence result can still be "Luna!" —
                    # if it was clearly loud speech, let the cloud check it.
                    if not active and peak_rms >= 2.0 * _energy_gate():
                        found, cleaned = _cloud_wake_check(utt_pcm, words)
                        if found:
                            print("[STT] Wake word (cloud) — conversation active")
                            with state.lock:
                                state.conversation_active = True
                                state.last_activity_time  = time.time()
                            if cleaned and cut_off(cleaned) and not messages_armed():
                                # "Hej Luna, jaki jest najlepszy sposób..." — wait for the rest
                                # (6 Oct 21:44: answered at once, "Chyba nie dokończyłeś pytania")
                                _held, active = (cleaned, time.time()), True
                                print(f"[STT] cut off mid-sentence — waiting for the rest: \"{cleaned}\"",
                                      flush=True)
                                with state.lock:
                                    state.luna_mode = "listening"
                                    state.listening = True
                                continue
                            return cleaned if cleaned else WAKE_ACK
                    print(f"[STT] Dropped (noise): \"{text}\" conf={conf:.2f}")
                    with state.lock:
                        state.luna_mode = "listening" if active else "idle"
                        state.listening = active
                    continue

            print(f"[Luna heard] {time.strftime('%H:%M:%S')} {text}")

            if cleaned is not None:
                # Face gate applies to wake words too: "hello" said between
                # two people greeting each other shouldn't wake Luna. Someone
                # summoning her is in front of her camera (gate auto-disables
                # when no camera is available).
                if not _addressed_to_luna():
                    print(f"[STT] Wake ignored (nobody facing me): \"{text}\"")
                    with state.lock:
                        state.luna_mode = "listening" if active else "idle"
                        state.listening = active
                    continue
                fuzzy = wake is not None and not wake[2]
                fuzzy_cloud = None
                if fuzzy:
                    # a near-miss ("ludzie" scores 0.73 against "lunie") must be
                    # confirmed: her name has to be in the real words (6 Oct
                    # 17:54, Maja and a parent rehearsing a poem: "…żeby ludzie
                    # w zgodzie żyli" woke her)
                    fuzzy_cloud = _cloud_transcribe(utt_pcm)
                    if not fuzzy_cloud or not _cloud_has_wake(fuzzy_cloud):
                        print(f"[STT] false wake — \"{text}\" was not her name "
                              f"(cloud: \"{fuzzy_cloud}\")", flush=True)
                        with state.lock:
                            state.luna_mode = "listening" if active else "idle"
                            state.listening = active
                        continue
                print("[STT] Wake word — conversation active")
                with state.lock:
                    state.conversation_active = True
                    state.last_activity_time  = time.time()
                if (cleaned and not fuzzy
                        and fast_command(cleaned, _avg_confidence(result))):
                    print(f"[STT] sure of \"{cleaned}\" — no cloud", flush=True)
                    return cleaned
                if fuzzy:
                    cleaned = _strip_wake_from_cloud(fuzzy_cloud)
                if cleaned:
                    cloud = fuzzy_cloud or _cloud_transcribe(utt_pcm)
                    if cloud and not messages_armed() and english_side_talk(cloud):
                        # Vosk turned an English call into Polish-ish words with
                        # a "luna" in them; the real words have no "Luna" at all
                        # (6 Oct 16:42: "…we need more people on the sprint review")
                        print(f"[STT] false wake — English side talk: \"{cloud}\"", flush=True)
                        with state.lock:
                            state.conversation_active = False
                            state.proactive_muted_until = max(state.proactive_muted_until,
                                                              time.time() + 300)
                            state.luna_mode = "idle"
                            state.listening = False
                        active = False
                        continue
                    if cloud:
                        cleaned = _strip_wake_from_cloud(cloud)
                    elif cloud == "":
                        # the cloud heard no words after "Luna" — whatever
                        # Vosk made of the rest was noise; just answer "Tak?"
                        cleaned = ""
                    _save_utterance(utt_pcm, text, cloud, cleaned or "(wake)")
                if cleaned and cut_off(cleaned) and not messages_armed():
                    _held = (cleaned, time.time())  # "Luna, żeby to wyk..." — the rest
                    active = True                   # comes without "Luna"
                    print(f"[STT] cut off mid-sentence — waiting for the rest: "
                          f"\"{cleaned}\"", flush=True)
                    continue
                return cleaned if cleaned else WAKE_ACK

            if active:
                # Addressed-speech gate: inside the conversation window, only
                # answer speech from someone actually facing Luna — people
                # talking among themselves in the room (any language) are
                # ignored, and their chatter doesn't keep the window open.
                if not _addressed_to_luna():
                    print(f"[STT] Ignored (nobody facing me): \"{text}\"")
                    with state.lock:
                        state.luna_mode = "listening"
                        state.listening = True
                    continue
                fast = fast_command(text, conf)
                if fast:
                    print(f"[STT] sure of \"{fast}\" — no cloud", flush=True)
                    with state.lock:
                        state.last_activity_time = time.time()
                    return fast
                cloud = fix_lone_nie(_cloud_transcribe(utt_pcm, short_lang(text.split())),
                                     text, conf)
                if cloud == "" and conf >= 0.98 and len(text.split()) >= 2:
                    # the cloud returns nothing for short sounds it can't place
                    # ("puk puk"); Vosk was sure of every word — believe it
                    print(f"[STT] cloud heard nothing, Vosk is sure: \"{text}\"", flush=True)
                    cloud = None
                if cloud == "":
                    # The cloud heard no words. Vosk's text is its guess at
                    # noise — answering it is how Luna replied to things
                    # nobody said. Keep listening instead.
                    print(f"[STT] cloud heard no speech — dropping Vosk's \"{text}\"")
                    _save_utterance(utt_pcm, text, cloud, "(dropped)")
                    with state.lock:
                        state.luna_mode = "listening"
                        state.listening = True
                    continue
                if cloud and not messages_armed() and english_side_talk(cloud):
                    # a work call in English next to her ("upload it and then
                    # download it…" got an answer on 5 Oct): not said to her
                    print(f"[STT] English side talk — ignored: \"{cloud}\"", flush=True)
                    with state.lock:                 # a call: no hellos for 5 min
                        state.proactive_muted_until = max(state.proactive_muted_until,
                                                          time.time() + 300)
                        state.luna_mode = "listening"
                        state.listening = True
                    continue
                with state.lock:
                    state.last_activity_time = time.time()
                global last_utterance_pcm
                last_utterance_pcm = utt_pcm
                final = cloud if cloud else text     # None: cloud unreachable
                if _held:
                    final = join_held(final)
                if cut_off(final) and not messages_armed():
                    _held = (final, time.time())
                    print(f"[STT] cut off mid-sentence — waiting for the rest: \"{final}\"",
                          flush=True)
                    with state.lock:
                        state.luna_mode = "listening"
                        state.listening = True
                    continue
                _save_utterance(utt_pcm, text, cloud, final)
                return final

            # Passive mode and Vosk didn't spot the wake word — its small
            # model mishears "Luna" often, so let the cloud have a look.
            found, cleaned = _cloud_wake_check(utt_pcm, words)
            if found:
                print("[STT] Wake word (cloud) — conversation active")
                with state.lock:
                    state.conversation_active = True
                    state.last_activity_time  = time.time()
                if cleaned and cut_off(cleaned) and not messages_armed():
                    # "Hej Luna, jaki jest najlepszy sposób..." — wait for the rest
                    # (6 Oct 21:44: answered at once, "Chyba nie dokończyłeś pytania")
                    _held, active = (cleaned, time.time()), True
                    print(f"[STT] cut off mid-sentence — waiting for the rest: \"{cleaned}\"",
                          flush=True)
                    with state.lock:
                        state.luna_mode = "listening"
                        state.listening = True
                    continue
                return cleaned if cleaned else WAKE_ACK

            note_side_speech()                     # people talking, not to her
            with state.lock:
                state.luna_mode = "idle"
            return ""

        partial = json.loads(rec.PartialResult()).get("partial", "")
        if partial:
            with state.lock:
                state.heard_text = partial
                if active:                       # live captions while you speak
                    state.caption = ("you", partial + "…", time.time() + 3.0)
