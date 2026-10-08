# shared_state.py
from threading import Lock, RLock
import time


class SharedState:

    __slots__ = (
        "lock",
        "frame",
        "face_detected", "face_x", "face_y",
        "face_w",                # face width as a fraction of the frame width
        "emotion",
        "frozen_emotion",        # emotion locked while speaking
        "gesture",
        "gesture_time",          # time.time() the gesture was detected
        "reply_scene",           # body-language scene the model picked for
                                 # its reply (reply_scenes.py) | None
        "reply_scene_start",     # time.time() it started
        "touch_kind",            # last touch: "tap" | "stroke" | "multi"
        "touch_x", "touch_y",    # where, normalised 0..1
        "touch_time",            # time.time() of that touch
        "touch_zone",            # "eye" | "mouth" | "top" | "other"
        "proactive_muted_until", # no unprompted speech before this time
        "gesture_anim",          # animation Luna is performing: "nod" | "shake"
                                 # | "wave" | "thumbs_up" | "heart" | None
        "gesture_anim_start",    # time.time() it started
        "heard_text", "response",
        "speaking", "listening",
        "audio_energy",
        "audio_playing",         # True only while real TTS audio is playing
                                 # (drives lip sync; speaking stays True for the
                                 # whole call so the mic stays blocked)
        "look_dir",
        "servo_action",
        "conversation_active",
        "convo_expired_time",    # time.time() when conversation last timed out
        "last_activity_time",
        "last_wake_time",        # her name was just said (speech_to_text)
        "mic_unblock_time",      # time.time() after which mic is allowed
        "luna_mode",             # "idle" | "listening" | "processing" | "speaking"
        "face_override",         # temporary face state ("excited" | "love" | None)
        "face_override_until",   # time.time() when the override expires
        "mic_ok",                # False when no working microphone was found
        "camera_ok",             # False when no working camera was found
        "last_face_time",        # time.time() a face was last seen (addressed-
                                 # speech gate: people talking TO Luna face her)
        "last_spoken_text",      # Luna's most recent utterance (lowercased)
        "last_spoken_time",      # time.time() when that utterance finished
        "light",                 # log10(room light) from the camera, smoothed
                                 # (camera_thread.py) — None until measured
        "focus_until",           # "tryb skupienia": no small talk until then
        "costume",               # (kind, until): cat / dog / bunny ears on her face
        "bare_wake",             # the window holds only her name so far ("hm?")
        "overlay",               # (kind, until, data): mirror / photo / clock /
                                 # flash over the whole screen (screens.py)
        "sunrise",               # (start, end) of a wake-up alarm's dawn:
                                 # the screen brightens until end (timers.py)
        "messages_waiting",      # unheard voice messages (messages.py)
        "radio",                 # the station playing (radio.py), or None
        "mic_muted_until",       # "nie słuchaj": no audio is processed until then
                                 # (a finger held on the screen ends it)
        "heard_at",              # when the last utterance's speech really ended —
                                 # her first sound after it logs the latency
        "motion",                # (x 0..1 mirrored like face_x, y 0..1, strength
                                 # 0..1, time): where things move in the camera
                                 # picture (gesture_module) — her eyes follow it
        "layout",                # ([(name or "?", x 0..1 across the frame)], time):
                                 # who is where in the camera picture (vision_module)
        "others",                # ([names, "?" = unknown], time) — the other faces
                                 # in view besides state.person (faces.py)
        "person",                # (name, similarity, time) — who is in front of her
                                 # (faces.py), or None
        "convo_closed_hard",     # the window was closed on purpose ("pa!", radio):
                                 # no grace for speech that began just after
        "voice_mood",            # forces the TTS delivery ("sleepy" for the
                                 # bedtime story) — None = the reply's emotion
        "caption",               # (who, text, until): subtitles — "luna" or
                                 # "you" (drawn when captions are on)
        "online",                # the cloud answered last time (health.py)
        "big_text",              # (text, until): a big glyph between her eyes
                                 # (the rock-paper-scissors countdown)
        "game_hand",             # (choice, until): her hand shows rock /
                                 # paper / scissors (games.py)
        "timer_text",            # nearest timer for the corner of the screen
                                 # ("7:42") or None (timers.py)
        "sleep_mode",            # "dobranoc" → asleep until morning or until
                                 # spoken to (commands.py)
        "user_mood",             # how the user seemed on camera at the last
                                 # reply (brain.USER_MOODS), "no_person"
    )

    def __init__(self):
        # re-entrant: a helper that takes the lock, called by code already
        # holding it, must not freeze every thread (it did on 4 Oct)
        self.lock                = RLock()
        self.frame               = None
        self.face_detected       = False
        self.face_x              = 0.5
        self.face_y              = 0.5
        self.face_w              = 0.2
        self.emotion             = "Neutral"
        self.frozen_emotion      = None
        self.gesture             = None
        self.gesture_time        = 0.0
        self.reply_scene         = None
        self.reply_scene_start   = 0.0
        self.touch_kind          = None
        self.touch_x             = 0.5
        self.touch_y             = 0.5
        self.touch_time          = 0.0
        self.touch_zone          = None
        self.proactive_muted_until = 0.0
        self.gesture_anim        = None
        self.gesture_anim_start  = 0.0
        self.heard_text          = ""
        self.response            = ""
        self.speaking            = False
        self.listening           = False
        self.audio_energy        = 0.0
        self.audio_playing       = False
        self.look_dir            = None
        self.servo_action        = None
        self.conversation_active = False
        self.convo_expired_time  = 0.0
        self.last_activity_time  = 0.0
        self.last_wake_time      = 0.0
        self.mic_unblock_time    = 0.0
        self.luna_mode           = "idle"
        self.face_override       = None
        self.face_override_until = 0.0
        self.mic_ok              = True
        self.camera_ok           = True
        self.last_face_time      = 0.0
        self.last_spoken_text    = ""
        self.last_spoken_time    = 0.0
        self.user_mood           = "no_person"
        self.sleep_mode          = False
        self.timer_text          = None
        self.big_text            = None
        self.online              = True
        self.caption             = None
        self.voice_mood          = None
        self.messages_waiting    = 0
        self.radio               = None
        self.mic_muted_until     = 0.0
        self.person              = None
        self.others              = ([], 0.0)
        self.layout              = ([], 0.0)
        self.heard_at            = 0.0
        self.motion              = None
        self.convo_closed_hard   = False
        self.sunrise             = None
        self.overlay             = None
        self.costume             = None
        self.bare_wake           = False
        self.focus_until         = 0.0
        self.light               = None
        self.game_hand           = None


state = SharedState()