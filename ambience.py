"""
ambience.py — sounds to fall asleep to, made right here.

  "Włącz szum deszczu" / "deszcz"   → soft rain: filtered noise with drops
  "Szum morza" / "fale"              → waves: noise that swells and ebbs
  "Biały szum" / "szum"              → steady pink noise
  "…na 30 minut"                     → goes out after that (default 45 min,
                                       with a 20 s fade)
  "Wyłącz szum"                      → off

No files, no network: numpy makes the sound in 0.1 s blocks and feeds its
own pw-play stream (like radio.py). It ducks while she listens or speaks,
and the radio and the sounds don't play at once.
"""

import re
import subprocess
import threading
import time

import numpy as np

from shared_state import state

RATE = 24000
BLOCK = RATE // 10                     # 0.1 s
GAIN = 0.30                            # quiet: it's for sleeping
DUCK = 0.15
DEFAULT_MINUTES = 45
FADE_SECS = 20

KINDS = {"rain": ("deszcz", "deszczu", "rain"),
         "sea": ("morz", "fal", "ocean", "sea", "waves"),
         "noise": ("biały szum", "bialy szum", "różowy szum", "rozowy szum",
                   "white noise", "szum")}
NAMES = {"rain": "szum deszczu", "sea": "szum morza", "noise": "biały szum"}
_ON = re.compile(r"\b(?:włącz|wlacz|puść|pusc|zagraj|daj)\b|^(?:szum|deszcz|fale)\b")
_OFF = ("wyłącz szum", "wylacz szum", "wyłącz deszcz", "wyłącz morze", "wyłącz fale",
        "stop szum", "koniec szumu", "wyłącz dźwięki", "zatrzymaj szum")

_lock = threading.Lock()
_player = None                          # {"kind", "stop": Event, "until", "proc"}


def _die_with_parent():
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:
        pass


LOOP_SECS = 30


def _shaped_noise(n, power, rng):
    """Noise with a 1/f^power spectrum, made with one FFT. An FFT-made signal
    is periodic, so it loops with no seam (pink: 1, brown: 2)."""
    spec = rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)
    f = np.arange(n // 2 + 1, dtype=float)
    f[0] = 1.0
    x = np.fft.irfft(spec / f ** (power / 2), n)
    return x / (np.abs(x).max() + 1e-9)


class _Gen:
    """Endless sound, block by block, from a 30 s loop made once (cheap: no
    per-sample Python — a filter loop would cost the Pi ~15 % of a core)."""

    def __init__(self, kind):
        self.kind, self.pos, self.t = kind, 0, 0.0
        self.rng = np.random.default_rng()
        n = LOOP_SECS * RATE
        self.loop = _shaped_noise(n, 2.0 if kind == "sea" else 1.0, self.rng) * \
            (0.9 if kind == "sea" else 0.5)
        self.drop = np.exp(-np.arange(160) / 30.0)          # one raindrop's decay

    def block(self):
        n = BLOCK
        idx = (self.pos + np.arange(n)) % len(self.loop)
        self.pos = (self.pos + n) % len(self.loop)
        x = self.loop[idx]
        t = self.t + np.arange(n) / RATE
        self.t += n / RATE
        if self.kind == "sea":
            # waves: a slow swell every ~9.5 s
            x = x * (0.2 + 0.8 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 9.5)) ** 2)
        elif self.kind == "rain":
            # a steady hiss + random drops
            hits = (self.rng.random(n) < 0.004) * self.rng.uniform(0.2, 0.8, n)
            env = np.convolve(hits, self.drop)[:n]
            x = x * 0.6 + env * self.rng.standard_normal(n) * 0.25
        return x


def _ducked():
    with state.lock:
        return state.speaking or state.listening or state.conversation_active


def _play(p):
    try:
        from openai_tts import tts
        sink = tts._sink
    except Exception:
        sink = None
    cmd = ["pw-play", "--raw", f"--rate={RATE}", "--format=s16", "--channels=1",
           "--media-role=Music"] + (["--target", sink] if sink else []) + ["-"]
    out = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           preexec_fn=_die_with_parent)
    p["proc"] = out
    gen, gain, t0 = _Gen(p["kind"]), 0.0, time.time()
    written = 0.0
    try:
        while not p["stop"].is_set():
            now = time.time()
            left = p["until"] - now
            if left <= 0:
                print("[ambience] time is up — off", flush=True)
                break
            target = GAIN * (DUCK if _ducked() else 1.0)
            target *= min(1.0, (now - t0) / 3.0)          # 3 s fade in
            target *= min(1.0, left / FADE_SECS)           # fade out at the end
            new = gain + (target - gain) * 0.3
            x = gen.block() * np.linspace(gain, new, BLOCK)
            gain = new
            out.stdin.write((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
            written += BLOCK / RATE
            ahead = written - (time.time() - t0)
            if ahead > 0.5:                        # real-time pace: the ducking and
                time.sleep(ahead - 0.5)            # the fades follow the clock
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            out.stdin.close()
        except OSError:
            pass
        out.terminate()
        global _player
        with _lock:
            if _player is p:
                _player = None
        with state.lock:
            if state.radio and state.radio.startswith("♪"):
                state.radio = None


def play(kind, minutes=DEFAULT_MINUTES):
    stop()
    try:
        import radio                           # one sound at a time
        radio.stop()
    except Exception:
        pass
    p = {"kind": kind, "stop": threading.Event(), "until": time.time() + minutes * 60}
    global _player
    with _lock:
        _player = p
    with state.lock:
        state.radio = "♪ " + NAMES[kind]       # the note on her screen
    threading.Thread(target=_play, args=(p,), daemon=True, name="ambience").start()
    print(f"[ambience] {kind} for {minutes} min", flush=True)


def stop():
    global _player
    with _lock:
        p, _player = _player, None
    if p:
        p["stop"].set()
        if p.get("proc"):
            try:
                p["proc"].kill()
            except OSError:
                pass
        with state.lock:
            if state.radio and state.radio.startswith("♪"):
                state.radio = None
    return p is not None


def playing():
    with _lock:
        return _player["kind"] if _player else None


def handle(text, speak):
    low = text.lower().strip(" .!?")
    words = re.findall(r"\w+", low)
    if any(k in low for k in _OFF) and len(words) <= 5:
        if not stop():
            speak("Nic nie szumi.")
        return True
    if (len(words) > 8 or text.strip().endswith("?")
            or (words and words[0] in ("jak", "czy", "dlaczego", "co", "jaki", "kiedy"))):
        return False                            # "czy pada deszcz?" is a question
    if not (_ON.search(low) or "szum" in words):
        return False
    kind = next((k for k, stems in KINDS.items() if any(s in low for s in stems)), None)
    if kind is None:
        return False
    import timers
    secs, _ = timers.parse_duration(low)
    minutes = max(1, secs // 60) if secs else DEFAULT_MINUTES
    speak(f"Włączam {NAMES[kind]}" + (f" na {timers.say_duration(minutes * 60)}." if secs
                                      else f". Wyłączy się sam za {DEFAULT_MINUTES} minut."))
    play(kind, minutes)
    return True
