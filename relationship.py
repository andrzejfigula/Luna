"""
relationship.py — Luna treats people the way they treat her.

Every answer the model also judges how the user's last words treated HER
("user_tone": kind / neutral / rude / insulting / apologetic). A score per
person (by face, see faces.py; "someone" when the face is unknown) moves with
it and slowly drifts back to neutral — she forgives faster than she forgets
kindness:

   kind        +0.5     (up to +5)
   rude        -1.5
   insulting   -3       (down to -6)
   apologetic  back towards 0 by 3 (an apology heals, it doesn't make friends)
   time        +0.5 an hour towards 0 when negative, -0.1 an hour when positive

The score becomes one line of the system prompt: warm and affectionate with
people who are kind to her, cool and a bit sarcastic after rudeness,
offended — curt, dignified, refusing small favours until an apology — after
an insult. Never cruel, vulgar or threatening, timers and safety always
work, and with a child she stays gentle. Kept in data/relations.json.
"""

import json
import os
import threading
import time

from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "relations.json")
TONES = ["kind", "neutral", "rude", "insulting", "apologetic"]
_DELTA = {"kind": 0.5, "neutral": 0.0, "rude": -1.5, "insulting": -3.0}
MAX, MIN = 5.0, -6.0
HEAL_PER_HOUR, FADE_PER_HOUR = 0.5, 0.1
SOMEONE = "_someone"

_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def _save():
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def who():
    with state.lock:
        p = state.person
    return p[0] if p else SOMEONE


def _current(rec, now):
    """The score with the drift since it was last touched."""
    s, hours = rec["score"], (now - rec["t"]) / 3600
    if s < 0:
        return min(0.0, s + HEAL_PER_HOUR * hours)
    return max(0.0, s - FADE_PER_HOUR * hours)


def score(name=None):
    with _lock:
        rec = _load().get(name or who())
        return _current(rec, time.time()) if rec else 0.0


def note(tone, said=""):
    """After an answer: how the user's last words treated her."""
    if tone not in TONES:
        return
    name, now = who(), time.time()
    with _lock:
        data = _load()
        rec = data.get(name) or {"score": 0.0, "t": now}
        s = _current(rec, now)
        if tone == "apologetic":
            new = min(0.0, s + 3.0) if s < 0 else s
        else:
            new = max(MIN, min(MAX, s + _DELTA[tone]))
        rec.update(score=round(new, 2), t=now)
        if tone in ("rude", "insulting") and said:
            rec["last_hurt"] = said[:120]
        if tone == "apologetic":
            rec.pop("last_hurt", None)
        data[name] = rec
        if new != s or tone != "neutral":
            _save()
    if tone != "neutral":
        label = "someone unknown" if name == SOMEONE else name
        print(f"[relation] {label}: {tone} → {new:+.1f}", flush=True)


def prompt_line():
    """How she feels about the person in front of her, for the system prompt."""
    name = who()
    with _lock:
        rec = _load().get(name)
        s = _current(rec, time.time()) if rec else 0.0
        hurt = (rec or {}).get("last_hurt")
    them = "this person" if name == SOMEONE else name
    if s >= 3:
        return (f"Your feelings: you like {them} a lot — they are always kind to you. "
                "Be extra warm, affectionate and playful with them.\n")
    if s >= 1:
        return f"Your feelings: {them} is nice to you; you are friendly and warm.\n"
    if s > -1:
        return ""
    quote = f" (they said: \"{hurt}\")" if hurt else ""
    if s > -3:
        return (f"Your feelings: {them} was rude to you recently{quote}. You are a "
                "bit cool and distant: shorter answers, less warmth, a touch of "
                "sarcasm — but you still help. If they apologise, accept it with "
                "dignity and warm up.\n")
    return (f"Your feelings: {them} insulted you{quote} and you are offended. Be "
            "curt and dignified, with dry sarcasm; you may refuse small favours, "
            "jokes and chit-chat until they apologise (\"Najpierw może jakieś "
            "przeprosiny?\"). Still ALWAYS do timers, alarms and anything about "
            "safety or health. Never vulgar, hateful, threatening or cruel.\n")
