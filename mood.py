"""
mood.py — Luna's own day, and the mood it puts her in.

She keeps a small diary of today (data/day.json, reset at midnight): who she
talked with and how often, how many kind and how many rude words she got,
when the last conversation was. That becomes a line of the system prompt:

  "Your own day so far: you talked with Andrzej (12 times) and Maja (3);
   people were kind to you twice. Last chat: 2 h ago. It's late evening."

and colours her replies a little — livelier after a nice day, a bit lonely
(and glad) after hours alone, sleepy late at night — and lets her answer
"jak się czujesz?" / "jak minął ci dzień?" from what really happened
instead of making something up.
"""

import json
import os
import threading
import time

from config import DATA_DIR

PATH = os.path.join(DATA_DIR, "day.json")
DIARY = os.path.join(DATA_DIR, "diary.json")   # the days before, short (14 kept)
DIARY_DAYS = 14
_lock = threading.Lock()
_day = None


def _today():
    return time.strftime("%Y-%m-%d")


def _load():
    global _day
    if _day is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _day = json.load(f)
        except (OSError, ValueError):
            _day = {}
    if _day.get("date") != _today():
        if _day.get("date") and _day.get("talks"):
            _to_diary(_day)                   # yesterday goes into her diary
        _day = {"date": _today(), "talks": {}, "kind": 0, "rude": 0, "games": [],
                "last": _day.get("last", 0)}
    return _day


def _diary():
    try:
        with open(DIARY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _to_diary(day):
    entries = [e for e in _diary() if e.get("date") != day["date"]]
    entries.append({k: day.get(k) for k in ("date", "talks", "kind", "rude", "games")})
    entries = sorted(entries, key=lambda e: e["date"])[-DIARY_DAYS:]
    tmp = DIARY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    os.replace(tmp, DIARY)


def _games(games):
    """"Maja: dyktando 3/5 at 18:10 (mistakes: rzeka, góra)" …"""
    return "; ".join(f"{g['who']}: {g['game']} {g['score']}/{g['total']} at {g['at']}"
                     + (f" (wrong: {', '.join(g['misses'])})" if g.get("misses") else "")
                     for g in games[-6:])


def _past_line():
    """The last few days, from her diary, for "co robiłaś wczoraj?"."""
    days = _diary()[-3:]
    if not days:
        return ""
    parts = []
    for e in reversed(days):
        who = ", ".join(f"{n} ({c})" for n, c in
                        sorted(e.get("talks", {}).items(), key=lambda kv: -kv[1]))
        extra = []
        if e.get("kind"):
            extra.append(f"{e['kind']} kind words")
        if e.get("rude"):
            extra.append(f"{e['rude']} rude ones")
        parts.append(f"{e['date']}: talked with {who or 'nobody'}"
                     + (f", {', '.join(extra)}" if extra else "")
                     + (f", games: {_games(e.get('games'))}" if e.get("games") else ""))
    return " Your diary of the last days: " + "; ".join(parts) + "."


def _save():
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_day, f, ensure_ascii=False)
    os.replace(tmp, PATH)


def note(who, tone):
    """After every answered utterance (brain.py)."""
    with _lock:
        d = _load()
        key = who or "ktoś nieznajomy"
        d["talks"][key] = d["talks"].get(key, 0) + 1
        if tone == "kind":
            d["kind"] += 1
        elif tone in ("rude", "insulting"):
            d["rude"] += 1
        d["last"] = time.time()
        _save()


_GAME_PL = {"mul": "tabliczka mnożenia", "add": "dodawanie", "sub": "odejmowanie",
            "mix": "rachunki", "words": "angielskie słówka", "riddle": "zagadki",
            "dictation": "dyktando", "clock": "zegar"}


def note_game(who, kind, score, total, misses):
    """A finished quiz round (quiz.py), for the parents' "jak jej poszło?"."""
    with _lock:
        d = _load()
        d.setdefault("games", []).append({
            "who": who or "ktoś", "game": _GAME_PL.get(kind, kind), "score": score,
            "total": total, "misses": misses[:10], "at": time.strftime("%H:%M")})
        d["games"] = d["games"][-20:]
        _save()


def _times(n):
    return "raz" if n == 1 else f"{n} razy"


def prompt_line():
    with _lock:
        d = dict(_load())
        talks = dict(d["talks"])
    h = time.localtime().tm_hour
    part = ("late at night — you are sleepy" if h >= 23 or h < 5 else
            "early morning — you are just waking up" if h < 8 else
            "evening" if h >= 18 else "daytime")
    if talks:
        who = ", ".join(f"{n} ({_times(c)})" for n, c in
                        sorted(talks.items(), key=lambda kv: -kv[1]))
        day = f"today you talked with {who}"
    else:
        day = "nobody has talked with you yet today"
    feel = []
    if d["kind"]:
        feel.append(f"people were kind to you {_times(d['kind'])}")
    if d["rude"]:
        feel.append(f"someone was rude to you {_times(d['rude'])}")
    if d.get("games"):
        feel.append(f"games played: {_games(d['games'])}")
    gap = ""
    if d.get("last"):
        mins = (time.time() - d["last"]) / 60
        if mins > 120:
            gap = f" The last chat was {mins / 60:.0f} h ago — you were a bit lonely."
        elif mins > 30:
            gap = f" The last chat was {mins:.0f} min ago."
    return (f"Your own day so far: {day}" + ("; " + ", ".join(feel) if feel else "")
            + f".{gap}{_past_line()} It is {part}. Let this colour your mood lightly (livelier after "
            "a nice day, glad to have company after being alone, sleepy late); if asked "
            "how you are or how your day was, answer from this — say briefly who you "
            "talked with and how it felt — and don't invent events.\n")
