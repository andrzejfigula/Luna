"""
birthdays.py — the family's birthdays.

  "Maja ma urodziny 12 maja", "moje urodziny są 3 marca",
  "urodziny Emilki są 5 czerwca", "Andrzej urodził się 14 lutego 1988"
        → kept with the person in data/people.json ("birthday": "MM-DD",
          "born": year if said)
  "Ile dni do urodzin Mai?", "ile dni do moich urodzin?"
        → counted here, exactly (models are bad at calendar sums)
  on the day: the model is told ("Today is Maja's birthday — she turns 9!"),
  so the first hello is a birthday wish; a week before, it knows it's coming.

Name days the same way: "Maja ma imieniny 3 maja" ("nameday": "MM-DD"),
"kiedy Maja ma imieniny?", and on the day the model knows to wish her.
(Not filled in from a calendar: the family says which day they celebrate.)

Only for people she knows by face (faces.py) — a birthday belongs to someone.
"""

import re
from datetime import date, datetime

from shared_state import state

_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
               "sierpnia", "września", "października", "listopada", "grudnia"]
_SET = re.compile(r"\burodzin\w*|\burodził\w*\s+się|\burodzila\s+sie|\burodzil\s+sie")


def _today():
    return datetime.now().date()


def _date_in(low):
    """(month, day, year or None) for "12 maja", "dwunastego maja 2018", else None."""
    import calc
    for i, m in enumerate(_MONTHS_GEN):
        k = re.search(r"(\w+)(?:\s+(\w+))?\s+" + m + r"\b(?:\s+(\d{4}))?", low)
        if not k:
            continue
        a, b, year = k.group(1), k.group(2), k.group(3)
        day = None
        if b and b.isdigit():
            day = int(b)
        elif b in calc._ORD:
            day = calc._ORD[b] + (calc._ORD.get(a, 0) if a in ("dwudziestego", "trzydziestego")
                                  else 0)
        elif a.isdigit():
            day = int(a)
        elif a in calc._ORD:
            day = calc._ORD[a]
        if day and 1 <= day <= 31:
            return i + 1, day, int(year) if year else None
    return None


def _who(low, text):
    """The person meant: "moje" → whoever is in front of her; else a known
    name (any case form)."""
    import faces
    known = faces.names()
    if re.search(r"\b(moje|moich|mój|moj|mi|ja|urodziłem|urodziłam)\b", low):
        with state.lock:
            if state.person:
                return state.person[0]
    import calc
    words = re.findall(r"\w+", text)
    for i, w in enumerate(words):
        prev = words[i - 1].lower() if i else ""
        if w.lower() in _MONTHS_GEN and (prev.isdigit() or prev in calc._ORD):
            continue                                # "3 maja" is May, not Maja
        hit = faces.match_name(w, known)            # any case form: "Mai" → Maja
        if hit:
            return hit
    return None


def set_from(text):
    """A birthday being told → (name, "MM-DD", year) saved; None if it isn't one."""
    import faces
    low = text.lower()
    if not _SET.search(low) or "ile" in low.split() or low.rstrip().endswith("?"):
        return None
    d = _date_in(low)
    if not d:
        return None
    name = _who(low, text)
    if not name:
        return None
    month, day, year = d
    with faces._lock:
        p = faces._load().get(name)
        if p is None:
            return None
        p["birthday"] = f"{month:02d}-{day:02d}"
        if year:
            p["born"] = year
        faces._save()
    print(f"[birthdays] {name}: {day}.{month}" + (f".{year}" if year else ""), flush=True)
    return name, p["birthday"], year


def _next(md, today):
    m, d = (int(x) for x in md.split("-"))
    for y in (today.year, today.year + 1):
        try:
            when = date(y, m, d)
        except ValueError:                         # 29 February
            when = date(y, 3, 1)
        if when >= today:
            return when


def _all():
    import faces
    with faces._lock:
        return {n: (p.get("birthday"), p.get("born"))
                for n, p in faces._load().items() if p.get("birthday")}


def days_answer(text, today=None):
    """"Ile dni do urodzin Mai?" → the answer, or None."""
    low = text.lower()
    if "urodzin" not in low or not re.search(r"\b(ile|kiedy)\b", low):
        return None
    today = today or _today()
    name = _who(low, text)
    if not name:
        return None
    md, born = _all().get(name, (None, None))
    if not md:
        return (f"Nie wiem jeszcze, kiedy {name} ma urodziny. Powiedz na przykład: "
                f"{name} ma urodziny 12 maja.")
    when = _next(md, today)
    days = (when - today).days
    import calc
    if born:
        n = when.year - born
        age = f" Skończy {n} {calc._plural(n, 'rok', 'lata', 'lat')}."
    else:
        age = ""
    if days == 0:
        return f"To dzisiaj! Wszystkiego najlepszego!{age.replace('Skończy', 'Kończy dziś')}"
    if days == 1:
        return f"Już jutro!{age}"
    phrase = re.search(r"urodzin\s+(\w+)", text, re.I)    # "Mai", as said
    whose = f"urodzin {phrase.group(1)}" if phrase else "urodzin"
    return calc._say_left(whose, days) + age


_AGE = re.compile(r"\bile\s+(?:lat\s+)?(?:ma|mam|masz|skończy|skonczy|kończy|konczy)"
                  r"(?:\s+lat)?\b", re.I)


def age_answer(text, today=None):
    """"Ile lat ma Maja?", "ile mam lat?" → "Maja ma 8 lat, a 12 maja skończy 9."
    None unless the year of birth is known (the model can still try)."""
    low = text.lower()
    if not _AGE.search(low) or "lat" not in low:
        return None
    name = _who(low, text)
    md, born = _all().get(name, (None, None)) if name else (None, None)
    if not born:
        return None
    import calc
    today = today or _today()
    nxt = _next(md, today)
    age = nxt.year - born - (0 if nxt == today else 1)
    with state.lock:
        me = state.person[0] if state.person else None
    who = "Masz" if name == me and re.search(r"\b(mam|ja)\b", low) else f"{name} ma"
    out = f"{who} {age} {calc._plural(age, 'rok', 'lata', 'lat')}"
    if nxt == today:
        return out + " — od dzisiaj! Wszystkiego najlepszego!"
    when = f"{nxt.day} {_MONTHS_GEN[nxt.month - 1]}"
    return out + f", a {when} {'skończysz' if who == 'Masz' else 'skończy'} {age + 1}."


_NAMEDAY = re.compile(r"\bimienin\w*", re.I)


def set_nameday_from(text):
    """"Maja ma imieniny 3 maja" → (name, "MM-DD") saved; None if it isn't one."""
    import faces
    low = text.lower()
    if not _NAMEDAY.search(low) or re.search(r"\b(ile|kiedy)\b", low) or \
            low.rstrip().endswith("?"):
        return None
    d = _date_in(low)
    name = _who(low, text) if d else None
    if not name:
        return None
    month, day, _ = d
    with faces._lock:
        p = faces._load().get(name)
        if p is None:
            return None
        p["nameday"] = f"{month:02d}-{day:02d}"
        faces._save()
    print(f"[birthdays] {name}: name day {day}.{month}", flush=True)
    return name, p["nameday"]


def namedays():
    import faces
    with faces._lock:
        return {n: p["nameday"] for n, p in faces._load().items() if p.get("nameday")}


def nameday_answer(text, today=None):
    """"Kiedy Maja ma imieniny?", "ile dni do imienin Mai?" → the answer, or None."""
    low = text.lower()
    if not _NAMEDAY.search(low) or not re.search(r"\b(ile|kiedy)\b", low):
        return None
    name = _who(low, text)
    if not name:
        return None
    md = namedays().get(name)
    if not md:
        return (f"Nie wiem, kiedy {name} obchodzi imieniny. Powiedz na przykład: "
                f"{name} ma imieniny 3 maja.")
    today = today or _today()
    when = _next(md, today)
    days = (when - today).days
    on = f"{when.day} {_MONTHS_GEN[when.month - 1]}"
    if days == 0:
        return f"Dzisiaj! {name} ma dziś imieniny — wszystkiego najlepszego!"
    if days == 1:
        return f"Już jutro, {on}."
    import calc
    return f"{on.capitalize()} — za {days} {calc._plural(days, 'dzień', 'dni', 'dni')}."


def prompt_line(today=None):
    """Birthdays and name days today or within a week, for the system prompt."""
    today = today or _today()
    out = []
    for name, md in namedays().items():
        when = _next(md, today)
        days = (when - today).days
        if days == 0:
            out.append(f"TODAY is {name}'s name day (imieniny)! Wish them all the best "
                       "when you greet or talk to them.")
        elif days <= 3:
            out.append(f"{name}'s name day (imieniny) is in {days} days.")
    for name, (md, born) in _all().items():
        when = _next(md, today)
        days = (when - today).days
        turns = f" — turns {when.year - born}" if born else ""
        if days == 0:
            out.append(f"TODAY is {name}'s birthday{turns}! Wish them a happy birthday "
                       "warmly when you greet or talk to them.")
        elif days <= 7:
            out.append(f"{name}'s birthday is in {days} days ({when.day}.{when.month}){turns}.")
    return (" ".join(out) + "\n") if out else ""
