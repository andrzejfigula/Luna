"""
idle_engine.py — Luna's own life when nobody is talking to her.

Two jobs:

  • Noticing you. When you come back after a while she brightens up, waves and
    (sometimes) says hello; the greeting depends on the time of day and on
    whether it's the first time she's seen you today.

  • Micro-scenes. Every so often, while idle, she does something small and
    human: winks, stretches, yawns (more at night), glances around the room,
    or pulls out a clock and plays with it. These are purely visual — free,
    local, and they can run as often as we like.

Speech is the scarce resource: unprompted talking gets old fast and costs an
API call, so it is rate-limited (PROACTIVE_MIN_GAP_SECS), silenced during
quiet hours, and can be muted by saying "Luna, cicho" (see check_mute()).
Animations are not limited — movement is what makes her feel alive, the voice
is what makes her intrusive.

Touch reactions live here too: robot_face.py draws the instant visual
response, this module adds the occasional voice.
"""

import random
import threading
import time

from shared_state import state
import idle_scenes
from config import (IDLE_LIFE, IDLE_ABSENCE_SECS, IDLE_SCENE_MIN_SECS,
                    IDLE_SCENE_MAX_SECS, IDLE_SCENE_WEIGHTS,
                    IDLE_SCENES_DISABLED,
                    IDLE_PRESENCE_GRACE, IDLE_DEBUG,
                    PROACTIVE_SPEECH, PROACTIVE_MIN_GAP_SECS,
                    PROACTIVE_QUIET_FROM, PROACTIVE_QUIET_TO,
                    GREETINGS_MORNING, GREETINGS_DAY, GREETINGS_EVENING,
                    GREETINGS_NIGHT, GREETINGS_FIRST_TODAY,
                    MUTE_PHRASES, UNMUTE_PHRASES, MUTE_SECS,
                    TOUCH_REPLIES, TOUCH_REPLY_CHANCE, TOUCH_SPEECH_COOLDOWN,
                    IDLE_AFTER_TOUCH_SECS,
                    GESTURE_DURATION,
                    FACE_OVERRIDE_SECS, NIGHT_FROM, NIGHT_TO)

_last_proactive = 0.0
_forced_at = {}                  # calendar scene → when it last played
FORCED_COOLDOWN = 600            # and how long before it may play again


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


def _is_night():
    h = _hour()
    return h >= NIGHT_FROM or h < NIGHT_TO


def _quiet_now():
    h = _hour()
    if PROACTIVE_QUIET_FROM <= PROACTIVE_QUIET_TO:
        return PROACTIVE_QUIET_FROM <= h < PROACTIVE_QUIET_TO
    return h >= PROACTIVE_QUIET_FROM or h < PROACTIVE_QUIET_TO


def _may_speak():
    """Unprompted speech allowed right now?"""
    if not PROACTIVE_SPEECH or _quiet_now():
        return False
    with state.lock:
        muted = state.proactive_muted_until
    return time.time() > muted and time.time() - _last_proactive >= PROACTIVE_MIN_GAP_SECS


def _busy():
    with state.lock:
        return (state.speaking or state.conversation_active
                or state.luna_mode in ("listening", "processing", "speaking"))


def _face_free(now):
    """May a scene start now? One thing drives the face at a time: a scene
    must not start on top of a touch reaction, a wave/nod/heart, or a mood
    someone else put on her face (a reply's lingering emotion, a greeting).
    robot_face.py enforces the same order the other way round — a touch or a
    gesture cancels a scene that is already playing."""
    with state.lock:
        touch_t   = state.touch_time
        g_anim    = state.gesture_anim
        g_start   = state.gesture_anim_start
        override  = state.face_override
        over_end  = state.face_override_until
    if now - touch_t < IDLE_AFTER_TOUCH_SECS:
        return False
    if g_anim and now - g_start < GESTURE_DURATION.get(g_anim, 0.0):
        return False
    return not (override and now < over_end)


# ── actions ───────────────────────────────────────────────────────────────────

def _play(action):
    """Start a visual idle scene (robot_face animates it)."""
    now = time.time()
    sc  = idle_scenes.SCENES.get(action)
    with state.lock:
        state.idle_action       = action
        state.idle_action_start = now
        state.idle_action_reply = False
        if sc and sc.mood:
            state.face_override       = sc.mood
            state.face_override_until = now + sc.duration


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


def _pick_scene(face_present):
    return idle_scenes.pick(_is_night(), face_present,
                            IDLE_SCENE_WEIGHTS, IDLE_SCENES_DISABLED)


# ── main loop ─────────────────────────────────────────────────────────────────

def idle_loop():
    # she has been alone since start-up, so the first person to show up after
    # a long boot-time absence gets greeted too. Stamped BEFORE the import
    # below, which builds the TTS engine (a few seconds).
    left_at = time.time()

    from text_to_speech import speak     # deferred — avoids circular import
    global _last_proactive

    was_present  = False
    last_scene   = time.time()
    next_scene   = random.uniform(IDLE_SCENE_MIN_SECS, IDLE_SCENE_MAX_SECS)
    last_touch_t = 0.0
    last_touch_say = 0.0
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
                if away >= IDLE_ABSENCE_SECS and not _busy():
                    today = time.strftime("%Y-%m-%d")
                    first_today = greeted_day != today
                    greeted_day = today
                    print(f"[idle] welcome back (away {away / 60:.0f} min)")
                    _set_face("happy", GESTURE_DURATION["wave"] + 2.0)
                    _gesture("wave")
                    if _may_speak():
                        _last_proactive = now
                        speak(_greeting(first_today), can_drop=True)
                    last_scene = now      # don't fire a scene right after
            elif was_present and not present:
                left_at = now
            was_present = present

            # ── reaction to being touched (voice; visuals are in the face)
            if touch_t > last_touch_t:
                last_touch_t = touch_t
                last_scene = now          # the scene timer restarts after a touch
                replies = TOUCH_REPLIES.get(touch_zone or "other", {}).get(touch_kind)
                # you started this, so it isn't rationed like unprompted talk —
                # it only needs its own short cooldown (mute + quiet hours apply)
                with state.lock:
                    muted = state.proactive_muted_until
                if (replies and not _busy() and not _quiet_now()
                        and now > muted
                        and now - last_touch_say >= TOUCH_SPEECH_COOLDOWN
                        and random.random() < TOUCH_REPLY_CHANCE):
                    last_touch_say = now
                    speak(random.choice(replies), can_drop=True)

            # ── calendar moments jump the queue ──────────────────────────
            if IDLE_LIFE and not _busy() and _face_free(now):
                forced = idle_scenes.forced_scene(present, IDLE_SCENES_DISABLED)
                if forced and now - _forced_at.get(forced, 0) > FORCED_COOLDOWN:
                    _forced_at[forced] = now
                    print(f"[idle] moment: {forced}")
                    _play(forced)
                    last_scene = now

            # ── micro-scenes ─────────────────────────────────────────────
            if (IDLE_LIFE and not _busy() and now - last_scene >= next_scene
                    and _face_free(now)):
                scene = _pick_scene(present)
                if scene:
                    print(f"[idle] scene: {scene}")
                    _play(scene)
                last_scene = now
                next_scene = random.uniform(IDLE_SCENE_MIN_SECS, IDLE_SCENE_MAX_SECS)

        except Exception as e:
            print(f"[idle] loop error (recovering): {e}")
            time.sleep(2.0)
        time.sleep(0.5)


def start_idle():
    t = threading.Thread(target=idle_loop, daemon=True)
    t.name = "idle"
    t.start()
