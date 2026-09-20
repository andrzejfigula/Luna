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
sudo apt-get install -y python3-pygame python3-numpy python3-opencv libportaudio2 rtkit
# realtime priority for PipeWire's audio thread — without it the face
# renderer preempts audio and replies crackle. Takes effect after a reboot.
sudo usermod -aG pipewire $USER

# 2. project + venv (must see the apt packages → --system-site-packages)
git clone <this repo> ~/luna && cd ~/luna
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt

# 3. Vosk model (local wake-word spotting + endpointing, ~90 MB)
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-pl-0.22.zip
unzip vosk-model-small-pl-0.22.zip && rm vosk-model-small-pl-0.22.zip

# 4. OpenAI key + hardware choices
cp .env.example .env && nano .env      # OPENAI_API_KEY=sk-...
```

`.env` also selects the hardware (all optional, auto-detect when empty):

| Variable | Values | Example |
|---|---|---|
| `LUNA_CAMERA` | V4L2 index or device path | `0`, `/dev/video2` |
| `LUNA_MIC` | sounddevice index or part of the name | `C270` |
| `LUNA_SPEAKER` | `jack` (3.5 mm), `hdmi`, `bluetooth`, `default`, or a PipeWire node name | `jack` |
| `LUNA_TTS_VOICE` | OpenAI voice — `nova`, `shimmer`, `marin` are bright; `coral`, `sage` calmer | `nova` |
| `LUNA_BRIGHTNESS` | touchscreen backlight, percent (applied by `run.sh`) | `100` |
| `LUNA_TIMEZONE` / `LUNA_LOCATION` | IANA zone + place name given to the model with the current local time | `Europe/Warsaw` / `Poland` |

Output volume follows the chosen PipeWire sink: `wpctl status` lists them,
`wpctl set-volume <id> 1.0` sets it.

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

- `WAKE_WORDS`, `WAKE_FUZZY_RATIO`, `CLOUD_WAKE_CHECK` — Vosk-small often
  mishears "Luna"; the cloud check catches those (one cheap transcription per
  sentence heard while idle). Add variants from `luna.log` if needed.
- `TTS_PREBUFFER_SECS` — raise if replies crackle mid-sentence.
- Lip sync: `LIPSYNC_LATENCY_MS` (mouth ahead of sound → raise, behind →
  lower), `LIPSYNC_GAIN` (wider mouth), `LIPSYNC_RMS_FULL` (loudness that
  counts as fully open), `LIPSYNC_ATTACK/RELEASE` (smoothing).
- `TTS_LEADIN_SECS` — silence before each reply; the Pi's 3.5 mm output pops
  when a stream opens. `install_autostart.sh` also installs a WirePlumber
  rule (`pi/51-luna-no-suspend.conf`) that stops the jack from suspending.
- `OPENAI_MODEL`, `OPENAI_TTS_INSTRUCTIONS` (voice character), `OPENAI_TTS_SPEED`
- `CLOUD_STT_LANGUAGE = "pl"` to force Polish instead of auto-detect.
- `REQUIRE_FACE_TO_TALK` — only answer when someone is facing the camera.
- `VISION_ALWAYS` — a low-detail camera frame (~85 tokens) goes with every
  request so Luna always "sees"; `VISION_KEYWORDS` (zobacz, przeczytaj, jaki
  kolor, read…) switch it to high detail for that question.
- `data/persona.txt` — who Luna is and how she talks (identity, gender,
  language, tone). Plain text, edit freely, restart to apply.
  `data/knowledge.txt` — optional facts appended to the prompt.
- `FACE_STYLE` — 1 purple "Luna classic", 2 cyan "robo", 3 amber "loona"
  (default; gradient block eyes with pupils, hair and hands).
  Keys 1/2/3 switch live when a keyboard is attached.
- Gestures: Luna nods / shakes her head / waves / thumbs-up / makes a heart
  when it fits the reply (the LLM picks, see `brain.py`). Wave at the camera
  and she waves back (`gesture_module.py`, motion-based; `WAVE_*` in config).

## Troubleshooting

- **Crackle mid-sentence** → check `pw-top` while a reply plays: the
  `alsa_output…` line must show QUANT 1024 and a non-increasing ERR count.
  `install_autostart.sh` installs `pi/51-luna-quantum.conf` (PipeWire) and
  `pi/51-luna-no-suspend.conf` (WirePlumber) which fix this on the Pi 4's
  3.5 mm output. Also make sure PipeWire is realtime
  (`ps -eLo cls,rtprio,comm | grep data-loop` → `FF 8x`; otherwise do the
  `rtkit` + `usermod -aG pipewire` step and reboot). `run.sh` runs Luna at
  `nice 10` as well. Lowering `RENDER_FPS` is a last resort, not needed.
- **No sound** → audio goes through PipeWire (`LUNA_SPEAKER`, default sink
  when unset); the startup log line `[TTS] … → <sink>` shows where it went.
  `wpctl status` lists sinks, `wpctl set-volume <id> 1.0` fixes a quiet one
  (the 3.5 mm jack ships at 40 %). `aplay` is NOT used because
  `pipewire-alsa` isn't on the stock image.
- **Mic not found** → `./venv/bin/python -c "import sounddevice as sd; print(sd.query_devices())"`
  and set `AUDIO_INPUT_DEVICE`.
- **Nothing recognised** → `STT_DEBUG_AUDIO=True` prints `heard=... peak_rms=... gate=...`;
  speech should sit well above the gate.
- **Face not fullscreen / wrong screen** → `run.sh` sets `SDL_VIDEODRIVER=wayland`
  and `WAYLAND_DISPLAY=wayland-0`; it must run inside the desktop session.
