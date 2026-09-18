import time
from shared_state import state
from robot_face import RobotFace
from config import SLEEP_AFTER_FRAMES

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
            # expire stale overrides
            if override and now > override_end:
                state.face_override = None
                override = None

        # ── LLM-chosen emotion lingering after a reply wins ──────────────
        if override:
            face.set_state(override)

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

        face.draw()
