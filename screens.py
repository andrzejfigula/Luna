"""
screens.py — things Luna shows on her whole screen for a moment, on request.

  "pokaż lustro" / "lustro"          → the camera as a mirror, MIRROR_SECS
  "zrób mi zdjęcie" / "zrób fotkę"   → 3-2-1, a flash, the photo saved to
                                       photos/ and shown for a few seconds
  "pokaż zegar" / "pokaż godzinę"    → a big clock with the date, CLOCK_SECS
  "pokaż przypomnienia"              → timers, reminders and alarms, 10 s
  "pokaż listę zakupów"              → a list from lists.py, 12 s
  "pokaż status"                     → temperature, uptime, cloud, API calls
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
_PEOPLE = re.compile(r"^(?:luna,?\s+)?(?:kogo\s+(?:już\s+|juz\s+|wszystkiego\s+)?(?:znasz|pamiętasz|"
                     r"pamietasz|rozpoznajesz)|(?:pokaż|pokaz)\s+(?:mi\s+)?(?:wszystkie\s+)?"
                     r"(?:osoby|ludzi|twarze|znajomych|wszystkich)(?:,?\s+(?:które|ktore|których|"
                     r"ktorych|co|kogo)\s+(?:znasz|pamiętasz|pamietasz|rozpoznajesz))?|"
                     r"(?:pokaż\s+|pokaz\s+|otwórz\s+|otworz\s+)?(?:galeri\w+)\s+(?:osób|osob|twarzy|"
                     r"ludzi|znajomych))\W*$", re.I)
# ("co mamy dzisiaj?" is left alone: it may mean "what day is it")
_TODAY = ("plan dnia", "plan na dziś", "plan na dzisiaj", "co mamy w planie",
          "dzisiejszy plan", "plany na dziś", "plany na dzisiaj",
          # (14 Oct probe: to the model / a photo search)
          "pokaż kalendarz", "pokaz kalendarz", "pokaż mój kalendarz", "co mam dzisiaj w planie",
          "co mam dziś w planie", "co mam w planie")
_SHOW_LIST = ("pokaż listę", "pokaz liste", "pokaż mi listę", "show the list",
              "show my list")
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
           "show the clock", "show me the time")


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


def show_photos(paths, names=None, title="Zdjęcia"):
    """The gallery of these photos (a name under each, if given)."""
    names = names or [""] * len(paths)
    gallery.show([{"path": p, "caption": n, "sub": gallery.when(p), "kind": "photo"}
                  for p, n in zip(paths, names)], title)


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
    n = len(rows)
    speak(f"Oto plan na dziś — {n} {'rzecz' if n == 1 else 'rzeczy'}.")


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
    os.replace(os.path.join(PHOTOS_DIR, name), os.path.join(BIN, name))
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
        name = max(binned, key=lambda f: os.path.getmtime(os.path.join(BIN, f)))
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
    if _PEOPLE.match(low.strip()):
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
    if any(k in low for k in _SHOW_LIST):
        import lists
        name = lists.find(text)
        items = lists.get(name) if name else []
        if not items:
            speak("Ta lista jest pusta." if name else "Nie masz jeszcze żadnej listy.")
        else:
            _show("list", 12, (f"Lista: {name}", [("•", i) for i in items]))
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
