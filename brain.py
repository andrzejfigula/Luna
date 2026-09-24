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
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
from openai import OpenAI

import idle_scenes

from text_to_speech import speak
from shared_state import state
from config import (
    FACE_OVERRIDE_SECS,
    GESTURE_DURATION,
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
    VISION_ALWAYS,
    LUNA_TIMEZONE,
    LUNA_LOCATION,
)

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception as e:
    print(f"[brain] Unknown LUNA_TIMEZONE={LUNA_TIMEZONE!r} ({e}) — using system time")
    _TZ = None


def _local_now_text():
    """'Sunday, 20 September 2026, 23:30 (Europe/Warsaw, CEST, UTC+02:00)'"""
    now = datetime.now(_TZ) if _TZ else datetime.now().astimezone()
    off = now.strftime("%z")
    return (f"{now.strftime('%A, %d %B %Y, %H:%M')} "
            f"({LUNA_TIMEZONE if _TZ else 'system'}, {now.strftime('%Z')}, "
            f"UTC{off[:3]}:{off[3:]})")

# Safety net for the model slipping into masculine 1st-person forms.
# Irregular / high-frequency ones first, then the regular "-łem" → "-łam"
# and "-łbym" → "-łabym" endings.
_FEM_SPECIAL = {
    "mógłbym": "mogłabym", "mogłem": "mogłam", "poszedłem": "poszłam",
    "poszedłbym": "poszłabym", "szedłem": "szłam", "wziąłem": "wzięłam",
    "wziąłbym": "wzięłabym", "zacząłem": "zaczęłam", "zdjąłem": "zdjęłam",
    "jestem gotowy": "jestem gotowa", "jestem pewny": "jestem pewna",
    "jestem ciekawy": "jestem ciekawa", "jestem zmęczony": "jestem zmęczona",
    "jestem szczęśliwy": "jestem szczęśliwa", "jestem zadowolony": "jestem zadowolona",
    "byłbym": "byłabym", "chciałbym": "chciałabym", "wolałbym": "wolałabym",
    "powinienem": "powinnam", "mogłem": "mogłam",
}
_FEM_SPECIAL_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _FEM_SPECIAL),
                                                    key=len, reverse=True)) + r")\b",
                             re.IGNORECASE)
_FEM_ENDINGS_RE = re.compile(r"\b(\w+?)(łem|łbym)\b")


def _feminize(text):
    """Turn masculine 1st-person forms into feminine ones ("zrobiłem" →
    "zrobiłam", "chciałbym" → "chciałabym"). Only touches endings that are
    unambiguous 1st-person masculine in Polish."""
    def special(m):
        src = m.group(1); rep = _FEM_SPECIAL[src.lower()]
        return rep.capitalize() if src[0].isupper() else rep
    text = _FEM_SPECIAL_RE.sub(special, text)
    text = _FEM_ENDINGS_RE.sub(lambda m: m.group(1) + ("łam" if m.group(2) == "łem"
                                                       else "łabym"), text)
    return text


# Face states robot_face.py knows how to draw. The model must pick one.
EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "excited", "love"]
# Body language robot_face.py can animate: hand/head gestures plus the idle
# scenes that are safe to play while she is talking (see idle_scenes.py).
HAND_GESTURES = ["nod", "shake", "wave", "thumbs_up", "heart"]
SCENE_GESTURES = sorted(idle_scenes.reply_scenes())
GESTURES = ["none"] + HAND_GESTURES + SCENE_GESTURES

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

GRAMMAR RULE (Polish): you are FEMALE. Every 1st-person verb and adjective
about yourself takes the FEMININE form. Correct: "mogłabym", "chciałabym",
"byłabym", "zrobiłam", "widziałam", "byłam", "jestem gotowa", "jestem
pewna", "jestem ciekawa", "sama". WRONG, never use: "mógłbym",
"chciałbym", "byłbym", "zrobiłem", "widziałem", "byłem", "jestem gotowy",
"jestem pewny", "jestem ciekawy", "sam". Check your reply for this before
answering.

Always answer as JSON with exactly three keys:
  "reply"   — what you say out loud (plain text, no markdown, 1-3 short sentences)
  "emotion" — one of {EMOTIONS}, the facial expression you show while saying it.
  "gesture" — one of {GESTURES}, the body language you perform while saying it.
Pick the emotion that fits the reply: "happy" for warmth and good news,
"excited" for enthusiasm, "love" for affection/compliments, "surprised" for
unexpected things, "sad" for bad news or sympathy, "angry" only for playful
grumpiness, otherwise "neutral".
Gesture vocabulary, by what it expresses:
  agreement/denial — nod, shake
  greeting/approval — wave, wave_both, thumbs_up, clap, salute
  affection — heart, please, slow_blink, shy
  amusement — wink, smirk, laugh, dance, eye_roll
  thinking — remember, think_bubble, chin_rest, scratch_head, curious
  feeling — sigh, relief, proud, scared, impatient, tear_wipe
  surprise/confusion — double_blink, eye_twitch, cross_eyes, glitch

Pick the gesture from the CONTENT of your reply, in this priority:
1. The reply answers a yes/no question. "nod" if the answer is yes/agree
   ("Tak", "Yes", "Oczywiście", "Jasne", "Zgadzam się"); "shake" if the
   answer is no/deny/disagree ("Nie", "No", "Niestety nie", "Nie sądzę").
   The gesture MUST match the answer word: a reply beginning with "Nie" or
   "No" is always "shake", never "nod".
2. Greeting or goodbye ("Cześć", "Hej", "Do zobaczenia") → "wave".
3. You praise the user or say well done / bravo / congratulations → "thumbs_up".
4. The user expressed love or affection for you, or thanked you warmly, and
   you reply with affection → "heart".
5. A playful, teasing or knowing reply → "wink" or "smirk"; recalling
   something → "remember"; something absurd → "cross_eyes" or "eye_roll";
   warmth without words → "slow_blink".
6. Everything else, including ordinary answers and plain facts → "none".
Most replies are "none"; never use "nod" for a statement that is not an
agreement or a yes.
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
                "gesture": {"type": "string", "enum": GESTURES},
            },
            "required": ["reply", "emotion", "gesture"],
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

def _ask_openai(text, image_b64=None, detail="low"):
    """Returns (reply, emotion, gesture) or None on any failure."""
    if _client is None:
        return None
    try:
        if image_b64:
            # The frame rides along with every message so Luna can always
            # see, but a bare picture pulls the model's attention: it starts
            # describing the room instead of continuing the conversation.
            # Say explicitly, next to the image, what it is for.
            if detail == "low":
                note = ("(Załączone zdjęcie to aktualny obraz z Twojej kamery, "
                        "dołączany do KAŻDEJ wiadomości. Użyj go tylko, jeśli moja "
                        "wiadomość dotyczy tego, co widzisz. W przeciwnym razie "
                        "zignoruj je całkowicie i odpowiedz na moją wiadomość w "
                        "kontekście naszej rozmowy — nie opisuj, co jest na "
                        "zdjęciu.)")
            else:
                note = ("(Załączone zdjęcie to aktualny obraz z Twojej kamery — "
                        "moja wiadomość dotyczy tego, co na nim widać.)")
            content = [
                {"type": "text", "text": f"{text}" + chr(10) + chr(10) + note},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}",
                               "detail": detail}},
            ]
            if detail != "low":
                print(f"[brain] Attaching camera frame ({detail} detail)")
        else:
            content = text

        _history.append({"role": "user", "content": content})
        while len(_history) > OPENAI_MAX_HISTORY:
            _history.pop(0)

        # the model has no clock — give it the real local time so "która
        # godzina?" isn't answered with a confident guess
        system = (f"{SYSTEM_PROMPT}\nYou are in {LUNA_LOCATION}. The current "
                  f"local date and time there is: {_local_now_text()}. When "
                  f"asked the time or date, answer with exactly this local "
                  f"time — do not convert it to any other zone.")

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
        fixed   = _feminize(reply)
        if fixed != reply:
            print(f"[brain] feminized: {reply!r} → {fixed!r}")
            reply = fixed
        emotion = str(data.get("emotion", "neutral")).lower()
        if emotion not in EMOTIONS:
            emotion = "neutral"
        gesture = str(data.get("gesture", "none")).lower()
        if gesture not in GESTURES:
            gesture = "none"

        # keep history text-only: images are large and only matter for the
        # turn they were asked in
        _history[-1] = {"role": "user", "content": text}
        _history.append({"role": "assistant", "content": reply})

        print(f"[brain] OpenAI ({emotion}, {gesture}): {reply}")
        return reply, emotion, gesture

    except Exception as e:
        print(f"[brain] OpenAI error: {e}")
        if _history and _history[-1]["role"] == "user":
            _history.pop()
        return None


# ── Yes/no question about the current camera frame (used by behavior_engine) ─

def confirm_wave():
    """Ask the vision model whether the person in the current frame is waving
    (open, empty hand raised toward the camera). Returns True/False; False on
    any failure so a network hiccup never produces a spurious reaction."""
    if _client is None:
        return False
    img = _camera_jpeg_b64()
    if not img:
        return False
    try:
        r = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text":
                     "Look at the person in this webcam frame. Are they WAVING "
                     "at the camera — an open, EMPTY hand raised with the palm "
                     "toward the camera, as a greeting? If the hand is holding, "
                     "showing or pointing at any object, or the hand is not "
                     "clearly visible, answer no. Answer with exactly one word: "
                     "yes or no."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{img}",
                                   "detail": "low"}},
                ]}],
            max_tokens=3,
            temperature=0.0,
        )
        ans = (r.choices[0].message.content or "").strip().lower()
        print(f"[brain] wave check → {ans}")
        return ans.startswith("y")
    except Exception as e:
        print(f"[brain] wave check failed: {e}")
        return False


# ── Main process ──────────────────────────────────────────────────────────────

def process(text):
    text = text.strip()
    if not text:
        return

    print(f"[brain] Processing: {text}")

    lower = text.lower()

    visual = _wants_vision(lower)
    image  = _camera_jpeg_b64() if (visual or VISION_ALWAYS) else None
    result = _ask_openai(text, image, detail="high" if visual else "low")

    if result:
        reply, emotion, gesture = result
    else:
        print("[brain] OpenAI failed — using offline reply")
        reply, emotion, gesture = OFFLINE_REPLY, "sad", "shake"

    # The LLM's emotion drives the face:
    #  • during the reply: text_to_speech freezes state.emotion for the whole
    #    utterance, so set it BEFORE speak()
    #  • after the reply: hold it as a face_override for a few seconds, then
    #    the renderer falls back to neutral
    with state.lock:
        state.emotion = emotion.capitalize()
        if gesture in GESTURE_DURATION:              # hands / head
            state.gesture_anim       = gesture
            state.gesture_anim_start = time.time()
        elif gesture in idle_scenes.SCENES:          # facial scene
            state.idle_action       = gesture
            state.idle_action_start = time.time()
            state.idle_action_reply = True
    try:
        speak(reply)
    finally:
        with state.lock:
            state.emotion             = "Neutral"
            state.face_override       = emotion if emotion != "neutral" else None
            state.face_override_until = time.time() + FACE_OVERRIDE_SECS
