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
                    WAVE_CONFIRM_MIN_GAP, WAVE_SPEAK_GAP, WAVE_BACK_GAP)

_last_confirm = 0.0

_last_react = {}   # gesture name → last reaction time


_WAVE_FILE = "/tmp/luna_wave.json"   # survives restarts (not reboots): 7 Oct, each of
                                     # ~25 restarts reset the gaps — 17 spoken hellos


def _load_wave():
    try:
        import json
        with open(_WAVE_FILE) as f:
            d = json.load(f)
        return float(d.get("said", 0.0)), float(d.get("back", 0.0))
    except Exception:
        return 0.0, 0.0


def _save_wave():
    try:
        import json
        with open(_WAVE_FILE, "w") as f:
            json.dump({"said": _last_wave_said, "back": _last_wave_back}, f)
    except Exception:
        pass


_last_wave_said, _last_wave_back = _load_wave()


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
        busy     = (state.speaking or state.sleep_mode
                    or state.luna_mode in ("processing", "speaking"))
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
        global _last_wave_back
        if time.time() - _last_wave_back < WAVE_BACK_GAP:
            return                         # a "wave" again so soon: most likely typing
        _last_wave_back = time.time()
        _save_wave()
        print("[behavior] waving back")
        _set_face("happy", GESTURE_DURATION["wave"] + 1.5)
        with state.lock:
            state.gesture_anim       = "wave"
            state.gesture_anim_start = time.time()
        global _last_wave_said
        with state.lock:
            muted = time.time() < state.proactive_muted_until    # "cicho", a call
            # just talked with her: a hand moving is gesturing, not hello
            # (7 Oct 21:15 — "Cześć!" right after Andrzej's "To super")
            muted = muted or time.time() - state.last_activity_time < 180
            muted = muted or state.sleep_mode or time.time() < state.focus_until
        try:
            import idle_engine                  # quiet hours: the wave, no words
            muted = muted or idle_engine._quiet_now()
        except Exception:
            pass
        try:
            import speech_to_text
            muted = muted or speech_to_text.people_talking()   # they are talking
        except Exception:
            pass
        if not in_convo and not muted and time.time() - _last_wave_said > WAVE_SPEAK_GAP:
            _last_wave_said = time.time()
            _save_wave()
            # someone she knows waving, who hasn't had their first hello today:
            # that hello, with the day in it (8 Oct 8:03 — "O, cześć!" to
            # Andrzej, whose morning briefing was still due; 93% rain)
            hello = None
            with state.lock:
                who = state.person[0] if state.person else None
            try:
                import idle_engine
                if who and idle_engine.first_hello_due(who):
                    from brain import greeting
                    hello = greeting(True, who=who)
                    if hello:
                        idle_engine.mark_greeted(who)
            except Exception as e:
                print(f"[behavior] first hello failed: {e}", flush=True)
            speak(hello or random.choice(WAVE_REPLIES), can_drop=True)


def start_behavior():
    t = threading.Thread(target=behavior_loop, daemon=True)
    t.name = "behavior"
    t.start()
