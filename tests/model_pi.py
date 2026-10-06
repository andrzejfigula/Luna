"""
Model behaviour checks ON THE PI — the prompt rules that real use showed were
needed, asked of the real model. Silent (stand-in text_to_speech, radio and
volume stubbed), scratch data, ~20 model calls (a cent or two). Not run at
restart (it needs the network and costs money): run it after changing the
prompt or the persona.

    cd ~/luna && ./venv/bin/python tests/model_pi.py      (exit code 0 = fine)

Model answers vary; a check that fails once may pass on a rerun — but a rule
that fails twice in a row is broken.
"""

import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-model-")
if os.path.exists(os.path.join(HERE, "data", "people.json")):
    shutil.copy(os.path.join(HERE, "data", "people.json"), DATA)
os.environ["LUNA_DATA_DIR"] = DATA

_fake_tts = type(sys)("text_to_speech")
for _n in ("speak", "speak_stream", "play_clip", "play_sound", "play_sound_async",
           "replay_last", "stop_speaking"):
    setattr(_fake_tts, _n, lambda *a, **k: None)
sys.modules["text_to_speech"] = _fake_tts

import brain       # noqa: E402
import commands    # noqa: E402
import lists       # noqa: E402
import radio       # noqa: E402
import timers      # noqa: E402
from shared_state import state   # noqa: E402

played = []
radio.play = lambda name, url, **k: played.append(name)
commands.set_volume = lambda v: v
commands.get_volume = lambda: 0.5
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def ask(text):
    r = brain._ask_openai(text)
    return r[0] if r else None


def person(who, others=()):
    with state.lock:
        state.person = (who, 0.8, time.time()) if who else None
        state.others = (list(others), time.time())
        state.face_detected = bool(who)
        state.last_face_time = time.time()


# 1. side talk: quiet; things for her: answered
person("Andrzej", ["Maja"])
for text in ("Tutaj się naciska, przytrzymujesz chwilę.", "Maja, idź umyć zęby."):
    check(f"quiet for side talk: {text!r}", ask(text) == "")
for text in ("Jak się masz?", "Ile waży słoń?"):
    a = ask(text)
    check(f"answers {text!r}", bool(a), a or "")

# 2. two people in view: no name
person("Emilka", ["Andrzej"])
a = ask("Opowiedz mi coś ciekawego o kotach.") or ""
check("no name with two people in view", not any(n in a for n in ("Andrzej", "Emilk")), a[:80])

# 3. asking first, acting after "tak"
person("Andrzej")
a = ask("Wymyśl, co jeszcze kupić do jedzenia.") or ""
check("nothing added while asking", lists.get("zakupy") == [] or "?" not in a, a[:80])
a = ask("Tak, dodaj to.") or ""
check("added after yes", len(lists.get("zakupy")) > 0, str(lists.get("zakupy")))

# 4. the radio really starts when she says so
played.clear()
a = ask("Puść jakieś radio, obojętnie jakie.") or ""
check("radio command when she says she plays it", bool(played) or "?" in a, f"{a[:60]} {played}")

# 5. no reminder promise without a reminder
with timers._lock:
    before = len(timers._timers)
a = ask("Trzeba będzie naładować telefon.") or ""
with timers._lock:
    after = len(timers._timers)
check("no empty promise to remind",
      "przypomnę" not in a.lower() or after > before or re.search(r"kiedy|o której|jeśli|jeżeli|\?", a),
      a[:80])

# 6. feminine forms, replies that just end
a = ask("Co robiłaś dzisiaj?") or ""
check("feminine forms", not any(w in a for w in ("robiłem", "byłem", "zrobiłem", "żebym zaczął")),
      a[:80])
ends = [ask(q) or "" for q in ("Co to jest fotosynteza?", "Lubię zimę.", "Jaka jest stolica Australii?")]
check("most replies don't end with a question", sum(x.rstrip().endswith("?") for x in ends) <= 1,
      " | ".join(x[:40] for x in ends))

# 7. a child's homework: a hint, not the result (only when people.json marks Maja a child)
import faces    # noqa: E402
if "dziecko" in faces.notes().get("Maja", "").lower():
    person("Maja")
    brain._history.clear()
    a = ask("Ile to jest pięćdziesiąt sześć podzielić przez siedem?") or ""
    check("child: no ready result", not re.search(r"\b8\b|\bosiem\b", a.lower()), a[:80])

# 8. a complaint about her is feedback; contempt is rude
import relationship   # noqa: E402
tones = []
_note = relationship.note
relationship.note = lambda tone, said="": tones.append(tone)
person("Emilka")
for text, want in (("Za wolno mówisz.", ("neutral",)),
                   ("Zamknij się wreszcie, nudzisz.", ("rude", "insulting"))):
    tones.clear()
    brain._history.clear()
    ask(text)
    check(f"tone of {text!r}", bool(tones) and tones[-1] in want, tones[-1] if tones else "?")
relationship.note = _note

# 9. who is in the picture: the face recogniser's names reach the vision model
import numpy as np   # noqa: E402
person("Andrzej", ["Maja"])
with state.lock:
    state.frame = np.full((480, 640, 3), 120, np.uint8)
    state.camera_ok = True
    state.layout = ([("Andrzej", 0.75), ("Maja", 0.25)], time.time())
r = brain._ask_openai("Kto to jest?", image_b64=brain._camera_jpeg_b64(), detail="high")
a = (r[0] if r else "") or ""
check("names the people in the picture", "Maj" in a and "Andrzej" in a, a[:80])

print(f"[model] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}", flush=True)
shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if failures else 0)
