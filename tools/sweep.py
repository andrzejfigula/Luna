"""
sweep.py — one-line questions through main.py's order of checks (commands.handle,
then the model), with the REAL model, silent (a stand-in text_to_speech) and
scratch data. A quick way to see how she answers a batch of everyday things:

    cd ~/luna && ./venv/bin/python -X utf8 tools/sweep.py questions.txt
    ./venv/bin/python -X utf8 tools/sweep.py --at 20:45 questions.txt   # pretend time
    ./venv/bin/python -X utf8 tools/sweep.py --keep questions.txt       # one conversation

questions.txt: one "Who|What they say" per line ("Maja|Ile masz lat?"; "?|…" a face
she doesn't know, "|…" nobody in view).
Without --keep every line starts a fresh conversation. With --hello the
first-talk-of-the-day briefing is left on. It costs a few cents per batch.
(8 Oct: these sweeps found the costume, the age, the name days, "to wszystko".)
"""

import argparse
import datetime as _dt
import os
import shutil
import sys
import tempfile
import time

ap = argparse.ArgumentParser()
ap.add_argument("questions")
ap.add_argument("--at", help="pretend local time HH:MM (today)")
ap.add_argument("--keep", action="store_true", help="one conversation, history kept")
ap.add_argument("--hello", action="store_true", help="leave the morning briefing on")
args = ap.parse_args()

if args.at:                          # before Luna's modules read the clock
    hh, mm = (int(x) for x in args.at.split(":"))
    _real_time, _real_lt, _real_sf = time.time, time.localtime, time.strftime
    _now = _real_lt()
    _off = time.mktime((_now.tm_year, _now.tm_mon, _now.tm_mday, hh, mm, 0, 0, 0, -1)) \
        - _real_time()
    time.time = lambda: _real_time() + _off
    time.localtime = lambda s=None: _real_lt(time.time() if s is None else s)
    time.strftime = lambda f, t=None: _real_sf(f, time.localtime() if t is None else t)

    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime.fromtimestamp(time.time(), tz)

    _dt.datetime = _FakeDT

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-sweep-")
for f in ("people.json", "settings.json"):
    if os.path.exists(os.path.join(HERE, "data", f)):
        shutil.copy(os.path.join(HERE, "data", f), DATA)
os.environ["LUNA_DATA_DIR"] = DATA

_fake = type(sys)("text_to_speech")
for _n in ("speak", "speak_stream", "play_clip", "play_sound", "play_sound_async",
           "replay_last", "stop_speaking"):
    setattr(_fake, _n, lambda *a, **k: None)
sys.modules["text_to_speech"] = _fake

import ambience            # noqa: E402
import brain               # noqa: E402
import commands            # noqa: E402
import idle_engine         # noqa: E402
import radio               # noqa: E402
import screens             # noqa: E402
import weather             # noqa: E402
from shared_state import state   # noqa: E402

radio.play = lambda *a, **k: None
ambience.play = lambda *a, **k: True
screens._take_photo = lambda *a: None
commands.set_volume = lambda v: v
commands.get_volume = lambda: 0.5
weather.start_weather()
for _ in range(30):
    if weather._summary:
        break
    time.sleep(0.5)
if not args.hello:
    idle_engine.first_hello_due = lambda who: False

said = []
# answers that go through brain.process (another town's weather, the news, a
# story) are heard too, not just "(recorded)"
brain.process = lambda t, context=None, **k: said.append(
    (brain._ask_openai(t, context=context) or [""])[0])

lines = [ln.split("|", 1) for ln in open(args.questions, encoding="utf-8").read().splitlines()
         if "|" in ln]
for who, text in lines:
    if not args.keep:
        brain._history.clear()
    with state.lock:                 # "?|…" — a face she doesn't know; "|…" — nobody
        state.person = (who, 0.8, time.time()) if who and who != "?" else None
        state.face_detected = bool(who)
        state.last_face_time = time.time()
        state.last_wake_time = time.time()
    said.clear()
    h = commands.handle(text, lambda t, **k: said.append(t), lambda *a, **k: True)
    if isinstance(h, tuple) and h[0] == "ask":
        r = brain._ask_openai(h[1])
        said.append(r[0] if r else "")
    elif not h:
        r = brain._ask_openai(text)
        said.append(r[0] if r else "")
    elif h != "recorded":
        brain.note_local(text, said)
    print(f"{who}: {text}\n   → {' | '.join(said) or '(' + str(h) + ')'}", flush=True)

shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(0)
