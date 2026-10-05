"""
Dialog test ON THE PI: everyday sentences through the real commands.handle,
checked for what she says — silent (speech is captured), no model calls (a
sentence for the model is marked "(model)"), scratch data, the radio, sleep
sounds and the camera stubbed. Run by restart.sh after the smoke test.

Each case: (sentence, expected) where expected is a piece of her reply, or
MODEL when the sentence must go to the model. Unit tests call functions one
by one; this caught what they couldn't — a question guard that sent
"ile zostało na minutniku?" to the model before its handler was reached.

    cd ~/luna && ./venv/bin/python tests/dialog_pi.py      (exit code 0 = fine)
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
DATA = tempfile.mkdtemp(prefix="luna-dialog-")
if os.path.exists(os.path.join(HERE, "data", "people.json")):
    shutil.copy(os.path.join(HERE, "data", "people.json"), DATA)
os.environ["LUNA_DATA_DIR"] = DATA

# silent BY CONSTRUCTION: some handlers play audio themselves (counting plays
# its number clips through text_to_speech.play_clip, the games speak from a
# thread) — on 5 Oct an ad-hoc run counted to ten out loud on the live
# speaker. A stand-in text_to_speech makes every such path a no-op.
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
from shared_state import state   # noqa: E402

radio.play = lambda *a, **k: None
ambience.play = lambda *a, **k: True
screens._take_photo = lambda *a: None

MODEL = object()
CASES = [
    ("Przypomnij mi za 20 minut o praniu", "przypomnę za 20 minut"),
    ("Minutnik na 8 minut do jajek", "8 minut — do jajek"),
    ("Ile zostało na minutniku?", "Minutniki"),
    ("Obudź mnie o 6:30 w dni robocze", "budzik w dni robocze"),
    ("Która godzina w Nowym Jorku?", "W Nowym Jorku jest teraz"),
    ("Jaki dzień tygodnia będzie 24 grudnia?", "24 grudnia wypada w"),
    ("Ile dni do Wigilii?", "Wigilii"),
    ("Która godzina?", "Jest "),
    ("Ile to jest 17 razy 23?", "391"),
    ("Jak się pisze żółw?", "żółw"),
    ("Wylosuj liczbę od 1 do 6", "Losuję"),
    ("Kto dziś zmywa: Maja, tata czy mama?", "Losuję"),
    ("Wybierz: pizza czy makaron?", "Wybieram"),
    ("Co o mnie wiesz?", ""),
    ("Ile mam gwiazdek?", "gwiazd"),
    ("Jakie to radio?", "Radio nie gra"),
    ("Czy możesz nastawić minutnik na 10 minut?", "minutnik na 10 minut"),
    ("Możesz mi przypomnieć za 15 minut o herbacie?", "przypomnę za 15 minut"),
    ("Włączysz szum deszczu?", "szum deszczu"),
    ("No to nastaw minutnik na 5 minut", "minutnik na 5 minut"),
    ("Zagrajmy w memory", "memory"),
    ("Koniec", "koniec gry"),
    ("Zagrajmy we dwoje w kółko i krzyżyk", "we dwoje"),
    ("Koniec", "koniec gry"),
    ("Zapomnij wszystko", "Na pewno"),
    ("Nie", "niczego nie zapominam"),
    ("Usuń wiadomości", "wiadomości"),
    ("Przywróć listę zakupów", "Nie mam czego przywrócić"),
    ("Pokaż plan dnia", "plan"),
    ("Zmień mój głos jak robot", "głos: robot"),
    ("Zrób mi zdjęcie", ""),
    # ordinary talk: the model, never a command
    ("Jutro mamy dyktando w szkole", MODEL),
    ("Szum morza mnie uspokaja", MODEL),
    ("Babcia zawsze opowiadała mi bajki na dobranoc", MODEL),
    ("Gotujemy obiad, bo zaraz przyjdą goście", MODEL),
    ("Kto jest lepszy, Messi czy Ronaldo?", MODEL),
    ("Gdzie jest pilot?", MODEL),
    ("Czy możesz mi wytłumaczyć fotosyntezę?", MODEL),
    ("Moja koleżanka gra w kółko i krzyżyk na lekcjach", MODEL),
]

failures = []
said = []
with state.lock:
    state.person = None
for text, want in CASES:
    said.clear()
    reply = memory.check_forget(text)
    if reply:
        said.append(reply)
        handled = True
    else:
        handled = commands.handle(text, lambda t, **k: said.append(t), lambda *a, **k: True)
    out = " | ".join(said)
    if want is MODEL:
        ok = not handled
    else:
        ok = bool(handled) and want.lower() in out.lower()
    print(f"  {'ok  ' if ok else 'FAIL'} {text!r} → {out if handled else '(model)'}", flush=True)
    if not ok:
        failures.append(text)
    time.sleep(0.05)

print(f"[dialog] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}", flush=True)
shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if failures else 0)
