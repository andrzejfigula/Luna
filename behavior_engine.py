"""
behavior_engine.py — reacts to gestures with the face + voice (no servos).

WAVE → Luna "waves back": happy face, her hand waves (state.gesture_anim,
       animated in robot_face.py) and a spoken greeting.

Interrupt rules (answering ALWAYS wins):
  • speaking or processing an answer     → gesture ignored
  • conversation window open (attentive) → face + wobble only, no speech
                                            (would talk over the user)
  • fully idle                           → full reaction with a greeting
A cooldown stops one long wave from triggering several greetings.
"""

import random
import threading
import time

from shared_state import state
from config import (GESTURE_REACT_COOLDOWN, FACE_OVERRIDE_SECS,
                    WAVE_REPLIES, GESTURE_DURATION, WAVE_CLOUD_CONFIRM,
                    WAVE_CONFIRM_MIN_GAP)

_last_confirm = 0.0

_last_react = {}   # gesture name → last reaction time


def _cooled(gesture):
    now = time.time()
    if now - _last_react.get(gesture, 0.0) < GESTURE_REACT_COOLDOWN:
        return False
    _last_react[gesture] = now
    return True


def _set_face(override, secs=FACE_OVERRIDE_SECS):
    # face_override survives whatever the renderer would otherwise show
    with state.lock:
        state.face_override       = override
        state.face_override_until = time.time() + secs


def behavior_loop():
    from text_to_speech import speak   # deferred — avoids circular import
    from brain import confirm_wave

    while True:
        try:
            _behavior_step(speak, confirm_wave)
        except Exception as e:
            # a reaction error must never kill the behavior thread
            print(f"[behavior] loop error (recovering): {e}")
            time.sleep(1.0)
        time.sleep(0.1)


def _behavior_step(speak, confirm_wave):
    global _last_confirm
    with state.lock:
        gesture  = state.gesture
        busy     = state.speaking or state.luna_mode in ("processing", "speaking")
        in_convo = state.conversation_active
        state.gesture = None          # consume

    if gesture is None or busy:
        return

    if gesture == "WAVE":
        if WAVE_CLOUD_CONFIRM:
            # motion looked like a wave — let the vision model decide whether
            # it's really an empty hand waving (vs. showing an object)
            if time.time() - _last_confirm < WAVE_CONFIRM_MIN_GAP:
                return
            _last_confirm = time.time()
            if not confirm_wave():
                print("[behavior] motion looked like a wave, but it isn't one")
                return
        if not _cooled("WAVE"):
            return
        print("[behavior] waving back")
        _set_face("happy", GESTURE_DURATION["wave"] + 1.5)
        with state.lock:
            state.gesture_anim       = "wave"
            state.gesture_anim_start = time.time()
        if not in_convo:
            speak(random.choice(WAVE_REPLIES), can_drop=True)


def start_behavior():
    t = threading.Thread(target=behavior_loop, daemon=True)
    t.name = "behavior"
    t.start()
