# Luna — notes for Claude

A Loona-like desk robot on a Raspberry Pi 4 (Polish first): face on a 7"
touchscreen, Logitech C270 camera + mic, Bluetooth speaker, OpenAI for chat,
speech-to-text and TTS. The family (Andrzej, Emilka, Maja, 8) uses her daily
while you work. Code here (`D:\Code\luna`, Windows + Git Bash); the Pi copy
`raspberry@raspberrypi.local:~/luna` is NOT a git checkout.

## Save tokens

- Find code with `grep -n` and read line ranges; most modules are 500–3500
  lines. The module map below says where to look.
- Logs: `bash tools/lastlog.sh [lines] [all] ['extra|pattern']` — only the
  useful lines since the last restart. A day's summary:
  `ssh raspberry@raspberrypi.local 'cd ~/luna && python3 tools/log_report.py'`.
- `docs/backlog-done.md` (350 KB) is history — don't open it unless asked.
  New rows: `python tools/backlog_add.py "**Title** — what changed" "why"`.
- Keep new code comments to a line or two; the story goes in the commit.

## Ship (test → copy → restart, ~45 s)

    git add -A && bash tools/ship.sh          # --quick (unit + smoke) while tuning

check_pi.sh runs the unit tests on the PC (the ones skipped here — cv2,
pygame — then on the Pi) beside routing + smoke | dialog on the Pi, in a
per-run `/tmp/lunacheck-run-*` (`full`: all four on the Pi, before a merge).
New files must be `git add`ed or the Pi never sees them. deploy.sh copies changed tracked files (one tar
connection; never `.env`, `data/`, `.md`), `restart.sh --now --tested` skips
re-testing code that just passed and prints `restart: OK — pid N` or the error.
Don't write your own ssh wait loops (`pgrep -f restart.sh` matches itself and
hangs). Local quick run: `python -X utf8 -m unittest tests.test_local_logic`.
After a brain.py / prompt change, run ONE real-model line
(`tools/sweep.py`) before shipping — check_pi once passed with every answer broken.

## Rules from Andrzej (always)

- Work on a branch; **merge to main only when he says "merge"**:
  `git fetch && git merge-base --is-ancestor origin/main origin/<b> && git push origin origin/<b>:main`.
  Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Restart at will with `--now` (never wait for idle). No AUDIBLE tests at
  night or while the family uses her.
- sudo / apt: he runs them. Never print `.env` (OpenAI key) or use a password.
- Never delete or overwrite real data (`data/*.json`, lists, notes, memory,
  photos). Pi tests: fake `text_to_speech` + scratch `LUNA_DATA_DIR`
  (see `tests/dialog_pi.py`) — a handler once counted out loud, a test once
  left a real timer.
- Real-model sweeps cost money — keep them few (`--max-calls`).
- No idle animations (she does nothing on her own). Guests aren't auto-enrolled.
- Parked: interrupting her by voice/camera (until a hardware-AEC speakerphone,
  `docs/voice-interrupt.md`); the web panel.
- User-visible change → a plain-Polish line on top of `data/whatsnew.txt`.
- **Before proposing a feature, check it isn't built already** (741+ are):
  `grep -n -i '<keyword>' CO_NOWEGO.md docs/backlog-done.md *.py | head`
  (Polish and English words). E.g. messages for a family member exist
  (`messages.py`). Propose only what's missing, or name the existing module
  and suggest an improvement to it.

## Pitfalls

- Patches: use the Edit tool or a script FILE. Python/bash heredocs turn `\b`
  into a backspace byte and mangle `\n` (deploy.sh refuses control chars).
  Write files with `newline="\n"` (no CRLF).
- `pkill -f` / `pgrep -f` with a pattern that is in your own ssh command line
  hits the ssh shell (exit 255). Luna's pid: `pgrep -f "^./venv/bin/python -u main.py"`.
- Hung Luna: `kill -USR2 <pid>` dumps stacks into luna.log (before restarting);
  `kill -USR1` logs per-thread CPU.
- Keep heavy imports lazy (tests run on Windows without the openai SDK);
  no function-local re-imports of a module imported at the top (test_syntax).
- A new mode (game, reading…) must handle repeat / hint / stop and a request for
  something else, not end on any sentence it doesn't parse.
- Screenshot of the Pi screen: `ssh … "XDG_RUNTIME_DIR=/run/user/1000
  WAYLAND_DISPLAY=wayland-0 grim -s 0.5 /tmp/screen.png"`, scp, Read.

## Module map

Voice in → `speech_to_text.py` (Vosk gating + cloud transcription, wake word,
conversation window, radio-on wake with `mouth.py`), `echo.py` (her own voice
coming back). `main.py` voice loop: mute → forget → `commands.handle` (local,
no model) → `brain.py` (OpenAI chat, persona, actions). Voice out →
`text_to_speech.py`, `openai_tts.py`, `audio_out.py`, `polish.py` (numbers,
grammar). `openai_client.py` (the SDK loaded on first use). State: `shared_state.py`; settings: `config.py`, `settings.py`.

Camera: `camera_thread.py`, `vision_module.py` (faces, addressed speech),
`faces.py` (who), `mouth.py` (talking, seen), `gesture_module.py`.
Face/screen: `robot_face.py`, `face_renderer.py`, `face_spec.py`,
`reply_scenes.py`, `ui_screens.py`, `screens.py`, `statusbar.py`,
`touch_module.py`, `display.py`.

Features: `radio.py`, `timers.py`, `lists.py`, `weather.py`, `clock.py`,
`calc.py`, `moon.py`, `news.py`, `websearch.py`, `webphoto.py`, `drawing.py`,
`gallery.py`, `messages.py`, `errands.py`, `birthdays.py`, `cooking.py`,
`reading.py`, `homework.py`, `kids.py`, `story.py`, `voicefx.py`,
`ambience.py`, `breathing.py`, `counting.py`. Games: `quiz.py`/`quizdata.py`,
`twenty.py`/`twenty_kb.py`, `tictac.py`, `memo.py`, `games.py`, `clockgame.py`,
`riddles.py`, `fun.py`. Her: `memory.py`, `mood.py`, `relationship.py`,
`greetings.py`, `idle_engine.py`, `behavior_engine.py`, `body.py`.
Robustness: `watchdog.py`, `health.py`, `hedge.py`, `prio.py`, `holds.py`,
`backup.py`, `timing.py` (latency), `weekly.py`.

Tests: `tests/test_local_logic.py` (unit), `test_routing.py`, `smoke_pi.py`,
`dialog_pi.py`, `scenario_pi.py` / `model_pi.py` / `tools/sweep.py` +
`tests/sweeps/*.txt` (real model). Docs: `SETUP.md` (Pi setup), `CO_NOWEGO.md`
(Polish cheat sheet for the family).
