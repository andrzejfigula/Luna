"""
counting.py — counting out loud, and a stopwatch.

  "Policz do dwudziestu"       → hide and seek: "Chowajcie się!", then one
                                 number a second, big on her screen, and
                                 "Kto się nie schował, ten kryje!" (from 10 up;
                                 "do pięciu" is plain counting)
  "Odliczaj od dziesięciu"     → a rocket countdown: 10, 9 … 1, "Start!"
  "Włącz stoper"               → counts up in the corner of the screen
  "Ile na stoperze?"           → how long so far
  "Zatrzymaj stoper"           → stops it and says the time

The numbers are spoken by her own voice, each made once and kept on disk
(sounds.clip), so a count keeps a steady one-second beat — a live TTS call
per number would stutter — and works offline the second time. A tap on the
screen stops the count.
"""

import re
import threading
import time

from shared_state import state

COUNT_MAX = 30            # "policz do stu" would take too long for a game
BEAT_SECS = 1.0

_COUNT = re.compile(r"\b(?:policz|policzyć|policzysz|odlicz|odliczaj|odliczyć|licz|odliczanie|count)\b(?:\s+\w+){0,2}?"
                    r"\s+(do|od|to|from)\s+(.+)$")
_TIME_UNITS = ("minut", "sekund", "godzin", "minute", "second", "hour")

_STOPWATCH_START = ("włącz stoper", "wlacz stoper", "start stoper", "uruchom stoper",
                    "odpal stoper", "stoper start", "włącz stopera", "start the stopwatch",
                    "mierz czas", "zmierz czas", "zacznij mierzyć czas")
_STOPWATCH_STOP = ("zatrzymaj stoper", "stop stoper", "wyłącz stoper", "wylacz stoper",
                   "zatrzymaj stopera", "stoper stop", "stop the stopwatch", "koniec pomiaru")
_STOPWATCH_ASK = ("ile na stoperze", "ile jest na stoperze", "ile pokazuje stoper",
                  "ile minęło na stoperze", "ile minęło", "ile już minęło")

_watch = {"t0": None}     # the stopwatch


# ── numbers in words ──────────────────────────────────────────────────────────

def _word(n):
    import clock
    if n < 20:
        return clock._UNITS[n]
    t, u = divmod(n, 10)
    return clock._TENS[t] + (" " + clock._UNITS[u] if u else "")


def _plural(n, one, few, many):
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def say_elapsed(secs):
    """134 → "2 minuty i 14 sekund"."""
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} {_plural(h, 'godzina', 'godziny', 'godzin')}")
    if m:
        parts.append(f"{m} {_plural(m, 'minuta', 'minuty', 'minut')}")
    if s or not parts:
        parts.append(f"{s} {_plural(s, 'sekunda', 'sekundy', 'sekund')}")
    return " i ".join(parts) if len(parts) == 2 else " ".join(parts)


# ── counting ──────────────────────────────────────────────────────────────────

def parse_count(text):
    """("up", 20) for "policz do dwudziestu", ("down", 10) for "odliczaj od
    dziesięciu", else None."""
    import calc
    low = text.lower().strip(" ?!.")
    if any(u in low for u in _TIME_UNITS):
        return None                                   # "odlicz 10 minut" is a timer
    m = _COUNT.search(low)
    if not m:
        return None
    rest = m.group(2)
    words = re.findall(r"\w+", rest)
    if not words or len(words) > 3 or not all(
            w.isdigit() or w in calc._ONES or w in calc._SCALES for w in words):
        return None                                   # "do 5 po angielsku" → the model
    n = calc.number_in(rest)
    if not n or n < 2:
        return None
    direction = "down" if m.group(1) in ("od", "from") else "up"
    return direction, int(min(n, COUNT_MAX))


def _prepare(numbers):
    """Make sure every number clip exists (made in parallel the first time)."""
    import sounds
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as pool:
        clips = list(pool.map(lambda n: sounds.clip(_word(n).capitalize() + "."), numbers))
    return dict(zip(numbers, clips))


def _interrupted(t0):
    with state.lock:
        return state.touch_time > t0


def count(direction, n, speak, play_sound, hide=None):
    from text_to_speech import play_clip
    numbers = list(range(1, n + 1)) if direction == "up" else list(range(n, 0, -1))
    clips = {}
    prep = threading.Thread(target=lambda: clips.update(_prepare(numbers)), daemon=True)
    prep.start()
    # hide-and-seek only when it sounds like it: "policz do pięciu" from a child
    # learning numbers got "Chowajcie się!" (9 Oct probe)
    hide = (n >= 10) if hide is None else hide
    if direction == "up":
        speak(f"Liczę do {n}! Chowajcie się!" if hide else f"Liczę do {n}!")
    else:
        speak(f"Odliczam od {n}!")
    prep.join(20)
    print(f"[count] {direction} {n} ({sum(1 for c in clips.values() if c)}/{len(numbers)} "
          "clips)", flush=True)
    t0 = time.time()
    with state.lock:
        state.emotion = "Happy"
    next_beat = t0
    for num in numbers:
        if _interrupted(t0):
            print("[count] stopped by touch", flush=True)
            with state.lock:
                state.big_text = None
            return
        time.sleep(max(0.0, next_beat - time.time()))
        start = time.time()
        pcm = clips.get(num)
        with state.lock:                   # the number stays up while it is said
            state.big_text = (str(num), start + max(0.95, len(pcm or b"") / 48000))
        if pcm:
            play_clip(pcm, label=_word(num))
        else:
            play_sound("tick")                             # offline, first time
        # one a second — or a short breath after a long "dwadzieścia siedem"
        next_beat = max(start + BEAT_SECS, time.time() + 0.12)
    time.sleep(max(0.0, next_beat - time.time()))
    if direction == "up":
        # (she can't look for anyone — whoever is "it" goes seeking)
        speak("Kto się nie schował, ten kryje!" if hide else "Gotowe!")
    else:
        play_sound("chime")
        speak("Start!")
    with state.lock:
        state.emotion = "Neutral"


# ── stopwatch ─────────────────────────────────────────────────────────────────

def stopwatch_text():
    """The corner of the screen while the stopwatch runs: "+2:14"."""
    t0 = _watch["t0"]
    if t0 is None:
        return None
    secs = int(time.time() - t0)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"+{h}:{m:02d}:{s:02d}" if h else f"+{m}:{s:02d}"


def ask_stopwatch(text, speak):
    """"Ile na stoperze?" — a question, so commands.py asks here before its
    question guard. True when answered."""
    low = text.lower()
    if (any(k in low for k in _STOPWATCH_ASK) and _watch["t0"] is not None
            and len(re.findall(r"\w+", low)) <= 6):
        speak(f"Na stoperze: {say_elapsed(time.time() - _watch['t0'])}.")
        return True
    return False


def handle(text, speak, play_sound):
    """Counting and stopwatch commands. True when handled."""
    low = text.lower()
    if any(k in low for k in _STOPWATCH_START):
        _watch["t0"] = time.time()
        play_sound("tick")
        speak("Stoper ruszył!")
        print("[count] stopwatch started", flush=True)
        return True
    if any(k in low for k in _STOPWATCH_STOP):
        if _watch["t0"] is None:
            speak("Stoper nie był włączony.")
            return True
        secs = time.time() - _watch["t0"]
        _watch["t0"] = None
        print(f"[count] stopwatch stopped at {secs:.1f}s", flush=True)
        speak(f"Stop! {say_elapsed(secs)}.")
        return True
    if ask_stopwatch(text, speak):
        return True
    c = parse_count(text)
    if c:
        hide = True if re.search(r"chowa|chowan|kryj", low) else None
        count(c[0], c[1], speak, play_sound, hide=hide)
        return True
    return False
