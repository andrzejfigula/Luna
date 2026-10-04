"""
breathing.py — a guided breathing exercise, only when you ask for it.

"Luna, ćwiczenie oddechowe" / "pomóż mi się uspokoić": a soft circle on her
screen grows while you breathe in, holds, and shrinks while you breathe out
(BREATH_IN / BREATH_HOLD / BREATH_OUT seconds, a longer out-breath calms),
BREATH_CYCLES times. Her "wdech" / "wydech" are recorded once (sounds.py), so
they land exactly on the phase changes. A tap on the screen ends it.
"""

import time

from shared_state import state
from config import BREATH_IN, BREATH_HOLD, BREATH_OUT, BREATH_CYCLES

TRIGGERS = ("ćwiczenie oddechowe", "cwiczenie oddechowe", "ćwiczenia oddechowe",
            "pooddychajmy", "pomóż mi się uspokoić", "pomoz mi sie uspokoic",
            "breathing exercise", "oddychajmy razem")


def is_trigger(low):
    return any(k in low for k in TRIGGERS)


def run(speak, play_sound):
    """Blocks for the whole exercise (voice thread)."""
    with state.lock:
        state.emotion = "Love"
    speak("Dobrze. Usiądź wygodnie i oddychaj razem ze mną.")
    cycle = BREATH_IN + BREATH_HOLD + BREATH_OUT
    t0 = time.time() + 0.3
    with state.lock:
        state.overlay = ("breath", t0 + BREATH_CYCLES * cycle + 0.6,
                         (t0, BREATH_IN, BREATH_HOLD, BREATH_OUT))
    for i in range(BREATH_CYCLES):
        start = t0 + i * cycle
        for at, sound in ((0.0, "inhale"), (BREATH_IN + BREATH_HOLD, "exhale")):
            while time.time() < start + at:
                with state.lock:
                    if state.overlay is None or state.overlay[0] != "breath":
                        state.emotion = "Neutral"
                        return                      # tapped away
                time.sleep(0.02)
            play_sound(sound, can_drop=False)
    while True:                                     # let the last breath finish
        with state.lock:
            ov = state.overlay
        if not ov or ov[0] != "breath" or time.time() >= ov[1]:
            break
        time.sleep(0.05)
    speak("Brawo. Jak się teraz czujesz?")
    with state.lock:
        state.emotion = "Neutral"
