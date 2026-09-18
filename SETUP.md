# Luna on Raspberry Pi 4 — Setup & Run

This fork turns Luna into a Loona-style desktop robot: animated face on the
official 7" touchscreen, voice conversation in Polish/English through OpenAI,
camera vision, LLM-controlled emotions. No servos, no local ML models.

## Hardware / OS this is built for

| | |
|---|---|
| Board | Raspberry Pi 4 Model B, 4 GB |
| OS | Raspberry Pi OS (Debian 13 "trixie"), 64-bit, Wayland/labwc desktop |
| Python | 3.13 (system) |
| Display | 7" DSI touchscreen, 800×480 |
| Camera + mic | Logitech C270 (`/dev/video0`, mic `hw:3,0`, 16 kHz mono) |
| Speaker | anything PipeWire plays to — Bluetooth, 3.5 mm jack or HDMI |

## Install

```bash
# 1. system packages (pygame / numpy / opencv come from apt, not pip)
sudo apt-get update
sudo apt-get install -y python3-pygame python3-numpy python3-opencv libportaudio2

# 2. project + venv (must see the apt packages → --system-site-packages)
git clone <this repo> ~/luna && cd ~/luna
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt

# 3. Vosk model (local wake-word spotting + endpointing, ~90 MB)
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip
unzip vosk-model-small-pl-0.22.zip && rm vosk-model-small-pl-0.22.zip

# 4. OpenAI key
cp .env.example .env && nano .env      # OPENAI_API_KEY=sk-...
```

## Run

```bash
./run.sh            # from a terminal on the Pi or over SSH (sets up Wayland env)
./stop.sh           # stop it (also stops the autostart watchdog)
```

Start with the desktop and auto-restart on crash:

```bash
./install_autostart.sh     # adds an lwrespawn line to ~/.config/labwc/autostart
```

Log: `~/luna/luna.log`. ESC on an attached keyboard quits; keys 1/2 switch face style.

## How a conversation flows

```
C270 mic ─► sounddevice 16 kHz ─► energy gate ─► Vosk (wake word "Luna", endpointing)
     ─► utterance audio ─► OpenAI gpt-4o-mini-transcribe (auto PL/EN)
     ─► brain.py: gpt-4.1-mini, JSON {reply, emotion} (+ camera JPEG if the
        question is visual: "co widzisz", "ile palców", "what is this"…)
     ─► state.emotion drives the face ─► gpt-4o-mini-tts streamed as PCM ─► pw-play
```

Say **"Luna"** first; after that the conversation window stays open for
`CONVO_TIMEOUT` seconds per turn, no wake word needed. When nobody has been in
front of the camera for 30 s the face goes to sleep.

## Tuning (config.py)

- `WAKE_WORDS`, `WAKE_FUZZY_RATIO` — Vosk-small sometimes mishears "Luna"; add
  variants it produces (check `luna.log`) or lower the ratio a little.
- `OPENAI_MODEL`, `OPENAI_TTS_VOICE`, `OPENAI_TTS_INSTRUCTIONS`
- `CLOUD_STT_LANGUAGE = "pl"` to force Polish instead of auto-detect.
- `REQUIRE_FACE_TO_TALK` — only answer when someone is facing the camera.
- `VISION_KEYWORDS` — which questions get a camera frame attached.
- `SYSTEM_PROMPT` — Luna's personality. `data/knowledge.txt` — optional facts.
- `FACE_STYLE` — 1 purple "Luna classic", 2 cyan "robo".

## Troubleshooting

- **No sound** → audio goes through PipeWire's default sink; check
  `wpctl status` and `wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0`. `aplay` is
  NOT used because `pipewire-alsa` isn't on the stock image.
- **Mic not found** → `./venv/bin/python -c "import sounddevice as sd; print(sd.query_devices())"`
  and set `AUDIO_INPUT_DEVICE`.
- **Nothing recognised** → `STT_DEBUG_AUDIO=True` prints `heard=... peak_rms=... gate=...`;
  speech should sit well above the gate.
- **Face not fullscreen / wrong screen** → `run.sh` sets `SDL_VIDEODRIVER=wayland`
  and `WAYLAND_DISPLAY=wayland-0`; it must run inside the desktop session.
