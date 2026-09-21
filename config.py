# config.py

import os
import time

# Load .env file if present (simple parser — no extra dependency needed).
# .env is git-ignored, so secrets stay out of version control.
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ── Pi 4 fixed config ─────────────────────────────────────────────────────────
PI_MODEL        = 4
VISION_FPS      = 6      # Haar face detection rate (cheap, but it's a Pi 4)
# Haar cascade sensitivity: lower minNeighbors / scaleFactor and smaller
# minSize find more faces (and a few more false ones); histogram
# equalisation helps with side-lit faces. A face is held for
# FACE_HOLD_SECS after the last detection so single missed frames don't
# make the eyes / preview box flicker.
FACE_MIN_NEIGHBORS = 3
FACE_SCALE_FACTOR  = 1.1
FACE_MIN_SIZE      = 24      # px on the half-size (320x240) analysis frame
FACE_EQUALIZE      = True
FACE_HOLD_SECS     = 0.6
RENDER_FPS      = 30     # face animation; 30 is smooth on the 7" DSI panel

# ── Display (official 7" DSI touchscreen) ─────────────────────────────────────
SCREEN_WIDTH   = 800
SCREEN_HEIGHT  = 480
FULLSCREEN     = True
HIDE_CURSOR    = True

# Small live camera preview in the bottom-right corner (mirrored, with the
# face box). .env: LUNA_CAMERA_PREVIEW=1   (size in px: LUNA_CAMERA_PREVIEW=200)
_cp = os.environ.get("LUNA_CAMERA_PREVIEW", "").strip().lower()
CAMERA_PREVIEW   = _cp not in ("", "0", "false", "no", "off")
CAMERA_PREVIEW_W = int(_cp) if _cp.isdigit() and int(_cp) > 1 else 160

def _env(name, default):
    """Optional override from .env / environment; empty value = default."""
    v = os.environ.get(name, "").strip()
    return v if v else default


# ── Camera (Logitech C270 on /dev/video0) ─────────────────────────────────────
# .env: LUNA_CAMERA=0   or   LUNA_CAMERA=/dev/video2
CAMERA_ID      = _env("LUNA_CAMERA", "0")
CAMERA_ID      = int(CAMERA_ID) if CAMERA_ID.isdigit() else CAMERA_ID
FRAME_WIDTH    = 640     # full frame goes to the LLM for "what do you see";
FRAME_HEIGHT   = 480     # face detection runs on a half-size copy
FPS            = 15
ESP32_STREAM   = ""
USE_ESP32_CAM  = False

# ── Knowledge (optional facts injected into the system prompt) ────────────────
KNOWLEDGE_PATH = "data/knowledge.txt"

# ── Robot identity ────────────────────────────────────────────────────────────
ROBOT_NAME = "Luna"
# Any of these activates conversation. Polish inflections included because
# Vosk's small model often emits them for "Luna"; the cloud transcript is
# checked too (CLOUD_WAKE_CHECK) so a misheard wake word still gets through.
WAKE_WORDS = ["luna", "hej luna", "hey luna", "luno", "lunę", "lune", "luny",
              "lunie", "luną", "lóna", "łuna"]

# Luna's identity and character — edit data/persona.txt (plain text, no code).
# The fallback below is only used if that file is missing.
PERSONA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "persona.txt")
try:
    with open(PERSONA_PATH, encoding="utf-8") as _f:
        SYSTEM_PROMPT = _f.read().strip()
except OSError:
    SYSTEM_PROMPT = f"""You are {ROBOT_NAME}, a small, curious female desktop
robot (she/her; in Polish use feminine forms about yourself) with an animated
face on a little screen. Warm, playful, a bit cheeky. Speak the user's
language (Polish or English). You are speaking out loud: 1-3 short sentences,
no lists or markdown."""

# Spoken when the LLM can't be reached (no key / no network)
OFFLINE_REPLY = "Przepraszam, nie mogę teraz połączyć się z moim mózgiem."

# ── Conversation mode ─────────────────────────────────────────────────────────
CONVO_TIMEOUT      = 10    # seconds of silence before deactivating conversation
POST_SPEAK_DELAY   = 0.8   # settle time after Luna speaks before listening again
DOUBLE_FLUSH       = True  # flush audio queue twice (before and after delay)
MIC_BLOCK_AFTER_SPEAK = 0.6   # echo-guard after speech ends (speech itself already
                              # blocks the mic via state.speaking)

# Some TTS drivers (notably pyttsx3's macOS "nsss" backend on a reused engine)
# can return from runAndWait() BEFORE the audio has actually finished playing
# through the speaker. If that happens the mic would unblock while Luna is
# still audibly talking and hear herself. text_to_speech.py detects an
# early return (elapsed time well under the expected speech duration) and
# pads the mic block to cover the remaining expected playback time.
TTS_EARLY_RETURN_RATIO = 0.6   # elapsed/expected below this = treat as early return

# Extra defense: if what the mic just heard closely matches what Luna just
# said (within this many seconds), it's almost certainly speaker echo/room
# reverb, not a real new utterance from the user — discard it. Both checks
# must pass (AND, not OR) to stay high-precision — heavily garbled ASR
# echoes won't always clear this, but the timing fix above (mic block
# padded to the real speech duration) prevents most of those from being
# heard in the first place; this is just cleanup for trailing echo/reverb.
ECHO_GUARD_WINDOW  = 8.0    # seconds after speaking to check for self-echo
ECHO_RUN_THRESH    = 0.5    # longest contiguous word-run shared with the reply
ECHO_OVERLAP_THRESH = 0.6   # fraction of heard words that appear in the reply

# Spoken when a wake word is heard on its own ("Luna!") with no question attached
WAKE_REPLIES = ["Tak?", "Słucham!", "Hej! W czym mogę pomóc?"]

# ── Face idle ─────────────────────────────────────────────────────────────────
SLEEP_AFTER_FRAMES   = RENDER_FPS * 30   # nobody in view for 30 s → sleep

# ── OpenAI ────────────────────────────────────────────────────────────────────
# Put the key in .env (git-ignored):  OPENAI_API_KEY=sk-...
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Where Luna lives — the current local date/time in this zone is given to the
# model with every request. .env: LUNA_TIMEZONE=Europe/Warsaw
LUNA_TIMEZONE  = os.environ.get("LUNA_TIMEZONE", "").strip() or "Europe/Warsaw"
LUNA_LOCATION  = os.environ.get("LUNA_LOCATION", "").strip() or "Poland"
OPENAI_MODEL   = "gpt-4.1-mini"     # chat + vision; fast and cheap enough for voice
OPENAI_TIMEOUT = 15.0               # seconds — a stall must never freeze Luna

# ── Audio devices ─────────────────────────────────────────────────────────────
# Microphone — .env: LUNA_MIC=<index>  or  LUNA_MIC=<part of the device name>
# (e.g. LUNA_MIC=C270). Unset = auto detect (system default input).
# List devices: ./venv/bin/python -c "import sounddevice; print(sounddevice.query_devices())"
AUDIO_INPUT_DEVICE  = _env("LUNA_MIC", None)
if isinstance(AUDIO_INPUT_DEVICE, str) and AUDIO_INPUT_DEVICE.isdigit():
    AUDIO_INPUT_DEVICE = int(AUDIO_INPUT_DEVICE)

# Speaker — .env: LUNA_SPEAKER=jack | hdmi | bluetooth | default | <PipeWire node name>
# ("jack" = 3.5 mm headphone jack). List sinks: wpctl status
AUDIO_OUTPUT_DEVICE = _env("LUNA_SPEAKER", "default")

# ── STT ───────────────────────────────────────────────────────────────────────
# Vosk does wake-word spotting + endpointing locally; the cloud does the
# actual transcription (see speech_to_text.py).
VOSK_MODEL_PATH = "vosk-model-small-pl-0.22"   # Polish; wake word "luna" works

# None = auto-detect the device's native sample rate (recommended).
# The C270 mic is 16 kHz native, which is exactly what Vosk wants — no resampling.
MIC_SAMPLE_RATE = 16000

VOSK_SAMPLE_RATE = 16000    # vosk always needs 16000 — do not change

CLOUD_STT          = True
CLOUD_STT_MODEL    = "gpt-4o-mini-transcribe"
CLOUD_STT_LANGUAGE = None      # None = auto-detect (Polish / English); or "pl"
CLOUD_STT_PROMPT   = "Luna"    # spelling hint for the robot's name
CLOUD_STT_TIMEOUT  = 8.0
CLOUD_STT_MAX_SECS = 20        # longest utterance sent to the cloud

# ── STT noise rejection (only respond when actually addressed) ─────────────────
# Layered defence so ambient noise is never turned into words Luna answers.
#
# 1) Energy gate (VAD): audio blocks quieter than the gate are treated as
#    ambient noise and fed to Vosk as digital silence, so background sound is
#    never transcribed. The gate ADAPTS to the room: a slow-moving noise-floor
#    estimate tracks ambient loudness, and the gate sits MIC_GATE_FACTOR above
#    it — rising automatically in noisy rooms, falling in quiet ones.
#    MIC_ENERGY_THRESHOLD is the minimum gate (int16 RMS scale, 0–32767).
#    To calibrate: watch the "[STT] ... peak_rms=/gate=" debug lines — speech
#    should sit well above the gate, room noise below it.
MIC_GAIN             = 1.6      # software gain on the mic stream (the C270's
                                # hardware gain is already at max); helps Vosk
                                # with quiet / distant speech
MIC_ENERGY_THRESHOLD = 400.0    # gate never drops below this (post-gain RMS)
MIC_GATE_FACTOR      = 2.0      # gate = noise_floor × this (≥ threshold above)
MIC_GATE_MAX         = 4000.0   # safety cap so speech can always get through

# 2) Confidence gate: drop a recognised phrase whose average Vosk word
#    confidence is below this (0.0–1.0). Filters low-confidence hallucinations
#    that noise produces.
STT_CONFIDENCE_THRESHOLD = 0.45   # the cloud does the real transcription;
                                  # this only needs to reject pure noise

# Wake words are checked on their OWN confidence (not the whole phrase) so a
# noise-hallucinated "luna" can't wake her, while a clearly spoken wake word
# still cuts through a noisy room. Slightly-misheard wake words (e.g. Vosk
# hearing "lunar") also wake her via fuzzy matching when heard confidently.
WAKE_CONFIDENCE_THRESHOLD = 0.45
WAKE_FUZZY_RATIO          = 0.70   # difflib similarity for near-miss wake words
                                  # ("lena", "luma", "una" all pass at 0.70)

# Cloud wake check: in passive mode, when Vosk heard real speech but no wake
# word, send the utterance to the cloud and look for the wake word there.
# Costs one cheap transcription per spoken sentence heard while idle.
CLOUD_WAKE_CHECK          = True
CLOUD_WAKE_MIN_INTERVAL   = 2.0    # seconds between cloud wake checks

# 3) Addressed-speech gate: people talking TO Luna face her; people talking to
#    EACH OTHER in the room don't. Speech (wake words included — "hello"
#    between two people greeting each other shouldn't wake her) is only
#    accepted when the camera has seen a face within FACE_RECENT_SECS, so
#    side conversations in any language no longer get random replies. The
#    gate disables itself automatically when no camera is available, and
#    can be turned off here for mic-only / dim-light setups.
REQUIRE_FACE_TO_TALK = False   # off: the wake word is the gate. Turning it on
                               # makes Luna ignore "Luna!" whenever the camera
                               # hasn't seen a face in the last few seconds
FACE_RECENT_SECS     = 4.0   # tolerance for glancing away mid-question

# 3) Minimum length: ignore stray single-character tokens ("a", "i", "o") that
#    noise commonly yields. Real short answers ("yes"/"no"/"hi") still pass.
STT_MIN_UTTERANCE_CHARS = 2

# Print per-utterance rms/confidence so the thresholds above can be tuned.
STT_DEBUG_AUDIO = True

# ── TTS (OpenAI, streamed PCM) ────────────────────────────────────────────────

TTS_RATE = 155   # legacy, unused by the OpenAI engine

OPENAI_TTS_MODEL        = "gpt-4o-mini-tts"
# .env: LUNA_TTS_VOICE=nova   (alloy, ash, ballad, coral, echo, fable, nova,
# onyx, sage, shimmer, verse, marin, cedar — nova/shimmer/marin are the bright ones)
OPENAI_TTS_VOICE        = _env("LUNA_TTS_VOICE", "marin")
OPENAI_TTS_SPEED        = 1.0
# Delivery style. Kept conversational on purpose — "cheerful robot" style
# prompts make the voice sound artificial.
OPENAI_TTS_INSTRUCTIONS = (
    "Voice identity: a young woman in her early twenties with a LIGHT, "
    "HIGH-pitched, girlish, bright voice. Keep the pitch consistently high "
    "and airy from the first word to the last; never drop into a low, deep, "
    "husky or masculine register, even for serious or calm sentences. "
    "Delivery: natural, warm, relaxed conversation with a friend, a smile in "
    "the voice, natural pace and intonation, no exaggerated acting. Native "
    "Polish pronunciation; switch to natural English when the text is English."
)
OPENAI_TTS_TIMEOUT      = 20.0
TTS_PREBUFFER_SECS      = 0.6    # audio buffered before playback starts — avoids
                                 # crackle/underruns when the stream stutters
TTS_LEADIN_SECS         = 0.25   # silence played before each reply so the Pi's
                                 # 3.5 mm output pop happens before the voice

# ── Lip sync ──────────────────────────────────────────────────────────────────
# The mouth follows the real loudness of the audio being played: the TTS
# engine measures an RMS envelope of every PCM frame it sends to the player
# and the renderer reads it back at (now - playback start - latency).
LIPSYNC_FRAME_MS   = 20     # envelope resolution
LIPSYNC_LATENCY_MS = 90     # pipe + PipeWire quantum/headroom + DAC delay;
                            # raise if the mouth runs ahead of the sound,
                            # lower if it lags behind
LIPSYNC_GAIN       = 1.0    # >1 = mouth opens wider for the same loudness
LIPSYNC_RMS_FULL   = 6500   # int16 RMS that counts as "fully open"
LIPSYNC_ATTACK     = 0.55   # smoothing: how fast the mouth opens (0-1)
LIPSYNC_RELEASE    = 0.30   # how fast it closes

# Raw-PCM capable player. pw-play goes through PipeWire, so audio follows the
# desktop's default output (Bluetooth speaker, 3.5 mm jack, HDMI) and its
# volume. aplay would bypass PipeWire and hit the 3.5 mm jack directly.
TTS_PLAYER = "pw-play"

# ── Brain ─────────────────────────────────────────────────────────────────────
OPENAI_MAX_TOKENS   = 200   # max tokens per response (keep short for speech)
OPENAI_TEMPERATURE  = 0.8   # creativity (0.0 = factual, 1.0 = creative)
OPENAI_MAX_HISTORY  = 8     # max conversation history turns to send to API

# The camera frame is attached to EVERY request at low detail (~85 tokens)
# so Luna can always "see"; questions containing any of the words below get
# it at high detail instead (needed to read text, small objects).
VISION_ALWAYS = True
VISION_KEYWORDS = [
    # Polish
    "widzisz", "widać", "widac", "zobacz", "spójrz", "spojrz", "popatrz",
    "obejrzyj", "przeczytaj", "napisane", "napis", "tekst", "co to jest",
    "co to", "kamer", "co trzymam", "jak wyglądam", "jak wygladam",
    "co mam na", "kto to", "ile osób", "ile osob", "ile palc", "co jest na",
    "jaki kolor", "jakiego koloru", "rozpoznaj", "pokaż", "pokaz", "obraz",
    "zdjęci", "zdjeci", "ekran", "etykiet",
    # English
    "see", "look", "read", "written", "text", "what is this", "what's this",
    "camera", "what am i", "holding", "wearing", "who is", "how many",
    "describe", "color", "colour", "label", "screen", "picture", "photo",
]
VISION_JPEG_QUALITY = 80

# ── Expressions ───────────────────────────────────────────────────────────────
FACE_OVERRIDE_SECS     = 4.0   # how long the LLM-chosen emotion lingers after a reply

# ── Gestures (camera motion, see gesture_module.py) ───────────────────────────
GESTURE_FPS            = 15    # analysis rate (160x120 frame differencing, ~1 ms);
                               # a quick wave needs several samples per swing
GESTURE_DEBUG          = False # log every near-miss with its features (tuning)
GESTURE_REACT_COOLDOWN = 4.0   # seconds between reactions to the same gesture

# A wave = a hand-sized moving blob near the face that reverses horizontal
# direction several times within a short window.
WAVE_WINDOW_SECS       = 1.6
WAVE_MIN_REVERSALS     = 4     # a wave: several direction changes in the window
WAVE_MIN_AMPLITUDE     = 0.35  # sideways travel ≥ this × the face width
                               # (scale-free: works close up and far away)
WAVE_MIN_SWING         = 0.15  # a half-swing must travel ≥ this × face width
                               # before a direction change counts (kills jitter)
WAVE_MAX_VERTICAL      = 3.0   # loose sanity limit only: the motion blob
                               # (hand + forearm) moves a lot vertically even
                               # in a real wave, so this can't be strict
WAVE_MIN_PRESENCE      = 0.6   # the moving blob must be present in this
                               # fraction of the window's samples — a hand
                               # holding something up stops moving
WAVE_MIN_MEAN_SPEED    = 0.12  # mean sideways speed ≥ this × face width per
                               # sample (a wave keeps moving)
WAVE_SWING_REGULARITY  = 0.0   # off — measured real waves are irregular
                               # (0.2-0.35) at 15 fps sampling
WAVE_MIN_AREA          = 25    # blob size limits (px² at 160x120)
WAVE_MAX_AREA          = 2200
WAVE_DIFF_THRESHOLD    = 22    # frame-difference level that counts as motion
WAVE_REQUIRE_FACE      = True  # no face in view → no wave (a hand over the
                               # face while taking headphones off isn't one)
WAVE_FACE_GRACE_SECS   = 1.5   # ...but a face seen this recently still counts
                               # (Haar drops frames while things move)
# Distances below are in HALF face widths/heights from the face centre, using
# the size the detector actually measured (so they hold at any distance).
WAVE_MIN_FACE_DIST     = 1.15  # hand centre at least this far to the side of
                               # the head (just outside it; the motion rules
                               # take care of glasses / headphones)
WAVE_MAX_FACE_DIST     = 7.0   # ...and not further than this
WAVE_MAX_FACE_VDIST    = 2.6   # vertical tolerance for a single sample
WAVE_MAX_BELOW_FACE    = 1.3   # the hand's mean height: not lower than this
                               # many half face heights below the face centre.
                               # Waves land anywhere from -0.7 (hand raised)
                               # to +1.3 (waving from the elbow); showing an
                               # object is usually lower still (+1.4..+1.9)

# Motion alone can't tell a wave from a hand showing an object — both move.
# So a motion candidate is CONFIRMED by asking the vision model whether the
# current frame shows an open, empty hand waving. ~1 s, a fraction of a cent.
WAVE_CLOUD_CONFIRM     = False   # off: too slow (~1 s) and missed real waves
WAVE_CONFIRM_MIN_GAP   = 3.0   # seconds between confirmation requests

# Local wave-vs-object check: skin colour. The face gives the person's own
# skin tone (Cr/Cb statistics, adapts to lighting); an open empty hand is
# mostly skin, a hand holding an object mostly isn't.
WAVE_MIN_SKIN          = 0.60  # mean skin fraction of the moving blob's box
                               # when the face is WAVE_SKIN_REF_FW px wide.
                               # Weak filter only: in daylight skin does NOT
                               # separate a hand from a hand with an object
                               # (both 0.6-0.9 with the tolerance below)
WAVE_SKIN_REF_FW       = 40    # face width (px at 160 px analysis) the threshold
                               # above is calibrated for; further away the hand
                               # is small and its box holds more background, so
                               # the threshold scales down with face width...
WAVE_MIN_SKIN_FLOOR    = 0.45  # ...but never below this
WAVE_MIN_AREA_FACE     = 0.12  # mean blob area ≥ this × the face box area —
                               # a whole waving hand, not a sliver of skin
                               # next to an object (waves 0.16-0.26, slivers 0.04-0.07)
WAVE_SKIN_SIGMA        = 3.0   # tolerance around the face's Cr/Cb mean, in std
WAVE_SKIN_MIN_STD      = 6.0   # floor for that std: under even daylight the face
                               # is very uniform and the window would collapse,
                               # rejecting a hand lit by the window
WAVE_HEAD_EXCLUDE      = 1.1   # motion inside this box around the head is
                               # ignored (head movement itself)

# Luna's reaction to a wave: happy face + she waves her hand + one of these
# (spoken only when idle)
WAVE_REPLIES           = ["Cześć!", "Hej, hej!", "O, cześć! Miło cię widzieć!",
                          "Hejka!"]

# ── Luna's own gestures (chosen by the LLM per reply, or by behavior_engine) ──
# nod / shake move the head; wave / thumbs_up / heart bring a hand up.
GESTURE_DURATION = {
    "nod":       1.4,
    "shake":     1.4,
    "wave":      2.2,
    "thumbs_up": 2.6,
    "heart":     3.2,
}

# ── Face style ────────────────────────────────────────────────────────────────
# 1 = Luna classic (purple, soft rounded)
# 2 = Robo (cyan, sharp corners, equalizer-bar mouth — NIMO/modern-robot look)
# 3 = Loona (amber gradient block eyes, no pupils, shape-based expressions)
# Press 1 / 2 / 3 on the face window to switch live; this sets the startup default.
FACE_STYLE = 3
