# Recipes — where a change goes

Line numbers drift: `python -X utf8 tools/codemap.py -f NAME` finds a def again.
Before any of these: `python -X utf8 tools/backlog.py find WORDS` (741+ features
exist, this one may too). A user-visible change ends with a plain-Polish line on
top of `data/whatsnew.txt`, a line in `CO_NOWEGO.md` and a backlog row.

## A voice command (local, no model)

1. `commands.handle` (`commands.py`, ~1620) is an ordered chain; the first `True`
   wins. Pages and wake-up first, then whatever is active (`quiz.active()` ~1795),
   new triggers late (`quiz.trigger` ~2598). A trigger placed above an active mode
   eats that mode's answers.
2. Match strictly: short utterances, anchored. An ordinary sentence that happens
   to contain the word must still reach the model (`intent.py` tells asking from
   mentioning).
3. The work goes in the feature's module, called with `speak`. Add a line to the
   list at the top of `commands.py`.
4. Tests: the sentence in `LOCAL` in `tests/test_routing.py`, a near miss in its
   `MODEL` list, a `(sentence, expected)` in `CASES` in `tests/dialog_pi.py`.

## The model can do it too (the "command" action)

The label goes through `brain.run_command` (~2559) into `commands.handle`, and only
if allowed: `brain.command_allowed`, `_GAME_OK` (a game; it needs an offer or a
request first), `_VOICED_OK` (speaks for itself). So: add the label to the list in
the prompt (`grep -n 'Switches only the app can flip' brain.py`) and to the allow
list. A prompt change needs ONE real-model line (`tools/sweep.py`, `--max-calls`).

## A mode or game

Copy the shape of `quiz.py`: `active()`, `stop()`, `trigger(text)`,
`start(kind, text, speak, play_sound_async)`, `answer(text, speak, play_sound_async)`.

- In `commands.handle`: `x.active() and x.answer(...)` with the other active modes,
  `x.trigger(text)` with the late ones.
- It must handle repeat, hint, stop (quiz: `_REPEAT_Q`, `_HINT_Q`, `_STOP`) and a
  request for something else: `answer` returns False and the sentence goes on down
  the chain. Never end on a sentence it doesn't parse.
- `modes.py`: a line in `AWAITING` (the window stays open over the radio while it
  waits); in `TAKERS` only if it takes the very next sentence before any command.
- Its file: `store.load(PATH, {}, "x")` / `store.save(PATH, data)`, never `json` by hand.
- `grep -n 'quiz.active()' *.py`: other code that must know a mode is on
  (`commands.py` ~1420: "Pokaż" isn't the page again while one is running).
- Tests: a unit test with a fake `speak`, cases in `tests/dialog_pi.py`, and the
  label in `_GAME_OK` if the model may start it.

## A screen

- Show: `screens._show(kind, secs, data)` sets `state.overlay`; `screens.show_weather`
  is a short example.
- Draw: `elif kind == "weather"` in `robot_face.py` (~3644) calls `ui_screens.draw_*`.
- Taps: `robot_face.py` ~2630–2694.
- Closing by itself with a countdown: `KINDS` in `autoclose.py`.
- A still page: add it to `still` in `face_renderer.py` (8 fps instead of the full
  pace; `ui_screens.moving` keeps full speed while it animates).
- See it: the screenshot line in CLAUDE.md's Pitfalls.

## A setting

Default in `config.py`, value through `settings.get(key, default)` /
`settings.put` (`data/settings.json`, read live). On the page: a row and its tap
in `settings_page.py`. Follow `draw_fps`, its row (~218) and its tap (~415).

## An action in the model's JSON

`grep -n '"list_add"' brain.py` shows all a type touches: the prompt, the guards
that remove a wrong one (~1947–1999) and where it is carried out. Prefer a
"command" label above when the local command exists. Check with `tests/model_pi.py`
(~20 calls) or one line of `tools/sweep.py`.

## Which gate catches what

| Gate | Where, when | Catches |
|---|---|---|
| `tools/preflight.sh` | PC, before check and deploy | control characters from a heredoc, untracked files, syntax errors in what changed |
| `tests/run_unit.py` | PC, then on the Pi what the PC skipped (cv2, pygame); every check | logic (`tests/test_local_logic.py`, `tests/test_reply_stream.py`), every module compiles (`tests/test_syntax.py`), tools and docs (`tests/test_dev_tools.py`) |
| `tests/test_routing.py` | Pi, default and full | a sentence goes to the right handler; commands don't swallow questions |
| `tests/smoke_pi.py` | Pi, every check | the real modules run, no sound and no API; locks taken twice, freezes |
| `tests/dialog_pi.py` | Pi, default and full | what she says to everyday sentences, silent, scratch data |
| `tests/scenario_pi.py`, `tests/model_pi.py`, `tools/sweep.py` | Pi, by hand, costs money | the real model: prompt rules, family scenarios |

`tools/check_pi.sh`: `quick` = unit + smoke, no argument = + routing and dialog,
`full` = all four on the Pi (before a merge), `unit|routing|smoke|dialog` = one.
