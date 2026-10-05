"""
cooking.py — a recipe, one step at a time, hands free.

  "Gotujemy naleśniki" / "przepis na naleśniki krok po kroku" /
  "pomóż mi upiec ciasto czekoladowe"
     → the ingredients first, then each step big on her screen
  "dalej" / "następny krok"   "powtórz"   "wróć" / "poprzedni krok"
  "koniec" / "skończyłam"
  a step with a time ("smaż 2 minuty z każdej strony") → "Nastawić minutnik
  na 2 minuty?" — "tak" sets it (timers.py)

The recipe comes from the model as JSON (ingredients, steps with the
minutes each needs). Between steps she waits as long as cooking takes
(STEP_IDLE); words that aren't about the recipe end it and go to the model.
"""

import json
import re
import threading
import time

from shared_state import state

STEP_IDLE = 30 * 60

# ("zróbmy …" / "pomóż mi zrobić …" are too wide: "zróbmy coś fajnego")
_START = re.compile(r"\b(?:gotujemy|ugotujmy|upieczmy|pieczemy|przepis\s+na|"
                    r"pomóż\s+mi\s+(?:ugotować|upiec)|pomoz\s+mi\s+(?:ugotowac|upiec))\s+"
                    r"(.+?)(?:\s+krok\s+po\s+kroku)?[.!?]*$", re.I)
_NEXT = ("dalej", "następny", "nastepny", "następne", "kolejny", "gotowe", "zrobione",
         "już", "juz", "ok", "okej", "next")
_BACK = ("wróć", "wroc", "poprzedni", "cofnij", "wcześniej")
_AGAIN = ("powtórz", "powtorz", "jeszcze raz", "co teraz", "co mam robić")
_YES = ("tak", "nastaw", "proszę", "prosze", "poproszę", "dobrze", "jasne", "yes")
_STOP = ("koniec", "kończymy", "konczymy", "skończyłam", "skończyłem", "stop", "wystarczy")

_lock = threading.Lock()
_c = None            # {"title", "ingredients", "steps": [{"text", "minutes"}], "i", "t", "offer"}


def wants(text):
    """The dish asked for, or None. ("zróbmy dyktando" is a quiz, not food.)"""
    if len(re.findall(r"\w+", text)) > 12:
        return None
    m = _START.search(text.strip())
    if not m:
        return None
    dish = m.group(1).strip(" ,.")
    if re.search(r"\b(dyktand|quiz|zdjęci|zdjeci|zagad|przerw|porządek|porzadek|"
                 r"lekcj|zadani|pranie|zakupy)", dish.lower()):
        return None
    return dish


def _recipe(dish):
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=20, max_retries=1)
    r = c.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.4, max_tokens=900,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   f"Ktoś prosi o przepis na: \"{dish}\". Najpierw oceń, czy to jest "
                   "potrawa, wypiek albo napój. Zwróć JSON {\"is_food\": true/false, "
                   '"title": "nazwa TEJ potrawy w mianowniku", "ingredients": ["ilość + '
                   'składnik", ...], "steps": [{"text": "jeden krok, jedno-dwa krótkie '
                   'zdania do przeczytania na głos", "minutes": liczba minut czekania '
                   'w tym kroku albo 0}, ...]} — prosty domowy przepis dla 2–4 osób, 4 do '
                   '10 kroków. Gdy is_food jest false, reszta pusta; nigdy nie podawaj '
                   'przepisu na coś innego niż to, o co proszono.'}])
    d = json.loads(r.choices[0].message.content)
    if not d.get("is_food") or not d.get("title") or not d.get("steps"):
        return None
    # the recipe must be for what was asked (it once answered "prezentacja"
    # with a Greek salad)
    asked = {w[:4] for w in re.findall(r"\w{4,}", dish.lower())}
    got = {w[:4] for w in re.findall(r"\w{4,}", d["title"].lower())}
    if asked and not asked & got:
        print(f"[cooking] asked {dish!r}, got {d['title']!r} — not used", flush=True)
        return None
    steps = [{"text": str(s.get("text", "")).strip(), "minutes": int(s.get("minutes") or 0)}
             for s in d["steps"] if str(s.get("text", "")).strip()]
    return {"title": d["title"].strip(), "ingredients": [str(x) for x in d.get("ingredients", [])],
            "steps": steps}


def active():
    global _c
    with _lock:
        if _c and time.time() - _c["t"] > STEP_IDLE:
            _c = None
        return _c is not None


def _card(text, sub):
    with state.lock:
        state.overlay = ("card", time.time() + STEP_IDLE, {"text": text, "sub": sub, "tone": None})


def _clear():
    with state.lock:
        if state.overlay and state.overlay[0] == "card":
            state.overlay = None


def _keep_listening():
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time() + 20)


def _say_step(speak):
    c = _c
    s = c["steps"][c["i"]]
    n, total = c["i"] + 1, len(c["steps"])
    words = s["text"].split()
    short = " ".join(words[:7]) + ("…" if len(words) > 7 else "")
    _card(short, f"{c['title']} · krok {n} z {total} · „dalej”, „powtórz”, „wróć”")
    lead = "Ostatni krok: " if n == total else f"Krok {n}: "
    offer = ""
    c["offer"] = None
    if s["minutes"]:
        import timers
        offer = f" Nastawić minutnik na {timers.say_duration(s['minutes'] * 60)}?"
        c["offer"] = s["minutes"]
    speak(lead + s["text"] + offer)
    _keep_listening()


def start(dish, speak):
    global _c
    speak(f"Już szukam przepisu na {dish}.")
    try:
        rec = _recipe(dish)
    except Exception as e:
        print(f"[cooking] recipe failed: {e}", flush=True)
        rec = None
    if not rec:
        speak("Nie udało mi się znaleźć przepisu. Spróbuj powiedzieć to inaczej.")
        return
    with _lock:
        _c = dict(rec, i=-1, t=time.time(), offer=None)
    print(f"[cooking] {rec['title']}: {len(rec['ingredients'])} ingredients, "
          f"{len(rec['steps'])} steps", flush=True)
    ing = rec["ingredients"]
    _card(rec["title"], f"{len(ing)} składników · powiedz „dalej”, gdy wszystko masz")
    speak(f"{rec['title']}! Potrzebujesz: " + ", ".join(ing) + ". Kiedy wszystko "
          "będzie pod ręką, powiedz: dalej." if ing else f"{rec['title']}! Powiedz: dalej.")
    _keep_listening()


def answer(text, speak):
    """An utterance while cooking. True when it was about the recipe."""
    global _c
    low = text.lower().strip(" .!?")
    words = re.findall(r"\w+", low)
    with _lock:
        c = _c
        if c is None:
            return False
        c["t"] = time.time()
        if c.get("offer") and any(w in words for w in _YES) and len(words) <= 4:
            import timers
            mins = c["offer"]
            c["offer"] = None
            timers.add(mins * 60, c["steps"][c["i"]]["text"][:40])
            speak(f"Minutnik na {timers.say_duration(mins * 60)} ustawiony.")
            _keep_listening()
            return True
        if any(k in low for k in _STOP) and len(words) <= 4:
            _c = None
            _clear()
            speak("Smacznego!")
            return True
        if any(k in low for k in _AGAIN) and len(words) <= 4:
            if c["i"] < 0:
                speak("Potrzebujesz: " + ", ".join(c["ingredients"]) + ".")
                _keep_listening()
            else:
                _say_step(speak)
            return True
        if any(k in low for k in _BACK) and len(words) <= 4:
            c["i"] = max(0, c["i"] - 1)
            _say_step(speak)
            return True
        if any(w in words for w in _NEXT) and len(words) <= 5:
            c["i"] += 1
            if c["i"] >= len(c["steps"]):
                _c = None
                _clear()
                speak("To wszystko! Smacznego!")
                return True
            _say_step(speak)
            return True
        if len(words) <= 2 and c.get("offer") and any(w in ("nie", "no") for w in words):
            c["offer"] = None
            speak("Dobrze. Powiedz: dalej, kiedy skończysz.")
            _keep_listening()
            return True
    return False                      # a question about something else: the model
