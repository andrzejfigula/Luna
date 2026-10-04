"""
screens.py — things Luna shows on her whole screen for a moment, on request.

  "pokaż lustro" / "lustro"          → the camera as a mirror, MIRROR_SECS
  "zrób mi zdjęcie" / "zrób fotkę"   → 3-2-1, a flash, the photo saved to
                                       photos/ and shown for a few seconds
  "pokaż zegar" / "pokaż godzinę"    → a big clock with the date, CLOCK_SECS
  "pokaż przypomnienia"              → timers, reminders and alarms, 10 s
  "pokaż listę zakupów"              → a list from lists.py, 12 s
  "pokaż zdjęcia"                    → her photos, newest first, 6 s each;
                                       a tap shows the next one

robot_face.py draws the overlay (state.overlay = (kind, until, data)); a tap
on the screen closes it. Photos stay on the Pi (photos/, newest PHOTOS_KEEP
kept) and are never sent anywhere.
"""

import os
import re
import time

from shared_state import state
from config import MIRROR_SECS, CLOCK_SECS, PHOTO_SHOW_SECS, PHOTOS_DIR, PHOTOS_KEEP

_MIRROR = ("lustro", "lusterko", "mirror", "pokaż mnie", "pokaz mnie")
_PHOTO  = ("zrób mi zdjęcie", "zrób zdjęcie", "zrób nam zdjęcie", "zrób fotkę",
           "zrob mi zdjecie", "zrob zdjecie", "take a photo", "take a picture")
_LIST   = ("pokaż przypomnienia", "pokaż minutniki", "pokaż budziki",
           "pokaz przypomnienia", "pokaż mi przypomnienia", "show my reminders")
_GALLERY = ("pokaż zdjęcia", "pokaż ostatnie zdjęcie", "pokaż moje zdjęcia",
            "pokaż fotki", "pokaz zdjecia", "pokaż zdjęcie", "show my photos",
            "show the photos")
GALLERY_STEP = 6.0          # seconds per photo; a tap shows the next one
_SHOW_LIST = ("pokaż listę", "pokaz liste", "pokaż mi listę", "show the list",
              "show my list")
_CLOCK  = ("pokaż zegar", "pokaż godzinę", "pokaz zegar", "pokaz godzine",
           "show the clock", "show me the time")


def _show(kind, secs, data=None):
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
    shots = sorted(f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg"))
    for old in shots[:-PHOTOS_KEEP]:
        try:
            os.remove(os.path.join(PHOTOS_DIR, old))
        except OSError:
            pass
    time.sleep(0.25)
    _show("photo", PHOTO_SHOW_SECS, path)
    with state.lock:
        state.emotion = "Happy"
    speak("Pięknie wyszło!")
    with state.lock:
        state.emotion = "Neutral"


def handle(text, speak, play_sound_async):
    """A screen request? Show it and return True."""
    low = text.lower()
    if len(re.findall(r"\w+", low)) > 7:
        return False
    if any(k in low for k in _PHOTO):
        _take_photo(speak, play_sound_async)
        return True
    if any(k in low for k in _MIRROR):
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
    if any(k in low for k in _GALLERY):
        shots = sorted((f for f in os.listdir(PHOTOS_DIR) if f.endswith(".jpg")),
                       reverse=True) if os.path.isdir(PHOTOS_DIR) else []
        if not shots:
            speak("Nie mam jeszcze żadnych zdjęć. Powiedz: zrób mi zdjęcie!")
        else:
            paths = [os.path.join(PHOTOS_DIR, f) for f in shots]
            _show("gallery", len(paths) * GALLERY_STEP + 1,
                  {"paths": paths, "i": 0, "next": time.time() + GALLERY_STEP})
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
    if any(k in low for k in _CLOCK):
        _show("clock", CLOCK_SECS)
        return True
    return False
