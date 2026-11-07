# Luna — notes for Claude

A Loona-like desk robot on a Raspberry Pi 4 (Polish first): face on a 7"
touchscreen, Logitech C270 camera + mic, Bluetooth speaker, OpenAI for chat,
speech-to-text and TTS. The family (Andrzej, Emilka, Maja, 8) uses her daily
while you work. Code here (`D:\Code\luna`, Windows + Git Bash); the Pi copy
`raspberry@raspberrypi.local:~/luna` is NOT a git checkout.

## Save tokens

- Every call re-reads the whole conversation, so the cost is calls × context
  (measured: 99% of tokens). Batch independent commands into one Bash call,
  read a file once, `grep -c`/`-l` before a broad grep. Context compacts at
  200k. `.claude/settings.json` denies unused tools, but their schemas still
  load: the first context is ~54k whatever we do. Check with
  `python -X utf8 tools/claude_usage.py [--tools]` (`sed` and `grep` output cost most).
- Find code with `python -X utf8 tools/codemap.py` (a line per module), `… radio`
  (its defs with line numbers), `… -f word` (a def by name), then read line
  ranges; most modules are 500–3500 lines, and Polish lines are long: `| cut -c1-200`.
- How to add a command, mode, screen, setting: `docs/recipes.md`. Measuring and
  baselines: `docs/performance.md`.
- Old, don't trust them: `README.md`, `UPDATES.txt`, `IMPROVEMENTS-3.md`.
- Logs: `bash tools/lastlog.sh [lines] [all] ['extra|pattern']` — only the
  useful lines since the last restart. A day's summary:
  `ssh raspberry@raspberrypi.local 'cd ~/luna && python3 tools/log_report.py'`
  (last 40 exchanges; `--all` is ~20k tokens).
- Backlog: `BACKLOG.md` is only what's open; `docs/backlog-done.md` (400 KB) is
  history, don't open it. `python -X utf8 tools/backlog.py find WORDS | show N |
  recent | open | add "**Title** — what changed" "why" [⏳] | done N | check`.
  Proposals not agreed yet: `docs/ideas.md`, `python -X utf8 tools/ideas.py area=games
  size=S | stats | show N | keep/drop/undo/built N | page` (writes a page to tick them);
  ✗ means don't propose it again.
- Keep new code comments to a line or two; the story goes in the commit.

## Ship (test → copy → restart, ~50 s)

    git add <new files> && bash tools/ship.sh   # --quick (unit + smoke) while tuning

check_pi.sh runs preflight, then the unit tests on the PC (the ones skipped
here — cv2, pygame — then on the Pi) beside routing + smoke | dialog on the Pi,
in a per-run `/tmp/lunacheck-run-*` (`full`: all four on the Pi, before a merge).
Code that already passed isn't checked again (`LUNA_CHECK_AGAIN=1` forces it).
New files must be `git add`ed or the Pi never sees them; add them by name, not
`-A` (`docs/screens/` isn't ours; preflight lists what's untracked). deploy.sh
copies changed tracked files (one tar connection; never `.env`, `data/`, `.md`).
ship.sh restarts only if code outside tools/tests/docs changed (`--restart`
forces it, `--no-check` skips the tests); `restart.sh --now --tested` skips
re-testing code that just passed and prints `restart: OK — pid N` or the error.
Don't write your own ssh wait loops (`pgrep -f restart.sh` matches itself and
hangs). Local run: `python -X utf8 tests/run_unit.py --jobs 8` (8 s).
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
- No idle animations (she does nothing on her own). A face she learns is a
  guest (`faces.is_family`): no plan, no house info; only family make it family.
- Side talk in the open window: measured, left as is — mouth.py's "talking %"
  carries no signal with this camera (`docs/side-talk.md`, `tools/mouth_stats.py`).
- Parked: interrupting her by voice/camera (until a hardware-AEC speakerphone,
  `docs/voice-interrupt.md`); the web panel.
- User-visible change → a plain-Polish line on top of `data/whatsnew.txt`.
- **Before proposing a feature, check it isn't built already** (860+ are):
  `python -X utf8 tools/backlog.py find radio piosenk` (Polish and English;
  it matches pieces of words, so give stems). E.g. messages for a family member exist
  (`messages.py`). Propose only what's missing, or name the existing module
  and suggest an improvement to it.

## Pitfalls

- Patches: use the Edit tool, or a script file written with the Write tool.
  Python/bash heredocs (even one that writes a script file) turn `\b` into a
  backspace byte, `\U0001F300` into the character and `\\s` into `\s`
  (deploy.sh refuses control chars). Need an emoji range? `chr(0x1F300)`.
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
- SSH ControlMaster doesn't work under this Git Bash (`mux_client_request_session`):
  to save connections, put more into one ssh call.

## Module map

Voice in → `speech_to_text.py` (Vosk gating + cloud transcription, wake word,
conversation window, radio-on wake with `mouth.py`), `activation.py` (name heard
→ she answers), `intent.py` (asking or just mentioning), `echo.py` (her own voice
coming back). `main.py` voice loop: mute → forget → `commands.py` (`handle`: local,
no model) → `brain.py` (OpenAI chat, persona, actions), `reply_stream.py` (the reply
out of the JSON as it comes). Voice out → `text_to_speech.py`, `openai_tts.py`,
`audio_out.py`, `polish.py` (numbers, grammar), `tts_fx.py` (a theme's voice),
`voicecheck.py` (a take in her register?), `sounds.py` ("mhm", a giggle).
`openai_client.py` (the SDK loaded on first use). State: `shared_state.py`; settings: `config.py`, `settings.py`, `settings_page.py`; `devices.py` (speaker, mic, camera).

Camera: `camera_thread.py`, `vision_module.py` (faces, addressed speech),
`faces.py` (who), `mouth.py` (talking, seen), `gesture_module.py`.
Face/screen: `robot_face.py`, `face_renderer.py`, `face_spec.py`,
`reply_scenes.py`, `ui_screens.py` (`ui_lessons.py`, `ui_paint.py`, `ui_schedule.py`),
`screens.py`, `autoclose.py`, `dock.py`, `controls.py` (the lamp's / music's strip), `statusbar.py`, `themes.py`, `perf_hud.py`,
`touch_module.py`, `display.py`. GPU: `gl_fx.py` (over the face), `gl_lamp.py` with
`lamp_scenes.py` (the lamp), `gl_vis.py` with `visualizer.py` (the radio). The sky behind Luna's own face:
`environment.py` (time, sun, season, weather → colours; TUNE), its glow in
`gl_face.py`'s soft pass, rain/snow/stars/arc as meshes in `gl_env.py`;
`tools/env_sim.py` simulates it on the Pi, `gl_face_preview.py --env` renders it. Drawn characters: `characters.py` (data,
CharLife), `gl_chars.py` (shaders); Mochi's ears/paws/glyphs: `mochi_rig.py`
(preview: `tools/gl_face_preview.py --chars|--fx … mochi`, offscreen on the Pi).

Features: `radio.py`, `timers.py`, `lists.py`, `weather.py`, `clock.py`,
`calc.py`, `agenda.py` with `ui_agenda.py` (the calendar: dated events, reminders), `moon.py`, `news.py`, `websearch.py`, `webphoto.py`, `drawing.py`,
`gallery.py`, `messages.py`, `contacts.py` with `ui_contacts.py` (a card for each person), `phone.py` with `phone_link.py` (BlueZ, MAP, PBAP) and `ui_phone.py` (a paired phone's SMS), `errands.py`, `birthdays.py`, `cooking.py`,
`reading.py`, `homework.py`, `kids.py`, `story.py`, `voicefx.py`,
`ambience.py`, `breathing.py`, `counting.py`, `paint.py`, `schedule.py`, `printer.py`. Games: `quiz.py`/`quizdata.py`,
`twenty.py`/`twenty_kb.py`, `tictac.py`, `memo.py`, `games.py`, `clockgame.py`,
`riddles.py`, `fun.py`, `hangman.py` (wisielec). Her: `memory.py`, `mood.py`, `relationship.py`,
`greetings.py`, `idle_engine.py`, `behavior_engine.py`, `body.py`.
Robustness: `watchdog.py`, `health.py`, `hedge.py`, `prio.py`, `holds.py`,
`backup.py`, `timing.py` (latency), `weekly.py`.

Tests: `tests/test_local_logic.py` (unit), `tests/test_routing.py`, `tests/smoke_pi.py`,
`tests/dialog_pi.py`, `tests/scenario_pi.py` / `tests/model_pi.py` / `tools/sweep.py` +
`tests/sweeps/*.txt` (real model), `tests/test_dev_tools.py` (these tools; this map
stays complete). Docs: `SETUP.md` (Pi setup), `CO_NOWEGO.md` (Polish cheat sheet for
the family), `docs/recipes.md`, `docs/performance.md`.
