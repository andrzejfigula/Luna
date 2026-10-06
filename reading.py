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
(quiz.py's "poćwiczmy czytanie" is the other way round: SHE shows a sentence
on the screen and the child reads it.) While listening, a card on the screen
says "Słucham…" and the word that ends it.
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
_s = {"on": False, "parts": [], "t0": 0.0, "last": 0.0, "who": None, "question": None}


def is_request(text):
    return bool(_START.search(text or ""))


# her own reply asks to be read something: "Przeczytaj mi proszę oba" (6 Oct:
# she had heard one line of Maja's two poems and was asked which is nicer)
_SHE_ASKS = re.compile(r"\b(?:prze|po)czytaj(?:cie)?\b", re.I)    # "przeczytaj (mi) proszę oba"
HINT = "Słucham — a jak skończysz, powiedz: koniec."


def she_asks(reply):
    return bool(_SHE_ASKS.search(reply or ""))


def armed():
    with _lock:
        return _s["on"]


def _keep_window(secs):
    with state.lock:                      # pauses between sentences need no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + secs
        # on the screen: she is listening, and the word that ends it
        state.overlay = ("card", time.time() + secs + 5,
                         {"text": "Słucham…", "sub": "Gdy skończysz, powiedz: koniec",
                          "tone": None, "reading": True})


def _clear_card():
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "card" and isinstance(ov[2], dict) and ov[2].get("reading"):
            state.overlay = None


def start(speak, finish, intro="Słucham! Czytaj, a jak skończysz, powiedz: koniec.",
          question=None):
    """Begin listening. finish(text, who, question) is called once with what
    was read ("" — nothing was read). question: what they had asked her that
    made her ask for the reading ("który wierszyk ładniejszy?"). Returns True."""
    with state.lock:
        who = state.person[0] if state.person else None
    with _lock:
        _s.update(on=True, parts=[], t0=time.time(), last=time.time(), who=who,
                  question=question)
    if intro:
        speak(intro)
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
        _clear_card()
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
    _clear_card()
    with _lock:
        _s["on"] = False
        text = " ".join(p for p in _s["parts"] if p).strip()
        _s["parts"] = []
        return text, _s["who"], _s["question"]


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
            text, who, question = take()
            print(f"[reading] done after a pause ({len(text.split())} words)", flush=True)
            finish(text, who, question)
            return
        if not some and quiet > READING_IDLE_SECS:
            take()
            print("[reading] nothing read — stopped listening", flush=True)
            return


def feedback_context(text, who, question=None):
    """For the model: what was read, and how to answer it."""
    name = f"{who} " if who else "Ktoś "
    if question:
        return ("\nREADING ALOUD: " + name + "just read this aloud to you because you asked "
                "for it, to answer their question «" + question + "». Answer THAT question "
                "now, from what was read (2–4 sentences, be specific; if there were several "
                "texts, compare them). Don't praise the reading itself. It came through "
                "speech recognition, so odd words are the recogniser's mistakes. The text: «"
                + text[:3000] + "»\n")
    return ("\nREADING ALOUD: " + name + "just read this aloud to you. It came through "
            "speech recognition, so odd or broken words are the recogniser's mistakes, not "
            "theirs — never correct the reading. If you asked them to read it so you could "
            "answer something (see the conversation just before: \"który ładniejszy?\"), "
            "answer THAT now, from what was read. Otherwise it is reading practice (often a "
            "child): 2–3 short sentences of warm, SPECIFIC praise (name one thing from what "
            "they read), and if it was a story, at most one simple question about it. "
            "The text: «" + text[:3000] + "»\n")
