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

# ── Where the user's data lives (memory, timers, lists, settings) ─────────────
# LUNA_DATA_DIR redirects it — tests set it so they never touch the real
# memory, timers or shopping list.
DATA_DIR = (os.environ.get("LUNA_DATA_DIR", "").strip()
            or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# ── Pi 4 fixed config ─────────────────────────────────────────────────────────
PI_MODEL        = 4
VISION_FPS      = 6      # Haar face detection rate (cheap, but it's a Pi 4)
# One full-frame Haar pass costs ~110 ms of CPU on the Pi (measured), so 6/s
# was two thirds of a core. Two savings (vision_module.py):
VISION_IDLE_FPS   = 2      # nobody seen for VISION_IDLE_AFTER s → look less often
VISION_IDLE_AFTER = 60
VISION_FULL_EVERY = 6      # with a face in view, search only around it, and
                           # scan the whole frame every Nth time (new people)
# Haar cascade sensitivity: lower minNeighbors / scaleFactor and smaller
# minSize find more faces (and a few more false ones); histogram
# equalisation helps with side-lit faces. A face is held for
# FACE_HOLD_SECS after the last detection so single missed frames don't
# make the eyes / preview box flicker.
FACE_MIN_NEIGHBORS = 2
FACE_SCALE_FACTOR  = 1.1
FACE_SCALE_FULL    = 1.2     # the whole-frame search: coarser scale steps, ~half the
                             # cost (it was 123 ms a frame on the Pi, the biggest
                             # single CPU user) — near the last face 1.1 still
VISION_NEAR_MISSES = 2       # Haar drops single frames: miss the face near where
                             # it was this many times before searching everywhere
FACE_MIN_SIZE      = 24      # px on the half-size (320x240) analysis frame
FACE_EQUALIZE      = True    # CLAHE (local contrast) — handles a backlit face
FACE_HOLD_SECS     = 0.6
VISION_DEBUG       = False   # log detections (position, size, count) every ~2 s
RENDER_FPS      = 30     # face animation; 30 is smooth on the 7" DSI panel
RENDER_FPS_CALM = 20     # awake but calm (not speaking, no gesture, scene or touch):
                         # slow eye moves and blinks look the same, and a frame
                         # costs ~18 ms on the Pi — 30 fps was half a core
RENDER_FPS_ASLEEP = 12   # while she sleeps (nobody around / "dobranoc"): the
                         # sleeping face barely moves, and drawing it at 30 fps
                         # was half a CPU core

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
CONVO_QUESTION_BONUS = 8   # …plus this when her reply ended with a question:
                           # a thoughtful answer needs longer than 10 s
CONVO_GRACE        = 4    # speech that STARTED up to this long after the window
                           # closed is still answered — you began in time
POST_SPEAK_DELAY   = 0.2   # settle time after Luna speaks before listening again
DOUBLE_FLUSH       = True  # flush audio queue twice (before and after delay)
# Barge-in (bargein.py): while she speaks, these words stop her and she listens
BARGE_IN        = "log"   # True / False / "log": listens and logs "[barge] (log only) would
                           # stop…" but never stops her — off until echo cancelling: alone it
                           # stopped her by herself (1 in 15 replies) and caught "stop!" over
                           # her voice only 1–2 times in 8 (offline, 6 Oct); the log gathers
                           # real false stops and her echo level in the room meanwhile
BARGE_WORDS     = ["stop", "przestań", "cicho", "luna", "luno"]   # (not "poczekaj", "dość":
                   # her own "poszukajmy" was heard as "poczekaj" — offline test, 6 Oct)
BARGE_MIN_CONF  = 0.85
BARGE_OVER_ECHO = 1.6      # louder than her own voice in the mic by this much
MIC_BLOCK_AFTER_SPEAK = 0.2   # (was 0.45, and listen() then waited 0.2 s more and threw
                              # away what came: "I start talking before she listens",
                              # 6 Oct) — echo-guard after speech ends (speech itself already
                              # blocks the mic via state.speaking). Was 0.6 + 0.8:
                              # 1.4 s deaf after every answer ate the first words of
                              # a quick reply. The persistent player knows when her
                              # last sample plays; 0.45 covers PipeWire's ~0.1 s and
                              # the room's echo

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
OPENAI_MODEL   = "gpt-4.1-mini"     # the helpers (memory, greetings, cooking…) + vision
CHAT_MODEL     = "gpt-5.4-mini"     # her replies: first sentence 1.13 s vs 1.67 s for
                                    # gpt-4.1-mini on the same 5 questions (7 Oct), no
                                    # reasoning (reasoning_effort "none")
CRAFT_MODEL    = "gpt-4.1"          # poems, rhymes, songs: the mini model's Polish
                                    # rhymes were weak (6 Oct, Maja's "wierszyk");
                                    # rare requests, so the cost and +~0.5 s are fine
OPENAI_TIMEOUT = 15.0               # seconds — a stall must never freeze Luna
SEARCH_MODEL   = "gpt-5.4-mini"    # web search (websearch.py): 4.4 s vs 5.4 s for gpt-4.1-mini
                                   # on 3 real questions (7 Oct), reasoning off
SEARCH_TIMEOUT = 20.0
CHAT_HEDGE_AFTER = 2.0             # the reply stream hasn't started by then (the first
                                   # token normally comes in 0.65–0.9 s): a second request

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
CLOUD_STT_MODEL    = "gpt-transcribe"   # (was gpt-4o-mini-transcribe) 7 Oct, same clips:
                                     # 0.56 s every time vs 0.5–3.4 s, "skrobanie szyb rano"
                                     # right (old: "szyprano"), and "" for hiss or a knock
                                     # where the old one echoed its prompt or made up
                                     # "Cześć, Andrzej! Jak minął twój dzień?"
CLOUD_STT_LANGUAGE = None      # None = auto-detect (Polish / English); or "pl"
# Context for the transcriber. Measured on the Pi (speaker -> room -> C270):
# with just "Luna" a lone "Tak." came back as "ták" (language guessed wrong
# on a one-word clip) — this context took short-reply errors from 11 % to 0
# and English still transcribes fine.
CLOUD_STT_PROMPT   = ("Rozmowa po polsku z małym robotem biurkowym o imieniu "
                      "Luna. Czasem pada zdanie po angielsku.")
CLOUD_STT_TIMEOUT  = 8.0
CLOUD_STT_MAX_SECS = 20        # longest utterance sent to the cloud

# Keep the last N utterances (WAV + both transcripts) in stt_log/ to review
# misrecognitions. Off by default: it stores your voice on the Pi.
# .env: LUNA_STT_SAVE=40
STT_SAVE_UTTERANCES = int(os.environ.get("LUNA_STT_SAVE", "0") or 0)

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
CLOUD_WAKE_MAX_PER_HOUR   = 60     # and at most this many an hour (TV on…)

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
# The utterance is over after this much silence following real speech (Vosk
# alone waits ~1.05 s). Raise it if she answers before you finish sentences
# with long pauses.
STT_END_SILENCE = 0.6    # (was 0.75 — 6 Oct: "more snappy"; a sentence cut mid-word
                         # still waits for its end, see speech_to_text.cut_off)
STT_END_SILENCE_SHORT = 1.1   # ...but one or two words ("Nie.", "No więc…") wait
                         # longer: a pause after an opener is the middle of a
                         # thought (6 Oct: "Ale nie przerywaj mi, jak mówię")

# Print per-utterance rms/confidence so the thresholds above can be tuned.
STT_DEBUG_AUDIO = True

# ── TTS (OpenAI, streamed PCM) ────────────────────────────────────────────────

TTS_RATE = 155   # legacy, unused by the OpenAI engine

OPENAI_TTS_MODEL        = "gpt-4o-mini-tts-2025-12-15"   # the plain name still served
                        # the older snapshot: first audio 0.93 s median (worst 42 s) vs
                        # 0.66 s (worst 9.3 s) for this one, 8 lines each (7 Oct)
# .env: LUNA_TTS_VOICE=nova   (alloy, ash, ballad, coral, echo, fable, nova,
# onyx, sage, shimmer, verse, marin, cedar — nova/shimmer/marin are the bright ones)
OPENAI_TTS_VOICE        = _env("LUNA_TTS_VOICE", "marin")
OPENAI_TTS_SPEED        = 1.2     # the house rate (6 Oct: "20% faster", Andrzej); per person
                                  # in settings "tts_speed_by"
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
OPENAI_TTS_TIMEOUT      = 8.0 
# The reply's emotion (the one her face shows) colours the voice too: this is
# appended to the instructions for that one sentence. Same voice, different
# mood — every line keeps the "high, light, girlish" identity above.
TTS_EMOTION_STYLE = {
    "happy":     "Right now you are cheerful: a bright smile in the voice, a "
                 "little livelier than usual.",
    "excited":   "Right now you are excited and enthusiastic: more energy, a "
                 "slightly quicker pace and bigger intonation — still natural.",
    "love":      "Right now you are tender and affectionate: warm, soft, a "
                 "little slower, as if talking to someone you adore.",
    "sad":       "Right now you are gentle and sympathetic: softer, a bit "
                 "slower and quieter — but keep the same high, light voice.",
    "surprised": "Right now you are genuinely surprised: a lively rise in the "
                 "intonation, a touch of disbelief.",
    "angry":     "Right now you are playfully grumpy, mock-annoyed with a "
                 "pout — never actually aggressive or harsh.",
    "sleepy":    "Right now you are telling a bedtime story: very calm, soft "
                 "and slow, a little sleepy, gentle pauses — soothing, almost "
                 "a lullaby.",
}
# How the listener seems on camera (brain.USER_MOODS) can soften the delivery.
TTS_LISTENER_STYLE = {
    "tired":    "The listener looks tired: keep it calm, unhurried and soft.",
    "sad":      "The listener looks sad: be extra gentle and warm.",
    "stressed": "The listener looks stressed: calm, steady and reassuring.",
}
# One long-lived player fed with silence between replies (audio_out.py):
# no per-reply player start, no stream-open pop, no lead-in silence. False =
# the old way (a pw-play per reply).
AUDIO_PERSISTENT  = True
AUDIO_AHEAD_SECS  = 0.40    # audio kept queued in the player: the writer
                            # thread stalled up to 0.18 s under face rendering
AUDIO_PREBUFFER_SECS = 0.35 # speech held back before it starts. The TTS API sends
                            # a first burst, then pauses ~0.2–0.35 s: with 0.15
                            # EVERY reply had a hole after its first syllables
                            # (measured 2026-10-04); with 0.3 none did
NIGHT_VOICE_GAIN  = 0.5     # during the quiet hours she speaks at half volume
                            # (and her mouth moves less) — 1.0 = off
TTS_STREAM_PREBUFFER_SECS = 0.3  # streamed replies: an underrun there is filled with
                                  # silence (a pause, not crackle), so less is safe
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
OPENAI_MAX_TOKENS   = 700   # room for a story when asked (the persona keeps
                            # ordinary answers short; 200 could cut the JSON)
OPENAI_TEMPERATURE  = 0.8   # creativity (0.0 = factual, 1.0 = creative)
OPENAI_MAX_HISTORY  = 12    # max conversation history messages sent to the API
                            # (6 exchanges — riddles, follow-ups, "another one")

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
    # homework held up to the camera: the task must be readable (high detail)
    "zadani", "ćwiczeni", "cwiczeni", "zeszyt", "książk", "ksiazk", "stron",
    "kartk", "rysun", "obrazek", "obrazku",
    # English
    "see", "look", "read", "written", "text", "what is this", "what's this",
    "camera", "what am i", "holding", "wearing", "who is", "how many",
    "describe", "color", "colour", "label", "screen", "picture", "photo",
]
VISION_JPEG_QUALITY = 80

# ── Local commands (commands.py) — handled without the model ─────────────────
VOLUME_STEP      = 0.10   # "głośniej" / "ciszej"
VOLUME_MIN       = 0.10   # never fully silent by voice — she must answer you
VOLUME_MAX       = 1.00
SPEED_STEP       = 0.10   # "mów wolniej" / "mów szybciej"
SPEED_MIN, SPEED_MAX = 0.75, 1.60
SETTINGS_PATH    = os.path.join(DATA_DIR, "settings.json")
SLEEP_BRIGHTNESS = 3      # screen % while she sleeps ("dobranoc")
# Night mode (display.py): during the quiet hours the screen dims by itself,
# and comes up a bit while you talk to her. Never above LUNA_BRIGHTNESS.
# Auto-brightness from the room's light (display.py, camera_thread.py). The
# camera's auto-exposure hides darkness in the picture, so the light level is
# picture brightness ÷ exposure time; log10 of it is compared with these.
# Measured: daylight ≈ -0.15 (mean 111 / exposure 156). The dark end is a
# conservative guess — the hourly [health] line logs "light" for tuning.
AMBIENT_AUTO           = True
AMBIENT_LOG_BRIGHT     = -0.8   # at or above: LUNA_BRIGHTNESS
AMBIENT_LOG_DARK       = -2.2   # at or below: AMBIENT_MIN_BRIGHTNESS
AMBIENT_MIN_BRIGHTNESS = 25
LAMP_BRIGHTNESS       = 45     # "włącz lampkę": the night-light level
NIGHT_MODE            = True
NIGHT_BRIGHTNESS      = 12
NIGHT_TALK_BRIGHTNESS = 40
BREATH_IN, BREATH_HOLD, BREATH_OUT = 4.0, 2.0, 6.0   # "ćwiczenie oddechowe"
BREATH_CYCLES = 5
FOCUS_MINUTES = 25        # "tryb skupienia" (pomodoro): quiet, then a break
BREAK_MINUTES = 5
GOODBYE_REPLIES = ["Pa pa!", "Do zobaczenia!", "Na razie!", "Papa, wracaj szybko!"]
GOODNIGHT_REPLIES = ["Dobranoc! Śpij dobrze.", "Dobranoc, słodkich snów!",
                     "Dobranoc. To ja też się zdrzemnę."]

# ── Weather (weather.py) — opt-in ────────────────────────────────────────────
# .env: LUNA_LAT=52.23  LUNA_LON=21.01  (decimal degrees). Unset = off, and
# nothing is sent anywhere. open-meteo.com, free, no API key.
def _coord(name):
    try:
        return float(os.environ.get(name, "").strip())
    except ValueError:
        return None
WEATHER_LAT          = _coord("LUNA_LAT")
WEATHER_LON          = _coord("LUNA_LON")
WEATHER_REFRESH_SECS = 1800

# ── Health (health.py) ───────────────────────────────────────────────────────
HEALTH_PROBE_SECS = 60     # while offline, check the API is reachable this often
HEALTH_LOG_SECS   = 3600   # a "[health]" summary line in luna.log

LISTS_PATH = os.path.join(DATA_DIR, "lists.json")

# ── Timers & reminders (timers.py) ───────────────────────────────────────────
TIMERS_PATH       = os.path.join(DATA_DIR, "timers.json")
LOG_MAX_MB        = 5     # health.py rotates luna.log beyond this (once an hour)
TIMERS_MAX        = 10
TIMER_REPEAT_SECS = 60    # nobody reacted to the ring → once more after this
SNOOZE_MINUTES    = 9     # "drzemka" with no number
SUNRISE_SECS      = 600   # a wake-up alarm brightens the screen this long before

# ── Whole-screen moments (screens.py) ────────────────────────────────────────
MIRROR_SECS     = 15
CLOCK_SECS      = 10
PHOTO_SHOW_SECS = 6
PHOTOS_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
PHOTOS_KEEP     = 50      # older photos are deleted

# ── Between conversations (idle_engine.py: greeting you, touch voice) ─────────
IDLE_ABSENCE_SECS    = 600     # away this long → she greets you when you return
IDLE_DEBUG           = False   # log presence transitions
IDLE_PRESENCE_GRACE  = 8       # "you are here" if a face was seen this recently
                               # (raw face_detected flickers several times a
                               # minute)

# ── The user's mood (brain.py) ───────────────────────────────────────────────
# Read from the camera frame on every request and used to set her tone.
# Mentioning it out loud is rationed: the same mood twice in a row, one of
# these, and not more often than the cooldown.
MOOD_COMMENT_MOODS    = ["tired", "sad", "stressed", "happy"]
MOOD_COMMENT_COOLDOWN = 1800   # seconds (30 min)

# ── Non-verbal sounds (sounds.py) ────────────────────────────────────────────
# "mhm", "hmm", "hm?", a giggle, "oh!" — made once by her own TTS voice,
# cached in data/sounds/, then played locally with no delay or cost.
SOUNDS_ENABLED       = os.environ.get("LUNA_SOUNDS", "1").strip().lower() \
                       not in ("0", "false", "no", "off")
SOUNDS_DIR           = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "data", "sounds")
WAKE_SOUND_CHANCE    = 0.7    # "Luna!" alone → a quick "hm?" instead of a sentence
THINK_SOUND_DELAY    = 1.3    # answer not there after this long → a "hmm"
THINK_SOUND_CHANCE   = 0.5    # ...this often (every time gets old)
THINK_SOUNDS         = ["hmm", "mhm"]
TOUCH_SOUND_CHANCE   = 0.75   # touched and not answering with words → a sound
TOUCH_SOUND_COOLDOWN = 3.0
# (zone, kind) → sounds; zone None = any zone
TOUCH_SOUNDS = {
    ("eye", "tap"):    ["oh"],
    ("mouth", "tap"):  ["giggle"],
    (None, "tap"):     ["huh", "giggle"],
    (None, "stroke"):  ["aww", "giggle"],
    (None, "multi"):   ["hey"],
}

# ── Long-term memory (memory.py) ─────────────────────────────────────────────
# After each conversation one cheap model call updates data/memory.json
# (facts about you + a line about what you talked about); it is added to the
# system prompt, so she can ask tomorrow how things went. Plain JSON on the
# Pi — "Luna, zapomnij wszystko" wipes it. .env: LUNA_MEMORY=0 turns it off.
MEMORY_ENABLED         = os.environ.get("LUNA_MEMORY", "1").strip().lower()                          not in ("0", "false", "no", "off")
MEMORY_PATH            = os.path.join(DATA_DIR, "memory.json")
MEMORY_MODEL           = "gpt-4.1-mini"
MEMORY_TIDY_MODEL      = "gpt-4.1"   # the first one each day: it also weeds out
                                     # junk facts, which the mini model won't
MEMORY_MAX_FACTS       = 40
MEMORY_MAX_EPISODES    = 30    # kept in the file
MEMORY_PROMPT_EPISODES = 6     # the most recent ones go into the prompt
MEMORY_MAX_THREADS     = 5     # open follow-ups ("jak poszła rozmowa?")
MEMORY_THREAD_ASKS     = 2     # offered in at most this many conversations
FORGET_PHRASES = ["zapomnij wszystko", "zapomnij o mnie", "wyczyść pamięć",
                  "wyczysc pamiec", "wymaż pamięć", "wymaz pamiec",
                  "forget everything", "forget about me"]
FORGET_REPLY   = "Dobrze. Zapomniałam wszystko, co o tobie wiedziałam."

# ── Proactive speech (the scarce resource — animations are free) ──────────────
PROACTIVE_SPEECH       = True
PROACTIVE_MIN_GAP_SECS = 900   # at most one unprompted line per 15 min
PROACTIVE_QUIET_FROM   = 22    # no unprompted talking between these hours
PROACTIVE_QUIET_TO     = 8
MUTE_SECS              = 3600  # "Luna, cicho" silences her for this long
MUTE_PHRASES   = ["cicho", "bądź cicho", "badz cicho", "nie odzywaj się",
                  "nie odzywaj sie", "zamilcz", "be quiet", "hush"]
UNMUTE_PHRASES = ["możesz mówić", "mozesz mowic", "odzywaj się", "odzywaj sie",
                  "you can talk", "unmute"]

# (without gender: these are for someone she doesn't recognise)
GREETINGS_MORNING = ["Dzień dobry!", "O, dzień dobry! Jak się spało?",
                     "Dobry! Zaczynamy dzień?"]
GREETINGS_DAY     = ["O, jesteś!", "Hej, jesteś z powrotem!", "Cześć! Tęskniłam trochę."]
GREETINGS_EVENING = ["Dobry wieczór!", "O, jesteś. Jak minął dzień?"]
GREETINGS_NIGHT   = ["Jeszcze nie śpisz?", "O, cześć. Późno już."]
GREETINGS_FIRST_TODAY = ["Dzień dobry! Pierwszy raz dziś cię widzę.",
                         "O, cześć! Czekałam na ciebie."]

# ── Touch (the 7" panel; see touch_module.py) ─────────────────────────────────
TOUCH_ENABLED      = True
TOUCH_DEVICE       = os.environ.get("LUNA_TOUCH_DEVICE", "").strip()  # "" = auto
TOUCH_TAP_MAX_SECS = 0.4    # longer than this isn't a tap
TOUCH_STROKE_MIN   = 0.06   # normalised travel that counts as stroking
TOUCH_STROKE_REPEAT = 0.35  # min seconds between "still being petted" events
TOUCH_MULTI_WINDOW = 1.6    # seconds
TOUCH_HOLD_SECS    = 0.7    # finger held still this long = "listen to me"
                            # (talk without the wake word)
TOUCH_MULTI_COUNT  = 3      # taps inside that window = "poking"
TOUCH_POKE_HOLD    = 3.0    # once poking starts, every further tap keeps her
                            # annoyed; she calms down this long after the last
                            # one (otherwise tap 4 read as a friendly tap again)
TOUCH_FLIP_X       = False  # set if the panel is mounted rotated
TOUCH_FLIP_Y       = False
TOUCH_DEBUG        = False

# Zones are worked out from where the face is drawn: "eye", "mouth", "top"
# (above the eyes), "other".
TOUCH_REACT_SECS      = 2.2   # how long the face holds its touch reaction
TOUCH_POKE_SECS       = 3.0   # ...when poked repeatedly (she sulks longer)
TOUCH_SPEECH_COOLDOWN = 25    # seconds between spoken touch reactions. Being
                              # touched is not "unprompted" — you started it —
                              # so it has its own short budget, not the 15 min
                              # proactive one (quiet hours and mute still apply)
TOUCH_REPLY_CHANCE = 0.6    # how often a touch also gets a spoken line
TOUCH_REPLIES = {
    "eye":   {"tap":    ["Hej, to moje oko!", "Łaskocze!"],
              "multi":  ["No dobra, wystarczy!", "Przestań mnie dziobać!"]},
    "mouth": {"tap":    ["Mmm?", "Chcesz, żebym coś powiedziała?"]},
    "top":   {"stroke": ["Mmm, miło...", "Głaszcz dalej!"],
              "tap":    ["Hej!"]},
    "other": {"stroke": ["Miło.", "Lubię to."],
              "multi":  ["Ej, spokojnie!"]},
}

# ── Expressions ───────────────────────────────────────────────────────────────
FACE_OVERRIDE_SECS     = 4.0   # how long the LLM-chosen emotion lingers after a reply

# ── Gestures (camera motion, see gesture_module.py) ───────────────────────────
# ── Eyes that follow movement (gesture_module tracks it, robot_face looks) ──
GAZE_FACE_PUPIL   = 0.4    # pupil shift per face offset (was 0.25)
GAZE_MOTION_PUPIL = 0.8    # pupil shift toward something moving
GAZE_MOTION_MAX_W = 0.65   # how far a glance at movement pulls away from a face
GAZE_MOTION_HOLD  = 1.0    # keep looking where it moved this long after it stops
GAZE_MOTION_MIN   = 0.05   # weaker movement (strength 0..1) is ignored

GESTURE_FPS            = 15    # analysis rate (160x120 frame differencing, ~1 ms);
                               # a quick wave needs several samples per swing
GESTURE_DEBUG          = False # log every near-miss with its features (tuning)
GESTURE_REACT_COOLDOWN = 4.0   # seconds between reactions to the same gesture

# A wave = a hand-sized moving blob near the face that reverses horizontal
# direction several times within a short window.
WAVE_WINDOW_SECS       = 2.4   # how long a stretch of movement is judged at
                               # once — longer means she needs to see you keep
                               # it up before she believes you
WAVE_MIN_REVERSALS     = 7     # ~3.5 full back-and-forths inside that window
WAVE_MIN_AMPLITUDE     = 0.8   # (was 0.35: on 4 Oct a hand moving near the face at
                               # the desk — 14–27 px of travel with a 40 px face —
                               # "waved" seven times in minutes; real waves in the
                               # same log travelled 107–151 px)  # sideways travel ≥ this × the face width
                               # (scale-free: works close up and far away)
WAVE_MIN_SWING         = 0.15  # a half-swing must travel ≥ this × face width
                               # before a direction change counts (kills jitter)
WAVE_MAX_VERTICAL      = 3.0   # loose sanity limit only: the motion blob
                               # (hand + forearm) moves a lot vertically even
                               # in a real wave, so this can't be strict
WAVE_MIN_PRESENCE      = 0.6   # at a WAVE_SKIN_REF_FW-wide face; scales down
                               # with distance to WAVE_MIN_PRESENCE_FLOOR —
                               # a far hand's motion blob flickers at the turns
WAVE_MIN_PRESENCE_FLOOR = 0.35
                               # the moving blob must be present in this
                               # fraction of the window's samples — a hand
                               # holding something up stops moving
WAVE_MIN_MEAN_SPEED    = 0.12  # mean sideways speed ≥ this × face width per
                               # sample (a wave keeps moving)
WAVE_SWING_REGULARITY  = 0.0   # off — measured real waves are irregular
                               # (0.2-0.35) at 15 fps sampling
WAVE_MIN_AREA          = 12    # blob size limits (px² at 160x120) — a far
                               # hand is small
WAVE_MAX_AREA          = 2200
WAVE_DIFF_THRESHOLD    = 16    # frame-difference level that counts as motion
                               # (lower = a small far hand still registers)
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
WAVE_CONFIRM_MIN_GAP   = 3.0
WAVE_SPEAK_GAP         = 900   # she waves back every time, but SAYS hello at most
                               # this often   # seconds between confirmation requests

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
