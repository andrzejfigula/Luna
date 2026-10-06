"""
reading.py — "posłuchaj, jak czytam": a child reads aloud, Luna listens.

  "Posłuchaj, jak czytam" / "poczytam ci" / "chcę ci przeczytać" →
  "Słucham! Czytaj, a jak skończysz, powiedz: koniec." Every sentence after
  that is only collected (no answers in between, no "Luna" needed across
  pauses) until "koniec" / "skończyłam" or READING_END_SECS of silence; then
  one answer about what was read: warm, specific praise, perhaps a question
  about the story. "Przestań czytać" / "stop" ends it with nothing said.

Reading practice is what an 8-year-old does every day; with the normal
conversation rules she would have answered every sentence of the book.
"""

import re
import threading
import time

from shared_state import state

READING_END_SECS = 25      # this much silence after some reading = done
READING_IDLE_SECS = 60     # armed but nothing read at all: give up quietly
READING_MAX_SECS = 15 * 60

_START = re.compile(
    r"\b(?:posłuchaj|słuchaj|posluchaj|sluchaj),?\s+(?:jak|co)\s+(?:czytam|przeczytam|"
    r"poczytam|będę\s+czytać|bede\s+czytac)\b|"
    r"\b(?:poczytam|przeczytam)\s+ci\b|"
    r"\b(?:chcę|chce|mogę|moge)\s+ci\s+(?:po|prze)?czytać\b|"
    r"\bbędę\s+ci\s+czytać\b|"
    r"\bczy\s+mogę\s+ci\s+(?:po|prze)?czytać\b", re.I)
_END = re.compile(r"^(?:no\s+)?(?:koniec|skończyłam|skończyłem|skonczylam|skonczylem|"
                  r"to\s+wszystko|to\s+koniec|i\s+tyle|już|juz|the\s+end)\b", re.I)
_END_TAIL = re.compile(r"\s+(?:koniec|skończyłam|skończyłem)[\s.!]*$", re.I)
_STOP = re.compile(r"^(?:luna,?\s+)?(?:przestań|przestan|stop|nie\s+chcę\s+już|"
                   r"nie\s+chce\s+juz)(?:\s+czytać)?\b", re.I)

_lock = threading.Lock()
_s = {"on": False, "parts": [], "t0": 0.0, "last": 0.0, "who": None}


def is_request(text):
    return bool(_START.search(text or ""))


def armed():
    with _lock:
        return _s["on"]


def _keep_window(secs):
    with state.lock:                      # pauses between sentences need no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + secs


def start(speak, finish):
    """Begin listening. finish(text, who) is called once with what was read
    (None: nothing was read). Returns True."""
    with state.lock:
        who = state.person[0] if state.person else None
    with _lock:
        _s.update(on=True, parts=[], t0=time.time(), last=time.time(), who=who)
    speak("Słucham! Czytaj, a jak skończysz, powiedz: koniec.")
    _keep_window(READING_END_SECS)
    threading.Thread(target=_watch, args=(finish,), daemon=True, name="reading").start()
    print("[reading] listening", flush=True)
    return True


def add(text):
    """A sentence heard while reading. Returns "end" when they said they are
    done (the text is complete), "stop" when they called it off, else None."""
    t = (text or "").strip()
    low = t.lower().strip(" .!?")
    if _STOP.match(low):
        with _lock:
            _s["on"] = False
        print("[reading] stopped", flush=True)
        return "stop"
    if _END.match(low) and len(low.split()) <= 4:
        return "end"
    rest = _END_TAIL.sub("", t) if _END_TAIL.search(t) else None
    with _lock:
        _s["parts"].append(rest if rest is not None else t)
        _s["last"] = time.time()
    _keep_window(READING_END_SECS)
    return "end" if rest is not None else None


def take():
    """End the reading: the text read (or "") and the reader."""
    with _lock:
        _s["on"] = False
        text = " ".join(p for p in _s["parts"] if p).strip()
        _s["parts"] = []
        return text, _s["who"]


def _watch(finish):
    """Silence ends the reading: after READING_END_SECS with something read,
    or READING_IDLE_SECS with nothing."""
    while True:
        time.sleep(1.0)
        with _lock:
            if not _s["on"]:
                return
            quiet = time.time() - _s["last"]
            some = bool(_s["parts"])
            too_long = time.time() - _s["t0"] > READING_MAX_SECS
        with state.lock:
            busy = state.speaking
        if busy:
            continue
        if (some and quiet > READING_END_SECS) or too_long:
            text, who = take()
            print(f"[reading] done after a pause ({len(text.split())} words)", flush=True)
            finish(text, who)
            return
        if not some and quiet > READING_IDLE_SECS:
            take()
            print("[reading] nothing read — stopped listening", flush=True)
            return


def feedback_context(text, who):
    """For the model: what was read, and how to answer it."""
    name = f"{who} " if who else "Ktoś "
    return ("\nREADING ALOUD: " + name + "just read this aloud to you, for practice. It "
            "came through speech recognition, so odd or broken words are the recogniser's "
            "mistakes, not theirs — never correct the reading. Answer in 2–3 short "
            "sentences: warm, SPECIFIC praise (name one thing from what they read), and "
            "if it was a story, at most one simple question about it. The text: «"
            + text[:3000] + "»\n")
