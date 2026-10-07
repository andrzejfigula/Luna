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
commands.set_volume = lambda v: v          # the real speaker's volume stays as it is
commands.get_volume = lambda: 0.5
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
    ("Kiedy jest Wielkanoc?", "Wielkanoc wypada"),
    ("Ile dni minęło od 1 września?", "Od 1 września"),
    ("Ile to cali 30 centymetrów?", "11,81 cala"),
    ("Ile dni do tłustego czwartku?", "tłustego czwartku"),
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
    ("Co mam na liście zakupów?", "Na liście zakupów"),
    ("Pokaż plan dnia", "plan"),
    ("Jaka będzie jutro pogoda?", "W jakim mieście"),   # no town set in scratch data
    ("Zmień mój głos jak robot", "głos: robot"),
    ("Czy mogę ci poczytać?", "Słucham"),               # reading.py (disarmed below)
    ("Poczytaj ze mną", "Słucham"),
    ("Zgadnij, o czym myślę", "ja będę zgadywać"),       # twenty.py, the child thinks
    ("Koniec", "kończymy"),
    # 7 Oct evening probes — each of these had gone to the model
    ("Możesz przyciemnić ekran?", "przyciemniam"),        # display.py override
    ("Rozjaśnij ekran", "rozjaśniam"),
    ("Jakie mam przypomnienia?", "przypomnie"),          # timers.reminders_answer
    ("Kiedy przyjdzie Emilka, powiedz jej, że dzwoniła babcia", "Emilka"),   # errands
    ("Przetłumacz na niemiecki: dzień dobry", MODEL),    # one sentence, not the mode
    ("Zmień stację na RMF", "RMF FM"),                  # that station, not the next
    ("Włącz odgłosy lasu", "Takiego dźwięku nie mam"),  # ambience: what she has
    ("Tryb skupienia na 25 minut", "25 minut skupienia"),
    ("Koniec skupienia", "koniec skupienia"),
    ("Na razie nie", MODEL),                             # not "przyciemnij ekran"
    ("Napisz na ekranie Shure MV7", "na ekranie"),        # commands.show_text
    ("Zrób mi zdjęcie", ""),
    ("Włącz lampkę", ""),
    ("Lampka na niebiesko", ""),
    ("Wyłącz lampkę", ""),
    ("Ciszej", ""),
    ("Mów wolniej", ""),
    ("Mów normalnie", ""),
    ("Za wolno mówisz", ""),
    ("Mów normalnie", ""),
    ("Za cicho", ""),
    ("Jest cicho w domu, wszyscy śpią", MODEL),
    ("Możesz mówić wolniej?", ""),
    ("Mów normalnie", ""),
    ("Włącz radio z jakąś spokojną muzyką", "Dwójkę"),
    ("Wyłącz radio", ""),
    ("Włącz napisy", "napisy"),
    ("Wyłącz napisy", "napisy"),
    ("Włącz tryb skupienia", "skupi"),
    ("Koniec skupienia", ""),
    ("Tłumacz na angielski", "angielski"),
    ("Koniec tłumaczenia", "Koniec tłumaczenia"),
    ("Rzuć kostką", "Wypadła"),
    ("Orzeł czy reszka?", ""),
    ("Zapamiętaj słowa do dyktanda: rzeka, góra i żaba", "3 słowa do dyktanda"),
    ("Wyczyść słowa do dyktanda", "moje słowa"),
    ("Powtórz", ""),
    ("Opowiedz dalszy ciąg bajki", "Nie pamiętam żadnej bajki"),
    ("Pokaż zegar", ""),
    ("Pokaż listę zakupów", ""),
    ("Pokaż status", ""),
    ("Zapamiętaj, że klucze są w szufladzie", ""),
    ("Gdzie są klucze?", "Zapisałam: Klucze są w szufladzie"),
    ("Zapomnij, że klucze są w szufladzie", "zapomniałam"),
    ("Maja ma imieniny 3 maja", "Zapamiętałam"),
    ("Kiedy Maja ma imieniny?", "3 maja"),
    # ordinary talk: the model, never a command
    ("Jutro mamy dyktando w szkole", MODEL),
    ("Szum morza mnie uspokaja", MODEL),
    ("Babcia zawsze opowiadała mi bajki na dobranoc", MODEL),
    ("Gotujemy obiad, bo zaraz przyjdą goście", MODEL),
    ("Kto jest lepszy, Messi czy Ronaldo?", MODEL),
    ("Gdzie jest pilot?", MODEL),
    ("Co mówiłaś o planetach?", MODEL),
    ("Czy możesz mi wytłumaczyć fotosyntezę?", MODEL),
    ("Moja koleżanka gra w kółko i krzyżyk na lekcjach", MODEL),
    # the internet is down: what still works
    ("<offline>", None),
    ("Dopisz mleko i chleb do listy zakupów", "Dopisałam: mleko, chleb"),
    ("Co mam na liście zakupów?", "mleko, chleb"),
    ("Nastaw minutnik na 3 minuty", "minutnik na 3 minuty"),
    ("Przypomnij mi o 23:59, żeby zamknąć okno", "przypomnę o"),
    ("Przypomnij mi jutro o 8 o dentyście", "jutro o ósmej"),
    ("Która godzina?", "Jest "),
    ("Jak się masz?", MODEL),                 # brain then says its recorded apology
    ("<online>", None),
    ("Pa!", ""),                             # last: she goes to sleep
]

failures = []
said = []
with state.lock:
    state.person = None
for text, want in CASES:
    if text in ("<offline>", "<online>"):
        with state.lock:
            state.online = text == "<online>"
        continue
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
    import reading
    if reading.armed():                     # the test goes on with other sentences
        reading.take()
    time.sleep(0.05)

print(f"[dialog] {'OK' if not failures else 'FAILED: ' + ', '.join(failures)}", flush=True)
shutil.rmtree(DATA, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if failures else 0)
