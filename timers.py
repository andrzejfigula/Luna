"""
timers.py — kitchen timers, reminders and wake-up alarms.

  "Luna, minutnik na 10 minut"                    → timer, 600 s
  "przypomnij mi o 18 żeby zadzwonić do mamy"     → reminder at 18:00
  "za pół godziny przypomnij mi o praniu"         → timer with a label
  "wyłącz minutnik" / "ile zostało?"              → the model sees the list
  "obudź mnie o 7"                                → alarm: for SUNRISE_SECS
                                                    before, the screen
                                                    brightens like a dawn
                                                    (display.py), then a
                                                    good-morning with the
                                                    weather

The model asks for them through the "actions" field of its JSON reply (see
brain.py); this module keeps them in data/timers.json so they survive a
restart, shows the nearest one as a small countdown in the corner of the
screen, and when one is due: a chime, her face lights up, and she says what
it was for. If nobody reacts (touch or speech) she reminds once more a minute
later. Timers ring even in quiet hours or after "Luna, cicho" — you asked for
them.
"""

import json
import re
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared_state import state
from config import (TIMERS_PATH, TIMERS_MAX, TIMER_REPEAT_SECS, LUNA_TIMEZONE,
                    SUNRISE_SECS)

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception:
    _TZ = None

_lock   = threading.Lock()
_timers = []        # [{"due": epoch, "label": str, "kind": "timer"|"reminder", "set": epoch}]


# ── persistence ──────────────────────────────────────────────────────────────

def _load():
    global _timers
    try:
        with open(TIMERS_PATH, encoding="utf-8") as f:
            _timers = [t for t in json.load(f) if "due" in t]
    except FileNotFoundError:
        _timers = []
    except (OSError, ValueError) as e:
        print(f"[timers] could not read {TIMERS_PATH} ({e})")
        _timers = []


def _save():
    tmp = TIMERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_timers, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TIMERS_PATH)


# ── what the model asks for ──────────────────────────────────────────────────

def _parse_at(at):
    """'2026-10-04 18:00' (local time) → epoch, or None."""
    try:
        dt = datetime.strptime(at.strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:                                   # just "18:00": today (or tomorrow)
            hm = datetime.strptime(at.strip()[:5], "%H:%M")
            now = datetime.now(_TZ) if _TZ else datetime.now()
            dt = now.replace(hour=hm.hour, minute=hm.minute, second=0,
                             microsecond=0, tzinfo=None)
        except ValueError:
            return None
    if _TZ:
        dt = dt.replace(tzinfo=_TZ)
    due = dt.timestamp()
    if due < time.time() - 60:                 # already past today → tomorrow
        due += 86400
    return due


_REPEATS = {"none", "daily", "weekdays", "weekends", "weekly", "monthly", "yearly"}


def _add_months(dt, n):
    """Same day n months later (the 31st → the month's last day)."""
    import calendar
    m = dt.month - 1 + n
    y, m = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def _matches(dt, repeat):
    wd = dt.weekday()                       # Monday = 0
    return (repeat == "daily" or (repeat == "weekdays" and wd < 5)
            or (repeat == "weekends" and wd >= 5))


def _next_matching(due, repeat, inclusive=False):
    """The next time a repeating reminder rings: same wall-clock time on the
    next matching day (computed on the calendar, so a DST change doesn't
    shift it by an hour)."""
    dt = datetime.fromtimestamp(due, _TZ) if _TZ else datetime.fromtimestamp(due)
    step = {"weekly": lambda d: d + timedelta(days=7),
            "monthly": lambda d: _add_months(d, 1),
            "yearly": lambda d: _add_months(d, 12)}.get(repeat)
    if step:
        # the date they gave is the series' anchor: the next one not in the past
        now = time.time() + 1
        if not inclusive:
            dt = step(dt)
        while (dt.replace(tzinfo=None).replace(tzinfo=_TZ) if _TZ else dt).timestamp() < now:
            dt = step(dt)
    else:
        if not inclusive:
            dt += timedelta(days=1)
        for _ in range(8):
            if _matches(dt, repeat):
                break
            dt += timedelta(days=1)
    if _TZ:                                  # re-resolve the offset for that day
        dt = dt.replace(tzinfo=None).replace(tzinfo=_TZ)
    return dt.timestamp()


_KIND_WORDS = {"minutnik": "timer", "minutniki": "timer", "timer": "timer",
               "budzik": "alarm", "budziki": "alarm", "alarm": "alarm",
               "przypomnienie": "reminder", "przypomnienia": "reminder",
               "reminder": "reminder"}


def _stems(text):
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4}


def skip_tomorrow(now=None):
    """"Wyłącz budzik na jutro" / "jutro bez budzika": tomorrow's wake-up
    alarms are skipped — a repeating one moves to its next day after
    tomorrow, a one-off is removed. (The model's "cancel budzik" deleted a
    weekday alarm for good — 7 Oct probe.) Returns (skipped, next due or None)."""
    now = now or time.time()
    tomorrow = (datetime.fromtimestamp(now) + timedelta(days=1)).date()
    skipped, nxt = 0, None
    with _lock:
        keep = []
        for t in _timers:
            if t["kind"] == "alarm" and datetime.fromtimestamp(t["due"]).date() == tomorrow:
                skipped += 1
                if t.get("repeat", "none") != "none":
                    t["due"] = _next_matching(t["due"], t["repeat"])
                    keep.append(t)
                    nxt = t["due"] if nxt is None else min(nxt, t["due"])
                continue
            keep.append(t)
        _timers[:] = sorted(keep, key=lambda t: t["due"])
        if skipped:
            _save()
    if skipped:
        print(f"[timers] tomorrow's alarm skipped ({skipped})", flush=True)
    return skipped, nxt


def _to_cancel(label):
    """Which entries a cancel means. Never more than asked for: a label that
    matches nothing cancels nothing (it used to clear everything — a weekday
    alarm included)."""
    low = label.lower().strip()
    if low in ("wszystko", "wszystkie", "all", "everything"):
        return list(_timers)
    if low.split()[0:1] in (["wszystkie"], ["all"]) and _all_of(low):   # "wszystkie budziki"
        return [t for t in _timers if t["kind"] in _all_of(low)]
    if low in _KIND_WORDS:                       # "wyłącz budzik"
        return [t for t in _timers if t["kind"] == _KIND_WORDS[low]]
    if not low:
        # "wyłącz minutnik" with no name: the kitchen timers — or the only
        # thing set, if there is just one
        timers_only = [t for t in _timers if t["kind"] == "timer"]
        return timers_only or (list(_timers) if len(_timers) == 1 else [])
    exact = [t for t in _timers if low in t["label"].lower()]
    if exact:
        return exact
    want = _stems(low)                           # "piekarnika" ~ "piekarnik"
    return [t for t in _timers if want & _stems(t["label"])]


_ALL_OF_KIND = (("reminder", r"przypomnie\w*|reminders?"), ("alarm", r"budzik\w*|alarm\w*"),
                ("timer", r"minutnik\w*|timers?"))


def _all_of(said):
    """"Wyłącz wszystkie przypomnienia" — the kinds named, or None when they
    really meant everything (8 Oct sweep: the model's "wszystkie" would have
    taken the weekday alarm along with the reminders)."""
    kinds = {k for k, rx in _ALL_OF_KIND if re.search(rf"\b(?:{rx})\b", said or "", re.I)}
    return kinds or None


def apply(actions, said=""):
    """Carry out the model's timer actions. Returns a short log string.
    said: what the person said — "wszystkie przypomnienia" limits a cancel
    of everything to the reminders."""
    done = []
    with _lock:
        for a in actions or []:
            kind  = str(a.get("type", "")).lower()
            label = str(a.get("label", "")).strip()
            if kind == "timer":
                secs = int(a.get("seconds") or 0)
                if 0 < secs <= 7 * 86400:
                    _timers.append({"due": time.time() + secs, "label": label,
                                    "kind": "timer", "secs": secs, "set": time.time()})
                    done.append(f"timer {secs}s '{label}'")
            elif kind in ("reminder", "alarm"):
                due = _parse_at(str(a.get("at", "")))
                secs = int(a.get("seconds") or 0)
                if not due and not str(a.get("at", "")).strip() and 0 < secs <= 7 * 86400:
                    # "za godzinę" as a reminder with seconds and no "at": the
                    # model sends that, and it used to vanish without a trace
                    due = time.time() + secs
                repeat = str(a.get("repeat", "none")).lower()
                if repeat not in _REPEATS:
                    repeat = "none"
                if due and repeat == "none" and due < time.time() - 60:
                    print(f"[timers] {kind} at {a.get('at')!r} is in the past — ignored")
                    due = None
                if due:
                    if repeat != "none":
                        due = _next_matching(due, repeat, inclusive=True)
                    _timers.append({"due": due, "label": label, "kind": kind,
                                    "repeat": repeat, "set": time.time()})
                    done.append(f"{kind} {time.strftime('%d.%m %H:%M', time.localtime(due))} "
                                f"'{label}'" + (f" ({repeat})" if repeat != "none" else ""))
                else:
                    print(f"[timers] {kind} not set — no usable time in {a}", flush=True)
            elif kind == "cancel":
                gone = _to_cancel(label)
                kinds = _all_of(said) if label.lower().split()[:1] in (
                    ["wszystko"], ["wszystkie"], ["all"], ["everything"]) else None
                if kinds:
                    gone = [t for t in gone if t["kind"] in kinds]
                _timers[:] = [t for t in _timers if t not in gone]
                done.append(f"cancelled {len(gone)}" + ("" if gone else
                            f" (nothing matched '{label}')"))
        _timers.sort(key=lambda t: t["due"])
        del _timers[TIMERS_MAX:]
        if done:
            _save()
    if done:
        print("[timers] " + "; ".join(done), flush=True)
    return done


# ── "minutnik na 10 minut" without the model ─────────────────────────────────

_NUM = {"jeden": 1, "jedna": 1, "jedną": 1, "jedno": 1, "dwa": 2, "dwie": 2,
        "trzy": 3, "cztery": 4, "pięć": 5, "sześć": 6, "siedem": 7, "osiem": 8,
        "dziewięć": 9, "dziesięć": 10, "jedenaście": 11, "dwanaście": 12,
        "trzynaście": 13, "czternaście": 14, "piętnaście": 15, "szesnaście": 16,
        "siedemnaście": 17, "osiemnaście": 18, "dziewiętnaście": 19,
        "dwadzieścia": 20, "trzydzieści": 30, "czterdzieści": 40,
        "pięćdziesiąt": 50, "sześćdziesiąt": 60, "dziewięćdziesiąt": 90}
_UNIT = (("sek", 1), ("min", 60), ("godz", 3600))
# what a bare timer command may contain besides the duration
_TIMER_WORDS = {"minutnik", "timer", "nastaw", "ustaw", "włącz", "odlicz", "odliczaj",
                "na", "mi", "proszę", "luna", "luno", "nowy", "z", "i", "a", "set",
                "for", "a", "minutnika"}


def _unit(word):
    if word.startswith("minutnik"):
        return None
    return next((u for p, u in _UNIT if word.startswith(p)), None)


def parse_duration(text):
    """Seconds in "10 minut", "pięć minut", "dwadzieścia pięć sekund",
    "pół godziny", "półtorej godziny", "kwadrans", "godzinę"; None if none.
    Returns (seconds, set of the words that made up the duration)."""
    words = re.findall(r"\w+", text.lower())
    total, used, i = 0, set(), 0
    while i < len(words):
        w = words[i]
        if w == "kwadrans":
            total += 900; used.add(w); i += 1; continue
        if w in ("pół", "półtorej", "półtora") and i + 1 < len(words) \
                and words[i + 1].startswith(("godz", "min")):
            unit = 3600 if words[i + 1].startswith("godz") else 60
            total += int(unit * (0.5 if w == "pół" else 1.5))
            used.update((w, words[i + 1])); i += 2; continue
        n, j = None, i
        if w.isdigit():
            n, j = int(w), i + 1
        elif w in _NUM:
            n, j = _NUM[w], i + 1
            if n >= 20 and j < len(words) and words[j] in _NUM and _NUM[words[j]] < 10:
                n += _NUM[words[j]]; j += 1                     # dwadzieścia pięć
        if n is not None and j < len(words):
            unit = _unit(words[j])
            if unit:
                total += n * unit
                used.update(words[i:j + 1]); i = j + 1; continue
        if n is None and w in ("minutę", "sekundę", "godzinę"):  # "na godzinę"
            total += _unit(w); used.add(w)
        i += 1
    return (total, used) if total else (None, used)


def local_timer(text):
    """Seconds when the whole utterance is a plain timer request ("nastaw
    minutnik na 10 minut"); None otherwise — anything more ("na makaron")
    goes to the model, which can label it."""
    low = text.lower()
    if not any(k in low for k in ("minutnik", "timer", "odlicz")):
        return None
    secs, used = parse_duration(low)
    if not secs or secs > 7 * 86400:
        return None
    words = set(re.findall(r"\w+", low))
    return secs if words <= (_TIMER_WORDS | used) else None


_REMIND = re.compile(r"^(?:luna,?\s+)?przypomnij\s+(?:mi|nam)\s*,?\s+(.+?)[.!?]*$", re.I)
# a day, a date or a repeat: the model works those out
_REMIND_LATER = re.compile(r"\b(codziennie|co\s+\w+|w\s+weekend|"
                           r"rano|wieczorem|po\s+południu|stycznia|lutego|marca|kwietnia|maja|"
                           r"czerwca|lipca|sierpnia|września|października|listopada|grudnia)\b",
                           re.I)
# a day said with it: "jutro", "pojutrze", "w piątek" (→ days ahead)
_REMIND_DAY = re.compile(r"\b(jutro|pojutrze|w\s+(poniedziałek|wtorek|środę|czwartek|piątek|"
                         r"sobotę|niedzielę))\b\s*,?\s*", re.I)
_WD_ACC = ["poniedziałek", "wtorek", "środę", "czwartek", "piątek", "sobotę", "niedzielę"]
# "żebym zadzwonił", "że mam…": would need turning round ("zadzwoń") — the model
_FIRST_PERSON = re.compile(r"\b(żebym|zebym|mam|muszę|musze|mój|moja|moje|mojej|mnie|"
                           r"mi|bym|jestem|będę)\b", re.I)


def _time_word(w):
    """Can this word be part of a spoken clock time ("wpół do ósmej", "17:30")?"""
    import clockgame
    w = w.strip(".")
    return (bool(re.fullmatch(r"\d{1,2}(?:[:.]\d{2})?", w))
            or w in ("wpół", "wpol", "do", "po", "za", "przed", "zero")
            or clockgame._hour_at([w], 0)[0] is not None
            or clockgame._minutes_at([w], 0)[0] is not None)


def local_reminder(text, now=None):
    """"przypomnij mi za 20 minut o praniu", "przypomnij mi o 17, żeby
    zadzwonić do mamy" → (action for apply(), confirmation); None for
    anything with a day, a repeat or a sentence to turn round."""
    import clock
    import clockgame
    m = _REMIND.match(text.strip())
    if not m or _REMIND_LATER.search(text):
        return None
    rest = m.group(1)
    now_dt = datetime.fromtimestamp(now or time.time())
    day, day_said = 0, ""
    d = _REMIND_DAY.search(rest)
    if d:                                          # "jutro o 8", "w piątek o 17"
        word = d.group(1).lower()
        if word == "jutro":
            day, day_said = 1, "jutro"
        elif word == "pojutrze":
            day, day_said = 2, "pojutrze"
        else:
            wd = _WD_ACC.index(d.group(2).lower())
            day = (wd - now_dt.weekday()) % 7 or 7
            day_said = f"w {d.group(2).lower()}"
        rest = (rest[:d.start()] + rest[d.end():]).strip(" ,")
    span, action, said = None, None, None
    z = re.search(r"\bza\s+((?:\w+\s+){0,3}?(?:sekund\w*|minut\w*|godzin\w*|kwadrans))\b",
                  rest, re.I)
    if z and day:
        return None                                # "jutro za 20 minut": the model
    if z:
        secs, _ = parse_duration(z.group(1))
        if secs and secs <= 86400:
            span = z.span()
            action = {"type": "timer", "seconds": secs}
            said = f"za {say_duration(secs)}"
    else:
        for o in re.finditer(r"\bo\s+", rest, re.I):
            tail = rest[o.end():].split()
            for n in (4, 3, 2, 1):                     # the longest clock time there
                words = tail[:n]
                if len(words) < n:
                    continue
                cand = " ".join(words).rstrip(",").lower()
                t = clockgame.parse(cand)
                after = tail[n].lower() if len(tail) > n else ""
                if re.fullmatch(r"\d+", cand) and after and not words[-1].endswith(",") \
                        and after not in ("że", "żeby", "zeby", "aby", "o", "to"):
                    continue                           # "o 5 rzeczach" is no time
                if t and all(_time_word(w) for w in cand.replace(",", " ").split()):
                    h, mi = t
                    if day:
                        if h <= 6:                     # "jutro o piątej": 17:00, not 5 am
                            h += 12
                        when = (now_dt + timedelta(days=day)).strftime("%Y-%m-%d")
                        at = f"{when} {h:02d}:{mi:02d}"
                    else:
                        if (h, mi) < (now_dt.hour, now_dt.minute) and h < 12 and \
                                (h + 12, mi) > (now_dt.hour, now_dt.minute):
                            h += 12                    # "o piątej" in the afternoon: 17:00
                        at = f"{h:02d}:{mi:02d}"
                    span = (o.start(), o.end() + len(" ".join(tail[:n])))
                    action = {"type": "reminder", "at": at, "repeat": "none"}
                    said = (f"{day_said} " if day_said else "") + f"o {clock.hour_locative(h, mi)}"
                    break
            if span:
                break
    if not span:
        return None
    what = (rest[:span[0]] + " " + rest[span[1]:]).strip(" ,")
    what = re.sub(r"^(?:że|żeby|zeby|aby|to)\s+", "", what, flags=re.I).strip(" ,")
    if not what or len(what.split()) > 8 or _FIRST_PERSON.search(what):
        return None
    action["label"] = what
    return action, f"Dobrze, przypomnę {said}."


_LABEL = re.compile(r"^(.*?\b(?:minutnik\w*|timer|odlicz\w*)\b.*?)\s+(na|do|dla)\s+"
                    r"([a-ząćęłńóśźż]+(?:\s+[a-ząćęłńóśźż]+){0,2})[.!]*$", re.I)


def local_labelled_timer(text):
    """(seconds, label) for "minutnik na 10 minut na makaron", "nastaw timer
    na 8 minut do jajek"; None otherwise (no label, or anything more)."""
    m = _LABEL.match(text.strip())
    if not m:
        return None
    label = m.group(3).lower()
    if parse_duration(label)[0] or set(label.split()) & {"minut", "minuty", "minutę",
                                                         "godzin", "godzinę", "sekund"}:
        return None                                  # "na pół godziny" is the time
    if m.group(2).lower() != "na":                   # "do jajek": the word stays as said
        label = f"{m.group(2).lower()} {label}"
    secs = local_timer(m.group(1))
    return (secs, label) if secs else None


def say_duration(secs):
    """Polish words for a duration, for her confirmation."""
    if secs % 3600 == 0:
        h = secs // 3600
        return "godzinę" if h == 1 else f"{h} {_pl(h, 'godzinę', 'godziny', 'godzin')}"
    if secs == 5400:
        return "półtorej godziny"
    if secs % 60 == 0:
        m = secs // 60
        return "minutę" if m == 1 else f"{m} {_minutes_pl(m) if m != 1 else 'minuta'}"
    return f"{secs} {_pl(secs, 'sekundę', 'sekundy', 'sekund')}"


def _left(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


def prompt_block():
    """Active timers for the system prompt (so "ile zostało?" works)."""
    with _lock:
        items = list(_timers)
    if not items:
        return "\nActive timers and reminders: none.\n"
    now = time.time()
    lines = ["\nActive timers and reminders (soonest first):"]
    today = datetime.fromtimestamp(now).date()
    for t in items:
        # the day too: with only "rings at 10:00" the model put tomorrow's
        # hairdresser on today and found nothing for tomorrow (7 Oct probe)
        due = datetime.fromtimestamp(t["due"])
        days = (due.date() - today).days
        day = ("today" if days == 0 else "tomorrow" if days == 1 else
               due.strftime("%A"))
        at = f"{day} {due:%d.%m} {due:%H:%M}"
        what = t["label"] or ("minutnik" if t["kind"] == "timer" else "przypomnienie")
        first = what.split()[0].lower() if what.split() else ""
        if (t["kind"] != "alarm" and first not in ("o", "że", "ze", "żeby", "aby")
                and len(first) > 3 and re.search(r"(?:ie|ach|ej|ym|im|u|ce)$", first)):
            what = "o " + what               # the model said "tabletce", not "o tabletce"
        rep = t.get("repeat", "none")
        # "przypomnij mi za godzinę wyjąć pranie" is kept as a labelled timer —
        # to the family it's a reminder too (7 Oct probe: "jakie mam
        # przypomnienia?" left it out)
        kind = "timer/reminder" if t["kind"] == "timer" and t["label"] else t["kind"]
        lines.append(f"- {kind} \"{what}\": rings at {at}, {_left(t['due'] - now)} left"
                     + (f", repeats {rep}" if rep != "none" else ""))
    return "\n".join(lines) + "\n"


_REPEAT_PL = {"daily": "codziennie", "weekdays": "pn–pt", "weekends": "weekendy",
              "weekly": "co tydzień", "monthly": "co miesiąc", "yearly": "co roku"}
_KIND_PL = {"timer": "minutnik", "reminder": "przypomnienie", "alarm": "budzik"}


def screen_lines():
    """What "pokaż przypomnienia" lists on her screen: (time, what) pairs."""
    with _lock:
        items = list(_timers)
    out = []
    now = time.time()
    for t in items:
        if t["kind"] == "timer":
            left = int(t["due"] - now)
            if left < 3600:
                when = f"{left // 60}:{left % 60:02d}"
            else:
                when = time.strftime("%H:%M", time.localtime(t["due"]))
        else:
            when = time.strftime("%H:%M", time.localtime(t["due"]))
            if t["due"] - now > 86400 and t.get("repeat", "none") == "none":
                when = time.strftime("%d.%m %H:%M", time.localtime(t["due"]))
        what = t["label"] or _KIND_PL.get(t["kind"], "")
        rep = _REPEAT_PL.get(t.get("repeat", "none"))
        out.append((when, what + (f"  ({rep})" if rep else "")))
    return out


def goodnight_note(within=16 * 3600):
    """What "dobranoc" adds: the next wake-up alarm, if one rings before
    morning is over — "Budzik masz na siódmą trzydzieści." Else None."""
    import clock
    now = time.time()
    with _lock:
        alarms = sorted(t["due"] for t in _timers
                        if t["kind"] == "alarm" and 0 < t["due"] - now < within)
    if not alarms:
        return None
    lt = time.localtime(alarms[0])
    return f"Budzik masz na {clock.hour_accusative(lt.tm_hour, lt.tm_min)}."


def countdown_text():
    """What the corner of the screen shows: the nearest timer, or None."""
    with _lock:
        if not _timers:
            return None
        t = _timers[0]
    left = t["due"] - time.time()
    if t["kind"] in ("reminder", "alarm") and left > 3600:
        return time.strftime("%H:%M", time.localtime(t["due"]))
    left = max(0, int(left))
    h, rem = divmod(left, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── ringing ──────────────────────────────────────────────────────────────────

def _pl(n, one, few, many):
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _minutes_pl(n):
    if n == 1:
        return "minuta"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "minuty"
    return "minut"


_LEFT_Q = re.compile(r"\b(?:ile|jak\s+długo)\b.*\b(?:zostało|zostalo|jeszcze|do\s+końca|"
                     r"do\s+konca)\b.*\b(?:minutnik\w*|timer\w*)\b", re.I)


def _say_left(secs):
    secs = max(0, int(round(secs)))
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append("godzina" if h == 1 else f"{h} {_pl(h, 'godzina', 'godziny', 'godzin')}")
    if m:
        parts.append("minuta" if m == 1 else f"{m} {_minutes_pl(m)}")
    if s and not h and m < 5:                       # seconds only when it is close
        parts.append("sekunda" if s == 1 else f"{s} sekundy" if s % 10 in (2, 3, 4)
                     and s % 100 not in (12, 13, 14) else f"{s} sekund")
    return " i ".join(parts) or "chwila"


def running_timer(now=None):
    """Is a kitchen timer counting down right now?"""
    now = now or time.time()
    with _lock:
        return any(t["kind"] == "timer" and t["due"] > now for t in _timers)


def left_answer(text, now=None):
    """"Ile zostało na minutniku?" → exact, from the running timers; None if
    it isn't that question."""
    now = now or time.time()
    with _lock:
        running = [t for t in _timers if t["kind"] == "timer" and t["due"] > now]
    # bare "Ile zostało?" / "ile jeszcze?" while a timer runs (7 Oct probe: the
    # model guessed "około dziesięciu minut")
    bare = bool(running) and bool(re.fullmatch(
        r"\W*(?:a\s+)?(?:ile\s+(?:jeszcze\s+)?(?:zostało|zostalo|jeszcze)|jak\s+długo\s+jeszcze)"
        r"(?:\s+czasu)?\W*", text.lower()))
    if not (_LEFT_Q.search(text) or bare):
        return None
    if not running:
        return "Nie mam teraz żadnego minutnika."
    running.sort(key=lambda t: t["due"])
    out = []
    for t in running[:3]:
        left = _say_left(t["due"] - now)
        out.append(f"{t['label']}: {left}" if t["label"] else left)
    if len(running) == 1:
        if running[0]["label"]:
            return f"Na minutniku — {out[0]}."
        first = out[0].split()[0]                    # the verb agrees with it
        verb = ("Została" if not first.isdigit() else
                "Zostały" if int(first) % 10 in (2, 3, 4) and int(first) % 100 not in (12, 13, 14)
                else "Zostało")
        return f"{verb} {out[0]}."
    return "Minutniki — " + "; ".join(out) + "."


_REMS_Q = re.compile(r"\b(?:jakie|co)\s+(?:mam\s+|są\s+|masz\s+)?(?:\w+\s+)?przypomnie\w*|"
                     r"\bmoje\s+przypomnienia\b|\bile\s+(?:mam\s+|jest\s+)?przypomnie\w*|"
                     r"\bo\s+czym\s+(?:masz\s+)?mi\s+przypomnie\w*",
                     re.I)
_WD_LOC = ["w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę",
           "w niedzielę"]


def reminders_answer(text, now=None):
    """"Jakie mam przypomnienia?" → every reminder, labelled timer and alarm,
    read from the list itself (7 Oct probe: the model left out "wyjąć pranie
    za godzinę", kept as a labelled timer). None if it isn't that question."""
    import clock
    if not _REMS_Q.search(text) or len(text.split()) > 8:
        return None
    now = now or time.time()
    with _lock:
        items = sorted((t for t in _timers if t["due"] > now
                        and (t["kind"] != "timer" or t["label"])), key=lambda t: t["due"])
    if not items:
        return "Nie masz teraz żadnych przypomnień."
    today = datetime.fromtimestamp(now).date()
    out = []
    for t in items[:5]:
        due = datetime.fromtimestamp(t["due"])
        what = t["label"] or _KIND_PL.get(t["kind"], "")
        first = what.split()[0].lower() if what.split() else ""
        if (first not in ("o", "że", "ze", "żeby", "aby") and len(first) > 3
                and re.search(r"(?:ie|ach|ej|ym|im|u|ce)$", first)):
            what = "o " + what               # "wizycie u dentysty" → "o wizycie…"
        if t["kind"] == "alarm":
            what = f"budzik{' — ' + t['label'] if t['label'] else ''}"
        rep = t.get("repeat", "none")
        at = f"o {clock.hour_locative(due.hour, due.minute)}"
        if t["kind"] == "timer":
            # accusative after "za": "za godzinę", not "za godzina"
            when = f"za {say_duration(max(60, int(round((t['due'] - now) / 60)) * 60))}"
        elif rep != "none":
            when = f"{_REPEAT_PL.get(rep, '')} {at}"
        elif due.date() == today:
            when = f"dziś {at}"
        elif (due.date() - today).days == 1:
            when = f"jutro {at}"
        elif (due.date() - today).days < 7:
            when = f"{_WD_LOC[due.weekday()]} {at}"
        else:
            when = f"{due.day}.{due.month:02d} {at}"
        out.append(f"{what} — {when}")
    more = f" I jeszcze {len(items) - 5}." if len(items) > 5 else ""
    return ("Masz przypomnienie: " if len(out) == 1 else "Masz przypomnienia: ") + \
        "; ".join(out) + "." + more


def _announcement(t, missed=False):
    label = t["label"]
    if t["kind"] == "alarm":
        try:
            from brain import greeting
            text = greeting(True, waking=True)   # good morning + weather + plans
        except Exception:
            text = None
        return text or "Dzień dobry! Pora wstawać."
    if t["kind"] == "timer":
        mins = round(t.get("secs", 0) / 60)
        if label.lower().startswith("o "):           # a reminder "za 20 minut o praniu"
            text = f"Przypominam {label}!"
        elif label.lower().startswith(("do ", "dla ")):   # "minutnik do jajek"
            text = f"Dzyń! Minutnik {label}!"
        elif label:
            text = f"Minął czas: {label}!"
        elif mins >= 1:
            verb = "Minęła" if mins == 1 else ("Minęły" if _minutes_pl(mins) == "minuty" else "Minęło")
            text = f"Dzyń! {verb} {mins} {_minutes_pl(mins)}."
        else:
            text = "Dzyń! Minutnik!"
    else:
        text = (f"Przypominam {label}!" if label.lower().startswith("o ") else   # o praniu
                f"Przypominam: {label}!" if label else "Przypominam o czymś!")
    if missed:
        text = "Byłam wyłączona i przegapiłam przypomnienie. " + text
    return text


def _interacted_since(t0):
    with state.lock:
        return state.touch_time > t0 or state.last_activity_time > t0


def _ring(t, missed=False):
    from text_to_speech import speak, play_sound
    from commands import wake_up
    import audio_out
    wake_up("timer")
    # a timer you set rings at full volume even in the quiet hours
    audio_out.full_volume_until = time.time() + TIMER_REPEAT_SECS + 60
    _last_rang.update(t=time.time(), entry=t)
    text = t.get("say") or _announcement(t, missed)
    if t.get("then"):                                # focus → break
        secs, label, say = t["then"]
        add(secs, label, say)
    if t["kind"] == "alarm":
        import radio
        if radio.wake_up_radio():                    # "budź mnie radiem"
            speak(text)
            with state.lock:
                state.conversation_active = True
                state.last_activity_time = time.time()
            return
    for attempt in range(2):
        with state.lock:
            state.face_override = "surprised"
            state.face_override_until = time.time() + 4.0
            state.gesture_anim = "wave"
            state.gesture_anim_start = time.time()
        play_sound("chime", can_drop=False)
        if attempt and t["kind"] == "alarm":
            speak("Halo, śpiochu! Pora wstawać!")
        else:
            speak(text if attempt == 0 else "Halo! " + text)
        with state.lock:                 # listen for "jeszcze 5 minut" / "dzięki"
            state.conversation_active = True     # without the wake word
            state.last_activity_time = time.time()
        rang = time.time()
        if attempt == 0:
            # once more in a minute, unless you touched her or talked to her
            while time.time() - rang < TIMER_REPEAT_SECS:
                if _interacted_since(rang):
                    return
                time.sleep(0.5)


def add(seconds, label, say=None, then=None):
    """A timer set by Luna herself (focus mode): `say` replaces the usual
    announcement; `then` = (seconds, label, say) is set when it rings."""
    with _lock:
        _timers.append({"due": time.time() + seconds, "label": label, "kind": "timer",
                        "secs": seconds, "say": say, "then": then, "set": time.time()})
        _timers.sort(key=lambda t: t["due"])
        _save()


_last_rang = {"t": 0.0, "entry": None}


def snooze(seconds):
    """"Jeszcze 5 minut" right after something rang: ring it again later.
    Returns False when nothing rang recently."""
    t = _last_rang["entry"]
    if t is None or time.time() - _last_rang["t"] > 600:
        return False
    with _lock:
        _timers.append({"due": time.time() + seconds, "label": t["label"],
                        "kind": t["kind"], "secs": seconds, "say": t.get("say"),
                        "repeat": "none", "set": time.time()})
        _timers.sort(key=lambda x: x["due"])
        _save()
    _last_rang["entry"] = None
    print(f"[timers] snoozed {seconds}s: {t['kind']} '{t['label']}'", flush=True)
    return True


def extend(seconds):
    """"Dodaj 5 minut do minutnika": the nearest kitchen timer runs longer.
    Returns False when no timer is running."""
    with _lock:
        timer = next((t for t in _timers if t["kind"] == "timer"), None)
        if timer is None:
            return False
        timer["due"] += seconds
        timer["secs"] = timer.get("secs", 0) + seconds
        _timers.sort(key=lambda x: x["due"])
        _save()
    print(f"[timers] extended by {seconds}s", flush=True)
    return True


def remove(labels):
    with _lock:
        before = len(_timers)
        _timers[:] = [t for t in _timers if t["label"] not in labels]
        if len(_timers) != before:
            _save()


def _take_due(now):
    """Remove what is due now; a repeating one is put back for its next day."""
    due = []
    with _lock:
        while _timers and _timers[0]["due"] <= now:
            due.append(_timers.pop(0))
        for t in due:
            if t.get("repeat", "none") != "none":
                _timers.append(dict(t, due=_next_matching(t["due"], t["repeat"])))
        if due:
            _timers.sort(key=lambda t: t["due"])
            _save()
    return due


def _watch():
    first = True
    while True:
        try:
            now = time.time()
            due = _take_due(now)
            for t in due:
                if t["kind"] == "alarm":
                    from commands import wake_up     # before the dawn ends
                    wake_up("alarm")
                missed = first and now - t["due"] > 120
                print(f"[timers] ringing: {t['kind']} '{t['label']}'", flush=True)
                threading.Thread(target=_ring, args=(t, missed), daemon=True).start()
            first = False
            # a wake-up alarm close enough: the dawn on the screen
            with _lock:
                alarm = next((t for t in _timers if t["kind"] == "alarm"), None)
            dawn = None
            if alarm and alarm["due"] - now <= SUNRISE_SECS:
                dawn = (alarm["due"] - SUNRISE_SECS, alarm["due"])
            with _lock:
                first_timer = next((t for t in _timers if t["kind"] == "timer"), None)
            with state.lock:
                import counting
                state.timer_text = countdown_text() or counting.stopwatch_text()
                state.sunrise = dawn
                overlay_on = bool(state.overlay and now < state.overlay[1])
                if first_timer and 0 < first_timer["due"] - now <= 5.0 \
                        and not overlay_on:
                    n = int(first_timer["due"] - now) + 1
                    if not state.big_text or state.big_text[0] != str(n):
                        state.big_text = (str(n), now + 0.95)
        except Exception as e:
            print(f"[timers] watch error (recovering): {e}")
        time.sleep(0.2)


def start_timers():
    with _lock:
        _load()
    if _timers:
        print(f"[timers] {len(_timers)} pending from before")
    threading.Thread(target=_watch, daemon=True, name="timers").start()
