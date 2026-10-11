"""
drawing.py — "Luna, narysuj mi jednorożca": a real picture on her screen.

  "narysuj mi kotka na rowerze" / "namaluj smoka" / "draw me a dinosaur"
        → "Już rysuję… chwilka!", ~10 s later the picture, big, for 40 s
  "pokaż rysunki" / "pokaż jeszcze raz rysunek" → the last ones again
  "narysuj mnie / nas / to, co widzisz" → the camera frame, redrawn (11 Oct)

The picture comes from OpenAI's image model (gpt-image-1-mini, low quality —
about a cent each), always in a cheerful children's-book style, never anything
scary; a request the model refuses gets "Tego nie narysuję…". At most one
drawing every DRAW_GAP seconds and DRAW_PER_DAY a day, so a game of "narysuj
jeszcze!" can't run up a bill. Kept in DATA_DIR/drawings (the newest KEEP).
(8 Oct: she had only cat / dog / bunny ears to offer for "narysuj mi kotka".)
"""

import base64
import json
import os
import random
import re
import threading
import time

from config import DATA_DIR
from shared_state import state

DIR = os.path.join(DATA_DIR, "drawings")
KEEP = 30
DRAW_GAP = 20
DRAW_PER_DAY = 25
SHOW_SECS = 40
MODEL = "gpt-image-1-mini"

_ASK = re.compile(r"^(?:luna,?\s+)?(?:(?:czy\s+)?(?:możesz|mozesz|mogłabyś|moglabys)\s+)?"
                  r"(?:(?:mi|nam)\s+)?"
                  r"(?:narysuj|narysujesz|narysować|narysowac|namaluj|namalujesz|namalować|"
                  r"namalowac|draw)"
                  r",?(?:\s+(?:mi|nam|me),?)?(?:\s+(?:a|an))?\s+(.{2,200}?)[.!?]*$", re.I)
_SHOW = re.compile(r"\b(?:pokaż|pokaz)\s+(?:mi\s+)?(?:jeszcze\s+raz\s+)?(?:te\s+|moje\s+|swoje\s+)?"
                   r"(?:rysun\w*|obraz\w*)\b", re.I)
_lock = threading.Lock()
_last = [0.0]
_last_what = [""]              # "narysuj jeszcze raz" — what it was
_last_cam = [False]            # … and whether it was the camera's picture


def wants(text):
    """The thing to draw, or None. "Jeszcze raz mnie narysuj" (verb last) and
    "narysuj mnie jeszcze raz" too — 10 Oct 20:36: the first went to the
    model, which said "rysuję jeszcze raz" and nothing was drawn."""
    t = (text or "").strip()
    last = re.match(r"^(?:luna,?\s+)?(?:(?:jeszcze\s+raz|znowu|ponownie)\s+)?"
                    r"((?:\w+\s+){0,3}?\w+)\s+(?:narysuj|namaluj)\W*$", t, re.I)
    if last:
        t = f"narysuj {last.group(1)}"
    m = _ASK.match(t)
    if not m:
        return None
    what = m.group(1).strip()
    bare = re.sub(r"\s+(?:jeszcze\s+raz|znowu|ponownie|jeszcze\s+jeden\s+raz)\W*$", "", what,
                  flags=re.I)
    # "narysuj mnie ze zdjęcia" — the photo part is how, not what (handle()
    # takes the camera frame for it)
    bare = re.sub(r",?\s+(?:ze\s+zdjęcia|ze\s+zdjecia|z\s+kamery|z\s+obrazu\s+z\s+kamery|"
                  r"tak\s*,?\s+jak\s+wyglądam|jak\s+wyglądam)\W*$", "", bare or what, flags=re.I)
    return bare or what


# what the camera sees, asked for in so many words ("ze zdjęcia", "to, co
# widzisz", "zrób nam zdjęcie") — or a portrait of whoever is in front of her
_FROM_CAM = re.compile(r"\bze?\s+zdj\w*|\bz\s+kamery|\bz\s+obrazu|\bco\s+(?:teraz\s+)?widzisz|"
                       r"\bjak\s+wyglądam|\bjak\s+wygladam|\bzrób\s+(?:nam\s+|mi\s+)?zdjęcie|"
                       r"\bfrom\s+the\s+(?:camera|photo)|\bwhat\s+you\s+see", re.I)
_IN_FRONT = re.compile(r"(?:mnie|nas)\b|(?:nas\s+)?wszystkich\b|(?:naszą|nasza|całą|cala)?\s*rodzin", re.I)


def _camera_jpeg():
    """The camera's newest frame as JPEG bytes, or None (no camera, or it is
    switched off for privacy)."""
    with state.lock:
        frame, ok = state.frame, state.camera_ok
        off = time.time() < getattr(state, "camera_off_until", 0.0)
    if frame is None or not ok or off:
        return None
    try:
        import cv2
        good, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return buf.tobytes() if good else None
    except Exception:
        return None


def _details(what):
    """"mnie: okulary, broda" → "okulary, broda" (what to add to a photo)."""
    m = re.search(r"[:—–]\s*(.{3,})$", what or "")
    return m.group(1).strip() if m else ""


def _subject(what):
    """"mnie", "siebie", "naszą rodzinę" — words for a picture drawn without
    the camera (it is off, or the person isn't in front of her)."""
    low = what.lower().strip()
    det = re.match(r"(mnie|mnie samą|mnie samego)\s*[:,—–-]\s*(.{3,})$", low)
    if det:                    # "mnie: krótkie włosy, okulary" — details they gave
        return f"{_subject(det.group(1))}, {det.group(2)}"
    if re.fullmatch(r"siebie|się|sama siebie|ciebie|lunę|lune|(?:,\s*)?jak\s+wyglądasz|"
                    r"(?:,\s*)?jak\s+wygladasz|yourself", low):
        return ("małego, uroczego robota biurkowego z ekranem zamiast twarzy, dwoma "
                "dużymi świecącymi bursztynowymi oczami, stojącego na biurku pod "
                "rozgwieżdżonym niebem")
    if re.fullmatch(r"(?:naszą|nasza|całą|cala)?\s*rodzin\w*|nas(?:\s+wszystkich)?", low):
        return "szczęśliwą rodzinę: mamę, tatę i ośmioletnią córkę, razem i uśmiechniętych"
    if re.fullmatch(r"mnie|mnie samą|mnie samego", low):
        with state.lock:
            who = state.person[0] if state.person else None
        try:
            import faces
            note = (faces.notes().get(who) or "").lower() if who else ""
        except Exception:
            note = ""
        if "dziecko" in note or "córka" in note:
            return "uśmiechniętą ośmioletnią dziewczynkę"
        if "tata" in note or "partner " in note:
            return "uśmiechniętego tatę"
        if "mama" in note or "partnerka" in note:
            return "uśmiechniętą mamę"
        return "uśmiechniętą osobę"
    if re.fullmatch(r"(?:coś|cos|cokolwiek|co\s+chcesz|coś\s+(?:ładnego|ladnego|fajnego|"
                    r"śmiesznego|smiesznego|wesołego|wesolego)|niespodziankę|niespodzianke)", low):
        # "Narysuj coś" drew the word "coś" (9 Oct) — a surprise of her own instead
        return random.choice(_SURPRISES)
    return what


_SURPRISES = ("kotka w skafandrze kosmicznym na Księżycu", "smoka, który piecze naleśniki",
              "jednorożca na tęczy", "żółwia na deskorolce", "sowę czytającą książkę pod "
              "gwiazdami", "rakietę lecącą między planetami", "małego robota podlewającego "
              "kwiatki", "lisa w szaliku w jesiennym lesie")


def _count_today():
    path = os.path.join(DIR, "count.json")
    today = time.strftime("%Y-%m-%d")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return path, today, d.get(today, 0)


def _bump(path, today, n):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({today: n + 1}, f)
    except OSError:
        pass


def _show(path, secs=SHOW_SECS):
    with state.lock:
        state.overlay = ("photo", time.time() + secs, path)


def _card(text, secs):
    with state.lock:
        state.overlay = ("card", time.time() + secs, {"text": text, "sub": "", "tone": None})


def saved():
    try:
        files = sorted(f for f in os.listdir(DIR) if f.endswith(".png"))
    except OSError:
        return []
    return [os.path.join(DIR, f) for f in files]


def show_saved(speak):
    pics = saved()[-8:]
    if not pics:
        speak("Jeszcze nic nie narysowałam. Powiedz na przykład: narysuj mi jednorożca.")
        return True
    if len(pics) == 1:
        _show(pics[0])
    else:
        with state.lock:
            state.overlay = ("gallery", time.time() + 6 * len(pics) + 2,
                             {"paths": pics[::-1], "i": 0, "next": time.time() + 6.0})
    speak("Proszę, moje rysunki." if len(pics) > 1 else "Proszę, mój rysunek.")
    return True


_STYLE = ("Pogodna, prosta, kolorowa ilustracja jak z książeczki dla dzieci, łagodne "
          "kształty, jasne tło, bez żadnych napisów, nic strasznego.")


def _from_photo(client, photo, what):
    """The camera frame redrawn as an illustration (11 Oct: "draw what you
    see on the camera" — Andrzej's OK to send the frame for it)."""
    extra = _details(what)
    return client.images.edit(
        model=MODEL, size="1024x1024", quality="low", n=1,
        image=("kamera.jpg", photo, "image/jpeg"),
        # (no example features in here: a test frame with nobody in it came
        # back as a bearded man in glasses — the words were drawn, not the photo)
        prompt=("Przerysuj dokładnie to zdjęcie z kamery jako ilustrację dla dziecka: "
                "te same osoby z ich prawdziwym wyglądem i ubraniem, ta sama liczba "
                "osób, te same pozy, ten sam pokój. Niczego i nikogo nie dodawaj ani "
                "nie zmieniaj, tylko narysuj. "
                + (f"Dodaj jedynie: {extra}. " if extra else "") + _STYLE))


def draw(what, speak, intro="Już rysuję… chwilka!", english=False, photo=None):
    """Start a drawing in the background; True (handled) either way. photo:
    JPEG bytes of the camera frame to redraw instead of imagining."""
    os.makedirs(DIR, exist_ok=True)
    path, today, n = _count_today()
    with _lock:
        if time.time() - _last[0] < DRAW_GAP:
            speak("Jeszcze kończę poprzedni rysunek — chwilka.")
            return True
        if n >= DRAW_PER_DAY:
            speak("Na dziś mam już dość rysowania — narysuję jutro!")
            return True
        _last[0] = time.time()
    _bump(path, today, n)
    speak(intro)
    _card("Rysuję…", 30)
    print(f"[draw] {what!r}{' from the camera' if photo else ''}", flush=True)

    def run():
        from text_to_speech import speak as say
        try:
            from openai import OpenAI
            from config import OPENAI_API_KEY
            c = OpenAI(api_key=OPENAI_API_KEY, timeout=90, max_retries=1)
            if photo:
                r = _from_photo(c, photo, what)
            else:
                r = c.images.generate(
                    model=MODEL, size="1024x1024", quality="low", n=1,
                    prompt=f"Obrazek dla dziecka: {_subject(what)}. {_STYLE}")
            png = base64.b64decode(r.data[0].b64_json)
            out = os.path.join(DIR, time.strftime("%Y%m%d-%H%M%S") + ".png")
            with open(out, "wb") as f:
                f.write(png)
            for old in saved()[:-KEEP]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            _show(out)
            print(f"[draw] done: {out}", flush=True)
            say("Here you go!" if english else "Gotowe! Proszę bardzo.")
            try:
                # the model hears what is on her screen (11 Oct: "Luna, podobna?"
                # after a portrait → "Jasne, podobnie")
                import brain
                brain.add_to_last_reply(
                    "(Rysunek gotowy, pokazany na ekranie: "
                    + ("obraz z kamery przerysowany jako ilustracja" if photo
                       else _subject(what)) + ".)")
            except Exception:
                pass
        except Exception as e:
            print(f"[draw] failed: {e}", flush=True)
            with state.lock:
                state.overlay = None
            refused = "safety" in str(e).lower() or "moderation" in str(e).lower()
            say("Tego nie narysuję — może coś wesołego?" if refused
                else "Nie udało mi się narysować — spróbuj jeszcze raz.")
    threading.Thread(target=run, daemon=True, name="draw").start()
    return True


_SHOW_OF = re.compile(r"^(?:luna,?\s+)?(?:pokaż|pokaz)\s+(?:mi\s+|nam\s+)?(?:jakiś\s+|jakis\s+)?"
                      r"(?:obrazek|obrazka|rysunek|rysunku|obraz|zdjęcie|zdjecie)\s+"
                      r"(?!z\s+wczoraj|z\s+dziś)(.{2,60}?)[.!?]*$", re.I)


# "Dobra, jeszcze raz ze zdjęcia" just after a drawing (11 Oct 12:02 — it
# went to the model, two sentences of "zaraz to zrobię" before the drawing)
_AGAIN = re.compile(r"^(?:(?:no\s+)?dobra,?\s+|dobrze,?\s+)?(?:luna,?\s+)?(?:narysuj\s+)?"
                    r"(?:jeszcze\s+raz|jeszcze\s+jeden(?:\s+raz)?|znowu|ponownie)"
                    r"(?:,?\s+(ze\s+zdjęcia|ze\s+zdjecia|z\s+kamery))?[.!?]*$", re.I)
AGAIN_SECS = 300               # "jeszcze raz ze zdjęcia" — a bare "jeszcze raz"
BARE_AGAIN_SECS = 90           # only right after (a game's "jeszcze raz" comes later)


def handle(text, speak):
    again = _AGAIN.match((text or "").strip())
    bare = again and not again.group(1) and not re.search(r"narysuj", text, re.I)
    if again and _last_what[0] and time.time() - _last[0] < (BARE_AGAIN_SECS if bare
                                                             else AGAIN_SECS):
        cam = _last_cam[0] or bool(again.group(1))
        photo = _camera_jpeg() if cam else None
        if photo:
            return draw(_last_what[0], speak, "Rysuję jeszcze raz — chwilka!", photo=photo)
        return draw(_last_what[0], speak, "Rysuję jeszcze raz — chwilka!")
    of = _SHOW_OF.match((text or "").strip())
    if of and not re.match(r"(?:jeszcze|ostatni|swój|swoj|mój|moj|ten)\b", of.group(1), re.I):
        # "pokaż mi obrazek kota" — a picture of it, drawn (no web pictures)
        photo = re.search(r"zdj", of.group(0), re.I)
        return draw(of.group(1).strip(), speak,
                    "Zdjęć nie mam, ale narysuję — chwilka!" if photo else "Już rysuję… chwilka!")
    if _SHOW.search(text or "") and len(text.split()) <= 6:
        return show_saved(speak)
    what = wants(text)
    cam = bool(what) and bool(_FROM_CAM.search(text) or _IN_FRONT.match(what)
                              or _in_view(what))
    if what and re.fullmatch(r"(?:to\s+)?(?:jeszcze(?:\s+raz)?|jeszcze\s+jedn\w*|inn\w*|drugi\w*|again|another(?:\s+one)?)", what, re.I):
        # "narysuj jeszcze raz" — the same thing again, a new picture
        if not _last_what[0]:
            speak("A co mam narysować?")
            return True
        what, cam = _last_what[0], _last_cam[0]
    if what:
        _last_what[0], _last_cam[0] = what, cam
        english = bool(re.match(r"\s*(?:luna,?\s*)?draw\b", text, re.I))   # "Draw me a cat"
        if cam:
            # "narysuj mnie", "narysuj to, co widzisz" — the camera frame,
            # redrawn (10–11 Oct: from imagination it was never them)
            photo = _camera_jpeg()
            if photo:
                return draw(what, speak, "Drawing what I see — just a moment!" if english
                            else "Rysuję to, co widzę w kamerze — chwilka!",
                            english=english, photo=photo)
            if not _is_person(what):
                speak("Kamera jest teraz wyłączona — nic nie widzę. Powiedz, co mam narysować.")
                return True
            if _is_person(what):
                return draw(what, speak, "Kamera jest wyłączona, więc rysuję z wyobraźni — "
                                         "nie będzie podobny. Chwilka!", english=english)
        if english:
            return draw(what, speak, "Drawing it now — just a moment!", english=True)
        if _is_person(what):
            # no photo of someone who isn't in front of her — say it, or "it
            # doesn't look like me" follows (10 Oct 20:35)
            return draw(what, speak, "Rysuję z wyobraźni — więc nie będzie podobny. Chwilka!")
        return draw(what, speak)
    return False


def _in_view(what):
    """"narysuj Maję" while Maja is in front of the camera."""
    with state.lock:
        here = [state.person[0]] if state.person else []
        if state.others and time.time() - state.others[1] < 10:
            here += list(state.others[0])
    try:
        import faces
        return bool(here) and faces.match_name(what.lower().split()[0]) in here
    except Exception:
        return False


def _is_person(what):
    """"mnie", "Maję", "tatę", "naszą rodzinę" — a person or the family."""
    low = what.lower().strip()
    if re.match(r"mnie\b", low) or re.fullmatch(
            r"nas(?:\s+wszystkich)?|(?:naszą|nasza|całą)?\s*rodzin\w*|"
            r"tat\w*|mam\w*|siebie\s+i\s+\w+", low):
        return True
    try:
        import faces
        return bool(faces.match_name(low.split()[0]))
    except Exception:
        return False
