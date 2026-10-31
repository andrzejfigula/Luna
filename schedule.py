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
from shared_state import close_after, state

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
_expect = {"until": 0.0, "who": None, "day": None, "draft": None, "paper": False,
           "fresh": False}
# the entry just added by voice: "to ma być w planie lekcji" means it
_last = {"id": None, "t": 0.0}
LAST_SECS = 10 * 60
# "wyczyść plan lekcji / tygodnia" asked back: "tak" wipes it. what: "lessons" | "week";
# who None for the week: everyone's
_clearing = {"what": None, "who": None, "until": 0.0}
UNDO_SECS = 24 * 3600          # "przywróć plan": what a clear or removal took, this long
BARE_UNDO_SECS = 120           # a bare "cofnij" — only this soon after

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
                   r"na\s+tydzien|zajęć|zajec)|tygodniowy\s+plan|harmonogram\w*|"
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
                     r"(?:\s+(?:tygodnia|zajęć|zajec|lekcji))?(?:\s+(?:dla\s+)?(\w+))?)\W*$")
# "przywróć plan lekcji (Mai)", "cofnij usunięcie z planu", "przywróć paradę"
_RESTORE = re.compile(r"^(?:luna,?\s+)?(?:przywróć|przywroc|odzyskaj|cofnij)\b\s*(.*)$")
_RESTORE_WORD = re.compile(r"\b(?:plan\w*|lekcj\w*|lekcje|grafik\w*|harmonogram\w*)\b")
_LESSONS_SHOW = re.compile(
    r"^(?:luna,?\s+)?(?:(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+|nam\s+)?|"
    r"(?:a\s+)?jaki\s+(?:jest\s+|mam\s+|masz\s+)?)?(?:(?:mój|moj|swój|swoj)\s+)?"
    r"plan\s+lekcji(?:\s+(?:dla\s+)?(\w+))?\W*$|"
    r"^(?:luna,?\s+)?(?:pokaż|pokaz)\s+(?:mi\s+)?(?:moje\s+)?lekcje(?:\s+(\w+))?\W*$")
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


def remove(eid, keep=False):
    """keep: by voice or a tap — "przywróć" brings it back (not a paper's own swap)."""
    with _lock:
        d = _load()
        gone = [e for e in d["events"] if e["id"] == eid]
        d["events"] = [e for e in d["events"] if e["id"] != eid]
        d["done"].pop(eid, None)
        _save(d)
    if gone and keep:
        e = gone[0]
        _keep(gone, f"do planu: {e['title']}" + (f" ({e['who']})" if e.get("who") else ""))
    if gone:
        print(f"[schedule] removed {gone[0]['who'] or 'dom'}: {gone[0]['title']}", flush=True)
    return gone[0] if gone else None


def get(eid):
    return next((e for e in events() if e["id"] == eid), None)


def _undo_path():
    return PATH.replace(".json", "_undo.json")


def _keep(gone, said):
    """What a clear or removal took, for "przywróć plan" (a file: a restart
    must not lose it). said: "plan lekcji Mai", "do planu: parada (Maja)"."""
    try:
        with open(_undo_path() + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            json.dump({"t": time.time(), "said": said, "events": gone}, f, ensure_ascii=False)
        os.replace(_undo_path() + ".tmp", _undo_path())
    except OSError as e:
        print(f"[schedule] undo not kept: {e}", flush=True)


def _kept():
    try:
        with open(_undo_path(), encoding="utf-8") as f:
            u = json.load(f)
        return u if u.get("events") else None
    except (OSError, ValueError, AttributeError):
        return None


def restore(text, now=None):
    """"przywróć plan lekcji", "cofnij usunięcie z planu", "przywróć paradę" or
    a bare "cofnij" just after → the reply; None when it isn't for the plan."""
    now = time.time() if now is None else now
    m = _RESTORE.match(text.lower().strip())
    if not m or len(text.split()) > 9:
        return None
    rest = m.group(1).strip(" .!?")
    u = _kept()
    fresh = u and now - u["t"] <= UNDO_SECS
    if not rest or re.fullmatch(r"to|z\s+powrotem|to\s+z\s+powrotem", rest):
        import lists                 # the newer one of the two undos takes a bare "cofnij"
        lu = lists._undo
        if not fresh or now - u["t"] > BARE_UNDO_SECS or (lu and lu[0] > u["t"]):
            return None
    elif not _RESTORE_WORD.search(rest):
        titles = {w[:5] for e in (u["events"] if fresh else []) for w in re.findall(r"\w{3,}", e["title"].lower())}
        if not titles & {w[:5] for w in re.findall(r"\w{3,}", rest)}:
            return None              # "przywróć listę", "cofnij minutnik"
    if not fresh:
        return "Nie mam czego przywrócić — nic ostatnio nie znikało z planu."
    with _lock:
        d = _load()
        have = {e["id"] for e in d["events"]}
        back = [e for e in u["events"] if e["id"] not in have]
        d["events"] += back
        if back:
            _save(d)
    try:
        os.remove(_undo_path())
    except OSError:
        pass
    print(f"[schedule] restored {len(back)} entries ({u['said']})", flush=True)
    _refresh()
    if not back:
        return "Plan jest już taki jak wcześniej."
    return f"Przywróciłam {u['said']}."


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
    if e.get("end"):                          # (26 Oct: "w środę o 16:00 do 17:30")
        return f"{days_said(e['days'])} od {e['at']} do {e['end']}"
    return f"{days_said(e['days'])} o {e['at']}"


_PLURAL_A = re.compile(r"(?:enia|ania|ęcia|ecia|ycia|icia)$")


def title_after_ma(title):
    """"Maja ma …": "lekkoatletyka" → "lekkoatletykę", "piłka nożna" →
    "piłkę nożną"; "angielski", "zajęcia dodatkowe" stay (26 Oct: "Maja ma
    lekkoatletyka")."""
    words = (title or "").split(" ")
    if not words[0].endswith("a") or _PLURAL_A.search(words[0].lower()) or len(words[0]) < 3:
        return title
    out = [words[0][:-1] + "ę"]
    for w in words[1:]:
        if not re.fullmatch(r"\w+(?:na|ka|wa|ta|ła|ra|ża|sza|cza)", w):
            out.append(w)
            out.extend(words[len(out):])
            break
        out.append(w[:-1] + "ą")
    return " ".join(out)


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
        n = faces.match_name(w, known=faces.family()) or faces.match_role(w)
        if n and faces.is_family(n):           # a guest has no plan
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
    """The one talking, if they are family (a guest's "mój plan" is no one's)."""
    import faces
    with state.lock:
        who = state.person[0] if state.person and time.time() - state.person[2] < 30 else None
    return who if who and faces.is_family(who) else None


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
    title = title_after_ma(e["title"]) if e["who"] else e["title"]
    return f"Dobrze, zapisałam: {whose}{title} {when_said(e)}.{note}"


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
    _last.update(id=e["id"], t=time.time())
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
# "zaktualizuj plan lekcji Mai", "mam nowy plan lekcji" — a new one, from paper
_LESSONS_PAPER = re.compile(
    r"(?:\b(?:zaktualizuj\w*|aktualizuj\w*|uaktualnij\w*|odczytaj\w*|zeskanuj\w*|"
    r"wczytaj\w*|zczytaj\w*)\s+(?:\w+\s+){0,2}|"
    r"\bprzeczytaj\w*\s+(?:jeszcze\s+raz|ponownie|od\s+nowa)\s+(?:\w+\s+)?|"
    r"^(?:luna,?\s+)?(?:\w+\s+)?(?:mam|mamy|ma|oto|tu\s+jest|to\s+jest)\s+(?:mój\s+|moj\s+)?"
    r"now\w+\s+)plan\w*\s+lekcji\b")
# "…od nowa": the old lessons all go once the paper is read (not only its days)
_FRESH = re.compile(r"\bod\s+(?:nowa|zera|początku|poczatku)\b|\bzastąp\w*|\bzastap\w*")
# "skasuj …" or "możesz skasować …?" (26 Oct: the polite one went to the model)
_CLEAR_VERB = (r"^(?:luna,?\s+)?(?:(?:wyczyść|wyczysc|usuń|usun|skasuj|wykasuj|wymaż|wymaz|"
               r"wyrzuć|wyrzuc)|(?P<polite>(?:czy\s+)?(?:możesz|mozesz|mógłbyś|moglbys|"
               r"mogłabyś|moglabys|proszę|prosze)\s+(?:mi\s+)?(?:wyczyścić|wyczyscic|usunąć|"
               r"usunac|skasować|skasowac|wykasować|wykasowac|wymazać|wymazac)))")
_LESSONS_CLEAR = re.compile(
    _CLEAR_VERB +
    r"\s+(?:(?:cały|caly|całą|cala|wszystkie|mój|moj|moje)\s+)*(?:plan\w*\s+lekcji|lekcje)"
    r"(?:\s+(?:dla\s+)?(\w+))?\W*$")
# "skasuj cały plan Mai" — a bare "plan" only with a name (26 Oct: a timer cancel
# 'plan Mai' and "Tak, skasowałam")
_WEEK_CLEAR = re.compile(
    _CLEAR_VERB +
    r"\s+(?:(?:cały|caly|całą|cala|mój|moj)\s+)*(?:(?:plan\s+(?:tygodnia|tygodniowy|zajęć|zajec)|"
    r"tygodniowy\s+plan|harmonogram\w*|grafik\w*)(?:\s+(?:dla\s+)?(\w+))?|"
    r"plan\s+(?!dnia\b|na\b|lekcji\b)(\w+))\W*$")
_SURE = re.compile(r"^(?:tak|no\s+tak|potwierdzam|na\s+pewno|pewnie|jasne|wyczyść|wyczysc|"
                   r"usuń|usun|skasuj|dawaj|możesz|mozesz|proszę|prosze)\b")


def paper_request(text):
    """"Weź ten plan i dodaj do grafiku Mai", "przepisz plan z kartki",
    "mam na kartce plan Mai, ogarniesz go do jej grafiku?" — True."""
    low = text.lower()
    if _LESSONS_PAPER.search(low) and "?" not in low and len(low.split()) <= 14:
        return True
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
    school = any(r.get("kind") == "lesson" for r in rows or [])
    for r in rows or []:
        title = " ".join(str(r.get("title") or "").split()).strip(" .,;:-–")
        days = sorted({int(d) for d in r.get("days") or [] if isinstance(d, int) and 0 <= d <= 6})
        if not title or not days:
            continue
        no = r.get("lesson_no") if isinstance(r.get("lesson_no"), int) else 0
        kind = "lesson" if r.get("kind") == "lesson" else "activity"
        if kind == "activity" and school and no > 0:
            kind = "lesson"         # in a numbered row of the grid (26 Oct: kółko przyrodnicze)
        if kind == "lesson":
            title = canonical_subject(title)
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
    """The read entries into the plan: (added, already there, replaced). An
    entry with the same owner, title and time gets the new days instead of a
    twin. A timetable is the whole school week: on the days it covers, the
    person's old lessons give way (replaced: how many lesson-days went)."""
    added, kept, replaced = [], [], 0
    covered = {d for e in entries if e["kind"] == "lesson" for d in e["days"]}
    old = [x for x in events() if x.get("who", "") == who and x.get("kind") == "lesson"]
    for e in entries:
        same = next((x for x in events() if x.get("who", "") == who
                     and x["title"].lower() == e["title"].lower() and x["at"] == e["at"]), None)
        if same:
            days = set(same["days"]) | set(e["days"])
            if same.get("kind") == "lesson" and e["kind"] == "lesson":
                gone = set(same["days"]) & covered - set(e["days"])
                replaced += len(gone)
                days -= gone
            if days != set(same["days"]):
                update(same["id"], days=sorted(days))
                same["changed"] = True
            kept.append(same)
            continue
        added.append(add(who, e["title"], e["days"], e["at"], e["end"], by=by,
                         remind=dict(_NO_REMIND) if e["kind"] == "lesson" else None,
                         kind="lesson" if e["kind"] == "lesson" else None))
    matched = {x["id"] for x in kept}
    for x in old:
        gone = set(x["days"]) & covered
        if x["id"] in matched or not gone:
            continue
        replaced += len(gone)
        left = sorted(set(x["days"]) - covered)
        if left:
            update(x["id"], days=left)
        else:
            remove(x["id"])
    if replaced:
        print(f"[schedule] {who or 'dom'}: {replaced} old lesson-days replaced", flush=True)
    return added, kept, replaced


def _pl(n, one, few, many):
    if n == 1:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def paper_said(who, added, kept, unclear, bells, replaced=0):
    """What she says after reading the paper (and the question for the first
    entry with no time, if any)."""
    changed = replaced or any(x.get("changed") for x in kept)
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
    elif changed:
        out = "Przepisałam z kartki nowy plan lekcji" + (f" {genitive(who)}" if who else "") + "."
    elif kept:
        out = "To wszystko już jest w planie tygodnia."
    else:
        out = ""
    if kept and parts:
        out += f" {len(kept)} {_pl(len(kept), 'pozycję', 'pozycje', 'pozycji')} już było."
    if replaced:
        out += " Stary plan lekcji na te dni zastąpiłam nowym."
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


def _sharpness(img):
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _frames(n=3, gap=0.6):
    """The paper as JPEGs (base64): the two sharpest of a few full-size stills
    (camera_thread.grab_stills); the usual frames when there are none."""
    import brain
    try:
        import base64
        import cv2
        import camera_thread
        stills = camera_thread.grab_stills(4)
        if stills:
            best = sorted(stills, key=_sharpness, reverse=True)[:2]
            print("[schedule] stills' sharpness: " + ", ".join(
                f"{_sharpness(s):.0f}" for s in stills), flush=True)
            out = []
            for img in best:
                ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                if ok:
                    out.append(base64.b64encode(buf.tobytes()).decode("ascii"))
            if out:
                return out
    except Exception as e:
        print(f"[schedule] no stills ({e!r}) — the usual frames", flush=True)
    imgs = []
    for i in range(n):
        if i:
            time.sleep(gap)
        img = brain._camera_jpeg_b64()
        if img:
            imgs.append(img)
    return imgs


def import_paper(who, speak, fresh=False):
    """Read the plan held to the camera and save it as `who`'s entries; the
    reading (15–30 s) runs on its own thread with "Czytam plan…" on screen.
    fresh: a timetable on it replaces ALL their old lessons (cleared only
    once the paper was read)."""
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
        cleared = (clear_lessons(who) if fresh and who
                   and any(e["kind"] == "lesson" for e in entries) else 0)
        added, kept, replaced = save_paper(who, entries, by=by)
        replaced += cleared
        text, ask = paper_said(who, added, kept, unclear, bells, replaced)
        print(f"[schedule] from paper: {len(added)} added, {len(kept)} already there, "
              f"{len(unclear)} with no time{', usual bells' if bells else ''}", flush=True)
        if who and any(e["kind"] == "lesson" for e in entries):
            show_lessons(who)
        else:
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


def _import(who, speak, fresh):
    return import_paper(who, speak, fresh=True) if fresh else import_paper(who, speak)


def _ask_clear(name, text, speak):
    """"Wyczyść plan lekcji Mai" → asked back first, the page on show."""
    import faces
    who = None
    if name and name not in _FILLER:
        who = (faces.match_name(name) or faces.match_role(name)
               or next((n for n in lesson_people() if name in faces.forms(n)), None))
        if who is None:
            return False                     # "usuń lekcje angielskiego"
    if who is None and _MINE.search(text.lower()):
        who = _speaker()
    if who is None:
        d = _page()
        who = d.get("who") if d and d.get("view") == "lessons" else None
    if who is None:
        speak("Czyj plan lekcji wyczyścić? Powiedz na przykład: wyczyść plan lekcji Mai.")
        return True
    show_lessons(who)
    if not lessons(who):
        speak(f"Plan lekcji {genitive(who)} jest pusty.")
        return True
    _ask_sure("lessons", who)
    speak(f"Na pewno wyczyścić cały plan lekcji {genitive(who)}? Powiedz: tak — albo nie.")
    return True


def _ask_sure(what, who):
    _clearing.update(what=what, who=who, until=time.time() + EXPECT_SECS)
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = time.time()


def _whose_week(who):
    return f"plan tygodnia {genitive(who)}" if who else "cały plan tygodnia całej rodziny"


def _ask_clear_week(name, text, speak):
    """"Wyczyść plan tygodnia (Mai)" → asked back first: a person's, or everyone's
    (the page's person when it's open)."""
    import faces
    who = None
    if name and name not in _FILLER:
        who = (faces.match_name(name) or faces.match_role(name)
               or next((n for n in people() if name in faces.forms(n)), None))
        if who is None:
            return False
    elif _MINE.search(text.lower()):
        who = _speaker()
    else:
        d = _page()
        who = d.get("who") if d else None
    show(who)
    if not week_entries(who):
        speak(f"{_whose_week(who)[0].upper()}{_whose_week(who)[1:]} jest pusty.")
        return True
    _ask_sure("week", who)
    speak(f"Na pewno wyczyścić {_whose_week(who)} — wszystko, razem z planem lekcji? "
          "Powiedz: tak — albo nie.")
    return True


# "przenieś kółko przyrodnicze do planu lekcji Mai", "ale to ma być w planie lekcji",
# "dodaj do planu lekcji Mai kółko w poniedziałek o 12:45" (26 Oct: the hour she asked
# after a paper went in as a reminder; she said "już poprawiam" and nothing moved)
_INTO_LESSONS = (r"(?:do|w|na)\s+(?:(?:jej|jego|moim|mój|moj|mojego|swoim|swój|swoj|swojego)\s+)?"
                 r"plan(?:u|ie)?\s+lekcji")
_TO_LESSONS = re.compile(
    r"^(?:luna\W+)?(?:ale\s+|nie\W+|no\s+)?(?:"
    r"(?:przenieś|przenies|przesuń|przesun|wpisz|dopisz|dodaj|daj|wrzuć|wrzuc|zapisz)\s+"
    rf"(?P<a>.*?)\s*{_INTO_LESSONS}\b(?P<a2>.*)|"
    r"(?P<b>.*?)\s*(?:ma|mają|maja|miało|mialo|miała|miał|powinn\w*|musi|muszą)\s+"
    rf"(?:być|byc)\s+(?:{_INTO_LESSONS}|lekcj\w*)\b(?P<b2>.*))$")
_NOT_TITLE = {"to", "ten", "tę", "te", "ta", "tą", "je", "go", "ją", "tego", "tej", "jej",
              "jego", "mi", "nam", "też", "tez", "również", "przecież", "tylko", "jako", "nie",
              "lekcja", "lekcję", "lekcji", "osobne", "osobno", "zamiast", "planie", "tygodnia"}
# "…wpisałaś jako przypomnienie, popraw to": the complaint's own words
_NOT_TITLE_RX = re.compile(r"^(?:wpisa|zapisa|dopisa|dodał|dodal|przeni|przenio|popraw|"
                           r"przypomn|zrobi|daj)\w*$")


def _to_lessons(text, speak):
    """An entry of the week's plan moved into the plan lekcji (a lesson, no
    reminder); a new lesson when there's none to move. True when handled."""
    low = " ".join(text.lower().split())
    m = _TO_LESSONS.match(low)
    if not m or "?" in low:
        return False
    body = " ".join(g for g in m.group("a", "a2", "b", "b2") if g)
    if re.search(r"\b(?:kartk\w*|kartce|papier\w*|rozpisk\w*)\b|"
                 r"\b(?:ten|tego|tym|cały|caly)\s+plan", body):
        return False                         # the whole plan on paper: import_paper
    who, rest = _who_of(body)
    days, rest = _days_of(rest)
    at, end, rest = _time_of(rest)
    words = [w for w in re.findall(r"[\w'-]+", rest)
             if w not in _FILLER and w not in _NOT_TITLE and not _NOT_TITLE_RX.match(w)]
    title = " ".join(words)
    draft = _expect.get("draft") if expecting() else None

    def same(t):
        tw = {w[:5] for w in re.findall(r"\w{3,}", (t or "").lower())}
        ww = {w[:5] for w in re.findall(r"\w{3,}", title)}
        return bool(ww and tw and len(ww & tw) >= (len(tw) + 1) // 2)
    hits = []
    if title:
        # (with a day or an hour, a lesson already there is not it: a new one)
        hits = [e for e in events() if (who is None or e.get("who") == who) and same(e["title"])
                and not (e.get("kind") == "lesson" and (days or at))]
    elif not draft and time.time() - _last["t"] < LAST_SECS and get(_last["id"]):
        hits = [get(_last["id"])]
    if not hits and draft and (not title or same(draft.get("title"))):
        p = dict(draft, kind="lesson", remind=dict(_NO_REMIND))     # she was asking its hour
    elif not hits:
        if not title or len(words) > 4:
            speak("Co przenieść do planu lekcji? Powiedz na przykład: przenieś kółko "
                  "przyrodnicze do planu lekcji Mai.")
            return True
        d = _page()
        page_who = d.get("who") if d and d.get("view") == "lessons" else None
        p = {"who": who if who is not None else _lesson_who(page_who),
             "title": canonical_subject(title),
             "days": None, "at": None, "end": "", "remind": dict(_NO_REMIND), "kind": "lesson"}
    else:
        if who is None and len({e.get("who") or "" for e in hits}) > 1:
            speak("Pasuje kilka: " + "; ".join(f"{e['title']} {e['who']}".strip()
                                               for e in hits[:4]) + ". Powiedz też, czyje.")
            return True
        moved, there = [], []
        for e in hits:
            if e.get("kind") == "lesson" and not (days or at):
                there.append(e)
                continue
            ch = {"kind": "lesson", "remind": dict(_NO_REMIND)}
            if len(hits) == 1 and days:
                ch["days"] = days
            if len(hits) == 1 and at:
                ch.update(at=at, end=end or _plus(at, LESSON_MINS))
            elif not e.get("end"):
                ch["end"] = _plus(e["at"], LESSON_MINS)
            moved.append(update(e["id"], **ch))
        owner = hits[0].get("who") or ""
        show_lessons(owner or None)
        whose = f" {genitive(owner)}" if owner else ""
        if moved:
            print(f"[schedule] into the lessons of {owner or 'dom'}: "
                  + ", ".join(e["title"] for e in moved), flush=True)
            speak(f"Przeniosłam do planu lekcji{whose}: "
                  + "; ".join(f"{e['title']} {when_said(e)}" for e in moved)
                  + ". Bez przypomnienia, jak inne lekcje.")
        else:
            speak(f"{there[0]['title'][0].upper()}{there[0]['title'][1:]} już jest w planie "
                  f"lekcji{whose}: {when_said(there[0])}.")
        return True
    for k, v in (("days", days), ("at", at), ("end", end)):
        if v:
            p[k] = v
    if p.get("at") and not p.get("end"):
        p["end"] = _plus(p["at"], LESSON_MINS)
    _take(p, speak)
    if not expecting():
        show_lessons(p.get("who") or None)
    return True


def handle(text, speak):
    """Local commands for the week's plan. True when handled."""
    low = text.lower().strip()
    if _clearing["what"]:
        what, who = _clearing["what"], _clearing["who"]
        live = time.time() < _clearing["until"]
        _clearing.update(what=None, who=None, until=0.0)
        name = f"plan lekcji {genitive(who)}" if what == "lessons" else _whose_week(who)
        if live and _SURE.match(low) and not re.search(r"\bnie\b", low):
            if what == "lessons":
                n = clear_lessons(who, keep=True)
                show_lessons(who)
            else:
                n = clear_week(who, keep=True)
                show(who)
            speak(f"Wyczyściłam {name}. Gdyby co, powiedz: przywróć plan." if n else f"{name[0].upper()}{name[1:]} był już pusty.")
            return True
        if live and (_STOP.match(low) or re.match(r"^nie\b", low)):
            speak(f"Dobrze, {name} zostaje.")
            return True
        # something else: the question lapses
    if expecting() and _expect.get("paper"):
        _expect.update(until=0.0, paper=False)
        who, known = _paper_who(text)
        if known:
            return _import(who, speak, _expect.get("fresh"))
        if _STOP.match(low):
            speak("Dobrze, nie przepisuję.")
            return True
        if re.match(r"^(?:co|słucham|że co|powtórz|powtorz|jak)\W*$", low):
            _expect.update(until=time.time() + EXPECT_SECS, paper=True)
            speak("Czyj to plan? Powiedz na przykład: Mai.")
            return True
        # something else: not the answer
    if _to_lessons(text, speak):
        return True
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
    m = _LESSONS_CLEAR.match(low)
    if m and ("?" not in low or m.group("polite")):
        return _ask_clear(m.group(2), text, speak)
    m = _WEEK_CLEAR.match(low)
    if m and ("?" not in low or m.group("polite")) and m.group(3) not in _FILLER:
        return _ask_clear_week(m.group(2) or m.group(3), text, speak)
    if paper_request(text):
        who, known = _paper_who(text)
        fresh = bool(_FRESH.search(low))
        if known:
            return _import(who, speak, fresh)
        _expect.update(until=time.time() + EXPECT_SECS, draft=None, paper=True, fresh=fresh)
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        speak("Czyj to plan? Powiedz na przykład: Mai.")
        return True
    m = _LESSONS_SHOW.match(low)
    if m:
        import faces
        name = next((g for g in m.groups() if g), "")
        who = (faces.match_name(name) or faces.match_role(name)
               or next((n for n in lesson_people() if name in faces.forms(n)), None)
               ) if name else None
        if name and not who and name not in _FILLER:
            return False                     # "pokaż lekcje angielskiego"
        who = show_lessons(who)
        speak(lessons_said(who))
        if lesson_people():
            close_after()                # (the plan read out: nothing follows)
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
        if events():
            close_after()
        return True
    if _ENDS.search(low):
        said = ends_said(text)
        if said:
            speak(said)
            close_after()
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
    said = restore(text)
    if said:
        speak(said)
        return True
    m = _REMOVE.match(low)
    if m:
        hits = _match(m.group(1) or f"{m.group(2)} {m.group(3) or ''}")
        if not hits:
            speak("Nie widzę tego w planie tygodnia.")
        elif len(hits) > 1:
            speak("Pasuje kilka: " + "; ".join(f"{e['title']} {e['who']}".strip() for e in hits[:4])
                  + ". Powiedz też, czyje.")
        else:
            remove(hits[0]["id"], keep=True)
            _refresh()
            speak(f"Usunęłam z planu: {hits[0]['title']}"
                  + (f" ({hits[0]['who']})" if hits[0]["who"] else "") + ".")
        return True
    return False


_ENDS = re.compile(
    r"^(?:luna,?\s+)?(?:a\s+)?"
    r"(?=.*\b(?:lekcj|zaję|zajec|szkoł|szkol))(?!.*\b(?:rok|semestr|ferie|wakacj))"
    r"(?:(?:o\s+któr|o\s+ktor|kiedy\b)(?=.*\bs?ko[nń]cz)|"
    r"(?:do\s+któr|do\s+ktor)(?=.*\b(?:ma|mam|masz|są|trwaj\w*|s?ko[nń]cz\w*)\b))")


def ends_said(text, now=None):
    """'O której Maja kończy zajęcia?' from the plan — 30 Oct: the model,
    shown the whole week, answered a Friday with Wednesday's lessons."""
    low = text.lower()
    who = _who_of(text)[0]
    if not who and re.search(r"\b(?:kończę|konczę|mam)\b", low):
        who = _speaker()
    if not who:
        mine = {e.get("who") for e in events() if e.get("who")}
        who = next(iter(mine)) if len(mine) == 1 else None
    if not who:
        return None
    lt = time.localtime(now or time.time())
    tomorrow = bool(re.search(r"\bjutr", low))
    wd = (lt.tm_wday + tomorrow) % 7
    mins = -1 if tomorrow else lt.tm_hour * 60 + lt.tm_min
    when = "jutro" if tomorrow else "dziś"
    rows = [e for e in week_rows(wd, who) if e.get("who") == who]
    school = next((e for e in rows if e.get("kind") == "school"), None)
    rest = [e for e in rows if e is not school and _mins(e.get("end") or e["at"]) > mins]
    if school:
        verb = "skończyła" if mins >= _mins(school["end"]) else "kończy"
        out = f"{who} {verb} {when} lekcje o {school['end']}."
    elif rows:
        out = f"{who} nie ma {when} lekcji."
    else:
        return f"{when.capitalize()} {who} nie ma w planie ani lekcji, ani zajęć."
    if rest:
        items = [f"{title_after_ma(e['title'])} o {e['at']}" for e in rest]
        last = rest[-1].get("end")
        out += (" Potem ma jeszcze " if school else " Ma ") + (
            " i ".join([", ".join(items[:-1]), items[-1]]) if len(items) > 1 else items[0]) + (
            f", do {last}." if last else ".")
    elif school and re.search(r"zaję|zajec", low):
        out += f" Po szkole nic już {when} nie ma."
    return out


_ASKED = re.compile(r"^(?:luna,?\s+)?(?:a\s+)?(?:co|jakie|jaki|jaka|jaką|o\s+któr|o\s+ktor|"
                    r"do\s+któr|do\s+ktor|kiedy|czy|ile)\b")
_PLAN_Q = re.compile(r"\b(?:lekcj|zaję|zajec|szkoł|szkol|w\s+planie|plan\s+(?:tygodnia|lekcji|"
                     r"dnia|zajęć))")
_EDIT = re.compile(r"\b(?:dodaj|dopisz|wpisz|usuń|usun|skreśl|zmień|zmien|przenieś|przenies|"
                   r"przesuń|przesun|wyczyść|wyczysc|wczytaj|przepisz)")


def asked(text):
    """A short question about the plan answered by the model ("jakie Maja ma
    dziś zajęcia po lekcjach?", "czy Maja ma jutro basen?"): nothing follows,
    the window closes (brain, like weather_told)."""
    low = text.lower().strip()
    if len(low.split()) > 14 or _EDIT.search(low):
        return False
    if not (_ASKED.search(low) or low.endswith("?")):
        return False
    if _PLAN_Q.search(low):
        return True
    titles = {w for e in events() for w in re.findall(r"\w{4,}", e["title"].lower())}
    return any(w in titles for w in re.findall(r"\w+", low))


def week_entries(who=None):
    """Whose the week page's "Wyczyść" would take: a person's own, or all."""
    return [e for e in events() if who is None or (e.get("who") or "") == who]


def clear_week(who=None, keep=False):
    """The week's plan wiped: `who`'s entries (lessons too), or everyone's."""
    with _lock:
        d = _load()
        gone = [e for e in d["events"] if who is None or (e.get("who") or "") == who]
        d["events"] = [e for e in d["events"] if e not in gone]
        for e in gone:
            d["done"].pop(e["id"], None)
        if gone:
            _save(d)
    if gone and keep:
        _keep(gone, _whose_week(who))
    print(f"[schedule] cleared the week of {who or 'everyone'}: {len(gone)} entries", flush=True)
    return len(gone)


def week_rows(wd, who=None):
    """A day on the week page: the entries, but a person's lessons as one
    "szkoła" row from the first to the last (its id "school:<who>")."""
    out, school = [], {}
    for e in on_day(wd, who):
        if e.get("kind") != "lesson":
            out.append(e)
            continue
        w = e.get("who") or ""
        end = e.get("end") or _plus(e["at"], LESSON_MINS)
        s = school.get(w)
        if s is None:
            school[w] = {"id": f"school:{w}", "kind": "school", "who": w, "title": "szkoła",
                         "at": e["at"], "end": end, "days": [wd], "n": 1, "remind": None}
        else:
            s["n"] += 1
            s["end"] = max(s["end"], end, key=_mins)
    out += school.values()
    return sorted(out, key=lambda e: _mins(e["at"]))


def today_said(who=None, now=None):
    lt = time.localtime(now or time.time())
    today = week_rows(lt.tm_wday, who)
    if not events():
        return ("Plan tygodnia jest jeszcze pusty. Dotknij plusa albo powiedz: dodaj do planu, "
                "Maja, angielski, od poniedziałku do piątku o siedemnastej.")
    if not today:
        return "Oto plan tygodnia. Na dziś nic w nim nie ma."
    parts = [f"{e['title']}" + (f" — {e['who']}" if e["who"] and not who else "")
             + (f" od {e['at']} do {e['end']}" if e.get("kind") == "school" else f" o {e['at']}")
             for e in today[:3]]
    return "Oto plan tygodnia. Dziś: " + "; ".join(parts) + "."


# ── the page ──────────────────────────────────────────────────────────────────

def show(who=None, day=None):
    import faces
    if who and who not in faces.family():
        who = None
    data = {"day": time.localtime().tm_wday if day is None else day, "who": who,
            "sel": None, "page": 0, "confirm": 0.0, "toast": None}
    with state.lock:
        state.overlay = ("schedule", time.time() + PAGE_SECS, data)


# ── plan lekcji: one person's school week, Pn–Pt, a grid ──────────────────────
# The same entries (kind "lesson", each person's own); "pokaż plan lekcji Mai",
# a new paper replaces the old lessons on its days (save_paper).

def genitive(name):
    """Maja → Mai, Emilka → Emilki, Andrzej → Andrzeja (for "plan lekcji …")."""
    if not name:
        return ""
    low = name.lower()
    if low.endswith("ja"):
        return name[:-2] + "i"
    if low.endswith("a"):
        return name[:-1] + ("i" if low[-2:-1] in ("k", "g", "l", "i") else "y")
    return name + "a"


def lessons(who):
    return [e for e in events() if e.get("kind") == "lesson" and (e.get("who") or "") == (who or "")]


def clear_lessons(who, keep=False):
    """All of `who`'s lessons gone (the rest of their plan stays): how many
    lesson-days went."""
    with _lock:
        d = _load()
        gone = [e for e in d["events"] if e.get("kind") == "lesson"
                and (e.get("who") or "") == (who or "")]
        d["events"] = [e for e in d["events"] if e not in gone]
        for e in gone:
            d["done"].pop(e["id"], None)
        if gone:
            _save(d)
    if gone and keep:
        _keep(gone, f"plan lekcji {genitive(who)}")
    n = sum(len(e["days"]) for e in gone)
    print(f"[schedule] cleared {who or 'dom'}'s lessons: {len(gone)} entries", flush=True)
    return n


MIN_ROWS = 8                   # the plan lekcji page: room for 8 lessons a day


def lesson_slots(who, at_least=MIN_ROWS):
    """(rows, cells, spare): lesson_grid's rows topped up to `at_least` with
    empty ones after the last (the usual bells, or 10 min after the one
    before), so a lesson can be added there by a tap; spare = how many."""
    rows, cells = lesson_grid(who)
    rows = list(rows)
    spare = 0
    while rows and len(rows) < at_least:
        prev = _mins(rows[-1][1] or _plus(rows[-1][0], LESSON_MINS))
        k = len(rows)
        at = BELLS[k] if k < len(BELLS) and _mins(BELLS[k]) >= prev + 5 else _plus(
            f"{prev // 60:02d}:{prev % 60:02d}", 10)
        rows.append((at, _plus(at, LESSON_MINS)))
        spare += 1
    return rows, cells, spare


def lesson_grid(who):
    """(rows, cells): rows = [(at, end)] the lesson hours Mon–Fri in order;
    cells[(row, weekday)] = that lesson's entries (two if the paper clashes)."""
    ls = [e for e in lessons(who) if any(d < 5 for d in e["days"])]
    ends = {}
    for e in ls:
        ends[e["at"]] = max(ends.get(e["at"], ""), e.get("end") or "")
    rows = sorted(ends.items(), key=lambda t: _mins(t[0]))
    row_of = {at: i for i, (at, _) in enumerate(rows)}
    cells = {}
    for e in ls:
        for d in e["days"]:
            if d < 5:
                cells.setdefault((row_of[e["at"]], d), []).append(e)
    return rows, cells


# each subject its own colour: the usual ones fixed (W-f always green), any
# other one a colour no subject in that plan has
SUBJECT_COLS = ((214, 64, 76), (58, 112, 220), (236, 132, 36), (46, 168, 84), (140, 86, 214),
                (226, 86, 176), (196, 164, 30), (26, 156, 140), (30, 170, 214), (156, 104, 58),
                (104, 116, 142), (92, 86, 200), (128, 150, 40), (170, 60, 90), (210, 110, 100),
                (60, 130, 90), (180, 120, 200), (90, 160, 200), (200, 140, 90), (120, 180, 120))
_SUBJECTS = ((r"\bw[\s.\-]*f\b|wychowani\w*\s+fizyczn", "w-f", 3),
             (r"wczesnoszk|zintegrowan", "edukacja wczesnoszkolna", 11),
             (r"świetlic|swietlic", "świetlica", 10),
             (r"wychowawc|godz\w*\.?\s+wych", "wychowawcza", 12),
             (r"polsk", "polski", 0), (r"matem|^mat\b", "matematyka", 1),
             (r"angiel", "angielski", 2), (r"niemieck", "niemiecki", 14),
             (r"relig", "religia", 4), (r"plasty", "plastyka", 5), (r"muzy", "muzyka", 6),
             (r"przyrod", "przyroda", 7), (r"informaty|komputer", "informatyka", 8),
             (r"techni", "technika", 9), (r"histor", "historia", 13),
             (r"geograf", "geografia", 15))


def subject_key(title):
    """"WF", "w-f", "wychowanie fizyczne" → "w-f"; "j. polski" → "polski"."""
    low = " ".join((title or "").lower().split())
    for rx, key, _ in _SUBJECTS:
        if re.search(rx, low):
            return key
    return re.sub(r"[^\w]+", " ", low).strip()


def canonical_subject(title):
    """A lesson's name one way: "w-f" / "W.F." → "WF", "j. polski" → "polski" (the
    same subject read differently on two days stays one entry)."""
    if re.search(r"\b(?:kół\w*|kol\w*|koło|koła|kole|klub\w*|warsztat\w*|wyrówn\w*)\b",
                 (title or "").lower()):
        return title                         # "kółko przyrodnicze" is not przyroda
    key = subject_key(title)
    if key == "w-f":
        return "WF"
    if any(key == k for _, k, _ in _SUBJECTS) and key != "wychowawcza":
        return key
    return title


def subject_colours(titles):
    """{title: (r, g, b)} — the same subject the same colour, different ones
    different (while there are colours)."""
    fixed = {key: i for _, key, i in _SUBJECTS}
    keys = {t: subject_key(t) for t in titles}
    taken = {fixed[k] for k in keys.values() if k in fixed}
    free = [i for i in range(len(SUBJECT_COLS)) if i not in taken]
    free = [i for i in free if i >= len(fixed)] + [i for i in free if i < len(fixed)]
    own = {}
    for k in sorted({k for k in keys.values() if k not in fixed}):
        own[k] = free[len(own) % len(free)] if free else len(own) % len(SUBJECT_COLS)
    return {t: SUBJECT_COLS[fixed[k] if k in fixed else own[k]] for t, k in keys.items()}


def lesson_people():
    """Those with lessons (an adult without a timetable is no chip)."""
    have = []
    for e in events():
        if e.get("kind") == "lesson" and e.get("who") and e["who"] not in have:
            have.append(e["who"])
    return have


def page_people(d):
    """The page's chips: those with lessons, then the ones "+ Dodaj"-ed there."""
    have = lesson_people()
    return have + [n for n in d.get("added") or () if n not in have]


def lesson_candidates(d):
    """Whom "+ Dodaj" offers: the family and anyone in the plan, not yet a chip."""
    shown = page_people(d)
    return [n for n in people() if n not in shown]


def _lesson_who(who=None):
    """Named, else the speaker if they have lessons, else the first with lessons."""
    if who:
        return who
    ps = lesson_people()
    me = _speaker()
    if me and me in ps:
        return me
    return ps[0] if ps else None


def _open_lessons(d, who=None):
    """The week page → the plan lekcji page (a named person without lessons a chip)."""
    who = _lesson_who(who)
    d.update(view="lessons", who=who, confirm=0.0, pick=False, ask=False,
             added=[who] if who and who not in lesson_people() else [])


def show_lessons(who=None):
    """The "plan lekcji" page; returns whose it shows."""
    who = _lesson_who(who)
    data = {"view": "lessons", "who": who, "day": time.localtime().tm_wday, "sel": None,
            "page": 0, "confirm": 0.0, "toast": None, "pick": False, "ask": False,
            "added": [who] if who and who not in lesson_people() else []}
    with state.lock:
        state.overlay = ("schedule", time.time() + PAGE_SECS, data)
    return who


def _school_day(who, now=None):
    """(weekday, "Dziś" / "Jutro" / "W poniedziałek") — today until its last
    lesson ends, else the next day with lessons; None with no lessons."""
    rows, cells = lesson_grid(who)
    if not rows:
        return None
    lt = time.localtime(now or time.time())
    mins = lt.tm_hour * 60 + lt.tm_min
    for k in range(8):
        wd = (lt.tm_wday + k) % 7
        here = [r for r in range(len(rows)) if (r, wd) in cells]
        if not here:
            continue
        last = rows[here[-1]]
        if k == 0 and mins >= _mins(last[1] or _plus(last[0], LESSON_MINS)):
            continue
        return wd, ("Dziś" if k == 0 else "Jutro" if k == 1 else _DAYS_IN[wd].capitalize())
    return None


def lessons_said(who, now=None):
    whose = f" {genitive(who)}" if who else ""
    nxt = _school_day(who, now)
    if nxt is None:
        return (f"Nie mam jeszcze planu lekcji{whose}. Potrzymaj kartkę z planem przed kamerą "
                f"i powiedz: wczytaj plan lekcji{whose}.")
    wd, when = nxt
    rows, cells = lesson_grid(who)
    day = [(rows[r], cells[(r, wd)]) for r in range(len(rows)) if (r, wd) in cells]
    titles = ", ".join(" / ".join(e["title"] for e in es) for _, es in day)
    (at, _), ((lat, lend), _) = day[0][0], day[-1]
    return (f"Plan lekcji{whose}. {when}: {titles} — od {at.lstrip('0') or '0'} "
            f"do {(lend or _plus(lat, LESSON_MINS)).lstrip('0')}.")


def _tap_lessons(d, x, y, W, H, speak):
    import ui_lessons
    hit = ui_lessons.hit(x, y, W, H, d)
    if not hit:
        return True
    kind = hit[0]
    if kind == "who":
        d["who"] = hit[1]
    elif kind == "add" or (kind == "paper" and not d.get("who")):
        d["pick"] = True                     # whose plan: the family not on a chip yet
    elif kind == "pick":
        d.setdefault("added", []).append(hit[1])
        d["who"], d["pick"] = hit[1], False
    elif kind == "no":                       # "Anuluj", or a tap beside the dialog
        d["pick"] = d["ask"] = False
    elif kind == "clear":
        d["ask"] = True
    elif kind == "yes":                      # "Tak, wyczyść" — they stay a chip for a new paper
        who = d["who"]
        clear_lessons(who, keep=True)
        if who not in d.setdefault("added", []):
            d["added"].append(who)
        d["ask"] = False
        d["toast"] = (f"Wyczyszczone: plan lekcji {genitive(who)}", time.time() + 3.0)
    elif kind == "week":
        d["view"] = None
    elif kind == "paper":                    # the plan becomes what's on the paper
        who = d["who"]

        def run():                           # (it waits for the frames: not on the render thread)
            from text_to_speech import speak as say
            import_paper(who, speak or say, fresh=True)
        threading.Thread(target=run, daemon=True, name="lessons-paper").start()
    elif kind == "cell":
        row, wd = hit[1], hit[2]
        rows, cells, _ = lesson_slots(d.get("who"))
        es = cells.get((row, wd))
        if es:
            d.update(view=None, sel=es[0]["id"], confirm=0.0, back="lessons")
        elif row < len(rows) and d.get("who"):
            at, end = rows[row]
            expect(d["who"], wd)
            _expect["draft"] = {"who": d["who"], "title": None, "days": [wd], "at": at,
                                "end": end, "remind": dict(_NO_REMIND), "kind": "lesson"}
            (speak or _say)(f"Jaka lekcja jest {_DAYS_IN[wd]} o {at.lstrip('0')}? "
                            "Powiedz samą nazwę.")
    return True


def _paper_tap(who, speak):
    """"Z kartki" on the week page: read it into `who`'s week; on "Wszyscy",
    asked whose it is first (the answer goes to import_paper)."""
    if who is None:
        _expect.update(until=time.time() + EXPECT_SECS, draft=None, paper=True, fresh=False)
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        (speak or _say)("Czyj to plan? Powiedz na przykład: Mai — albo: cały dom.")
        return

    def run():                               # (it waits for the frames: not on the render thread)
        from text_to_speech import speak as say
        import_paper(who, speak or say)
    threading.Thread(target=run, daemon=True, name="week-paper").start()


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
    """The page's person chips: the family, and anyone in the plan."""
    import faces
    names = list(faces.family())
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
    if d.get("view") == "lessons" and not d.get("sel"):
        return _tap_lessons(d, x, y, W, H, speak)
    hit = ui_schedule.hit(x, y, W, H, d)
    if not hit:
        return True
    kind = hit[0]
    now = time.time()
    if not d.get("sel") and kind != "wipe":
        d["confirm"] = 0.0
    if kind == "day":
        d["day"], d["page"] = hit[1], 0
    elif kind == "who":
        d["who"], d["page"] = hit[1], 0
    elif kind == "row" and hit[1].startswith("school:"):     # "szkoła" → the plan lekcji
        _open_lessons(d, hit[1].split(":", 1)[1] or None)
    elif kind == "row":
        d["sel"], d["confirm"] = hit[1], 0.0
    elif kind == "wipe":                     # "Wyczyść", tapped twice
        if now - d.get("confirm", 0.0) < 4.0:
            n = clear_week(d.get("who"), keep=True)
            d["confirm"], d["page"] = 0.0, 0
            d["toast"] = (f"Wyczyszczone: {n} {_pl(n, 'pozycja', 'pozycje', 'pozycji')}",
                          now + 3.0)
        else:
            d["confirm"] = now
    elif kind == "more":
        d["page"] += 1
    elif kind == "add":
        expect(d.get("who"), d.get("day"))
        (speak or _say)("Powiedz, co dodać — kto, co, w jakie dni i o której. Na przykład: "
                               "Maja, angielski, od poniedziałku do piątku o siedemnastej.")
    elif kind == "lessons":
        _open_lessons(d, d.get("who") if d.get("who") in lesson_people() else None)
    elif kind == "paper":                    # the plan on paper → this person's week
        _paper_tap(d.get("who"), speak)
    elif kind == "back":
        d["sel"], d["confirm"] = None, 0.0
        d["view"] = d.pop("back", None) or d.get("view")
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
                remove(e["id"], keep=True)
                d["sel"], d["confirm"] = None, 0.0
                d["view"] = d.pop("back", None) or d.get("view")
                d["toast"] = (f"Usunięte: {e['title']}", now + 3.0)
            else:
                d["confirm"] = now
    return True


def swipe(dx):
    d = _page()
    if d is None or d.get("sel"):
        return False
    if d.get("view") == "lessons":           # the next person / the one before
        if d.get("pick") or d.get("ask"):
            return True
        ps = page_people(d)
        if ps:
            k = ps.index(d["who"]) if d.get("who") in ps else -1
            d["who"] = ps[(k + (1 if dx < 0 else -1)) % len(ps)]
        return True
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
    acc = title_after_ma(title)                  # "ma lekkoatletykę", not "ma lekkoatletyka"
    if to:
        voc = faces.vocatives().get(to) or to
        if owner == to:
            return (f"{voc}, właśnie trwa {title} — o {e['at']}." if when == "już"
                    else f"{voc}, {when} masz {acc}.")
        if owner:
            return f"{voc}, przypominam: {owner} {when} ma {acc}."
        return f"{voc}, przypominam: {when} {title}."
    if owner:
        return f"Przypominam: {owner} {when} ma {acc}."
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


def _day_line(wd, mins=None):
    """One day's plan for the prompt, lessons as one school span; with `mins`
    (now, minutes) what is already over is marked."""
    parts = []
    for e in week_rows(wd):
        end = e.get("end") or ""
        what = "school (lessons)" if e.get("kind") == "school" else e["title"]
        over = mins is not None and mins >= _mins(end or e["at"])
        parts.append(f"{e.get('who') or 'the whole house'}: {what} {e['at']}"
                     + (f"–{end}" if end else "") + (" (already over)" if over else ""))
    return "; ".join(parts) or "nothing in the plan"


def prompt_line(now=None):
    evs = events()
    if not evs:
        return ""
    lt = time.localtime(now or time.time())
    wd, nxt = lt.tm_wday, (lt.tm_wday + 1) % 7
    near = (f"TODAY is {DAYS[wd]} ({DAYS_SHORT[wd]}). Today's plan: "
            f"{_day_line(wd, lt.tm_hour * 60 + lt.tm_min)}. Tomorrow, {DAYS[nxt]}: "
            f"{_day_line(nxt)}. Answer about \"dziś\"/\"jutro\" from these two lines "
            "only, never from another day of the week.\n")
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
                end = max((e.get("end") or _plus(e["at"], LESSON_MINS) for e in day), key=_mins)
                days.append(f"{DAYS_SHORT[wd]} {day[0]['at']}–{end}: "
                            + ", ".join(f"{e['at']} {e['title']}" for e in day))
        school.append(f"{who or 'the whole house'}'s school lessons: " + "; ".join(days))
    return ("The family's weekly plan (plan tygodnia; the app reminds by itself, "
            "\"pokaż plan tygodnia\" shows it, \"pokaż plan lekcji <kto>\" one person's "
            "lessons Mon–Fri; to add or remove an entry use the command "
            "\"dodaj do planu: <kto>, <co>, <dni>, o <godzina>\" / \"usuń z planu <co> <kto>\"): "
            + "; ".join([f"{e.get('who') or 'the whole house'}: {e['title']} "
                         f"{days_said(e['days'])} {e['at']}"
                         + (f"–{e['end']}" if e.get("end") else "") for e in by] + school)
            + ".\n" + near)


def today_rows(now=None):
    """Today's entries for "plan dnia" (screens.today_rows)."""
    lt = time.localtime(now or time.time())
    return [(e["at"], (f"{e['who']}: {e['title']}" if e.get("who") else e["title"])
             + (f" (do {e['end']})" if e.get("kind") == "school" else ""))
            for e in week_rows(lt.tm_wday)]
