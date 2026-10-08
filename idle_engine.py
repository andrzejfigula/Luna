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

import os
import random
import re
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
    # "bądź cicho przez godzinę", "nie przeszkadzaj do rana" (7 Oct probe: the
    # words after "cicho" sent it to the model, which answered "dobrze, będę
    # cicho" and changed her speech speed instead)
    import timers
    secs, used = timers.parse_duration(low)
    until_morning = bool(re.search(r"\bdo\s+(?:rana|jutra)\b", low))
    extra = set(used or ()) | {"przez", "na", "do", "rana", "jutra"}

    def bare(phrases, allow=()):
        # the phrase and only fillers around it: "Luna, cicho!" — not "za cicho",
        # "jest cicho w domu" or "możesz mówić wolniej?" (that one was swallowed)
        hit = max((p for p in phrases if p in low), key=len, default=None)
        if not hit:
            return False
        rest = re.findall(r"\w+", low.replace(hit, " ", 1))
        return all(w in ("luna", "luno", "już", "juz", "teraz", "proszę", "prosze", "no",
                         "dobra", "ok", "okej", "hej", "a", "to") or w in allow for w in rest)

    if bare(MUTE_PHRASES, extra):
        how_long = MUTE_SECS
        if until_morning:
            t = time.localtime()
            hours = (PROACTIVE_QUIET_TO - t.tm_hour) % 24 or 24
            how_long = hours * 3600 - t.tm_min * 60
        elif secs:
            how_long = secs
        with state.lock:
            state.proactive_muted_until = time.time() + how_long
        print(f"[idle] proactive speech muted for {how_long / 60:.0f} min")
        return True
    if bare(UNMUTE_PHRASES):
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
    try:
        import speech_to_text
        if speech_to_text.people_talking():   # a call, or a chat between them
            return False
    except Exception:
        pass
    return time.time() > muted and time.time() - _last_proactive >= PROACTIVE_MIN_GAP_SECS


def _busy():
    with state.lock:
        return (state.speaking or state.conversation_active
                or state.luna_mode in ("listening", "processing", "speaking"))


def _people_talking():
    """A call or people talking to each other (speech_to_text) — a note for
    someone waits until it's over."""
    try:
        import speech_to_text
        return speech_to_text.people_talking()
    except Exception:
        return False


def _timed_errand_ok(who, now):
    """"Przypomnij jej rano, żeby wzięła kanapki" — asked for the early
    morning, like an alarm: said even in the quiet hours (at the night voice),
    from 5:00, unless "Luna, cicho" — Maja leaves for school before 8."""
    with state.lock:
        muted = state.proactive_muted_until
    if now <= muted or time.localtime(now).tm_hour < 5:
        return False
    try:
        import errands
        return any(e.get("at") for e in errands.waiting(who))
    except Exception:
        return False


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


# ── who has had their first hello today (kept across restarts) ────────────────

def _greeted_path():
    from config import DATA_DIR
    return os.path.join(DATA_DIR, "greeted.json")


def load_greeted():
    """{who or "?": "YYYY-MM-DD"} — a restart must not bring a second
    morning briefing."""
    import json
    try:
        with open(_greeted_path(), encoding="utf-8") as f:
            return {(None if k == "?" else k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def save_greeted(days):
    import json
    try:
        tmp = _greeted_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({("?" if k is None else k): v for k, v in days.items()}, f)
        os.replace(tmp, _greeted_path())
    except OSError as e:
        print(f"[idle] could not save greetings ({e})", flush=True)


# ── main loop ─────────────────────────────────────────────────────────────────

_greeted = {}          # who → the day of their first hello (shared with brain.py)


def first_hello_due(who):
    """Hasn't this person had their first hello (the briefing) today?"""
    return bool(who) and _greeted.get(who) != time.strftime("%Y-%m-%d")


def mark_greeted(who):
    """Their first talk of the day carried the briefing (brain.py): no second
    one when they come back to the desk later."""
    if who:
        _greeted[who] = time.strftime("%Y-%m-%d")
        save_greeted(_greeted)


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
    _greeted.update(load_greeted())
    greeted_days = _greeted              # who (None: unknown) → day of their first hello
    asked_name_at = 0.0                  # when she last asked a stranger their name
    errands_checked = 0.0                # notes to pass on (errands.py)

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
                    # give recognition a moment: the hello is by name — a full
                    # recognition cycle (RECOGNISE_EVERY 2.5 s); 1.5 s was too
                    # short and Andrzej was asked his name (7 Oct)
                    who = None
                    for _ in range(35):
                        with state.lock:
                            who = state.person[0] if state.person else None
                        if who:
                            break
                        time.sleep(0.1)
                    today = time.strftime("%Y-%m-%d")
                    # everyone gets their own first hello of the day — counted
                    # only once it is SAID: on 8 Oct Andrzej came in at 7:24, in
                    # the quiet hours, and the silent "welcome back" used up the
                    # morning briefing he should have had after eight
                    first_today = greeted_days.get(who) != today
                    print(f"[idle] welcome back{' ' + who if who else ''} "
                          f"(away {away / 60:.0f} min)")
                    # her face follows how she feels about them (relationship.py):
                    # a heart for someone she likes a lot, no wave for someone
                    # who was rude — the words that follow say the rest
                    import relationship
                    feel = relationship.score(who or relationship.SOMEONE)
                    if feel >= 3:
                        _set_face("love", GESTURE_DURATION["heart"] + 2.0)
                        _gesture("heart")
                    elif feel <= -1:
                        _set_face("neutral", 3.0)
                    else:
                        _set_face("happy", GESTURE_DURATION["wave"] + 2.0)
                        _gesture("wave")
                    if _may_speak():
                        _last_proactive = now
                        greeted_days[who] = today
                        if first_today:
                            save_greeted(greeted_days)
                        # the first hello of the day knows your day (weather,
                        # reminders, memory); later ones are short phrases
                        from brain import greeting
                        # a face she doesn't know, in a home whose faces she
                        # does: ask for the name (at most every 30 min)
                        import faces
                        stranger = (who is None and faces.names()
                                    and now - asked_name_at > 1800
                                    and not faces.probably_family())
                        if stranger:
                            asked_name_at = now
                        hello = (greeting(first_today, who=who, stranger=bool(stranger))
                                 or _greeting(first_today))
                        if stranger:
                            # the greeting took a second or two: recognised by now?
                            with state.lock:
                                late = state.person[0] if state.person else None
                            if late:
                                print(f"[idle] it's {late} after all — no stranger hello",
                                      flush=True)
                                who, stranger = late, False
                                asked_name_at = 0.0
                                hello = (greeting(first_today, who=who) or
                                         _greeting(first_today))
                        speak(hello, can_drop=True)
                        if "?" in hello and not stranger:
                            # she asked something ("…opowiesz mi żart?"): the answer
                            # needs no "Luna" — "puk puk" was lost on 6 Oct
                            with state.lock:
                                state.conversation_active = True
                                state.last_activity_time = time.time() + 8
                        if stranger:                  # the answer needs no "Luna"
                            import commands
                            commands.expect_name()
                            with state.lock:
                                state.conversation_active = True
                                state.last_activity_time = time.time() + 8
                        import messages
                        waiting = messages.unheard(who)
                        if waiting:
                            frm = {m.get("from") for m in waiting} - {None, who}
                            speak("Masz wiadomość głosową" + (f" od: {', '.join(sorted(frm))}"
                                  if frm else "") + ". Powiedz: odtwórz wiadomość.",
                                  can_drop=True)
            elif was_present and not present:
                left_at = now
            was_present = present

            # ── a note to pass on, and its person is right here ──────────
            if now - errands_checked > 5:
                errands_checked = now
                with state.lock:
                    p = state.person
                if (p and now - p[2] < 6 and not _busy()
                        and (_voice_allowed(now) or _timed_errand_ok(p[0], now))
                        and not _people_talking()):     # not into his video call
                    import errands
                    if errands.waiting(p[0]):
                        errands.deliver(p[0], lambda t: speak(t, can_drop=False))

            # ── finger held on the screen: "I want to talk to you" ───────
            if touch_t > last_touch_t and touch_kind == "hold":
                last_touch_t = touch_t
                with state.lock:
                    was_muted = now < state.mic_muted_until
                    state.mic_muted_until = 0.0          # the finger turns the mic on
                if was_muted:
                    print("[idle] finger held — microphone on again", flush=True)
                    speak("Znowu słucham!", can_drop=True)
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
