"""
screens.py — things Luna shows on her whole screen for a moment, on request.

  "pokaż lustro" / "lustro"          → the camera as a mirror, MIRROR_SECS
  "zrób mi zdjęcie" / "zrób fotkę"   → 3-2-1, a flash, the photo saved to
                                       photos/ and shown for a few seconds
  "pokaż zegar" / "pokaż godzinę"    → a big clock with the date, CLOCK_SECS
  "pokaż przypomnienia"              → timers, reminders and alarms, 10 s
  "pokaż listę zakupów"              → a list from lists.py, 12 s
  "pokaż status"                     → temperature, uptime, cloud, API calls
  "pokaż ustawienia"                 → the settings page (settings_page.py)
  "pokaż zdjęcia"                    → her photos, newest first, 6 s each
                                       (gallery.py: "następne", "poprzednie",
                                       ‹ › and ✕ on the screen)
  "pokaż pogodę"                     → the weather as pictures (ui_screens.py)

robot_face.py draws the overlay (state.overlay = (kind, until, data)); a tap
on the screen closes it. Photos stay on the Pi (photos/, newest PHOTOS_KEEP
kept) and are never sent anywhere.
"""

import json
import os
import re

import gallery
import intent
import time

from shared_state import state
from config import MIRROR_SECS, CLOCK_SECS, PHOTO_SHOW_SECS, PHOTOS_DIR, PHOTOS_KEEP

_MIRROR = ("lustro", "lusterko", "mirror", "pokaż mnie", "pokaz mnie",
           # 13 Oct probe: "Pokaż mi mnie" went to the model
           "pokaż mi mnie", "pokaz mi mnie", "pokaż nas", "pokaż mi nas")
_PHOTO  = ("zrób mi zdjęcie", "zrób zdjęcie", "zrób nam zdjęcie", "zrób fotkę",
           "zrob mi zdjecie", "zrob zdjecie", "take a photo", "take a picture",
           # (14 Oct probe: "Zrób selfie" went to the model)
           "zrób selfie", "zrob selfie", "zróbmy selfie", "zrobmy selfie", "zrób nam selfie",
           "zróbmy sobie zdjęcie", "zrobmy sobie zdjecie", "take a selfie")
_LIST   = ("pokaż przypomnienia", "pokaż minutniki", "pokaż budziki",
           "pokaz przypomnienia", "pokaż mi przypomnienia", "show my reminders")
_GALLERY = ("pokaż zdjęcia", "pokaż ostatnie zdjęcie", "pokaż moje zdjęcia",
            "pokaż fotki", "pokaz zdjecia", "pokaż zdjęcie", "show my photos",
            "show the photos", "pokaż dzisiejsze zdjęcia", "pokaż wczorajsze zdjęcia",
            "pokaż zdjęcia z dzisiaj", "pokaż zdjęcia z wczoraj",
            # (13 Oct 11:42, Andrzej: "pokaż galerię" → "nie mam dostępu do galerii")
            "pokaż galerię", "pokaz galerie", "pokaż galerie", "otwórz galerię",
            "otworz galerie", "galeria zdjęć", "pokaż swoje zdjęcia")
# the people she knows, with their faces (gallery.py; the bin forgets one)
# (19 Oct 20:00–20:08: "kogoś kogo znasz" (Vosk), "Pokaż, kogo znasz.", "Pokaż
# profile ludzi, których znasz." all went to the model — 4 tries; matched on
# text without punctuation, see _people_asked)
_KNOWN = r"(?:już\s+|juz\s+|wszystkiego\s+)?(?:znasz|pamiętasz|pamietasz|rozpoznajesz)"
_PEOPLE = re.compile(
    r"^(?:luna\s+)?(?:"
    r"(?:(?:pokaż|pokaz)\s+(?:mi\s+|nam\s+)?)?kogo(?:ś\s+kogo|s\s+kogo)?\s+" + _KNOWN +
    r"|(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+|nam\s+)?(?:wszystkie\s+|swoje\s+)?"
    r"(?:(?:profile|profil|portrety|zdjęcia|zdjecia|twarze|galeri\w*)\s+)?"
    r"(?:osoby|osób|osob|ludzi|twarze|twarzy|znajomych|wszystkich|profile|profil\w*|portrety)"
    r"(?:\s+(?:które|ktore|których|ktorych|co|kogo|jakich|jakie)\s+" + _KNOWN + r")?"
    r"|galeri\w+\s+(?:osób|osob|twarzy|ludzi|znajomych)"
    r")$", re.I)


# "pokaż ustawienia" — the settings page with its tabs (settings_page.py)
_SETTINGS = re.compile(
    r"^(?:luna\s+)?(?:(?:pokaż|pokaz|otwórz|otworz|włącz|wlacz|show|open)\s+(?:mi\s+|nam\s+|the\s+)?)?"
    r"(?:ustawienia|ustawień|ustawien|panel\s+ustawień|menu\s+ustawień|swoje\s+ustawienia|settings)$",
    re.I)


def _people_asked(low):
    return bool(_PEOPLE.match(" ".join(re.findall(r"[\w-]+", low))))
# ("co mamy dzisiaj?" is left alone: it may mean "what day is it")
_TODAY = ("plan dnia", "plan na dziś", "plan na dzisiaj", "co mamy w planie",
          "dzisiejszy plan", "plany na dziś", "plany na dzisiaj",
          # (14 Oct probe: to the model / a photo search)
          "pokaż kalendarz", "pokaz kalendarz", "pokaż mój kalendarz", "co mam dzisiaj w planie",
          "co mam dziś w planie", "co mam w planie",
          # (proposal 4, 17 Oct: a spoken briefing, not only "Oto plan — 5 rzeczy")
          "co mnie dziś czeka", "co mnie dzisiaj czeka", "co nas dziś czeka",
          "co nas dzisiaj czeka", "jaki mam plan na dziś", "jaki mam plan na dzisiaj",
          "co dziś w planie", "co dzisiaj w planie", "jaki jest plan na dziś")
# (22 Oct: "Pokaż tą listę jeszcze raz." went to the model — with the camera:
# "…jest pusta. Andzeju, to Ty.")
_SHOW_LIST = re.compile(r"\b(?:pokaż|pokaz|wyświetl|wyswietl)\s+(?:mi\s+|nam\s+)?(?:jeszcze\s+raz\s+)?"
                        r"(?:tę\s+|te\s+|tą\s+|ta\s+|moją\s+|moja\s+|naszą\s+|nasza\s+)?"
                        r"(?:listę|liste)\b|\bshow\s+(?:the|my)\s+list")
_last_list = [None]                     # the list shown last ("pokaż tę listę")
# "Pokaż, co mamy dzisiaj zrobić." — the to-do list
_SHOW_TODO = re.compile(r"^(?:luna,?\s+)?(?:pokaż|pokaz)\s+(?:mi\s+)?,?\s*co\s+(?:mamy|mam)\s+"
                        r"(?:dzisiaj\s+|dziś\s+|dzis\s+|jeszcze\s+)?(?:do\s+)?(?:zrobić|zrobic|zrobienia)\W*$")
# "pokaż pogodę" — the days of the forecast (14 Oct probe: "pokaż prognozę"
# looked for a photo; "pokaż pogodę" went to the model)
_WEATHER = re.compile(r"^(?:luna,?\s+)?(?:pokaż|pokaz)\s+(?:mi\s+)?(?:pogodę|pogode|prognozę|"
                      r"prognoze|prognozę\s+pogody|pogodę\s+na\s+(?:tydzień|tydzien|"
                      r"weekend|jutro))\W*$")
_STATUS = ("pokaż status", "pokaz status", "status systemu", "jaki masz status",
           "show status", "show your status",
           # 13 Oct 22:17: "pokaż statystyki" — a photo search, then a drawing
           "pokaż statystyki", "pokaz statystyki", "pokaż swoje statystyki",
           "pokaż mi statystyki", "pokaż diagnostykę", "pokaż diagnostyke")
_CLOCK  = ("pokaż zegar", "pokaż godzinę", "pokaz zegar", "pokaz godzine",
           "show the clock", "show me the time",
           "włącz zegar", "wlacz zegar")           # (23 Oct 12:44: to the model)


def _show(kind, secs, data=None):
    if kind == "list" and data and len(data[1]) > 7:   # paged: long enough for all
        secs = max(secs, 6 * -(-len(data[1]) // 7) + 2)
    with state.lock:
        state.overlay = (kind, time.time() + secs, data)


def close():
    with state.lock:
        state.overlay = None


def _take_photo(speak, play_sound_async):
    import cv2
    speak("Uśmiech! Patrz w kamerę.")
    for n in ("3", "2", "1"):
        with state.lock:
            state.big_text = (n, time.time() + 0.75)
        play_sound_async("tick")
        time.sleep(0.75)
    with state.lock:
        frame = state.frame
    _show("flash", 0.25)
    if frame is None:
        speak("Ojej, nie widzę nic przez kamerę.")
        return
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    path = os.path.join(PHOTOS_DIR, time.strftime("%Y%m%d-%H%M%S") + ".jpg")
    cv2.imwrite(path, cv2.flip(frame, 1), [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    print(f"[screens] photo saved: {path}", flush=True)
    names = _tag(path)
    shots = sorted(f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg"))
    for old in shots[:-PHOTOS_KEEP]:
        try:
            os.remove(os.path.join(PHOTOS_DIR, old))
        except OSError:
            pass
    time.sleep(0.25)
    # in the gallery, standing: "poprzednie" goes back to the older ones
    shots = sorted((f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg")), reverse=True)
    gallery.show(_items(shots, _tags()), "Zdjęcia", auto=False, secs=PHOTO_SHOW_SECS)
    with state.lock:
        state.emotion = "Happy"
    speak("Pięknie wyszło!" + (f" {_and(names)} na zdjęciu." if names else ""))
    with state.lock:
        state.emotion = "Neutral"


_TAGS = os.path.join(PHOTOS_DIR, "people.json")


def _tags():
    try:
        with open(_TAGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _tag(path):
    """Who is in the photo just taken (faces.py), kept in photos/people.json."""
    try:
        import cv2
        import faces
        names = faces.who_in(cv2.imread(path))
    except Exception as e:
        print(f"[screens] who is in the photo: {e}", flush=True)
        return []
    tags = _tags()
    tags[os.path.basename(path)] = names
    keep = set(os.listdir(PHOTOS_DIR))
    tags = {f: n for f, n in tags.items() if f in keep}
    with open(_TAGS, "w", encoding="utf-8") as f:
        json.dump(tags, f, ensure_ascii=False)
    if names:
        print(f"[screens] in the photo: {', '.join(names)}", flush=True)
    return names


def photos_of(name):
    """Her own photos with `name` in them ("zrób nam zdjęcie"), newest first."""
    if not os.path.isdir(PHOTOS_DIR):
        return []
    tags = _tags()
    shots = sorted((f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg")), reverse=True)
    return [os.path.join(PHOTOS_DIR, f) for f in shots if name in tags.get(f, [])]


def _items(shots, tags):
    """Photo files (newest first) → the gallery's items: who is on it, when."""
    return [{"path": os.path.join(PHOTOS_DIR, f),
             "caption": _and(tags[f]) if tags.get(f) else "",
             "sub": gallery.when(f), "kind": "photo"} for f in shots]


def people_items(now=None):
    """The people she knows for the gallery: a portrait (faces.py), else
    their newest photo, else none (ui_screens draws the first letter)."""
    import faces
    notes, out = faces.notes(), []
    for name in faces.names():
        # their portrait — else their face cut from a photo of hers, else the
        # first letter (never a whole photo: its middle may be someone else)
        pic = faces.portrait(name) or faces.portrait_from_photos(name, photos_of(name))
        seen = faces.last_seen(name)
        sub = [notes.get(name, "").split("—")[0].strip(" ,")]
        if seen:
            lt = time.localtime(seen)
            sub.append("widziałam " + gallery.day_word(lt.tm_year, lt.tm_mon, lt.tm_mday, now)
                       + (f", {lt.tm_hour}:{lt.tm_min:02d}"
                          if now is None or now - seen < 2 * 86400 else ""))
        out.append({"path": pic, "caption": name, "sub": " · ".join(x for x in sub if x),
                    "kind": "person", "name": name, "round": True})
    return out


def show_people(speak):
    items = people_items()
    if not items:
        speak("Jeszcze nikogo nie znam. Powiedz: zapamiętaj mnie, jestem… i swoje imię.")
        return True
    import calc
    gallery.show(items, "Kogo znam", auto=False, secs=60)
    n = len(items)
    speak(f"Znam {n} {calc._plural(n, 'osobę', 'osoby', 'osób')}: "
          f"{_and([i['name'] for i in items])}.")
    return True


# ── touches on her pages (robot_face) ─────────────────────────────────────────

LIST_CONFIRM = 4.0          # a list item tapped again within this: crossed off
LIST_CONFIRM_MIN = 0.7      # …but not sooner: 16 Oct 13:57 the to-do list's only
                            # item went at once (a double tap to close the page?)


def list_tap(nx, ny, now=None):
    """A tap on a list page. On an item: "Usunąć?" first, then it is crossed
    off. Returns "confirm" | "removed" | "emptied" | None (not on an item —
    the caller closes the page, as a tap always did)."""
    import ui_screens
    import lists
    now = now if now is not None else time.time()
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "list" or len(ov[2]) < 3:
            return None
        heading, rows, meta = ov[2]
        page = meta.get("page")
        if page is None:
            page = ui_screens.list_page(rows, now)
        k = ui_screens.list_row_at(nx, ny, rows, page)
        if k is None:
            return None
        meta["page"] = page                     # it stops turning while you tap
        state.overlay = (ov[0], max(ov[1], now + 15), ov[2])
        conf = meta.get("confirm")
        if conf and conf[0] == k and now - conf[1] < LIST_CONFIRM_MIN:
            return "confirm"                    # one tap that bounced, or a double tap
        if not conf or conf[0] != k or now - conf[1] > LIST_CONFIRM:
            meta["confirm"] = (k, now)
            print(f"[lists] tapped {rows[k][1]!r} — asking first", flush=True)
            return "confirm"
        meta["confirm"] = None
        item = rows[k][1]
    if not lists.remove_exact(meta["list"], item):
        return None
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "list" or ov[2][2] is not meta:
            return "removed"
        rows = [r for r in rows if r[1] != item]
        if not rows:
            state.overlay = None
            return "emptied"
        meta["page"] = min(meta["page"], (len(rows) - 1) // ui_screens.LIST_PAGE)
        meta["toast"] = (f"Skreślone: {item} · „przywróć listę”", now + 3.0)
        state.overlay = (ov[0], ov[1], (heading, rows, meta))
    return "removed"


def end_game_page(kind):
    """The ✕ on a game's page ends the game, not only its picture: noughts
    and crosses, memo, a quiz's card / clock / flag, twenty questions."""
    import importlib
    ended = []
    if kind in ("ttt", "memo"):
        importlib.import_module("tictac" if kind == "ttt" else "memo").stop()
        ended.append(kind)
    if kind == "story":                            # a story (or its replay): over
        if importlib.import_module("story").stop():
            ended.append("story")
    if kind in ("card", "clockface", "photo", "stars"):
        for name in ("quiz", "twenty"):
            mod = importlib.import_module(name)
            if mod.active() and mod.stop():
                ended.append(name)
    with state.lock:
        state.overlay = None
    if ended:
        print(f"[screens] ✕ on the {kind} page — ended: {', '.join(ended)}", flush=True)
    return ended


def show_photos(paths, names=None, title="Zdjęcia"):
    """The gallery of these photos (a name under each, if given)."""
    names = names or [""] * len(paths)
    gallery.show([{"path": p, "caption": n, "sub": gallery.when(p), "kind": "photo"}
                  for p, n in zip(paths, names)], title)


def show_all_photos():
    """Every photo, newest first (the dock's icon). False: there are none."""
    shots = _shots()[::-1]
    if shots:
        gallery.show(_items(shots, _tags()), "Zdjęcia")
    return bool(shots)


def _and(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " i " + names[-1]


def _person_in(low):
    """"pokaż zdjęcia Mai" → "Maja" (a known person), else None."""
    try:
        import faces
        known = faces.names()
    except Exception:
        return None
    m = re.search(r"zdję\w*\s+(?:z\s+)?(\w+)", low)
    if not m or not known:
        return None
    word = m.group(1)
    hit = faces.match_name(word, known)   # "Andrzeja", "Emilki", "Mai"
    if hit:
        return hit
    if word in ("mi", "moje", "mnie", "nas", "nasze", "ostatnie", "wszystkie"):
        return None
    nom = faces.nominative(word)          # "Mai" → "Maja"
    return next((n for n in known if n.lower() == nom.lower()), None)


def _child_here():
    """A child in front of her: the week's report is for the grown-ups."""
    try:
        import brain
        with state.lock:
            who = state.person[0] if state.person else None
        return bool(who) and brain._is_child(who)
    except Exception:
        return False


def wants_today(text):
    low = text.lower()
    return any(k in low for k in _TODAY) and len(re.findall(r"\w+", low)) <= 8


def show_today(speak):
    rows = today_rows()
    if not rows:                        # asked to show it: the screen says so too
        _show("list", 10, ("Plan na dziś", [("—", "nic zapisanego")]))
        speak("Na dziś nic nie mam zapisanego — żadnych przypomnień ani spraw.")
        return
    _show("list", 20, ("Plan na dziś", rows))
    speak(today_said(rows))


def today_said(rows):
    """The plan in a few spoken sentences — the next reminders, birthdays,
    the weather and the to-do list; the screen shows the rest. ("Oto plan na
    dziś — 5 rzeczy" told nothing to someone across the room.)"""
    timed = [(l, r) for l, r in rows if re.match(r"\d{1,2}:\d{2}$", l)]
    said = []
    if timed:
        said.append("O " + ", o ".join(f"{l} {r}".strip() for l, r in timed[:2]) + ".")
    for when, label in (("zaległe", "Zaległe"), ("dziś", "Dziś trzeba"), ("jutro", "Jutro")):
        items = [re.sub(r"\s*\(\d{1,2} \w+\)$", "", r) for l, r in rows if l == when]
        if items:
            said.append(f"{label}: {', '.join(items[:3])}.")
    said += [f"{r[:1].upper()}{r[1:]} — {l}." for l, r in rows
             if r.startswith(("urodziny", "imieniny"))][:2]
    said += [f"Do przekazania: {r}." for l, r in rows
             if l in ("przekazać",) or l.startswith("po ")][:1]
    todo = next((r for l, r in rows if l == "lista" and r.startswith("do zrobienia:")), None)
    if todo:
        n = int(todo.rsplit(":", 1)[1])
        said.append(f"Na liście do zrobienia: {n} "
                    f"{'sprawa' if n == 1 else 'sprawy' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'spraw'}.")
    wx = next((r for l, r in rows if l == "pogoda"), None)
    try:                       # the row is cut to fit the screen: the whole day here
        import weather
        if wx:
            wx = weather._summary.split("Today:")[-1].split(";")[0].strip()
    except Exception:
        pass
    if wx:                     # "pochmurno, 8–14°C, rain chance 60%" → words
        wx = re.sub(r"(-?\d+)–(-?\d+)°C", r"od \1 do \2 stopni", wx)
        wx = re.sub(r",?\s*rain chance (\d+)%?", r", szansa deszczu \1 procent", wx)
        said.append(f"Pogoda: {wx.rstrip(', ')}.")
        if len(said) == 1:
            # only the weather: "Na dziś: Pogoda: deszcz…" (22 Oct: "Czemu
            # pogoda jest w kalendarzu?") — say the plan is empty first
            return "Na dziś nic nie ma w planie. " + said[0]
    if not said:
        n = len(rows)
        return f"Oto plan na dziś — {n} {'rzecz' if n == 1 else 'rzeczy'}."
    return "Na dziś: " + " ".join(said)


def today_rows():
    """"Plan na dziś": today's timers and reminders, notes waiting to be
    passed on, birthdays this week, the weather, the lists — (left, right) rows."""
    import time as _t
    rows = []
    try:
        import timers
        with timers._lock:
            items = list(timers._timers)
        end = _t.mktime(_t.localtime()[:3] + (23, 59, 59, 0, 0, -1))
        for e in sorted(items, key=lambda e: e["due"]):
            if e["due"] <= end:
                what = e["label"] or timers._KIND_PL.get(e["kind"], "")
                rows.append((_t.strftime("%H:%M", _t.localtime(e["due"])), what))
    except Exception:
        pass
    try:
        import schedule                        # the week's plan: today's entries
        rows += schedule.today_rows()
    except Exception:
        pass
    try:
        import errands
        with errands._lock:
            notes = errands._load()
        for e in notes:
            if errands._due(e) or e.get("at"):
                when = f"po {e['at']}" if e.get("at") else "przekazać"
                rows.append((when, f"{e['to']}: {e['words']}"))
    except Exception:
        pass
    try:
        import birthdays
        from datetime import datetime
        today = datetime.now().date()
        for name, (md, born) in birthdays._all().items():
            days = (birthdays._next(md, today) - today).days
            if days == 0:
                rows.append(("dziś!", f"urodziny: {name}"))
            elif days <= 7:
                rows.append((f"za {days} dni", f"urodziny: {name}"))
        for name, md in birthdays.namedays().items():
            if birthdays._next(md, today) == today:
                rows.append(("dziś!", f"imieniny: {name}"))
    except Exception:
        pass
    try:
        import weather
        if weather.enabled() and weather._summary:
            s = weather._summary.split("Today:")[-1].split(";")[0].strip()
            rows.append(("pogoda", s[:40]))
    except Exception:
        pass
    try:
        import lists
        rows += lists.due_rows()               # to-dos for today, tomorrow, overdue
        for name, items in lists.get().items():
            rows.append(("lista", f"{name}: {len(items)}"))
    except Exception:
        pass
    return rows[:14]                   # two pages on her screen


# her photos by voice (14 Oct probe: "Usuń ostatnie zdjęcie", "Ile masz zdjęć?"
# went to the model, which can't do either). Deleting moves it to a bin —
# "przywróć zdjęcie" brings it back; nothing is lost by a misheard word.
_PHOTO_COUNT = re.compile(r"^(?:luna,?\s+)?ile\s+(?:masz|mamy|jest)\s+(?:już\s+)?(?:zdjęć|zdjec|"
                          r"fotek|fotografii)\W*$")
_PHOTO_DELETE = re.compile(r"^(?:luna,?\s+)?(?:usuń|usun|skasuj|wyrzuć|wyrzuc|wykasuj)\s+"
                           r"(?:to|ostatnie|tamto|te)\s+(?:zdjęcie|zdjecie|fotkę|fotke)\W*$")
_PHOTO_RESTORE = re.compile(r"^(?:luna,?\s+)?(?:przywróć|przywroc|odzyskaj)\s+(?:to\s+|ostatnie\s+)?"
                            r"(?:zdjęcie|zdjecie|fotkę|fotke)\W*$")
BIN = os.path.join(PHOTOS_DIR, "kosz")


def _shots():
    try:
        return sorted(f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg"))
    except OSError:
        return []


def bin_photo(item):
    """A photo into the bin (gallery.py's bin button, "usuń to zdjęcie")."""
    path = item["path"] if isinstance(item, dict) else item
    name = os.path.basename(path)
    if name not in _shots():
        return False
    os.makedirs(BIN, exist_ok=True)
    # a rename keeps the mtime (when it was taken): stamp the binning, later than
    # anything already there, so "przywróć zdjęcie" brings back the last one
    newest = max((os.stat(os.path.join(BIN, f)).st_mtime_ns for f in os.listdir(BIN)), default=0)
    dst = os.path.join(BIN, name)
    os.replace(os.path.join(PHOTOS_DIR, name), dst)
    t = max(time.time_ns(), newest + 1000)
    os.utime(dst, ns=(t, t))
    print(f"[screens] photo {name} moved to the bin", flush=True)
    return True


def photo_command(low, speak):
    """"Ile masz zdjęć?", "Usuń to / ostatnie zdjęcie", "Przywróć zdjęcie"."""
    import calc
    low = low.strip()
    if _PHOTO_COUNT.match(low):
        n = len(_shots())
        speak("Nie mam jeszcze żadnych zdjęć. Powiedz: zrób zdjęcie." if not n else
              f"Mam {n} {calc._plural(n, 'zdjęcie', 'zdjęcia', 'zdjęć')}. "
              "Powiedz: pokaż zdjęcia.")
        return True
    if _PHOTO_DELETE.match(low):
        cur = gallery.current()              # the one on the screen, if any
        shown = cur["path"] if cur and os.path.dirname(cur["path"]) == PHOTOS_DIR else None
        shots = _shots()
        name = os.path.basename(shown) if shown else (shots[-1] if shots else None)
        if not name or name not in shots:
            speak("Nie mam żadnego zdjęcia do usunięcia.")
            return True
        bin_photo(os.path.join(PHOTOS_DIR, name))
        with state.lock:
            if state.overlay and state.overlay[0] in ("photo", "gallery"):
                state.overlay = None
        speak("Dobrze, usunęłam to zdjęcie. Gdyby co — powiedz: przywróć zdjęcie.")
        return True
    if _PHOTO_RESTORE.match(low):
        try:
            binned = sorted(f for f in os.listdir(BIN) if f.endswith(".jpg"))
        except OSError:
            binned = []
        if not binned:
            speak("Nie mam czego przywrócić.")
            return True
        name = max(binned, key=lambda f: os.stat(os.path.join(BIN, f)).st_mtime_ns)
        os.replace(os.path.join(BIN, name), os.path.join(PHOTOS_DIR, name))
        print(f"[screens] photo {name} back from the bin", flush=True)
        _show("photo", PHOTO_SHOW_SECS, os.path.join(PHOTOS_DIR, name))
        speak("Proszę, wróciło.")
        return True
    return False


def handle(text, speak, play_sound_async):
    """A screen request? Show it and return True."""
    low = text.lower().replace("pokazać", "pokaż").replace("pokazac", "pokaz")
    if len(re.findall(r"\w+", low)) > 7:
        return False
    if photo_command(low.strip(" .!?"), speak):
        return True
    if any(k in low for k in _PHOTO):
        _take_photo(speak, play_sound_async)
        return True
    if any(k in low for k in _MIRROR) and intent.asked(low, 2):
        _show("mirror", MIRROR_SECS)
        speak("Proszę bardzo, oto lusterko.")
        return True
    if any(k in low for k in _LIST):
        import timers
        lines = timers.screen_lines()
        if not lines:
            speak("Nie masz teraz żadnych minutników ani przypomnień.")
        else:
            _show("list", 10, ("Przypomnienia", lines))
        return True
    if _people_asked(low):
        return show_people(speak)
    if any(k in low for k in _GALLERY):
        shots = sorted((f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg")),
                       reverse=True) if os.path.isdir(PHOTOS_DIR) else []
        tags = _tags()
        who = _person_in(low)
        if who:                               # "pokaż zdjęcia Mai"
            shots = [f for f in shots if who in tags.get(f, [])]
        day = None                            # "dzisiejsze" / "z wczoraj"
        if re.search(r"dzisiejsz|z dzisiaj|z dziś", low):
            day = time.strftime("%Y%m%d")
        elif re.search(r"wczorajsz|z wczoraj", low):
            day = time.strftime("%Y%m%d", time.localtime(time.time() - 86400))
        if day:
            shots = [f for f in shots if f.startswith(day)]
        if not shots:
            speak(f"Nie mam zdjęć, na których jest {who}." if who else
                  "Nie mam zdjęć z tego dnia." if day else
                  "Nie mam jeszcze żadnych zdjęć. Powiedz: zrób mi zdjęcie!")
        else:
            gallery.show(_items(shots, tags),
                         f"Zdjęcia: {who}" if who else
                         "Dzisiejsze zdjęcia" if day == time.strftime("%Y%m%d") else
                         "Wczorajsze zdjęcia" if day else "Zdjęcia")
        return True
    todo = _SHOW_TODO.match(low.replace(",", " ").replace("  ", " "))
    if todo or _SHOW_LIST.search(low):
        import lists
        name = "do zrobienia" if todo else lists.find(text)
        if (_last_list[0] and re.search(r"\b(?:tę|tą|te|ta)\s+list|jeszcze\s+raz", low)
                and not re.search(r"zakup|zrobi|zada", low)
                and not any(k in low for k in lists.get())):
            name = _last_list[0]               # "pokaż tą listę jeszcze raz" — that one
        items = lists.get(name) if name else []
        if not items:
            speak(lists.empty_answer(name))
        else:
            _last_list[0] = name
            # {"list"}: a tap on an item crosses it off (list_tap)
            _show("list", 12, (f"Lista: {name}", [("•", i) for i in items], {"list": name}))
        return True
    import weekly
    if weekly.wanted(low) and not _child_here():
        said, rows = weekly.report()
        _show("list", 25, ("Mój tydzień", rows or [("—", "jeszcze nic")]))
        speak(said)
        return True
    words = " ".join(re.findall(r"[\w-]+", low))
    if _SETTINGS.match(words) or (len(words.split()) <= 9 and re.search(
            # (22 Oct: "Hej włącz ustawienia.", "Nie, włącz ustawienia, masz taką
            # komendę." — the model: "nie mam takiej komendy", twice)
            r"\b(?:pokaż|pokaz|otwórz|otworz|włącz|wlacz)\s+(?:mi\s+)?ustawienia\b", words)):
        import settings_page
        _show("settings", settings_page.PAGE_SECS, {"tab": 0})
        speak("Proszę, oto ustawienia.")
        return True
    if any(k in low for k in _STATUS):
        import health
        _show("list", 15, ("Status", health.status_rows()))
        return True
    if _WEATHER.match(low.strip()):
        import weather
        rows = weather.forecast_rows()
        pics = weather.screen_days()
        if not rows:
            speak("Nie mam teraz prognozy pogody.")
        else:
            if pics and pics.get("days"):     # pictures: now, the hours, the week
                pics["t0"] = time.time()
                _show("weather", 25, pics)
            else:
                _show("list", 20, ("Pogoda", rows))
            speak(f"Dziś {rows[0][1].split(',')[0]}, "
                  f"{rows[0][1].split(',')[1].strip().replace('–', ' do ').replace('°C', ' stopni')}.")
        return True
    if any(k in low for k in _CLOCK):
        # "pokaż zegar przez minutę / na 5 minut" — that long (14 Oct probe:
        # always 10 s); up to an hour, the night-clock is something else
        import timers
        secs, _ = timers.parse_duration(low) if re.search(r"\b(?:przez|na)\b", low) else (0, None)
        _show("clock", min(secs, 3600) if secs else CLOCK_SECS)
        return True
    return False
