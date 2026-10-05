"""
Smoke test ON THE PI, before every restart: the real modules (TTS, brain,
commands, faces…), no sound and no API calls.

The unit tests run on any machine and can't import the parts that need the
Pi (OpenAI SDK, OpenCV, PortAudio); on 4 Oct a lock taken twice in the
speaking code passed them all and froze Luna at her first word. This walks
those paths for real, each under a time limit.

    cd ~/luna && ./venv/bin/python tests/smoke_pi.py     (exit code 0 = fine)
"""

import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-smoke-")
if os.path.exists(os.path.join(HERE, "data", "people.json")):
    shutil.copy(os.path.join(HERE, "data", "people.json"), DATA)   # names + notes
os.environ["LUNA_DATA_DIR"] = DATA

failures = []


def check(name, fn, limit=5.0):
    """Run fn in a thread; it must finish in `limit` s without raising."""
    out = {}

    def run():
        try:
            out["v"] = fn()
        except BaseException as e:            # noqa: BLE001 — report everything
            out["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t0 = time.time()
    t.start()
    t.join(limit)
    if t.is_alive():
        failures.append(f"{name}: did not finish in {limit:.0f} s (deadlock?)")
        print(f"  FAIL {name}: hung", flush=True)
    elif "e" in out:
        failures.append(f"{name}: {type(out['e']).__name__}: {out['e']}")
        print(f"  FAIL {name}: {out['e']!r}", flush=True)
    else:
        print(f"  ok   {name} ({time.time() - t0:.2f} s)", flush=True)
    return out.get("v")


from shared_state import state                                # noqa: E402

print("[smoke] imports", flush=True)
mods = {}
for m in ("text_to_speech", "brain", "commands", "faces", "relationship", "mood",
          "radio", "news", "weather", "quiz", "kids", "counting", "calc", "screens",
          "messages", "timers", "lists", "memory", "idle_engine", "watchdog",
          "ambience", "errands", "birthdays", "backup", "riddles", "news", "kids",
          "cooking", "quizdata", "clockgame", "twenty", "tictac", "memo", "intent"):
    mods[m] = check(f"import {m}", lambda m=m: __import__(m), limit=60)

tts, brain, faces = mods["text_to_speech"], mods["brain"], mods["faces"]
known = faces.names() if faces else []
child = next((n for n in known if "dziecko" in faces.notes().get(n, "").lower()), None)

print("[smoke] speaking (silent)", flush=True)
for who in (None, known[0] if known else None, child):
    with state.lock:
        state.person = (who, 0.9, time.time()) if who else None
    check(f"start speaking, person={who}",
          lambda: tts._speaking(lambda style: None, lambda: "test", False))

print("[smoke] the prompt, built as for an answer", flush=True)


def prompt():
    with state.lock:                      # a helper that re-takes it must not hang
        return (brain._translator_rule() + brain._length_rule() + faces.prompt_line()
                + mods["relationship"].prompt_line() + mods["mood"].prompt_line()
                + mods["weather"].prompt_line() + mods["timers"].prompt_block()
                + mods["lists"].prompt_block() + mods["memory"].prompt_block())


text = check("prompt lines", prompt)
if text is not None and len(text) < 200:
    failures.append("prompt suspiciously short")

print("[smoke] sleep sounds (made, not played)", flush=True)
check("rain, sea and noise blocks",
      lambda: [mods["ambience"]._Gen(k).block() for k in ("rain", "sea", "noise")])

print("[smoke] local commands", flush=True)
with state.lock:
    state.person = None
said = []
speak = lambda t, **k: said.append(t)                        # noqa: E731
for utterance in (("Która godzina?", "Ile to jest 17 razy 23?", "Ile dni do Wigilii?",
                  "Jak się pisze żółw?", "Ile zostało do siedemnastej?",
                  "Obudź mnie o 6:30", "Przywróć listę zakupów", "Co o mnie wiesz?",
                  "Przypomnij mi za 20 minut o praniu", "Która godzina w Tokio?",
                  "Ile zostało na minutniku?", "Zagrajmy w memory", "Koniec",
                  "Pokaż plan dnia", "Usuń wiadomości")
                 + ((f"Gdzie jest {known[0]}?", f"Co wiesz o {known[0]}?") if known else ())):
    check(f"command {utterance!r}",
          lambda u=utterance: mods["commands"].handle(u, speak, lambda *a, **k: True))
if not any("391" in s for s in said):
    failures.append("calculator answer missing")
if child:                                   # homework: no ready answer for a child
    with state.lock:
        state.person = (child, 0.9, time.time())
    said.clear()
    mods["brain"].process = lambda *a, **k: None     # the model isn't called here
    check("calculator steps aside for a child",
          lambda: mods["commands"].handle("Ile to jest 17 razy 23?", speak, lambda *a, **k: True))
    if any("391" in s for s in said):
        failures.append(f"the calculator gave {child} the answer")

with state.lock:
    state.person = None
print(f"[smoke] {'OK' if not failures else 'FAILED'}", flush=True)
for f in failures:
    print("  -", f, flush=True)
shutil.rmtree(DATA, ignore_errors=True)
os._exit(1 if failures else 0)
