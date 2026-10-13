"""
drawing.py — "Luna, narysuj mi jednorożca": a real picture on her screen.

  "narysuj mi kotka na rowerze" / "namaluj smoka" / "draw me a dinosaur"
        → "Dobrze, już rysuję. Chwileczkę!", ~10 s later the picture, big, for 40 s
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

# (11 Oct: "No narysuj nas…", "Maluj mnie", "Masz narysować tę postać" went
# to the model — and it once switched the lamp on instead)
_ASK = re.compile(r"^(?:(?:no|dobra|dobrze|to|a|okej|ok|więc|wiec|teraz)\s*,?\s+)*"
                  r"(?:luna,?\s+)?(?:(?:no|to|a|teraz)\s+)?"
                  r"(?:(?:czy\s+)?(?:możesz|mozesz|mogłabyś|moglabys|masz)\s+)?"
                  r"(?:(?:mi|nam)\s+)?"
                  r"(?:narysuj|narysujesz|narysować|narysowac|namaluj|namalujesz|namalować|"
                  r"namalowac|maluj|rysuj|draw)"
                  r",?(?:\s+(?:mi|nam|me),?)?(?:\s+(?:a|an))?\s+(.{2,200}?)[.!?]*$", re.I)
_SHOW = re.compile(r"\b(?:pokaż|pokaz)\s+(?:mi\s+|nam\s+)?(?:jeszcze\s+raz\s+)?"
                   r"(?:wszystkie\s+|ostatnie\s+)?(?:te\s+|moje\s+|swoje\s+|twoje\s+)?"
                   r"(?:rysun\w*|obraz\w*)\b", re.I)
_lock = threading.Lock()
_last = [0.0]
_last_what = [""]              # "narysuj jeszcze raz" — what it was
_last_cam = [False]            # … and whether it was the camera's picture


_MAKE = re.compile(r"^(?:luna,?\s+)?(?:(?:czy\s+)?(?:możesz|mozesz|mogłabyś|moglabys)\s+)?"
                   r"(?:mi\s+|nam\s+)?(?:zrobić|zrobic|zrób|zrob)\s+(?:mi\s+|nam\s+)?"
                   r"(?:rysunek|rysuneczek|obrazek|obrazka|obrazki)\s+(.{2,150}?)[.!?]*$", re.I)


def wants(text):
    """The thing to draw, or None. "Jeszcze raz mnie narysuj" (verb last) and
    "narysuj mnie jeszcze raz" too — 10 Oct 20:36: the first went to the
    model, which said "rysuję jeszcze raz" and nothing was drawn."""
    t = (text or "").strip()
    last = re.match(r"^(?:luna,?\s+)?(?:(?:jeszcze\s+raz|znowu|ponownie)\s+)?"
                    r"((?:\w+\s+){0,3}?\w+)\s+(?:narysuj|namaluj)\W*$", t, re.I)
    if last:
        t = f"narysuj {last.group(1)}"
    # "Możesz zrobić rysunek kotka na rowerze?" (13 Oct sweep: "Jasne — zrobię
    # kotka na rowerze." and nothing drawn) — the same as "narysuj kotka…"
    make = _MAKE.match(t)
    if make:
        t = f"narysuj {make.group(1)}"
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
_FROM_CAM = re.compile(r"\bze?\s+zdj\w*|\bjak\s+(?:tu\s+|teraz\s+)?jesteśmy|\bodwzoruj|"
                       r"\bjak\s+(?:tu\s+|teraz\s+)?jestem\b|\bz\s+kamery|\bz\s+obrazu|\bco\s+(?:teraz\s+)?widzisz|"
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
    """"mnie: okulary, broda" → "okulary, broda"; "mnie jako astronautę" →
    "jako astronautę" — what to change in the photo ("" for a plain portrait)."""
    m = re.search(r"[:—–]\s*(.{3,})$", what or "")
    if m:
        return m.group(1).strip()
    rest = re.sub(r"^(?:mnie|nas(?:\s+wszystkich)?|(?:naszą|nasza|całą|cala)?\s*rodzin\w*|"
                  r"to,?\s+co\s+(?:teraz\s+)?widzisz)\b,?\s*", "", (what or "").strip(), flags=re.I)
    rest = _FROM_CAM.sub("", rest).strip(" ,.")
    rest = re.sub(r"^(?:tak,?\s+)?(?:po\s+prostu|i\s+tyle|tak)$", "", rest, flags=re.I)
    if re.search(r"\b(?:narysuj|zapamiętaj|zapamietaj|zrób|zrob|popatrz|patrz|odwzoruj)\b",
                 rest, re.I):
        return ""                        # talk to her ("zapamiętaj kilka rzeczy"), not a change
    return rest if len(rest) >= 3 and rest != (what or "").strip() else ""


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
                + (f"Jedyna zmiana, o którą proszą: {extra}. " if extra else "") + _STYLE))


# Her lines here open with "Dobrze, …": "Już rysuję… chwilka!" came back from a
# speech→text round trip as "Jus resuya, fika", "Gotowe!" as "Gotová" — a short
# start drifts out of Polish; 3 of 3 clean with "Dobrze," (11 Oct). Cached, a
# bad take would have been said that way on every drawing.
def draw(what, speak, intro="Dobrze, już rysuję. Chwileczkę!", english=False, photo=None):
    """Start a drawing in the background; True (handled) either way. photo:
    JPEG bytes of the camera frame to redraw instead of imagining."""
    with state.lock:
        online = state.online
    if not online:
        # the image model is in the cloud: say so now, not after a 90 s timeout
        speak("Nie mam teraz internetu, więc nie narysuję. Spróbujmy później!")
        return True
    if not photo:
        import webphoto            # the same topics as for photos: not for a child
        if webphoto.NOT_FOR_KIDS.search(what or ""):
            print(f"[draw] not for a child: {what!r}", flush=True)
            speak("Tego nie narysuję — może coś wesołego?")
            return True
    os.makedirs(DIR, exist_ok=True)
    path, today, n = _count_today()
    with _lock:
        if time.time() - _last[0] < DRAW_GAP:
            speak("Chwileczkę, jeszcze kończę poprzedni rysunek.")
            return True
        if n >= DRAW_PER_DAY:
            speak("Na dziś mam już dość rysowania — narysuję jutro!")
            return True
        _last[0] = time.time()
    _bump(path, today, n)
    if not (threading.current_thread().name == "command"
            and not re.search(r"wyłączona|wyobraźni", intro)):
        # (from the model's answer — brain._spoken_command's thread — her
        # "Jasne, już rysuję…" was just said: no second "Dobrze, już rysuję. Chwileczkę!")
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
            say("Here you go!" if english else "Dobrze, rysunek jest gotowy. Proszę bardzo!")
            with state.lock:
                # a reaction needs no "Luna" (11 Oct: the window closed while
                # she drew, and "jeszcze raz ze zdjęcia" waited for the wake word)
                state.conversation_active = True
                state.last_activity_time = max(state.last_activity_time, time.time())
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


# "Jak wygląda żyrafa?" — a photo answers it (13 Oct sweep: words about a long
# neck and spots); not the weather, a plan, a list, nor a person
_LOOKS = re.compile(r"^(?:luna,?\s+)?(?:a\s+|i\s+|no\s+to\s+)?jak\s+(?:właściwie\s+|wlasciwie\s+)?"
                    r"(?:wygląda|wyglada|wyglądają|wygladaja)\s+(.{2,40}?)[.!?]*$", re.I)
_NOT_A_THING = re.compile(r"^(?:on|ona|ono|oni|one|to|ten|ta|tamt\w*|tw\w*|moj\w*|mój|lun[aey]|"
                          r"nasz\w*|wasz\w*|jej|jego|ich|pogoda|pogod\w*|dzień|dzien|dzisiaj|dziś|"
                          r"dzis|jutro|plan\w*|sytuacja|sprawa|lista|kalendarz|zakupy|tydzień|"
                          r"tydzien|weekend|wynik\w*|kurs\w*|stan|wszystko|życie|zycie|"
                          r"teraz|u\s+\w+|w\s+\w+|na\s+\w+)\b", re.I)


def person_photos(what):
    """("Maja", [her photos]) when `what` is someone of the family with photos
    of hers taken here ("zrób nam zdjęcie"), else None."""
    try:
        import faces
        import screens
        name = faces.match_name(_first_word(what)) or faces.match_role(_first_word(what))
        paths = screens.photos_of(name) if name else []
        return (name, paths) if paths else None
    except Exception:
        return None


def show_person(what, speak):
    """"Pokaż mi zdjęcie Mai" / "Jak wygląda Maja?" — her real photos, if any
    (13 Oct: she was always drawn "z wyobraźni", with photos of her on disk)."""
    got = person_photos(what)
    if not got:
        return False
    import screens
    name, paths = got
    screens.show_photos(paths[:8], [name] * len(paths[:8]))
    speak(f"Proszę, tak wygląda {name}." if len(paths) == 1
          else f"Proszę, zdjęcia, na których jest {name}.")
    return True


# "Pokaż mi słonia." — what's left of "pokaż mi …" after every handler (screens,
# lists, games) had its turn: a thing to see (12 Oct: the model looked for an
# elephant in the camera frame — "słonia na tym zdjęciu nie widzę")
# ("mi" may be left out: "Pokaż pandę" went to the model — 13 Oct probe)
_BARE_SHOW = re.compile(r"^(?:luna,?\s+)?(?:a\s+|no\s+to\s+)?(?:pokaż|pokaz)\s+(?:(?:mi|nam)\s+)?"
                        r"([^\W\d_]+(?:\s+[^\W\d_]+){0,2})[.!?]*$", re.I)
_NOT_TO_SEE = re.compile(r"^(?:co[śs]?|jak|gdzie|kiedy|ile|kto|któr\w*|ktor\w*|czy|się|sie|"
                         r"siebie|jeszcze|ostatni\w*|wszystk\w*|inn\w*|now\w*|"
                         r"swo\w*|zdj\w*|rysun\w*|obraz\w*|galeri\w*|zegar\w*|godzin\w*|"
                         r"czas|dat\w*|status|film\w*|bajk\w*|quiz\w*|gr[aęy]|ekran|menu|"
                         r"słow\w*|slow\w*|liczb\w*|lustr\w*|kamer\w*|oczy|oko|twarz\w*|"
                         r"min[ęey]|emocj\w*|sztuczk\w*|drog\w*|przepis\w*|notatk\w*|"
                         r"zadani\w*|lekcj\w*|wiadomo\w*|histori\w*|przykład\w*|przyklad\w*|"
                         r"z|ze|od|do|o|po|przez|dla|bez|pod|nad|przy|"   # "z Wikipedii"
                         r"list\w*|zakup\w*|kalendarz\w*|przypomn\w*|minutnik\w*|budzik\w*|"
                         r"jak\w*|tak\w*|ten|tę|te|tego|tamt\w*|"
                         # her own face and body: "Pokaż język", "pokaż serduszko"
                         r"język|jezyk|języczek|serduszk\w*|serce|uśmiech|usmiech|zęby|zeby|"
                         r"ząbki|zabki|rękę|reke|łapkę|lapke|brzuch\w*|nos|nosek|ucho|uszy|"
                         r"uszka|mnie|nas|go|ją|ja|je)\b", re.I)


def bare_show(text, speak):
    """"Pokaż mi słonia" → a photo from Wikipedia (else drawn); a person → their
    photos. Called last in commands.handle. False when it isn't that."""
    m = _BARE_SHOW.match((text or "").strip())
    if not m:
        return False
    what = m.group(1).strip()
    if _NOT_A_THING.match(what) or _NOT_TO_SEE.match(what):
        return False
    if _is_person(what):
        return show_person(what, speak)
    import webphoto
    return webphoto.show(what, speak, lambda intro="Dobrze, już rysuję. Chwileczkę!":
                         draw(what, speak, intro))


def looks_wanted(text):
    """"Jak wygląda żyrafa?" → "żyrafa"; None for "jak wygląda pogoda", a person."""
    m = _LOOKS.match((text or "").strip())
    if not m:
        return None
    what = m.group(1).strip(" ,")
    if _NOT_A_THING.match(what) or _is_person(what) or len(what.split()) > 4:
        return None
    return what


# "Dobra, jeszcze raz ze zdjęcia" just after a drawing (11 Oct 12:02 — it
# went to the model, two sentences of "zaraz to zrobię" before the drawing)
_AGAIN = re.compile(r"^(?:(?:no\s+)?dobra,?\s+|dobrze,?\s+)?(?:luna,?\s+)?(?:narysuj\s+)?"
                    r"(?:jeszcze\s+raz|jeszcze\s+jeden(?:\s+raz)?|znowu|ponownie)"
                    r"(?:,?\s+(ze\s+zdjęcia|ze\s+zdjecia|z\s+kamery))?[.!?]*$", re.I)
# "A teraz ze zdjęcia" (12 Oct 13:32, after "narysuj Emilkę": the model drew
# "mnie" from the camera instead, after two sentences)
_NOW_PHOTO = re.compile(r"^(?:a\s+)?(?:luna,?\s+)?(?:a\s+)?(?:teraz|to\s+teraz|a\s+może|a\s+moze)"
                        r",?\s+(ze\s+zdjęcia|ze\s+zdjecia|z\s+kamery)[.!?]*$", re.I)
AGAIN_SECS = 300               # "jeszcze raz ze zdjęcia" — a bare "jeszcze raz"
BARE_AGAIN_SECS = 90           # only right after (a game's "jeszcze raz" comes later)


def handle(text, speak):
    import webphoto
    if webphoto.again_wanted(text) and webphoto._shown.get("at", 0) >= _last[0]:
        return webphoto.show_again(speak)           # "pokaż to jeszcze raz" (the photo)
    if not webphoto._shown.get("title") and webphoto._MORE.match((text or "").strip()) \
            and re.search(r"zdję|zdje", text or "", re.I):
        # "Pokaż inne zdjęcie" with none shown yet: the model said "Jasne —
        # pokazuję inne zdjęcie" and nothing came (13 Oct sweep)
        speak("Najpierw powiedz, czego zdjęcie mam pokazać — na przykład: "
              "pokaż mi zdjęcie żyrafy.")
        return True
    if webphoto.more_wanted(text) and webphoto._shown.get("at", 0) >= _last[0]:
        # "pokaż inne zdjęcie" / "jeszcze jedno" after a Wikipedia photo (not
        # after a drawing — then "jeszcze raz" is a new drawing, below)
        return webphoto.more(speak)
    again = _AGAIN.match((text or "").strip()) or _NOW_PHOTO.match((text or "").strip())
    bare = again and not again.group(1) and not re.search(r"narysuj", text, re.I)
    if again and _last_what[0] and time.time() - _last[0] < (BARE_AGAIN_SECS if bare
                                                             else AGAIN_SECS):
        cam = _last_cam[0] or bool(again.group(1))
        photo = _camera_jpeg() if cam else None
        if photo:
            return draw(_last_what[0], speak, "Dobrze, rysuję jeszcze raz. Chwileczkę!", photo=photo)
        return draw(_last_what[0], speak, "Dobrze, rysuję jeszcze raz. Chwileczkę!")
    m = _LOOKS.match((text or "").strip())
    if m and _is_person(m.group(1).strip(" ,")) and show_person(m.group(1), speak):
        return True                                # "Jak wygląda Maja?" — her photos
    looks = looks_wanted(text)
    if looks:
        import webphoto
        return webphoto.show(looks, speak, lambda intro="Dobrze, już rysuję. Chwileczkę!":
                             draw(looks, speak, intro))
    of = _SHOW_OF.match((text or "").strip())
    if of and not re.match(r"(?:jeszcze|ostatni|swój|swoj|mój|moj|ten)\b", of.group(1), re.I):
        # "pokaż mi obrazek kota" — a picture of it, drawn; "pokaż mi zdjęcie
        # żyrafy" — a real one, from Wikipedia (webphoto.py), else drawn
        what = of.group(1).strip()
        if re.search(r"zdj", of.group(0), re.I) and _is_person(what) and show_person(what, speak):
            return True                            # "pokaż mi zdjęcie Mai" — a real one
        if re.search(r"zdj", of.group(0), re.I) and not _is_person(what):
            import webphoto
            return webphoto.show(what, speak, lambda intro="Dobrze, już rysuję. Chwileczkę!":
                                 draw(what, speak, intro))
        if _is_person(what):
            # no photo of them here: say it's from imagination (13 Oct sweep:
            # "pokaż mi zdjęcie mamy" → "Dobrze, już rysuję")
            return draw(what, speak, "Dobrze, zdjęcia nie mam, więc narysuję z wyobraźni. "
                                     "Chwileczkę!")
        return draw(what, speak, "Dobrze, już rysuję. Chwileczkę!")
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
    if what and not cam and re.fullmatch(r"(?:t[ęa]|tego|tą)\s+(?:postać|postac|rzecz|scenę|scene|"
                                         r"obrazek|rysunek)|to|go|ją|ja|je|tamto|tamtego", what, re.I):
        return False       # "masz narysować tę postać" — the model knows which (11 Oct)
    if what:
        _last_what[0], _last_cam[0] = what, cam
        english = bool(re.match(r"\s*(?:luna,?\s*)?draw\b", text, re.I))   # "Draw me a cat"
        if cam:
            # "narysuj mnie", "narysuj to, co widzisz" — the camera frame,
            # redrawn (10–11 Oct: from imagination it was never them)
            photo = _camera_jpeg()
            if photo:
                return draw(what, speak, "Drawing what I see — just a moment!" if english
                            else "Dobrze, rysuję to, co widzę w kamerze. Chwileczkę!",
                            english=english, photo=photo)
            if not _is_person(what):
                speak("Kamera jest teraz wyłączona — nic nie widzę. Powiedz, co mam narysować.")
                return True
            return draw(what, speak, "Kamera jest teraz wyłączona, więc rysuję z wyobraźni. "
                                         "Chwileczkę!", english=english)
        if english:
            return draw(what, speak, "Drawing it now — just a moment!", english=True)
        if _is_person(what):
            # no photo of someone who isn't in front of her — say it, or "it
            # doesn't look like me" follows (10 Oct 20:35)
            return draw(what, speak, "Dobrze, rysuję z wyobraźni, więc nie będzie bardzo podobny. Chwileczkę!")
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
        return bool(here) and faces.match_name(_first_word(what)) in here
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
        return bool(faces.match_name(_first_word(low)))
    except Exception:
        return False


def _first_word(what):
    """"Maja: kot w ręce" → "maja" (the colon kept "Maja:" from being a name)."""
    w = re.findall(r"[^\W\d_]+", (what or "").lower())
    return w[0] if w else ""
