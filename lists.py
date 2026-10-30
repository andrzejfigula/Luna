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
BARE_UNDO_SECS = 120  # a bare "cofnij" — only this soon after
_undo = None         # (time, list name, items before) — the last clear or removal
# a day, and kept on disk: 16 Oct a tap crossed off "wypłacić pieniądze na
# drewno", and by the time anyone noticed the hour was up — and a restart
# would have lost it anyway
UNDO_SECS = 24 * 3600


def _undo_path():
    return LISTS_PATH.replace(".json", "_undo.json")


def _load():
    global _lists, _undo
    try:
        with open(LISTS_PATH, encoding="utf-8") as f:
            _lists = {k: list(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        _lists = {}
    try:
        with open(_undo_path(), encoding="utf-8") as f:
            t, name, items = json.load(f)
        _undo = (float(t), str(name), [str(i) for i in items])
    except (OSError, ValueError, TypeError):
        pass


def _save():
    tmp = LISTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_lists, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LISTS_PATH)
    try:                                     # what "przywróć listę" would bring back
        if _undo:
            with open(_undo_path() + ".tmp", "w", encoding="utf-8") as f:
                json.dump(list(_undo), f, ensure_ascii=False)
            os.replace(_undo_path() + ".tmp", _undo_path())
        elif os.path.exists(_undo_path()):
            os.remove(_undo_path())
    except OSError:
        pass


def _owners_path():
    return LISTS_PATH.replace(".json", "_owners.json")


def owners():
    """{list name: who started it} — "co mam dzisiaj zrobić?" from Emilka is not
    about the to-do list Andrzej dictated (6 Oct). The shopping list is shared."""
    try:
        with open(_owners_path(), encoding="utf-8") as f:
            return dict(json.load(f))
    except (OSError, ValueError):
        return {}


def _set_owner(lst, who):
    own = owners()
    if who:
        own[lst] = who
    else:
        own.pop(lst, None)
    try:
        tmp = _owners_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(own, f, ensure_ascii=False)
        os.replace(tmp, _owners_path())
    except OSError:
        pass


def _speaker():
    try:
        from shared_state import state
        with state.lock:
            return state.person[0] if state.person else None
    except Exception:
        return None


def _name(name):
    name = (name or "").strip().lower()
    return name or "zakupy"


_AMOUNT = re.compile(r"^(?:\d+[.,]?\d*\s*(?:g|kg|ml|l|dag)?|pół|szczypt\w*|łyżk\w*|łyżecz\w*|"
                     r"szklan\w*|garś\w*|kostk\w*|opakowani\w*|paczk\w*|odrobin\w*|trochę)\s+",
                     re.I)
_NOMINATIVE = {"soli": "sól", "cukru": "cukier", "mąki": "mąka", "mleka": "mleko",
               "masła": "masło", "oleju": "olej", "pieprzu": "pieprz", "drożdży": "drożdże",
               "śmietany": "śmietana", "jajek": "jajka", "jaj": "jajka", "wody": "woda",
               "ryżu": "ryż", "makaronu": "makaron", "sera": "ser", "twarogu": "twaróg",
               "cynamonu": "cynamon", "kakao": "kakao", "proszku do pieczenia": "proszek do pieczenia",
               "ziemniaków": "ziemniaki", "pomidorów": "pomidory", "jabłek": "jabłka",
               "marchwi": "marchew", "cebuli": "cebula", "mięsa": "mięso", "kurczaka": "kurczak"}


def shopping_item(item):
    """"szczypta soli" → "sól", "2 szklanki mąki" → "mąka": the thing to buy
    (8 Oct sweep: "szczypta soli" on the shopping list — the prompt rule alone
    didn't do it). Unknown words are left as they were."""
    if " — " in item:
        return item                    # "ziemniaki — 2 kg": an amount they said (10 Oct)
    m = _AMOUNT.match(item)
    if not m:
        return item
    rest = item[m.end():].strip()
    unit = re.fullmatch(r"(\d+[.,]?\d*)\s*(kg|g|dag|l|ml)", m.group(0).strip())
    if unit:                           # "2 kg ziemniaków" — a buying amount: kept
        thing = _NOMINATIVE.get(rest.lower())
        return f"{thing} — {unit.group(1)} {unit.group(2)}" if thing else item
    rest = re.sub(r"^(?:\w+\s+)?(?=\w)", lambda x: "" if re.match(
        r"(?:szklan|łyż|garś|kostk)\w*\s", x.group(0) or "") else x.group(0), rest)
    return _NOMINATIVE.get(rest.lower(), rest if rest.lower() in _NOMINATIVE.values() else item)


def _same_word(a, b):
    """"wypłacić" ~ "wypłacenie", "pieniądze" ~ "pieniędzy", "ser" ~ "sera"."""
    n = max(3, min(len(a), len(b), 6) - 1)
    return a[:n] == b[:n]


def closest(item, items):
    """The one item meant, said another way (23 Oct: "usuń wypłacenie pieniędzy
    na drewno" — the list had "wypłacić pieniądze na drewno", nothing came off)."""
    words = lambda s: re.findall(r"[^\W\d_]{3,}", s.lower())
    want = words(item)
    if not want:
        return None
    scored = []
    for i in items:
        have = words(i)
        hit = sum(any(_same_word(w, h) for h in have) for w in want)
        scored.append((hit / len(want), hit / max(len(have), 1), i))
    scored.sort(reverse=True)
    best = scored[0] if scored else None
    if not best or best[0] < (1.0 if len(want) <= 2 else 0.66) or best[1] < 0.5:
        return None
    if len(scored) > 1 and scored[1][:2] == best[:2]:
        return None                        # two equally close: not a guess
    return best[2]


def _without(item, items):
    keep = [i for i in items if item.lower() not in i.lower()]
    if len(keep) == len(items):
        near = closest(item, items)
        keep = [i for i in items if i != near]
    return keep


def _a_task(item):
    """"przykryć drewno", "umyć auto" — a thing to do, not to buy ("kupić mleko"
    is shopping)."""
    first = (item.split() or [""])[0].lower()
    return (len(item.split()) >= 2 and len(first) > 3 and first.endswith(("ć", "c"))
            and not first.startswith(("kupi", "kupować", "kupowac")))


def apply(actions, said=""):
    """list_add / list_remove / list_clear from the model's actions. said: the
    words — a task on "zakupy" when no shopping was named goes to the to-do list
    (23 Oct 12:38: "Dodaj do listy przykryć drewno" → zakupy, tapped off)."""
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
            if (kind == "list_add" and lst == "zakupy" and said
                    and not re.search(r"zakup|sklep", said, re.I) and _a_task(item)):
                lst = "do zrobienia"
                done.append("moved to do zrobienia")
            if lst == "zakupy" and kind == "list_add":
                item = shopping_item(item)
            fresh = not _lists.get(lst)
            items = _lists.setdefault(lst, [])
            if fresh and kind == "list_add" and lst != "zakupy":
                _set_owner(lst, _speaker())          # whose list this is
            if kind in ("list_remove", "list_clear") and items:
                _undo = (time.time(), lst, list(items))     # a mishearing can be undone
            if kind == "list_add" and item and lst != "zakupy":
                item = dated(item)                   # "jutro" → "(18 października)"
            if kind == "list_add" and item:
                if item.lower() not in (i.lower() for i in items):
                    items.append(item)
                    done.append(f"+{item} → {lst}")
            elif kind == "list_remove" and item:
                keep = _without(item, items)
                if len(keep) == len(items):
                    # on another list ("list" left out → zakupy; it was a to-do)
                    other = [k for k, v in _lists.items()
                             if k != lst and len(_without(item, v)) != len(v)]
                    if len(other) == 1:
                        lst, items = other[0], _lists[other[0]]
                        _undo = (time.time(), lst, list(items))
                        keep = _without(item, items)
                if len(keep) != len(items):
                    done.append(f"-{item} ← {lst}")
                else:
                    done.append(f"nothing matched {item!r} on {lst}")
                _lists[lst] = keep
            elif kind == "list_clear":
                _lists[lst] = []
                done.append(f"cleared {lst}")
            if not _lists.get(lst):
                _lists.pop(lst, None)
                if lst in owners():
                    _set_owner(lst, None)
        if done:
            _save()
    if done:
        print("[lists] " + "; ".join(done), flush=True)
    return done


def remove_exact(name, item):
    """Just this item (a tap on the list on her screen): not every item that
    contains its words, as list_remove does ("mleko" would take "mleko
    kokosowe" with it). "Przywróć listę" brings it back. True if it was there."""
    global _undo
    with _lock:
        if _lists is None:
            _load()
        items = _lists.get(name) or []
        if item not in items:
            return False
        _undo = (time.time(), name, list(items))
        items.remove(item)
        if not items:
            _lists.pop(name, None)
            if name in owners():
                _set_owner(name, None)
        _save()
    print(f"[lists] -{item} ← {name} (tapped)", flush=True)
    return True


_RESTORE = re.compile(r"\b(?:przywróć|przywroc|odzyskaj)\s+(?:t[aąeę]\s+)?(?:list|zakup|"
                      r"to\b|poprzedni|skreślon|skreslon|usunięt|usuniet)|"
                      r"\bcofnij\s+(?:to\s+)?(?:skreśl|skresl|usunięci|usunieci|czyszczeni|"
                      r"wyczyszczeni)", re.I)


def restore(text, now=None):
    """"przywróć listę" → the reply, or None when the words don't ask for it."""
    global _undo
    now = time.time() if now is None else now
    bare = re.fullmatch(r"\s*(?:luna,?\s+)?(?:cofnij|odwołaj|odwolaj)(?:\s+to)?[.!]*\s*",
                        text or "", re.I)
    if bare:
        # a bare "Cofnij" right after a removal (11 Oct sweep: "Usuń chleb" →
        # "Cofnij" → "potrzebuję wiedzieć którą") — later it may mean anything
        if not _undo or now - _undo[0] > BARE_UNDO_SECS:
            return None
    elif not _RESTORE.search(text) or len(text.split()) > 8:
        return None
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


_REMOVE = re.compile(r"^(?:luna,?\s+)?(?:skreśl|skresl|wykreśl|wykresl|usuń|usun|wyrzuć|wyrzuc)\s+"
                     r"(?:mi\s+)?(?:z\s+(?:listy|listę)(?:\s+(?:zakupów|zakupow|do\s+zrobienia))?:?\s+)?"
                     r"(.+?)(?:\s+z\s+(?:listy|listę|liste)(?:\s+(?:zakupów|zakupow|do\s+zrobienia|\w+))?)?"
                     r"[.!]*$", re.I)
# "Kupiłam mleko" — off the shopping list, when it's there (else it's just talk)
_BOUGHT = re.compile(r"^(?:luna,?\s+)?(?:już\s+|juz\s+)?(?:kupiłam|kupiłem|kupilam|kupilem|"
                     r"mam\s+już|mam\s+juz|kupione)(?:\s+już|\s+juz)?:?\s+(.+?)[.!]*$", re.I)
_NOT_A_LIST = re.compile(r"ulubion|plan|zdjęc|zdjec|rysun|przypomn|budzik|minutnik|alarm|pamięc|"
                         r"pamiec|twarz|wszystk|całą|cala|\blist[aęy]\b", re.I)


def local_remove(text):
    """"Skreśl chleb", "usuń umyć auto z listy" — each thing found on one list
    (said any way: closest()) comes off without the model; otherwise None and
    the model has it. The reply, or None."""
    m = _REMOVE.match(text.strip()) or _BOUGHT.match(text.strip())
    if not m or _NOT_A_LIST.search(m.group(1)):
        return None
    only = "zakupy" if m.re is _BOUGHT else None
    global _undo
    parts = [p.strip(" .") for p in re.split(r",|\s+i\s+|\s+oraz\s+", m.group(1)) if p.strip(" .")]
    with _lock:
        if _lists is None:
            _load()
        found = {}
        for p in parts:
            if p.lower() in ("to", "tamto", "ten", "tę", "tą", "je", "go", "ją", "coś", "cos",
                             "ostatnie", "ostatnią", "tamtą") or not re.search(r"[^\W\d_]{3,}", p):
                return None                # "usuń to" (to ⊂ "umyć auto"): the model's
            hits = []
            for k, v in _lists.items():
                if only and k != only:
                    continue
                keep = _without(p, v)
                hits += [(k, i) for i in v if i not in keep]
            if len(hits) != 1:
                return None                # not there, or twice: the model asks
            found[p] = hits[0]
        lsts = {k for k, _ in found.values()}
        if len(lsts) != 1:
            return None
        lst = lsts.pop()
        gone = [i for _, i in found.values()]
        _undo = (time.time(), lst, list(_lists[lst]))
        _lists[lst] = [i for i in _lists[lst] if i not in gone]
        if not _lists[lst]:
            _lists.pop(lst)
            if lst in owners():
                _set_owner(lst, None)
        _save()
    print(f"[lists] -{', '.join(gone)} ← {lst} (local)", flush=True)
    return f"Skreśliłam: {', '.join(gone)}."


_CLEAR = re.compile(r"^(?:luna,?\s+)?(?:wyczyść|wyczysc|wyczyszcz|opróżnij|oproznij|skasuj|"
                    r"usuń|usun)\s+(?:całą\s+|cala\s+)?(?:listę|liste)(?:\s+(?:zakupów|zakupow|"
                    r"do\s+zrobienia|(\w+)))?\W*$", re.I)


def clear_empty_answer(text):
    """"Wyczyść listę zakupów" when it is already empty → said here (9 Oct: "Jasne,
    już czyszczę… Właściwie ta lista już była pusta" — the first half was already
    spoken). None when the list has items: the model clears it (with undo)."""
    name = _clear_target(text)
    if not name or get(name):
        return None
    return ("Lista zakupów już jest pusta." if name == "zakupy"
            else f"Lista „{name}” już jest pusta.")


def _clear_target(text, named=False):
    """The list "wyczyść listę …" names (zakupy when none); named: None unless one is."""
    m = _CLEAR.match((text or "").strip())
    if not m:
        return None
    low = text.lower()
    if named and not re.search(r"list[eę]\s+\w", low):
        return None
    return ("do zrobienia" if "do zrobienia" in low else m.group(1).lower() if m.group(1)
            else "zakupy")


def local_clear(text):
    """"Wyczyść listę zakupów" with things on it — cleared here, undo kept (30 Oct:
    via the model, 4.7 s and a hedge retry). A bare "usuń listę" stays the model's."""
    global _undo
    name = _clear_target(text, named=True)
    if not name:
        return None
    with _lock:
        if _lists is None:
            _load()
        items = _lists.get(name)
        if not items:
            return None
        _undo = (time.time(), name, list(items))
        _lists.pop(name)
        if name in owners():
            _set_owner(name, None)
        _save()
    print(f"[lists] cleared {name} (local, {len(items)})", flush=True)
    title = "zakupów" if name == "zakupy" else f"„{name}”"
    return (f"Wyczyściłam listę {title} — {_things(len(items))}. "
            "Gdyby co, powiedz: przywróć listę.")


def _things(n):
    if n == 1:
        return "była jedna rzecz"
    few = n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
    return f"{'były' if few else 'było'} {n} rzeczy"


def empty_answer(name, now=None):
    """"Pokaż listę …" found nothing to show: say which list is empty, which
    ones there are, and that a tap-emptied one can come back."""
    if not name:
        return "Nie masz jeszcze żadnej listy."
    now = time.time() if now is None else now
    title = "zakupów" if name == "zakupy" else name
    have = [k for k in get() if k != name]
    line = (f"Lista {title} jest pusta." if name in ("zakupy", "do zrobienia")
            else f"Nie mam listy „{name}”.")
    if _undo and _undo[1] == name and now - _undo[0] <= UNDO_SECS:
        line += " Coś z niej niedawno zniknęło — powiedz: przywróć listę."
    elif have:
        line += " Mam listę: " + ", ".join("zakupów" if k == "zakupy" else k
                                           for k in have) + "."
    return line


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
    own = owners()
    who = _speaker()

    def whose(k):
        # spelled out for the one asking — 13 Oct 11:32: Emilka's "Co mam
        # dzisiaj zrobić?" got Andrzej's to-do list read as hers
        if not own.get(k):
            return ""
        if who and who != own[k]:
            return f" ({own[k].upper()}'S list — NOT {who}'s)"
        return f" (started by {own[k]})"

    body = "; ".join(f"{k}{whose(k)}: {', '.join(v)}" for k, v in lists.items())
    return (f"Your lists: {body}. A list started by someone is theirs: when another "
            "person asks what THEY have to do, don't read it as theirs.\n")


# ── to-do items with a day ────────────────────────────────────────────────────
# 16 Oct: "wypłacić pieniądze na drewno 16 października" lived only in her
# memory, which dropped it the day after ("przeszła data") — never said on the
# day. Now the day is part of the item: "jutro" / "w piątek" become a date when
# it is written down, the plan for the day names it, and once past it is "zaległe".
_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
           "sierpnia", "września", "października", "listopada", "grudnia"]
_WEEKDAYS = {"poniedziałek": 0, "poniedzialek": 0, "wtorek": 1, "środę": 2, "srode": 2,
             "środa": 2, "czwartek": 3, "piątek": 4, "piatek": 4, "sobotę": 5, "sobote": 5,
             "sobota": 5, "niedzielę": 6, "niedziele": 6, "niedziela": 6}
_REL_DAY = re.compile(r"\b(dzisiaj|dziś|dzis|jutro|pojutrze|"
                      r"(?:w|we)\s+(" + "|".join(_WEEKDAYS) + r"))\b", re.I)


def dated(item, now=None):
    """"zadzwonić do babci jutro" → "zadzwonić do babci (18 października)";
    an item with no day, or with a date already, stays as it is."""
    import datetime as _dt
    if due(item, now) is not None:
        return item
    m = _REL_DAY.search(item)
    if not m:
        return item
    today = _dt.date.fromtimestamp(now if now is not None else time.time())
    word = m.group(1).lower()
    if word.startswith("dzi"):
        day = today
    elif word == "jutro":
        day = today + _dt.timedelta(days=1)
    elif word == "pojutrze":
        day = today + _dt.timedelta(days=2)
    else:
        ahead = (_WEEKDAYS[m.group(2).lower()] - today.weekday()) % 7 or 7
        day = today + _dt.timedelta(days=ahead)
    rest = (item[:m.start()] + item[m.end():]).strip(" ,.")
    rest = re.sub(r"\s{2,}", " ", rest)
    return f"{rest} ({day.day} {_MONTHS[day.month - 1]})"


def due(item, now=None):
    """The day an item is for ("… 16 października", "… (18 października)"),
    as a date — the nearest such day not long past — or None."""
    import datetime as _dt
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b", item.lower())
    if not m:
        return None
    today = _dt.date.fromtimestamp(now if now is not None else time.time())
    month, day = _MONTHS.index(m.group(2)) + 1, int(m.group(1))
    try:
        d = _dt.date(today.year, month, day)
    except ValueError:
        return None
    if (d - today).days < -180:             # "5 stycznia", written in December
        d = d.replace(year=today.year + 1)
    elif (d - today).days > 180:
        d = d.replace(year=today.year - 1)
    return d


def due_rows(now=None):
    """("dziś" | "jutro" | "zaległe", item) for dated items on any list but
    shopping — for the plan of the day and the morning hello."""
    import datetime as _dt
    today = _dt.date.fromtimestamp(now if now is not None else time.time())
    rows = []
    for name, items in get().items():
        if name == "zakupy":
            continue
        for i in items:
            d = due(i, now)
            if d is None:
                continue
            gap = (d - today).days
            if gap < 0:
                rows.append(("zaległe", i))
            elif gap == 0:
                rows.append(("dziś", i))
            elif gap == 1:
                rows.append(("jutro", i))
    order = {"zaległe": 0, "dziś": 1, "jutro": 2}
    return sorted(rows, key=lambda r: order[r[0]])


_TODO = re.compile(r"\bdo\s+zrobienia|\bzada[nńi]\w*|\bto\s*-?\s*do\b|\bspraw\w*\b", re.I)
_NAMED = re.compile(r"\b(?:list[eęy]|liście)\s+(?:mi\s+)?(.+?)\W*$", re.I)


def find(text):
    """Which list does "pokaż listę …" mean? The one named in the text — even
    an empty or missing one: 16 Oct 13:59, the to-do list had just emptied and
    "pokaż listę rzeczy do zrobienia" showed the shopping list. Unnamed: the
    shopping list, else the only one there is."""
    lists = get()
    low = text.lower()
    if _TODO.search(low):
        return "do zrobienia"
    for k in lists:
        if k in low or k[:5] in low:
            return k
    if "zakup" in low:
        return "zakupy"
    named = _NAMED.search(low)
    rest = re.sub(r"\b(?:proszę|prosze|teraz|jeszcze|raz|mi|moją|moja|tę|tą|tamtą|"
                  r"luna|na\s+ekranie|please)\b", " ", named.group(1) if named else "")
    rest = " ".join(re.findall(r"[^\W\d_]+", rest))
    if rest:
        return rest
    return "zakupy" if "zakupy" in lists else next(iter(lists), None)
