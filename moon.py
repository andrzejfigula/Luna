"""
moon.py — "Jaka dziś faza Księżyca?", "Kiedy pełnia?", "Kiedy nów?" — worked
out here, not guessed (she's named after the Moon; the model would make the
date up). Mean synodic month from a known new moon; good to about a day,
which is how the family uses it.
"""

import math
import re
from datetime import datetime, timedelta

SYNODIC = 29.530588853
_NEW = datetime(2000, 1, 6, 18, 14)          # a new moon (UTC)
_NAMES = ((1.0, "nów"), (6.4, "przybywający sierp"), (8.4, "pierwsza kwadra"),
          (13.8, "Księżyc przybywający, prawie w pełni"), (15.8, "pełnia"),
          (21.1, "Księżyc ubywający, po pełni"), (23.1, "ostatnia kwadra"),
          (28.5, "ubywający sierp"), (SYNODIC + 1, "nów"))
_ASK = re.compile(r"faz\w*\s+księżyc\w*|faz\w*\s+ksiezyc\w*|\bjaki\s+(?:dziś|dzis|dzisiaj|teraz)?\s*"
                  r"(?:jest\s+)?księżyc|kiedy\s+(?:będzie\s+|bedzie\s+|jest\s+|następna\s+|nastepna\s+)?"
                  r"(?:pełnia|pelnia|nów|now)\b|\bmoon\s+phase\b|\bfull\s+moon\b", re.I)


def _age(when=None):
    """Days since the last new moon."""
    when = when or datetime.utcnow()
    return ((when - _NEW).total_seconds() / 86400.0) % SYNODIC


def phase(when=None):
    """(name, lit percent, age in days)."""
    age = _age(when)
    name = next(n for limit, n in _NAMES if age < limit)
    lit = round(50 * (1 - math.cos(2 * math.pi * age / SYNODIC)))
    return name, lit, age


def next_full(when=None):
    when = when or datetime.utcnow()
    age = _age(when)
    days = (SYNODIC / 2 - age) % SYNODIC
    return when + timedelta(days=days)


def next_new(when=None):
    when = when or datetime.utcnow()
    return when + timedelta(days=(SYNODIC - _age(when)) % SYNODIC)


def _say_day(dt):
    """"około 26 października — za 18 dni" (the mean cycle is good to ~a day)."""
    import calc
    d = (dt.date() - datetime.utcnow().date()).days
    if d <= 0:
        return "dziś"
    if d == 1:
        return "jutro"
    return (f"około {dt.day} {calc._MONTHS_GEN[dt.month - 1]} — za {d} "
            f"{calc._plural(d, 'dzień', 'dni', 'dni')}")


def answer(text):
    """The local answer, or None if it isn't a Moon question."""
    low = (text or "").lower()
    if not _ASK.search(low):
        return None
    if re.search(r"kiedy.*(?:nów|now\b)", low):
        return f"Nów będzie {_say_day(next_new())}."
    if re.search(r"kiedy|full moon", low):
        name, _, age = phase()
        if name == "pełnia":
            return "Pełnia jest właśnie teraz — popatrz w niebo, jeśli nie ma chmur!"
        return f"Najbliższa pełnia: {_say_day(next_full())}."
    name, lit, age = phase()
    tail = {"pełnia": " Cała tarcza świeci — mój ulubiony widok!",
            "nów": " Księżyca prawie nie widać — za to gwiazdy lepiej."}.get(name, "")
    return f"Dziś {name} — oświetlone jest około {lit} procent tarczy.{tail}"
