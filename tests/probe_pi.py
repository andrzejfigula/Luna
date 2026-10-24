"""
Probe ON THE PI: sentences (one per line, from a file or stdin) through the
real commands.handle, silent and on scratch data like dialog_pi.py; prints
where each went — her local reply, or "(model)". No checks: for reading.
Some local handlers still call the cloud (news summary, drawing): leave those out.

    cd ~/luna && ./venv/bin/python tests/probe_pi.py phrases.txt
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-probe-")
for f in ("people.json", "lists.json"):
    if os.path.exists(os.path.join(HERE, "data", f)):
        shutil.copy(os.path.join(HERE, "data", f), DATA)    # a copy: never written back
os.environ["LUNA_DATA_DIR"] = DATA

_fake_tts = type(sys)("text_to_speech")
for _name in ("speak", "speak_stream", "play_clip", "play_sound", "play_sound_async",
              "replay_last", "stop_speaking"):
    setattr(_fake_tts, _name, lambda *a, **k: None)
sys.modules["text_to_speech"] = _fake_tts

import ambience            # noqa: E402
import commands            # noqa: E402
import memory              # noqa: E402
import radio               # noqa: E402
import screens             # noqa: E402

radio.play = lambda *a, **k: None
commands.set_volume = lambda v: v
commands.get_volume = lambda: 0.5
ambience.play = lambda *a, **k: True
screens._take_photo = lambda *a: None

src = open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else sys.stdin
said = []
for text in (l.strip() for l in src):
    if not text or text.startswith("#"):
        continue
    said.clear()
    reply = memory.check_forget(text)
    if reply:
        said.append(reply)
        handled = True
    else:
        handled = commands.handle(text, lambda t, **k: said.append(t), lambda *a, **k: True)
    print(f"{text!r} → {' | '.join(said) if handled else '(model)'}", flush=True)
    import reading
    if reading.armed():
        reading.take()
    time.sleep(0.05)

shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(0)
