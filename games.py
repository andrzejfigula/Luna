"""
games.py — rock, paper, scissors with Luna.

"Luna, zagrajmy w kamień, papier, nożyce!" — best of three. Each round:
a big 3-2-1 counts down between her eyes (with ticks), on "!" her hand on the
screen shows her pick — chosen at random BEFORE she looks, she plays fair —
and she reads yours from the camera (one vision call). Then the verdict, the
score, and at the end a rematch offer: "tak" / "jeszcze raz" within
REMATCH_SECS starts a new match without naming the game again.

Runs in the voice thread (commands.handle), so the microphone simply waits
until the game is over.
"""

import random
import re
import time

from shared_state import state

CHOICES = ["rock", "paper", "scissors"]
PL      = {"rock": "kamień", "paper": "papier", "scissors": "nożyce"}
BEATS   = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

REMATCH_SECS = 25
_rematch_until = 0.0

_NAMES = {"kamień", "kamien", "papier", "nożyce", "nozyce", "rock", "paper", "scissors"}
_YES = {"tak", "jasne", "dawaj", "gramy", "jeszcze", "rewanż", "rewanz", "ok", "okej",
        "pewnie", "chętnie", "chetnie", "yes", "again"}


def is_trigger(text):
    words = set(re.findall(r"\w+", text.lower()))
    return len(words & _NAMES) >= 2


def is_rematch(text):
    words = re.findall(r"\w+", text.lower())
    return time.time() < _rematch_until and len(words) <= 5 and bool(set(words) & _YES)


def _big(text, secs):
    with state.lock:
        state.big_text = (text, time.time() + secs)


def _hand(choice, secs):
    with state.lock:
        state.game_hand = (choice, time.time() + secs) if choice else None


def _mood(emotion):
    with state.lock:
        state.emotion = emotion


def _round(play_sound_async, classify_hand, camera_jpeg):
    """One throw. Returns (mine, yours) — yours is None when she couldn't
    see a hand."""
    mine = random.choice(CHOICES)                     # decided before looking
    for n in ("3", "2", "1"):
        _big(n, 0.75)
        play_sound_async("tick")
        time.sleep(0.75)
    _big("!", 0.9)
    _hand(mine, 4.0)
    play_sound_async("tick")
    # three looks over ~1.2 s, judged together: one frame 0.45 s after "!"
    # caught the hand still rising or blurred — "Nie widzę twojej ręki" twice
    # in a row for Andrzej (7 Oct)
    imgs = []
    for wait in (0.35, 0.4, 0.45):
        time.sleep(wait)
        img = camera_jpeg()
        if img:
            imgs.append(img)
    yours = classify_hand(imgs) if imgs else None
    print(f"[game] me: {mine}, you: {yours}", flush=True)
    return mine, yours


def _verdict(mine, yours):
    if mine == yours:
        return "draw"
    return "me" if BEATS[mine] == yours else "you"


def play_match(speak, play_sound_async):
    """Best of three. Blocks until the match is over."""
    global _rematch_until
    from brain import classify_hand, _camera_jpeg_b64

    _mood("Excited")
    speak("Super, gramy do dwóch wygranych! Pokaż rękę do kamery, kiedy zobaczysz wykrzyknik.")
    me = you = misses = 0
    while me < 2 and you < 2:
        mine, yours = _round(play_sound_async, classify_hand, _camera_jpeg_b64)
        if yours is None:
            misses += 1
            _mood("Surprised")
            if misses >= 2:
                speak("Nie widzę twojej ręki. Zagramy, jak będziesz bliżej kamery!")
                break
            speak("Nie widzę twojej ręki — trzymaj ją przed kamerą. Jeszcze raz!")
            continue
        v = _verdict(mine, yours)
        if v == "me":
            me += 1
            _mood("Happy")
            line = random.choice(["wygrałam!", "punkt dla mnie!", "mam cię!"])
        elif v == "you":
            you += 1
            _mood("Sad")
            line = random.choice(["wygrywasz.", "punkt dla ciebie.", "no nie…"])
        else:
            _mood("Surprised")
            line = random.choice(["remis!", "myślimy tak samo!"])
        score = f"{me} do {you}" if (me < 2 and you < 2) else ""
        speak(f"Ja {PL[mine]}, ty {PL[yours]} — {line}" + (f" {score}." if score else ""))
    if me == 2:
        _mood("Excited")
        speak(f"Wygrałam {me} do {you}! Rewanż?")
    elif you == 2:
        _mood("Love")
        speak(f"Wygrywasz {you} do {me}. Gratulacje! Rewanż?")
    _mood("Neutral")
    _hand(None, 0)
    _rematch_until = time.time() + REMATCH_SECS
    with state.lock:                        # keep listening for "tak!"
        state.conversation_active = True
        state.last_activity_time = time.time()
