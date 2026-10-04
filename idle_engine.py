"""
idle_engine.py — Luna between conversations.

  • Noticing you. When you come back after a while she brightens up, waves and
    (sometimes) says hello; the greeting depends on the time of day and on
    whether it's the first time she's seen you today.

  • Touch. robot_face.py draws the instant visual response; this module adds
    the voice — now and then a spoken line, otherwise often a little sound.

Speech is the scarce resource: unprompted talking gets old fast and costs an
API call, so it is rate-limited (PROACTIVE_MIN_GAP_SECS), silenced during
quiet hours, and can be muted by saying "Luna, cicho" (see check_mute()).

She plays no animations of her own here: body-language scenes only run as
part of a reply (reply_scenes.py, chosen by the model in brain.py).
"""

import random
import threading
import time

from shared_state import state
from config import (IDLE_ABSENCE_SECS, IDLE_PRESENCE_GRACE, IDLE_DEBUG,
                    PROACTIVE_SPEECH, PROACTIVE_MIN_GAP_SECS,
                    PROACTIVE_QUIET_FROM, PROACTIVE_QUIET_TO,
                    GREETINGS_MORNING, GREETINGS_DAY, GREETINGS_EVENING,
                    GREETINGS_NIGHT, GREETINGS_FIRST_TODAY,
                    MUTE_PHRASES, UNMUTE_PHRASES, MUTE_SECS,
                    TOUCH_REPLIES, TOUCH_REPLY_CHANCE, TOUCH_SPEECH_COOLDOWN,
                    TOUCH_SOUNDS, TOUCH_SOUND_CHANCE, TOUCH_SOUND_COOLDOWN,
                    GESTURE_DURATION, FACE_OVERRIDE_SECS)

_last_proactive = 0.0


# ── quiet / mute ──────────────────────────────────────────────────────────────

def check_mute(text):
    """Called from the voice loop with every recognised utterance. Returns
    True when the utterance was a mute/unmute command (so it needn't reach
    the brain)."""
    low = text.lower().strip(" .!?")
    if any(p in low for p in MUTE_PHRASES):
        with state.lock:
            state.proactive_muted_until = time.time() + MUTE_SECS
        print(f"[idle] proactive speech muted for {MUTE_SECS / 60:.0f} min")
        return True
    if any(p in low for p in UNMUTE_PHRASES):
        with state.lock:
            state.proactive_muted_until = 0.0
        print("[idle] proactive speech back on")
        return True
    return False


def _hour():
    return time.localtime().tm_hour


def _quiet_now():
    h = _hour()
    if PROACTIVE_QUIET_FROM <= PROACTIVE_QUIET_TO:
        return PROACTIVE_QUIET_FROM <= h < PROACTIVE_QUIET_TO
    return h >= PROACTIVE_QUIET_FROM or h < PROACTIVE_QUIET_TO


def _asleep():
    """Asleep ("dobranoc") or focusing ("tryb skupienia"): no small talk."""
    with state.lock:
        return state.sleep_mode or time.time() < state.focus_until


def _may_speak():
    """Unprompted speech allowed right now?"""
    if not PROACTIVE_SPEECH or _quiet_now() or _asleep():
        return False
    with state.lock:
        muted = state.proactive_muted_until
    return time.time() > muted and time.time() - _last_proactive >= PROACTIVE_MIN_GAP_SECS


def _busy():
    with state.lock:
        return (state.speaking or state.conversation_active
                or state.luna_mode in ("listening", "processing", "speaking"))


def _voice_allowed(now):
    """Quiet hours and "Luna, cicho" apply to every sound she makes on her
    own — touch sounds included."""
    with state.lock:
        muted = state.proactive_muted_until
    return not _quiet_now() and not _asleep() and now > muted


# ── actions ───────────────────────────────────────────────────────────────────

def _touch_sound(zone, kind):
    choices = TOUCH_SOUNDS.get((zone, kind)) or TOUCH_SOUNDS.get((None, kind))
    return random.choice(choices) if choices else None


def _gesture(name):
    with state.lock:
        state.gesture_anim       = name
        state.gesture_anim_start = time.time()


def _set_face(mood, secs=FACE_OVERRIDE_SECS):
    with state.lock:
        state.face_override       = mood
        state.face_override_until = time.time() + secs


def _greeting(first_today):
    if first_today and GREETINGS_FIRST_TODAY:
        return random.choice(GREETINGS_FIRST_TODAY)
    h = _hour()
    if 5 <= h < 11:
        return random.choice(GREETINGS_MORNING)
    if 11 <= h < 18:
        return random.choice(GREETINGS_DAY)
    if 18 <= h < 22:
        return random.choice(GREETINGS_EVENING)
    return random.choice(GREETINGS_NIGHT)


# ── main loop ─────────────────────────────────────────────────────────────────

def idle_loop():
    # she has been alone since start-up, so the first person to show up after
    # a long boot-time absence gets greeted too. Stamped BEFORE the import
    # below, which builds the TTS engine (a few seconds).
    left_at = time.time()

    # deferred — avoids a circular import
    from text_to_speech import speak, play_sound_async
    global _last_proactive

    was_present  = False
    last_touch_t = 0.0
    last_touch_say = 0.0
    last_touch_sound = 0.0
    greeted_day  = None                  # date of the last "first time today"

    while True:
        try:
            now = time.time()
            with state.lock:
                last_face  = state.last_face_time
                touch_kind = state.touch_kind
                touch_t    = state.touch_time
                touch_zone = state.touch_zone
            # debounced presence: the detector drops frames several times a
            # minute, and raw face_detected would keep resetting the timers
            present = (now - last_face) <= IDLE_PRESENCE_GRACE

            # ── someone came back ────────────────────────────────────────
            if present != was_present and IDLE_DEBUG:
                print(f"[idle] presence {was_present} -> {present} "
                      f"(away {now - left_at:.0f}s, busy={_busy()})", flush=True)
            if present and not was_present:
                away = now - left_at
                if away >= IDLE_ABSENCE_SECS and not _busy() and not _asleep():
                    today = time.strftime("%Y-%m-%d")
                    first_today = greeted_day != today
                    greeted_day = today
                    print(f"[idle] welcome back (away {away / 60:.0f} min)")
                    _set_face("happy", GESTURE_DURATION["wave"] + 2.0)
                    _gesture("wave")
                    if _may_speak():
                        _last_proactive = now
                        # the first hello of the day knows your day (weather,
                        # reminders, memory); later ones are short phrases
                        from brain import greeting
                        speak(greeting(first_today) or _greeting(first_today),
                              can_drop=True)
                        import messages
                        if messages.unheard():
                            speak("Masz nową wiadomość głosową. Powiedz: odtwórz "
                                  "wiadomość.", can_drop=True)
            elif was_present and not present:
                left_at = now
            was_present = present

            # ── finger held on the screen: "I want to talk to you" ───────
            if touch_t > last_touch_t and touch_kind == "hold":
                last_touch_t = touch_t
                with state.lock:
                    already = state.conversation_active
                    state.conversation_active = True
                    state.last_activity_time  = now
                if not already:
                    print("[idle] finger held on the screen — listening")
                    from commands import wake_up
                    wake_up("finger held on the screen")
                    play_sound_async("huh")       # "hm?" — I'm listening

            # ── reaction to being touched (voice; visuals are in the face)
            if touch_t > last_touch_t and touch_kind != "stop":
                last_touch_t = touch_t
                replies = TOUCH_REPLIES.get(touch_zone or "other", {}).get(touch_kind)
                # you started this, so it isn't rationed like unprompted talk —
                # it only needs its own short cooldown (mute + quiet hours apply)
                if (replies and not _busy() and _voice_allowed(now)
                        and now - last_touch_say >= TOUCH_SPEECH_COOLDOWN
                        and random.random() < TOUCH_REPLY_CHANCE):
                    last_touch_say = now
                    speak(random.choice(replies), can_drop=True)
                # no words this time → often a little sound (a giggle, "ej!")
                elif (not _busy() and _voice_allowed(now)
                        and now - last_touch_sound >= TOUCH_SOUND_COOLDOWN
                        and random.random() < TOUCH_SOUND_CHANCE):
                    snd = _touch_sound(touch_zone, touch_kind)
                    if snd:
                        last_touch_sound = now
                        play_sound_async(snd)

        except Exception as e:
            print(f"[idle] loop error (recovering): {e}")
            time.sleep(2.0)
        time.sleep(0.5)


def start_idle():
    t = threading.Thread(target=idle_loop, daemon=True)
    t.name = "idle"
    t.start()
