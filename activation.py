"""
activation.py — the gate between "her name was heard" and "she answers".

speech_to_text finds a candidate call (Vosk's word, a name only the cloud
heard, or with the radio on a sentence the face in front of her was seen
saying) and judge() gives it one verdict, logged as one line without the
words that were said:

    [wake] REJECT about_her src=cloud conf=- mode=idle radio=0 tts_ago=41s words=7 ms=830

ACCEPT can come with limits: scope "local" (a local command only, never the
model) and quiet (her name alone, unsure: the listening face, no "hm?", and
the next sentence isn't taken as said to her). EXPIRE: such a quiet call
nobody followed. CANCEL: a pending call, or the answer still being prepared,
called off (muted, a tap, the window closed from outside).
"""

import re
import threading
import time

from shared_state import state
from config import (WAKE_SURE_CONF, WAKE_UNSURE_QUIET, WAKE_REJECT_COOLDOWN,
                    RADIO_FACE_LOCAL_ONLY)

ACCEPT, REJECT, EXPIRE, CANCEL = "ACCEPT", "REJECT", "EXPIRE", "CANCEL"
WEAK = ("cloud", "radio-face")     # her name only in the cloud's words, or no name at all


class Candidate:
    """src: "vosk" (Vosk's own word), "vosk-fuzzy" (a near-miss the cloud
    confirmed), "cloud" (only the cloud heard her name), "radio-face".
    text: what's left after her name ("" — the name alone)."""

    def __init__(self, src, text="", vosk="", cloud=None, conf=None,
                 name_like=False, radio=False):
        self.src, self.text, self.vosk, self.cloud = src, text or "", vosk or "", cloud
        self.conf, self.name_like, self.radio = conf, name_like, radio


class Verdict:
    def __init__(self, outcome, reason, scope="full", quiet=False, stamp=True):
        self.outcome, self.reason = outcome, reason
        self.scope = scope       # "local": only a local command, never the model
        self.quiet = quiet       # her name alone: no sound
        self.stamp = stamp       # brain: the next sentence came with her name

    def __repr__(self):
        return f"Verdict({self.outcome}, {self.reason}, {self.scope}, quiet={self.quiet})"


_lock = threading.Lock()
_cool_until = 0.0
_pending = None                  # (when) — a quiet call waiting for its request
_turn = {"id": 0, "thread": None, "cancelled": False, "helpers": set()}


# ── Is her name a call, or is she talked about? ───────────────────────────────

_OBLIQUE = {"luny", "lunę", "lunie", "luną"}      # "zapytaj Lunę", "o Lunie": about her
_LEAD = {"hej", "hey", "hi", "cześć", "no", "a", "dobra", "halo", "ej", "słuchaj",
         "dobrze", "ok", "okej", "dzień", "dobry", "dobranoc", "pa", "siema", "witaj",
         "oj", "ach", "aha", "ale", "więc", "dzięki", "dziękuję"}
# a word that makes the name a part of the sentence: "co Luna umie", "Maja i Luna"
_ABOUT_BEFORE = {"co", "że", "bo", "jak", "gdy", "kiedy", "jest", "to", "ta", "nasza",
                 "moja", "twoja", "z", "ze", "o", "do", "dla", "przez", "u", "od",
                 "nie", "też", "i", "oraz", "albo", "czy", "gdzie"}
_THEME = re.compile(r"\b(?:na|w|do|motyw\w*|postać|postac|profil\w*|włącz|wlacz|bądź|badz)$",
                    re.I)


def name_role(text, rx):
    """"call" when her name in the cloud's words is said to her, "about" when
    it is said about her, None when it isn't there. rx finds her names
    (speech_to_text._wake_re). 26 Oct: "Chodź Maja, pokażę ci, co Luna
    nauczyłem nowego." woke her; "I jak, Luna, jak tam…" and "Co tam Luna?"
    are calls."""
    roles = []
    for m in rx.finditer(text or ""):
        before, after = text[:m.start()], text[m.end():]
        word = m.group(0).lower()
        prev = re.findall(r"\w+", before)
        bare_before = before.rstrip()
        punct_before = bool(bare_before) and bare_before[-1] in ",.!?:;-–—"
        punct_after = not after.strip() or after.lstrip()[:1] in ",.!?:;-–—"
        if word in _OBLIQUE and not _THEME.search(bare_before):
            roles.append("call" if after.lstrip()[:1] == "," and not prev else "about")
        elif all(w.lower() in _LEAD for w in prev):
            roles.append("call")               # first, maybe after "hej" / "no"
        elif punct_before or punct_after:
            roles.append("call")               # set off by commas, or last: "Co tam Luna?"
        elif prev and prev[-1].lower() in _ABOUT_BEFORE:
            roles.append("about")
        else:
            roles.append("call")               # "Powiedz mi Luna jaka pogoda"
    if not roles:
        return None
    return "call" if "call" in roles else "about"


# ── The verdict ───────────────────────────────────────────────────────────────

def _sure(c):
    """Her name alone, and both recognisers (or Vosk, clearly) heard it."""
    if c.src == "vosk":
        return c.conf is None or c.conf >= WAKE_SURE_CONF
    if c.src == "vosk-fuzzy":
        return True                            # Vosk's near-miss, the cloud's name
    return c.name_like                         # cloud: Vosk heard something like it


def _verdict(c, rx, now):
    with state.lock:
        muted = now < state.mic_muted_until
    if muted:
        return Verdict(REJECT, "muted")
    if c.src in WEAK and now < _cool_until:
        return Verdict(REJECT, "cooldown")
    if c.cloud and rx is not None and name_role(c.cloud, rx) == "about":
        return Verdict(REJECT, "about_her")
    if c.src == "radio-face":
        if RADIO_FACE_LOCAL_ONLY:              # no name at all: never the model
            return Verdict(ACCEPT, "radio_face", scope="local", stamp=False)
        return Verdict(ACCEPT, "radio_face", stamp=False)
    if not c.text:
        if _sure(c):
            return Verdict(ACCEPT, "bare")
        return Verdict(ACCEPT, "bare_unsure", quiet=WAKE_UNSURE_QUIET, stamp=False)
    return Verdict(ACCEPT, "request")


def judge(c, rx=None, now=None):
    """The one verdict for a candidate call (logged)."""
    global _pending
    now = now or time.time()
    v = _verdict(c, rx, now)
    _log(v.outcome, v.reason, c, now)
    with _lock:
        if v.outcome == REJECT:
            _cooldown(v.reason, now)
        else:
            _pending = now if v.quiet else None
    return v


def reject(c, reason, now=None):
    """A rejection decided elsewhere (no face, not her name, English side
    talk): logged the same way, and the same cooldown."""
    now = now or time.time()
    _log(REJECT, reason, c, now)
    with _lock:
        _cooldown(reason, now)
    return Verdict(REJECT, reason)


def _cooldown(reason, now):
    global _cool_until
    if reason not in ("muted", "cooldown"):
        _cool_until = max(_cool_until, now + WAKE_REJECT_COOLDOWN)


def cooling(now=None):
    """Just rejected a call: no cloud-only wakes for a moment (the same
    conversation goes on — its next sentence isn't worth the cloud)."""
    return (now or time.time()) < _cool_until


def _log(outcome, reason, c, now):
    with state.lock:
        active = state.conversation_active
        spoke = state.last_spoken_time
        heard = getattr(state, "heard_at", 0.0)
    conf = "-" if c.conf is None else f"{c.conf:.2f}"
    tts_ago = f"{now - spoke:.0f}s" if spoke else "-"
    ms = f"{(now - heard) * 1000:.0f}" if heard and 0 <= now - heard < 60 else "-"
    words = len((c.cloud if c.cloud is not None else c.vosk).split())
    print(f"[wake] {outcome} {reason} src={c.src} conf={conf} "
          f"mode={'window' if active else 'idle'} radio={int(bool(c.radio))} "
          f"tts_ago={tts_ago} words={words} ms={ms}", flush=True)


# ── A quiet call waiting for its request ──────────────────────────────────────

def pending():
    return _pending is not None


def followed():
    """The request after a quiet call came: it is settled."""
    global _pending
    with _lock:
        _pending = None


def expire(now=None):
    """The window closed with a quiet call unanswered: it was nothing."""
    global _pending
    with _lock:
        p, _pending = _pending, None
    if p is not None:
        print(f"[wake] EXPIRE nothing_followed after={(now or time.time()) - p:.0f}s",
              flush=True)


# ── Cancelling the turn in progress ───────────────────────────────────────────

def begin_turn():
    """The voice loop starts on what it heard (main.voice_loop)."""
    with _lock:
        _turn["id"] += 1
        _turn["thread"] = threading.get_ident()
        _turn["cancelled"] = False
        _turn["helpers"] = set()
        return _turn["id"]


def end_turn():
    with _lock:
        _turn["thread"] = None
        _turn["cancelled"] = False
        _turn["helpers"] = set()


def join_turn(tid):
    """This thread speaks for turn tid (brain's streamed answer)."""
    with _lock:
        if tid and _turn["id"] == tid and _turn["thread"] is not None:
            _turn["helpers"].add(threading.get_ident())


def cancel(reason):
    """Call off a quiet call that's waiting, and the answer being prepared:
    what the model still sends is not said. Returns True when there was
    something to cancel."""
    global _pending
    with _lock:
        p, _pending = _pending, None
        busy = _turn["thread"] is not None and not _turn["cancelled"]
        if busy:
            _turn["cancelled"] = True
    if p is not None or busy:
        print(f"[wake] CANCEL {reason} pending={int(p is not None)} turn={int(busy)}",
              flush=True)
    return p is not None or busy


def turn_id():
    """The turn this thread is part of (0: none) — for work handed to
    another thread (join_turn)."""
    me = threading.get_ident()
    with _lock:
        mine = _turn["thread"] == me or me in _turn["helpers"]
        return _turn["id"] if mine else 0


def turn_cancelled(tid=None):
    """In the voice loop's own thread (or for turn tid), during a cancelled
    turn: say nothing (a timer firing elsewhere still speaks)."""
    with _lock:
        if tid is not None:
            return bool(tid) and _turn["id"] == tid and _turn["cancelled"]
        me = threading.get_ident()
        return _turn["cancelled"] and (_turn["thread"] == me or me in _turn["helpers"])
