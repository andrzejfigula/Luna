"""
Family scenarios ON THE PI, through main.py's order of checks (check_mute →
check_forget → commands.handle → the model), with the REAL model and the real
forecast — silent (a stand-in text_to_speech), scratch data. Run by hand
(it costs a few cents), not by restart.sh:

    cd ~/luna && ./venv/bin/python -X utf8 tests/scenario_pi.py

Each scenario is a few turns of a real afternoon; the checks are the things
that broke on 7–8 Oct: a child's sum answered outright, a game not starting
after "W zagadki!", no umbrella for someone leaving in the rain, reading aloud
not answered, a cooking question without the recipe.
"""

import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-scenario-")
for f in ("people.json", "settings.json"):
    if os.path.exists(os.path.join(HERE, "data", f)):
        shutil.copy(os.path.join(HERE, "data", f), DATA)
os.environ["LUNA_DATA_DIR"] = DATA

_fake = type(sys)("text_to_speech")
for _n in ("speak", "speak_stream", "play_clip", "play_sound", "play_sound_async",
           "replay_last", "stop_speaking"):
    setattr(_fake, _n, lambda *a, **k: None)
sys.modules["text_to_speech"] = _fake

import ambience            # noqa: E402
import brain               # noqa: E402
import commands            # noqa: E402
import idle_engine         # noqa: E402
import radio               # noqa: E402
import reading             # noqa: E402
import screens             # noqa: E402
import weather             # noqa: E402
from idle_engine import check_mute     # noqa: E402
from memory import check_forget        # noqa: E402
from shared_state import state         # noqa: E402

radio.play = lambda *a, **k: None
ambience.play = lambda *a, **k: True
screens._take_photo = lambda *a: None
commands.set_volume = lambda v: v
commands.get_volume = lambda: 0.5
weather.start_weather()
for _ in range(30):
    if weather._summary and weather._today:
        break
    time.sleep(0.5)

failures = []


def turn(who, text, wake=False):
    """One utterance the way main.py handles it; returns what she said."""
    with state.lock:
        state.person = (who, 0.8, time.time()) if who else None
        state.face_detected = bool(who)
        state.last_face_time = time.time()
        if wake:
            state.last_wake_time = time.time()
    said = []
    if reading.armed():
        if reading.add(text) == "end":
            orig = brain.process
            brain.process = lambda t, **k: said.append(
                (brain._ask_openai(t, context=k.get("context")) or [""])[0])
            try:
                commands.reading_done(*reading.take())
            finally:
                brain.process = orig
        return " | ".join(said)
    if check_mute(text):
        return "(muted)"
    fr = check_forget(text)
    if fr:
        return fr
    h = commands.handle(text, lambda t, **k: said.append(t), lambda *a, **k: True)
    if h:
        if h != "recorded":
            brain.note_local(text, said)
        if isinstance(h, tuple) and h[0] == "ask":
            r = brain._ask_openai(h[1])
            said.append(r[0] if r else "")
        return " | ".join(said)
    r = brain._ask_openai(text)
    return r[0] if r else ""


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name} — {detail[:110]}", flush=True)
    if not ok:
        failures.append(name)


def fresh():
    brain._history.clear()
    idle_engine._greeted.clear()


# 1. Maja after school: a hint, not the result; a game after her offer
fresh()
turn("Maja", "Cześć Luna, wróciłam ze szkoły", wake=True)
a = turn("Maja", "Mam zadanie z matmy, ile to jest 36 podzielić na 4?")
check("child's sum: a hint, not 9", not re.search(r"\b9\b|dziewięć", a.lower()), a)
turn("Maja", "A teraz pobawimy się?")
a = turn("Maja", "W zagadki!")
check("\"W zagadki!\" after her offer starts the riddles", "zagad" in a.lower(), a)
turn("Maja", "Koniec")

# 2. Leaving in the morning: an umbrella when it is going to rain
fresh()
a = turn("Emilka", "Dobra, wychodzę do pracy, pa", wake=True)
rainy = (weather._today.get("rain") or 0) >= 50
check("leaving: a goodbye" + (" with an umbrella" if rainy else ""),
      ("parasol" in a) == rainy and bool(a), a)

# 3. Reading aloud: collected, then praised
fresh()
turn("Maja", "Luna, posłuchaj, jak czytam", wake=True)
turn("Maja", "Ala ma kota. Kot ma na imię Mruczek.")
a = turn("Maja", "Koniec")
check("reading aloud gets an answer about it", bool(a) and "Mrucz" in a, a)

# 4. Cooking along: a question between steps is answered from the recipe
fresh()
turn("Emilka", "Luna, gotujemy naleśniki", wake=True)
turn("Emilka", "Dalej")
a = turn("Emilka", "Ile mleka?")
check("cooking: \"Ile mleka?\" from the recipe", "szklank" in a.lower() or "ml" in a.lower(), a)
turn("Emilka", "Koniec gotowania")

# 5. Said with her name: answered, not taken for side talk
fresh()
a = turn("Andrzej", "Jestem zdenerwowany", wake=True)
check("with her name: answered", bool(a), a)

# 6. The shopping list by voice: add, read, cross off
import lists               # noqa: E402
import timers              # noqa: E402
fresh()
turn("Emilka", "Luna, dopisz mleko i chleb do zakupów", wake=True)
check("two items added", {"mleko", "chleb"} <= set(lists.get("zakupy")), str(lists.get("zakupy")))
a = turn("Emilka", "Co mam na liście zakupów?")
check("the list read back", "mleko" in a.lower() and "chleb" in a.lower(), a)
turn("Emilka", "Skreśl mleko")
check("crossed off", "mleko" not in lists.get("zakupy"), str(lists.get("zakupy")))

# 7. A reminder for tomorrow, then "what reminders?"
fresh()
turn("Emilka", "Luna, przypomnij mi jutro o ósmej o dentyście", wake=True)
a = turn("Emilka", "Jakie mam przypomnienia?")
check("tomorrow's reminder listed", "denty" in a.lower() and "jutro" in a.lower(), a)

# 8. A timer and "ile zostało?"
fresh()
turn("Andrzej", "Luna, nastaw minutnik na 10 minut", wake=True)
a = turn("Andrzej", "Ile zostało?")
check("time left told", bool(re.search(r"minut|sekund", a)), a)
turn("Andrzej", "Wyłącz minutnik")
check("timer gone", not timers.running_timer(), a)

# 9. A question in the middle of a quiz doesn't end it in silence
fresh()
turn("Maja", "Luna, zagrajmy w quiz", wake=True)
a = turn("Emilka", "Luna, jaka jest dziś pogoda?", wake=True)
check("weather answered during a quiz", bool(re.search(r"°|stopn|pada|słońc|chmur|deszcz", a)), a)
turn("Maja", "Koniec")

# 10. A sad child: comfort, not a lecture
fresh()
a = turn("Maja", "Luna, jestem smutna, pokłóciłam się z Zosią", wake=True)
check("comfort for a sad child", bool(a) and len(a) < 400, a)

print(f"[scenario] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}", flush=True)
shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if failures else 0)
