"""
agenda.py — the family calendar ("kalendarz"): events on a date, with reminders.
(Not calendar.py: that name is Python's own module.)

  "Dodaj do kalendarza dentysta 12 listopada o 15"
  "Maja ma wycieczkę w przyszły piątek, zapisz w kalendarzu, przypomnij tydzień wcześniej"
  "Co mamy w sobotę?" / "Co w kalendarzu w tym tygodniu?" / "Kiedy dentysta?"
  "Przesuń dentystę na czwartek o 16" / "Odwołaj dentystę" / "Przywróć dentystę"
  "Przepisz zaproszenie do kalendarza" — the camera reads it (brain.read_events)

schedule.py is the repeating week, timers.py the bare reminders: both are shown
here, read-only, with birthdays, name days and holidays (items_on), but kept where
they are. data/calendar.json; ui_agenda.py draws the page, the layout is here so
taps and tests need no pygame. idle_engine calls tick() every few seconds.
"""

import calendar
import json
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import calc
import schedule
from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "calendar.json")
PAGE_SECS = 120                # untouched this long, the page closes
SHOWN_SECS = 20                # opened to show what was just said
EXPECT_SECS = 40               # "Na kiedy?": the next sentence is the answer
LAST_SECS = 10 * 60            # "przypomnij dzień wcześniej" means the event just added
BARE_UNDO_SECS = 120           # a bare "cofnij" — only this soon after
UNDO_SECS = 24 * 3600          # "przywróć dentystę"
GRACE = 10 * 60                # a reminder not said by start + this: dropped
HOLD = 15 * 60                 # for a person: waits this long to see them, then the room
MORNING, EVENING = "08:00", "18:00"   # an all-day event's reminder; "a day before" at
QUIET_FROM, QUIET_TO = 22, 7   # held till morning unless "always"
ALL_DAY_ENDS = 20              # an all-day reminder unsaid by this hour: dropped
MAX_FROM_PAPER = 60
HOUR, DAY, WEEK = 60, 1440, 10080
LEADS = (0, 15, HOUR, 2 * HOUR, DAY, 2 * DAY, WEEK)        # the card's chips
REPEATS = ("none", "week", "2weeks", "month", "year")
REPEAT_SAID = {"none": "nie powtarzaj", "week": "co tydzień", "2weeks": "co dwa tygodnie",
               "month": "co miesiąc", "year": "co roku"}
MONTHS = ("Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień",
          "Wrzesień", "Październik", "Listopad", "Grudzień")
MONTHS_GEN = tuple(calc._MONTHS_GEN)
DAYS_NOM = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
DAYS_SHORT = ("Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd")

_lock = threading.Lock()
_mem = {"mtime": None, "data": None}
_expect = {"until": 0.0, "draft": None, "day": None, "tries": 0}
_last = {"ids": [], "t": 0.0}
_pending = {"what": None, "ids": [], "until": 0.0, "to": None}
_reading = [0.0]


def _now():
    return time.time()


def _today(now=None):
    return datetime.fromtimestamp(now if now is not None else _now()).date()


# ── the data ─────────────────────────────────────────────────────────────────

def _load():
    """A fresh copy (callers change it); read from the card only when it changed."""
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return {"events": [], "trash": []}
    if _mem["mtime"] != mtime:
        try:
            with open(PATH, encoding="utf-8") as f:
                d = json.load(f)
            _mem.update(mtime=mtime, data={"events": d.get("events") or [],
                                           "trash": d.get("trash") or []})
        except (OSError, ValueError):
            return {"events": [], "trash": []}
    return json.loads(json.dumps(_mem["data"]))


def _save(d):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)
    _mem.update(mtime=None, data=None)


def events():
    with _lock:
        return _load()["events"]


def get(eid):
    return next((e for e in events() if e["id"] == eid), None)


def default_leads(at):
    """The evening before, and an hour ahead (an all-day one: that morning)."""
    return [DAY, HOUR] if at else [DAY, 0]


def add(title, day, at=None, end=None, who="", end_date=None, repeat="none", remind=None,
        always=False, note="", by=None, now=None):
    now = now if now is not None else _now()
    e = {"id": uuid.uuid4().hex[:8], "title": title, "date": day.isoformat(),
         "end_date": end_date.isoformat() if end_date and end_date > day else None,
         "at": at or None, "end": end or None, "who": who or "",
         "repeat": repeat if repeat in REPEATS else "none",
         "remind": default_leads(at) if remind is None else sorted(set(remind), reverse=True),
         "always": bool(always), "note": note or "", "by": by, "added": now, "armed": now,
         "skip": [], "said": {}}
    with _lock:
        d = _load()
        d["events"].append(e)
        _save(d)
    _forget_marks()
    return e


def update(eid, now=None, **fields):
    """Changed fields; a new date, time or reminder arms its reminders afresh."""
    with _lock:
        d = _load()
        for e in d["events"]:
            if e["id"] == eid:
                e.update(fields)
                if {"date", "at", "remind", "end_date", "repeat"} & set(fields):
                    e["armed"] = now if now is not None else _now()
                    e["said"] = {}
                _save(d)
                _forget_marks()
                return e
    return None


def remove(eid, now=None):
    """Off the calendar, but "przywróć" brings it back for a day."""
    now = now if now is not None else _now()
    with _lock:
        d = _load()
        gone = next((e for e in d["events"] if e["id"] == eid), None)
        if gone is None:
            return None
        d["events"] = [e for e in d["events"] if e["id"] != eid]
        d["trash"] = [t for t in d["trash"] if now - t["t"] < UNDO_SECS] + [{"t": now, "e": gone}]
        _save(d)
    _forget_marks()
    return gone


def restore(words="", now=None):
    """The last one removed, or the one these words name. The event, or None."""
    now = now if now is not None else _now()
    with _lock:
        d = _load()
        kept = [t for t in d["trash"] if now - t["t"] < UNDO_SECS]
        pick = next((t for t in reversed(kept) if not words or _names(t["e"], words)), None)
        if pick is None:
            return None
        d["trash"] = [t for t in d["trash"] if t is not pick]
        d["events"].append(pick["e"])
        _save(d)
    _forget_marks()
    return pick["e"]


# ── when it happens ──────────────────────────────────────────────────────────

def _d(s):
    return date.fromisoformat(s)


def _span(e):
    return (_d(e["end_date"]) - _d(e["date"])).days if e.get("end_date") else 0


def _add_months(d, n):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def occurrences(e, a, b):
    """The start dates of `e`'s occurrences touching the days a..b."""
    start, span, rep = _d(e["date"]), _span(e), e.get("repeat") or "none"
    skip = set(e.get("skip") or [])
    out = []
    if start > b:
        return out
    if rep == "none":
        out = [start] if start + timedelta(days=span) >= a else []
    elif rep in ("week", "2weeks"):
        step = 7 if rep == "week" else 14
        k = max(0, ((a - timedelta(days=span)) - start).days // step)
        cur = start + timedelta(days=k * step)
        while cur <= b:
            if cur + timedelta(days=span) >= a:
                out.append(cur)
            cur += timedelta(days=step)
    else:
        step = 1 if rep == "month" else 12
        k = max(0, ((a.year - start.year) * 12 + a.month - start.month - 1) // step)
        while True:
            cur = _add_months(start, k * step)
            if cur > b:
                break
            if cur + timedelta(days=span) >= a:
                out.append(cur)
            k += 1
    return [c for c in out if c.isoformat() not in skip]


def next_of(e, today=None):
    """The next day it starts (or is still on), or None."""
    today = today or _today()
    got = occurrences(e, today, today + timedelta(days=800))
    return got[0] if got else None


def _at_ts(day, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return time.mktime((day.year, day.month, day.day, h, m, 0, 0, 0, -1))


def start_ts(e, day):
    return _at_ts(day, e.get("at") or MORNING)


def due_ts(e, day, lead):
    """When a reminder `lead` minutes ahead is said: a day or more ahead, in the
    evening; an all-day event's own at 8."""
    if lead >= DAY:
        return _at_ts(day - timedelta(days=lead // DAY), EVENING)
    if not e.get("at"):
        return _at_ts(day, MORNING)
    return start_ts(e, day) - lead * 60


def _expiry(e, day):
    if e.get("at"):
        return start_ts(e, day) + GRACE
    return _at_ts(day, f"{ALL_DAY_ENDS:02d}:00")


def due(now=None):
    """(event, day, lead, due time, [leads this one uses up]) said now — only the
    nearest of those due, the earlier ones are stale by then."""
    now = now if now is not None else _now()
    today = _today(now)
    out = []
    for e in events():
        leads = e.get("remind") or []
        if not leads:
            continue
        ahead = max(leads) // DAY + 1
        armed, said = e.get("armed") or 0, e.get("said") or {}
        for day in occurrences(e, today, today + timedelta(days=ahead)):
            if day < today or now > _expiry(e, day):
                continue
            key = day.isoformat()
            times = [(due_ts(e, day, lead), lead) for lead in leads]
            live = [(t, lead) for t, lead in times if t >= armed]
            if not live and e.get("at") and start_ts(e, day) >= armed:
                live = [(start_ts(e, day), 0)]         # set too late for them: at its start
            ripe = [(t, lead) for t, lead in live if t <= now and f"{key}|{lead}" not in said]
            if ripe:
                t, lead = max(ripe)
                out.append((e, day, lead, t, [x for _, x in ripe]))
    return out


def _mark(eid, day, leads, now):
    with _lock:
        d = _load()
        for e in d["events"]:
            if e["id"] == eid:
                said = e.setdefault("said", {})
                for lead in leads:
                    said[f"{day.isoformat()}|{lead}"] = now
                cut = (_today(now) - timedelta(days=7)).isoformat()
                e["said"] = {k: v for k, v in said.items() if k.split("|")[0] >= cut}
                _save(d)
                return


def _quiet(now):
    h = time.localtime(now).tm_hour
    return h >= QUIET_FROM or h < QUIET_TO


def tick(now, person, someone, can_speak, busy, speak):
    """Say what is due: to its person when she sees them, after HOLD to whoever is
    there or the room; the whole house's at once. Not at night, not in front of a
    guest, not over her own speech. Returns how many were said."""
    import faces
    said = 0
    if busy:
        return 0
    for e, day, lead, t, leads in due(now):
        if faces.guest_here():
            continue
        always = bool(e.get("always"))
        if not always and (not can_speak or _quiet(now)):
            continue
        owner = e.get("who") or ""
        here = bool(person or someone)
        if owner and person != owner and not always and now - t < HOLD:
            continue
        to = person if person and faces.is_family(person) else None
        text = phrase(e, day, to, now)
        _mark(e["id"], day, leads, now)
        print(f"[agenda] reminding {to or 'the room'}: {text}", flush=True)
        if not here:                          # nobody seen: a chime first, like a timer
            try:
                from commands import wake_up
                wake_up("agenda")
                from text_to_speech import play_sound
                play_sound("chime", can_drop=False)
            except Exception:
                pass
        speak(text)
        _after_ring(e, text)
        said += 1
    return said


def _after_ring(e, text):
    """"Jeszcze 5 minut" works as after a timer, and no wake word is needed for it."""
    try:
        import brain
        import timers
        timers._last_rang.update(t=_now(), entry={"label": e["title"], "kind": "reminder", "say": None})
        brain.note_said(text)
    except Exception:
        pass
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = _now()


# ── how she says it ──────────────────────────────────────────────────────────

_PREP = re.compile(r"^(?:do|na|u|w|we|z|ze|po|nad|pod|od|przy)\s", re.I)


def _cap(s):
    return s[:1].upper() + s[1:]


def _clock(at):
    import clock
    h, m = (int(x) for x in at.split(":"))
    return f"o {clock.hour_locative(h, m)}"


def day_said(day, today=None):
    """"dziś", "jutro", "w piątek", "w środę 12 listopada"."""
    today = today or _today()
    n = (day - today).days
    if n == 0:
        return "dziś"
    if n == 1:
        return "jutro"
    if n == 2:
        return "pojutrze"
    if 0 < n < 7:
        return calc._on_day(day)
    out = f"{calc._on_day(day)} {day.day} {MONTHS_GEN[day.month - 1]}"
    return out + f" {day.year}" if day.year != today.year and n > 200 else out


def when_said(e, day=None, today=None):
    today = today or _today()
    day = day or next_of(e, today) or _d(e["date"])
    out = day_said(day, today)
    if e.get("end_date"):
        last = day + timedelta(days=_span(e))
        out += f" (do {last.day} {MONTHS_GEN[last.month - 1]})"
    return out + (f" {_clock(e['at'])}" if e.get("at") else "")


def in_days(day, today=None):
    n = (day - (today or _today())).days
    return ("dziś" if n == 0 else "jutro" if n == 1 else "pojutrze" if n == 2 else
            f"za {n} dni" if n > 0 else "minęło")


def phrase(e, day, to, now=None):
    """The reminder in her words, to `to` (a name) or to the room (None)."""
    import faces
    import timers
    now = now if now is not None else _now()
    today = _today(now)
    left = (start_ts(e, day) - now) / 60.0
    if e.get("at") and day == today and 0 < left < 60:
        when = f"za {timers.say_duration(int(round(left)) * 60)}"
    elif e.get("at") and day == today and left <= 0:
        when = "teraz"
    else:
        when = when_said(e, day, today)
    title, owner = e["title"], e.get("who") or ""
    acc = schedule.title_after_ma(title)
    plain = bool(_PREP.match(title))           # "do dentysty": no "masz" in front of it
    voc = (faces.vocatives().get(to) or to) if to else ""
    if owner and to == owner:
        body = f"{voc}, {when} — {title}." if plain else f"{voc}, {when} masz {acc}."
    else:
        head = f"{voc}, przypominam: " if to else "Przypominam: "
        if owner:
            body = head + (f"{owner} {when} — {title}." if plain else f"{owner} {when} ma {acc}.")
        else:
            body = head + f"{when} — {title}."
    if e.get("note"):
        body += f" Pamiętaj: {e['note']}."
    return body


def _lead_said(lead, at):
    if lead == 0:
        return "o czasie" if at else "tego dnia rano"
    if lead == 15:
        return "kwadrans przed"
    if lead == 30:
        return "pół godziny przed"
    if lead == HOUR:
        return "godzinę przed"
    if lead < DAY:
        import timers
        return f"{timers.say_duration(lead * 60)} przed"
    if lead == DAY:
        return "dzień wcześniej wieczorem"
    if lead == WEEK:
        return "tydzień wcześniej"
    return f"{lead // DAY} dni wcześniej"


def reminders_said(e, now=None):
    """"Przypomnę dzień wcześniej wieczorem i godzinę przed." — the ones still ahead."""
    now = now if now is not None else _now()
    leads = e.get("remind") or []
    if not leads:
        return "Bez przypomnienia."
    day = next_of(e, _today(now)) or _d(e["date"])
    live = [x for x in leads if due_ts(e, day, x) > now]
    if not live:
        return "Przypomnę, gdy się zacznie." if e.get("at") and start_ts(e, day) > now else ""
    return "Przypomnę " + " i ".join(_lead_said(x, e.get("at")) for x in live) + "."


def _conflict(e):
    """Something else at that time, for the same person or the whole house."""
    if not e.get("at"):
        return ""
    day, who = _d(e["date"]), e.get("who") or ""
    a = schedule._mins(e["at"])
    b = schedule._mins(e["end"]) if e.get("end") else a + 60
    for it in items_on(day, who or None):
        if it["kind"] not in ("event", "plan") or it.get("id") == e["id"] or not it.get("at"):
            continue
        s = schedule._mins(it["at"])
        t = schedule._mins(it["end"]) if it.get("end") else s + 60
        if s < b and a < t:
            whose = f" ({it['who']})" if it.get("who") and it["who"] != who else ""
            return f"Uwaga: o {it['at']} jest już {it['title']}{whose}."
    return ""


def _whose(e):
    """"Maja: " in speech; nothing when it's the speaker's own."""
    who = e.get("who")
    return f"{who}: " if who and who != _speaker() else ""


def _confirm(e, now=None):
    what = _whose(e) + e["title"]
    return " ".join(x for x in (f"Zapisałam: {what}, {when_said(e)}.", _conflict(e),
                                reminders_said(e, now)) if x)


# ── what she hears: a date, a time, a repeat, a reminder ─────────────────────

_ORD = "|".join(sorted(calc._ORD, key=len, reverse=True))
_MON = "|".join(MONTHS_GEN)
_DAYN = rf"(?:\d{{1,2}}(?:-?go|-?tego|\.)?|(?:dwudziestego|trzydziestego)\s+(?:{_ORD})|{_ORD})"
_WD_ACC = (r"poniedziałek|poniedzialek", r"wtorek", r"środę|środa|srode|sroda",
           r"czwartek", r"piątek|piatek", r"sobotę|sobota|sobote", r"niedzielę|niedziela|niedziele")
_WD_ANY = "|".join(_WD_ACC)
_WD_GEN = ("poniedziałku|poniedzialku", "wtorku", "środy|srody", "czwartku", "piątku|piatku",
           "soboty", "niedzieli")
_WD_GEN_ANY = "|".join(_WD_GEN)
_MONTH_LOC = ("styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu", "lipcu", "sierpniu",
              "wrześniu", "październiku", "listopadzie", "grudniu")
_MONTH_ACC = ("styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień",
              "wrzesień", "październik", "listopad", "grudzień")
_NUM = {"jeden": 1, "jedna": 1, "jedną": 1, "dwa": 2, "dwie": 2, "trzy": 3, "cztery": 4,
        "pięć": 5, "piec": 5, "sześć": 6, "szesc": 6, "siedem": 7, "osiem": 8, "dziewięć": 9,
        "dziesięć": 10, "piętnaście": 15, "dwadzieścia": 20, "trzydzieści": 30,
        "czterdzieści": 40}
_NUM_ANY = r"\d{1,3}|" + "|".join(_NUM)


def _num(s, default=1):
    if not s:
        return default
    return int(s) if s.isdigit() else _NUM.get(s, default)


def _wd_index(word):
    return next(i for i, alts in enumerate(_WD_ACC) if re.fullmatch(alts, word))


def _wd_gen_index(word):
    return next(i for i, alts in enumerate(_WD_GEN) if re.fullmatch(alts, word))


def _day_num(s):
    s = s.strip().rstrip(".")
    m = re.match(r"\d{1,2}", s)
    if m:
        return int(m.group())
    return sum(calc._ORD.get(p, 0) for p in s.split()) or None


def _dated(y, m, d, today, year_said=False):
    """A date; without a year the next time it comes."""
    for k in (0, 1):
        try:
            got = date(y + k, m, d)
        except ValueError:
            continue
        if year_said or got >= today:
            return got
    return None


def _next_week_day(today, wd):
    return today + timedelta(days=7 - today.weekday() + wd)


def _feasts(y):
    """(date, name, a statutory day off) — Polish holidays and the family's days."""
    e = calc._easter(y)
    one = timedelta(days=1)
    return [(date(y, 1, 1), "Nowy Rok", True), (date(y, 1, 6), "Trzech Króli", True),
            (date(y, 1, 21), "Dzień Babci", False), (date(y, 1, 22), "Dzień Dziadka", False),
            (date(y, 2, 14), "Walentynki", False), (e - 52 * one, "Tłusty czwartek", False),
            (date(y, 3, 8), "Dzień Kobiet", False), (e, "Wielkanoc", False),
            (e + one, "Poniedziałek Wielkanocny", True), (date(y, 5, 1), "Święto Pracy", True),
            (date(y, 5, 3), "Święto Konstytucji 3 Maja", True),
            (date(y, 5, 26), "Dzień Matki", False), (e + 49 * one, "Zielone Świątki", False),
            (e + 60 * one, "Boże Ciało", True), (date(y, 6, 1), "Dzień Dziecka", False),
            (date(y, 6, 23), "Dzień Ojca", False), (date(y, 8, 15), "Wniebowzięcie NMP", True),
            (date(y, 11, 1), "Wszystkich Świętych", True),
            (date(y, 11, 11), "Święto Niepodległości", True),
            (date(y, 11, 30), "Andrzejki", False), (date(y, 12, 6), "Mikołajki", False),
            (date(y, 12, 24), "Wigilia", y >= 2025), (date(y, 12, 25), "Boże Narodzenie", True),
            (date(y, 12, 26), "Drugi dzień świąt", True), (date(y, 12, 31), "Sylwester", False)]


_FEAST_SAID = (("wigili[ęea]", "Wigilia"), ("sylwestra?", "Sylwester"),
               ("(?:boże|boze)\\s+narodzenie", "Boże Narodzenie"), ("wielkanoc", "Wielkanoc"),
               ("mikołajki|mikolajki", "Mikołajki"), ("walentynki", "Walentynki"),
               ("andrzejki", "Andrzejki"), ("nowy\\s+rok", "Nowy Rok"),
               ("dzień\\s+matki|dzien\\s+matki", "Dzień Matki"),
               ("dzień\\s+ojca|dzien\\s+ojca", "Dzień Ojca"),
               ("dzień\\s+dziecka|dzien\\s+dziecka", "Dzień Dziecka"),
               ("dzień\\s+babci|dzien\\s+babci", "Dzień Babci"),
               ("dzień\\s+dziadka|dzien\\s+dziadka", "Dzień Dziadka"),
               ("boże\\s+ciało|boze\\s+cialo", "Boże Ciało"),
               ("tłusty\\s+czwartek|tlusty\\s+czwartek", "Tłusty czwartek"))


def _feast_day(name, today):
    for y in (today.year, today.year + 1):
        for d, n, _ in _feasts(y):
            if n == name and d >= today:
                return d
    return None


def _cut(low, m):
    return (low[:m.start()] + " " + low[m.end():]).strip()


def parse_date(low, today):
    """(first day, last day or None, the text without them), or None. `low` is
    lower case. A weekday: the next one ("w przyszły": in the next calendar week)."""
    # od 20 grudnia do 3 stycznia, od 12 do 15 listopada
    m = re.search(rf"\bod\s+({_DAYN})(?:\s+({_MON}))?\s+do\s+({_DAYN})\s+({_MON})"
                  r"(?:\s+(\d{4}))?\b", low)
    if m:
        end_mon = MONTHS_GEN.index(m.group(4)) + 1
        start_mon = MONTHS_GEN.index(m.group(2)) + 1 if m.group(2) else end_mon
        year = int(m.group(5)) if m.group(5) else None
        a = _dated(year or today.year, start_mon, _day_num(m.group(1)), today, bool(year))
        if a:
            b = _dated(a.year, end_mon, _day_num(m.group(3)), a)
            if b:
                return a, b, _cut(low, m)
    # od poniedziałku do środy, od jutra do piątku
    m = re.search(rf"\bod\s+(?:(jutra|dziś|dzisiaj)|({_WD_GEN_ANY}))\s+do\s+({_WD_GEN_ANY})\b", low)
    if m:
        wd2 = _wd_gen_index(m.group(3))
        if m.group(1):
            a = today + timedelta(days=1 if m.group(1) == "jutra" else 0)
        else:
            a = today + timedelta(days=(_wd_gen_index(m.group(2)) - today.weekday()) % 7 or 7)
        return a, a + timedelta(days=(wd2 - a.weekday()) % 7), _cut(low, m)
    # (w środę) 12 listopada (2027)
    m = re.search(rf"(?:\b(?:w|we|na)\s+(?:{_WD_ANY}),?\s+)?(?:\b(?:na|dnia|w\s+dniu)\s+)?"
                  rf"\b({_DAYN})\s+({_MON})\b(?:\s+(\d{{4}})(?:\s+r(?:oku|\.)?)?)?", low)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        got = _dated(year or today.year, MONTHS_GEN.index(m.group(2)) + 1, _day_num(m.group(1)),
                     today, bool(year))
        if got:
            return got, None, _cut(low, m)
    # 12.11, 12.11.2026, 12/11 — but "o 10.30" is a time
    for m in re.finditer(r"(?:\b(?:na|dnia)\s+)?\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}|\d{2}))?\b", low):
        before = low[:m.start()].split()
        if before and before[-1] in ("o", "od", "do", "godz", "godz.", "godzinie"):
            continue
        d_, mon = int(m.group(1)), int(m.group(2))
        if 1 <= mon <= 12 and 1 <= d_ <= 31:
            y = m.group(3)
            year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else None
            got = _dated(year or today.year, mon, d_, today, bool(year))
            if got:
                return got, None, _cut(low, m)
    # w Wigilię, na Wielkanoc
    for rx, name in _FEAST_SAID:
        m = re.search(rf"\b(?:w|we|na)\s+(?:{rx})\b", low)
        if m:
            got = _feast_day(name, today)
            if got:
                return got, None, _cut(low, m)
    # w (przyszły) weekend
    m = re.search(r"\b(?:w|na)\s+(?:(ten|tym|najbliższy|najblizszy|przyszły|przyszly|następny|"
                  r"nastepny)\s+)?weekend\b", low)
    if m:
        word = m.group(1) or ""
        sat = (today + timedelta(days=(5 - today.weekday()) % 7))
        if word.startswith(("przysz", "nast")):
            sat = _next_week_day(today, 5)
        return sat, sat + timedelta(days=1), _cut(low, m)
    # w przyszłym tygodniu w środę / w środę w przyszłym tygodniu
    next_wk = r"(?:w\s+)(?:przyszłym|przyszlym|następnym|nastepnym)\s+tygodniu"
    m = re.search(rf"\b{next_wk}\s+(?:w|we|na)\s+({_WD_ANY})\b|\b(?:w|we|na)\s+({_WD_ANY})\s+{next_wk}\b", low)
    if m:
        return _next_week_day(today, _wd_index(m.group(1) or m.group(2))), None, _cut(low, m)
    # w sobotę za tydzień / za tydzień w sobotę
    m = re.search(rf"\b(?:w|we|na)\s+({_WD_ANY})\s+za\s+tydzień\b|\bza\s+tydzień\s+(?:w|we|na)\s+({_WD_ANY})\b", low)
    if m:
        wd = _wd_index(m.group(1) or m.group(2))
        return today + timedelta(days=((wd - today.weekday()) % 7 or 7) + 7), None, _cut(low, m)
    # w sobotę, w ten piątek, w przyszłą środę
    m = re.search(rf"\b(?:w|we|na)\s+(?:(ten|tę|tą|te|najbliższ\w+|najblizsz\w+|przyszł\w+|"
                  rf"przyszl\w+|następn\w+|nastepn\w+)\s+)?({_WD_ANY})\b", low)
    if m:
        wd = _wd_index(m.group(2))
        if (m.group(1) or "").startswith(("przysz", "nast")):
            return _next_week_day(today, wd), None, _cut(low, m)
        return today + timedelta(days=(wd - today.weekday()) % 7 or 7), None, _cut(low, m)
    # dziś, jutro, pojutrze
    m = re.search(r"\b(?:na\s+)?(dziś|dzis|dzisiaj|jutro|pojutrze)\b", low)
    if m:
        n = {"jutro": 1, "pojutrze": 2}.get(m.group(1), 0)
        return today + timedelta(days=n), None, _cut(low, m)
    # za 3 dni, za dwa tygodnie, za miesiąc, za rok
    m = re.search(rf"\bza\s+(?:({_NUM_ANY})\s+)?(dzień|dzien|dni|tydzień|tydzien|tygodni\w*|"
                  r"miesiąc|miesiac|miesiące|miesiace|miesięcy|miesiecy|rok|lata|lat)\b", low)
    if m:
        n, unit = _num(m.group(1)), m.group(2)
        if unit.startswith("dz") or unit == "dni":
            return today + timedelta(days=n), None, _cut(low, m)
        if unit.startswith("ty"):
            return today + timedelta(days=7 * n), None, _cut(low, m)
        months = n if unit.startswith("mies") else 12 * n
        return _add_months(today, months), None, _cut(low, m)
    # (na) dwunastego — the next 12th
    m = re.search(rf"(?:\bna\s+)?\b(?:(?:dwudziestego|trzydziestego)\s+)?(?:{_ORD})\b", low)
    if m:
        n = _day_num(re.sub(r"^na\s+", "", m.group(0)))
        if n and 1 <= n <= 31:
            for k in range(0, 3):
                y, mon = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
                try:
                    got = date(y, mon, n)
                except ValueError:
                    continue
                if got >= today:
                    return got, None, _cut(low, m)
    return None


def parse_range(low, today):
    """(first, last, the rest) for a question: days, a week, a month. None if none."""
    m = re.search(r"\bw\s+tym\s+tygodniu\b", low)
    if m:
        return today, today + timedelta(days=6 - today.weekday()), _cut(low, m)
    m = re.search(r"\bw\s+(?:przyszłym|przyszlym|następnym|nastepnym)\s+tygodniu\b", low)
    if m:
        a = _next_week_day(today, 0)
        return a, a + timedelta(days=6), _cut(low, m)

    def month_of(y, mon):
        return date(y, mon, 1), date(y, mon, calendar.monthrange(y, mon)[1])
    m = re.search(r"\bw\s+tym\s+miesiącu\b|\bw\s+tym\s+miesiacu\b", low)
    if m:
        return today, month_of(today.year, today.month)[1], _cut(low, m)
    m = re.search(r"\bw\s+(?:przyszłym|przyszlym|następnym|nastepnym)\s+(?:miesiącu|miesiacu)\b", low)
    if m:
        a = _add_months(today.replace(day=1), 1)
        return (*month_of(a.year, a.month), _cut(low, m))
    m = re.search(rf"\b(?:w\s+({'|'.join(_MONTH_LOC)})|na\s+({'|'.join(_MONTH_ACC)}))\b", low)
    if m:
        mon = (_MONTH_LOC.index(m.group(1)) if m.group(1) else _MONTH_ACC.index(m.group(2))) + 1
        y = today.year + (1 if mon < today.month else 0)
        return (*month_of(y, mon), _cut(low, m))
    got = parse_date(low, today)
    if got:
        a, b, rest = got
        return a, b or a, rest
    return None


_LEAD_UNIT = (r"minut\w*|kwadrans\w*|godzin\w*|dzień|dzien|dni|dnia|tydzień|tydzien|tygodni\w*|"
              r"miesiąc|miesiac")
_LEAD_RX = (rf"(?:(?:(pół|pol|półtorej|poltorej)|({_NUM_ANY}))\s+)?({_LEAD_UNIT})\s+"
            r"(?:wcześniej|wczesniej|przed\b(?:\s+(?:czasem|tym|wydarzeniem))?)")
_LEAD_CHAIN = re.compile(rf"\b({_LEAD_UNIT})\s+(?:i|oraz)\s+(?=(?:\S+\s+)?(?:{_LEAD_UNIT})\s+"
                         r"(?:wcześniej|wczesniej|przed)\b)")
_REMIND_WORD = re.compile(r"\b(?:(?:i|oraz)\s+)?(?:(?:z\s+)?przypomnieni\w+|przypomnij|przypominaj)"
                          r"(?:\s+(?:mi|nam|jej|mu|im|o\s+tym))*\b")
_NO_REMIND = re.compile(r"\b(?:i\s+)?(?:bez\s+przypomnie\w+|nie\s+przypominaj(?:\s+(?:mi|nam|o\s+tym))*)\b")
_ALWAYS = re.compile(r"\b(?:i\s+)?(?:powiedz\s+na\s+głos|powiedz\s+na\s+glos|zawsze\s+na\s+głos|"
                     r"nawet\s+(?:gdy|jak|kiedy)\s+nikogo\s+nie\s+ma)\b")


def _lead_mins(half, n, unit):
    if half:
        whole = 30 if half.startswith("p") and "tor" not in half else 90
        return whole if unit.startswith("godzin") else None
    k = _num(n)
    if unit.startswith("minut"):
        return k
    if unit.startswith("kwadrans"):
        return 15 * k
    if unit.startswith("godzin"):
        return HOUR * k
    if unit.startswith(("dz", "dn")):
        return DAY * k
    if unit.startswith("ty"):
        return WEEK * k
    return 30 * DAY * k


def remind_of(low):
    """(minutes ahead or None for the usual, always?, the text without them)."""
    always = bool(_ALWAYS.search(low))
    low = _ALWAYS.sub(" ", low)
    if _NO_REMIND.search(low):
        return [], always, _NO_REMIND.sub(" ", low)
    leads = []
    low = _LEAD_CHAIN.sub(r"\1 wcześniej i ", low)      # "tydzień i godzinę wcześniej"

    def take(m):
        k = _lead_mins(m.group(1), m.group(2), m.group(3))
        if k is not None:
            leads.append(k)
        return " "
    low = re.sub(rf"(?:\b(?:i|oraz|a\s+także)\s+)?\b{_LEAD_RX}", take, low)
    m = re.search(r"\b(?:tego\s+dnia\s+rano|rano\s+tego\s+dnia|w\s+dniu\s+wydarzenia)\b", low)
    if m and _REMIND_WORD.search(low):
        leads.append(0)
        low = _cut(low, m)
    low = _REMIND_WORD.sub(" ", low)
    return (sorted(set(leads), reverse=True) if leads else None), always, low


_REPEAT_RX = ((re.compile(r"\b(?:co\s+rok|co\s+roku|każdego\s+roku|kazdego\s+roku|corocznie|rokrocznie)\b"), "year"),
              (re.compile(r"\bco\s+(?:dwa|2)\s+tygodnie\b"), "2weeks"),
              (re.compile(r"\b(?:co\s+tydzień|co\s+tydzien|każdego\s+tygodnia|kazdego\s+tygodnia)\b"), "week"),
              (re.compile(r"\b(?:co\s+miesiąc|co\s+miesiac|każdego\s+miesiąca|kazdego\s+miesiaca)\b"), "month"))
_EVERY_WD = re.compile(rf"\b(?:co|w\s+każd\w+|w\s+kazd\w+|każd\w+|kazd\w+)\s+({_WD_ANY})\b")


def repeat_of(low):
    for rx, kind in _REPEAT_RX:
        if rx.search(low):
            return kind, rx.sub(" ", low)
    m = _EVERY_WD.search(low)
    if m:                                      # "co piątek": the next one, then weekly
        return "week", low[:m.start()] + f" w {m.group(1)} " + low[m.end():]
    return "none", low


_WORDS_FIRST = re.compile(
    r"^(?:(?:że|ze|żeby|zeby|aby|to|i|a|oraz|mam|mamy|masz|ma|mają|maja\s+mieć|będzie|bedzie|"
    r"będę|bede|będziemy|bedziemy|jest|są|idę|ide|idziemy|jadę|jade|jedziemy|muszę|musze|"
    r"musimy|iść|isc|jechać|jechac|nowe|nowy|proszę|prosze|moje|moja|mój|moj|nasze|nasza|"
    r"nasz|wydarzenie|termin|o\s+tym|coś|cos)\s+)+", re.I)
_WORDS_LAST = re.compile(
    r"(?:\s+(?:i|a|oraz|to|w|we|na|o|że|ze|z|dnia|godzinie|godz|zapisz|dodaj|wpisz|dopisz|"
    r"wstaw|proszę|prosze|tam|mi|nam|ok|okej|rano|wieczorem))+$", re.I)
_NOM_KEEP = {"imię", "zwierzę", "kurczę", "książę", "niemowlę", "się", "cię", "mię"}
_TITLE_MAX = 80


def _nominative(title):
    """"wycieczkę szkolną" → "wycieczka szkolna": the page shows it, a reminder bends it."""
    words = title.split(" ")
    w = words[0]
    if len(w) > 3 and w.endswith("ę") and w.lower() not in _NOM_KEEP:
        words[0] = w[:-1] + "a"
        if len(words) > 1 and words[1].endswith("ą") and len(words[1]) > 3:
            words[1] = words[1][:-1] + "a"
    return " ".join(words)


def _clean_title(s, original=""):
    s = re.sub(r"\b(?:rano|wieczorem|po\s+południu|po\s+poludniu|popołudniu|"
               r"(?:do|w|na)\s+kalendarz\w*|kalendarz\w*)\b", " ", s)
    s = " ".join(re.sub(r"[,;:!?]+", " ", s).split()).strip(" .-–—")
    prev = None
    while prev != s:
        prev = s
        s = _WORDS_FIRST.sub("", s + " ").strip()
        s = _WORDS_LAST.sub("", " " + s).strip()
    if not s or s in ("wydarzenie", "termin", "coś", "to"):
        return ""
    if original:                               # as it was said: "u dr Nowak", not "u dr nowak"
        m = re.search(re.escape(s).replace(r"\ ", r"\s+"), original, re.I)
        if m and len(m.group(0).split()) == len(s.split()):
            s = " ".join(m.group(0).split())
    return _nominative(s)[:_TITLE_MAX]


def _speaker():
    return schedule._speaker()


def _outsider():
    """A guest, or a stranger in front of her (as for the contact cards)."""
    import settings_page
    return settings_page._outsider_here()


def _who_in(low, speaker):
    who, rest = schedule._who_of(low)
    if who and re.search(rf"\b(?:z|ze|u|do|od)\s+{re.escape(who[:3].lower())}", low):
        return speaker or "", low              # "spotkanie z Andrzejem" isn't Andrzej's own
    if who is not None:
        return who, rest
    if re.search(r"\b(?:mamy|nasz\w*|idziemy|jedziemy|będziemy|bedziemy|musimy)\b", low):
        return "", rest
    return speaker or "", rest


def parse(text, speaker=None, day=None, now=None):
    """A sentence → {title, date, end_date, at, end, who, repeat, remind, always}."""
    now = now if now is not None else _now()
    today = _today(now)
    original = text
    low = _norm(text)
    remind, always, low = remind_of(low)
    rep, low = repeat_of(low)
    a, b = day, None
    got = parse_date(low, today)
    if got:
        a, b, low = got
    at, end, low = schedule._time_of(low)
    if at and a == today and schedule._mins(at) * 60 + _midnight(now) < now:
        h, m = at.split(":")
        if int(h) < 12:                        # "dziś o ósmej" said at 15:00: 20:00
            at = f"{int(h) + 12:02d}:{m}"
    who, low = _who_in(low, speaker)
    return {"title": _clean_title(low, original), "date": a, "end_date": b, "at": at or None,
            "end": end or None, "who": who, "repeat": rep, "remind": remind, "always": always}


def _midnight(now):
    return time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))


# ── which event is meant ─────────────────────────────────────────────────────

_SMALL = {"do", "na", "u", "w", "we", "z", "ze", "po", "o", "i", "a", "ten", "ta", "to", "tę",
          "tą", "tego", "tej", "mój", "moj", "moją", "moja", "mam", "mamy", "ma", "jest",
          "będzie", "bedzie", "nasz", "nasza", "naszą", "wydarzenie", "termin", "wizyta",
          "wizytę", "wizyty", "spotkanie", "spotkania"}


_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def _same(a, b):
    """The same word, bent: "dentyście" ~ "dentysta"."""
    a, b = a.translate(_FOLD), b.translate(_FOLD)
    n = max(3, min(len(a), len(b)) - 2)
    return a[:n] == b[:n]


def _words(s):
    return [w for w in re.findall(r"[\wąćęłńóśźż-]+", s.lower()) if w not in _SMALL]


def _names(e, words):
    """Do these words name this event? All of them, its title or its person."""
    want = _words(words)
    title = re.findall(r"[\wąćęłńóśźż-]+", e["title"].lower())
    who = (e.get("who") or "").lower()
    if not want:
        title_words = _words(e["title"])
        said = re.findall(r"[\wąćęłńóśźż-]+", words.lower())
        return bool(said) and not title_words and all(any(_same(w, t) for t in title) for w in said)
    return all(any(_same(w, t) for t in title) or (who and _same(w, who)) for w in want) \
        and any(any(_same(w, t) for t in title) for w in want)


def find(words, today=None):
    """The upcoming events these words name, nearest first."""
    today = today or _today()
    got = []
    for e in events():
        if _names(e, words):
            n = next_of(e, today)
            if n:
                got.append((n, e))
    got.sort(key=lambda p: (p[0], p[1].get("at") or ""))
    return [e for _, e in got]


# ── everything on a day: the events, and what the rest of her knows ───────────

def _item(kind, at, title, who="", end=None, eid=None):
    return {"kind": kind, "at": at or "", "end": end, "title": title, "who": who or "", "id": eid}


def _feast_on(d):
    return [(n, off) for f, n, off in _feasts(d.year) if f == d]


def items_on(d, who=None, plan=True):
    """What is on a day, by time: "event" (can be changed here), "plan", "reminder",
    "birthday", "nameday", "feast". `who`: theirs and the whole house's."""
    out = []
    for e in events():
        if who and (e.get("who") or "") not in (who, ""):
            continue
        for s in occurrences(e, d, d):
            first = s == d
            out.append(_item("event", e.get("at") if first else "", e["title"], e.get("who"),
                             e.get("end") if first else None, e["id"]))
    if plan:
        try:
            for r in schedule.week_rows(d.weekday(), who):
                title = "szkoła" if r.get("kind") == "school" else r["title"]
                out.append(_item("plan", r["at"], title, r.get("who"), r.get("end")))
        except Exception:
            pass
    out += _reminders_on(d)
    out += _people_days_on(d, who)
    out += [_item("feast", "", n) for n, _ in _feast_on(d)]
    order = {"feast": 0, "birthday": 1, "nameday": 2}
    return sorted(out, key=lambda i: (i["at"] or "", order.get(i["kind"], 3)))


def _reminders_on(d):
    try:
        import timers
        with timers._lock:
            rows = list(timers._timers)
        out = []
        for t in rows:
            if t.get("kind") == "reminder" and datetime.fromtimestamp(t["due"]).date() == d:
                at = time.strftime("%H:%M", time.localtime(t["due"]))
                out.append(_item("reminder", at, t.get("label") or "przypomnienie"))
        return out
    except Exception:
        return []


def _people_days_on(d, who=None):
    out = []
    try:
        import birthdays
        md = d.strftime("%m-%d")
        for name, (m, born) in birthdays._all().items():
            if m == md and (not who or who == name):
                age = f" ({d.year - born})" if born else ""
                out.append(_item("birthday", "", f"urodziny: {name}{age}", name))
        for name, m in birthdays.namedays().items():
            if m == md and (not who or who == name):
                out.append(_item("nameday", "", f"imieniny: {name}", name))
    except Exception:
        pass
    return out


_marks = {"key": None, "data": None}


_rows = {"key": None, "data": None}


def _forget_marks():
    _marks.update(key=None, data=None)
    _rows.update(key=None, data=None)


def month_marks(y, m, who=None):
    """{day number: {"who": [names, "" for the house], "people": bool, "feast": bool,
    "off": bool}} — for the cells. Kept until something changes or the hour turns."""
    key = (y, m, who, int(_now() // 3600))
    if _marks["key"] == key:
        return _marks["data"]
    a, b = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    out = {}

    def cell(n):
        return out.setdefault(n, {"who": [], "people": False, "feast": False, "off": False})
    for e in events():
        if who and (e.get("who") or "") not in (who, ""):
            continue
        for s in occurrences(e, a, b):
            for k in range(_span(e) + 1):
                d = s + timedelta(days=k)
                if a <= d <= b:
                    cell(d.day)["who"].append(e.get("who") or "")
    for k in range(b.day):
        d = a + timedelta(days=k)
        if _reminders_on(d):
            cell(d.day)["who"].append("")
        if _people_days_on(d, who):
            cell(d.day)["people"] = True
        for _, off in _feast_on(d):
            cell(d.day)["feast"] = True
            cell(d.day)["off"] = cell(d.day)["off"] or off
    _marks.update(key=key, data=out)
    return out


def upcoming(today=None, days=60, who=None, limit=40):
    """[(day, item)] of events and people's days ahead, nearest first."""
    today = today or _today()
    rows = []
    for k in range(days):
        d = today + timedelta(days=k)
        for it in items_on(d, who, plan=False):
            if it["kind"] == "event" and not it["at"] and any(
                    e["id"] == it["id"] and _d(e["date"]) < d and e.get("repeat") == "none"
                    for e in events()) and k > 0:
                continue                       # a long trip: once, on its first day
            if it["kind"] != "feast":
                rows.append((d, it))
        if len(rows) >= limit:
            break
    return rows[:limit]


def today_rows(now=None):
    """Today's events for "plan na dziś" (screens.today_rows)."""
    today = _today(now)
    rows = []
    for it in items_on(today, plan=False):
        if it["kind"] == "event":
            name = f"{it['who']}: {it['title']}" if it["who"] else it["title"]
            rows.append((it["at"] or "cały dzień", name))
    return rows


def morning_note(who=None, now=None):
    """Today's events, for her morning hello: "15:00 dentysta / wycieczka"."""
    today = _today(now)
    rows = [it for it in items_on(today, who, plan=False) if it["kind"] == "event"]
    return " / ".join((f"{it['at']} " if it["at"] else "") + it["title"] for it in rows[:3])


def goodnight_note(now=None):
    """What "dobranoc" adds: tomorrow's events, "Jutro: dentysta o piętnastej." """
    today = _today(now) + timedelta(days=1)
    rows = [it for it in items_on(today, plan=False) if it["kind"] == "event"]
    if not rows:
        return None
    return "Jutro: " + ", ".join(it["title"] + (f" {_clock(it['at'])}" if it["at"] else "")
                                 for it in rows[:2]) + "."


def _asked_days_line(text, today):
    """"Co mamy 20 stycznia?": that day exactly, however far or crowded the next weeks are."""
    got = parse_range(text.lower(), today) if text else None
    if not got or (got[1] - got[0]).days > 7:
        return ""
    a, b = got[0], got[1]
    parts = [f"{e.get('who') or 'the whole house'}: {e['title']} {DAYS_SHORT[s.weekday()]} "
             f"{s.day:02d}.{s.month:02d}" + (f" {e['at']}" if e.get("at") else "")
             for e in events() for s in occurrences(e, a, b)]
    return f"In the calendar for the days just asked about: {'; '.join(parts[:12]) or 'nothing'}.\n"


def prompt_line(now=None, text=""):
    """The next weeks for the model (not in front of an outsider); `text`: the days it mentions."""
    if _outsider():
        return ""
    today = _today(now)
    asked = _asked_days_line(text, today)
    rows = []
    for e in events():
        n = next_of(e, today)
        if n and (n - today).days <= 45:
            rows.append((n, e))
    if not rows:
        return asked
    rows.sort(key=lambda p: (p[0], p[1].get("at") or ""))
    parts = [f"{e.get('who') or 'the whole house'}: {e['title']} {DAYS_SHORT[n.weekday()]} "
             f"{n.day:02d}.{n.month:02d}" + (f" {e['at']}" if e.get("at") else "")
             + (f" (in {(n - today).days} days)" if (n - today).days > 1 else "")
             for n, e in rows[:12]]
    return ("The family calendar (kalendarz; dated events, the app reminds by itself, these "
            "next ones are exact): " + "; ".join(parts) + ".\n" + asked)


# ── the voice commands ───────────────────────────────────────────────────────

_VERB = r"(?:dodaj|dopisz|wpisz|zapisz|wstaw|wrzuć|wrzuc|zanotuj|umieść|umiesc)"
_ADD_HEAD = re.compile(rf"^(?:proszę\s+|prosze\s+)?{_VERB}(?:\s+(?:mi|nam|to|tam))*\s+(?:do|w|na)\s+"
                       r"(?:(?:mój|moj|nasz|rodzinny|moim|naszym)\s+)?kalendarz(?:a|u)?\b\W*(.*)$")
_ADD_HEAD2 = re.compile(rf"^(?:do|w)\s+kalendarz(?:a|u)\s+{_VERB}(?:\s+(?:mi|nam))*\W*(.*)$")
_ADD_TAIL = re.compile(rf"^(.+?)[,.\s]+(?:i\s+)?{_VERB}(?:\s+(?:mi|nam|to|tam))*\s+(?:do|w|na)\s+"
                       r"(?:(?:mój|moj|nasz|moim|naszym)\s+)?kalendarz(?:a|u)?\W*(?:,?\s*(.*))?$")
_ADD_EVENT = re.compile(rf"^{_VERB}(?:\s+mi|\s+nam)?\s+(?:nowe\s+)?wydarzenie\b\W*(.*)$")
_SHOW = re.compile(r"^(?:(?:pokaż|pokaz|otwórz|otworz|włącz|wlacz|wyświetl|wyswietl)\s+(?:mi\s+|nam\s+)?)?"
                   r"(?:(?:mój|moj|nasz|rodzinny|cały|caly)\s+)?kalendarz(?:\s+(.+?))?\W*$")
_SHOW_MONTH = re.compile(r"^(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+)?(.+?)\s+w\s+kalendarzu\W*$")
_NEXT = re.compile(r"^(?:a\s+)?(?:co\s+(?:mam\s+|mamy\s+|masz\s+|macie\s+|jest\s+)?(?:dalej\s+|nowego\s+)?w\s+kalendarzu|"
                   r"co\s+(?:nas|mnie)\s+czeka|co\s+(?:mam|mamy)\s+zaplanowane|"
                   r"(?:jakie|co)\s+(?:mam|mamy)\s+(?:najbliższe\s+|najblizsze\s+)?(?:terminy|wydarzenia|plany)|"
                   r"(?:jakie\s+)?(?:najbliższe|najblizsze|następne|nastepne)\s+(?:wydarzenia|terminy|"
                   r"wydarzenie|w\s+kalendarzu)|co\s+najbliższego|co\s+najblizszego)\W*$")
_ASK_START = re.compile(r"^(?:a\s+|i\s+)?(?:co|jakie|czy)\b")
_ASK_SUBJECT = re.compile(r"\b(?:mam|mamy|ma|masz|macie|mają|maja|kalendarz\w*|zaplanowan\w*|plany|wolny|"
                          r"wolna|wolni|wolne|czeka|dzieje)\b")
_ASK_FILL = set("""co coś cos czy a i jakie jaki mam mamy masz ma macie mają maja jest są będzie bedzie
                dzieje się sie w we na kalendarzu kalendarz planie zaplanowane zaplanowanego
                zapisane zapisanego plany nas mnie czeka terminy wydarzenia jestem jesteśmy
                jestesmy wolny wolna wolni wolne ciekawego ciekawe wtedy""".split())
_WHEN_Q = re.compile(r"^(?:a\s+)?kiedy\s+(?:mam\s+|mamy\s+|ma\s+|jest\s+|będzie\s+|bedzie\s+|są\s+|"
                     r"idę\s+|ide\s+|idziemy\s+|jadę\s+|jade\s+|jedziemy\s+|wypada\s+)*(.+?)\W*$")
_LEFT_Q = re.compile(r"^(?:a\s+)?(?:(?:ile|za\s+ile)\s+(?:jeszcze\s+)?(?:dni\s+|czasu\s+)?(?:zostało\s+|zostalo\s+)?"
                     r"(?:do\s+)?)(.+?)\W*$")
_REMOVE = re.compile(r"^(?:usuń|usun|skasuj|wykreśl|wykresl|wyrzuć|wyrzuc|odwołaj|odwolaj|anuluj)\s+"
                     r"(?:z\s+kalendarza\W*\s*(.+?)|(.+?)\s+z\s+kalendarza|(.+?))\W*$")
_ONLY_NEXT = re.compile(r"\b(?:tylko\s+)?(?:najbliższ\w+|najblizsz\w+|ten\s+raz|tym\s+razem|tylko\s+(?:ten|tę|te|to))\b")
_MOVE = re.compile(r"^(?:przesuń|przesun|przełóż|przeloz|przenieś|przenies|zmień|zmien)\s+(.+?)\s+na\s+(.+?)\W*$")
_NOT_OURS = re.compile(r"\b(?:przypomnieni\w*|budzik\w*|minutnik\w*|timer\w*|alarm\w*|listy|liście|planu|plan)\b")
_RESTORE = re.compile(r"^(?:przywróć|przywroc|odzyskaj|cofnij)(?:\s+(?:usunięcie\s+|usuniecie\s+)?(.+?))?\W*$")
_BARE_UNDO = re.compile(r"^(?:cofnij(?:\s+to)?|usuń\s+to|usun\s+to|jednak\s+nie\s+zapisuj|nie\s+zapisuj|"
                        r"skasuj\s+to|to\s+pomyłka|to\s+pomylka)\W*$")
_REMIND_FOLLOW = re.compile(r"^(?:i\s+|a\s+|oraz\s+)?(?:przypomnij|przypominaj)(?:\s+(?:mi|nam|jej|mu|im|o\s+tym))*\s+")
_REMIND_NAMED = re.compile(r"^(?:przypomnij|przypominaj)(?:\s+(?:mi|nam|jej|mu|im))?\s+o\s+(.+?)\s+(?=\S+(?:\s+\S+)?\s+(?:wcześniej|wczesniej|przed)\b)")
_NO_REMIND_FOLLOW = re.compile(r"^(?:i\s+)?(?:nie\s+przypominaj(?:\s+(?:mi|nam|o\s+tym))*|bez\s+przypomnienia)\W*$")
_TIME_FOLLOW = re.compile(r"^(?:a\s+|to\s+|na\s+)?o\s+\S+(?:\s+\S+){0,3}\W*$")
_NOTE = re.compile(r"^(?:dodaj|dopisz|zapisz)\s+(?:notatkę|notatke|uwagę|uwage)\s+(?:do\s+)?(.+?)\W*$")
_PAPER_WORD = re.compile(r"\b(?:zaproszeni\w*|kartk\w*|kartce|ulotk\w*|plakat\w*|ogłoszeni\w*|ogloszeni\w*|"
                         r"pism\w*|harmonogram\s+wywozu|wywóz\s+śmieci|wywoz\s+smieci)\b")
_PAPER = re.compile(rf"^(?:przepisz|{_VERB}|przeczytaj|zeskanuj|weź|wez)\b.*\bkalendarz\w*\b|"
                    r"^(?:zeskanuj|przepisz)\s+(?:to\s+)?zaproszeni\w*")
_STOP = re.compile(r"^(?:anuluj|nieważne|niewazne|nic|stop|koniec|zostaw|jednak\s+nie|nie\s+dodawaj|"
                   r"nie\s+zapisuj|już\s+nic|juz\s+nic|nie)\b")
_REPEAT_Q = re.compile(r"^(?:co|słucham|sluchan|że\s+co|ze\s+co|powtórz|powtorz|jak)\W*$")
_NOT_ANSWER = re.compile(r"^(?:włącz|wlacz|wyłącz|wylacz|pokaż|pokaz|zagraj|graj|opowiedz|nastaw|ustaw|"
                         r"przypomnij|zrób|zrob|powiedz|puść|pusc|ile|jak\w*|kto|gdzie|czy|dlaczego|"
                         r"któr\w*|ktor\w*)\b|.*\?\s*$")


def _norm(text):
    return re.sub(r"^luna\W+", "", text.strip().lower()).rstrip(" .!")


def _guest_refuses(speak):
    if _outsider():
        speak("Kalendarz jest dla rodziny.")
        return True
    return False


def _keep_listening():
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = _now()


def expect(day=None):
    """"+" on the page, or "dodaj wydarzenie": the next sentence is the new event."""
    _expect.update(until=_now() + EXPECT_SECS, draft=None, day=day, tries=0)
    _keep_listening()


def expecting():
    return _now() < _expect["until"]


def _question(p):
    if not p.get("title"):
        return "Co mam wpisać?"
    if not p.get("date"):
        return "Na kiedy?"
    return None


def _take(p, speak, now=None):
    """A parsed event: saved, or the missing part asked for."""
    now = now if now is not None else _now()
    ask = _question(p)
    if ask:
        _expect.update(until=now + EXPECT_SECS, draft=p)
        _keep_listening()
        speak(ask)
        return True
    _expect.update(until=0.0, draft=None, day=None, tries=0)
    same = next((e for e in events() if occurrences(e, p["date"], p["date"])
                 and _names(e, p["title"]) and (e.get("at") or None) == p.get("at")), None)
    if same:
        speak(f"To już mam: {same['title']}, {when_said(same, p['date'])}.")
        show(p["date"], secs=SHOWN_SECS)
        return True
    e = add(p["title"], p["date"], p.get("at"), p.get("end"), p.get("who") or "",
            p.get("end_date"), p.get("repeat") or "none", p.get("remind"), p.get("always"),
            by=_speaker(), now=now)
    _last.update(ids=[e["id"]], t=now)
    print(f"[agenda] added {e['title']!r} {e['date']} {e.get('at')} for {e['who'] or 'dom'}", flush=True)
    page = _page()
    if page is not None and not page.get("sel"):
        _goto(page, _d(e["date"]))
        page["toast"] = (f"Dodane: {e['title']}", now + 3.0)
    else:
        show(_d(e["date"]), secs=SHOWN_SECS)
    speak(_confirm(e, now))
    return True


def _fill(draft, text, now=None):
    """The answer to "Na kiedy?" / "Co mam wpisać?"."""
    p = parse(text, draft.get("who") or _speaker(), now=now)
    out = dict(draft)
    if not out.get("date") and p.get("date"):
        out.update(date=p["date"], end_date=p.get("end_date"))
    if not out.get("at") and p.get("at"):
        out.update(at=p["at"], end=p.get("end"))
    if not out.get("title"):
        out["title"] = p.get("title") or None
    if out.get("remind") is None and p.get("remind") is not None:
        out["remind"] = p["remind"]
    return out


def _answering(low, text, speak, now):
    """The sentence after "Na kiedy?"; True when it was taken."""
    if _STOP.match(low):
        _expect.update(until=0.0, draft=None, day=None)
        speak("Dobrze, nie zapisuję.")
        return True
    if _REPEAT_Q.match(low):
        _expect["until"] = now + EXPECT_SECS
        _keep_listening()
        speak(_question(_expect["draft"] or {}) or "Powiedz, co i kiedy.")
        return True
    if _NOT_ANSWER.match(low):                 # a request for something else: it goes on
        _expect.update(until=0.0, draft=None, day=None)
        return False
    draft = _expect["draft"]
    if draft is None:
        draft = parse(text, _speaker(), day=_expect.get("day"), now=now)
        if draft.get("date") is None and _expect.get("day"):
            draft["date"] = _expect["day"]
    else:
        before = _question(draft)
        draft = _fill(draft, text, now)
        if _question(draft) == before:
            _expect["tries"] += 1
            if _expect["tries"] >= 2:          # twice not understood: it goes on down the chain
                _expect.update(until=0.0, draft=None, day=None, tries=0)
                return False
            _expect["until"] = now + EXPECT_SECS
            _keep_listening()
            speak("Nie zrozumiałam dnia. Powiedz na przykład: dwunastego listopada, albo w sobotę."
                  if before == "Na kiedy?" else before)
            return True
    return _take(draft, speak, now)


def _add_text(low):
    """What is to be added, if this asks for it: the sentence's own words; None if not."""
    for rx in (_ADD_HEAD, _ADD_HEAD2, _ADD_EVENT):
        m = rx.match(low)
        if m:
            return m.group(1).strip()
    m = _ADD_TAIL.match(low)
    if m:
        return (m.group(1) + " " + (m.group(2) or "")).strip()
    return None


def _weekly_plan_said(rest):
    """"Maja angielski od poniedziałku do piątku o 17": that is the week's plan."""
    return bool(re.search(rf"\bod\s+(?:{_WD_GEN_ANY})\s+do\s+(?:{_WD_GEN_ANY})\b|\bcodziennie\b|\bco\s+dzień\b|"
                          r"\bw\s+dni\s+(?:robocze|powszednie)\b", rest)
                and re.search(r"\bo\s+\S+", rest))


def _say_rows(day, rows, today, who=None):
    head = _cap(day_said(day, today))
    if not rows:
        name = f" {who}" if who else ""
        return f"{head}{name} nie ma nic zapisanego." if who else f"{head} nic nie mam zapisanego."
    said = [(f"{_clock(r['at'])} " if r["at"] else "") + (f"{r['who']}: " if r["who"] and not who else "") + r["title"]
            for r in rows[:4]]
    more = f" I jeszcze {len(rows) - 4}." if len(rows) > 4 else ""
    return f"{head}: " + ", ".join(said) + "." + more


def _answer_range(a, b, who, speak, today):
    show(a, who=who, secs=SHOWN_SECS * 2)
    if a == b:
        speak(_say_rows(a, items_on(a, who), today, who))
        return True
    rows = []
    for k in range((b - a).days + 1):
        d = a + timedelta(days=k)
        rows += [(d, it) for it in items_on(d, who, plan=False) if it["kind"] != "feast"]
    if not rows:
        speak("W tym czasie nic nie mam zapisanego.")
        return True
    said = [f"{day_said(d, today)}{(' ' + _clock(it['at'])) if it['at'] else ''} — "
            + (f"{it['who']}: " if it["who"] and not who else "") + it["title"] for d, it in rows[:5]]
    more = f" I jeszcze {len(rows) - 5}." if len(rows) > 5 else ""
    speak(_cap("; ".join(said)) + "." + more)
    return True


def _asked_range(low, today):
    """"Co mam w kalendarzu w sobotę?" → (a, b, who); None if the sentence says anything more.
    Without "kalendarz" it's the model's: it also knows what she remembers ("sprawdzian z matmy")."""
    if not _ASK_START.match(low) or "kalendarz" not in low:
        return None
    got = parse_range(low, today)
    if not got:
        return None
    a, b, rest = got
    who, rest2 = schedule._who_of(rest)
    words = re.findall(r"[\wąćęłńóśźż]+", rest2)
    if any(w not in _ASK_FILL for w in words):
        return None
    if who is None and re.search(r"\b(?:mam|jestem)\b", low):
        who = _speaker()
    return a, b, who or None


def _one_of(evs, what, speak, now, to=None):
    """Several events fit: which one? Remembered until the answer."""
    today = _today(now)
    _pending.update(what=what, ids=[e["id"] for e in evs[:4]], until=now + EXPECT_SECS, to=to)
    _keep_listening()
    names = ", ".join(f"{e['title']} {when_said(e, today=today)}" for e in evs[:3])
    speak(f"Mam kilka takich: {names}. Który dzień?")
    return True


def _do_remove(e, speak, now, only_next=False):
    today = _today(now)
    if only_next and e.get("repeat") != "none":
        n = next_of(e, today)
        update(e["id"], now=now, skip=(e.get("skip") or []) + [n.isoformat()])
        speak(f"Dobrze, tym razem bez tego: {e['title']}, {day_said(n, today)}. Dalej zostaje {REPEAT_SAID[e['repeat']]}.")
        return True
    remove(e["id"], now)
    _last.update(ids=[], t=0.0)
    speak(f"Usunęłam z kalendarza: {e['title']}. Gdyby co, powiedz: przywróć.")
    return True


def _do_move(e, to, speak, now):
    a, b, at, end = to
    changes = {}
    if a:
        changes["date"] = a.isoformat()
        if e.get("end_date"):
            changes["end_date"] = (a + timedelta(days=_span(e))).isoformat()
        if b:
            changes["end_date"] = b.isoformat()
    if at:
        changes["at"] = at
        changes["end"] = end
        if not e.get("at"):                    # it has a time now: an hour ahead too
            changes["remind"] = default_leads(at)
    e2 = update(e["id"], now=now, **changes)
    _last.update(ids=[e["id"]], t=now)
    show(_d(e2["date"]), secs=SHOWN_SECS)
    speak(" ".join(x for x in (f"Przesunięte: {e2['title']}, {when_said(e2, today=_today(now))}.",
                               _conflict(e2), reminders_said(e2, now)) if x))
    return True


def _move_target(words, today):
    """"czwartek o 16", "16", "szesnastą" → (a, b, at, end); None if neither day nor time."""
    got = parse_date("na " + words, today)
    a, b, rest = got if got else (None, None, words)
    rest = rest.strip()
    at, end, left = schedule._time_of(rest)
    if not at and rest:
        at, end, left = schedule._time_of("o " + rest)
    if not a and not at:
        return None
    if " ".join(left.split()) and not got:     # more words than a time: not a move
        return None
    return a, b, at or None, end or None


def _pending_answer(low, speak, now):
    what, ids, to = _pending["what"], _pending["ids"], _pending["to"]
    live = now < _pending["until"]
    _pending.update(what=None, ids=[], until=0.0, to=None)
    if not live:
        return False
    if _STOP.match(low):
        speak("Dobrze, zostaje, jak było.")
        return True
    today = _today(now)
    picks = [e for e in (get(i) for i in ids) if e]
    got = parse_date(low if re.match(r"(?:w|we|na)\s", low) else "w " + low, today) or parse_date(low, today)
    if got:
        picks = [e for e in picks if occurrences(e, got[0], got[0])]
    elif re.search(r"\b(?:pierwsz\w+|najbliższ\w+|najblizsz\w+)\b", low):
        picks = picks[:1]
    else:
        words = [e for e in picks if _names(e, low)]
        picks = words or []
    if len(picks) != 1:
        return False
    return _do_remove(picks[0], speak, now) if what == "remove" else _do_move(picks[0], to, speak, now)


def handle(text, speak):
    """Local commands for the calendar. True when handled."""
    now = _now()
    today = _today(now)
    low = _norm(text)
    if _pending["what"] and _pending_answer(low, speak, now):
        return True
    if expecting():
        if _answering(low, text, speak, now):
            return True
    recent = now - _last["t"] < LAST_SECS and _last["ids"]
    if recent:
        got = _follow_up(low, speak, now)
        if got:
            return True
    return _triggers(low, text, speak, now, today)


def _follow_up(low, speak, now):
    """After an event was just added: its reminder, its time, or "cofnij"."""
    e = get(_last["ids"][0]) if _last["ids"] else None
    if e is None:
        return False
    if _BARE_UNDO.match(low) and now - _last["t"] < BARE_UNDO_SECS:
        gone = 0
        for i in _last["ids"]:
            gone += 1 if remove(i, now) else 0
        _last.update(ids=[], t=0.0)
        speak("Dobrze, usunęłam." if gone == 1 else f"Dobrze, usunęłam wszystkie ({gone}).")
        return True
    if _NO_REMIND_FOLLOW.match(low):
        update(e["id"], now=now, remind=[])
        speak("Dobrze, bez przypomnienia.")
        return True
    if _REMIND_FOLLOW.match(low):
        leads, _, rest = remind_of(low)
        if leads and not _words(_REMIND_WORD.sub(" ", rest)):
            e2 = update(e["id"], now=now, remind=leads)
            speak(reminders_said(e2, now) or "Dobrze.")
            return True
    if _TIME_FOLLOW.match(low) and not e.get("at"):
        at, end, left = schedule._time_of(re.sub(r"^(?:a|to|na)\s+", "", low))
        if at and not " ".join(left.split()):
            e2 = update(e["id"], now=now, at=at, end=end or None, remind=default_leads(at))
            speak(f"Dobrze: {e2['title']}, {when_said(e2, today=_today(now))}. {reminders_said(e2, now)}".strip())
            return True
    return False


def _triggers(low, text, speak, now, today):
    if _PAPER.match(low) and _PAPER_WORD.search(low) and not re.search(r"\bplan\w*\b", low):
        if _guest_refuses(speak):
            return True
        who, _ = schedule._who_of(low)
        return read_paper(who or "", speak)
    rest = _add_text(low)
    if rest is not None:
        if _weekly_plan_said(rest):
            return False                       # the week's plan takes it (schedule.handle)
        if _guest_refuses(speak):
            return True
        if not rest:
            expect()
            speak("Co mam wpisać i na kiedy?")
            return True
        original = re.search(re.escape(rest), text, re.I)
        p = parse(original.group(0) if original else rest, _speaker(), now=now)
        return _take(p, speak, now)
    m = _SHOW.match(low) or _SHOW_MONTH.match(low)
    if m:
        return _show_asked(m.group(1) or "", speak, now, today)
    if _NEXT.match(low):
        return _say_next(speak, now, today)
    asked = _asked_range(low, today)
    if asked:
        if _guest_refuses(speak):
            return True
        return _answer_range(asked[0], asked[1], asked[2], speak, today)
    return _named_event(low, speak, now, today)


def _show_asked(words, speak, now, today):
    if _guest_refuses(speak):
        return True
    who = None
    if words:
        got = parse_range(words if re.match(r"(?:w|we|na)\s", words) else "na " + words, today)
        if got:
            a, b, left = got
            who, left = schedule._who_of(left)
            if " ".join(re.findall(r"\w+", left)):
                return False
            show(a, who=who or None, focus=(b - a).days > 7)
            speak(_cap(_range_said(a, b)) + ".")
            return True
        who, left = schedule._who_of(words)
        if not who or " ".join(re.findall(r"\w+", left)):
            return False                       # "kalendarz adwentowy": not ours
    show(today, who=who)
    speak(_brief(today, who))
    return True


def _range_said(a, b):
    if a.day == 1 and b.day == calendar.monthrange(b.year, b.month)[1] and a.month == b.month:
        return f"oto {MONTHS[a.month - 1].lower()}"
    return f"oto {a.day} {MONTHS_GEN[a.month - 1]}"


def _brief(today, who=None):
    """What she says on opening the page: today, then what is next."""
    rows = [it for it in items_on(today, who, plan=False) if it["kind"] == "event"]
    said = []
    if rows:
        said.append("Dziś: " + ", ".join(
            (f"{_clock(r['at'])} " if r["at"] else "") + r["title"] for r in rows[:3]) + ".")
    nxt = _next_events(today + timedelta(days=1), who, 1)
    if nxt:
        d, e = nxt[0]
        said.append(f"Następne: {e['title']}, {when_said(e, d, today)}.")
    if not said:
        return "W kalendarzu pusto. Powiedz na przykład: dodaj do kalendarza dentysta w środę o piętnastej."
    return " ".join(said)


def _next_events(first, who=None, n=5):
    rows = []
    for e in events():
        if who and (e.get("who") or "") not in (who, ""):
            continue
        d = next_of(e, first)
        if d:
            rows.append((d, e))
    rows.sort(key=lambda p: (p[0], p[1].get("at") or ""))
    return rows[:n]


def _say_next(speak, now, today):
    if _guest_refuses(speak):
        return True
    rows = _next_events(today, None, 4)
    show(today, view="next", secs=SHOWN_SECS * 2)
    if not rows:
        speak("W kalendarzu nic nie czeka.")
        return True
    speak(_cap("; ".join(f"{day_said(d, today)}{(' ' + _clock(e['at'])) if e.get('at') else ''} — "
                         + _whose(e) + e["title"] for d, e in rows)) + ".")
    return True


def _named_event(low, speak, now, today):
    """Sentences that are ours only if they name an event on the calendar."""
    m = _RESTORE.match(low)
    if m and not re.search(r"\bplan\w*\b|\blekcj\w*", low):
        words = re.sub(r"\bz\s+kalendarza\b", " ", m.group(1) or "").strip()
        if m.group(1) or now - max((t["t"] for t in _trash()), default=0) < BARE_UNDO_SECS:
            if _guest_refuses(speak):
                return True
            e = restore(words if words else "", now)
            if e:
                speak(f"Przywróciłam: {e['title']}, {when_said(e, today=today)}.")
                show(next_of(e, today) or _d(e["date"]), secs=SHOWN_SECS)
                return True
            if "kalendarz" in low:
                speak("Nie mam czego przywrócić.")
                return True
    m = _REMOVE.match(low)
    if m and not _NOT_OURS.search(low):
        said_cal = "kalendarz" in low
        words = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        only_next = bool(_ONLY_NEXT.search(words))
        words = _ONLY_NEXT.sub(" ", words).strip()
        words = re.split(r",|\s(?:bo|jednak|ponieważ|nie)\s", words)[0].strip()    # "to kino, nie idziemy"
        words = re.sub(r"^(?:to|ten|tę|te|tego|tą)\s+", "", words)
        evs = find(words, today)
        if evs:
            if _guest_refuses(speak):
                return True
            if len(evs) > 1 and not only_next:
                return _one_of(evs, "remove", speak, now)
            return _do_remove(evs[0], speak, now, only_next)
        if said_cal:
            speak(f"Nie widzę tego w kalendarzu: {words}.")
            return True
        return False
    m = _MOVE.match(low)
    if m and not _NOT_OURS.search(low):
        evs = find(m.group(1), today)
        to = _move_target(m.group(2), today) if evs else None
        if evs and to:
            if _guest_refuses(speak):
                return True
            if len(evs) > 1:
                return _one_of(evs, "move", speak, now, to)
            return _do_move(evs[0], to, speak, now)
    m = _REMIND_NAMED.match(low)
    if m and not _NOT_OURS.search(m.group(1)):
        evs = find(m.group(1), today)
        leads, _, rest = remind_of(low[m.end(1):])
        if evs and leads:
            if _guest_refuses(speak):
                return True
            e2 = update(evs[0]["id"], now=now, remind=leads)
            speak(f"{_cap(e2['title'])}: {reminders_said(e2, now).lower() or 'dobrze'}")
            return True
    m = _NOTE.match(low)
    if m:
        got = _note_of(m.group(1), today)
        if got:
            if _guest_refuses(speak):
                return True
            e, note = got
            update(e["id"], now=now, note=note)
            speak(f"Dopisałam do: {e['title']}.")
            return True
    m = _WHEN_Q.match(low) or _LEFT_Q.match(low)
    if m and not _NOT_OURS.search(low):
        evs = find(m.group(1), today)
        if evs:
            if _guest_refuses(speak):
                return True
            d = next_of(evs[0], today)
            e = evs[0]
            left = in_days(d, today)
            speak(_cap(f"{_whose(e)}{e['title']} — {when_said(e, d, today)}"
                       + (f", {left}" if left not in ("dziś", "jutro", "pojutrze") else "") + "."))
            show(d, secs=SHOWN_SECS)
            return True
    return False


_PAST_TENSE = re.compile(r"\b\w+(?:łam|łem|łeś|łaś|ła|ło|ł|liśmy|łyśmy|li|ły)\b")


def from_note(note, speak, now=None):
    """"Zapisz, że 20 listopada o 18 idziemy do kina": a date and an hour ahead is an event, which
    gets reminders, not a fact to remember. False: it stays memory's (and always in front of a guest)."""
    now = now if now is not None else _now()
    if _outsider() or _PAST_TENSE.search(note.lower()):
        return False
    p = parse(note, _speaker(), now=now)
    if not (p.get("title") and p.get("date") and p.get("at")) or p["date"] < _today(now):
        return False
    return _take(p, speak, now)


def _trash():
    with _lock:
        return _load()["trash"]


def _note_of(words, today):
    """"dentysty weź skierowanie" → (the event, "weź skierowanie"): the longest beginning
    of it that names an event; the rest is the note."""
    parts = re.split(r"\s*[:,]\s*", words, maxsplit=1)
    if len(parts) == 2:
        evs = find(parts[0], today)
        return (evs[0], parts[1].strip()) if evs and parts[1].strip() else None
    tokens = words.split()
    for k in range(len(tokens) - 1, 0, -1):
        evs = find(" ".join(tokens[:k]), today)
        if evs:
            return evs[0], " ".join(tokens[k:])
    return None


# ── from paper: an invitation, a school notice, a rubbish calendar ───────────

def from_paper(rows, today=None):
    """brain.read_events' rows → the ones that can be saved: {title, date, end_date, at,
    end, note, repeat}. A date that can't be read is dropped, never guessed."""
    today = today or _today()
    out = []
    for r in rows or []:
        title = " ".join(str(r.get("title") or "").split())[:_TITLE_MAX]
        try:
            day = date.fromisoformat(str(r.get("date") or ""))
        except ValueError:
            continue
        if not title or day < today:
            continue
        try:
            last = date.fromisoformat(str(r.get("end_date") or "")) if r.get("end_date") else None
        except ValueError:
            last = None
        at = str(r.get("at") or "")
        end = str(r.get("end") or "")
        out.append({"title": title, "date": day, "end_date": last,
                    "at": at if re.fullmatch(r"\d{2}:\d{2}", at) else None,
                    "end": end if re.fullmatch(r"\d{2}:\d{2}", end) else None,
                    "note": " ".join(str(r.get("note") or "").split())[:120]})
    return out[:MAX_FROM_PAPER]


def save_paper(rows, who="", by=None, now=None):
    """Saved, those already there skipped: (added, kept)."""
    added, kept = [], 0
    for r in rows:
        if any(_names(e, r["title"]) and occurrences(e, r["date"], r["date"]) for e in events()):
            kept += 1
            continue
        added.append(add(r["title"], r["date"], r["at"], r["end"], who, r["end_date"],
                         note=r["note"], by=by, now=now))
    return added, kept


def paper_said(added, kept, today=None):
    if not added:
        return ("To wszystko już mam w kalendarzu." if kept else
                "Nie widzę na tej kartce żadnej daty. Przysuń ją bliżej i powiedz jeszcze raz.")
    if len(added) <= 3:
        said = "Zapisałam: " + "; ".join(f"{e['title']}, {when_said(e, today=today)}" for e in added) + "."
    else:
        first = added[0]
        said = (f"Zapisałam {len(added)} {schedule._pl(len(added), 'termin', 'terminy', 'terminów')}. "
                f"Pierwszy: {first['title']}, {when_said(first, today=today)}.")
    return said + " Sprawdź, czy dobrze przeczytałam. Gdyby nie, powiedz: cofnij."


def read_paper(who, speak):
    """Read what is held to the camera into the calendar (15–30 s, on its own thread)."""
    import brain
    if _now() < _reading[0]:
        return True
    if brain._camera_jpeg_b64() is None:
        speak("Nie widzę teraz nic przez kamerę, więc kartki nie przeczytam.")
        return True
    _reading[0] = _now() + 90
    speak("Dobrze, czytam — potrzymaj kartkę chwilę prosto przed kamerą.")
    imgs = schedule._frames()
    by = _speaker()
    with state.lock:
        state.overlay = ("card", _now() + 60, {"text": "Czytam kartkę…", "sub": "", "tone": None})

    def run():
        from text_to_speech import speak as say
        got = brain.read_events(imgs)
        _reading[0] = 0.0
        with state.lock:
            if state.overlay and state.overlay[0] == "card":
                state.overlay = None
        rows = from_paper((got or {}).get("events")) if got and got.get("readable") else []
        if not rows:
            say("Nie umiem odczytać z tej kartki żadnej daty. Przysuń ją bliżej, prosto do kamery, "
                "i powiedz jeszcze raz.")
            return
        added, kept = save_paper(rows, who, by)
        _last.update(ids=[e["id"] for e in added], t=_now())
        print(f"[agenda] from paper: {len(added)} added, {kept} already there", flush=True)
        if added:
            show(_d(added[0]["date"]))
        say(paper_said(added, kept))
    threading.Thread(target=run, daemon=True, name="agenda-paper").start()
    return True


# ── the page ─────────────────────────────────────────────────────────────────

def open_from_dock():
    """The dock's icon: the month, but not for a guest or a stranger."""
    if not _outsider():
        return show()
    with state.lock:
        state.overlay = ("card", _now() + 4, {"text": "Kalendarz jest dla rodziny.", "sub": "", "tone": None})
    return None


def show(day=None, who=None, view="day", secs=PAGE_SECS, focus=False):
    day = day or _today()
    data = {"y": day.year, "m": day.month, "day": day.isoformat(), "who": who, "view": view,
            "sel": None, "page": 0, "confirm": 0.0, "toast": None, "edit": None}
    with state.lock:
        state.overlay = ("agenda", _now() + secs, data)
    return data


def _page():
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "agenda" and _now() < ov[1]:
            state.overlay = (ov[0], max(ov[1], _now() + PAGE_SECS), ov[2])
            return ov[2]
    return None


def _goto(d, day):
    d.update(y=day.year, m=day.month, day=day.isoformat(), page=0, view="day")


def _turn(d, step):
    first = _add_months(date(d["y"], d["m"], 1), step)
    d.update(y=first.year, m=first.month, page=0)
    today = _today()
    keep = today if (today.year, today.month) == (first.year, first.month) else first
    d["day"] = keep.isoformat()


def _say(text):
    """Speak from the render thread's tap without holding it up."""
    def run():
        try:
            from text_to_speech import speak
            speak(text)
        except Exception as e:
            print(f"[agenda] could not speak: {e}", flush=True)
    threading.Thread(target=run, daemon=True, name="agenda-say").start()


def people():
    import faces
    names = list(faces.family())
    for e in events():
        if e.get("who") and e["who"] not in names:
            names.append(e["who"])
    return names


def rows_of(d, today=None):
    """The list on the right: [(day, item)], the day's or the next ones."""
    today = today or _today()
    key = (d.get("view"), d.get("day"), d.get("who"), today, int(_now() // 10))
    if _rows["key"] != key:                    # the page draws often, the lists read files
        if d.get("view") == "next":
            rows = upcoming(today, who=d.get("who"))
        else:
            day = _d(d["day"])
            rows = [(day, it) for it in items_on(day, d.get("who"))]
        _rows.update(key=key, data=rows)
    return _rows["data"]


GRID_X, GRID_Y, CELL_W = 12, 88, 62
PANEL_X = 458
ROW_H, ROWS = 54, 5


def month_rows(y, m):
    """How many weeks the month touches."""
    first, days = date(y, m, 1).weekday(), calendar.monthrange(y, m)[1]
    return (first + days + 6) // 7


def cell_rect(y, m, n, H=480):
    """The day's cell, (x, y, w, h)."""
    first = date(y, m, 1).weekday()
    k = first + n - 1
    h = (H - GRID_Y - 6) // month_rows(y, m)
    return (GRID_X + (k % 7) * CELL_W, GRID_Y + (k // 7) * h, CELL_W - 4, h - 4)


def layout(W, H, d):
    """Rectangles (x, y, w, h), shared by the drawing and the taps."""
    if d.get("sel"):
        return card_layout(W, H)
    panel = W - PANEL_X - 12
    L = {"prev": (10, 10, 48, 48), "next": (398, 10, 48, 48),
         "who": (PANEL_X, 64, 124, 36), "view": (PANEL_X + 132, 64, 130, 36),
         "add": (PANEL_X, H - 50, 106, 44), "type": (PANEL_X + 112, H - 50, 100, 44),
         "paper": (PANEL_X + 218, H - 50, panel - 218, 44)}
    rows = rows_of(d)
    pages = max(1, -(-len(rows) // ROWS))
    d["page"] = d.get("page", 0) % pages
    shown = rows[d["page"] * ROWS:(d["page"] + 1) * ROWS]
    L["rows"] = [((PANEL_X, 108 + k * ROW_H, panel, ROW_H - 5), r) for k, r in enumerate(shown)]
    L["more"] = (PANEL_X, 108 + ROWS * ROW_H - 2, panel, 30) if pages > 1 else None
    L["pages"] = pages
    return L


def card_layout(W, H):
    x = 146
    y = (84, 138, 192, 246, 300, 354)
    L = {"back": (14, 14, 48, 48), "title": (72, 10, 644, 58),
         "w-": (x, y[0], 62, 44), "d-": (x + 68, y[0], 50, 44),
         "d+": (x + 412, y[0], 50, 44), "w+": (x + 468, y[0], 62, 44),
         "at-": (x, y[1], 46, 44), "at+": (x + 136, y[1], 46, 44),
         "end-": (x + 226, y[1], 46, 44), "end+": (x + 362, y[1], 46, 44),
         "allday": (x + 424, y[1], W - x - 424 - 16, 44),
         "who": (x, y[2], 240, 44), "repeat": (x + 362, y[2], W - x - 362 - 16, 44),
         "always": (x, y[4], 400, 44), "note": (x, y[5], W - x - 16, 44),
         "delete": (W - 24 - 180, H - 58, 180, 50)}
    w = (W - x - 16 - 6 * (len(LEADS) - 1)) // len(LEADS)
    L["leads"] = [((x + k * (w + 6), y[3], w, 44), lead) for k, lead in enumerate(LEADS)]
    return L


def _in(r, x, y, grow=0):
    return (r[0] - grow <= x < r[0] + r[2] + grow) and (r[1] - grow <= y < r[1] + r[3] + grow)


def hit(x, y, W, H, d):
    """What a tap (px) lands on: ("cell", n) | ("row", item) | ("prev",) … | None."""
    L = layout(W, H, d)
    if d.get("sel"):
        for r, lead in L["leads"]:
            if _in(r, x, y):
                return ("lead", lead)
        for key in ("back", "title", "w-", "d-", "d+", "w+", "at-", "at+", "end-", "end+", "allday",
                    "who", "repeat", "always", "note", "delete"):
            if _in(L[key], x, y, 3):
                return (key,)
        return None
    for key in ("prev", "next", "who", "view", "add", "type", "paper"):
        if _in(L[key], x, y, 3):
            return (key,)
    if L["more"] and _in(L["more"], x, y):
        return ("more",)
    for r, row in L["rows"]:
        if _in(r, x, y):
            return ("row", row)
    if x < PANEL_X:
        for n in range(1, calendar.monthrange(d["y"], d["m"])[1] + 1):
            if _in(cell_rect(d["y"], d["m"], n, H), x, y):
                return ("cell", n)
    return None


def on_close():
    """✕: the keyboard goes first, then the card; True when the page stays."""
    with state.lock:
        ov = state.overlay
        d = ov[2] if ov and ov[0] == "agenda" else None
    if d is None:
        return False
    if d.get("edit"):
        d["edit"] = None
        return True
    if d.get("sel"):
        d["sel"] = None
        return True
    return False


def _step_time(at, mins):
    t = (schedule._mins(at) + mins) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


def _tap_card(d, e, kind, hit_, now):
    eid = e["id"]
    if kind == "back":
        d["sel"] = None
    elif kind == "title":
        _start_edit(d, "title", e["title"])
    elif kind == "note":
        _start_edit(d, "note", e.get("note") or "")
    elif kind in ("w-", "w+", "d-", "d+"):
        step = {"w-": -7, "w+": 7, "d-": -1, "d+": 1}[kind]
        new = _d(e["date"]) + timedelta(days=step)
        changes = {"date": new.isoformat()}
        if e.get("end_date"):
            changes["end_date"] = (_d(e["end_date"]) + timedelta(days=step)).isoformat()
        update(eid, now=now, **changes)
    elif kind in ("at-", "at+", "end-", "end+"):
        sign = -15 if kind.endswith("-") else 15
        if not e.get("at"):                    # all day: ± changes how many days it lasts
            if kind.startswith("end"):
                last = _d(e["date"]) + timedelta(days=max(0, _span(e) + (1 if sign > 0 else -1)))
                update(eid, now=now, end_date=last.isoformat() if last > _d(e["date"]) else None)
            return
        if kind.startswith("at"):
            update(eid, now=now, at=_step_time(e["at"], sign))
        else:
            base = e.get("end") or e["at"]
            new = _step_time(base, sign)
            update(eid, now=now, end=new if schedule._mins(new) > schedule._mins(e["at"]) else None)
    elif kind == "allday":
        if e.get("at"):
            update(eid, now=now, at=None, end=None, remind=default_leads(None))
        else:
            update(eid, now=now, at="12:00", end=None, end_date=None, remind=default_leads("12:00"))
    elif kind == "lead":
        lead = hit_[1]
        have = set(e.get("remind") or [])
        if not e.get("at") and 0 < lead < DAY:
            d["toast"] = ("Cały dzień: najwcześniej rano tego dnia", now + 3.0)
            return
        have.symmetric_difference_update({lead})
        update(eid, now=now, remind=sorted(have, reverse=True))
    elif kind == "who":
        names = [""] + people()
        cur = e.get("who") or ""
        update(eid, now=now, who=names[(names.index(cur) + 1) % len(names)] if cur in names else "")
    elif kind == "repeat":
        cur = e.get("repeat") or "none"
        update(eid, now=now, repeat=REPEATS[(REPEATS.index(cur) + 1) % len(REPEATS)], skip=[])
    elif kind == "always":
        update(eid, now=now, always=not e.get("always"))
    elif kind == "delete":
        if now - d.get("confirm", 0.0) < 4.0:
            remove(eid, now)
            d.update(sel=None, confirm=0.0, toast=("Usunięte. Powiedz „przywróć”, jeśli to pomyłka.", now + 4.0))
        else:
            d["confirm"] = now


def _start_edit(d, field, value):
    d["edit"] = {"field": field, "text": value, "shift": not value, "layer": "abc"}


def _press(d, key, now):
    """A key on the keyboard (contacts.py owns its layout)."""
    import contacts
    e = d["edit"]
    if key != "save":
        contacts.type_key(e, key, _TITLE_MAX)
        return
    typed = " ".join(e["text"].split())
    field = e["field"]
    if field == "new":
        if typed:
            ev = add(typed, _d(d["day"]), who=d.get("who") or "", by=_speaker(), now=now)
            d["sel"] = ev["id"]
    elif field == "title":
        if typed:
            update(d["sel"], now=now, title=typed)
    elif field == "note":
        update(d["sel"], now=now, note=typed)
    d["edit"] = None


def tap(x, y, W, H, now=None):
    """A tap (px) on the page. True when it was on the page's controls."""
    now = now if now is not None else _now()
    d = _page()
    if d is None:
        return False
    if d.get("edit"):
        import contacts
        key = contacts.key_at("text", d["edit"]["layer"], x, y, W, H)
        if key:
            _press(d, key, now)
        return True
    got = hit(x, y, W, H, d)
    if not got:
        return True
    kind = got[0]
    if d.get("sel"):
        e = get(d["sel"])
        if e is None:
            d["sel"] = None
            return True
        if kind != "delete":
            d["confirm"] = 0.0
        _tap_card(d, e, kind, got, now)
        return True
    if kind == "cell":
        d.update(day=date(d["y"], d["m"], got[1]).isoformat(), page=0, view="day")
    elif kind in ("prev", "next"):
        _turn(d, -1 if kind == "prev" else 1)
    elif kind == "who":
        names = [None] + people()
        cur = d.get("who")
        d.update(who=names[(names.index(cur) + 1) % len(names)] if cur in names else None, page=0)
    elif kind == "view":
        d.update(view="day" if d.get("view") == "next" else "next", page=0)
    elif kind == "more":
        d["page"] = d.get("page", 0) + 1
    elif kind == "add":
        expect(_d(d["day"]))
        _say("Powiedz, co wpisać. Na przykład: dentysta o piętnastej.")
    elif kind == "type":
        _start_edit(d, "new", "")
    elif kind == "paper":                      # (it waits for the camera: not on the render thread)
        threading.Thread(target=read_paper, args=(d.get("who") or "", _say), daemon=True,
                         name="agenda-read").start()
    elif kind == "row":
        day, it = got[1]
        if it["kind"] == "event":
            d["sel"] = it["id"]
        elif it["kind"] == "plan":
            schedule.show(it.get("who") or None, day.weekday())
        else:
            d["toast"] = ("To jest z przypomnień" if it["kind"] == "reminder" else it["title"], now + 3.0)
    return True


def swipe(dx):
    """Another month, if no card or keyboard is up."""
    d = _page()
    if d is not None and not d.get("sel") and not d.get("edit"):
        _turn(d, -1 if dx > 0 else 1)


