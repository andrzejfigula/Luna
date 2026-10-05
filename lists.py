"""
lists.py — shopping list, to-do list, any list you name.

"Dopisz mleko do listy zakupów", "skreśl chleb", "co mam na liście?",
"wyczyść listę zakupów", "przywróć listę" (undo, for an hour). The model asks for changes through the "actions" of
its reply (list_add / list_remove / list_clear, see brain.py); every request
carries the current lists so it can read them back. "Pokaż listę zakupów"
puts one on her screen (screens.py). Kept in data/lists.json.
"""

import json
import os
import re
import threading
import time

from config import LISTS_PATH

_lock = threading.Lock()
_lists = None
_undo = None         # (time, list name, items before) — the last clear or removal
UNDO_SECS = 3600


def _load():
    global _lists
    try:
        with open(LISTS_PATH, encoding="utf-8") as f:
            _lists = {k: list(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        _lists = {}


def _save():
    tmp = LISTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_lists, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LISTS_PATH)


def _name(name):
    name = (name or "").strip().lower()
    return name or "zakupy"


def apply(actions):
    """list_add / list_remove / list_clear from the model's actions."""
    global _undo
    done = []
    with _lock:
        if _lists is None:
            _load()
        for a in actions or []:
            kind = str(a.get("type", ""))
            if not kind.startswith("list_"):
                continue
            lst = _name(a.get("list"))
            item = str(a.get("label", "")).strip()
            items = _lists.setdefault(lst, [])
            if kind in ("list_remove", "list_clear") and items:
                _undo = (time.time(), lst, list(items))     # a mishearing can be undone
            if kind == "list_add" and item:
                if item.lower() not in (i.lower() for i in items):
                    items.append(item)
                    done.append(f"+{item} → {lst}")
            elif kind == "list_remove" and item:
                keep = [i for i in items if item.lower() not in i.lower()]
                if len(keep) != len(items):
                    done.append(f"-{item} ← {lst}")
                _lists[lst] = keep
            elif kind == "list_clear":
                _lists[lst] = []
                done.append(f"cleared {lst}")
            if not _lists.get(lst):
                _lists.pop(lst, None)
        if done:
            _save()
    if done:
        print("[lists] " + "; ".join(done), flush=True)
    return done


_RESTORE = re.compile(r"\b(?:przywróć|przywroc|odzyskaj)\s+(?:t[aąeę]\s+)?(?:list|zakup|"
                      r"to\b|poprzedni|skreślon|skreslon|usunięt|usuniet)|"
                      r"\bcofnij\s+(?:to\s+)?(?:skreśl|skresl|usunięci|usunieci|czyszczeni|"
                      r"wyczyszczeni)", re.I)


def restore(text, now=None):
    """"przywróć listę" → the reply, or None when the words don't ask for it."""
    global _undo
    if not _RESTORE.search(text) or len(text.split()) > 8:
        return None
    now = time.time() if now is None else now
    with _lock:
        if _lists is None:
            _load()
        if not _undo or now - _undo[0] > UNDO_SECS:
            return "Nie mam czego przywrócić — nic ostatnio nie znikało z list."
        _, lst, items = _undo
        _undo = None
        current = _lists.get(lst, [])
        back = [i for i in items if i.lower() not in (c.lower() for c in current)]
        _lists[lst] = current + back
        _save()
    print(f"[lists] restored {len(back)} on {lst}", flush=True)
    if not back:
        return f"Lista {lst} jest już taka jak wcześniej."
    return f"Przywróciłam na listę {lst}: {', '.join(back)}."


_READ = re.compile(r"\b(?:co\s+(?:mam|mamy|jest|jeszcze\s+jest|zostało)\s+na\s+liście|"
                   r"co\s+(?:mam|mamy)\s+(?:jeszcze\s+)?(?:kupić|kupic|zrobić|zrobic)|"
                   r"przeczytaj\s+(?:mi\s+)?listę|przeczytaj\s+(?:mi\s+)?liste)\b(.*)$", re.I)


_ADD = re.compile(r"^(?:luna,?\s+)?(?:dopisz|dodaj|wpisz|zapisz)\s+(?:mi\s+)?(.+?)\s+(?:do|na)\s+"
                  r"(?:listy|listę|liste)(?:\s+(.+?))?[.!]*$", re.I)


def local_add(text):
    """"Dopisz mleko i chleb do listy zakupów" without the model (used when
    the cloud is down: the words are kept as said, "kawę" not "kawa").
    The reply, or None."""
    m = _ADD.match(text.strip())
    if not m:
        return None
    raw = re.split(r",|\s+i\s+|\s+oraz\s+", m.group(1))
    items = [i.strip(" .") for i in raw if i.strip(" .")]
    if not items or any(len(i.split()) > 4 for i in items):
        return None
    which = (m.group(2) or "zakupów").lower()
    name = "zakupy" if which.startswith("zakup") else which
    done = apply([{"type": "list_add", "label": i, "list": name} for i in items])
    if not done:
        return "To już jest na liście."
    return f"Dopisałam: {', '.join(items)}."


def read_answer(text):
    """"Co mam na liście zakupów?", "co mam kupić?" → the list read out, here
    and offline; None for anything else."""
    m = _READ.search(text)
    if not m or len(text.split()) > 9:
        return None
    low = text.lower()
    lists = get()
    if "zrobi" in low:
        name = next((k for k in lists if "zrobi" in k or "zada" in k), None)
    elif "kupi" in low:
        name = "zakupy" if "zakupy" in lists else None
    else:
        name = find(text) if lists else None
    if not name or not lists.get(name):
        what = "zakupów" if ("kupi" in low or "zakup" in low) else "tej liście"
        return f"Na liście {what} nic nie ma." if what == "zakupów" else "Ta lista jest pusta."
    items = lists[name]
    title = "zakupów" if name == "zakupy" else f"„{name}”"
    return f"Na liście {title} ({len(items)}): " + ", ".join(items) + "."


def get(name=None):
    with _lock:
        if _lists is None:
            _load()
        if name is None:
            return {k: list(v) for k, v in _lists.items()}
        return list(_lists.get(_name(name), []))


def prompt_block():
    lists = get()
    if not lists:
        return "Your lists (shopping, to-do…): all empty.\n"
    body = "; ".join(f"{k}: {', '.join(v)}" for k, v in lists.items())
    return f"Your lists: {body}.\n"


def find(text):
    """Which list does "pokaż listę …" mean? The one named in the text, else
    the shopping list, else the only one there is."""
    lists = get()
    low = text.lower()
    for k in lists:
        if k in low or k[:5] in low:
            return k
    if "zakup" in low and "zakupy" in lists:
        return "zakupy"
    return next(iter(lists), None)
