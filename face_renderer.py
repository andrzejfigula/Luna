import time
from shared_state import state
from robot_face import RobotFace
import lamp_scenes
import ui_screens
import settings_page                       # the face's fps can be set on the settings page
from config import SLEEP_AFTER_FRAMES, RENDER_FPS, RENDER_FPS_ASLEEP, RENDER_FPS_CALM

# state.emotion (set by brain.py from the LLM's choice) → face state
EMOTION_MAP = {
    "Happy":     "happy",
    "Surprised": "surprised",
    "Surprise":  "surprised",
    "Angry":     "angry",
    "Sad":       "sad",
    "Excited":   "excited",
    "Love":      "love",
    "Neutral":   "neutral",
}


def renderer_loop():
    import prio
    prio.background("renderer")
    face = RobotFace()

    while True:
        now = time.time()
        with state.lock:
            emotion       = state.emotion
            face_detected = state.face_detected
            speaking      = state.speaking
            listening     = state.listening
            thinking      = state.luna_mode == "processing"
            override      = state.face_override
            override_end  = state.face_override_until
            asleep        = state.sleep_mode
            busy = (state.reply_scene is not None
                    or now - state.gesture_anim_start < 3.0
                    or now - state.touch_time < 2.0
                    or bool(state.big_text and now < state.big_text[1]))
            # expire stale overrides
            if override and now > override_end:
                state.face_override = None
                override = None

        # ── LLM-chosen emotion lingering after a reply wins ──────────────
        if override:
            face.set_state(override)

        # ── "Dobranoc" — asleep until morning or until spoken to ─────────
        elif asleep and not speaking:
            face.set_state("sleeping")

        # ── Sleep when idle ───────────────────────────────────────────────
        elif face.idle_frames > SLEEP_AFTER_FRAMES:
            face.set_state("sleeping")

        # ── Speaking — emotion stays, mouth is driven by audio_energy ────
        elif speaking:
            pass

        # ── Thinking — utterance heard, waiting for the cloud ────────────
        elif thinking:
            face.set_state("thinking")

        # ── Normal emotion from vision ────────────────────────────────────
        else:
            mapped = EMOTION_MAP.get(emotion, "neutral")
            face.set_state(mapped)

        # asleep → fewer frames (the face barely moves); anything that wakes
        # her (an override from a touch, speech, listening) restores the pace
        sleepy = (not override and not speaking and not listening
                  and (asleep or face.idle_frames > SLEEP_AFTER_FRAMES))
        with state.lock:
            ov = state.overlay
        still = bool(ov and ov[0] in ("lamp", "clock", "list", "photo", "gallery", "stars",
                                      "clockface", "weather")
                     and not (ov[0] == "stars" and ov[2].get("new")
                              and now - ov[2]["t0"] < 1.0)    # (the pop-in)
                     # (a picture sliding in, the weather's rows coming up)
                     and not (ov[0] in ("gallery", "weather") and ui_screens.moving(ov[0], ov[2], now))
                     and now < ov[1] - 0.6)          # (full speed for the fade-out)
        calm = not (override or speaking or busy or face._gesture or face._scene)
        scene = ov and ov[0] == "lamp" and (ov[2] or {}).get("scene")
        face.anim_fps = (lamp_scenes.FPS.get(scene, 20) if scene and face.gl else 8 if still
                         else RENDER_FPS_ASLEEP if sleepy else RENDER_FPS_CALM if calm else RENDER_FPS)
        # awake, the GPU face is drawn more often than its pace: smoother, not faster
        awake = face.gl and not (scene or still or sleepy)
        face.fps = max(settings_page.draw_fps(), face.anim_fps) if awake else face.anim_fps

        try:
            face.draw()
        except SystemExit:
            raise
        except Exception as e:
            # a single bad frame (usually a scene doing something silly with
            # a surface) must not kill the face — drop the scene, not the app.
            # A dead display is different: that one really is fatal.
            import pygame, traceback
            if not pygame.display.get_init():
                raise
            with state.lock:
                bad = state.reply_scene
                state.reply_scene = None
            print(f"[face] frame error in scene {bad!r}: {e}", flush=True)
            traceback.print_exc()
            time.sleep(0.2)
