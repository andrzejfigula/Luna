"""
schedule.py — the family's week: "plan tygodnia".

  "Pokaż plan tygodnia" / "pokaż plan Mai" / "pokaż harmonogram"  → the page
  "Dodaj do planu: Maja angielski od poniedziałku do piątku o 17"
  "Usuń z planu angielski Mai"
  "Przepisz plan z kartki Mai" / "dodaj ten plan do grafiku Mai" → the
      timetable held to the camera, read (brain.read_timetable) and saved

Each entry: whose it is (or the whole house), what, on which weekdays, at
what time (and till when), and its reminder: how long before, to whom (its
owner, a chosen person, everyone) and whether she says it even when nobody
is around. data/schedule.json; the page (ui_schedule.py) shows the week by
day and person, and a tap on an entry changes its days, time and reminder,
or removes it; "+" asks for a new one by voice. idle_engine calls tick()
every few seconds: a reminder for a person is said when she sees them, from
`before` minutes ahead until GRACE after the start; "always" ones are said
at their time whoever is there (like a timer). The model sees the week in
its prompt (prompt_line), so "Co Maja ma w środę?" is answered from it.
"""

import json
import os
import re
import threading
import time
import uuid

from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "schedule.json")
PAGE_SECS = 90                 # untouched this long, the page closes
GRACE = 10 * 60                # a reminder not said by start + this: dropped for the day
EXPECT_SECS = 40               # after "+": the next sentence is the new entry
BEFORE_STEPS = (None, 0, 5, 10, 15, 30, 60)      # None: no reminder
DEFAULT_BEFORE = 15
DAYS = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")
DAYS_SHORT = ("Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd")
_DAYS_IN = ("w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę",
            "w niedzielę")

_lock = threading.Lock()
_expect = {"until": 0.0, "who": None, "day": None, "draft": None, "paper": False}

_DAY_RX = (r"poniedział\w*", r"wtor\w*|wtork\w*", r"środ\w*|srod\w*", r"czwart\w*",
           r"piątek|piątk\w*|piatek|piatk\w*", r"sobot\w*", r"niedziel\w*")
_DAY_ANY = "|".join(f"(?:{r})" for r in _DAY_RX)
_EVERY = re.compile(r"\b(?:codziennie|co\s+dzień|co\s+dzien|każdego\s+dnia|kazdego\s+dnia|"
                    r"cały\s+tydzień|caly\s+tydzien)\b")
_WORKDAYS = re.compile(r"\b(?:w\s+)?(?:dni\s+robocze|dni\s+powszednie|w\s+tygodniu|"
                       r"dni\s+szkolne)\b")
_WEEKEND = re.compile(r"\b(?:w\s+)?weekend\w*\b")
_EVERYONE = re.compile(r"\b(?:wszyscy|wszystkich|wszystkim|cała\s+rodzina|całej\s+rodziny|"
                       r"cala\s+rodzina|calej\s+rodziny|rodzinn\w*|dla\s+domu|cały\s+dom)\b")

_SHOW = re.compile(r"^(?:luna,?\s+)?(?:(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+|nam\s+)?)?"
                   r"(?:(?:cały\s+|caly\s+)?plan\s+(?:tygodnia|tygodniowy|na\s+tydzień|"
                   r"na\s+tydzien|zajęć|zajec|lekcji)|tygodniowy\s+plan|harmonogram\w*|"
                   r"grafik\w*|rozkład\s+zajęć|rozklad\s+zajec)"
                   r"(?:\s+(?:dla\s+)?(\w+))?\W*$")
_SHOW_WHO = re.compile(r"^(?:luna,?\s+)?(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+|nam\s+)?"
                       r"(?:plan|harmonogram|grafik|zajęcia|zajecia)\s+(\w+)\W*$")
_ADD = re.compile(r"^(?:luna,?\s+)?(?:dodaj|dopisz|wpisz|zapisz)\s+(?:do\s+|w\s+)"
                  r"(?:planu|plan|harmonogramu|harmonogram|grafiku|grafik|kalendarza)"
                  r"(?:\s+(?:tygodnia|tygodniowego|zajęć|zajec))?\W*\s*(.+)$")
_REMOVE = re.compile(r"^(?:luna,?\s+)?(?:usuń|usun|skasuj|wykreśl|wykresl|wyrzuć|wyrzuc)\s+"
                     r"(?:z\s+(?:planu|harmonogramu|grafiku)(?:\s+(?:tygodnia|zajęć|zajec))?"
                     r"\W*\s*(.+)|(.+?)\s+z\s+(?:planu|harmonogramu|grafiku)"
                     r"(?:\s+(?:tygodnia|zajęć|zajec))?)\W*$")
_STOP = re.compile(r"^(?:anuluj|nieważne|niewazne|nic|stop|koniec|zostaw|jednak\s+nie|"
                   r"nie\s+dodawaj|już\s+nic|juz\s+nic)\b")
# after "+": a command or a question is something else, not a title
_NOT_ENTRY = re.compile(r"^(?:luna\W+)?(?:włącz|wlacz|wyłącz|wylacz|pokaż|pokaz|zagraj|graj|"
                        r"opowiedz|nastaw|ustaw|przypomnij|zrób|zrob|powiedz|puść|pusc|"
                        r"ile|jak\w*|co|kto|gdzie|kiedy|czy|dlaczego|któr\w*|ktor\w*)\b|.*\?\s*$")
_FILLER = {"ma", "mają", "mam", "mamy", "masz", "macie", "jest", "są", "będzie",
           "bedzie", "zawsze", "co", "każdy", "każdą", "kazdy", "kazda", "w", "we", "i",
           "oraz", "od", "do", "dla", "o", "godzinie", "godz", "a", "też", "tez", "to",
           "każde", "kazde", "też", "prosze", "proszę", "tak", "potem", "na"}


# ── the data ──────────────────────────────────────────────────────────────────

_mem = {"mtime": None, "data": None}      # the page reads it every frame


def _load():
    """A fresh copy (callers change it); read from the card only when it changed."""
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return {"events": [], "done": {}}
    if _mem["mtime"] != mtime:
        try:
            with open(PATH, encoding="utf-8") as f:
                d = json.load(f)
            _mem.update(mtime=mtime, data={"events": d.get("events") or [],
                                           "done": d.get("done") or {}})
        except (OSError, ValueError):
            return {"events": [], "done": {}}
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


def _mins(at):
    h, m = at.split(":")
    return int(h) * 60 + int(m)


def on_day(wd, who=None):
    """That weekday's entries by time; `who` keeps theirs and the house's."""
    out = [e for e in events() if wd in e["days"]
           and (who is None or e.get("who") in (who, ""))]
    return sorted(out, key=lambda e: _mins(e["at"]))


def add(who, title, days, at, end="", by=None, remind=None, kind=None):
    e = {"id": uuid.uuid4().hex[:8], "who": who or "", "title": title.strip(),
         "days": sorted(set(days)), "at": at, "end": end or "",
         "remind": remind if remind is not None else
         {"before": DEFAULT_BEFORE, "to": "owner", "always": False},
         "added": time.time(), "by": by}
    if kind:
        e["kind"] = kind                     # "lesson": read from a school timetable
    with _lock:
        d = _load()
        d["events"].append(e)
        _save(d)
    print(f"[schedule] added {e['who'] or 'dom'}: {e['title']} {days_said(e['days'])} "
          f"{e['at']}", flush=True)
    return e


def update(eid, **changes):
    with _lock:
        d = _load()
        for e in d["events"]:
            if e["id"] == eid:
                for k, v in changes.items():
                    if k == "remind":
                        e["remind"] = dict(e.get("remind") or {}, **v) if v is not None else None
                    else:
                        e[k] = v
                if "at" in changes or "days" in changes:
                    d["done"].pop(eid, None)      # a new time: it may ring today
                _save(d)
                return e
    return None


def remove(eid):
    with _lock:
        d = _load()
        gone = [e for e in d["events"] if e["id"] == eid]
        d["events"] = [e for e in d["events"] if e["id"] != eid]
        d["done"].pop(eid, None)
        _save(d)
    if gone:
        print(f"[schedule] removed {gone[0]['who'] or 'dom'}: {gone[0]['title']}", flush=True)
    return gone[0] if gone else None


def get(eid):
    return next((e for e in events() if e["id"] == eid), None)


# ── words ─────────────────────────────────────────────────────────────────────

def days_said(days):
    """[0..4] → "od poniedziałku do piątku", [1, 3] → "we wtorek i w czwartek"."""
    days = sorted(set(days))
    if len(days) == 7:
        return "codziennie"
    if days == [5, 6]:
        return "w weekendy"
    gen = ("poniedziałku", "wtorku", "środy", "czwartku", "piątku", "soboty", "niedzieli")
    if len(days) >= 3 and days == list(range(days[0], days[-1] + 1)):
        return f"od {gen[days[0]]} do {gen[days[-1]]}"
    parts = [_DAYS_IN[d] for d in days]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " i " + parts[-1]


def days_short(days):
    days = sorted(set(days))
    if len(days) == 7:
        return "codziennie"
    if len(days) >= 3 and days == list(range(days[0], days[-1] + 1)):
        return f"{DAYS_SHORT[days[0]]}–{DAYS_SHORT[days[-1]]}"
    return ", ".join(DAYS_SHORT[d] for d in days)


def when_said(e):
    return f"{days_said(e['days'])} o {e['at']}" + (f" do {e['end']}" if e.get("end") else "")


def remind_short(e):
    """The reminder in a few words for the page: "15 min · Maja"."""
    r = e.get("remind")
    if not r or r.get("before") is None:
        return "bez przypomnienia"
    b = r["before"]
    to = r.get("to") or "owner"
    who = (e.get("who") or "wszyscy") if to == "owner" else "wszyscy" if to == "everyone" else to
    return (f"{b} min" if b else "o czasie") + f" · {who}" + \
        (" · zawsze" if r.get("always") else "")


# ── reading a new entry from a sentence ───────────────────────────────────────

def _days_of(low):
    """(weekdays, the text without them)."""
    days = set()
    rx_range = re.compile(rf"\bod\s+({_DAY_ANY})\s+do\s+({_DAY_ANY})\b")
    for m in list(rx_range.finditer(low)):
        a = next(i for i, r in enumerate(_DAY_RX) if re.fullmatch(r, m.group(1)))
        b = next(i for i, r in enumerate(_DAY_RX) if re.fullmatch(r, m.group(2)))
        k = a
        while True:
            days.add(k)
            if k == b:
                break
            k = (k + 1) % 7
    low = rx_range.sub(" ", low)
    if _EVERY.search(low):
        days |= set(range(7))
        low = _EVERY.sub(" ", low)
    if _WORKDAYS.search(low):
        days |= set(range(5))
        low = _WORKDAYS.sub(" ", low)
    if _WEEKEND.search(low):
        days |= {5, 6}
        low = _WEEKEND.sub(" ", low)
    for i, r in enumerate(_DAY_RX):
        rx = re.compile(rf"\b(?:w\s+|we\s+|co\s+|każd\w*\s+|kazd\w*\s+)?(?:{r})\b")
        if rx.search(low):
            days.add(i)
            low = rx.sub(" ", low)
    return sorted(days), low


_T = r"\d{1,2}(?:[:.]\d{2})?"


def _clock_of(words):
    import clockgame
    t = clockgame.parse(" ".join(words))
    return t


def _time_of(low):
    """("17:00", "18:00" or "", the text without them) or (None, "", low)."""
    import timers
    m = re.search(rf"\b(?:od|o)\s+(?:godzinie\s+|godz\.?\s+)?({_T})(?:\s*(?:do|-|–)\s*({_T}))?\b",
                  low)
    spans, start, end = [], None, None
    if m:
        start = _clock_of([m.group(1).replace(".", ":") if ":" in m.group(1) or "." in m.group(1)
                           else m.group(1)])
        end = _clock_of([m.group(2)]) if m.group(2) else None
        spans.append(m.span())
    else:
        words = low.split()
        for i, w in enumerate(words):
            if w not in ("o", "od"):
                continue
            j = i + 1
            if j < len(words) and words[j] in ("godzinie",):
                j += 1
            k = j
            while k < len(words) and timers._time_word(words[k]) and not (
                    words[k] == "do" and k > j and words[k - 1] not in ("wpół", "wpol")):
                k += 1
            t = _clock_of(words[j:k]) if k > j else None
            if t:
                start = t
                cut = k
                if k + 1 < len(words) and words[k] == "do":
                    q = k + 1
                    while q < len(words) and timers._time_word(words[q]) and words[q] != "do":
                        q += 1
                    end = _clock_of(words[k + 1:q])
                    if end:
                        cut = q
                low = " ".join(words[:i] + words[cut:])
                break
    if start is None:
        return None, "", low
    for a, b in reversed(spans):
        low = low[:a] + " " + low[b:]
    morning = bool(re.search(r"\brano\b|\bz\s+rana\b|\bprzed\s+południem\b", low))
    low = re.sub(r"\b(?:rano|z\s+rana|wieczorem|po\s+południu|po\s+poludniu|popołudniu)\b", " ",
                 low)

    def fix(t):
        h, mi = t
        if 1 <= h <= 6 and not morning:      # "o piątej" lessons are at 17:00
            h += 12
        return f"{h:02d}:{mi:02d}"
    s = fix(start)
    e = fix(end) if end else ""
    if e and _mins(e) <= _mins(s):
        e = ""
    return s, e, low


def _who_of(text):
    """(who or None, "" for the whole house; the text without the name)."""
    import faces
    low = text
    if _EVERYONE.search(low):
        return "", _EVERYONE.sub(" ", low)
    for w in re.findall(r"\w+", low):
        n = faces.match_name(w) or faces.match_role(w)
        if n:
            return n, re.sub(rf"\b(?:dla\s+)?{re.escape(w)}\b", " ", low, count=1)
    return None, low


def parse(text, who_default=None, day_default=None, partial=False):
    """A new entry from a sentence → dict(who, title, days, at, end) with
    None where it's missing; None when nothing in it looks like one (no day,
    no time — unless `partial`: a short "Maja, angielski" is a start)."""
    low = " ".join(text.lower().replace(",", " , ").split())
    who, low = _who_of(low)
    days, low = _days_of(low)
    at, end, low = _time_of(low)
    words = [w for w in re.findall(r"[\w'-]+", low) if w not in _FILLER]
    title = " ".join(words).strip()
    if not (days or at) and not (partial and title and len(words) <= 4
                                 and not _NOT_ENTRY.match(text.lower().strip())):
        return None
    if who is None:
        who = who_default
    if not days and day_default is not None:
        days = [day_default]
    return {"who": who, "title": title or None, "days": days or None, "at": at, "end": end}


def missing(p):
    if not p["title"]:
        return "Co to za zajęcia?"
    if not p["days"]:
        return "W jakie dni?"
    if not p["at"]:
        return "O której godzinie?"
    return None


# ── voice ─────────────────────────────────────────────────────────────────────

def _speaker():
    with state.lock:
        return state.person[0] if state.person and time.time() - state.person[2] < 30 else None


def expect(who=None, day=None):
    """"+" on the page: the next sentence is the new entry."""
    _expect.update(until=time.time() + EXPECT_SECS, who=who, day=day, draft=None, paper=False)
    with state.lock:
        state.conversation_active = True          # no "Luna" needed for the answer
        state.last_activity_time = time.time()


def expecting():
    return time.time() < _expect["until"]


def _confirm(e):
    whose = f"{e['who']} ma " if e["who"] else ""
    r = e.get("remind") or {}
    note = (f" Przypomnę {r['before']} minut wcześniej." if r.get("before") else
            " Przypomnę o czasie." if r.get("before") == 0 else "")
    return f"Dobrze, zapisałam: {whose}{e['title']} {when_said(e)}.{note}"


def _take(p, speak):
    """A parsed entry: saved, or the missing part asked for."""
    ask = missing(p)
    if ask:
        _expect.update(until=time.time() + EXPECT_SECS, draft=p)
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        speak(ask)
        return True
    _expect.update(until=0.0, draft=None)
    e = add(p["who"] or "", p["title"], p["days"], p["at"], p.get("end"), by=_speaker(),
            remind=p.get("remind"), kind=p.get("kind"))
    _toast(f"Dodane: {e['title']}")
    _refresh(e["days"][0] if e["days"] else None)
    speak(_confirm(e))
    return True


def _fill(draft, text):
    """The answer to "W jakie dni?" / "O której?" / "Co to za zajęcia?"."""
    p = parse(text) or {"who": None, "title": None, "days": None, "at": None, "end": ""}
    out = dict(draft)
    for k in ("days", "at", "end"):
        if not out.get(k) and p.get(k):
            out[k] = p[k]
    if p.get("who") and not out.get("who"):
        out["who"] = p["who"]
    if not out.get("title"):
        out["title"] = p.get("title") or " ".join(
            w for w in re.findall(r"[\w'-]+", text.lower()) if w not in _FILLER) or None
    return out


def _match(text):
    """The entries a removal means: by title words, and the name if said."""
    who, low = _who_of(text.lower())
    days, low = _days_of(low)
    words = {w[:5] for w in re.findall(r"\w{3,}", low) if w not in _FILLER}
    hits = []
    for e in events():
        if who is not None and e.get("who") != who:
            continue
        tw = {w[:5] for w in re.findall(r"\w{3,}", e["title"].lower())}
        if words and tw and len(words & tw) >= (len(tw) + 1) // 2:
            hits.append(e)
    return hits


# ── a plan on paper, read by the camera ───────────────────────────────────────
# 26 Oct: Andrzej showed Maja's school timetable; she read it aloud, but her
# answer ran out of tokens before one entry and nothing was saved.

_PAPER_VERB = re.compile(r"\b(?<!nie\s)(?:przepisz\w*|przepisa\w*|dodaj|dodaj\w+|dodał\w*|dodać|"
                         r"wpisz\w*|wpisa\w*|zapisz\w*|zapisa\w*|dopisz\w*|dopisa\w*|wczytaj\w*|"
                         r"wczyta\w*|przenieś\w*|przenies\w*|wrzuć|wrzuc|zeskanuj\w*)\b")
_PAPER_REF = re.compile(r"\b(?:kartk\w*|kartce|papier\w*|rozpisk\w*|plan\w*\s+lekcji|"
                        r"(?:ten|tego|tym|tę|te|to)\s+(?:plan\w*|grafik\w*|rozkład\w*|"
                        r"harmonogram\w*))\b")
_PLAN_WORD = re.compile(r"\b(?:plan\w*|grafik\w*|harmonogram\w*|rozkład\w*|kalendarz\w*|"
                        r"lekcj\w*|zajęci\w*|zajęć|zajec)\b")
_MINE = re.compile(r"\b(?:mój|moj|moja|moje|mojego|moich|mi|mnie)\b")
# lesson numbers 1–8 and no hours on the paper: the usual bells (said aloud)
BELLS = ("08:00", "08:55", "09:50", "10:55", "11:50", "12:45", "13:40", "14:35")
LESSON_MINS = 45
_HM = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")
_reading = [0.0]                # a paper being read until then: no second one


_INTO = re.compile(r"\bdo\s+(?:\w+\s+)?(?:planu|grafik\w*|harmonogram\w*|kalendarz\w*)\b")


def paper_request(text):
    """"Weź ten plan i dodaj do grafiku Mai", "przepisz plan z kartki",
    "mam na kartce plan Mai, ogarniesz go do jej grafiku?" — True."""
    low = text.lower()
    return bool(len(low.split()) <= 25 and (_PAPER_VERB.search(low) or _INTO.search(low))
                and _PAPER_REF.search(low) and _PLAN_WORD.search(low)
                and not re.search(r"\bnie\s+(?:dodawaj|wpisuj|przepisuj|zapisuj)", low))


def _hm(s):
    m = _HM.match(s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _plus(at, mins):
    t = _mins(at) + mins
    return f"{t // 60 % 24:02d}:{t % 60:02d}"


def from_paper(rows):
    """brain.read_timetable's entries → (entries, unclear, bells): each entry
    {title, days, at, end, kind} with the same title and hours on several days
    merged; unclear = those with no readable time; bells = the usual hours were
    used for numbered lessons (none on the paper)."""
    clean = []
    for r in rows or []:
        title = " ".join(str(r.get("title") or "").split()).strip(" .,;:-–")
        days = sorted({int(d) for d in r.get("days") or [] if isinstance(d, int) and 0 <= d <= 6})
        if not title or not days:
            continue
        kind = "lesson" if r.get("kind") == "lesson" else "activity"
        no = r.get("lesson_no") if isinstance(r.get("lesson_no"), int) else 0
        clean.append({"title": title, "days": days, "at": _hm(r.get("at")),
                      "end": _hm(r.get("end")), "kind": kind, "no": no})
    # a numbered lesson with no hours: the hours of that number elsewhere
    by_no = {}
    for c in clean:
        if c["kind"] == "lesson" and c["no"] and c["at"]:
            by_no.setdefault(c["no"], (c["at"], c["end"]))
    bells = False
    lessons = [c for c in clean if c["kind"] == "lesson"]
    if lessons and not any(c["at"] for c in lessons):
        bells = any(1 <= c["no"] <= len(BELLS) for c in lessons)
        by_no = {i + 1: (b, _plus(b, LESSON_MINS)) for i, b in enumerate(BELLS)}
    for c in clean:
        if not c["at"] and c["kind"] == "lesson" and c["no"] in by_no:
            c["at"], c["end"] = by_no[c["no"]]
    merged, unclear = {}, []
    for c in clean:
        if c["end"] and c["at"] and _mins(c["end"]) <= _mins(c["at"]):
            c["end"] = ""
        if not c["at"]:
            unclear.append(c)
            continue
        key = (c["title"].lower(), c["at"], c["end"])
        if key in merged:
            merged[key]["days"] = sorted(set(merged[key]["days"]) | set(c["days"]))
        else:
            merged[key] = {k: c[k] for k in ("title", "days", "at", "end", "kind")}
    out = sorted(merged.values(), key=lambda e: (min(e["days"]), _mins(e["at"])))
    return out, unclear, bells


_NO_REMIND = {"before": None, "to": "owner", "always": False}


def save_paper(who, entries, by=None):
    """The read entries into the plan: (added, already there). An entry with
    the same owner, title and time gets the new days instead of a twin."""
    added, kept = [], []
    for e in entries:
        same = next((x for x in events() if x.get("who", "") == who
                     and x["title"].lower() == e["title"].lower() and x["at"] == e["at"]), None)
        if same:
            if not set(e["days"]) <= set(same["days"]):
                update(same["id"], days=sorted(set(same["days"]) | set(e["days"])))
            kept.append(same)
            continue
        added.append(add(who, e["title"], e["days"], e["at"], e["end"], by=by,
                         remind=dict(_NO_REMIND) if e["kind"] == "lesson" else None,
                         kind="lesson" if e["kind"] == "lesson" else None))
    return added, kept


def _pl(n, one, few, many):
    if n == 1:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def paper_said(who, added, kept, unclear, bells):
    """What she says after reading the paper (and the question for the first
    entry with no time, if any)."""
    lessons = [e for e in added if e.get("kind") == "lesson"]
    other = [e for e in added if e.get("kind") != "lesson"]
    n = sum(len(e["days"]) for e in lessons)
    parts = []
    if lessons:
        days = sorted({d for e in lessons for d in e["days"]})
        parts.append(f"{n} {_pl(n, 'lekcję', 'lekcje', 'lekcji')} {days_said(days)}")
    if other:
        parts.append("zajęcia: " + "; ".join(f"{e['title']} {when_said(e)}" for e in other[:4])
                     + (f" i {len(other) - 4} innych" if len(other) > 4 else ""))
    if parts:
        whose = f"{who} ma teraz w planie" if who else "W planie domu jest teraz"
        out = f"Przepisałam z kartki. {whose} " + ", a ".join(parts) + "."
    elif kept:
        out = "To wszystko już jest w planie tygodnia."
    else:
        out = ""
    if kept and parts:
        out += f" {len(kept)} {_pl(len(kept), 'pozycję', 'pozycje', 'pozycji')} już było."
    if bells:
        out += (" Godzin lekcji nie ma na kartce, więc wpisałam zwykłe dzwonki od ósmej — "
                "popraw je na ekranie, jeśli są inne.")
    if other:
        out += f" O zajęciach przypomnę {DEFAULT_BEFORE} minut wcześniej, o lekcjach nie."
    ask = None
    if unclear:
        u = unclear[0]
        rest = unclear[1:]
        out += f" Nie odczytałam godziny: {u['title']} {days_said(u['days'])}."
        if rest:
            out += " Ani: " + ", ".join(r["title"] for r in rest[:3]) + " — dopisz je potem."
        ask = f"O której jest {u['title']}?"
    return out.strip(), ask


def _frames(n=3, gap=0.6):
    import brain
    imgs = []
    for i in range(n):
        if i:
            time.sleep(gap)
        img = brain._camera_jpeg_b64()
        if img:
            imgs.append(img)
    return imgs


def import_paper(who, speak):
    """Read the plan held to the camera and save it as `who`'s entries; the
    reading (15–30 s) runs on its own thread with "Czytam plan…" on screen."""
    import brain
    if time.time() < _reading[0]:
        print("[schedule] already reading a plan on paper", flush=True)
        return True
    if brain._camera_jpeg_b64() is None:
        speak("Nie widzę teraz nic przez kamerę, więc kartki nie przeczytam.")
        return True
    _reading[0] = time.time() + 90
    # (from the model's answer — brain._spoken_command's thread — this waits for
    # her reply to end); the frames after it, while they hold the paper up
    speak("Potrzymaj kartkę chwilę prosto przed kamerą." if
          threading.current_thread().name == "command" else
          "Dobrze, czytam kartkę — potrzymaj ją chwilę prosto przed kamerą.")
    imgs = _frames()
    by = _speaker()
    with state.lock:
        state.overlay = ("card", time.time() + 60, {"text": "Czytam plan…", "sub": "",
                                                     "tone": None})
    print(f"[schedule] reading a plan on paper for {who or 'dom'} ({len(imgs)} frames)",
          flush=True)

    def run():
        from text_to_speech import speak as say
        got = brain.read_timetable(imgs)
        _reading[0] = 0.0
        with state.lock:
            if state.overlay and state.overlay[0] == "card":
                state.overlay = None
        if not got or not got.get("readable") or not got.get("entries"):
            say("Nie umiem odczytać tej kartki. Przysuń ją bliżej, prosto do kamery, "
                "i powiedz jeszcze raz: przepisz plan z kartki.")
            return
        entries, unclear, bells = from_paper(got["entries"])
        added, kept = save_paper(who, entries, by=by)
        text, ask = paper_said(who, added, kept, unclear, bells)
        print(f"[schedule] from paper: {len(added)} added, {len(kept)} already there, "
              f"{len(unclear)} with no time{', usual bells' if bells else ''}", flush=True)
        show(who, day=min(added[0]["days"]) if added else None)
        say(text + (" " + ask if ask else ""))
        try:
            brain.add_to_last_reply(f"(Zapisane w planie tygodnia z kartki: {len(added)} "
                                    "pozycji — widać je na ekranie.)")
        except Exception:
            pass
        if ask:
            u = unclear[0]
            expect(who)                       # (clears the draft: set it after)
            _expect["draft"] = {"who": who, "title": u["title"], "days": u["days"],
                                "at": None, "end": "",
                                "remind": dict(_NO_REMIND) if u["kind"] == "lesson" else None,
                                "kind": "lesson" if u["kind"] == "lesson" else None}
    threading.Thread(target=run, daemon=True, name="schedule-paper").start()
    return True


def _paper_who(text):
    """(who, known): the person named, "mój" → the speaker; known False when
    nobody can be told."""
    import faces
    # "do grafiku Mai" first — her own "Andrzeju, …" may come before it
    for m in re.finditer(r"\b(?:plan\w*|grafik\w*|harmonogram\w*|kalendarz\w*)\s+"
                         r"(?:lekcji\s+|zajęć\s+|dla\s+)?(\w+)", text.lower()):
        n = faces.match_name(m.group(1)) or faces.match_role(m.group(1))
        if n:
            return n, True
    who, _ = _who_of(text.lower())
    if who is not None:
        return who, True
    if _MINE.search(text.lower()) and _speaker():
        return _speaker(), True
    return None, False


def handle(text, speak):
    """Local commands for the week's plan. True when handled."""
    low = text.lower().strip()
    if expecting() and _expect.get("paper"):
        _expect.update(until=0.0, paper=False)
        who, known = _paper_who(text)
        if known:
            return import_paper(who, speak)
        if _STOP.match(low):
            speak("Dobrze, nie przepisuję.")
            return True
        if re.match(r"^(?:co|słucham|że co|powtórz|powtorz|jak)\W*$", low):
            _expect.update(until=time.time() + EXPECT_SECS, paper=True)
            speak("Czyj to plan? Powiedz na przykład: Mai.")
            return True
        # something else: not the answer
    if expecting():
        draft = _expect.get("draft")
        if _STOP.match(low):
            _expect.update(until=0.0, draft=None)
            speak("Dobrze, nic nie dodaję.")
            return True
        if re.match(r"^(?:co|słucham|że co|powtórz|powtorz|jak)\W*$", low):
            speak(missing(draft) if draft else "Powiedz, co dodać, na przykład: "
                  "Maja, angielski, od poniedziałku do piątku o siedemnastej.")
            _expect["until"] = time.time() + EXPECT_SECS
            return True
        if draft:
            filled = _fill(draft, text)
            if missing(filled) != missing(draft) or (len(text.split()) <= 4
                                                      and not _NOT_ENTRY.match(low)):
                return _take(filled, speak)
        else:
            p = parse(text, _expect.get("who"), _expect.get("day"), partial=True)
            if p:
                return _take(p, speak)
        _expect.update(until=0.0, draft=None)        # something else: not an entry
    if paper_request(text):
        who, known = _paper_who(text)
        if known:
            return import_paper(who, speak)
        _expect.update(until=time.time() + EXPECT_SECS, draft=None, paper=True)
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        speak("Czyj to plan? Powiedz na przykład: Mai.")
        return True
    m, m2 = _SHOW.match(low), _SHOW_WHO.match(low)
    if m or m2:
        import faces
        name = (m.group(1) if m else m2.group(1)) or ""
        who = (faces.match_name(name) or faces.match_role(name)) if name else None
        if not m and not who:
            return False                     # "pokaż plan dnia" and the like
        show(who)
        speak(today_said(who))
        return True
    m = _ADD.match(low)
    if m:
        body = text.strip()[m.start(1):]
        first = re.match(r"^([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż]+)\s*,\s*(.+)$", body)
        if first and _who_of(body)[0] is None and first.group(2).count(",") >= 1:
            # "dodaj do planu: Babcia, wizyta, w sobotę o 15" — someone she doesn't know by face
            p = parse(first.group(2), partial=True)
            if p:
                p["who"] = first.group(1)
                return _take(p, speak)
        p = parse(m.group(1), who_default=_speaker(), partial=True)
        if not p:
            who, rest = _who_of(m.group(1))
            p = {"who": who if who is not None else _speaker(),
                 "title": rest.strip(" .,:") or None, "days": None, "at": None, "end": ""}
        return _take(p, speak)
    m = _REMOVE.match(low)
    if m:
        hits = _match(m.group(1) or m.group(2) or "")
        if not hits:
            speak("Nie widzę tego w planie tygodnia.")
        elif len(hits) > 1:
            speak("Pasuje kilka: " + "; ".join(f"{e['title']} {e['who']}".strip() for e in hits[:4])
                  + ". Powiedz też, czyje.")
        else:
            remove(hits[0]["id"])
            _refresh()
            speak(f"Usunęłam z planu: {hits[0]['title']}"
                  + (f" ({hits[0]['who']})" if hits[0]["who"] else "") + ".")
        return True
    return False


def today_said(who=None, now=None):
    lt = time.localtime(now or time.time())
    today = on_day(lt.tm_wday, who)
    if not events():
        return ("Plan tygodnia jest jeszcze pusty. Dotknij plusa albo powiedz: dodaj do planu, "
                "Maja, angielski, od poniedziałku do piątku o siedemnastej.")
    if not today:
        return "Oto plan tygodnia. Na dziś nic w nim nie ma."
    parts = [f"{e['title']}" + (f" — {e['who']}" if e["who"] and not who else "")
             + f" o {e['at']}" for e in today[:3]]
    return "Oto plan tygodnia. Dziś: " + "; ".join(parts) + "."


# ── the page ──────────────────────────────────────────────────────────────────

def show(who=None, day=None):
    import faces
    if who and who not in faces.names():
        who = None
    data = {"day": time.localtime().tm_wday if day is None else day, "who": who,
            "sel": None, "page": 0, "confirm": 0.0, "toast": None}
    with state.lock:
        state.overlay = ("schedule", time.time() + PAGE_SECS, data)


def _page():
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "schedule" and time.time() < ov[1]:
            state.overlay = (ov[0], max(ov[1], time.time() + PAGE_SECS), ov[2])
            return ov[2]
    return None


def _refresh(day=None):
    d = _page()
    if d is not None and day is not None and d.get("sel") is None:
        d["day"] = day


def _toast(msg):
    d = _page()
    if d is not None:
        d["toast"] = (msg, time.time() + 3.0)


def people():
    """The page's person chips: everyone she knows, and anyone in the plan."""
    import faces
    names = list(faces.names())
    for e in events():
        if e.get("who") and e["who"] not in names:
            names.append(e["who"])
    return names


def _next(seq, cur):
    seq = list(seq)
    return seq[(seq.index(cur) + 1) % len(seq)] if cur in seq else seq[0]


def _say(text):
    """Speak from the render thread's tap without holding it up."""
    def run():
        try:
            from text_to_speech import speak
            speak(text)
        except Exception as e:
            print(f"[schedule] could not speak: {e}", flush=True)
    threading.Thread(target=run, daemon=True, name="schedule-say").start()


def tap(x, y, W, H, speak=None):
    """A tap (px) on the page. True when it was on the page's controls."""
    import ui_schedule
    d = _page()
    if d is None:
        return False
    hit = ui_schedule.hit(x, y, W, H, d)
    if not hit:
        return True
    kind = hit[0]
    now = time.time()
    if kind == "day":
        d["day"], d["page"] = hit[1], 0
    elif kind == "who":
        d["who"], d["page"] = hit[1], 0
    elif kind == "row":
        d["sel"], d["confirm"] = hit[1], 0.0
    elif kind == "more":
        d["page"] += 1
    elif kind == "add":
        expect(d.get("who"), d.get("day"))
        (speak or _say)("Powiedz, co dodać — kto, co, w jakie dni i o której. Na przykład: "
                               "Maja, angielski, od poniedziałku do piątku o siedemnastej.")
    elif kind == "back":
        d["sel"], d["confirm"] = None, 0.0
    else:
        e = get(d.get("sel") or "")
        if e is None:
            d["sel"] = None
            return True
        r = dict(e.get("remind") or {"before": None, "to": "owner", "always": False})
        if kind == "eday":
            days = set(e["days"]) ^ {hit[1]}
            if days:
                update(e["id"], days=sorted(days))
            else:
                d["toast"] = ("Choć jeden dzień", now + 2.0)
        elif kind in ("at-", "at+", "end-", "end+"):
            key = "at" if kind.startswith("at") else "end"
            base = e.get(key) or (e["at"] if key == "end" else "17:00")
            m = (_mins(base) + (15 if kind.endswith("+") else -15)) % (24 * 60)
            if key == "end" and not e.get("end"):
                m = _mins(e["at"]) + 60
            val = f"{m // 60:02d}:{m % 60:02d}"
            if key == "end" and _mins(val) <= _mins(e["at"]):
                val = ""
            update(e["id"], **{key: val})
        elif kind == "before":
            r["before"] = _next(BEFORE_STEPS, r.get("before"))
            update(e["id"], remind=r)
        elif kind == "to":
            opts = ["owner", "everyone"] + [n for n in people() if n != e.get("who")]
            r["to"] = _next(opts, r.get("to") or "owner")
            update(e["id"], remind=r)
        elif kind == "always":
            r["always"] = not r.get("always")
            update(e["id"], remind=r)
        elif kind == "delete":
            if now - d.get("confirm", 0.0) < 4.0:
                remove(e["id"])
                d["sel"], d["confirm"] = None, 0.0
                d["toast"] = (f"Usunięte: {e['title']}", now + 3.0)
            else:
                d["confirm"] = now
    return True


def swipe(dx):
    d = _page()
    if d is None or d.get("sel"):
        return False
    d["day"], d["page"] = (d["day"] + (1 if dx < 0 else -1)) % 7, 0
    return True


# ── reminders (idle_engine) ───────────────────────────────────────────────────

def _targets(e):
    """Whom it's for: a list of names, or None for whoever is there."""
    r = e.get("remind") or {}
    to = r.get("to") or "owner"
    if to == "everyone" or (to == "owner" and not e.get("who")):
        return None
    return [e["who"]] if to == "owner" else [to]


def due(now=None):
    """(event, start time) whose reminder is due now and not said today."""
    now = now or time.time()
    lt = time.localtime(now)
    today = time.strftime("%Y-%m-%d", lt)
    out = []
    with _lock:
        d = _load()
    for e in d["events"]:
        r = e.get("remind")
        if not r or r.get("before") is None or lt.tm_wday not in e["days"]:
            continue
        if d["done"].get(e["id"]) == today:
            continue
        h, m = (int(x) for x in e["at"].split(":"))
        start = time.mktime(lt[:3] + (h, m, 0, 0, 0, -1))
        if start - r["before"] * 60 <= now <= start + GRACE:
            out.append((e, start))
    return out


def _mark(eid, now=None):
    with _lock:
        d = _load()
        d["done"][eid] = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        _save(d)


def phrase(e, to, start, now=None):
    """The reminder in her words, to `to` (a name) or to the room (None)."""
    import faces
    import timers
    now = now or time.time()
    left = int(round((start - now) / 60.0))
    when = ("teraz" if left <= 0 else f"za {timers.say_duration(left * 60)}"
            if left < 60 else f"o {e['at']}")
    if left <= 0 and now - start > 60:
        when = "już"
    title = e["title"]
    owner = e.get("who") or ""
    if to:
        voc = faces.vocatives().get(to) or to
        if owner == to:
            return (f"{voc}, właśnie trwa {title} — o {e['at']}." if when == "już"
                    else f"{voc}, {when} masz {title}.")
        if owner:
            return f"{voc}, przypominam: {owner} {when} ma {title}."
        return f"{voc}, przypominam: {when} {title}."
    if owner:
        return f"Przypominam: {owner} {when} ma {title}."
    return f"Przypominam: {when} {title}."


def tick(now, person, someone, can_speak, busy, speak):
    """Say what is due: to its person when she sees them (person = the name
    recognised just now, or None; someone = any face in view), one for
    everyone to whoever is there; an "always" one at its time, whoever is
    there (not while she is talking). Returns how many were said."""
    said = 0
    for e, start in due(now):
        r = e["remind"]
        targets = _targets(e)
        here = bool(person or someone) if targets is None else person in targets
        if here and can_speak and not busy:
            to = person
        elif r.get("always") and not busy:
            here = False
            to = targets[0] if targets else None
        else:
            if now > start + GRACE - 10:
                _mark(e["id"], now)
                print(f"[schedule] not said (nobody to tell): {e['title']}", flush=True)
            continue
        text = phrase(e, to, start, now)
        _mark(e["id"], now)
        print(f"[schedule] reminding {to or 'the room'}: {text}", flush=True)
        if not here:                          # nobody seen: a chime first, like a timer
            try:
                from commands import wake_up
                wake_up("schedule")
                from text_to_speech import play_sound
                play_sound("chime", can_drop=False)
            except Exception:
                pass
        speak(text)
        try:
            import brain
            brain.note_said(text)
        except Exception:
            pass
        said += 1
    return said


def prompt_line():
    evs = events()
    if not evs:
        return ""
    lessons = [e for e in evs if e.get("kind") == "lesson"]
    by = sorted((e for e in evs if e.get("kind") != "lesson"),
                key=lambda e: (e.get("who") or "~", min(e["days"]), _mins(e["at"])))
    school = []
    for who in sorted({e.get("who") or "" for e in lessons}):
        days = []
        for wd in range(7):
            day = sorted((e for e in lessons if (e.get("who") or "") == who and wd in e["days"]),
                         key=lambda e: _mins(e["at"]))
            if day:
                days.append(f"{DAYS_SHORT[wd]} " + ", ".join(f"{e['at']} {e['title']}"
                                                              for e in day))
        school.append(f"{who or 'the whole house'}'s school lessons: " + "; ".join(days))
    return ("The family's weekly plan (plan tygodnia; the app reminds by itself, "
            "\"pokaż plan tygodnia\" shows it; to add or remove an entry use the command "
            "\"dodaj do planu: <kto>, <co>, <dni>, o <godzina>\" / \"usuń z planu <co> <kto>\"): "
            + "; ".join([f"{e.get('who') or 'the whole house'}: {e['title']} "
                         f"{days_said(e['days'])} {e['at']}"
                         + (f"–{e['end']}" if e.get("end") else "") for e in by] + school)
            + ".\n")


def today_rows(now=None):
    """Today's entries for "plan dnia" (screens.today_rows)."""
    lt = time.localtime(now or time.time())
    return [(e["at"], f"{e['who']}: {e['title']}" if e.get("who") else e["title"])
            for e in on_day(lt.tm_wday)]
