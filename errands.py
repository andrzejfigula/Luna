"""
errands.py — "tell Maja when you see her".

  "Luna, przekaż Mai, żeby posprzątała pokój"
  "Powiedz Emilce, że obiad jest w lodówce"
  "Jak zobaczysz Andrzeja, powiedz mu, że dzwoniła babcia"

The note waits in data/errands.json until she recognises that person
(faces.py); then, when nobody is talking, she says it to them, turned into
words for them by the model ("Maju, tata prosi, żebyś posprzątała pokój.").
Only for people she knows by face. "Jakie mam przekazać wiadomości?" goes to
the model, which sees the waiting ones in its prompt.

With a time it waits for it: "o 18 powiedz Emilce, żeby zadzwoniła do mamy"
is said when she sees Emilka after six; "codziennie o 20:30 przypominaj Mai,
że pora spać" every evening, once, when Maja is around after half past
eight. "Usuń przypomnienia dla Mai" / "nie przypominaj już Mai" clears them.
"""

import json
import os
import re
import threading
import time

from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "errands.json")
KEEP_DAYS = 7

_lock = threading.Lock()
_ASK = re.compile(r"\b(?:przekaż|przekaz|powiedz|powtórz|powtorz|daj znać|daj znac|"
                  r"przypomnij|przypominaj)\s+(\w+)"
                  # up to four words before "że": "od mnie", "o 19", "jutro rano"
                  r"(?:[,:]?\s+(?!że\b|ze\b|żeby\b|zeby\b|aby\b|by\b)[\w:.]+){0,4}?"
                  r"[,:]?\s+(że|ze|żeby|zeby|aby|by)\s+(.+)$",
                  re.I)
_WHEN = re.compile(r"\b(?:jak|kiedy|gdy)\s+(?:zobaczysz|spotkasz|przyjdzie|wróci|wroci)\s+"
                   r"(\w+)\W+(?:to\s+)?(?:powiedz|przekaż|przekaz)\s+(?:mu|jej|im)?[,:]?\s*"
                   r"(że|ze|żeby|zeby|aby|by)\s+(.+)$", re.I)


_DAILY = re.compile(r"\b(?:codziennie|co dzień|co dzien|każdego dnia|kazdego dnia|"
                    r"co wieczór|co wieczor|co rano|każdego wieczoru)\b", re.I)
_AT = re.compile(r"\bo\s+(?:godzinie\s+)?(\d{1,2})(?:[:.](\d{2}))?\b", re.I)
_HOUR_WORDS = {"pierwszej": 1, "drugiej": 2, "trzeciej": 3, "czwartej": 4, "piątej": 5,
               "szóstej": 6, "siódmej": 7, "ósmej": 8, "dziewiątej": 9, "dziesiątej": 10,
               "jedenastej": 11, "dwunastej": 12, "trzynastej": 13, "czternastej": 14,
               "piętnastej": 15, "szesnastej": 16, "siedemnastej": 17, "osiemnastej": 18,
               "dziewiętnastej": 19, "dwudziestej": 20}
_CANCEL = re.compile(r"\b(?:usuń|usun|skasuj|anuluj)\s+(?:wszystkie\s+)?(?:przypomnienia|"
                     r"wiadomości|wiadomosci)\s+dla\s+(\w+)|\bnie\s+przypominaj\s+"
                     r"(?:już\s+|juz\s+)?(\w+)", re.I)


_PART_OF_DAY = ((r"\brano\b|\bz\s+rana\b|\bprzed\s+szkołą\b|\bprzed\s+szkola\b", "06:00"),
                (r"\bpo\s+szkole\b|\bpo\s+południu\b|\bpo\s+poludniu\b", "13:00"),
                (r"\bwieczorem\b|\bwieczór\b|\bwieczor\b", "17:00"))


def days_ahead(text):
    """"jutro" → 1, "pojutrze" → 2, else 0 (and 0 for a daily one)."""
    low = text.lower()
    if _DAILY.search(text) or re.search(r"\b(?:dziś|dzis|dzisiaj)\b", low):
        return 0
    return 2 if re.search(r"\bpojutrze\b", low) else 1 if re.search(r"\bjutr\w*", low) else 0


def _day(text, now=None):
    """The date it may first be said ("YYYY-MM-DD"), or None."""
    n = days_ahead(text)
    return time.strftime("%Y-%m-%d", time.localtime((now or time.time()) + n * 86400)) if n else None


def _when(text):
    """("HH:MM" or None, daily) from "codziennie o 20:30", "o dwudziestej trzydzieści",
    "rano" (6:00), "po szkole" (13:00), "wieczorem" (17:00)."""
    at, daily = _clock(text)
    if not at:
        at = next((hm for rx, hm in _PART_OF_DAY if re.search(rx, text, re.I)), None)
    return at, daily


def _clock(text):
    import calc
    daily = bool(_DAILY.search(text))
    m = _AT.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
    else:
        low = text.lower()
        k = re.search(r"\bo\s+(\w+)(?:\s+(\w+))?(?:\s+(\w+))?", low)
        h = mi = None
        while k:
            w = k.group(1)
            if w in _HOUR_WORDS:
                h = _HOUR_WORDS[w]
                rest = k.group(2) or ""
                if w == "dwudziestej" and rest in ("pierwszej", "drugiej", "trzeciej"):
                    h += _HOUR_WORDS[rest]
                    rest = k.group(3) or ""
                mi = calc.number_in(rest) if rest and calc.number_in(rest) else 0
                break
            k = re.search(r"\bo\s+(\w+)(?:\s+(\w+))?(?:\s+(\w+))?", low[k.end():])
        if h is None:
            return None, daily
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None, daily
    return f"{h:02d}:{mi:02d}", daily


def cancel(text):
    """"usuń przypomnienia dla Mai" → how many were removed, or None."""
    import faces
    m = _CANCEL.search(text)
    if not m:
        return None
    who = faces.match_name(m.group(1) or m.group(2) or "")
    if not who:
        return None
    with _lock:
        items = _load()
        keep = [e for e in items if e["to"] != who]
        _save(keep)
    print(f"[errands] cleared {len(items) - len(keep)} for {who}", flush=True)
    return who, len(items) - len(keep)


def _due(e, now=None):
    """Is this note to be said now (if its person is here)?"""
    now = now or time.time()
    if not e.get("daily") and now - e["t"] > KEEP_DAYS * 86400:
        return False
    lt = time.localtime(now)
    if e.get("day") and time.strftime("%Y-%m-%d", lt) < e["day"]:
        return False                      # "jutro rano": not this morning
    if e.get("at") and time.strftime("%H:%M", lt) < e["at"]:
        return False
    if e.get("daily"):
        return e.get("done") != time.strftime("%Y-%m-%d", lt)
    return True


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def take(text):
    """An errand being given → (to, words) saved; None if it isn't one."""
    import faces
    # both shapes; the one whose name is someone she knows ("powiedz jej" is no one)
    m = to = None
    for rx in (_WHEN, _ASK):
        m = rx.search(text)
        # "powiedz tacie" — a role too (9 Oct sweep: Maja's message for dad)
        to = (faces.match_name(m.group(1)) or faces.match_role(m.group(1))) if m else None
        if to:
            break
    m2 = _ASK.search(text)
    if not to and m2 and m2.group(1).lower() in ("jej", "mu"):
        # "Maja ma jutro wycieczkę, przypomnij jej rano, żeby wzięła kanapki" —
        # "jej" is the name said before it (8 Oct sweep: it became a reminder
        # for the whole house at 8:00)
        names = [faces.match_name(w) for w in re.findall(r"\w+", text[:m2.start()])]
        names = [n for n in names if n]
        if names:
            m, to = m2, names[-1]
    if not to:
        return None
    with state.lock:
        frm = state.person[0] if state.person else None
    if frm == to:
        return None                       # telling yourself: that's a reminder
    words = (m.group(2) + " " + m.group(3)).strip(" .!")
    at, daily = _when(text)
    with _lock:
        items = [e for e in _load() if e.get("daily") or time.time() - e["t"] < KEEP_DAYS * 86400]
        items.append({"to": to, "from": frm, "words": words, "t": time.time(),
                      "at": at, "daily": daily, "day": _day(text)})
        _save(items)
    print(f"[errands] for {to}" + (f" from {frm}" if frm else "")
          + (f" {'daily ' if daily else ''}after {at}" if at else "") + f": {words}",
          flush=True)
    return to, words


def waiting(who):
    with _lock:
        return [e for e in _load() if e["to"] == who and _due(e)]


def _sender(frm, to, notes):
    """Who asked, as the listener would say it: a child hears "mama" / "tata",
    a grown-up the name (8 Oct: Emilka heard "tata prosił…" about Andrzej)."""
    if "dziecko" in (notes.get(to) or "").lower():
        for role in ("mama", "tata"):
            if re.search(rf"\b{role}\b", (notes.get(frm) or "").lower()):
                return role
    return frm


def _phrase(e):
    """The note in words for them (vocative, "you" form), by the model; a
    plain fallback when it can't be reached."""
    import faces
    voc = faces.vocatives().get(e["to"]) or e["to"]
    frm = e.get("from")
    label = _sender(frm, e["to"], faces.notes()) if frm else ""
    asked = "prosiła" if label.endswith("a") else "prosił"       # Emilka / mama: prosiła
    plain = f"{voc}, " + (f"{label} {asked}, żebym ci przekazała: " if frm else
                         "mam dla ciebie wiadomość: ") + e["words"] + "."
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY, OPENAI_MODEL
        notes = faces.notes()
        c = OpenAI(api_key=OPENAI_API_KEY, timeout=10, max_retries=1)
        r = c.chat.completions.create(
            model=OPENAI_MODEL, temperature=0.3, max_tokens=80,
            messages=[{"role": "user", "content":
                       f"Jesteś Luną, małym robotem (mów o sobie w rodzaju żeńskim). "
                       + (f"{frm} ({notes.get(frm, '')}) poprosił cię, " if frm else
                          "Ktoś z domu (NIE wiesz kto — nie zgaduj i nie mów kto) poprosił cię, ")
                       + f"żebyś przekazała osobie {e['to']} "
                       f"({notes.get(e['to'], '')}) to: \"{e['words']}\". Powiedz to "
                       f"teraz bezpośrednio do tej osoby, zaczynając od \"{voc}\", jednym "
                       "lub dwoma krótkimi zdaniami, w formie zwracania się do niej "
                       "(np. \"żebyś posprzątała\")" + (f", mówiąc, że prosi {_sender(frm, e['to'], notes)}"
                                                       if frm else "") +
                       ". Nie dodawaj niczego, czego nie było w wiadomości (żadnych próśb "
                       "ani pośpiechu od siebie). Tylko te słowa, bez cudzysłowu."}])
        out = (r.choices[0].message.content or "").strip().strip('"')
        return out or plain
    except Exception as e2:
        print(f"[errands] phrasing failed ({e2}) — plain words", flush=True)
        return plain


def deliver(who, speak):
    """Say the waiting notes to `who` (they were just recognised)."""
    items = waiting(who)
    if not items:
        return False
    for e in items:
        said = _phrase(e)
        print(f"[errands] telling {who}: {said}", flush=True)
        speak(said)
    today = time.strftime("%Y-%m-%d")
    with _lock:
        rest = []
        for e in _load():
            if e in items:
                if not e.get("daily"):
                    continue                    # said: gone
                e["done"] = today               # every day: again tomorrow
            rest.append(e)
        _save(rest)
    return True


def mark_told(who, reply):
    """The model already passed a note on ("Co mi Andrzej przekazał?" → "Że kupił
    chleb.") — then it isn't said again when their face shows up (9 Oct probe).
    A note counts as told when most of its longer words are in the reply."""
    if not who or not reply:
        return 0
    said = {w[:5] for w in re.findall(r"\w{4,}", reply.lower())}
    told = []
    for e in waiting(who):
        if e.get("daily"):
            continue
        words = {w[:5] for w in re.findall(r"\w{4,}", e["words"].lower())}
        if words and len(words & said) >= max(1, (len(words) + 1) // 2):
            told.append(e)
    if told:
        with _lock:
            _save([e for e in _load() if e not in told])
        print(f"[errands] {len(told)} note(s) for {who} already told in a reply", flush=True)
    return len(told)


def prompt_line():
    with _lock:
        items = [e for e in _load() if e.get("daily") or time.time() - e["t"] < KEEP_DAYS * 86400]
    if not items:
        return ""
    return ("Notes you are to pass on when you see the person: "
            + "; ".join(f"for {e['to']}" + (f" from {e['from']}" if e.get("from") else "")
                        + (f" ({'every day ' if e.get('daily') else ''}after {e['at']})"
                           if e.get("at") else "")
                        + f": \"{e['words']}\"" for e in items) + ".\n")
