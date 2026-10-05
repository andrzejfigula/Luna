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
