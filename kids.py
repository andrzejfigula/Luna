"""
kids.py — two little helpers for the daily routine.

  "Myjemy zęby"            → two minutes on her screen, counting down, with a
                             nudge every 30 s to the next part of the mouth
                             (top left, top right, bottom right, bottom left)
                             and a chime at the end. A tap stops it.
  "Zacznij poranek"        → walks through the list "poranek" one step at a
  "Zacznij wieczór"          time: the step big on her screen, she says it,
  "Rutyna <name>"            and waits for "gotowe" / "zrobione" / "dalej".
                             The list is any list she keeps ("dopisz umyj
                             zęby do listy poranek") and stays as it is.

The routine lives between utterances like the quizzes (commands.handle
passes each utterance to answer() while it runs); anything that isn't
"done" ends it and goes to the model.
"""

import random
import re
import threading
import time

from shared_state import state

BRUSH_SECS   = 120
ROUTINE_IDLE = 15 * 60     # a step may take a while — but not forever

_BRUSH = ("myjemy zęby", "myjemy zeby", "mycie zębów", "mycie zebow", "umyjmy zęby",
          "umyjmy zeby", "myję zęby", "myje zeby", "idę myć zęby", "ide myc zeby",
          "pilnuj mycia zębów", "czas na mycie zębów", "brush teeth", "brushing teeth",
          "szczotkowanie zębów")
_ZONES = [("góra · lewa strona", "Zaczynamy od górnych zębów po lewej stronie."),
          ("góra · prawa strona", "Teraz górne zęby po prawej!"),
          ("dół · prawa strona", "Teraz dolne po prawej!"),
          ("dół · lewa strona", "I ostatnie: dolne po lewej!")]

_ROUTINE = re.compile(r"\b(?:zacznij|zaczynamy|zacznijmy|start|rozpocznij|włącz|wlacz)\s+"
                      r"(?:rutynę\s+|rutyne\s+|listę\s+|liste\s+)?(\w+)|"
                      r"\brutyna\s+(\w+)|\b(\w+)\s+krok po kroku")
_ROUTINE_NAMES = {"poranek": "poranek", "poranną": "poranek", "ranną": "poranek",
                  "rano": "poranek", "dzień": "poranek", "wieczór": "wieczór",
                  "wieczorną": "wieczór", "wieczor": "wieczór", "wieczorem": "wieczór"}
DEFAULT_STEPS = {"poranek": ["umyj buzię", "ubierz się", "zjedz śniadanie", "umyj zęby",
                             "spakuj plecak"],
                 "wieczór": ["umyj się", "umyj zęby", "przygotuj ubranie na jutro",
                             "piżama", "do łóżka"]}
_DONE = ("gotowe", "gotowy", "gotowa", "zrobione", "zrobiłem", "zrobiłam", "zrobilem",
         "zrobilam", "dalej", "następne", "nastepne", "następny", "już", "juz",
         "skończyłem", "skończyłam", "done", "next", "ok", "okej", "jest")
_STOP = ("koniec", "stop", "przestań", "przestan", "wystarczy", "kończymy")
_PRAISE = ["Super!", "Brawo!", "Świetnie!", "Pięknie!", "Tak trzymać!"]

_lock = threading.Lock()
_routine = None            # {"name", "steps", "i", "t"}
_brushing = [False]


# ── tooth brushing ────────────────────────────────────────────────────────────

def _card(text, sub, tone=None, secs=3.0):
    with state.lock:
        state.overlay = ("card", time.time() + secs, {"text": text, "sub": sub, "tone": tone})


def _clear():
    with state.lock:
        if state.overlay and state.overlay[0] == "card":
            state.overlay = None


def _card_gone():
    with state.lock:
        ov = state.overlay
    return not ov or ov[0] != "card" or time.time() > ov[1]


_brush_t0 = [0.0]
_brush_stop = [False]


def brushing_answer(text, speak):
    """While brushing: "ile jeszcze?" → the time left; "koniec" / "stop" ends
    it (7 Oct probe: both went to the model — only a tap could stop it)."""
    if not _brushing[0]:
        return False
    low = text.lower().strip(" .!?")
    words = re.findall(r"\w+", low)
    if set(words) & set(_STOP) and len(words) <= 4:        # whole words: not "stoper"
        _brush_stop[0] = True
        _brushing[0] = False                               # at once, not on the next tick
        speak("Dobrze, kończymy mycie.")
        return True
    if re.search(r"\bile\b.*\b(?:jeszcze|zostało|zostalo)\b|\bjak\s+długo\b", low):
        left = max(0, int(BRUSH_SECS - (time.time() - _brush_t0[0])))
        speak(f"Jeszcze {left // 60} minuta {left % 60} sekund." if left >= 60 else
              f"Jeszcze {left} sekund — prawie koniec!")
        return True
    return False


def _brush(speak, play_sound):
    _brushing[0] = True
    _brush_stop[0] = False
    try:
        speak("Dwie minuty mycia zębów! " + _ZONES[0][1])
        t0 = time.time()
        _brush_t0[0] = t0
        zone = 0
        while True:
            left = BRUSH_SECS - (time.time() - t0)
            if left <= 0:
                break
            z = min(3, int((time.time() - t0) // (BRUSH_SECS / 4)))
            if z != zone:                          # said while the clock runs on
                zone = z
                threading.Thread(target=speak, args=(_ZONES[z][1],), daemon=True).start()
            secs = int(left) + 1
            _card(f"{secs // 60}:{secs % 60:02d}", _ZONES[zone][0], secs=1.5)
            time.sleep(0.25)
            if _card_gone() or _brush_stop[0]:     # a tap on the screen, or "koniec"
                print("[kids] brushing stopped", flush=True)
                _clear()
                return
        _card("0:00", "gotowe!", "ok", secs=5)
        with state.lock:
            state.emotion = "Happy"
        play_sound("chime")
        speak(random.choice(["Gotowe! Piękne, czyste zęby!",
                             "Koniec! Zęby błyszczą jak gwiazdki!",
                             "Brawo, dwie minuty! Uśmiechnij się do mnie!"]))
        print("[kids] brushing done", flush=True)
    finally:
        _brushing[0] = False


# ── routines ──────────────────────────────────────────────────────────────────

def routine_name(text):
    """"zacznij poranek" → "poranek" (only when such a list exists or the
    name is a known routine), else None."""
    import lists
    low = text.lower()
    if len(re.findall(r"\w+", low)) > 7:
        return None
    m = _ROUTINE.search(low)
    if not m:
        return None
    word = next(g for g in m.groups() if g)
    name = _ROUTINE_NAMES.get(word, word)
    have = lists.get()
    if name in have:
        return name
    if name in _ROUTINE_NAMES.values():
        return name                                 # known, but no list yet
    return None


def offered_routine(reply):
    """Her reply offered the morning / bedtime steps → "poranek" / "wieczór"."""
    low = (reply or "").lower()
    if (("?" not in low and not re.search(r"\bchcesz\b|\bmogę\b|\bmoge\b", low))
            or not re.search(r"krok\s+po\s+kroku|po\s+kolei|listę|liste|plan", low)):
        return None
    if re.search(r"\bporann\w*|\bporan\w*|\bna\s+rano\b", low):
        return "poranek"
    if re.search(r"\bwieczorn\w*|\bna\s+wieczór\b|\bprzed\s+snem\b|\bdo\s+snu\b", low):
        return "wieczór"
    return None


def routine_active():
    global _routine
    with _lock:
        if _routine and time.time() - _routine["t"] > ROUTINE_IDLE:
            _routine = None
        return _routine is not None


def _step(speak):
    r = _routine
    step = r["steps"][r["i"]]
    _card(step, f"krok {r['i'] + 1} z {len(r['steps'])} · powiedz „gotowe”",
          secs=ROUTINE_IDLE)
    speak(("Pierwszy krok: " if r["i"] == 0 else
           "I ostatni: " if r["i"] == len(r["steps"]) - 1 else "Teraz: ") + step + ".")


def start_routine(name, speak):
    global _routine
    import lists
    steps = lists.get(name)
    if not steps and name in DEFAULT_STEPS:
        # no list yet: a sensible one, kept as an ordinary list the parents can
        # change ("skreśl … z listy poranek") — 8 Oct: Maja's "Co dziś mam
        # zrobić rano?" had nothing to start
        lists.apply([{"type": "list_add", "list": name, "label": s, "seconds": 0, "at": "",
                      "repeat": "none"} for s in DEFAULT_STEPS[name]])
        steps = lists.get(name)
        speak(f"Ułożyłam listę „{name}” — rodzice mogą ją zmienić.")
    if not steps:
        speak(f"Nie mam jeszcze listy „{name}”. Powiedz na przykład: dopisz „umyj zęby” "
              f"do listy {name}.")
        return
    with _lock:
        _routine = {"name": name, "steps": steps, "i": 0, "t": time.time()}
        print(f"[kids] routine {name}: {len(steps)} steps", flush=True)
        _step(speak)


def routine_answer(text, speak, play_sound):
    """An utterance while a routine runs. True when it was part of it."""
    global _routine
    low = text.lower()
    words = re.findall(r"\w+", low)
    with _lock:
        r = _routine
        if r is None:
            return False
        if re.search(r"\b(?:" + "|".join(map(re.escape, _STOP)) + r")\b", low) and len(words) <= 4:
            _routine = None
            _clear()
            speak("Dobrze, kończymy.")
            return True
        # "Powtórz" / "co dalej?" / "pomiń" belong to the routine (7 Oct probe:
        # "Powtórz" ended it, and every "Gotowe" after went to the model)
        if re.match(r"^(?:powtórz|powtorz|jeszcze\s+raz|co\s+(?:teraz|dalej|mam\s+robić)|"
                    r"co\s+mówiłaś|co\s+mowilas|który\s+krok|ktory\s+krok)\b", low.strip()):
            r["t"] = time.time()
            _step(speak)
            return True
        # "Nie chce mi się" / "ile jeszcze?" — part of it too (9 Oct probe: the
        # first ended the routine, and the steps after went to the model)
        if re.search(r"\bnie\s+chce\s+mi\s+się|\bnie\s+chce\s+mi\s+sie|\bnie\s+chcę\b|"
                     r"\bnie\s+chce\b|\bnie\s+mam\s+siły|\bczy\s+muszę|\bmuszę\?", low) \
                and len(words) <= 6:
            r["t"] = time.time()
            speak(random.choice(["Wiem, wiem. Tylko ten jeden krok — dasz radę!",
                                 "Rozumiem. Zróbmy tylko to jedno, a potem następne."]))
            _step(speak)
            return True
        if re.search(r"\bile\s+(?:jeszcze|zostało|zostalo|kroków|krokow)\b", low) and len(words) <= 6:
            r["t"] = time.time()
            left = r["steps"][r["i"]:]
            speak(("Został jeszcze tylko jeden krok: " if len(left) == 1 else
                   f"Zostały jeszcze {len(left)} kroki: " if len(left) in (2, 3, 4) else
                   f"Zostało jeszcze {len(left)} kroków: ") + ", ".join(left) + ".")
            return True
        skipped = bool(re.match(r"^(?:pomiń|pomin|przeskocz|nie\s+teraz)\b", low.strip())
                       and len(words) <= 4)
        if skipped:
            words = list(_DONE)[:1]          # the next step, without the praise
        if not (set(words) & set(_DONE)) or len(words) > 6:
            # something else ("opowiedz bajkę", a question): answered as usual,
            # and the routine waits — it ends with "koniec" or after a while
            print("[kids] not a step — the routine waits", flush=True)
            return False
        r["i"] += 1
        r["t"] = time.time()
        if r["i"] >= len(r["steps"]):
            _routine = None
            _card("Brawo!", "wszystko zrobione", "ok", secs=5)
            with state.lock:
                state.emotion = "Happy"
            play_sound("chime")
            done = random.choice(["Wszystko zrobione! Jesteś super!",
                                  "Gotowe, wszystkie kroki! Brawo!"])
            if r["name"] == "wieczór":
                # the bedtime chat: the best bit of the day (an answer needs no
                # "Luna" — the conversation stays open)
                speak(done + " " + random.choice(["A powiedz mi jeszcze: co dziś było najfajniejsze?",
                                                  "Zanim zaśniesz — co dziś było najlepsze?"]))
                with state.lock:
                    state.conversation_active = True
                    state.last_activity_time = time.time() + 8
            else:
                speak(done)
            return True
        speak("Dobrze, pomijamy." if skipped else random.choice(_PRAISE))
        _step(speak)
        return True


# ── entry ─────────────────────────────────────────────────────────────────────

def handle(text, speak, play_sound):
    low = text.lower()
    if any(k in low for k in _BRUSH) and "?" not in low and (
            len(re.findall(r"\w+", low)) <= 4 or re.search(
                r"\b(teraz|idę|ide|idziemy|chodź|chodz|czas|pora|już|juz)\b", low)):
        # (not "myjemy zęby dwa razy dziennie" — that is just said)
        if not _brushing[0]:
            threading.Thread(target=_brush, args=(speak, play_sound), daemon=True,
                             name="brushing").start()
        return True
    name = routine_name(text)
    if name:
        start_routine(name, speak)
        return True
    return False
