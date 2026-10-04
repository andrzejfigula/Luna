"""
fun.py — small on-request games and gadgets (all local, no model call).

  "włącz lampkę"           → night light: a warm glow over the whole screen
                             until "wyłącz lampkę" or a tap
  "przybij piątkę"         → her hand comes up; tap the screen within 4 s
  "rzuć kostką"            → a die rolls on her screen ("dwiema kostkami": two)
  "rzuć monetą" / "orzeł czy reszka" → a coin flips

robot_face.py draws the overlays ("lamp", "dice", "coin"); see screens.py for
the overlay mechanism. None of these run on their own.
"""

import random
import re
import time

from shared_state import state

LAMP_ON  = ("włącz lampkę", "zapal lampkę", "włącz lampkę nocną", "tryb lampki",
            "wlacz lampke", "night light", "turn on the lamp")
LAMP_OFF = ("wyłącz lampkę", "zgaś lampkę", "wylacz lampke", "zgas lampke",
            "turn off the lamp")
HIGH_FIVE = ("przybij piątkę", "daj piątkę", "przybijemy piątkę", "przybij piatke",
             "high five")
DICE = ("rzuć kostką", "rzuć kością", "rzuc kostka", "rzuć kostkami", "roll a die",
        "roll the dice", "roll a dice")
COIN = ("rzuć monetą", "rzuc moneta", "orzeł czy reszka", "orzel czy reszka",
        "flip a coin", "rzuć monetę")

LAMP_HOURS = 10


def _overlay(kind, secs, data=None):
    with state.lock:
        state.overlay = (kind, time.time() + secs, data)


def _mood(emotion):
    with state.lock:
        state.emotion = emotion


def lamp_on():
    _overlay("lamp", LAMP_HOURS * 3600)


def lamp_off():
    with state.lock:
        if state.overlay and state.overlay[0] == "lamp":
            state.overlay = None


def high_five(speak, play_sound):
    t0 = time.time()                 # any touch from the moment the hand is up
    with state.lock:                 # counts — even one that cuts "Przybij!"
        state.game_hand = ("paper", t0 + 7.0)
    _mood("Happy")
    speak("Przybij!")
    t_end = time.time() + 4.0
    touched = False
    while time.time() < t_end:
        with state.lock:
            touched = state.touch_time > t0
        if touched:
            break
        time.sleep(0.03)
    with state.lock:
        state.game_hand = None
    if touched:
        play_sound("giggle", can_drop=False)
        _mood("Excited")
        speak(random.choice(["Piątka!", "Jest piątka!", "Ale mocna!"]))
    else:
        _mood("Sad")
        speak("Hej, nie zostawiaj mnie z ręką w powietrzu!")
    _mood("Neutral")


_PL_DICE = {1: "jeden", 2: "dwa", 3: "trzy", 4: "cztery", 5: "pięć", 6: "sześć"}


def roll(speak, play_sound_async, low):
    two = bool(re.search(r"\b(dwiema|dwoma|dwie|2)\b", low)) or "kostkami" in low
    results = [random.randint(1, 6) for _ in range(2 if two else 1)]
    _overlay("dice", 3.6, {"results": results, "t0": time.time()})
    for _ in range(4):
        play_sound_async("tick")
        time.sleep(0.28)
    time.sleep(0.2)
    if two:
        speak(f"{_PL_DICE[results[0]].capitalize()} i {_PL_DICE[results[1]]} — "
              f"razem {sum(results)}!")
    else:
        speak(f"Wypadło {_PL_DICE[results[0]]}!")


def flip(speak, play_sound_async):
    side = random.choice(["orzeł", "reszka"])
    _overlay("coin", 3.4, {"side": side, "t0": time.time()})
    play_sound_async("tick")
    time.sleep(1.5)
    speak(side.capitalize() + "!")


def handle(text, speak, play_sound, play_sound_async):
    low = text.lower()
    words = re.findall(r"\w+", low)
    if len(words) > 8 or low.strip().endswith("?") and not any(k in low for k in COIN):
        return False
    if any(k in low for k in LAMP_OFF):
        lamp_off()
        return True
    if any(k in low for k in LAMP_ON):
        lamp_on()
        return True
    if any(k in low for k in HIGH_FIVE):
        high_five(speak, play_sound)
        return True
    if any(k in low for k in DICE) or re.search(r"\brzu[cć]\w*\b.*\bko(st|ś)", low):
        roll(speak, play_sound_async, low)
        return True
    if any(k in low for k in COIN):
        flip(speak, play_sound_async)
        return True
    return False
