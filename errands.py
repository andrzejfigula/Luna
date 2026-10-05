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
_ASK = re.compile(r"\b(?:przekaż|przekaz|powiedz|powtórz|powtorz|daj znać|daj znac)\s+(\w+)"
                  r"(?:\s+(?:od\s+(?:mnie|nas)))?[,:]?\s+(że|ze|żeby|zeby|aby|by)\s+(.+)$",
                  re.I)
_WHEN = re.compile(r"\b(?:jak|kiedy|gdy)\s+(?:zobaczysz|spotkasz|przyjdzie|wróci|wroci)\s+"
                   r"(\w+)\W+(?:to\s+)?(?:powiedz|przekaż|przekaz)\s+(?:mu|jej|im)?[,:]?\s*"
                   r"(że|ze|żeby|zeby|aby|by)\s+(.+)$", re.I)


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
        to = faces.match_name(m.group(1)) if m else None
        if to:
            break
    if not to:
        return None
    with state.lock:
        frm = state.person[0] if state.person else None
    if frm == to:
        return None                       # telling yourself: that's a reminder
    words = (m.group(2) + " " + m.group(3)).strip(" .!")
    with _lock:
        items = [e for e in _load() if time.time() - e["t"] < KEEP_DAYS * 86400]
        items.append({"to": to, "from": frm, "words": words, "t": time.time()})
        _save(items)
    print(f"[errands] for {to}" + (f" from {frm}" if frm else "") + f": {words}", flush=True)
    return to, words


def waiting(who):
    with _lock:
        return [e for e in _load() if e["to"] == who
                and time.time() - e["t"] < KEEP_DAYS * 86400]


def _phrase(e):
    """The note in words for them (vocative, "you" form), by the model; a
    plain fallback when it can't be reached."""
    import faces
    voc = faces.vocatives().get(e["to"]) or e["to"]
    frm = e.get("from")
    plain = f"{voc}, " + (f"{frm} prosił, żebym ci przekazała: " if frm else
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
                       "(np. \"żebyś posprzątała\")" + (", mówiąc kto prosił (dla dziecka "
                       "rodzic to tata/mama)" if frm else "") +
                       ". Tylko te słowa, bez cudzysłowu."}])
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
    with _lock:
        _save([e for e in _load() if e not in items])
    return True


def prompt_line():
    with _lock:
        items = [e for e in _load() if time.time() - e["t"] < KEEP_DAYS * 86400]
    if not items:
        return ""
    return ("Notes you are to pass on when you see the person: "
            + "; ".join(f"for {e['to']}" + (f" from {e['from']}" if e.get("from") else "")
                        + f": \"{e['words']}\"" for e in items) + ".\n")
