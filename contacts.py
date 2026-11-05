"""
contacts.py — a contact card for everyone she knows.

  "pokaż kartę Mai", "karta Andrzeja", "moja karta", "pokaż kontakty"
  "jaki numer ma Emilka?", "podaj telefon do mamy", "jaki jest adres Mai?"
  "telefon Mai to 600 100 200", "Emilka ma numer 600 100 200", "mój e-mail to
  ola małpa gmail kropka com", "adres Andrzeja to Kwiatowa 5, Kraków"
  with a card on the screen: "zmień numer na 600 100 200"
  "usuń telefon Mai"

On the page (ui_contacts.py draws it): a row tapped opens a keyboard for that
field, ‹ › or a swipe go to the next person, ✕ closes the keyboard, then the page.

Kept with the person in data/people.json: phone, email, address, card_note, and
birthday / born / nameday, the same keys birthdays.py uses. None of it goes into
the prompt, and only what field was changed is logged, never its value. "note"
(who someone is) stays read-only: it decides who counts as a child.

A guest or a stranger sees only their own card; a child sees everyone's and
changes only their own.
"""

import re
import time
from datetime import date

from shared_state import state

PAGE_SECS = 60                # untouched this long, the page closes
EDIT_SECS = 180               # …longer while typing
MAX_LEN = {"phone": 24, "email": 80, "address": 120, "card_note": 200,
           "birthday": 10, "nameday": 10}

# (key, label on the card, keyboard)
FIELDS = (("phone", "Telefon", "phone"), ("email", "E-mail", "text"),
          ("address", "Adres", "text"), ("birthday", "Data urodzenia", "date"),
          ("nameday", "Imieniny", "date"), ("card_note", "Uwagi", "text"))
_KIND = {f: k for f, _, k in FIELDS}
_LABEL = {f: l for f, l, _ in FIELDS}
HINT = {"phone": "np. 600 100 200", "email": "np. ola@gmail.com", "address": "ulica, numer, miasto",
        "birthday": "dzień.miesiąc.rok", "nameday": "dzień.miesiąc", "card_note": ""}

_MISSING = {"phone": "numeru", "email": "e-maila", "address": "adresu"}
_BAD_VALUE = {"phone": "To nie wygląda na numer telefonu. Powtórz proszę, cyfra po cyfrze.",
              "email": "To nie wygląda na adres e-mail. Powtórz proszę albo wpisz go na karcie.",
              "address": "Nie dosłyszałam adresu. Powtórz proszę."}
_FAMILY_ONLY = "Poproś kogoś z rodziny."
_GROWN_UP_ONLY = "Poproś dorosłego."


# ── values ────────────────────────────────────────────────────────────────────

def clean_phone(raw):
    """"600100200" → "600 100 200", "0048 600…" → "+48 600 100 200"; None if it isn't one."""
    s = (raw or "").strip()
    intl = s.startswith(("+", "00"))
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]
    if re.search(r"[^\d\s+().-]", s) or not 7 <= len(digits) <= 15:
        return None
    if intl and digits.startswith("48") and len(digits) == 11:
        return "+48 " + clean_phone(digits[2:])
    if intl:
        return "+" + digits
    return " ".join(digits[i:i + 3] for i in range(0, len(digits), 3))


def clean_email(raw):
    s = (raw or "").strip().rstrip(".").lower()
    return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s.]+", s) else None


def parse_date(raw, today=None):
    """"12.05.2018" / "12.05" → (month, day, year or None); None if it isn't a real date."""
    m = re.fullmatch(r"(\d{1,2})[.\-/ ](\d{1,2})(?:[.\-/ ](\d{4}))?\.?", (raw or "").strip())
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None
    try:
        date(year or 2000, month, day)                 # (2000: 29 February is fine without a year)
    except ValueError:
        return None
    if year and not date(1900, 1, 1) <= date(year, month, day) <= (today or date.today()):
        return None
    return month, day, year


def save(name, field, raw):
    """One field from what was typed or said (empty: removed). None, or what is wrong."""
    import faces
    raw = " ".join(str(raw or "").split())[:MAX_LEN[field]]
    change, drop = {}, ()
    if not raw:
        drop = ("birthday", "born") if field == "birthday" else (field,)
    elif field == "phone":
        change[field] = clean_phone(raw)
        if not change[field]:
            return "To nie wygląda na numer telefonu"
    elif field == "email":
        change[field] = clean_email(raw)
        if not change[field]:
            return "To nie wygląda na adres e-mail"
    elif _KIND[field] == "date":
        got = parse_date(raw)
        if not got:
            return "Wpisz datę: " + HINT[field]
        month, day, year = got
        change[field] = f"{month:02d}-{day:02d}"
        if field == "birthday":
            if year:
                change["born"] = year
            else:
                drop = ("born",)
    else:
        change[field] = raw
    with faces._lock:
        p = faces._load().get(name)
        if p is None:
            return "Nie znam tej osoby"
        for key in drop:
            p.pop(key, None)
        p.update(change)
        faces._save()
    print(f"[contacts] {name}: {field} {'removed' if not raw else 'saved'}", flush=True)
    return None


def card(name):
    """What the card shows ({field: stored value}, and "note"); None if unknown."""
    import faces
    keys = tuple(_KIND) + ("born", "note")
    with faces._lock:
        p = faces._load().get(name)
        return None if p is None else {k: p.get(k) for k in keys}


def _md(md):
    return tuple(int(x) for x in md.split("-"))


def shown(c, field, today=None):
    """A field as the card shows it: "12 maja 2018 (8 lat)"; "" when empty."""
    import birthdays
    import calc
    v = c.get(field)
    if not v:
        return ""
    if _KIND[field] != "date":
        return str(v)
    month, day = _md(v)
    out = f"{day} {birthdays._MONTHS_GEN[month - 1]}"
    born = c.get("born") if field == "birthday" else None
    if born:
        today = today or date.today()
        years = today.year - born - ((today.month, today.day) < (month, day))
        out += f" {born} ({years} {calc._plural(years, 'rok', 'lata', 'lat')})"
    return out


def typed(c, field):
    """A field as the keyboard starts with it: "12.05.2018"."""
    v = c.get(field)
    if not v:
        return ""
    if _KIND[field] != "date":
        return str(v)
    month, day = _md(v)
    born = c.get("born") if field == "birthday" else None
    return f"{day}.{month:02d}" + (f".{born}" if born else "")


# ── who may ───────────────────────────────────────────────────────────────────

def viewer():
    with state.lock:
        return state.person[0] if state.person else None


def _outsider():
    import settings_page
    return settings_page._outsider_here()


def may_see(name):
    return viewer() == name or not _outsider()


def may_edit(name):
    """None if they may, else who to ask."""
    if viewer() == name:
        return None
    if _outsider():
        return _FAMILY_ONLY
    import faces                                   # (not via brain: a failed import there means "adult")
    return _GROWN_UP_ONLY if "dziecko" in faces.notes().get(viewer(), "").lower() else None


def people():
    """Whose cards can be turned to now: family first, then guests."""
    import faces
    return [n for n in faces.family() + faces.guests() if may_see(n)]


# ── the page ──────────────────────────────────────────────────────────────────

def show(name, toast=None, back=None):
    import screens
    data = {"name": name, "edit": None, "toast": None, "back": back}
    if toast:
        data["toast"] = (toast, time.time() + 2.5)
    screens._show("contact", PAGE_SECS, data)


def on_screen(now=None):
    """Whose card (or whose picture among "kogo znam") is on the screen, or None."""
    import gallery
    with state.lock:
        ov = state.overlay
    if ov and ov[0] == "contact" and (now or time.time()) < ov[1]:
        return ov[2]["name"]
    item = gallery.current()
    return item.get("name") if item and item.get("kind") == "person" else None


def open_from(name, back=None):
    """Opened by a tap (the Osoby tab). None, or the reason it wasn't."""
    if not may_see(name):
        return _FAMILY_ONLY
    show(name, back=back)
    return None


def _page_data(now=None):
    now = now or time.time()
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "contact":
            return None
        secs = EDIT_SECS if ov[2].get("edit") else PAGE_SECS
        state.overlay = (ov[0], now + secs, ov[2])
        return ov[2]


def _toast(data, text, now=None):
    data["toast"] = (text, (now or time.time()) + 2.5)


def on_close():
    """✕ on this page: the keyboard goes first; a card opened from the settings
    goes back there. True if something is still on the screen."""
    import settings_page
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "contact":
            return False
        data = ov[2]
        if data.get("edit"):
            data["edit"] = None
            return True
        if data.get("back"):
            state.overlay = ("settings", time.time() + settings_page.PAGE_SECS, data["back"])
            return True
    return False


def card_layout(W, H):
    """{"rows": a rect (x, y, w, h) per field, "prev", "next"}."""
    x, top = 236, 84
    rh = (H - top - 12) // len(FIELDS)
    return {"rows": [(x, top + k * rh, W - x - 16, rh - 8) for k in range(len(FIELDS))],
            "prev": (28, H - 72, 80, 56), "next": (128, H - 72, 80, 56)}


def box_rect(W):
    """The field being typed; left of the ✕."""
    return (16, 18, W - 112, 62)


_LAYERS = {"abc": ("qwertyuiop", "asdfghjkl", "zxcvbnm"),
           "pl": ("ąćęłńóśźż", "asdfghjkl", "zxcvbnm"),
           "123": ("1234567890", "-/:;()&+_'", "#\"!?%=*")}


def key_layout(kind, layer, W, H):
    """The keyboard: [(key, (x, y, w, h))]. A key is a character, or "back",
    "save", "shift", "clear", "layer:abc" and the like."""
    top, gap = 92, 6
    bx, by, bw, bh = box_rect(W)
    out = [("clear", (bx + bw - 56, by + 6, 50, bh - 12))]
    kh = (H - top - 6) // 4
    if kind in ("phone", "date"):                  # big digits, "Zapisz" beside them
        kw = 170
        x0 = (W - 3 * kw - 196) // 2
        grid = ("123", "456", "789", ("+" if kind == "phone" else ".") + "0<")
        for r, row in enumerate(grid):
            for c, ch in enumerate(row):
                out.append(("back" if ch == "<" else ch,
                            (x0 + c * kw, top + r * kh, kw - gap, kh - gap)))
        out.append(("save", (x0 + 3 * kw + 10, top, 186, 4 * kh - gap)))
        return out
    unit = (W - 16) / 10.0

    def row_of(y, items, x):
        for key, width in items:
            out.append((key, (int(x), y, int(width * unit) - gap, kh - gap)))
            x += width * unit
    rows = _LAYERS[layer]
    for r, row in enumerate(rows[:2]):
        row_of(top + r * kh, [(ch, 1) for ch in row], (W - len(row) * unit) / 2)
    row_of(top + 2 * kh, [("shift", 1.5)] + [(ch, 1) for ch in rows[2]] + [("back", 1.5)], 8)
    switch = "layer:abc" if layer == "123" else "layer:123"
    polish = "layer:abc" if layer == "pl" else "layer:pl"
    row_of(top + 3 * kh, [(switch, 1.5), (polish, 1), (",", 1), (" ", 3), (".", 1), ("@", 1),
                          ("save", 1.5)], 8)
    return out


def _within(rect, x, y):
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def key_at(kind, layer, x, y, W, H):
    return next((k for k, r in key_layout(kind, layer, W, H) if _within(r, x, y)), None)


def press(data, key, now=None):
    """A key on the keyboard."""
    e, name = data["edit"], data["name"]
    if key == "save":
        said = may_edit(name) or save(name, e["field"], e["text"])
        if said:
            _toast(data, said, now)
        else:
            data["edit"] = None
            _toast(data, "Zapisane", now)
    elif key == "back":
        e["text"] = e["text"][:-1]
    elif key == "clear":
        e["text"] = ""
    elif key == "shift":
        e["shift"] = not e["shift"]
    elif key.startswith("layer:"):
        e["layer"] = key.split(":", 1)[1]
    elif len(e["text"]) < MAX_LEN[e["field"]]:
        e["text"] += key.upper() if e["shift"] else key
        e["shift"] = False
        if e["layer"] == "pl":                     # one Polish letter, then the letters again
            e["layer"] = "abc"


def _start_edit(data, field, now=None):
    said = may_edit(data["name"])
    c = card(data["name"])
    if said or c is None:
        _toast(data, said or "Nie znam tej osoby", now)
        return
    text = typed(c, field)
    data["edit"] = {"field": field, "text": text, "layer": "abc",
                    "shift": not text and field in ("address", "card_note")}


def _turn(data, step):
    names = people()
    if data["name"] in names and len(names) > 1:
        data["name"] = names[(names.index(data["name"]) + step) % len(names)]


def tap(x, y, W, H, now=None):
    """A tap (px): a key, a field to edit, ‹ or ›."""
    data = _page_data(now)
    if data is None:
        return False
    e = data.get("edit")
    if e:
        key = key_at(_KIND[e["field"]], e["layer"], x, y, W, H)
        if key:
            press(data, key, now)
        return True
    L = card_layout(W, H)
    for (field, _, _), rect in zip(FIELDS, L["rows"]):
        if _within(rect, x, y):
            _start_edit(data, field, now)
            return True
    if _within(L["prev"], x, y):
        _turn(data, -1)
    elif _within(L["next"], x, y):
        _turn(data, 1)
    return True


def swipe(dx):
    """A swipe: the next person (to the left) or the one before."""
    data = _page_data()
    if data is None or data.get("edit"):
        return False
    _turn(data, 1 if dx < 0 else -1)
    return True


# ── voice ─────────────────────────────────────────────────────────────────────

_ANY = re.compile(r"kart[aeęy]|kontakt|wizyt[oó]wk|ksi[aą][żz]k|telefon|numer|kom[oó]rk|mail|mejl|adres",
                  re.I)
_FIELD = re.compile(r"\b(?:(?P<email>(?:adres\w*\s+)?(?:e-?)?(?:mail|mejl)\w*)|"
                    r"(?P<phone>numer\w*(?:\s+(?:telefonu|telefon|komórki|komorki))?|telefon\w*|"
                    r"komórk\w*|komork\w*)|"
                    r"(?P<address>adres\w*))\b")
_LEAD = re.compile(r"^(?:(?:hej|ej),?\s+)?(?:luna|luno)\s*[,!.:]?\s+", re.I)
_SEP = re.compile(r"^(.*?)(?:\s*[:=]\s*|(?:^|\s+)(?:to\s+jest|to|jest|na|będzie|bedzie)\s+)(.+)$",
                  re.I | re.S)
_DELETE = {"usuń", "usun", "skasuj", "wykasuj", "wymaż", "wymaz", "wyczyść", "wyczysc"}
_VERBS = {"zapisz", "zapamiętaj", "zapamietaj", "wpisz", "dodaj", "ustaw", "zmień", "zmien",
          "popraw", "zanotuj"}
_MINE = {"mój", "moj", "moja", "moją", "moje", "mojej", "mojego", "moim", "mam", "mnie"}
_POLITE = {"mi", "nam", "proszę", "prosze", "sobie", "że", "ze", "jej", "jego", "tej", "tego", "tę"}
_SET_FILL = _VERBS | _POLITE | {"nowy", "nowa", "nowe", "ma", "do", "dla"}
_ASKING = {"jaki", "jaka", "jakie", "podaj", "powiedz", "przeczytaj", "znasz", "masz", "czy"}
_ASK_FILL = _ASKING | _POLITE | {"jest", "ma", "do", "dla"}
_SHOW_VERBS = {"pokaż", "pokaz", "otwórz", "otworz", "wyświetl", "wyswietl", "daj"}
_CARD_WORD = re.compile(r"^(?:kart[aeę]|kontakt\w*|wizytówk\w*|wizytowk\w*)$")
_BOOK = re.compile(r"\bksi[aą][żz]k\w*\s+(?:adresow|telefoniczn)\w*|\bkontakty\b")
_SHOW_FILL = _SHOW_VERBS | _POLITE | {"do", "dla", "dane", "kontaktowe", "kontaktową", "kontaktowa",
                                      "książkę", "książka", "ksiazke", "ksiazka", "adresową", "adresowa",
                                      "telefoniczną", "telefoniczna"}


def _clean(text):
    return _LEAD.sub("", text.strip()).strip(" .!?…")


def _words(s):
    return re.findall(r"\w+", s.lower())


def _person(word):
    import faces
    return faces.match_name(word) or faces.match_role(word)


def _who(words, fill):
    """(a name or None, "my"?, ok): ok only if every word is one that may be here."""
    name, mine = None, False
    for w in words:
        if w in fill:
            continue
        if w in _MINE:
            mine = True
            continue
        hit = _person(w)
        if not hit:
            return None, False, False
        name = name or hit
    return name, mine, True


def _subject(name, mine):
    if name:
        return name
    return viewer() if mine else on_screen()


def _field_of(m):
    return next(k for k in ("email", "phone", "address") if m.group(k))


def _spoken_digits(s):
    """"sześćset dwadzieścia trzy sto" → "623 100"; what is already digits stays."""
    import calc
    out, cur, last = [], None, 0

    def flush():
        nonlocal cur, last
        if cur is not None:
            out.append(str(cur))
        cur, last = None, 0
    for tok in re.findall(r"\+|\d+|[^\W\d_]+", s.lower()):
        if tok == "plus":
            tok = "+"
        if tok == "+" or tok.isdigit():
            flush()
            out.append(tok)
            continue
        if tok == "zero":
            flush()
            out.append("0")
            continue
        n = calc._ONES.get(tok)
        if n is None:
            return s                               # not a number after all
        size = 100 if n >= 100 else 10 if n >= 10 else 1
        if cur is not None and size < last:
            cur += n
        else:
            flush()
            cur = n
        last = size
    flush()
    return " ".join(out).replace("+ ", "+")


def _spoken_email(s):
    """"ola małpa gmail kropka com" → "ola@gmail.com"."""
    s = re.sub(r"\b(?:małpa|malpa|małpka|at)\b", "@", s, flags=re.I)
    s = re.sub(r"\bkropka\b", ".", s, flags=re.I)
    s = re.sub(r"\b(?:myślnik|myslnik|minus)\b", "-", s, flags=re.I)
    s = re.sub(r"\b(?:podkreślnik|podkreslnik)\b", "_", s, flags=re.I)
    return re.sub(r"\s+", "", s)


def _said_value(field, v):
    if field == "phone":
        return v.replace("+", "plus ").replace(" ", ", ").replace("plus,", "plus")
    if field == "email":
        return v.replace("@", " małpa ").replace(".", " kropka ")
    return v


def _set(text, speak):
    if text.rstrip().endswith("?"):
        return False
    t = _clean(text)
    m = _FIELD.search(t.lower())
    if not m:
        return False
    head = _words(t[:m.start()])
    tail = t[m.end():].strip(" ,-")
    sep = _SEP.match(tail)
    if sep:
        who_part, value = sep.group(1), sep.group(2)
    else:                                          # "telefon Mai 600 100 200"
        toks = tail.split()
        i = 0
        while i < len(toks) and _who(_words(toks[i]), _SET_FILL)[2] and _words(toks[i]):
            i += 1
        who_part, value = " ".join(toks[:i]), " ".join(toks[i:])
    value = value.strip(" .,")
    if not value:
        return False
    name, mine, ok = _who(head + _words(who_part), _SET_FILL)
    if not ok:
        return False
    field = _field_of(m)
    told = any(w in _VERBS for w in head)
    if field == "phone":
        value = _spoken_digits(value)
        good = clean_phone(value)
    elif field == "email":
        value = _spoken_email(value)
        good = clean_email(value)
    else:
        good = len(value) >= 3 and (told or re.search(r"\d", value)) and value
    if not good:                                   # "numer domu to 15", "adres jest ważny"
        if told and _subject(name, mine):
            speak(_BAD_VALUE[field])
            return True
        return False
    who = _subject(name, mine)
    if not who:
        if not (told or mine):
            return False
        speak("Nie widzę cię. Stań przede mną albo powiedz, czyje to." if mine
              else "Czyje to? Powiedz na przykład: telefon Mai to sześćset sto dwieście.")
        return True
    said = may_edit(who)
    if said:
        speak(said)
        return True
    said = save(who, field, good)
    if said:
        speak(said + ".")
        return True
    c = card(who)
    show(who, toast="Zapisane")
    speak(f"Zapisałam: {who}, {_LABEL[field].lower()} {_said_value(field, c[field])}.")
    return True


def _delete(text, speak):
    t = _clean(text)
    first = _words(t)[:1]
    if not first or first[0] not in _DELETE:
        return False
    m = _FIELD.search(t.lower())
    if not m:
        return False
    rest = _words(t[:m.start()])[1:] + _words(t[m.end():])
    name, mine, ok = _who(rest, _POLITE | {"do", "dla"})
    who = _subject(name, mine) if ok else None
    if not who:
        return False
    said = may_edit(who)
    if said:
        speak(said)
        return True
    field = _field_of(m)
    old = (card(who) or {}).get(field)
    if not old:
        speak(f"Nie mam zapisanego {_MISSING[field]}: {who}.")
        return True
    save(who, field, "")
    show(who, toast="Usunięte")
    speak(f"Usunęłam: {who}, {_LABEL[field].lower()} {_said_value(field, old)}.")
    return True


def _ask(text, speak):
    t = _clean(text)
    m = _FIELD.search(t.lower())
    if not m:
        return False
    words = _words(t[:m.start()] + " " + t[m.end():])
    name, mine, ok = _who(words, _ASK_FILL)
    if not ok:
        return False
    asked = any(w in _ASKING for w in words) or "do" in words or (name and "ma" not in words)
    if not asked:
        return False
    who = _subject(name, mine)
    if not who:
        if mine:
            speak("Nie widzę cię. Stań przede mną albo powiedz, czyj numer podać.")
            return True
        return False
    if not may_see(who):
        speak(_FAMILY_ONLY)
        return True
    field = _field_of(m)
    v = (card(who) or {}).get(field)
    show(who)
    if not v:
        speak(f"{who} nie ma jeszcze zapisanego {_MISSING[field]}. Możesz go podyktować "
              "albo wpisać na karcie.")
    elif field == "phone":
        speak(f"{who} ma numer {_said_value(field, v)}.")
    elif field == "email":
        speak(f"{who} ma e-mail {_said_value(field, v)}.")
    else:
        speak(f"{who} ma adres: {v}.")
    return True


def _show_card(text, speak):
    t = _clean(text)
    low = t.lower()
    words = _words(low)
    book = bool(_BOOK.search(low))
    cards = [w for w in words if _CARD_WORD.match(w)]
    if not cards and not book:
        return False
    rest = [w for w in words if not _CARD_WORD.match(w)]
    name, mine, ok = _who(rest, _SHOW_FILL)
    if not ok:
        return False
    verb = any(w in _SHOW_VERBS for w in words)
    if not (verb or name or mine or book):         # "karta", "kontakt": could be anything
        return False
    who = name or (viewer() if mine else None)
    if mine and not who:
        speak("Nie widzę cię. Stań przede mną albo powiedz, czyją kartę pokazać.")
        return True
    if who and not may_see(who):
        speak(_FAMILY_ONLY)
        return True
    if not who:                                    # no one named: whoever is at hand
        names = people()
        here = viewer() if viewer() in names else None
        who = on_screen() if on_screen() in names else here or (names[0] if names else None)
        if not who:
            import faces
            speak(_FAMILY_ONLY if faces.names() else "Jeszcze nikogo nie znam.")
            return True
    show(who)
    speak(f"Proszę, karta: {who}.")
    return True


def command(text, speak):
    """A sentence about someone's card. True if it was handled."""
    if not _ANY.search(text) or len(text.split()) > 16:
        return False
    return (_show_card(text, speak) or _delete(text, speak) or _set(text, speak)
            or _ask(text, speak))
