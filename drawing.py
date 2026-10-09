"""
drawing.py — "Luna, narysuj mi jednorożca": a real picture on her screen.

  "narysuj mi kotka na rowerze" / "namaluj smoka" / "draw me a dinosaur"
        → "Już rysuję… chwilka!", ~10 s later the picture, big, for 40 s
  "pokaż rysunki" / "pokaż jeszcze raz rysunek" → the last ones again

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
                  r",?(?:\s+(?:mi|nam|me),?)?(?:\s+(?:a|an))?\s+(.{2,80}?)[.!?]*$", re.I)
_SHOW = re.compile(r"\b(?:pokaż|pokaz)\s+(?:mi\s+)?(?:jeszcze\s+raz\s+)?(?:te\s+|moje\s+|swoje\s+)?"
                   r"(?:rysun\w*|obraz\w*)\b", re.I)
_lock = threading.Lock()
_last = [0.0]
_last_what = [""]              # "narysuj jeszcze raz" — what it was


def wants(text):
    """The thing to draw, or None."""
    m = _ASK.match((text or "").strip())
    return m.group(1).strip() if m else None


def _subject(what):
    """"mnie", "siebie", "naszą rodzinę" — words for the picture (no photo is
    ever sent; the family is drawn from a description)."""
    low = what.lower().strip()
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


def draw(what, speak, intro="Już rysuję… chwilka!", english=False):
    """Start a drawing in the background; True (handled) either way."""
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
    print(f"[draw] {what!r}", flush=True)

    def run():
        from text_to_speech import speak as say
        try:
            from openai import OpenAI
            from config import OPENAI_API_KEY
            c = OpenAI(api_key=OPENAI_API_KEY, timeout=60, max_retries=1)
            r = c.images.generate(
                model=MODEL, size="1024x1024", quality="low", n=1,
                prompt=(f"Obrazek dla dziecka: {_subject(what)}. Pogodna, prosta, kolorowa "
                        "ilustracja jak z książeczki dla dzieci, łagodne kształty, "
                        "jasne tło, bez żadnych napisów, nic strasznego."))
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


def handle(text, speak):
    of = _SHOW_OF.match((text or "").strip())
    if of and not re.match(r"(?:jeszcze|ostatni|swój|swoj|mój|moj|ten)\b", of.group(1), re.I):
        # "pokaż mi obrazek kota" — a picture of it, drawn (no web pictures)
        photo = re.search(r"zdj", of.group(0), re.I)
        return draw(of.group(1).strip(), speak,
                    "Zdjęć nie mam, ale narysuję — chwilka!" if photo else "Już rysuję… chwilka!")
    if _SHOW.search(text or "") and len(text.split()) <= 6:
        return show_saved(speak)
    what = wants(text)
    if what and re.fullmatch(r"(?:to\s+)?(?:jeszcze(?:\s+raz)?|jeszcze\s+jedn\w*|inn\w*|drugi\w*|again|another(?:\s+one)?)", what, re.I):
        # "narysuj jeszcze raz" — the same thing again, a new picture
        if not _last_what[0]:
            speak("A co mam narysować?")
            return True
        what = _last_what[0]
    if what:
        _last_what[0] = what
        if re.match(r"\s*(?:luna,?\s*)?draw\b", text, re.I):    # "Draw me a cat"
            return draw(what, speak, "Drawing it now — just a moment!", english=True)
        return draw(what, speak)
    return False
