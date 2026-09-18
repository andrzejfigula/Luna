# brain.py
"""
brain.py — OpenAI chat (text + optional camera image), with the LLM choosing
Luna's facial emotion for every reply.

Flow per utterance:
  process(text)
    → (optional) grab the latest camera frame if the question is visual
    → chat.completions with a JSON schema {reply, emotion}
    → state.emotion = <emotion>      (frozen by text_to_speech for the whole
                                       reply so the face holds the mood)
    → speak(reply)
    → state.face_override = <emotion> for FACE_OVERRIDE_SECS, then neutral
All settings pulled from config.py.
"""

import base64
import json
import time

import cv2
from openai import OpenAI

from text_to_speech import speak
from shared_state import state
from config import (
    FACE_OVERRIDE_SECS,
    KNOWLEDGE_PATH,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_HISTORY,
    OPENAI_TIMEOUT,
    SYSTEM_PROMPT as _PERSONA,
    OFFLINE_REPLY,
    VISION_KEYWORDS,
    VISION_JPEG_QUALITY,
)

# Face states robot_face.py knows how to draw. The model must pick one.
EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "excited", "love"]

# ── Optional knowledge.txt (facts injected into the system prompt) ────────────
knowledge_text = ""
try:
    with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        knowledge_text = f.read().strip()
    if knowledge_text:
        print(f"[brain] Loaded knowledge file {KNOWLEDGE_PATH}")
except OSError:
    pass   # optional — nothing to do

SYSTEM_PROMPT = _PERSONA.strip() + f"""

Always answer as JSON with exactly two keys:
  "reply"   — what you say out loud (plain text, no markdown, 1-3 short sentences)
  "emotion" — one of {EMOTIONS}, the facial expression you show while saying it.
Pick the emotion that fits the reply: "happy" for warmth and good news,
"excited" for enthusiasm, "love" for affection/compliments, "surprised" for
unexpected things, "sad" for bad news or sympathy, "angry" only for playful
grumpiness, otherwise "neutral".
"""
if knowledge_text:
    SYSTEM_PROMPT += f"""
--- KNOWLEDGE BASE ---
{knowledge_text}
--- END KNOWLEDGE BASE ---
"""

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "luna_reply",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reply":   {"type": "string"},
                "emotion": {"type": "string", "enum": EMOTIONS},
            },
            "required": ["reply", "emotion"],
            "additionalProperties": False,
        },
    },
}

# ── OpenAI client ─────────────────────────────────────────────────────────────
if OPENAI_API_KEY:
    # timeout: a network stall must never freeze Luna in "processing"
    _client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT, max_retries=1)
else:
    _client = None
    print("[brain] No OPENAI_API_KEY set — Luna can only say the offline reply. "
          "Put the key in .env (see .env.example).")
_history = []


# ── Camera → image attachment ─────────────────────────────────────────────────

def _wants_vision(lower):
    return any(k in lower for k in VISION_KEYWORDS)


def _camera_jpeg_b64():
    """Latest camera frame as base64 JPEG, or None when no camera."""
    with state.lock:
        frame     = state.frame
        camera_ok = state.camera_ok
    if frame is None or not camera_ok:
        return None
    ok, buf = cv2.imencode(".jpg", frame,
                           [int(cv2.IMWRITE_JPEG_QUALITY), VISION_JPEG_QUALITY])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── OpenAI call ───────────────────────────────────────────────────────────────

def _ask_openai(text, image_b64=None):
    """Returns (reply, emotion) or None on any failure."""
    if _client is None:
        return None
    try:
        if image_b64:
            content = [
                {"type": "text", "text": text},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}",
                               "detail": "low"}},
            ]
            print("[brain] Attaching camera frame")
        else:
            content = text

        _history.append({"role": "user", "content": content})
        while len(_history) > OPENAI_MAX_HISTORY:
            _history.pop(0)

        # the model has no clock — give it the real local time so "która
        # godzina?" isn't answered with a confident guess
        now = time.strftime("%A, %d %B %Y, %H:%M")
        system = f"{SYSTEM_PROMPT}\nCurrent local date and time: {now}."

        response = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, *_history],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
            response_format=_RESPONSE_FORMAT,
        )

        raw     = response.choices[0].message.content.strip()
        data    = json.loads(raw)
        reply   = str(data.get("reply", "")).strip()
        emotion = str(data.get("emotion", "neutral")).lower()
        if emotion not in EMOTIONS:
            emotion = "neutral"

        # keep history text-only: images are large and only matter for the
        # turn they were asked in
        _history[-1] = {"role": "user", "content": text}
        _history.append({"role": "assistant", "content": reply})

        print(f"[brain] OpenAI ({emotion}): {reply}")
        return reply, emotion

    except Exception as e:
        print(f"[brain] OpenAI error: {e}")
        if _history and _history[-1]["role"] == "user":
            _history.pop()
        return None


# ── Main process ──────────────────────────────────────────────────────────────

def process(text):
    text = text.strip()
    if not text:
        return

    print(f"[brain] Processing: {text}")

    lower = text.lower()

    image = _camera_jpeg_b64() if _wants_vision(lower) else None
    result = _ask_openai(text, image)

    if result:
        reply, emotion = result
    else:
        print("[brain] OpenAI failed — using offline reply")
        reply, emotion = OFFLINE_REPLY, "sad"

    # The LLM's emotion drives the face:
    #  • during the reply: text_to_speech freezes state.emotion for the whole
    #    utterance, so set it BEFORE speak()
    #  • after the reply: hold it as a face_override for a few seconds, then
    #    the renderer falls back to neutral
    with state.lock:
        state.emotion = emotion.capitalize()
    try:
        speak(reply)
    finally:
        with state.lock:
            state.emotion             = "Neutral"
            state.face_override       = emotion if emotion != "neutral" else None
            state.face_override_until = time.time() + FACE_OVERRIDE_SECS
