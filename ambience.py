"""
ambience.py — sounds to fall asleep to, made right here.

  "Włącz szum deszczu" / "deszcz"   → soft rain: filtered noise with drops
  "Szum morza" / "fale"              → waves: noise that swells and ebbs
  "Biały szum" / "szum"              → steady pink noise
  "Włącz kominek" / "ognisko"        → a fire: a low rumble and crackles
  "Szum lasu" / "ptaki"              → a forest: leaves in the wind, birds now and then
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

import visualizer
from shared_state import state

RATE = 24000
BLOCK = RATE // 10                     # 0.1 s
GAIN = 0.30                            # quiet: it's for sleeping
DUCK = 0.15
DEFAULT_MINUTES = 45
FADE_SECS = 20

# (the fire and the forest before "szum": "szum lasu" was white noise — 14 Oct probe)
KINDS = {"rain": ("deszcz", "deszczu", "rain"),
         "sea": ("morz", "fal", "ocean", "sea", "waves"),
         "fire": ("kominek", "kominka", "kominku", "ogień", "ognia", "ognisk", "fire"),
         "forest": ("las", "lasu", "lesie", "ptak", "ptaszk", "forest", "birds"),
         "noise": ("biały szum", "bialy szum", "różowy szum", "rozowy szum",
                   "white noise", "szum")}
NAMES = {"rain": "szum deszczu", "sea": "szum morza", "noise": "biały szum",
         "fire": "trzaskający kominek", "forest": "szum lasu z ptakami"}
NIGHT_MINUTES = 8 * 60                 # "…na noc"
# at the start of a word: "las" is not in "klasyczną" ("włącz klasyczną muzykę")
_KIND_RX = {k: re.compile(r"(?<!\w)(?:" + "|".join(
    (r"las\b" if s == "las" else re.escape(s)) for s in stems) + ")") for k, stems in KINDS.items()}
_SWITCH = re.compile(r"\b(?:przełącz|przelacz|zmie[ńn]\s+na)\b")   # "przełącz na kominek"
_ON = re.compile(r"\b(?:włącz|wlacz|puść|pusc|zagraj|daj)\b|^(?:szum|deszcz|fale)\b")
_OFF = ("wyłącz szum", "wylacz szum", "wyłącz deszcz", "wyłącz morze", "wyłącz fale",
        "stop szum", "koniec szumu", "wyłącz dźwięki", "zatrzymaj szum",
        "wyłącz kominek", "wyłącz kominka", "wyłącz dźwięk kominka", "wyłącz ognisko",
        "wyłącz las", "wyłącz ptaki", "wyłącz odgłos")

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


def _shaped_noise(n, power, rng, corner=1.0):
    """Noise with a 1/f^power spectrum, made with one FFT. An FFT-made signal
    is periodic, so it loops with no seam (pink: 1, brown: 2). Flat below
    `corner` Hz and nothing under 30 Hz — else brown noise is all sub-audio
    drift and plays as silence."""
    spec = rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)
    f = np.arange(n // 2 + 1, dtype=float) * RATE / n
    shape = 1.0 / np.maximum(f, corner) ** (power / 2)
    shape[f < 30] = 0.0
    x = np.fft.irfft(spec * shape, n)
    return x / (np.abs(x).max() + 1e-9)


class _Gen:
    """Endless sound, block by block, from a 30 s loop made once (cheap: no
    per-sample Python — a filter loop would cost the Pi ~15 % of a core)."""

    def __init__(self, kind):
        self.kind, self.pos, self.t = kind, 0, 0.0
        self.rng = np.random.default_rng()
        n = LOOP_SECS * RATE
        power = {"sea": 2.0, "fire": 2.0}.get(kind, 1.0)
        level = {"sea": 0.6, "fire": 0.35, "forest": 0.22}.get(kind, 0.5)
        corner = {"sea": 250.0, "fire": 120.0}.get(kind, 1.0)
        self.loop = _shaped_noise(n, power, self.rng, corner) * level
        self.drop = np.exp(-np.arange(160) / 30.0)          # one raindrop's decay
        self.crack = np.exp(-np.arange(90) / 7.0)           # one crackle's decay
        self.bird = np.zeros(0)                             # a song still being sung

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
        elif self.kind == "fire":
            # a low rumble that breathes, sparse crackles, now and then a pop
            x = x * (0.75 + 0.25 * np.sin(2 * np.pi * t / 3.7))
            hits = (self.rng.random(n) < 0.0016) * self.rng.uniform(0.2, 1.0, n)
            if self.rng.random() < 0.04:
                hits[self.rng.integers(n)] = 1.6               # a log settles
            env = np.convolve(hits, self.crack)[:n]
            x = x + env * self.rng.standard_normal(n) * 0.35
        elif self.kind == "forest":
            # leaves in the wind (slow swells) and a bird every few seconds
            x = x * (0.55 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 7.3)) ** 2)
            if len(self.bird) == 0 and self.rng.random() < 0.035:
                self.bird = self._song()
            if len(self.bird):
                k = min(n, len(self.bird))
                x = x.copy()
                x[:k] += self.bird[:k]
                self.bird = self.bird[k:]
        return x

    def _song(self):
        """A little bird: 2-5 quick chirps, each a rising or falling whistle."""
        out = []
        base = self.rng.uniform(2600, 4200)
        up = self.rng.random() < 0.5
        for _ in range(self.rng.integers(2, 6)):
            dur = self.rng.uniform(0.05, 0.12)
            m = int(dur * RATE)
            tt = np.arange(m) / RATE
            f0, f1 = (base * 0.8, base * 1.25) if up else (base * 1.25, base * 0.8)
            phase = 2 * np.pi * (f0 * tt + (f1 - f0) * tt * tt / (2 * dur))
            env = np.sin(np.pi * np.arange(m) / m) ** 2
            out.append(np.sin(phase) * env * self.rng.uniform(0.10, 0.20))
            out.append(np.zeros(int(self.rng.uniform(0.04, 0.10) * RATE)))
        return np.concatenate(out)


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
    level = float(np.sqrt((gen.loop ** 2).mean())) * 32767       # (the effects' scale)
    vis_t = np.arange(BLOCK * visualizer.RATE // RATE) * (RATE / visualizer.RATE)
    visualizer.set_kind(p["kind"])
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
            raw = gen.block()
            x = raw * np.linspace(gain, new, BLOCK)
            gain = new
            try:                                       # the radio's effects show it too
                visualizer.tap(np.interp(vis_t, np.arange(BLOCK), raw * 32767), level,
                               None, 1)
            except Exception as e:
                if not p.get("vis_err"):
                    p["vis_err"] = True
                    print(f"[vis] {e}", flush=True)
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
            idle = _player is None
        if idle:                               # (switched: the new sound's note stays)
            visualizer.reset()
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
    if any(k in low for k in _OFF) and len(words) <= 7:
        import timers
        secs, _ = timers.parse_duration(low) if re.search(r"\bza\b", low) else (None, None)
        if secs:                                # "wyłącz szum za pół godziny" — later
            with _lock:
                p = _player
                if p:
                    p["until"] = time.time() + secs
            speak(f"Dobrze, wyłączy się za {timers.say_duration(secs)}." if p
                  else "Nic nie szumi.")
            return True
        if not stop():
            speak("Nic nie szumi.")
        return True
    if (len(words) > 8 or text.strip().endswith("?")
            or (words and words[0] in ("jak", "czy", "dlaczego", "co", "jaki", "kiedy"))):
        return False                            # "czy pada deszcz?" is a question
    import intent                               # not "szum morza mnie uspokaja"
    night = bool(re.search(r"\bna\s+(?:całą\s+|cala\s+)?noc\b", low))   # "biały szum na noc"
    if not (_SWITCH.search(low) or (_ON.search(low) or "szum" in words) and (
            intent.asked(low, 3) or night
            or re.search(r"\bna\s+\w+\s+(?:minut|godzin)", low))):
        return False
    kind = next((k for k, rx in _KIND_RX.items() if rx.search(low)), None)
    if kind is None:
        if re.search(r"\b(?:odgłos\w*|odglos\w*|dźwięk\w*|dzwiek\w*|szum\w*)\b", low):
            # "włącz odgłosy lasu" — one she hasn't got (7 Oct probe: the
            # model went silent on it)
            speak("Takiego dźwięku nie mam. Mam deszcz, morze, kominek, las z ptakami "
                  "i biały szum — który włączyć?")
            return True
        return False
    import timers
    secs, _ = timers.parse_duration(low)
    minutes = max(1, secs // 60) if secs else NIGHT_MINUTES if night else DEFAULT_MINUTES
    speak(f"Włączam {NAMES[kind]}" + (f" na {timers.say_duration(minutes * 60)}." if secs
                                      else " na całą noc." if night
                                      else f". Wyłączy się sam za {DEFAULT_MINUTES} minut."))
    play(kind, minutes)
    return True
