"""
sweep.py — one-line questions through main.py's order of checks (commands.handle,
then the model), with the REAL model, silent (a stand-in text_to_speech) and
scratch data. A quick way to see how she answers a batch of everyday things:

    cd ~/luna && ./venv/bin/python -X utf8 tools/sweep.py questions.txt
    ./venv/bin/python -X utf8 tools/sweep.py --at 20:45 questions.txt   # pretend time
    ./venv/bin/python -X utf8 tools/sweep.py --at 08:00 --day 2026-10-10 q.txt   # a Saturday
    ./venv/bin/python -X utf8 tools/sweep.py --keep questions.txt       # one conversation

questions.txt: one "Who|What they say" per line ("Maja|Ile masz lat?"; "?|…" a face
she doesn't know, "|…" nobody in view, "Andrzej+Maja|…" Maja in view beside him; "Maja|~…" overheard, said without "Luna").
Without --keep every line starts a fresh conversation. With --hello the
first-talk-of-the-day briefing is left on. It costs a few cents per batch —
and stops at --max-calls API calls (default 80): on 7–13 Oct whole batteries
of sweeps were ~90% of the bill and once emptied the account.
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
ap.add_argument("--day", help="pretend date YYYY-MM-DD (with --at; default today)")
ap.add_argument("--keep", action="store_true", help="one conversation, history kept")
ap.add_argument("--hello", action="store_true", help="leave the morning briefing on")
ap.add_argument("--max-calls", type=int, default=80, help="stop after this many API calls")
args = ap.parse_args()

if args.at:                          # before Luna's modules read the clock
    hh, mm = (int(x) for x in args.at.split(":"))
    _real_time, _real_lt, _real_sf = time.time, time.localtime, time.strftime
    _now = _real_lt()
    y, mo, d = ((int(x) for x in args.day.split("-")) if args.day
                else (_now.tm_year, _now.tm_mon, _now.tm_mday))
    _off = time.mktime((y, mo, d, hh, mm, 0, 0, 0, -1)) - _real_time()
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
import drawing             # noqa: E402
import health              # noqa: E402
import idle_engine         # noqa: E402
import radio               # noqa: E402
import screens             # noqa: E402
import weather             # noqa: E402
from shared_state import state   # noqa: E402

radio.play = lambda *a, **k: None
os.kill = lambda *a, **k: print("[sweep] \"zrestartuj się\" — not really", flush=True)
ambience.play = lambda *a, **k: True
screens._take_photo = lambda *a: None
drawing._camera_jpeg = lambda: b"jpeg"      # no picture is made (it costs) — only said
drawing.draw = lambda what, speak, intro="Dobrze, już rysuję. Chwileczkę!", english=False, photo=None: (
    speak(intro), print(f"[sweep] draw {what!r}{' from the camera' if photo else ''}",
                        flush=True))[0] or True
commands.set_volume = lambda v: v
commands.get_volume = lambda: 0.5
weather.start_weather()
for _ in range(30):
    if weather._summary:
        break
    time.sleep(0.5)
if not args.hello:
    idle_engine.first_hello_due = lambda who: False

health._count_api_calls()            # every OpenAI call, counted (the cap below)


def _calls():
    with health._lock:
        return sum(health._day.values())


said = []
# answers that go through brain.process (another town's weather, the news, a
# story) are heard too, not just "(recorded)"
# (under brain._process_lock, as in main.py: a photo's or a search's thread
# answering while the next line is asked tangled the history — 13 Oct sweeps
# printed a reply "{" twice, never seen live)
def _process(t, context=None, **k):
    with brain._process_lock:
        said.append((brain._ask_openai(t, context=context) or [""])[0])


brain.process = _process


def _ask(t):
    with brain._process_lock:
        return brain._ask_openai(t)

_raw = open(args.questions, encoding="utf-8").read().splitlines()
lines = [ln.split("|", 1) for ln in _raw if "|" in ln]
# a "#keep" line: one conversation (follow-ups like "Osiem?" or "Cofnij" mean
# nothing without the turn before — 11 Oct, judged wrong in a fresh history)
args.keep = args.keep or "#keep" in (ln.strip() for ln in _raw)
for who, text in lines:
    if _calls() >= args.max_calls:
        print(f"[sweep] STOPPED: {_calls()} API calls (--max-calls {args.max_calls})", flush=True)
        break
    if not args.keep:
        brain._history.clear()
    who, *beside = who.split("+")    # "Andrzej+Maja|…" — Maja in view too
    with state.lock:                 # "?|…" — a face she doesn't know; "|…" — nobody
        state.others = (beside, time.time() if beside else 0.0)
        state.person = (who, 0.8, time.time()) if who and who != "?" else None
        state.face_detected = bool(who)
        state.last_face_time = time.time()
        # "Maja|~…" — overheard, no "Luna" (and she hasn't just spoken)
        state.last_wake_time = 0.0 if text.startswith("~") else time.time()
        if text.startswith("~"):
            state.last_spoken_time = 0.0
    text = text.lstrip("~")
    said.clear()
    if idle_engine.check_mute(text):           # main.py asks this first
        print(f"{who}: {text}\n   → (muted, silently)", flush=True)
        continue
    h = commands.handle(text, lambda t, **k: said.append(t), lambda *a, **k: True)
    if isinstance(h, tuple) and h[0] == "ask":
        r = _ask(h[1])
        said.append(r[0] if r else "")
    elif not h:
        r = _ask(text)
        said.append(r[0] if r else "")
    elif h != "recorded":
        brain.note_local(text, said)
    print(f"{who}: {text}\n   → {' | '.join(said) or '(' + str(h) + ')'}", flush=True)

print(f"[sweep] {_calls()} API calls", flush=True)
shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(0)
