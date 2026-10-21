"""The parts of Luna that are pure logic — no Pi, no network, no audio."""

import datetime
import json
import os
import sys
import shutil
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LUNA_DATA_DIR"] = tempfile.mkdtemp(prefix="luna-tests-")  # never real data

import games
import lists
import memory
import settings
import timers
from shared_state import state

TMP = tempfile.mkdtemp(prefix="luna-tests-")
timers.TIMERS_PATH = os.path.join(TMP, "timers.json")
memory.MEMORY_PATH = os.path.join(TMP, "memory.json")
settings.SETTINGS_PATH = os.path.join(TMP, "settings.json")
lists.LISTS_PATH = os.path.join(TMP, "lists.json")


class TimersTest(unittest.TestCase):

    def setUp(self):
        timers._timers.clear()

    def test_move_reminder(self):
        # 9 Oct sweep: the model moved Friday's reminder to the next Friday
        now = datetime.datetime(2026, 10, 9, 18, 0).timestamp()
        due = datetime.datetime(2026, 10, 9, 19, 0).timestamp()
        timers._timers.append({"kind": "reminder", "due": due, "repeat": "none",
                               "label": "urodziny babci w sobotę o 15:00"})
        timers._timers.append({"kind": "reminder", "repeat": "none", "label": "rachunek za prąd",
                               "due": datetime.datetime(2026, 10, 12, 8, 0).timestamp()})
        with mock.patch.object(timers, "_save", lambda: None):
            said = timers.local_move("Przesuń przypomnienie o urodzinach babci na ósmą", now)
            self.assertEqual(said, "Dobrze, przypomnę dziś o dwudziestej: urodziny babci "
                                   "w sobotę o 15:00.")
            self.assertEqual(datetime.datetime.fromtimestamp(timers._timers[0]["due"]).hour, 20)
            said = timers.local_move("Przesuń przypomnienie o rachunku na jutro na dziewiątą", now)
            self.assertIn("jutro o dziewiątej", said)
            self.assertIsNone(timers.local_move("Przesuń urodziny babci na szesnastą", now))  # the event
            self.assertIsNone(timers.local_move("Przesuń przypomnienie na ósmą", now))  # which one?
            self.assertIsNone(timers.local_move("Przesuń budzik na ósmą", now))

    def test_sleep_answer(self):
        # 9 Oct probe: the model said 10 and 13 h of sleep for 14
        now = datetime.datetime(2026, 10, 9, 17, 0).timestamp()
        due = datetime.datetime(2026, 10, 10, 7, 0).timestamp()
        timers._timers.append({"kind": "alarm", "due": due, "label": "", "repeat": "none"})
        self.assertEqual(timers.sleep_answer("Ile godzin snu mi zostało, jeśli pójdę spać teraz?", now),
                         "Budzik masz o siódmej — kładąc się teraz, wyśpisz się najwyżej 14 godzin.")
        said = timers.sleep_answer("Jak pójdę spać o pierwszej, to ile się wyśpię?", now)
        self.assertIn("kładąc się o pierwszej, wyśpisz się najwyżej 6 godzin.", said)
        said = timers.sleep_answer("Ile się wyśpię, jak położę się o wpół do dwunastej?", now)
        self.assertIn("najwyżej 7 godzin i 30 minut", said)
        late = datetime.datetime(2026, 10, 10, 5, 50).timestamp()
        self.assertIn("najwyżej godzinę i 10 minut", timers.sleep_answer("Ile jeszcze pośpię?", late))
        self.assertIsNone(timers.sleep_answer("Ile spałaś?", now - 10 ** 6))   # no alarm in 24 h
        self.assertIsNone(timers.sleep_answer("Ile zostało na minutniku?", now))
        self.assertIsNone(timers.sleep_answer("Ile godzin dziennie powinno spać dziecko?", now))

    def test_timer_reminder_and_cancel_by_label(self):
        timers.apply([{"type": "timer", "seconds": 60, "at": "", "label": "makaron"}])
        later = (datetime.datetime.now() + datetime.timedelta(minutes=30)).strftime("%H:%M")
        # (a fixed "23:59" failed when the check ran at 23:59:47)
        timers.apply([{"type": "reminder", "seconds": 0, "at": later, "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron", "piekarnik"])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron"])

    def test_the_same_alarm_is_not_set_twice(self):
        # 11 Oct sweep: "O której mam budzik?" — answered, and a second 07:30 set
        timers.apply([{"type": "alarm", "seconds": 0, "at": "07:30", "label": ""}])
        timers.apply([{"type": "alarm", "seconds": 0, "at": "07:30", "label": "przypomnienie"}])
        later = (datetime.datetime.now() + datetime.timedelta(minutes=30)).strftime("%H:%M")
        timers.apply([{"type": "reminder", "seconds": 0, "at": later, "label": "piekarnik"}])
        timers.apply([{"type": "reminder", "seconds": 0, "at": later, "label": "pranie"}])
        self.assertEqual(sorted(t["label"] for t in timers._timers), ["", "piekarnik", "pranie"])

    def test_cancel_without_label_takes_the_kitchen_timers_only(self):
        for s in (60, 120):
            timers.apply([{"type": "timer", "seconds": s, "at": "", "label": ""}])
        timers.apply([{"type": "alarm", "seconds": 0, "at": "06:30", "label": "",
                       "repeat": "weekdays"}])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": ""}])
        self.assertEqual([t["kind"] for t in timers._timers], ["alarm"])

    def test_cancel_never_takes_more_than_asked(self):
        timers.apply([{"type": "reminder", "seconds": 0, "at": "23:58", "label": "wyłączyć piekarnik"}])
        timers.apply([{"type": "alarm", "seconds": 0, "at": "06:30", "label": "", "repeat": "daily"}])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "zadzwonić do mamy"}])
        self.assertEqual(len(timers._timers), 2)                  # no match: nothing gone
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "piekarnika"}])
        self.assertEqual([t["kind"] for t in timers._timers], ["alarm"])   # stem match
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "budzik"}])
        self.assertEqual(timers._timers, [])

    def test_nonsense_is_ignored(self):
        timers.apply([{"type": "timer", "seconds": 0, "at": "", "label": ""},
                      {"type": "timer", "seconds": 10 ** 9, "at": "", "label": ""},
                      {"type": "reminder", "seconds": 0, "at": "kiedyś", "label": ""}])
        self.assertEqual(timers._timers, [])

    def test_past_clock_time_means_tomorrow(self):
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%H:%M")
        due = timers._parse_at(past)
        self.assertGreater(due, time.time() + 22 * 3600)

    def test_countdown_text(self):
        timers.apply([{"type": "timer", "seconds": 125, "at": "", "label": ""}])
        self.assertIn(timers.countdown_text(), ("2:05", "2:04"))

    def test_repeating_reminders(self):
        # Friday 2026-10-09 07:00 local → next weekday is Monday the 12th
        fri = datetime.datetime(2026, 10, 9, 7, 0).timestamp()
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(fri, "weekdays"))
        self.assertEqual((nxt.weekday(), nxt.hour, nxt.minute), (0, 7, 0))
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(fri, "daily"))
        self.assertEqual((nxt.day, nxt.hour), (10, 7))
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(fri, "weekends"))
        self.assertEqual(nxt.weekday(), 5)
        # set on a Saturday for weekdays → first ring Monday
        sat = datetime.datetime(2026, 10, 10, 6, 30).timestamp()
        first = datetime.datetime.fromtimestamp(timers._next_matching(sat, "weekdays", inclusive=True))
        self.assertEqual(first.weekday(), 0)

    def test_a_series_reschedules_itself_when_it_rings(self):
        timers._timers.clear()
        now = time.time()
        timers._timers.append({"due": now - 1, "label": "tabletki", "kind": "reminder",
                               "repeat": "daily", "set": now})
        timers._timers.append({"due": now - 1, "label": "raz", "kind": "reminder",
                               "repeat": "none", "set": now})
        due = timers._take_due(now)
        self.assertEqual(sorted(t["label"] for t in due), ["raz", "tabletki"])
        self.assertEqual([t["label"] for t in timers._timers], ["tabletki"])
        self.assertGreater(timers._timers[0]["due"], now + 23 * 3600)

    def test_local_timer_phrases(self):
        cases = {
            "Minutnik na 10 minut": 600,
            "Nastaw minutnik na pięć minut": 300,
            "Luna, ustaw timer na dwadzieścia pięć sekund": 25,
            "minutnik na pół godziny": 1800,
            "Nastaw minutnik na półtorej godziny": 5400,
            "minutnik na kwadrans": 900,
            "minutnik na godzinę": 3600,
            "Ustaw minutnik na 2 minuty i 30 sekund": 150,
        }
        for text, secs in cases.items():
            self.assertEqual(timers.local_timer(text), secs, text)
        for text in ("Nastaw minutnik na 10 minut na makaron",   # a label: the model
                     "Ile zostało na minutniku?",
                     "Przypomnij mi za 10 minut o praniu"):
            self.assertIsNone(timers.local_timer(text), text)

    def test_calc_two_numbers_in_a_row(self):
        import calc
        self.assertIsNone(calc.arithmetic("6:30 3"))          # found by the fuzz test
        self.assertIsNone(calc.arithmetic("3 6:30 !"))

    def test_voicefx(self):
        import voicefx
        import numpy as np
        self.assertEqual(voicefx.wants("Luna, zmień mój głos"), "?")
        self.assertEqual(voicefx.wants("Zmień mój głos jak wiewiórka"), "wiewiórka")
        self.assertEqual(voicefx.wants("Odwróć mój głos"), "od tyłu")
        self.assertEqual(voicefx.wants("Zrób mi głos jak robot"), "robot")
        self.assertIsNone(voicefx.wants("Mam dziś zachrypnięty głos"))
        self.assertIsNone(voicefx.wants("Zmień głos na męski"))         # hers, not mine
        self.assertEqual(voicefx.wants("Pobawmy się głosem"), "?")
        self.assertIsNone(voicefx.wants("Zrób mi herbatę"))
        self.assertIsNone(voicefx.wants("Zrób mi zdjęcie"))
        tone = (np.sin(np.arange(16000) / 16000 * 2 * np.pi * 220) * 8000).astype(np.int16)
        pcm = tone.tobytes()
        self.assertEqual(len(voicefx.apply(pcm, "od tyłu")), 24000 * 2)        # 1 s at 24 kHz
        self.assertEqual(len(voicefx.apply(pcm, "wiewiórka")), int(24000 / 1.6) * 2)
        self.assertEqual(len(voicefx.apply(pcm, "olbrzym")), int(24000 / 0.7) * 2)
        self.assertEqual(voicefx.apply(b"\0\0" * 100, "robot"), b"")       # too short
        self.assertIn(voicefx.arm("?"), voicefx.EFFECTS)
        self.assertTrue(voicefx.armed())

    def test_mute_only_when_bare(self):
        import idle_engine
        for t in ("Luna, cicho!", "bądź cicho", "Zamilcz", "Możesz mówić"):
            self.assertTrue(idle_engine.check_mute(t), t)
        for t in ("Za cicho", "Jest cicho w domu", "Możesz mówić wolniej?",
                  "Możesz mówić głośniej"):
            self.assertFalse(idle_engine.check_mute(t), t)

    def test_radio_from_abroad(self):
        import radio
        # 11 Oct: "more radio stations including abroad, not only a few Polish"
        self.assertEqual(radio._world_wanted("z francji"), ("FR", None, "z Francji"))
        self.assertEqual(radio._world_wanted("francuski jazz")[:2], ("FR", "jazz"))
        self.assertEqual(radio._world_wanted("reggae")[:2], (None, "reggae"))
        self.assertIsNone(radio._world_wanted("do śniadania"))          # not Denmark
        # jazz: real jazz stations (11 Oct: three tries, then Nowy Świat) — since
        # 15 Oct the catalogue's own (RadioCatalogTest), not a search abroad
        self.assertIsNone(radio._world_wanted("jakieś radio z jazzem"))
        self.assertIsNone(radio._world_wanted("trójkę"))
        self.assertEqual(radio._short("SABROSITA Ciudad de México 590 AM XEPH-AM NRM"),
                         "SABROSITA Ciudad de México")
        said, played = [], []
        found = [("Rai Radio 1", "http://a"), ("Radio 105", "http://b"), ("Virgin", "http://c")]
        with mock.patch.object(radio, "_world_search", lambda c, t: found), \
                mock.patch.object(radio, "_alive", lambda u: u != "http://a"), \
                mock.patch.object(radio, "play", lambda n, u, **k: played.append(n)), \
                mock.patch.object(radio, "_remember_station", lambda *a: None), \
                mock.patch.object(radio, "playing", lambda: played[-1] if played else None):
            self.assertTrue(radio.handle("Włącz radio z Włoch", said.append))
            self.assertEqual(played, ["Radio 105"])                     # Rai refused us
            self.assertIn("radio z Włoch", said[-1])
            self.assertTrue(radio.handle("Następna stacja", said.append))
            self.assertEqual(played[-1], "Virgin")
            # with a complaint after it (11 Oct: the model asked which one)
            self.assertTrue(radio.handle("Weź jakieś inne radio, to jest paskudne.",
                                         said.append))
            self.assertEqual(played[-1], "Radio 105")
        for t in ("Zmień radio, bo nudne", "Puść coś innego", "Daj inną stację"):
            with mock.patch.object(radio, "playing", lambda: "Trójka"):
                self.assertTrue(radio._next_asked(t.lower()), t)
        for t in ("Włącz inne radio z jazzem", "Coś innego chciałam powiedzieć"):
            with mock.patch.object(radio, "playing", lambda: "Trójka"):
                self.assertFalse(radio._next_asked(t.lower()), t)
        self.assertFalse(radio._next_asked("weź inne radio"))            # nothing plays
        # 11 Oct sweep: "jakieś radio rockowe" → "Nie znalazłam stacji…", "coś
        # spokojnego do pracy" and "puść BBC" → the model said it can't
        played.clear()
        with mock.patch.object(radio, "play", lambda n, u, **k: played.append(n)), \
                mock.patch.object(radio, "_remember_station", lambda *a: None), \
                mock.patch.object(radio, "_world_play", lambda w, s: False), \
                mock.patch.object(radio, "_lookup", lambda n: ("BBC World Service", "http://w")):
            for t in ("Włącz jakieś radio rockowe", "Włącz radio rockowe",
                      "Włącz coś spokojnego do pracy", "Puść BBC"):
                self.assertTrue(radio.handle(t, said.append), t)
        # (15 Oct: the catalogue's rock and "Do pracy" stations)
        rock, calm = ([n for n, _, _ in radio._CAT[c][2]] for c in ("rock", "calm"))
        self.assertIn(played[0], rock)
        self.assertIn(played[1], rock)
        self.assertIn(played[2], calm)
        self.assertEqual(played[3], "BBC World Service")
        self.assertEqual(radio._spoken("Radio Paradise Main Mix 320k AAC"),
                         "Radio Paradise Main Mix")
        # a station by its name, not after "radio" (went to the model, refused)
        played.clear()
        with mock.patch.object(radio, "_lookup", lambda n: ("Polskie Radio Chopin", "http://x")),                 mock.patch.object(radio, "play", lambda n, u, **k: played.append(n)),                 mock.patch.object(radio, "_remember_station", lambda *a: None):
            import settings
            settings.put("radio_found", {})
            self.assertTrue(radio.handle("Włącz Polskie Radio Chopin", said.append))
        self.assertEqual(played, ["Radio Chopin"])            # (in the catalogue since 15 Oct)
        import brain
        self.assertTrue(brain._COMMAND_OK.match("włącz Polskie Radio Chopin"))
        self.assertTrue(brain._COMMAND_OK.match("włącz BBC Radio 1"))

    def test_radio_is_levelled(self):
        import radio
        # 11 Oct: "radio is by default too loud compared to her voice"
        self.assertLess(radio.MUSIC_RMS, 3700 / 2)          # well under her voice

    def test_radio_genres(self):
        import radio
        said = []
        played = []
        old = radio.play
        radio.play = lambda name, url, **k: played.append(name)
        try:
            self.assertTrue(radio.handle("Włącz radio z jakąś spokojną muzyką", said.append))
            self.assertTrue(radio.handle("Włącz radijko", said.append))
            # (15 Oct: a calm station of the catalogue's "Do pracy", not Dwójka)
            self.assertIn(played[0], [n for n, _, _ in radio._CAT["calm"][2]])
            for t in ("Włącz radio zed", "Włącz radio set"):       # how STT hears "ZET"
                played.clear()
                self.assertTrue(radio.handle(t, said.append))
                self.assertEqual(played, ["Radio ZET"], t)
            for t in ("Puść jakieś radio, obojętnie jakie.", "Włącz jakieś radio"):
                played.clear()
                self.assertTrue(radio.handle(t, said.append), t)    # any → the last one
                self.assertEqual(len(played), 1, t)
            self.assertFalse(radio.handle("Puść coś śmiesznego", said.append))
            self.assertEqual(radio._spoken("Polskie Radio - Chopin (Radio Chopin) (AAC+)"),
                             "Polskie Radio Chopin")
            asked = []
            with mock.patch.object(radio, "_search", lambda q, c: asked.append(q) or []):
                radio._lookup("polskie radio chopin")
            self.assertIn("chopin", asked)                # substring search: shorter forms too
            with mock.patch.object(radio, "_lookup", lambda n: None):    # offline
                for t in ("Włącz radio dla dzieci", "Puść muzykę dla dzieci",
                          "Włącz RMF dla dzieci"):
                    played.clear()
                    self.assertTrue(radio.handle(t, said.append))
                    self.assertIn(played[0], ["RMF Dla Dzieci", "Polskie Radio Dzieciom"], t)
        finally:
            radio.play = old

    def test_reminder_with_seconds_only(self):
        import timers
        with mock.patch.object(timers, "_save", lambda: None), \
                mock.patch.object(timers, "_timers", []):
            done = timers.apply([{"type": "reminder", "seconds": 3600, "at": "",
                                  "label": "pranie", "repeat": "none"}])
            self.assertEqual(len(done), 1)
            self.assertAlmostEqual(timers._timers[0]["due"], time.time() + 3600, delta=5)
            self.assertEqual(timers.apply([{"type": "reminder", "seconds": 0, "at": "",
                                            "label": "x"}]), [])

    def test_brain_searches_when_it_says_so(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "brain.py"), encoding="utf-8").read()
        self.assertIn("said she'd check online without the command", src)
        import re as _re
        rx = r"\bsprawdz\w*\s+(?:to\s+|mi\s+)?w\s+(?:internecie|sieci)"
        self.assertTrue(_re.search(rx, "Sprawdzam w internecie kurs złotego.", _re.I))
        self.assertTrue(_re.search(rx, "Już sprawdzam to w internecie.", _re.I))
        self.assertFalse(_re.search(rx, "Mogę poszukać w internecie, jeśli chcesz.", _re.I))

    def test_websearch_parsing(self):
        import websearch
        self.assertEqual(websearch.request("Luna, poszukaj w internecie jaki zasięg ma Rode NT-USB?"),
                         "jaki zasięg ma Rode NT-USB")
        self.assertEqual(websearch.request("sprawdź w internecie: godziny otwarcia Biedronki"),
                         "godziny otwarcia Biedronki")
        self.assertIsNone(websearch.request("poszukaj kluczy"))
        self.assertIsNone(websearch.request("czy masz internet?"))
        self.assertEqual(websearch.clean("## [Biedronka](https://x.pl/a) jest **czynna** do 23. "
                                         "([maps.google.com](https://maps.google.com))"),
                         "Biedronka jest czynna do 23.")

    def test_show_text_on_screen(self):
        import commands
        from shared_state import state
        said = []
        self.assertTrue(commands.show_text("pokaż na ekranie: Rode NT-USB", said.append))
        self.assertEqual(state.overlay[2]["text"], "Rode NT-USB")
        self.assertTrue(commands.show_text("Luna, napisz na ekranie Shure MV7.", said.append))
        self.assertEqual(state.overlay[2]["text"], "Shure MV7")
        self.assertFalse(commands.show_text("pokaż zegar", said.append))
        self.assertFalse(commands.show_text("co jest na ekranie?", said.append))
        with state.lock:
            state.overlay = None

    def test_busy_with_holds_a_restart(self):
        from unittest import mock
        fakes = {n: mock.MagicMock() for n in ("quiz", "reading", "cooking", "radio")}
        fakes["quiz"].active.return_value = False
        fakes["reading"].armed.return_value = False
        fakes["cooking"].active.return_value = False
        fakes["radio"].playing.return_value = False
        with mock.patch.dict(sys.modules, fakes):
            import health
            self.assertIsNone(health.busy_with())
            fakes["quiz"].active.return_value = True
            self.assertEqual(health.busy_with(), "quiz")

    def test_reading_aloud(self):
        import reading
        for t in ("Posłuchaj, jak czytam.", "Luna, poczytam ci", "Chcę ci przeczytać bajkę",
                  "Czy mogę ci poczytać?"):
            self.assertTrue(reading.is_request(t), t)
        self.assertFalse(reading.is_request("Przeczytaj mi wiadomości"))
        self.assertFalse(reading.is_request("Czytałam dziś książkę"))
        done = []
        with mock.patch.object(reading.threading, "Thread"):
            reading.start(lambda s: None, lambda t, w: done.append(t))
        self.assertTrue(reading.armed())
        self.assertIsNone(reading.add("Był sobie kotek."))
        self.assertIsNone(reading.add("Kotek lubił mleko."))
        self.assertEqual(reading.add("Koniec."), "end")
        from shared_state import state
        self.assertEqual(state.overlay[2]["text"], "Słucham…")
        self.assertEqual(reading.take()[0], "Był sobie kotek. Kotek lubił mleko.")
        self.assertFalse(reading.armed())
        self.assertIsNone(state.overlay)
        with mock.patch.object(reading.threading, "Thread"):
            reading.start(lambda s: None, lambda t, w: None)
        self.assertEqual(reading.add("I żyli długo i szczęśliwie. Koniec."), "end")
        self.assertEqual(reading.take()[0], "I żyli długo i szczęśliwie.")
        with mock.patch.object(reading.threading, "Thread"):
            reading.start(lambda s: None, lambda t, w: None)
        self.assertEqual(reading.add("Przestań"), "stop")
        self.assertFalse(reading.armed())

    def test_she_asks_to_be_read(self):
        import reading
        self.assertTrue(reading.she_asks("Słyszałam tylko kawałek. Przeczytaj mi proszę oba!"))
        self.assertTrue(reading.she_asks("Przeczytajcie mi je, to powiem."))
        self.assertFalse(reading.she_asks("Przeczytałam to już."))
        self.assertFalse(reading.she_asks("Mogę ci przeczytać wiadomości."))
        self.assertTrue(reading.she_asks("Przeczytaj proszę oba."))
        self.assertIn("«Który ładniejszy?»",
                      reading.feedback_context("Wiersz.", "Emilka", "Który ładniejszy?"))

    def test_model_params_for_gpt5(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "brain.py"), encoding="utf-8").read()
        import ast, re as _re
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "model_params")
        ns = {"OPENAI_MAX_TOKENS": 700}
        exec(compile(ast.Module([fn], []), "brain", "exec"), ns)
        p = ns["model_params"]({"model": "gpt-5.4-mini", "max_tokens": 700, "temperature": 0.8})
        self.assertEqual(p["max_completion_tokens"], 700)
        self.assertNotIn("temperature", p)
        self.assertEqual(p["reasoning_effort"], "none")
        q = ns["model_params"]({"model": "gpt-4.1", "max_tokens": 700, "temperature": 0.8})
        self.assertEqual(q["temperature"], 0.8)

    def test_model_for_poems(self):
        import re
        import ast
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "brain.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], "id", "") == "_CRAFT")
        rx = eval(compile(ast.Expression(node.value), "brain", "eval"), {"re": re})
        self.assertTrue(rx.search("Wymyśl wierszyk o kotku"))
        self.assertTrue(rx.search("Zaśpiewaj piosenkę"))
        self.assertTrue(rx.search("Opowiedz mi spokojną bajkę na dobranoc"))
        self.assertFalse(rx.search("Która godzina?"))
        self.assertFalse(rx.search("Wierzysz w duchy?"))

    def test_neutral_you(self):
        from polish import neutral_you
        self.assertEqual(neutral_you("Co chciałbyś przeczytać?"), "Co chcesz przeczytać?")
        self.assertEqual(neutral_you("Chciałabyś posłuchać?"), "Chcesz posłuchać?")
        self.assertEqual(neutral_you("Mógłbyś powtórzyć?"), "Możesz powtórzyć?")
        self.assertEqual(neutral_you("Chciałabym zaśpiewać."), "Chciałabym zaśpiewać.")

    def test_empty_promise(self):
        from polish import empty_promise
        self.assertTrue(empty_promise("Dobrze, przypomnę ci o tym, jeśli chcesz.", []))
        self.assertTrue(empty_promise("Jasne, przypomnę ci wieczorem.", None))
        self.assertFalse(empty_promise("Przypomnę ci o 19:00.", [{"type": "reminder"}]))
        self.assertFalse(empty_promise("Przypomnę ci. O której?", []))
        self.assertFalse(empty_promise("Nie przypomnę sobie tego tytułu.", []))
        self.assertFalse(empty_promise("Pamiętaj o ładowarce.", []))

    def test_claims_undone(self):
        from polish import claims_undone
        cmd = [{"type": "command", "label": "wyłącz ekran gry"}]
        self.assertTrue(claims_undone("Jasne, usunęłam to z listy.", []))
        self.assertTrue(claims_undone("Jasne — wyłączam ekran gry.", cmd, ["wyłącz ekran gry"]))
        self.assertFalse(claims_undone("Włączam radio.", cmd, []))
        self.assertFalse(claims_undone("Skreśliłam mleko.", [{"type": "list_remove"}]))
        self.assertFalse(claims_undone("Nie wyłączam, spokojnie.", []))
        self.assertFalse(claims_undone("Zapisałam to sobie.", []))
        self.assertFalse(claims_undone("Mogę włączyć radio, chcesz?", []))

    def test_log_report_audio_by_hour(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools"))
        import log_report
        lines = ["[Luna] Running on Raspberry Pi 4 (started 08:00:01)",
                 "[health] 08:59 CPU 58°C, audio: 0 underruns, clock nudges 2, "
                 "PipeWire xruns 3 (since start), light 0.1",
                 "[health] 09:59 CPU 58°C, audio: 0 underruns, clock nudges 5, "
                 "PipeWire xruns 3 (since start)"]
        rows = log_report.audio_by_hour(lines)
        self.assertIn("since 08:00", rows[0])
        self.assertIn("+3 ", rows[1])
        self.assertIn("+0 ", rows[2])
        self.assertIn("5 nudges", rows[2])
        self.assertEqual(log_report.audio_by_hour(["[Luna] Running on x"]), [])
        lat = log_report.latency_summary([
            "[latency] end of speech → her voice 3.00s (text 1.00, model 1.10, sentence 2.00)",
            "[latency] end of speech → her voice 4.00s (text 1.50, model 1.60, sentence 2.50)",
            "[latency] end of speech → her voice 5.00s (text 2.00, model 2.10, sentence 3.00)"])
        self.assertIn("3 answers, median 4.00s", lat[0])
        self.assertIn("90% within 5.00s", lat[0])
        two = log_report.latency_summary(["[latency] end of speech → her voice 4.47s (text 1)",
                                          "[latency] end of speech → her voice 3.96s (text 1)"])
        self.assertIn("90% within 4.47s", two[0])
        self.assertIn("text 1.50, model 1.60, sentence 2.50", lat[1])
        self.assertEqual(log_report.latency_summary([]), [])

    def test_face_continuity(self):
        import faces
        from unittest import mock
        with mock.patch.object(faces, "_scores", lambda f: {"Andrzej": 0.36, "Maja": 0.10}):
            faces._last_sure.clear()
            self.assertEqual(faces.identify(None, learn_ok=False)[0], None)   # no sure match yet
            faces._last_sure["Andrzej"] = time.time() - 10
            self.assertEqual(faces.identify(None, learn_ok=False)[0], "Andrzej")
            faces._last_sure["Andrzej"] = time.time() - 120
            self.assertEqual(faces.identify(None, learn_ok=False)[0], None)   # too long ago
        with mock.patch.object(faces, "_scores", lambda f: {"Andrzej": 0.33, "Maja": 0.30}):
            faces._last_sure["Andrzej"] = time.time()
            self.assertEqual(faces.identify(None, learn_ok=False)[0], None)   # not clearly him
        with mock.patch.object(faces, "_scores", lambda f: {"Andrzej": 0.20}):
            self.assertEqual(faces.identify(None, learn_ok=False)[0], None)   # too far
        faces._last_sure.clear()

    def test_picture_note_names_left_to_right(self):
        import faces
        from shared_state import state
        with state.lock:
            old = state.layout
            state.layout = ([("Andrzej", 0.7), ("Maja", 0.2)], time.time())
        try:
            note = faces.picture_note()
            self.assertIn("od lewej: Maja, Andrzej", note)
            with state.lock:
                state.layout = ([("?", 0.5)], time.time())
            self.assertEqual(faces.picture_note(), "")
            with state.lock:
                state.layout = ([("Maja", 0.5), ("?", 0.9)], time.time())
            self.assertIn("Maja, ktoś, kogo nie znasz", faces.picture_note())
            with state.lock:
                state.layout = ([("Maja", 0.5)], time.time() - 60)
            self.assertEqual(faces.picture_note(), "")
        finally:
            with state.lock:
                state.layout = old

    def test_weather_setup_asks_once(self):
        import commands
        import weather
        said = []
        with mock.patch.object(weather, "enabled", lambda: False), \
                mock.patch.object(weather, "set_place", lambda p: "Kraków" if "krak" in p else None):
            self.assertTrue(commands.weather_setup("Jaka jest dziś pogoda?", said.append))
            self.assertIn("W jakim mieście", said[-1])
            self.assertEqual(commands.weather_setup("W Krakowie", said.append),
                             ("ask", "Jaka jest dziś pogoda?"))
            self.assertIn("Kraków", said[-1])
            self.assertFalse(commands.weather_setup("Jaka jest pogoda w Berlinie?", said.append))
            self.assertFalse(commands.weather_setup("Lubię jesień", said.append))

    def test_polite_to_command(self):
        import commands
        p = commands.polite_to_command
        self.assertEqual(p("Czy możesz włączyć lampkę?"), "włącz lampkę")
        self.assertEqual(p("Luna, możesz mi przypomnieć za 20 minut o praniu?"),
                         "przypomnij mi za 20 minut o praniu")
        self.assertEqual(p("Mogłabyś zagrać ze mną w kółko i krzyżyk?"),
                         "zagraj ze mną w kółko i krzyżyk")
        self.assertIsNone(p("Czy możesz mi wytłumaczyć fotosyntezę?"))   # unknown verb
        self.assertIsNone(p("Włącz lampkę"))
        self.assertEqual(p("Włączysz lampkę?"), "włącz lampkę")
        self.assertEqual(p("Luna, nastawisz minutnik na 5 minut?"), "nastaw minutnik na 5 minut")
        self.assertIsNone(p("Wiesz, co dziś robiłam?"))
        self.assertEqual(p("No to nastaw minutnik na 5 minut"), "nastaw minutnik na 5 minut")
        self.assertEqual(p("Luna, a teraz włącz radio"), "włącz radio")
        self.assertIsNone(p("To jest Kasia"))
        self.assertIsNone(p("No to dobranoc"))

    def test_weekday_of(self):
        import calc
        today = datetime.date(2026, 10, 5)                      # a Monday
        self.assertEqual(calc.weekday_of("Jaki dzień tygodnia będzie 24 grudnia?", today),
                         "Wigilia wypada w czwartek.".replace("Wigilia", "24 grudnia"))
        self.assertEqual(calc.weekday_of("W jaki dzień wypada Wigilia?", today),
                         "Wigilia wypada w czwartek.")
        self.assertEqual(calc.weekday_of("jaki dzień będzie 1 maja", today),
                         "1 maja 2027 wypada w sobotę.")
        self.assertEqual(calc.weekday_of("Jaki dzień tygodnia jest piątego października?",
                                         today), "5 października to dzisiaj — poniedziałek.")
        self.assertIsNone(calc.weekday_of("Jaki dzień będzie w piątek?", today))
        self.assertIsNone(calc.weekday_of("Jaki dzień był wczoraj?", today))
        # 13 Oct probe: the past and a year said went to the model / the wrong year
        self.assertEqual(calc.weekday_of("Jaki dzień tygodnia był 1 stycznia?", today),
                         "1 stycznia był czwartek.")
        self.assertEqual(calc.weekday_of("jaki dzień była Wigilia?", today),
                         "Wigilia 2025 była środa.")
        self.assertEqual(calc.weekday_of("Jaki dzień tygodnia będzie 24 grudnia 2030?", today),
                         "24 grudnia 2030 wypada we wtorek.")         # "we", not "w wtorek"

    def test_calendar_and_sums_probe_13_oct(self):
        import calc
        today = datetime.date(2026, 10, 13)
        self.assertEqual(calc.holiday_when("Kiedy są Andrzejki?", today),
                         "Andrzejki wypadają 30 listopada, w poniedziałek — za 48 dni.")
        self.assertEqual(calc.clock_change("Kiedy zmiana czasu?", today),
                         "Zmiana na czas zimowy jest w nocy z soboty na niedzielę, 25 października:"
                         " o trzeciej cofamy zegarki na drugą — śpimy godzinę dłużej.")
        self.assertIn("28 marca 2027", calc.clock_change("Kiedy przestawiamy zegarki?",
                                                         datetime.date(2026, 10, 26)))
        self.assertIsNone(calc.clock_change("Zmiana czasu to bez sensu"))
        self.assertEqual(calc.weekday_of("Jaki był dzień tygodnia 13 października 2000?", today),
                         "13 października 2000 był piątek.")
        self.assertEqual(calc.days_until("Ile dni do końca roku?", today),
                         "Do końca roku zostało 79 dni, czyli około 11 tygodni.")
        self.assertEqual(calc.days_until("Ile dni do końca miesiąca?", today),
                         "Do końca miesiąca zostało 18 dni, czyli około 3 tygodni.")
        self.assertEqual(calc.days_until("Ile dni do końca roku szkolnego?", today)[:28],
                         "Do końca roku szkolnego zost")
        for said, want in (("Pomnóż 12 przez 12", "12 razy 12 to 144."),
                           ("Podziel 144 przez 12", "144 przez 12 to 12."),
                           ("Dodaj 15 i 27", "15 plus 27 to 42."),
                           ("Odejmij 8 od 20", "20 minus 8 to 12."),
                           ("Ile to jest 100 podzielić na 3?", "100 przez 3 to około 33,33."),
                           ("Ile to jest ćwierć z 200?", "Ćwierć z 200 to 50."),
                           ("Ile to jest 1/4 z 200?", "1/4 z 200 to 50."),
                           ("Ile to jest trzy czwarte z 80?", "Trzy czwarte z 80 to 60."),
                           ("Ile to jest połowa z 90?", "Połowa z 90 to 45.")):
            self.assertEqual(calc.answer(said), said and want, said)
        self.assertIsNone(calc.answer("Dodaj 2 minuty"))
        self.assertIsNone(calc.fraction_of("Ile to jest coś z 90?"))

    def test_probe_13_oct_evening_routes(self):
        import drawing
        import quiz
        import twenty
        self.assertTrue(drawing._SHOW.search("Pokaż ostatni rysunek"))
        self.assertEqual(quiz.trigger("Zadaj mi pytanie z matematyki"), "mix")
        self.assertEqual(quiz.trigger("Zadanie z dodawania"), "add")
        self.assertEqual(quiz.trigger("Tabliczka mnożenia do 100"), "mul")
        self.assertIsNone(quiz.trigger("Zadanie z matematyki mam trudne"))
        self.assertTrue(twenty.reverse_wanted("Ja myślę o zwierzęciu"))
        self.assertTrue(twenty.reverse_wanted("Wymyśliłam zwierzę"))
        self.assertFalse(twenty.reverse_wanted("Myślę o zwierzęciu dla Mai na urodziny"))

    def test_do_not_disturb_and_stopwatch(self):
        import counting
        import idle_engine
        for t in ("Nie przeszkadzać", "Włącz tryb nie przeszkadzać", "Tryb cichy"):
            with state.lock:
                state.proactive_muted_until = 0.0
            self.assertTrue(idle_engine.check_mute(t), t)
            with state.lock:
                self.assertGreater(state.proactive_muted_until, time.time(), t)
        self.assertTrue(idle_engine.check_mute("Wyłącz tryb nie przeszkadzać"))
        with state.lock:
            self.assertEqual(state.proactive_muted_until, 0.0)
        import screens
        self.assertTrue(screens.handle("Pokaż zegar przez minutę", lambda *a, **k: None,
                                       lambda *a, **k: None))
        with state.lock:
            self.assertAlmostEqual(state.overlay[1] - time.time(), 60, delta=2)
            state.overlay = None
        said = []
        counting._watch["t0"] = time.time() - 75
        try:
            self.assertTrue(counting.ask_stopwatch("Ile czasu minęło?", said.append))
            self.assertIn("minut", said[0])
        finally:
            counting._watch["t0"] = None

    def test_photos_by_voice_and_quiet_stop(self):
        import commands
        import screens
        d = tempfile.mkdtemp()
        said = []
        with mock.patch.object(screens, "PHOTOS_DIR", d), \
                mock.patch.object(screens, "BIN", os.path.join(d, "kosz")), \
                mock.patch.object(screens, "_show", lambda *a, **k: None):
            self.assertTrue(screens.photo_command("ile masz zdjęć", said.append))
            self.assertIn("żadnych", said[-1])
            for n in ("20261014-100000.jpg", "20261014-110000.jpg"):
                open(os.path.join(d, n), "wb").close()
            self.assertTrue(screens.photo_command("ile masz zdjęć", said.append))
            self.assertTrue(said[-1].startswith("Mam 2 zdjęcia."))
            self.assertTrue(screens.photo_command("usuń ostatnie zdjęcie", said.append))
            self.assertEqual(screens._shots(), ["20261014-100000.jpg"])        # into the bin
            self.assertTrue(os.path.exists(os.path.join(d, "kosz", "20261014-110000.jpg")))
            self.assertTrue(screens.photo_command("przywróć zdjęcie", said.append))
            self.assertEqual(len(screens._shots()), 2)
            self.assertFalse(screens.photo_command("usuń zdjęcie babci z facebooka", said.append))
        # "Obudź się" — her own answer; a bare "Cisza" with nothing on — quiet
        said.clear()
        self.assertTrue(commands.handle("Luna, obudź się", said.append, lambda *a, **k: None))
        self.assertTrue(said)
        said.clear()
        with state.lock:
            state.conversation_active = True
        self.assertTrue(commands.handle("Cisza", said.append, lambda *a, **k: None))
        self.assertEqual(said, [])
        with state.lock:
            self.assertFalse(state.conversation_active)
            state.convo_closed_hard = False

    def test_evening_and_morning_said(self):
        import clockgame
        import commands
        # 14 Oct probe: "budzik na 8 wieczorem" was 08:00
        self.assertEqual(clockgame.parse("8 wieczorem"), (20, 0))
        self.assertEqual(clockgame.parse("dziewiątej wieczorem"), (21, 0))
        self.assertEqual(clockgame.parse("trzecia po południu"), (15, 0))
        self.assertEqual(clockgame.parse("drugiej w nocy"), (2, 0))
        self.assertEqual(clockgame.parse("dwunastej w nocy"), (0, 0))
        self.assertEqual(clockgame.parse("w pół do ósmej"), (7, 30))
        self.assertEqual(clockgame.parse("7 rano"), (7, 0))
        self.assertEqual(commands.local_alarm("Nastaw budzik na 8 wieczorem"), ("20:00", "none"))
        self.assertEqual(commands.local_alarm("Nastaw budzik na za dwadzieścia siódma"),
                         ("06:40", "none"))
        self.assertIsNone(commands.local_alarm("Obudź mnie za 20 minut"))
        at15 = datetime.datetime(2026, 10, 14, 15, 0).timestamp()
        r = timers.local_reminder
        self.assertEqual(r("Przypomnij mi o 7 rano o lekach", at15),
                         ({"type": "reminder", "at": "2026-10-15 07:00", "repeat": "none",
                           "label": "o lekach"}, "Dobrze, przypomnę jutro o siódmej rano."))
        self.assertEqual(r("Przypomnij mi o dziewiątej wieczorem o tabletce", at15)[0]["at"],
                         "21:00")
        self.assertEqual(r("Przypomnij mi kwadrans po piątej o praniu", at15)[0]["at"], "17:15")
        self.assertEqual(r("Przypomnij mi jutro o 6 rano o pociągu", at15)[0]["at"],
                         "2026-10-15 06:00")                 # not 18:00
        self.assertIsNone(r("Przypomnij mi 5 rzeczy na zakupy", at15))

    def test_probe_14_oct(self):
        import commands
        import counting
        import drawing
        import fun
        import health
        import screens
        import weather
        said = []
        # gestures at once; "pokaż kciuk" / "pokaż prognozę" are not photos
        for text, name in (("Pomachaj mi", "wave"), ("Luna, kiwnij głową", "nod"),
                           ("Pokręć głową", "shake"), ("Pokaż kciuk", "thumbs_up"),
                           ("Zrób serduszko", "heart")):
            self.assertTrue(fun.gesture(text, said.append), text)
            with state.lock:
                self.assertEqual(state.gesture_anim, name, text)
        self.assertFalse(fun.gesture("Pomachaj babci, jak przyjdzie jutro", said.append))
        for t in ("Pokaż prognozę", "Pokaż kciuk", "Pokaż kalendarz", "Pokaż buzię"):
            self.assertFalse(drawing.bare_show(t, lambda *a, **k: None), t)
        self.assertTrue(drawing._BARE_SHOW.match("Pokaż planety"))
        self.assertIsNone(drawing._NOT_TO_SEE.match("planety"))
        # animal sounds (and the costume)
        for text, sound in (("Zamiaucz", "Miau"), ("Jak robi krowa?", "Muuu"),
                            ("Ryknij jak lew", "Wrrr"), ("Jaki dźwięk wydaje kaczka?", "Kwa")):
            said.clear()
            self.assertTrue(fun.animal_sound(text, said.append), text)
            self.assertTrue(said[0].startswith(sound), (text, said))
        self.assertFalse(fun.animal_sound("Co robi kot?", said.append))
        self.assertFalse(fun.animal_sound("Jak mówi kot po angielsku?", said.append))
        with state.lock:
            state.costume = None
        # countdowns
        self.assertEqual(counting.parse_count("Policz od dziesięciu do zera"), ("down", 10))
        self.assertEqual(counting.parse_count("Odliczaj do startu rakiety"), ("down", 10))
        # letters
        self.assertEqual(commands.letters_answer("Ile liter ma słowo kot?"),
                         "Słowo kot ma 3 litery: ka, o, te.")
        self.assertEqual(commands.letters_answer("Na jaką literę zaczyna się słowo jabłko?"),
                         "Słowo jabłko zaczyna się na literę jot.")
        self.assertIn("dwuznak cz",
                      commands.letters_answer("Na jaką literę zaczyna się czapka?"))
        self.assertIsNone(commands.letters_answer("Ile liter ma alfabet po angielsku?"))
        # the processor's temperature
        with mock.patch.object(health.body, "cpu_temp", lambda: 52.4), \
                mock.patch.object(health.body, "load_percent", lambda: 23), \
                mock.patch.object(health.body, "throttled", lambda: False):
            self.assertEqual(health.temp_answer("Jaka jest temperatura procesora?"),
                             "Mój procesor ma 52 stopnie, obciążenie 23 procent. "
                             "Wszystko w normie.")
        self.assertIsNone(health.temp_answer("Jaka jest temperatura na dworze?"))
        # the forecast as rows
        d = {"daily": {"time": ["2026-10-14", "2026-10-15", "2026-10-16"],
                       "weather_code": [3, 61, 0], "temperature_2m_min": [7, 6, 4],
                       "temperature_2m_max": [13, 12, 15],
                       "precipitation_probability_max": [40, 80, 0]}}
        rows = weather.forecast_rows(d)
        self.assertEqual(rows[0], ("Dziś", "pochmurno, 7–13°C, deszcz 40%"))
        self.assertEqual(rows[2][0], "piątek 16.10")
        self.assertTrue(screens._WEATHER.match("pokaż prognozę"))
        # a page closed by voice — only a page, only those words
        with state.lock:
            state.overlay = ("clock", time.time() + 30, None)
        self.assertTrue(commands.close_page("Zamknij", said.append))
        with state.lock:
            self.assertIsNone(state.overlay)
            state.overlay = ("ttt", time.time() + 30, None)
        self.assertFalse(commands.close_page("Koniec", said.append))   # a game: its own
        with state.lock:
            state.overlay = ("list", time.time() + 30, None)
        self.assertFalse(commands.close_page("Zamknij okno w kuchni", said.append))
        with state.lock:
            state.overlay = None
        # the screen the other way round
        self.assertTrue(commands._SCREEN_AFTER.match("ekran ciemniej"))
        self.assertEqual(commands._SCREEN_AFTER.match("jasność ekranu na 50").group(2), "50")

    def test_every_ambience_sound_is_audible(self):
        # 18 Oct: the sea was brown noise all below 30 Hz — it played as silence
        import numpy as np
        import ambience
        for kind in ambience.NAMES:
            g = ambience._Gen(kind)
            x = np.concatenate([g.block() for _ in range(100)])
            spec = np.abs(np.fft.rfft(x)) ** 2
            f = np.fft.rfftfreq(len(x), 1 / ambience.RATE)
            audible = np.sqrt(spec[f > 60].sum() / spec.sum() * (x ** 2).mean())
            self.assertGreater(audible, 0.02, kind)

    def test_switching_sleep_sounds_keeps_the_note_and_shows_effects(self):
        # 18 Oct: sea → fire, the sea's player ending cleared the fire's note
        import ambience
        import visualizer
        from shared_state import state

        class FakeProc:
            def __init__(self, *a, **k):
                self.stdin = self
                self.wrote = 0

            def write(self, b):
                self.wrote += len(b)

            def close(self):
                pass

            def terminate(self):
                pass

            def kill(self):
                pass

        with mock.patch.object(ambience.subprocess, "Popen", FakeProc), \
                mock.patch.object(visualizer, "tap") as tap:
            try:
                ambience.play("sea", 1)
                time.sleep(0.2)
                ambience.play("fire", 1)
                end = time.time() + 10                # (a busy Pi builds a loop slowly)
                while not tap.called and time.time() < end:
                    time.sleep(0.05)
                time.sleep(0.2)
                self.assertEqual(state.radio, "♪ " + ambience.NAMES["fire"])
                self.assertEqual(ambience.playing(), "fire")
                self.assertTrue(tap.called)
                a, level, fd, ch = tap.call_args[0]
                self.assertEqual((len(a), ch), (visualizer.RATE // 10, 1))
                self.assertGreater(level, 100)
            finally:
                ambience.stop()
                time.sleep(0.2)
        self.assertIsNone(state.radio)

    def test_fire_and_forest_sounds(self):
        import numpy as np
        import ambience
        played, said = [], []
        with mock.patch.object(ambience, "play", lambda k, m=45: played.append((k, m))):
            for text, kind in (("Włącz kominek", "fire"), ("Włącz szum lasu", "forest"),
                               ("Puść odgłosy ptaków", "forest"), ("Włącz deszcz", "rain")):
                played.clear()
                self.assertTrue(ambience.handle(text, said.append), text)
                self.assertEqual(played[0][0], kind, text)
            played.clear()
            self.assertTrue(ambience.handle("Biały szum na noc", said.append))
            self.assertEqual(played[0], ("noise", ambience.NIGHT_MINUTES))
            self.assertIn("na całą noc", said[-1])
            played.clear()
            # "las" is not in "klasyczną": the radio's, not the forest
            self.assertFalse(ambience.handle("Włącz klasyczną muzykę", said.append))
            # 18 Oct: switching by voice, and the fire off by its name
            for text in ("Przełącz na kominek", "Zmień na szum morza"):
                played.clear()
                self.assertTrue(ambience.handle(text, said.append), text)
                self.assertTrue(played, text)
            with mock.patch.object(ambience, "stop", lambda: True):
                self.assertTrue(ambience.handle("Wyłącz dźwięk kominka", said.append))
        for kind in ("fire", "forest"):
            g = ambience._Gen(kind)
            x = np.concatenate([g.block() for _ in range(80)])           # 8 s
            self.assertEqual(len(x), 80 * ambience.BLOCK)
            self.assertTrue(np.isfinite(x).all() and np.abs(x).max() < 2.0, kind)

    def test_an_offer_waits_for_its_answer(self):
        from polish import waits_for_answer
        # 14 Oct 12:30: an offer with a full stop closed the window in 8 s
        self.assertTrue(waits_for_answer("Bo dziś jest chłodno. Jak chcesz, mogę ci jeszcze "
                                         "powiedzieć, czy wziąć coś cieplejszego."))
        self.assertTrue(waits_for_answer("Która stacja?"))
        self.assertTrue(waits_for_answer("Chcesz, żebym nastawiła minutnik."))
        self.assertFalse(waits_for_answer("Jak chcesz, to ci powiem. Jest dwunasta."))
        self.assertFalse(waits_for_answer("Jest dwunasta trzydzieści."))

    def test_probe_13_oct_night(self):
        import brain
        import drawing
        import fun
        import screens
        # "Jasne, przekażę Maji…" → "Mai"
        with mock.patch.object(brain.faces, "vocatives", lambda: {}):
            self.assertIn("przekażę Mai,", brain._feminize("Jasne, przekażę Maji, że tak."))
        # "pokaż statystyki" is the status screen, not a photo to look for
        self.assertTrue(any(k in "no pokaż statystyki" for k in screens._STATUS))
        self.assertFalse(drawing.bare_show("Pokaż statystyki", lambda *a, **k: None))
        # "Zrób kotka" — the costume at once
        said = []
        with state.lock:
            state.costume = None
        self.assertTrue(fun.costume("zrób kotka", said.append))
        with state.lock:
            self.assertEqual(state.costume[0], "cat")
            state.costume = None
        self.assertFalse(fun.costume("zrób kotka z papieru dla mamy", said.append))
        self.assertFalse(fun.costume("zrób zdjęcie kotka", said.append))

    def test_names_said_in_one_breath(self):
        from polish import flowing_names
        voc = {"Andrzej": "Andrzeju", "Maja": "Maju", "Emilka": "Emilko"}
        # 13 Oct: "…, Andrzeju." — the voice stopped before the name
        self.assertEqual(flowing_names("Jasne, Andrzeju.", voc), "Jasne Andrzeju.")
        self.assertEqual(flowing_names("Dobrze, Maju, zaraz to zrobię.", voc),
                         "Dobrze Maju, zaraz to zrobię.")
        self.assertEqual(flowing_names("Śpij dobrze, kochanie!", voc), "Śpij dobrze kochanie!")
        self.assertEqual(flowing_names("Emilko, chodź tutaj.", voc), "Emilko, chodź tutaj.")
        self.assertEqual(flowing_names("Wiem, Andrzej to lubi.", voc), "Wiem, Andrzej to lubi.")
        self.assertEqual(flowing_names("Tak, majonez.", voc), "Tak, majonez.")

    def test_tomorrow_and_yesterday(self):
        import clock
        now = datetime.datetime(2026, 10, 13, 19, 0)               # a Tuesday
        self.assertEqual(clock.spoken_other_day(1, now), "Jutro będzie środa, czternasty października.")
        self.assertEqual(clock.spoken_other_day(-1, now),
                         "Wczoraj był poniedziałek, dwunasty października.")
        self.assertEqual(clock.spoken_other_day(-1, datetime.datetime(2026, 10, 11, 9, 0)),
                         "Wczoraj była sobota, dziesiąty października.")
        for t in ("Jaki jutro dzień?", "Luna, jaki był wczoraj dzień?", "Który dzisiaj jest?"):
            self.assertIsNotNone(clock.answer(t), t)
        self.assertIsNone(clock.answer("Jaki jutro dzień będzie na spacer?"))

    def test_breathing_length_and_nap(self):
        import breathing
        import commands
        self.assertEqual(breathing.cycles_for("ćwiczenie oddechowe na 3 minuty"), 15)
        self.assertIsNone(breathing.cycles_for("ćwiczenie oddechowe"))
        self.assertTrue(breathing.is_trigger("zróbmy medytację"))
        self.assertEqual(commands.alarm_in("Obudź mnie za 20 minut"), 1200)
        self.assertEqual(commands.alarm_in("Luna, obudź mnie za pół godziny proszę"), 1800)
        self.assertIsNone(commands.alarm_in("Obudź mnie za 20 minut, jak Maja wróci"))
        self.assertIsNone(commands.alarm_in("obudź mnie o 6:30"))

    def test_days_since(self):
        import calc
        today = datetime.date(2026, 10, 5)
        self.assertEqual(calc.days_since("Ile dni minęło od 1 września?", today),
                         "Od 1 września minęły 34 dni, czyli około 5 tygodni.")
        self.assertEqual(calc.days_since("Ile dni minęło od Wigilii?", today),
                         "Od Wigilii minęło 285 dni, czyli około 41 tygodni.")
        self.assertEqual(calc.days_since("ile minęło od trzeciego października", today),
                         "Od 3 października minęły 2 dni.")
        self.assertIsNone(calc.days_since("Ile minęło od kiedy się poznaliśmy?", today))

    def test_convert(self):
        import calc
        self.assertEqual(calc.convert("Ile to cali 30 centymetrów?"),
                         "30 centymetrów to około 11,81 cala.")
        self.assertEqual(calc.convert("Zamień 5 mil na kilometry"),
                         "5 mil to około 8,05 kilometra.")
        self.assertEqual(calc.convert("Ile to jest 20 stopni Celsjusza w Fahrenheitach?"),
                         "20 stopni Celsjusza to 68 stopni Fahrenheita.")
        self.assertEqual(calc.convert("ile to 2,5 kilograma w gramach"),
                         "2,5 kilograma to 2500 gramów.")
        self.assertEqual(calc.convert("Ile to 1 litr w mililitrach?"), "1 litr to 1000 mililitrów.")
        self.assertEqual(calc.convert("ile to 3 stopy w centymetrach"),
                         "3 stopy to 91,44 centymetra.")
        self.assertIsNone(calc.convert("Ile to kosztuje?"))
        self.assertIsNone(calc.convert("Ile to jest 5 metrów?"))           # into what?

    def test_holidays(self):
        import calc
        today = datetime.date(2026, 10, 5)
        self.assertEqual(calc.holiday_when("Kiedy jest Wielkanoc?", today),
                         "Wielkanoc wypada 28 marca 2027, w niedzielę — za 174 dni.")
        self.assertEqual(calc.holiday_when("Kiedy wypada tłusty czwartek?", today),
                         "Tłusty czwartek wypada 4 lutego 2027, w czwartek — za 122 dni.")
        self.assertIn("Boże Ciało wypada 27 maja 2027, w czwartek",
                      calc.holiday_when("kiedy jest Boże Ciało", today))
        self.assertIn("14 października", calc.holiday_when("Kiedy jest Dzień Nauczyciela?", today))
        self.assertIsNone(calc.holiday_when("Kiedy jest mecz?", today))
        # "świąt wielkanocnych" is Easter, "świąt" alone still Christmas
        self.assertIn("Wielkanocy", calc.days_until("Ile dni do świąt wielkanocnych?", today))
        self.assertIn("Wigilii", calc.days_until("Ile dni do świąt?", today))
        self.assertIn("tłustego czwartku", calc.days_until("Ile dni do tłustego czwartku?", today))

    def test_random_answer(self):
        import fun
        import random as _r
        rng = _r.Random(3)
        for _ in range(20):
            said = fun.random_answer("Wylosuj liczbę od 1 do 10", rng)
            self.assertTrue(said.startswith("Losuję… ") and 1 <= int(said[8:-1]) <= 10)
        self.assertIn(fun.random_answer("Luna, wybierz: pizza czy makaron?", rng),
                      ("Wybieram: pizza!", "Wybieram: makaron!"))
        self.assertIn(fun.random_answer("Kto dziś zmywa: Maja, tata czy mama?", rng),
                      ("Losuję… Maja!", "Losuję… tata!", "Losuję… mama!"))
        self.assertIn("Losuję…", fun.random_answer("losuj liczbę od jeden do sześć", rng))
        self.assertIsNone(fun.random_answer("Wybierz mi dobry film", rng))     # the model
        self.assertIsNone(fun.random_answer("Kto wygrał mecz?", rng))
        self.assertIsNone(fun.random_answer("Kto jest lepszy, Messi czy Ronaldo?", rng))
        self.assertIn("Losuję", fun.random_answer("Kto zaczyna, ja czy ty?", rng))

    def test_race_records(self):
        import quiz
        import settings
        settings.put("race_best", {})
        self.assertIn("pierwszy rekord", quiz.race_result("mul", True, 61.2, "Maja"))
        self.assertIn("Nowy rekord! Poprzedni: 61", quiz.race_result("mul", True, 48, "Maja"))
        self.assertIn("Rekord to 48", quiz.race_result("mul", True, 55, "Maja"))
        self.assertIn("tylko bez błędu", quiz.race_result("mul", False, 30, "Maja"))
        self.assertIn("pierwszy rekord", quiz.race_result("add", True, 70, "Maja"))  # per game

    def test_reading_practice(self):
        import quiz
        self.assertEqual(quiz.trigger("Poćwiczmy czytanie"), "read")
        self.assertIsNone(quiz.trigger("Lubię czytanie książek"))
        q = {"kind": "read", "seen": set()}
        quiz._new_question(q)
        self.assertIn(q["answer"], quiz.READING)
        q["answer"] = "Żaba skacze do stawu."
        self.assertTrue(quiz._check(q, "Żaba skacze do stawu"))
        self.assertTrue(quiz._check(q, "żaba skacze do stawy"))           # close enough
        self.assertFalse(quiz._check(q, "Żaba śpi"))
        self.assertIn("skacze", q["hint"])

    def test_division_quiz(self):
        import quiz
        self.assertEqual(quiz.trigger("Przepytaj mnie z dzielenia"), "div")
        self.assertEqual(quiz.trigger("Przepytaj mnie z tabliczki mnożenia"), "mul")
        for _ in range(30):
            op, a, b, res = quiz._math_problem("div", 100, None)
            self.assertEqual(a, b * res)
        op, a, b, res = quiz._math_problem("div", 100, 7)
        self.assertEqual(b, 7)
        q = {"kind": "div", "seen": set(), "limit": 100}
        quiz._new_question(q)
        self.assertIn("podzielić przez", q["say"])

    def test_quiz_limit(self):
        import quiz
        self.assertEqual(quiz.quiz_limit("Quiz z dodawania do 20"), 20)
        self.assertEqual(quiz.quiz_limit("odejmowanie w zakresie 50"), 50)
        self.assertEqual(quiz.quiz_limit("dodawanie do tysiąca"), 1000)
        self.assertEqual(quiz.quiz_limit("przepytaj mnie z dodawania"), 100)
        self.assertEqual(quiz.quiz_limit("dodawanie do dziesięciu"), 10)

    def test_table_row(self):
        import quiz
        self.assertEqual(quiz.table_row("Przepytaj mnie z tabliczki mnożenia przez 7"), 7)
        self.assertEqual(quiz.table_row("tabliczka mnożenia przez siedem"), 7)
        self.assertIsNone(quiz.table_row("Przepytaj mnie z tabliczki mnożenia"))
        for _ in range(30):
            op, a, b, res = quiz._math_problem("mul", 100, 7)
            self.assertIn(7, (a, b))
            self.assertEqual(res, a * b)

    def test_custom_dictation_words(self):
        import quiz
        import settings
        self.assertEqual(quiz.custom_words("Zapamiętaj słowa do dyktanda: rzeka, góra i żaba"),
                         ["rzeka", "góra", "żaba"])
        said = []
        self.assertTrue(quiz.dictation_words("Słowa do dyktanda: chleb, hamak", said.append))
        self.assertEqual(settings.get("dictation_words"), ["chleb", "hamak"])
        q = {"kind": "dictation", "seen": set()}
        quiz._new_question(q)
        self.assertIn(q["answer"], ("chleb", "hamak"))
        self.assertTrue(quiz.dictation_words("Wyczyść słowa do dyktanda", said.append))
        self.assertEqual(settings.get("dictation_words"), [])
        self.assertEqual(quiz.custom_words("Zróbmy dyktando ze słów: ołówek, ćma"),
                         ["ołówek", "ćma"])

    def test_english_dictation(self):
        import quiz
        self.assertEqual(quiz.trigger("Zróbmy dyktando z angielskiego"), "dictation_en")
        self.assertEqual(quiz.trigger("Zróbmy dyktando"), "dictation")
        q = {"kind": "dictation_en", "seen": set()}
        quiz._new_question(q)
        self.assertIn(q["answer"], q["accept"])
        self.assertTrue(q["say"].startswith("Napisz po angielsku: "))
        self.assertTrue(any(quiz._same_word(w.upper(), q["answer"]) for w in q["accept"]))

    def test_mentions_dont_start_games(self):
        import cooking
        import quiz
        for s in ("Jutro mamy dyktando w szkole", "Kiedy będzie dyktando?"):
            self.assertIsNone(quiz.trigger(s), s)
        for s in ("Zróbmy dyktando", "Dyktando!", "Luna, przepytaj mnie z dyktanda",
                  "Poćwiczmy ortografię"):
            self.assertEqual(quiz.trigger(s), "dictation", s)
        self.assertIsNone(cooking.wants("Gotujemy obiad, bo zaraz przyjdą goście"))
        self.assertIsNone(cooking.wants("Gotujemy obiad"))
        self.assertIsNone(quiz.trigger("W szkole robili quiz ze stolic"))
        self.assertEqual(quiz.trigger("Zróbmy quiz ze stolic"), "capitals")
        self.assertEqual(quiz.trigger("quiz ze stolic"), "capitals")
        import tictac
        self.assertFalse(tictac.wants("Moja koleżanka gra w kółko i krzyżyk na lekcjach"))
        self.assertTrue(tictac.wants("Luna, zagrajmy w kółko i krzyżyk"))
        self.assertEqual(cooking.wants("Upieczmy ciasto czekoladowe"), "ciasto czekoladowe")

    def test_world_time(self):
        import clock
        from zoneinfo import ZoneInfo
        waw = ZoneInfo("Europe/Warsaw")
        oct5 = datetime.datetime(2026, 10, 5, 14, 15, tzinfo=waw)      # summer time
        self.assertEqual(clock.world_time("Która godzina w Tokio?", oct5),
                         "W Tokio jest teraz dwudziesta pierwsza piętnaście — "
                         "7 godzin później niż u nas.")
        self.assertEqual(clock.world_time("Luna, która jest godzina w Nowym Jorku?", oct5),
                         "W Nowym Jorku jest teraz ósma piętnaście — "
                         "6 godzin wcześniej niż u nas.")
        self.assertIn("3,5 godziny później", clock.world_time("ile jest godzin w Indiach", oct5))
        late = datetime.datetime(2026, 10, 5, 23, 30, tzinfo=waw)
        self.assertTrue(clock.world_time("Która godzina w Australii?", late).endswith(
            "już jutro."))
        self.assertIn("Na Hawajach jest", clock.world_time("a jaka godzina na Hawajach?", oct5))
        jan = datetime.datetime(2027, 1, 10, 12, 0, tzinfo=waw)          # winter time
        self.assertIn("8 godzin później", clock.world_time("Która godzina w Tokio?", jan))
        self.assertIn("tak samo jak u nas", clock.world_time("Która godzina w Berlinie?", jan))
        self.assertIsNone(clock.world_time("Która godzina w Pcimiu?", jan))     # unknown
        self.assertIsNone(clock.world_time("O której jest mecz w Tokio?", jan))

    def test_greeted_survives_restart(self):
        import idle_engine
        idle_engine.save_greeted({"Maja": "2026-10-05", None: "2026-10-04"})
        self.assertEqual(idle_engine.load_greeted(),
                         {"Maja": "2026-10-05", None: "2026-10-04"})

    def test_tictac_duo(self):
        import tictac
        self.assertTrue(tictac.duo_wanted("Zagrajmy we dwoje w kółko i krzyżyk"))
        self.assertTrue(tictac.wants("Chcę zagrać w kółko i krzyżyk z mamą"))
        tictac._say = lambda t: None
        tictac.start(lambda t: None, duo=True)
        cell = lambda i: ((190 + (i % 3) * 140 + 70) / 800, (30 + (i // 3) * 140 + 70) / 480)
        for i in (0, 3, 1, 4, 2):                    # X takes the top row
            tictac.tap(*cell(i))
        self.assertEqual(tictac._g["b"][:6], ["X", "X", "X", "O", "O", None])
        self.assertEqual(tictac._g["end"], "X")
        tictac.stop()

    def test_memo(self):
        import memo
        self.assertTrue(memo.wants("Zagrajmy w memory"))
        self.assertTrue(memo.wants("Luna, zagrajmy w pary"))
        self.assertFalse(memo.wants("W szkole graliśmy w memory na przerwie"))
        self.assertEqual(memo.card_at(0.5, 0.5), None)                 # in a gap
        self.assertEqual(memo.card_at((79 + 10) / 800, (31 + 10) / 480), 0)
        self.assertEqual(memo.card_at((79 + 3 * 164 + 10) / 800, (31 + 2 * 144 + 10) / 480), 11)
        # a whole game, tapped with perfect memory: 6 moves
        memo.start(lambda t: None)
        memo._say = lambda t: None
        pos = lambda i: ((79 + (i % 4) * 164 + 70) / 800, (31 + (i // 4) * 144 + 60) / 480)
        cards = memo._g["cards"]
        for shape in sorted(set(cards)):
            a, b = [i for i, c in enumerate(cards) if c == shape]
            memo.tap(*pos(a))
            memo.tap(*pos(b))
        self.assertTrue(memo._g["end"])
        self.assertEqual(memo._g["moves"], 6)
        memo.stop()
        # the hard one: 16 cards, 8 pairs, a 4 × 4 board
        self.assertTrue(memo.hard_wanted("Zagrajmy w trudne memory"))
        memo.start(lambda t: None, hard=True)
        self.assertEqual(len(memo._g["cards"]), 16)
        self.assertEqual(memo.card_at((85 + 3 * 160 + 5) / 800, (17 + 3 * 114 + 5) / 480, n=16), 15)
        memo.stop()

    def test_tictac(self):
        import tictac
        b = ["X", "X", None, "O", "O", None, None, None, None]
        self.assertEqual(tictac.best_move(b), 5)            # win beats blocking
        b = ["X", "X", None, None, "O", None, None, None, None]
        self.assertEqual(tictac.best_move(b), 2)            # block
        self.assertEqual(tictac._winner(["X"] * 3 + [None] * 6), ("X", (0, 1, 2)))
        self.assertEqual(tictac._winner(list("XOXXOOOXX")), ("draw", None))
        self.assertEqual(tictac.cell_at(0.5, 0.5), 4)        # the middle
        self.assertEqual(tictac.cell_at(0.01, 0.5), None)    # beside the board
        self.assertEqual(tictac.cell_at((190 + 10) / 800, (30 + 10) / 480), 0)
        self.assertTrue(tictac.wants("Zagrajmy w kółko i krzyżyk"))
        # squares said aloud (9 Oct probe: "Środek" only got the model's pretence)
        for said, cell in (("Środek", 4), ("Lewy górny róg", 0), ("prawy dolny", 8),
                           ("Górny środek", 1), ("środkowe po lewej", 3), ("pole 7", 6),
                           ("Piątka", 4), ("W lewym górnym rogu", 0)):
            self.assertEqual(tictac.spoken_cell(said), cell, said)
        self.assertIsNone(tictac.spoken_cell("prawy"))
        self.assertIsNone(tictac.spoken_cell("Mam 8 lat"))              # not a move (review)
        self.assertIsNone(tictac.spoken_cell("Ile masz lat?"))
        out = []
        with mock.patch.object(tictac.threading, "Timer", lambda *a, **k: mock.Mock()):
            tictac.start(out.append)
            self.assertTrue(tictac.voice_move("Środek", out.append))
            self.assertEqual(tictac._g["b"][4], "X")
            self.assertTrue(tictac.voice_move("Lewy górny róg", out.append))   # not her turn yet
            self.assertIn("mój ruch", out[-1])
        tictac.stop()
        # optimal play from both sides is always a draw
        for _ in range(5):
            b = [None] * 9
            turn = "X"
            while not tictac._winner(b)[0]:
                b[tictac.best_move(b, turn)] = turn
                turn = "O" if turn == "X" else "X"
            self.assertEqual(tictac._winner(b)[0], "draw")

    def test_local_reminder(self):
        at15 = datetime.datetime(2026, 10, 5, 15, 0).timestamp()
        r = timers.local_reminder
        self.assertEqual(r("Przypomnij mi za 20 minut o praniu", at15),
                         ({"type": "timer", "seconds": 1200, "label": "o praniu"},
                          "Dobrze, przypomnę za 20 minut."))
        self.assertEqual(r("Luna, przypomnij mi o 17, żeby zadzwonić do mamy", at15),
                         ({"type": "reminder", "at": "17:00", "repeat": "none",
                           "label": "zadzwonić do mamy"},
                          "Dobrze, przypomnę o siedemnastej."))
        self.assertEqual(r("przypomnij mi o piątej o wyjęciu ciasta", at15)[0]["at"], "17:00")
        self.assertEqual(r("przypomnij mi o praniu o 18", at15)[0],
                         {"type": "reminder", "at": "18:00", "repeat": "none",
                          "label": "o praniu"})
        self.assertEqual(r("Przypomnij mi o wpół do ósmej o bajce", at15)[0]["at"], "19:30")
        self.assertEqual(r("przypomnij mi o praniu za pół godziny", at15)[0]["seconds"], 1800)
        # 13 Oct probe: "za godzinę i kwadrans" was an hour
        self.assertEqual(r("Przypomnij mi za godzinę i kwadrans o pizzy", at15),
                         ({"type": "timer", "seconds": 4500, "label": "o pizzy"},
                          "Dobrze, przypomnę za godzinę i 15 minut."))
        self.assertEqual(r("przypomnij mi za 2 godziny i 10 minut o praniu", at15)[0]["seconds"],
                         7800)
        mon = datetime.datetime(2026, 10, 5, 15, 0).timestamp()      # a Monday
        self.assertEqual(r("Przypomnij mi jutro o 8 o dentyście", mon),
                         ({"type": "reminder", "at": "2026-10-06 08:00", "repeat": "none",
                           "label": "o dentyście"}, "Dobrze, przypomnę jutro o ósmej."))
        self.assertEqual(r("przypomnij mi w piątek o 17, żeby kupić bilety", mon)[0]["at"],
                         "2026-10-09 17:00")
        self.assertEqual(r("przypomnij mi pojutrze o piątej o basenie", mon)[0]["at"],
                         "2026-10-07 17:00")
        for text in ("Przypomnij mi jutro o dentyście",          # no time: the model
                     "Przypomnij mi o 17, żebym zadzwonił do mamy",   # to turn round
                     "Przypomnij mi codziennie o 8 o tabletkach",
                     "Przypomnij mi o praniu",                    # no time
                     "Przypomnij mi za 10 minut",                 # nothing to remind
                     "Przypomnij mi o 5 rzeczach na zakupy"):
            self.assertIsNone(r(text, at15), text)
        import clock
        self.assertEqual([clock.hour_locative(*t) for t in ((2, 0), (21, 0), (7, 5), (0, 0))],
                         ["drugiej", "dwudziestej pierwszej", "siódmej zero pięć", "północy"])

    def test_left_answer(self):
        now = 1_000_000.0
        with timers._lock:
            saved = list(timers._timers)
            timers._timers[:] = []
        try:
            self.assertEqual(timers.left_answer("Ile zostało na minutniku?", now),
                             "Nie mam teraz żadnego minutnika.")
            with timers._lock:
                timers._timers.append({"due": now + 262, "label": "", "kind": "timer"})
            self.assertEqual(timers.left_answer("Ile zostało na minutniku?", now),
                             "Zostały 4 minuty i 22 sekundy.")
            with timers._lock:
                timers._timers.append({"due": now + 1500, "label": "makaron", "kind": "timer"})
            self.assertEqual(timers.left_answer("ile jeszcze do końca minutnika", now),
                             "Minutniki — 4 minuty i 22 sekundy; makaron: 25 minut.")
            self.assertIsNone(timers.left_answer("Ile kosztuje minutnik?", now))
        finally:
            with timers._lock:
                timers._timers[:] = saved

    def test_duration_agreement(self):
        self.assertEqual(timers.say_duration(22), "22 sekundy")
        self.assertEqual(timers.say_duration(22 * 3600), "22 godziny")
        self.assertEqual(timers.say_duration(25 * 3600), "25 godzin")
        self.assertEqual(timers.say_duration(210), "3 minuty i 30 sekund")

    def test_labelled_timer(self):
        t = timers.local_labelled_timer
        self.assertEqual(t("Nastaw minutnik na 10 minut na makaron"), (600, "makaron"))
        self.assertEqual(t("minutnik na 8 minut do jajek"), (480, "do jajek"))
        self.assertEqual(timers._announcement({"kind": "timer", "label": "do jajek", "secs": 480}),
                         "Dzyń! Minutnik do jajek!")
        self.assertEqual(t("Luna, timer na pół godziny na ciasto drożdżowe"),
                         (1800, "ciasto drożdżowe"))
        self.assertIsNone(t("minutnik na pół godziny"))            # no label
        self.assertIsNone(t("minutnik na 10 minut"))
        self.assertIsNone(t("Ile zostało na minutniku na makaron?"))
        # 13 Oct probe: the label first, or after the time with no "na"
        self.assertEqual(t("Minutnik na makaron 9 minut"), (540, "makaron"))
        self.assertEqual(t("minutnik do jajek na 8 minut"), (480, "do jajek"))
        self.assertEqual(t("Nastaw minutnik 9 minut makaron"), (540, "makaron"))
        self.assertIsNone(t("minutnik na 10 minut proszę"))
        self.assertIsNone(t("minutnik 10 minut"))

    def test_say_duration(self):
        self.assertEqual([timers.say_duration(s) for s in (60, 300, 120, 1800, 3600, 5400, 45)],
                         ["minutę", "5 minut", "2 minuty", "30 minut", "godzinę",
                          "półtorej godziny", "45 sekund"])

    def test_weekly_monthly_yearly(self):
        # (a date still to come: past ones skip ahead to today — 17 Oct this
        # read 9 Oct → 23 Oct, not 16 Oct)
        fri = datetime.datetime(2030, 1, 4, 18, 0).timestamp()
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(fri, "weekly"))
        self.assertEqual((nxt.month, nxt.day, nxt.hour), (1, 11, 18))
        jan31 = datetime.datetime(2027, 1, 31, 9, 0).timestamp()
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(jan31, "monthly"))
        self.assertEqual((nxt.month, nxt.day), (2, 28))          # clamped
        # a birthday in May, set in October: next May, not "tomorrow"
        may = datetime.datetime(2026, 5, 12, 9, 0).timestamp()
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(may, "yearly", inclusive=True))
        self.assertGreater(nxt.timestamp(), time.time())
        self.assertEqual((nxt.month, nxt.day), (5, 12))

    def test_one_off_in_the_past_is_ignored(self):
        timers.apply([{"type": "reminder", "seconds": 0, "at": "2020-01-01 10:00",
                       "label": "dawno", "repeat": "none"}])
        self.assertEqual(timers._timers, [])

    def test_snooze_and_extend(self):
        timers._last_rang.update(t=time.time(), entry={"label": "", "kind": "alarm"})
        self.assertTrue(timers.snooze(300))
        self.assertEqual(timers._timers[0]["kind"], "alarm")
        self.assertFalse(timers.snooze(300))                    # only once per ring
        self.assertFalse(timers.extend(60))                     # no kitchen timer
        timers.apply([{"type": "timer", "seconds": 60, "at": "", "label": ""}])
        before = next(t for t in timers._timers if t["kind"] == "timer")["due"]
        self.assertTrue(timers.extend(120))
        after = next(t for t in timers._timers if t["kind"] == "timer")["due"]
        self.assertAlmostEqual(after - before, 120, delta=1)

    def test_polish_minutes(self):
        self.assertEqual([timers._minutes_pl(n) for n in (1, 2, 5, 12, 22, 25)],
                         ["minuta", "minuty", "minut", "minut", "minuty", "minut"])
        self.assertEqual(timers._announcement({"kind": "timer", "label": "", "secs": 180}),
                         "Dzyń! Minęły 3 minuty.")
        self.assertEqual(timers._announcement({"kind": "reminder", "label": "zadzwonić do mamy"}),
                         "Przypominam: zadzwonić do mamy!")
        # a labelled timer that is really a reminder (9 Oct: "Minął czas: wyjąć pranie!")
        self.assertEqual(timers._announcement({"kind": "timer", "label": "wyjąć pranie", "secs": 1800}),
                         "Przypominam: wyjąć pranie!")
        self.assertEqual(timers._announcement({"kind": "timer", "label": "makaron", "secs": 600}),
                         "Minął czas: makaron!")


class MemoryTest(unittest.TestCase):

    def test_relative_dates(self):
        today = memory._today()
        self.assertEqual(memory._when(today.isoformat()), "dzisiaj")
        self.assertEqual(memory._when((today - datetime.timedelta(days=1)).isoformat()), "wczoraj")
        self.assertEqual(memory._when((today - datetime.timedelta(days=3)).isoformat()), "3 dni temu")

    def test_due_thread_is_offered_at_conversation_start_at_most_twice(self):
        memory._session.clear()
        memory._save({"facts": ["Ma kota."], "episodes": [], "_wiped_at": 0,
                      "threads": [{"question": "Jak poszła rozmowa?",
                                   "due": memory._today().isoformat(), "asked": 0}]})
        offered = [("Jak poszła rozmowa?" in memory.prompt_block()) for _ in range(3)]
        self.assertEqual(offered, [True, True, False])

    def test_no_thread_mid_conversation(self):
        memory._save({"facts": [], "episodes": [], "_wiped_at": 0,
                      "threads": [{"question": "Jak poszło?",
                                   "due": memory._today().isoformat(), "asked": 0}]})
        memory._session[:] = [("cześć", "hej")]
        self.assertNotIn("Jak poszło?", memory.prompt_block())
        memory._session.clear()

    def test_transcript_names_the_speaker(self):
        t = memory._transcript([("[Maja] Lubię konie", "Super!", False),
                                ("włącz radio", "Włączam RMF.", True)])
        self.assertEqual(t, "[Maja] Lubię konie\nLuna: Super!\n"
                            "[Ktoś] włącz radio\nLuna (command): Włączam RMF.")

    def test_commands_only_are_not_consolidated(self):
        calls = []
        old = memory._client
        memory._client = type("C", (), {"chat": property(lambda s: calls.append(1))})()
        try:
            memory._session[:] = [("[Andrzej] włącz lampkę", "Włączam.", True)]
            memory.consolidate()
        finally:
            memory._client = old
        self.assertEqual(calls, [])
        self.assertEqual(memory._session, [])

    def test_ordinary_update_never_shrinks_memory(self):
        old = ["Andrzej lubi żarty opowiadane przez Lunę.",
               "Andrzej mówi po hiszpańsku i potrafi rozmawiać w tym języku.",
               "Andrzej pracuje nad projektem związanym z certyfikatami."]
        new = ["Andrzej pracuje nad projektem certyfikatów, teraz nad bazą danych.",
               "Maja ma chomika Pestkę."]
        got = memory.keep_old_facts(new, old, tidy=False)
        self.assertIn("Andrzej lubi żarty opowiadane przez Lunę.", got)
        self.assertIn("Andrzej mówi po hiszpańsku i potrafi rozmawiać w tym języku.", got)
        self.assertNotIn("Andrzej pracuje nad projektem związanym z certyfikatami.", got)  # updated
        self.assertIn("Maja ma chomika Pestkę.", got)
        # the tidy may weed, but not wipe
        self.assertEqual(memory.keep_old_facts(["Zupełnie co innego."], old, tidy=True), old)

    def test_facts_sanity(self):
        old = [f"fakt {i}" for i in range(12)]
        self.assertTrue(memory.facts_ok(old[:6], old))     # a cleanup
        self.assertFalse(memory.facts_ok(old[:2], old))    # lost most of it
        self.assertTrue(memory.facts_ok(old[:2], old, old[2:]))   # …and said why
        self.assertFalse(memory.facts_ok(None, old))
        self.assertTrue(memory.facts_ok([], ["a", "b"]))   # tiny memory: trust it

    def test_facts_about_and_forget_one(self):
        memory._save({"facts": ["Maja ma chomika o imieniu Pestka.",
                                "Andrzej lubi żarty.", "Mai ulubiony kolor to fiolet."],
                      "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertEqual(len(memory.facts_about("Maja")), 2)
        self.assertIsNone(memory.forget_fact("mam psa"))
        self.assertIsNone(memory.forget_fact("Andrzej lubi żarty", among=memory.facts_about("Maja")))
        self.assertEqual(memory.forget_fact("Maja ma chomika"),
                         "Maja ma chomika o imieniu Pestka.")
        self.assertEqual(memory.facts_about("Maja"), ["Mai ulubiony kolor to fiolet."])

    def test_put_away_is_not_every_sentence(self):
        import commands
        import faces
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]):
            with state.lock:
                state.person = ("Emilka", 0.9, time.time())
            self.assertIsNone(commands._remember("Położyłam Maję do łóżka"))
            self.assertIsNone(commands._remember("Odłożyłam to na później"))
            self.assertEqual(commands._remember("Położyłam klucze na lodówce"),
                             "Emilka położyła klucze na lodówce")
            with state.lock:
                state.person = None

    def test_where_is_thing(self):
        memory._save({"facts": ["Andrzej lubi żarty.", "Klucze są w szufladzie w kuchni.",
                                "Andrzej mówi: „mój paszport leży w szafie”."],
                      "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertEqual(memory.where_is_thing("Gdzie są klucze?"),
                         "W szufladzie w kuchni — tak mi mówiliście.")
        self.assertEqual(memory.where_is_thing("Gdzie jest mój paszport?"),
                         "W szafie — tak mi mówiliście.")
        self.assertIsNone(memory.where_is_thing("Gdzie jest Polska?"))
        self.assertIsNone(memory.where_is_thing("Gdzie są żarty?"))     # no place in it
        # "odłożyłam … do …" kept by commands._remember; a hidden present never told
        memory._save({"facts": ["Emilka odłożyła paszporty do niebieskiego segregatora",
                                "Andrzej schował prezent w szafie"],
                      "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertEqual(memory.where_is_thing("Gdzie są paszporty?"),
                         "Emilka odłożyła paszporty do niebieskiego segregatora.")
        self.assertIsNone(memory.where_is_thing("Gdzie jest prezent?"))
        memory._save({"facts": ["Andrzej zaparkował na poziomie minus dwa, miejsce 47"],
                      "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertEqual(memory.where_is_thing("Gdzie zaparkowałem?"),
                         "Andrzej zaparkował na poziomie minus dwa, miejsce 47.")
        self.assertEqual(memory.where_is_thing("Gdzie stoi nasz samochód?"),
                         "Andrzej zaparkował na poziomie minus dwa, miejsce 47.")
        memory._save(memory._empty())                  # other tests expect no notes

    def test_forget(self):
        memory._save({"facts": ["Ma kota."], "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertFalse(memory.check_forget("Zapomnij o tym, nieważne"))
        self.assertFalse(memory.check_forget("Luna, nie zapomnij o mnie jutro"))
        self.assertIn("Na pewno", memory.check_forget("Luna, zapomnij wszystko"))
        self.assertEqual(memory._load()["facts"], ["Ma kota."])     # not yet
        self.assertEqual(memory.check_forget("Nie, jednak nie"),
                         "Dobrze, niczego nie zapominam.")
        self.assertEqual(memory._load()["facts"], ["Ma kota."])
        memory.check_forget("Zapomnij wszystko")
        self.assertFalse(memory.check_forget("tak", now=time.time() + 60))  # too late
        self.assertEqual(memory._load()["facts"], ["Ma kota."])
        memory.check_forget("Zapomnij wszystko")
        self.assertTrue(memory.check_forget("Tak, zapomnij"))
        self.assertEqual(memory._load()["facts"], [])


class PolishTest(unittest.TestCase):

    def test_offer_only(self):
        from polish import offer_only
        self.assertTrue(offer_only("Może dopiszmy świeże warzywa i owoce?"))
        self.assertTrue(offer_only("Może chleb i masło? Chcesz, żebym dodała je do listy?"))
        self.assertFalse(offer_only("Dodałam mleko. Coś jeszcze?"))
        self.assertFalse(offer_only("Jasne, minutnik na 10 minut."))
        self.assertFalse(offer_only("Włączam Trójkę."))
        self.assertTrue(offer_only("Jasne — do jedzenia dorzuciłabym jeszcze pomidory i ser."))
        self.assertTrue(offer_only("Jasne — dopisałabym na przykład jogurt i jajka."))
        self.assertTrue(offer_only("Jasne — dorzuć jajka, jogurt i pomidory."))
        self.assertTrue(offer_only("Mogę dopisać mleko, jeśli chcesz."))
        self.assertTrue(offer_only("O, dobrze. Jeśli chcesz, mogę to od razu skreślić z listy."))
        self.assertFalse(offer_only("Jasne, dopisuję jajka. Można też dorzucić ser."))

    def test_feminize(self):
        from polish import feminize as f
        self.assertEqual(f("Zrobiłem to, czytałem i byłem gotowy."),
                         "Zrobiłam to, czytałam i byłam gotowa.")
        self.assertEqual(f("Chcesz, żebym zaczął od którejś z nich?"),
                         "Chcesz, żebym zaczęła od którejś z nich?")
        self.assertEqual(f("Mógłbym pomóc, żebym ci przyniósł."),
                         "Mogłabym pomóc, żebym ci przyniosła.")
        for keep in ("Można ją posmarować masłem.", "Pod stołem jest kot.",
                     "Myję ręce mydłem.", "Jadłam z kołem ratunkowym."):
            self.assertEqual(f(keep), keep)


class EchoTest(unittest.TestCase):

    def test_tail_only(self):
        import echo
        last = ("Na obiad może coś prostego i smacznego, na przykład makaron z sosem "
                "pomidorowym albo kurczak z warzywami. Chcesz, żebym pomogła z przepisem?")
        self.assertFalse(echo.is_echo("kurczak z warzywami.", last))     # an answer
        # after a question only a long word-for-word copy of the tail is echo
        self.assertTrue(echo.is_echo("żebym pomogła z przepisem?", last))
        self.assertFalse(echo.is_echo("z przepisem", last))
        self.assertFalse(echo.is_echo("Tak, poproszę przepis", last))
        self.assertFalse(echo.is_echo("", last))
        q = ("Spokojnie, Andrzeju — czuwam sobie i mam oko na wszystko. A ty jak tam, "
             "po pracy czy już po trybie kanapowym?")
        self.assertFalse(echo.is_echo("Wy, trybie kanapowym.", q))       # 7 Oct 20:59
        self.assertFalse(echo.is_echo("po trybie kanapowym", q))
        # not a question: the tail rule as before
        s = "Włączam radio. Miłego słuchania, Andrzeju."
        self.assertTrue(echo.is_echo("miłego słuchania andrzeju", s))


class ListsTest(unittest.TestCase):

    def setUp(self):
        lists._lists = {}
        lists._undo = None

    def test_local_add(self):
        self.assertEqual(lists.local_add("Dopisz mleko i chleb do listy zakupów"),
                         "Dopisałam: mleko, chleb.")
        self.assertEqual(lists.get("zakupy"), ["mleko", "chleb"])
        self.assertEqual(lists.local_add("dodaj umyć auto do listy rzeczy do zrobienia"),
                         "Dopisałam: umyć auto.")
        self.assertEqual(lists.local_add("Dopisz mleko do listy"), "To już jest na liście.")
        self.assertIsNone(lists.local_add("Dopisz, że jutro przyjdzie babcia"))

    def test_read_answer(self):
        self.assertEqual(lists.read_answer("Co mam na liście zakupów?"),
                         "Na liście zakupów nic nie ma.")
        self.act("list_add", "mleko")
        self.act("list_add", "chleb")
        self.act("list_add", "umyć auto", "rzeczy do zrobienia")
        self.assertEqual(lists.read_answer("Co mam na liście zakupów?"),
                         "Na liście zakupów (2): mleko, chleb.")
        self.assertEqual(lists.read_answer("Co mam jeszcze kupić?"),
                         "Na liście zakupów (2): mleko, chleb.")
        self.assertEqual(lists.read_answer("Co mam zrobić?"),
                         "Na liście „rzeczy do zrobienia” (1): umyć auto.")
        self.assertIsNone(lists.read_answer("Co mam dziś na obiad?"))

    def test_list_owner(self):
        from shared_state import state
        with state.lock:
            state.person = ("Andrzej", 0.9, time.time())
        try:
            self.act("list_add", "umyć auto", "do zrobienia")
            self.act("list_add", "mleko")
        finally:
            with state.lock:
                state.person = None
        own = lists.owners()
        self.assertEqual(own.get("do zrobienia"), "Andrzej")
        self.assertNotIn("zakupy", own)                    # shopping: everyone's
        self.assertIn("do zrobienia (started by Andrzej)", lists.prompt_block())
        with state.lock:                                   # Emilka asks (13 Oct)
            state.person = ("Emilka", 0.9, time.time())
        try:
            self.assertIn("do zrobienia (ANDRZEJ'S list — NOT Emilka's)",
                          lists.prompt_block())
            self.assertNotIn("zakupy (", lists.prompt_block())
        finally:
            with state.lock:
                state.person = None
        self.act("list_clear", "", "do zrobienia")
        self.assertNotIn("do zrobienia", lists.owners())

    def test_restore(self):
        self.assertIsNone(lists.restore("Kup chleb"))
        self.assertIn("Nie mam czego", lists.restore("Przywróć listę"))
        self.act("list_add", "mleko")
        self.act("list_add", "chleb")
        self.act("list_clear")
        self.act("list_add", "masło")
        self.assertEqual(lists.restore("Luna, przywróć listę zakupów"),
                         "Przywróciłam na listę zakupy: mleko, chleb.")
        self.assertEqual(lists.get("zakupy"), ["masło", "mleko", "chleb"])
        self.act("list_remove", "mleko")
        self.assertIn("Nie mam czego",
                      lists.restore("cofnij skreślenie", now=time.time() + lists.UNDO_SECS + 60))

    def test_bare_undo_right_after(self):
        # 11 Oct sweep: "Usuń chleb" → "Cofnij" → "potrzebuję wiedzieć którą"
        self.assertIsNone(lists.restore("Cofnij"))                 # nothing removed
        self.act("list_add", "chleb")
        self.act("list_remove", "chleb")
        self.assertIsNone(lists.restore("Cofnij", now=time.time() + 600))   # too late
        self.assertEqual(lists.restore("Cofnij"), "Przywróciłam na listę zakupy: chleb.")

    def act(self, kind, label="", lst="zakupy"):
        return lists.apply([{"type": kind, "label": label, "list": lst,
                             "seconds": 0, "at": "", "repeat": "none"}])

    def test_add_no_duplicates_remove_clear(self):
        self.act("list_add", "mleko")
        self.act("list_add", "Mleko")
        self.act("list_add", "chleb")
        self.act("list_add", "zadzwonić do Ani", "do zrobienia")
        self.assertEqual(lists.get("zakupy"), ["mleko", "chleb"])
        self.act("list_remove", "chleb")
        self.assertEqual(lists.get("zakupy"), ["mleko"])
        self.act("list_clear")
        self.assertEqual(lists.get(), {"do zrobienia": ["zadzwonić do Ani"]})

    def test_timer_actions_are_not_list_actions(self):
        self.assertEqual(lists.apply([{"type": "timer", "label": "makaron", "list": "",
                                       "seconds": 60, "at": "", "repeat": "none"}]), [])

    def test_find_and_prompt(self):
        self.act("list_add", "jajka")
        self.act("list_add", "pranie", "do zrobienia")
        self.assertEqual(lists.find("Pokaż listę zakupów"), "zakupy")
        self.assertEqual(lists.find("pokaż listę do zrobienia"), "do zrobienia")
        self.assertIn("zakupy: jajka", lists.prompt_block())

    def test_find_a_named_list_that_is_not_there(self):
        # 16 Oct 13:59: the to-do list was gone — the shopping list came up
        self.act("list_add", "jajka")
        for said in ("Pokaż mi listę rzeczy do zrobienia.", "pokaż listę zadań",
                     "pokaż listę to do"):
            self.assertEqual(lists.find(said), "do zrobienia", said)
        self.assertEqual(lists.find("pokaż listę prezentów"), "prezentów")
        for said in ("pokaż listę", "Pokaż mi listę, proszę.", "pokaż listę zakupów"):
            self.assertEqual(lists.find(said), "zakupy", said)
        self.assertEqual(lists.empty_answer("prezentów"),
                         "Nie mam listy „prezentów”. Mam listę: zakupów.")
        self.assertEqual(lists.empty_answer("do zrobienia"),
                         "Lista do zrobienia jest pusta. Mam listę: zakupów.")


class ClockTest(unittest.TestCase):

    def test_greeting_before_the_question(self):
        import clock
        self.assertTrue(clock.answer("Cześć, która godzina?").startswith("Jest "))
        self.assertTrue(clock.answer("Dzień dobry, jaki dziś dzień?").startswith("Dziś jest"))
        self.assertIn("W Tokio", clock.answer("Która godzina w Tokio?"))   # world time

    def test_spoken_time_and_date(self):
        import clock
        dt = datetime.datetime
        self.assertEqual(clock.spoken_time(dt(2026, 10, 4, 15, 26)), "Jest piętnasta dwadzieścia sześć.")
        self.assertEqual(clock.spoken_time(dt(2026, 10, 4, 7, 5)), "Jest siódma pięć.")
        self.assertEqual(clock.spoken_time(dt(2026, 10, 4, 21, 0)), "Jest dwudziesta pierwsza.")
        self.assertEqual(clock.spoken_time(dt(2026, 10, 4, 0, 0)), "Jest północ.")
        self.assertEqual(clock.spoken_time(dt(2026, 10, 4, 23, 59)),
                         "Jest dwudziesta trzecia pięćdziesiąt dziewięć.")
        self.assertEqual(clock.spoken_date(dt(2026, 10, 4)), "Dziś jest niedziela, czwarty października.")
        self.assertEqual(clock.spoken_date(dt(2026, 12, 31)), "Dziś jest czwartek, trzydziesty pierwszy grudnia.")
        self.assertEqual(clock.spoken_date(dt(2026, 5, 22)), "Dziś jest piątek, dwudziesty drugi maja.")

    def test_only_bare_questions(self):
        import clock
        self.assertIsNotNone(clock.answer("Luna, która jest godzina?"))
        self.assertIsNotNone(clock.answer("Powiedz mi, jaki dziś dzień"))
        self.assertIn("W Tokio", clock.answer("Która godzina jest teraz w Tokio?"))
        self.assertIsNone(clock.answer("O której godzinie zaczyna się mecz?"))


class GamesTest(unittest.TestCase):

    def test_trigger(self):
        self.assertTrue(games.is_trigger("Zagrajmy w kamień, papier, nożyce!"))
        self.assertTrue(games.is_trigger("papier nożyce kamień"))
        self.assertFalse(games.is_trigger("Mam w kieszeni kamień."))

    def test_rematch_only_right_after_a_match(self):
        games._rematch_until = 0
        self.assertFalse(games.is_rematch("tak"))
        games._rematch_until = time.time() + 10
        self.assertTrue(games.is_rematch("Tak, jeszcze raz!"))
        self.assertFalse(games.is_rematch("tak, ale najpierw powiedz mi, która jest godzina"))

    def test_rules(self):
        self.assertEqual(games._verdict("rock", "scissors"), "me")
        self.assertEqual(games._verdict("rock", "paper"), "you")
        self.assertEqual(games._verdict("paper", "paper"), "draw")


class CommandsTest(unittest.TestCase):

    def setUp(self):
        import commands
        self.c = commands
        self.said = []
        self.volume = None
        commands.set_volume = lambda v: setattr(self, "volume", v) or v
        commands.get_volume = lambda: 0.5
        with state.lock:
            state.sleep_mode = False

    def handle(self, text):
        return self.c.handle(text, lambda t, **k: self.said.append(t),
                             lambda n, **k: (self.said.append(f"({n})"), True)[1])

    def test_volume(self):
        self.assertTrue(self.handle("Ustaw głośność na 40%"))
        self.assertAlmostEqual(self.volume, 0.40)
        self.assertTrue(self.handle("Ciszej"))
        self.assertAlmostEqual(self.volume, 0.40)        # 0.5 - 0.1
        self.assertTrue(self.handle("dużo głośniej"))
        self.assertAlmostEqual(self.volume, 0.70)

    def test_long_sentence_goes_to_the_model(self):
        self.assertFalse(self.handle("Czy wiesz, dlaczego w nocy na ulicy jest ciszej niż w dzień?"))

    def test_good_night_and_wake(self):
        self.assertTrue(self.handle("Dobranoc, Luna"))
        self.assertTrue(state.sleep_mode)
        self.assertFalse(self.handle("Dzień dobry!"))     # wakes her, then the model answers
        self.assertFalse(state.sleep_mode)

    def test_goodbye_closes_the_conversation(self):
        with state.lock:
            state.conversation_active = True
        self.assertTrue(self.handle("Pa, Luna!"))
        self.assertFalse(state.conversation_active)
        with state.lock:
            state.conversation_active = True
        self.assertFalse(self.handle("Na razie nie, dzięki"))
        self.assertTrue(state.conversation_active)

    def test_speech_speed(self):
        settings.put("tts_speed", 1.0)
        self.assertTrue(self.handle("Mów wolniej"))
        self.assertAlmostEqual(settings.get("tts_speed"), 0.9)
        self.assertTrue(self.handle("mów normalnie"))
        from config import OPENAI_TTS_SPEED
        self.assertAlmostEqual(settings.get("tts_speed"), OPENAI_TTS_SPEED)   # the house rate


class CalcTest(unittest.TestCase):

    def test_arithmetic(self):
        import calc
        cases = {
            "Ile to jest 17 razy 23?": "17 razy 23 to 391.",
            "ile to jest dwanaście razy siedem": "12 razy 7 to 84.",
            "piętnaście procent z osiemdziesięciu": "15 procent z 80 to 12.",
            "Ile to jest 23 procent VAT od 2400 złotych?": "23 procent z 2400 to 552.",
            "Ile to 15% napiwku od 180 zł?": "15 procent z 180 to 27.",
            "pierwiastek z 144": "Pierwiastek z 144 to 12.",
            "100 podzielić przez 8": "100 przez 8 to 12,5.",
            "2+2*2": "2 plus 2 razy 2 to 6.",
            "dwa do potęgi dziesięć": "2 do potęgi 10 to 1024.",
            "minus pięć razy dwa": "Minus 5 razy 2 to minus 10.",
            "10 przez 0": "Przez zero nie da się dzielić.",
            "1 000 plus 1": "1000 plus 1 to 1001.",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(calc.arithmetic(text), want)
        for text in ("ile to jest 5", "ile razy dziennie podlewać kwiatki?",
                     "plus minus", "dwa razy w tygodniu"):
            with self.subTest(text=text):
                self.assertIsNone(calc.arithmetic(text))

    def test_days_until(self):
        import calc
        sunday = datetime.date(2026, 10, 4)
        self.assertEqual(calc.days_until("Ile dni do Wigilii?", sunday),
                         "Do Wigilii zostało 81 dni, czyli około 12 tygodni.")
        self.assertEqual(calc.days_until("ile do piątku", sunday), "Do piątku zostało 5 dni.")
        self.assertEqual(calc.days_until("ile jeszcze do weekendu", sunday),
                         "Przecież już jest weekend!")
        self.assertEqual(calc.days_until("ile dni do 6 października", sunday),
                         "Do 6 października zostały 2 dni.")
        self.assertEqual(calc.days_until("ile dni do piątego października", sunday),
                         "To już jutro!")
        self.assertEqual(calc.days_until("ile dni do 1 października", sunday)[:22],
                         "Do 1 października zost")              # next year
        self.assertIsNone(calc.days_until("ile kosztuje bilet do Krakowa", sunday))
        self.assertIsNone(calc.days_until("ile dni do moich urodzin", sunday))
        self.assertEqual(calc._easter(2027), datetime.date(2027, 3, 28))
        self.assertEqual(calc._easter(2026), datetime.date(2026, 4, 5))

    def test_time_until(self):
        import calc
        now = datetime.datetime(2026, 10, 5, 15, 15)
        self.assertEqual(calc.time_until("Ile zostało do siedemnastej?", now),
                         "Do 17:00 została 1 godzina i 45 minut.")
        self.assertEqual(calc.time_until("ile czasu do 17:30", now),
                         "Do 17:30 zostały 2 godziny i 15 minut.")
        self.assertEqual(calc.time_until("ile jeszcze do ósmej?", now),
                         "Do 20:00 zostały 4 godziny i 45 minut.")
        self.assertEqual(calc.time_until("ile do 15:20?", now), "Do 15:20 zostało 5 minut.")
        self.assertIsNone(calc.time_until("ile dni do Wigilii?", now))
        self.assertIsNone(calc.time_until("ile kosztuje bilet do Krakowa?", now))
        # 13 Oct probe: "do północy" was noon
        eve = datetime.datetime(2026, 10, 13, 19, 20)
        self.assertEqual(calc.time_until("Ile minut do północy?", eve),
                         "Do północy zostały 4 godziny i 40 minut.")
        self.assertEqual(calc.time_until("ile zostało do dwunastej w nocy", eve),
                         "Do północy zostały 4 godziny i 40 minut.")
        self.assertEqual(calc.time_until("ile do północy?", datetime.datetime(2026, 10, 13, 3, 0)),
                         "Do północy zostało 21 godzin.")
        self.assertEqual(calc.time_until("ile do południa?", datetime.datetime(2026, 10, 13, 9, 0)),
                         "Do 12:00 zostały 3 godziny.")

    def test_goodnight_mentions_the_alarm(self):
        timers._timers.clear()
        self.assertIsNone(timers.goodnight_note())
        due = time.time() + 8 * 3600
        timers._timers.append({"due": due, "label": "", "kind": "alarm", "set": time.time()})
        self.assertTrue(timers.goodnight_note().startswith("Budzik masz na "))
        timers._timers[0]["due"] = time.time() + 30 * 3600     # not tonight
        self.assertIsNone(timers.goodnight_note())
        timers._timers.clear()


class KidsTest(unittest.TestCase):

    def test_quiz_round(self):
        import quiz
        said = []
        say = lambda t, **k: said.append(t)
        with mock.patch.object(quiz, "QUESTIONS", 3):
            quiz.start("mul", "przepytaj mnie z tabliczki", say, lambda n: None)
            self.assertTrue(quiz.active())
            quiz.answer(str(quiz._q["answer"]), say, lambda n: None)          # right
            wrong = quiz._q["answer"] + 1
            quiz.answer(f"to będzie {wrong}", say, lambda n: None)          # wrong once
            self.assertIn("Spróbuj jeszcze raz", said[-1])
            quiz.answer("nie wiem", say, lambda n: None)                    # gives up
            quiz.answer(str(quiz._q["answer"]), say, lambda n: None)          # right
        self.assertFalse(quiz.active())
        self.assertIn("2 na 3", said[-1])

    def test_words_and_guessing(self):
        import quiz
        say = lambda t, **k: None
        quiz.start("words", "słówka", say, lambda n: None)
        en = quiz._q["answer"][0]
        self.assertTrue(quiz.answer(f"It's {en.capitalize()}!", say, lambda n: None))
        self.assertEqual(quiz._q["score"], 1)
        self.assertFalse(quiz.answer("Opowiedz mi lepiej bajkę o smoku i rycerzu",
                                     say, lambda n: None))
        quiz.start("guess", "zgadywanka", say, lambda n: None)
        lo, hi, tries = 1, 100, 0
        while quiz.active():
            g = (lo + hi) // 2
            secret = quiz._q["secret"]
            quiz.answer(str(g), say, lambda n: None)
            lo, hi = (g + 1, hi) if g < secret else (lo, g - 1)
            tries += 1
        self.assertLessEqual(tries, 7)                     # binary search wins

    def test_riddles(self):
        import quiz
        said = []
        say = lambda t, **k: said.append(t)
        self.assertEqual(quiz.trigger("Zadaj mi zagadkę"), "riddle")
        self.assertIsNone(quiz.trigger("To bardzo zagadkowe"))
        self.assertEqual(quiz.trigger("zagadki z matematyki"), "mix")
        quiz.start("riddle", "zagadka", say, lambda n: None)
        q = quiz._q
        self.assertEqual(q["total"], quiz.RIDDLES)
        quiz.answer("krzesło", say, lambda n: None)                  # wrong → a hint
        self.assertIn("Podpowiedź", said[-1])
        quiz.answer(f"to chyba {q['answer'][-1]}!", say, lambda n: None)   # another form
        self.assertEqual(quiz._q["score"], 1)
        quiz.answer("koniec", say, lambda n: None)
        self.assertFalse(quiz.active())

    def test_dictation(self):
        import quiz
        said = []
        say = lambda t, **k: said.append(t)
        self.assertEqual(quiz.trigger("Zróbmy dyktando"), "dictation")
        self.assertEqual(quiz._traps("żółw"), "przez ó z kreską, przez ż z kropką")
        self.assertEqual(quiz._traps("chmura"), "przez ch")
        quiz.start("dictation", "dyktando", say, lambda n: None)
        q = quiz._q
        word = q["answer"]
        self.assertIn(word, said[-1])
        quiz.answer("chwila", say, lambda n: None)                 # not ready yet
        self.assertIn("gotowe", said[-1])
        with mock.patch.object(quiz, "_read_paper", lambda: word.upper() + "."):
            quiz.answer("Gotowe!", say, lambda n: None)          # right (case, dot)
        self.assertEqual(q["score"], 1)
        wrong = quiz._q["answer"].replace("ó", "u").replace("rz", "ż") + "x"
        with mock.patch.object(quiz, "_read_paper", lambda: wrong):
            quiz.answer("już", say, lambda n: None)              # wrong → what I see
            self.assertIn(f"„{wrong}”", said[-1])
            quiz.answer("gotowe", say, lambda n: None)           # wrong again → spelled
        self.assertIn("piszemy tak", said[-2] if "Napisz" in said[-1] else said[-1])
        with mock.patch.object(quiz, "_read_paper", lambda: None):
            quiz.answer("gotowe", say, lambda n: None)           # nothing readable
        self.assertIn("Nie widzę dobrze napisu", said[-1])
        # a question with "jest" in it is not "it's written" (9 Oct school sweep)
        self.assertTrue(quiz._ready(["patrz", "jest"]))
        with mock.patch.object(quiz, "_read_paper", lambda: self.fail("read the paper")):
            self.assertFalse(quiz.answer("Ile to jest 36 podzielić przez 4?", say, lambda n: None))
        self.assertIsNone(quiz._q)                                # the dictation gave way
        quiz.start("riddle", "zagadka", say, lambda n: None)      # another game asked for
        self.assertFalse(quiz.answer("Zagrajmy w dwadzieścia pytań", say, lambda n: None))
        self.assertIsNone(quiz._q)

    def test_practice_what_was_wrong(self):
        import mood
        import quiz
        mood.PATH = os.path.join(TMP, "day-practice.json")
        mood.DIARY = os.path.join(TMP, "diary-practice.json")
        mood._day = None
        mood.note_game("Maja", "dictation", 3, 5, ["rzeka"])
        mood.note_game("Maja", "mul", 4, 5, ["7 × 8 = 56"])
        with state.lock:
            state.person = ("Maja", 0.9, time.time())
        self.assertEqual(quiz._past_misses("dyktando"), ["rzeka"])
        with mock.patch.object(quiz, "REPEAT_MISSES", 1.0):
            q = {"kind": "dictation", "seen": set()}
            quiz._new_question(q)
            self.assertEqual(q["answer"], "rzeka")
            q = {"kind": "mul", "seen": set(), "limit": 100}
            quiz._new_question(q)
            self.assertEqual(q["answer"], 56)
        with state.lock:
            state.person = None
        self.assertEqual(quiz._past_misses("dyktando"), [])       # someone else

    def test_stars(self):
        import quiz
        settings.put("stars", {})
        self.assertIsNone(quiz.award_star())                     # nobody known
        with state.lock:
            state.person = ("Maja", 0.9, time.time())
        self.assertEqual(quiz.award_star(), 1)
        self.assertEqual(quiz.award_star(), 2)
        with state.lock:
            self.assertEqual(state.overlay[0], "stars")
            state.person, state.overlay = None, None
        self.assertEqual(quiz._stars_pl(1), "gwiazdkę")
        self.assertEqual(quiz._stars_pl(3), "gwiazdki")
        self.assertEqual(quiz._stars_pl(12), "gwiazdek")

    def test_clock_game(self):
        import clockgame
        import quiz
        cases = {"siódma trzydzieści": (7, 30), "wpół do ósmej": (7, 30),
                 "kwadrans po siódmej": (7, 15), "za piętnaście ósma": (7, 45),
                 "za kwadrans ósma": (7, 45), "dziesięć po siódmej": (7, 10),
                 "dwadzieścia przed ósmą": (7, 40), "7:30": (7, 30), "siódma": (7, 0),
                 "dziewiętnasta trzydzieści": (19, 30), "chyba siódma zero pięć": (7, 5),
                 "dwudziesta pierwsza piętnaście": (21, 15), "wpół do dwunastej": (11, 30)}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(clockgame.parse(text), want)
        self.assertIsNone(clockgame.parse("nie wiem"))
        self.assertTrue(clockgame.same((19, 30), (7, 30)))
        self.assertEqual(clockgame.say(7, 30), "wpół do ósmej, czyli siódma trzydzieści")
        self.assertEqual(quiz.trigger("Pobawmy się w zegar"), "clock")
        self.assertIsNone(quiz.trigger("Pokaż zegar"))
        said = []
        quiz.start("clock", "zegar", lambda t, **k: said.append(t), lambda n: None)
        h, m = quiz._q["answer"]
        quiz.answer(f"{h}:{m:02d}", lambda t, **k: said.append(t), lambda n: None)
        self.assertEqual(quiz._q["score"], 1)
        quiz.answer("koniec", lambda t, **k: said.append(t), lambda n: None)

    def test_capitals_and_checked_sums(self):
        import quiz
        import quizdata
        self.assertEqual(quizdata._eval("3*4+2"), 14)
        self.assertEqual(quizdata._eval("20 : 4"), 5)
        with self.assertRaises(ValueError):
            quizdata._eval("__import__('os')")
        self.assertEqual(quiz.trigger("Quiz ze stolic"), "capitals")
        self.assertEqual(quiz.trigger("Przepytaj mnie z zadań z treścią"), "story")
        said = []
        quiz.start("capitals", "stolice", lambda t, **k: said.append(t), lambda n: None)
        right = quiz._q["answer"][0]
        quiz.answer(f"To {right.capitalize()}!", lambda t, **k: said.append(t), lambda n: None)
        self.assertEqual(quiz._q["score"], 1)
        quiz.answer("koniec", lambda t, **k: said.append(t), lambda n: None)

    def test_every_right_answer_counts(self):
        """All the quiz data, not one random item: a right answer in every
        accepted form must count (a random capital once didn't)."""
        import quiz
        import quizdata
        import riddles
        for question, accept in quizdata.CAPITALS:
            for a in accept:
                with self.subTest(capital=a):
                    q = {"kind": "capitals", "answer": [x.lower() for x in accept]}
                    self.assertTrue(quiz._check(q, f"To {a}!"))
        for riddle, accept, hint in riddles.RIDDLES:
            for a in accept:
                with self.subTest(riddle=a):
                    q = {"kind": "riddle", "answer": accept}
                    self.assertTrue(quiz._check(q, f"to chyba {a}"))
        for pl, en in quiz.WORDS:
            for a in en:
                with self.subTest(word=a):
                    q = {"kind": "words", "answer": en}
                    self.assertTrue(quiz._check(q, f"It's {a}."))
        for w in quiz.DICTATION:
            with self.subTest(dictation=w):
                self.assertTrue(quiz._same_word(w.upper() + "!", w))

    def test_no_cloud_no_crash(self):
        import quiz
        import quizdata
        said = []

        def offline(seen):
            raise RuntimeError("no network")
        with mock.patch.object(quizdata, "word_problem", offline):
            quiz.start("story", "zadania z treścią", lambda t, **k: said.append(t),
                       lambda n: None)
        self.assertIn("nie mam internetu", said[-1])
        self.assertFalse(quiz.active())

    def test_quiz_before_a_test(self):
        import quiz
        import memory
        with mock.patch.object(memory, "_load", lambda: {"facts": [
                "Maja ma w poniedziałek sprawdzian z angielskiego"]}):
            self.assertEqual(quiz.trigger("Przepytaj mnie przed sprawdzianem"), "words")
        with mock.patch.object(memory, "_load", lambda: {"facts": []}):
            self.assertEqual(quiz.trigger("Przepytaj mnie przed sprawdzianem"), "mix")
            self.assertIsNone(quiz.trigger("Jutro mam sprawdzian"))

    def test_quiz_waits_while_someone_else_talks(self):
        import quiz
        with state.lock:
            state.person = ("Maja", 0.9, time.time())
        quiz.start("mul", "tabliczka", lambda t, **k: None, lambda n: None)
        with state.lock:
            state.person = ("Emilka", 0.9, time.time())
        self.assertFalse(quiz.answer("Ile minut piec sernik w piekarniku?",
                                     lambda t, **k: None, lambda n: None))
        self.assertTrue(quiz.active())                       # Maja's quiz goes on
        with state.lock:
            state.person = None
        quiz.answer("koniec", lambda t, **k: None, lambda n: None)

    def test_quiz_ends_on_unrelated_talk(self):
        import quiz
        quiz.start("add", "quiz z dodawania do 20", lambda t, **k: None, lambda n: None)
        self.assertEqual(quiz._q["limit"], 20)
        self.assertFalse(quiz.answer("jaka jest pogoda?", lambda t, **k: None, lambda n: None))
        self.assertFalse(quiz.active())

    def test_routine_walks_a_list(self):
        import kids
        lists.apply([{"type": "list_add", "label": "umyj zęby", "list": "poranek"},
                     {"type": "list_add", "label": "ubierz się", "list": "poranek"}])
        said = []
        say = lambda t, **k: said.append(t)
        self.assertEqual(kids.routine_name("Zacznij poranek"), "poranek")
        self.assertEqual(kids.routine_name("włącz rutynę poranną"), "poranek")
        self.assertIsNone(kids.routine_name("włącz lampkę"))
        kids.start_routine("poranek", say)
        self.assertIn("umyj zęby", said[-1])
        self.assertTrue(kids.routine_answer("Gotowe!", say, lambda n: None))
        self.assertIn("ubierz się", said[-1])
        self.assertTrue(kids.routine_answer("już", say, lambda n: None))
        self.assertFalse(kids.routine_active())
        self.assertEqual(lists.get("poranek"), ["umyj zęby", "ubierz się"])   # kept
        lists.apply([{"type": "list_clear", "list": "poranek"}])
        # no "wieczór" list: the default steps; at the end, the best bit of the day
        kids.start_routine("wieczór", say)
        self.assertIn("Ułożyłam", said[-2])
        # reluctance, "how many left" and something else keep it going (9 Oct probe)
        self.assertTrue(kids.routine_answer("Nie chce mi się", say, lambda n: None))
        self.assertIn(kids.DEFAULT_STEPS["wieczór"][0], said[-1])
        self.assertTrue(kids.routine_answer("Ile jeszcze kroków?", say, lambda n: None))
        self.assertIn(f"{len(kids.DEFAULT_STEPS['wieczór'])}", said[-1])
        self.assertFalse(kids.routine_answer("Opowiedz bajkę o smoku", say, lambda n: None))
        self.assertTrue(kids.routine_active())
        for _ in kids.DEFAULT_STEPS["wieczór"]:
            kids.routine_answer("Gotowe", say, lambda n: None)
        self.assertIn("najfajniejsze" if "najfajniejsze" in said[-1] else "najlepsze", said[-1])
        self.assertTrue(state.conversation_active)
        lists.apply([{"type": "list_clear", "list": "wieczór"}])
        # a Saturday morning: no "spakuj plecak" (9 Oct)
        from datetime import date
        self.assertFalse(kids.school_day(date(2026, 10, 10)))     # Saturday
        self.assertTrue(kids.school_day(date(2026, 10, 12)))      # Monday
        with mock.patch.object(kids, "school_day", lambda: False):
            kids.start_routine("poranek", say)
            self.assertNotIn("spakuj plecak", kids._routine["steps"])
        self.assertIn("spakuj plecak", lists.get("poranek"))      # the list is kept
        kids._routine = None
        lists.apply([{"type": "list_clear", "list": "poranek"}])

    def test_usage_per_day(self):
        import health
        health._day.clear()
        health._day.update({"chat": 3, "stt": 5})
        health.flush_usage("2026-10-01")
        health._day.update({"chat": 2})
        health.flush_usage("2026-10-01")
        self.assertEqual(health.usage_line("2026-10-01"), "chat 5, stt 5")
        self.assertEqual(health.usage_line("2026-09-01"), "brak")

    def test_probably_family(self):
        import faces
        faces._seen = {}
        faces._near[:] = [None, 0.0, 0.0]
        self.assertFalse(faces.probably_family(1000.0))
        faces._near[:] = ["Andrzej", 0.36, 995.0]
        self.assertTrue(faces.probably_family(1000.0))       # a near miss just now
        faces._near[:] = ["Andrzej", 0.20, 995.0]
        self.assertFalse(faces.probably_family(1000.0))      # too far to say
        faces._seen = {"Maja": 900.0}
        self.assertTrue(faces.probably_family(1000.0))       # Maja was here
        faces._seen = {}

    def test_where_is(self):
        import faces
        faces._seen = {}
        t0 = 1_760_000_000.0
        self.assertIn("jeszcze nie była", faces.where_is("Maja", t0))
        faces.saw(["Maja", "?"], t0)
        self.assertEqual(faces.where_is("Maja", t0 + 5), "Maja jest tutaj, przy mnie!")
        self.assertEqual(faces.where_is("Maja", t0 + 12 * 60), "Maja była tu 12 minut temu.")
        self.assertEqual(faces.where_is("Maja", t0 + 3 * 60), "Maja była tu 3 minuty temu.")
        faces.saw(["Andrzej"], t0)
        self.assertIn("Andrzej był tu", faces.where_is("Andrzej", t0 + 7200))
        self.assertNotIn("?", faces._seen)

    def test_people_talking(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        s._side.clear()
        for t in (1000, 1030, 1060):
            s.note_side_speech(t)
        self.assertFalse(s.people_talking(1070))
        s.note_side_speech(1065)
        self.assertTrue(s.people_talking(1070))
        self.assertFalse(s.people_talking(1300))           # two minutes later: quiet
        s._side.clear()

    def test_star_goes_to_the_child_in_view(self):
        import quiz, faces
        from shared_state import state
        old = (state.person, state.others, faces.notes)
        try:
            faces.notes = lambda: {"Maja": "dziecko, 8 lat", "Andrzej": "tata"}
            state.person = ("Andrzej", 0.8)
            state.others = (["Maja"], 1000.0)
            self.assertEqual(quiz._star_for(1001.0), "Maja")
            state.others = (["Maja"], 0.0)                   # seen long ago
            self.assertEqual(quiz._star_for(1001.0), "Andrzej")
            state.others = ([], 1000.0)
            self.assertEqual(quiz._star_for(1001.0), "Andrzej")
            state.person = ("Maja", 0.5)
            state.others = (["Andrzej"], 1000.0)
            self.assertEqual(quiz._star_for(1001.0), "Maja")
        finally:
            state.person, state.others, faces.notes = old

    def test_translator_mode_vs_one_sentence(self):
        import commands
        self.assertEqual(commands._translator_language("włącz tryb tłumacza na angielski"),
                         ("English", "angielski"))
        self.assertEqual(commands._translator_language("przetłumacz wszystko na niemiecki")[0],
                         "German")
        self.assertIsNone(commands._translator_language(
            "przetłumacz na niemiecki: gdzie jest dworzec?"))
        self.assertIsNone(commands._translator_language("przetłumacz na angielski dzień dobry"))

    def test_spoken_numbers(self):
        import polish
        self.assertEqual(polish.number_words(7006652),
                         "siedem milionów sześć tysięcy sześćset pięćdziesiąt dwa")
        self.assertEqual(polish.number_words(21000), "dwadzieścia jeden tysięcy")
        self.assertEqual(polish.number_words(1001), "tysiąc jeden")
        # 9 Oct builder answers
        self.assertIn("GPT pięć kropka cztery mini", polish.spoken_numbers("gpt-5.4-mini"))
        self.assertEqual(polish.spoken_numbers("IP 192.168.3.43."),
                         "IP sto dziewięćdziesiąt dwa kropka sto sześćdziesiąt osiem kropka "
                         "trzy kropka czterdzieści trzy.")
        self.assertIn("poziomie minus 2", polish.spoken_numbers("na poziomie -2, miejsce 47"))
        self.assertIn("od 8 -14 stopni", polish.spoken_numbers("od 8 -14 stopni"))   # a range
        self.assertEqual(polish.spoken_numbers("ziemniaki — 2 kg, masło — 500 g, 1 l"),
                         "ziemniaki — 2 kilogramy, masło — 500 gramów, 1 litr")
        s = polish.spoken_numbers("to 86400. Godzina 12:30, rok 2026, 3,14159, tel 600123456.")
        self.assertIn("osiemdziesiąt sześć tysięcy czterysta.", s)
        self.assertIn("tysiąc dwieście trzydzieści cztery", polish.spoken_numbers("Liczba 1234."))
        self.assertIn("Godzina dwunasta trzydzieści", s)
        self.assertEqual(polish.spoken_numbers("Spotkanie 15.11 o 9:00."),
                         "Spotkanie piętnastego listopada o dziewiątej.")
        self.assertEqual(polish.spoken_numbers("Dziś 22°C."), "Dziś dwadzieścia dwa stopnie.")
        self.assertEqual(polish.spoken_numbers("Wynik 2:1"), "Wynik 2:1")
        self.assertEqual(polish.spoken_numbers("Dodaj 1/2 szklanki i ¼ łyżeczki."),
                         "Dodaj pół szklanki i ćwierć łyżeczki.")
        for keep in ("2026", "3,14159", "600123456"):
            self.assertIn(keep, s)

    def test_thread_only_for_its_person(self):
        import memory
        from shared_state import state
        from unittest import mock
        mem = {"facts": ["x"], "episodes": [], "_wiped_at": 0,
               "threads": [{"question": "Jak było u dentysty?", "due": "2000-01-01",
                            "who": "Andrzej", "asked": 0}]}
        old = (state.person, list(memory._session))
        try:
            memory._session.clear()
            with mock.patch.object(memory, "_load", lambda: mem), \
                    mock.patch.object(memory, "_save", lambda m: None):
                state.person = ("Maja", 0.7)
                self.assertNotIn("u dentysty", memory.prompt_block())
                self.assertEqual(mem["threads"][0]["asked"], 0)      # not used up
                state.person = ("Andrzej", 0.9)
                self.assertIn("u dentysty", memory.prompt_block())
                self.assertEqual(mem["threads"][0]["asked"], 1)
        finally:
            state.person = old[0]
            memory._session[:] = old[1]

    def test_leaving_and_umbrella(self):
        import commands, weather, time
        for t in ("wychodzę do pracy", "no to lecę do szkoły", "wychodzę już, pa", "idziemy na spacer",
                  "wychodzę", "dzięki, idę na trening, pa", "dobra, wychodzę"):
            self.assertTrue(commands._LEAVING.match(t), t)
        for t in ("wychodzę z siebie", "idę spać", "jadę jutro do babci na tydzień"):
            self.assertFalse(commands._LEAVING.match(t), t)
        old = dict(weather._today)
        try:
            today = time.strftime("%Y-%m-%d")
            weather._today.clear(); weather._today.update(rain=80, tmax=14, date=today)
            self.assertIn("parasol", weather.umbrella_note())
            weather._today.update(rain=10, tmax=2)
            self.assertIn("ciepło", weather.umbrella_note())
            weather._today.update(rain=10, tmax=18)
            self.assertIsNone(weather.umbrella_note())
            weather._today.update(rain=90, date="2000-01-01")        # stale: nothing
            self.assertIsNone(weather.umbrella_note())
            # by the hour: only the rain still ahead counts, and it says when
            at14 = time.mktime(time.strptime(today + " 14:05", "%Y-%m-%d %H:%M"))
            weather._today.update(rain=80, tmax=14, date=today,
                                  hours=[(8, 90), (14, 10), (15, 20), (21, 80)])
            self.assertEqual(weather.umbrella_note(at14), "Weź parasol — wieczorem ma padać.")
            weather._today.update(hours=[(8, 90), (14, 10), (21, 20)])  # the morning shower
            self.assertIsNone(weather.umbrella_note(at14))
        finally:
            weather._today.clear(); weather._today.update(old)

    def test_skip_tomorrows_alarm(self):
        import timers, commands
        from datetime import datetime
        now = datetime(2026, 10, 7, 21, 0).timestamp()             # a Wednesday
        old = list(timers._timers)
        save = timers._save
        try:
            timers._save = lambda: None
            timers._timers[:] = [
                {"due": datetime(2026, 10, 8, 6, 30).timestamp(), "label": "", "kind": "alarm",
                 "repeat": "weekdays"},
                {"due": datetime(2026, 10, 8, 9, 0).timestamp(), "label": "", "kind": "alarm",
                 "repeat": "none"}]
            n, nxt = timers.skip_tomorrow(now)
            self.assertEqual(n, 2)
            self.assertEqual(len(timers._timers), 1)                 # the one-off is gone
            self.assertEqual(datetime.fromtimestamp(nxt), datetime(2026, 10, 9, 6, 30))
            for t in ("wyłącz budzik na jutro", "jutro bez budzika", "nie budź mnie jutro"):
                self.assertTrue(commands._SKIP_TOMORROW.search(t), t)
            self.assertFalse(commands._SKIP_TOMORROW.search("wyłącz budzik"))
        finally:
            timers._timers[:] = old
            timers._save = save

    def test_quiz_repeat_hint_and_early_stop(self):
        import quiz
        said = []
        old = quiz._q
        try:
            quiz._q = {"kind": "mul", "card": "4 × 7 = ?", "say": "Ile to jest 4 razy 7?",
                       "answer": 28, "reveal": "4 × 7 = 28", "right": "4 razy 7 to 28.",
                       "score": 1, "total": 5, "n": 3, "tries": 0, "asked": 0}
            self.assertTrue(quiz.answer("Powtórz", said.append, lambda *a: None))
            self.assertEqual(said[-1], "Ile to jest 4 razy 7?")
            self.assertTrue(quiz.answer("Podpowiedz", said.append, lambda *a: None))
            self.assertIn("7 dodane 4 razy", said[-1])
            self.assertNotIn("28", said[-1])
            self.assertTrue(quiz.answer("Koniec", said.append, lambda *a: None))
            self.assertIn("Do tej pory 1 na 2", said[-1])
            self.assertIn("A odpowiedź: 4 razy 7 to 28.", said[-2])     # the open one, told
            self.assertIsNone(quiz._q)
            # plus / minus: tens first, then ones — never the result
            h = quiz._hint_for({"card": "71 − 23 = ?", "kind": "sub"})
            self.assertIn("dziesiątki — 20", h)
            self.assertNotIn("48", h)
            self.assertIn("2 dziesiątki", quiz._hint_for({"card": "40 − 20 = ?", "kind": "sub"}))
        finally:
            quiz._q = old

    def test_follow_ups(self):
        import calc, timers, time
        self.assertEqual(calc.arithmetic("Ile to jest 15 razy 4?"), "15 razy 4 to 60.")
        self.assertEqual(calc.arithmetic("A razy 5?"), "15 razy 5 to 75.")
        old = list(timers._timers)
        try:
            timers._timers[:] = [{"due": time.time() + 600, "label": "", "kind": "timer",
                                  "repeat": "none"}]
            self.assertTrue(timers.left_answer("Ile zostało?").startswith("Zostało"))
            self.assertTrue(timers.running_timer())
            timers._timers[:] = []
            self.assertIsNone(timers.left_answer("Ile zostało?"))   # nothing runs: not that
        finally:
            timers._timers[:] = old

    def test_weather_by_the_hour(self):
        import weather
        from datetime import datetime
        d = {"hourly": {"time": ["2026-10-08T15:00", "2026-10-08T18:00", "2026-10-09T07:00",
                                 "2026-10-09T08:00"],
                        "temperature_2m": [21.2, 18.0, 8.4, 9.0],
                        "precipitation_probability": [18, 55, 0, 0]}}
        line = weather._hours(d, datetime(2026, 10, 8, 14, 5))
        self.assertIn("today 15:00 21°C (rain 18%), 18:00 18°C (rain 55%)", line)
        self.assertIn("tomorrow 07:00 8°C", line)
        self.assertNotIn("08:00", line)

    def test_hourly_and_labels(self):
        import timers
        t = time.mktime((2030, 1, 7, 21, 30, 0, 0, 0, -1))     # far ahead: not "in the past"
        n = time.localtime(timers._next_matching(t, "hourly"))
        self.assertEqual((n.tm_mday, n.tm_hour, n.tm_min), (8, 8, 30))   # the night skipped
        self.assertFalse(timers._locative("wyniesienie"))
        self.assertTrue(timers._locative("wizycie"))

    def test_reminders_answer(self):
        import timers
        from datetime import datetime
        now = datetime(2026, 10, 7, 20, 30).timestamp()
        old = list(timers._timers)
        try:
            timers._timers[:] = [
                {"due": now + 3600, "label": "wyjąć pranie", "kind": "timer", "repeat": "none"},
                {"due": datetime(2026, 10, 8, 8, 0).timestamp(), "label": "śmieci",
                 "kind": "reminder", "repeat": "none"},
                {"due": datetime(2026, 10, 8, 20, 0).timestamp(), "label": "tabletki",
                 "kind": "reminder", "repeat": "daily"},
                {"due": now + 600, "label": "", "kind": "timer", "repeat": "none"},
            ]
            a = timers.reminders_answer("Jakie mam przypomnienia?", now)
            self.assertTrue(a.startswith("Masz przypomnienia: wyjąć pranie — za godzin"), a)
            self.assertIn("śmieci — jutro o ósmej", a)
            self.assertIn("tabletki — codziennie o dwudziestej", a)
            self.assertNotIn("minutnik", a)                     # a bare kitchen timer isn't one
            self.assertIsNone(timers.reminders_answer("Przypomnij mi o praniu", now))
            self.assertIsNotNone(timers.reminders_answer("Ile mam przypomnień?", now))
            timers._timers.append({"due": now + 7200, "label": "tabletce", "kind": "reminder",
                                   "repeat": "none"})
            self.assertIn("o tabletce", timers.reminders_answer("Jakie mam przypomnienia?", now))
            self.assertIn('"o tabletce"', timers.prompt_block())
            # "wyłącz wszystkie przypomnienia": the weekday alarm stays
            timers._timers.append({"due": now + 36000, "label": "", "kind": "alarm",
                                   "repeat": "weekdays"})
            saved = timers._save
            timers._save = lambda: None
            try:
                timers.apply([{"type": "cancel", "label": "wszystkie"}],
                             said="Wyłącz wszystkie przypomnienia")
                self.assertEqual([t["kind"] for t in timers._timers if t["kind"] != "timer"],
                                 ["alarm"])
                timers.apply([{"type": "cancel", "label": "wszystkie budziki"}])
                self.assertFalse([t for t in timers._timers if t["kind"] == "alarm"])
            finally:
                timers._save = saved
            timers._timers[:] = []
            self.assertEqual(timers.reminders_answer("Jakie mam przypomnienia?", now),
                             "Nie masz teraz żadnych przypomnień.")
        finally:
            timers._timers[:] = old

    def test_game_choice_after_offer(self):
        import commands, brain
        old = list(brain._history)
        try:
            brain._history[:] = [{"role": "user", "content": "Pobawimy się?"},
                                 {"role": "assistant", "content": "Jasne! Kółko i krzyżyk, "
                                  "zagadki albo memory?"}]
            self.assertEqual(commands._game_choice("w kółko i krzyżyk"),
                             "zagrajmy w kółko i krzyżyk")
            self.assertEqual(commands._game_choice("zagadki!"), "zadaj mi zagadkę")
            self.assertIsNone(commands._game_choice("nie chcę zagadek"))
            self.assertIsNone(commands._game_choice("jak maja poradziła sobie z zagadkami?"))
            brain._history[-1]["content"] = "Wczoraj była zabawa w zagadki i memory."
            self.assertIsNone(commands._game_choice("zagadki"))      # only mentioned
            brain._history[-1]["content"] = "Jasne! Kółko i krzyżyk, zagadki albo memory?"
            self.assertIsNone(commands._game_choice("a jaka jest pogoda"))
            # her offer before their answer allows the model's game command;
            # with no offer it doesn't
            brain._history.append({"role": "user", "content": "Tak"})
            self.assertTrue(brain.game_was_offered())
            brain._history[:] = [{"role": "assistant", "content": "Dzień dobry!"},
                                 {"role": "user", "content": "Pobawimy się?"}]
            self.assertFalse(brain.game_was_offered())
            self.assertIsNone(commands._game_choice("w kółko i krzyżyk"))
            # a quiz's own question is no offer (13 Oct: another quiz for "powiedz coś…")
            brain._history[:] = [{"role": "assistant", "content": "Super, quiz z angielskich "
                                  "słówek! 5 pytań — zaczynamy! Jak jest po angielsku: kot?"},
                                 {"role": "user", "content": "Powiedz coś po angielsku"}]
            self.assertFalse(brain.game_was_offered())
            self.assertTrue(brain._asks_to_choose(
                "Super, to zagramy. Wybierz: kamień, papier, nożyce, zgaduj liczbę albo zagadka."))
            self.assertFalse(brain._asks_to_choose("Super, gramy w kółko i krzyżyk!"))
            # radio on, she offered things: the window stays open for the answer
            # (16 Oct 13:56 "…albo krótki quiz — wybieraj." — closed, not heard)
            brain._history[:] = [{"role": "user", "content": "Co dzisiaj robimy?"},
                                 {"role": "assistant", "content": "Mogę zrobić minutnik, "
                                  "listę, radio albo krótki quiz — wybieraj."}]
            self.assertTrue(brain.awaits_answer())
            brain._history[-1]["content"] = "Mały krok czy chwila kawy?"
            self.assertTrue(brain.awaits_answer())
            brain._history[-1]["content"] = "(zrobione: włącz radio)"
            self.assertFalse(brain.awaits_answer())
            brain._history[-1]["content"] = "Włączam Lofi 24/7 — spokojna muzyka do pracy."
            self.assertFalse(brain.awaits_answer())
            # a phrase for later is no question (19 Oct: radio on, she listened on)
            for said in ("Dobrze, bez efektów. Powiedz „włącz efekty”, gdy zechcesz je z powrotem.",
                         "Dobrze, tłumaczę na angielski. Powiedz „koniec tłumaczenia”, żeby skończyć.",
                         "Dodałam. Gdy gra taka, którą lubisz, powiedz „dodaj do ulubionych”."):
                brain._history[-1]["content"] = said
                self.assertFalse(brain.awaits_answer(), said)
            for said in ("Mam to zrobić? Powiedz „tak” albo „nie”.",
                         "Powiedz „włącz efekty”, gdy zechcesz. A może coś jeszcze?"):
                brain._history[-1]["content"] = said
                self.assertTrue(brain.awaits_answer(), said)
        finally:
            brain._history[:] = old

    def test_screen_stop_and_mute_phrases(self):
        import commands, display, idle_engine
        from shared_state import state
        for t, verb in (("zgaś ekran", "zgaś"), ("luna, przyciemnij trochę ekran", "przyciemnij"),
                        ("rozjaśnij ekran proszę", "rozjaśnij"), ("wyłącz ekran", "wyłącz")):
            m = commands._SCREEN.match(t)
            self.assertTrue(m and m.group(1) == verb, t)
        self.assertFalse(commands._SCREEN.match("pokaż na ekranie kota"))
        for t in ("zatrzymaj", "stop", "luna, przestań", "wyłącz to"):
            self.assertTrue(commands._STOP_BARE.match(t), t)
        self.assertFalse(commands._STOP_BARE.match("zatrzymaj minutnik"))
        # a bare "Wyłącz" with the radio on: the radio (11 Oct: "wyłączam napisy")
        self.assertTrue(commands._STOP_BARE.match("wyłącz"))
        import radio
        said = []
        with mock.patch.object(radio, "playing", lambda: "Jazz Radio"),                 mock.patch.object(radio, "stop", lambda: said.append("stopped") or True):
            self.assertTrue(commands.handle("Wyłącz.", said.append, lambda *a, **k: True))
        self.assertEqual(said, ["stopped"])
        display.set_user_override("off")
        self.assertEqual(display._user_override(), "off")
        # 17 Oct: "ustaw ekran na 90% jasności" — that percent, not just "bright"
        for t, pct in (("Ustaw ekran na 90% jasności.", 90),
                       ("A ustaw ekran na 50% jasności.", 50),
                       ("ustaw jasność ekranu na 70 procent", 70)):
            said = []
            self.assertTrue(commands.handle(t, said.append, lambda *a, **k: True), t)
            self.assertEqual(display._user_override(), pct, t)
            self.assertEqual(said, [f"Dobrze, jasność ekranu na {pct} procent."])
        display.set_user_override(None)
        self.assertIsNone(display._user_override())
        old = state.proactive_muted_until
        try:
            import time
            self.assertTrue(idle_engine.check_mute("Bądź cicho przez godzinę"))
            self.assertAlmostEqual(state.proactive_muted_until - time.time(), 3600, delta=5)
            self.assertTrue(idle_engine.check_mute("Luna, cicho na pół godziny"))
            self.assertAlmostEqual(state.proactive_muted_until - time.time(), 1800, delta=5)
            self.assertTrue(idle_engine.check_mute("Nie przeszkadzaj"))
            self.assertFalse(idle_engine.check_mute("jest cicho w domu"))
            self.assertFalse(idle_engine.check_mute("za cicho mówisz"))
            # until a clock time, with a reason first (9 Oct workday sweep)
            import datetime as dt
            at13 = dt.datetime(2026, 10, 12, 13, 0).timestamp()
            self.assertEqual(idle_engine._until_clock("bądź cicho do 15", at13)[0], 7200)
            self.assertEqual(idle_engine._until_clock("cicho do trzeciej", at13)[0], 7200)
            self.assertEqual(idle_engine._until_clock("cicho do wpół do drugiej", at13)[0], 1800)
            self.assertIsNone(idle_engine._until_clock("nie przeszkadzaj do rana", at13))
            later = (time.localtime().tm_hour + 2) % 24        # any time of day (it
            if later >= 2:                                     # failed at 19:00 on 10 Oct)
                self.assertTrue(idle_engine.check_mute(f"Mam spotkanie, bądź cicho do {later}"))
        finally:
            state.proactive_muted_until = old

    def test_sleep_self_and_weather_ask(self):
        import commands
        for t in ("wyłącz się", "luna, idź spać", "dobra, idź już spać", "uśpij się proszę"):
            self.assertTrue(commands._SLEEP_SELF.match(t), t)
        for t in ("wyłącz radio", "wyłącz się za godzinę i zagraj", "idź spać do łóżka maju"):
            self.assertFalse(commands._SLEEP_SELF.match(t), t)
        for t in ("Czy będzie padać jutro?", "Czy jutro będzie deszcz?", "czy dziś pada?",
                  "Wziąć parasolkę?"):
            self.assertTrue(commands._WEATHER_ASK.search(t.lower()), t)
        self.assertFalse(commands._WEATHER_ASK.search("czy będziesz grać?"))

    def test_memory_day_line(self):
        import memory, datetime
        from unittest import mock
        mem = {"facts": [], "episodes": [{"date": "2026-10-07", "text": "Andrzej pytał o czas."}],
               "threads": []}
        with mock.patch.object(memory, "_load", lambda: mem), \
                mock.patch.object(memory, "_today", lambda: datetime.date(2026, 10, 7)):
            self.assertIn("say you don't remember", memory.day_line("O czym rozmawialiśmy wczoraj?"))
            self.assertIn("conversation's history", memory.day_line("O czym dziś rozmawialiśmy?"))
            self.assertIn("Andrzej pytał o czas.", memory.day_line("O czym dziś rozmawialiśmy?"))
            self.assertEqual(memory.day_line("Jaka pogoda wczoraj była?"[:0] + "Co tam?"), "")

    def test_twenty_reverse_unclear(self):
        import twenty
        from shared_state import state
        # 11 Oct: "Troszeczkę jego ma." → "Odpowiedz mi…", and "Czy to bóbr?" three times
        for t in ("Troszeczkę jego ma", "Prawie", "Nie do końca", "Po części"):
            self.assertTrue(twenty._UNSURE.search(t.lower()), t)
        self.assertTrue(twenty._YES.match("raczej tak"))
        self.assertTrue(twenty._NO.match("chyba nie"))
        self.assertFalse(twenty._NO.match("nie wiem"))
        said, moves = [], iter([("question", "Czy jest duże?", ""), ("question", "Czy pływa?", "")])
        old = twenty._next_move
        twenty._next_move = lambda qa, asked: next(moves)
        try:
            twenty._r = {"qa": [], "asked": 3, "t": time.time(), "q": "Czy ma ogon?",
                         "guess": None, "stage": "asking", "player": "Maja"}
            with state.lock:
                state.person = ("Maja", 0.7, time.time())
            twenty.answer("Hmm, ja wiem", said.append)
            self.assertTrue(said[-1].startswith("Odpowiedz mi"))
            twenty.answer("Hmm, ja wiem", said.append)            # the second time: on
            self.assertEqual(said[-1], "Czy jest duże?")
            self.assertEqual(twenty._r["qa"], [("Czy ma ogon?", "nie wiem")])
            twenty.answer("Troszeczkę jego ma.", said.append)
            self.assertEqual(twenty._r["qa"][-1], ("Czy jest duże?", "nie wiem"))
        finally:
            twenty._next_move = old
            twenty._r = None

    def test_alarm_removed_by_time(self):
        import commands
        import timers
        # 13 Oct sweep: "Usuń budzik na 6:40" SET it again
        self.assertIsNone(commands.local_alarm("Usuń budzik na 6:40"))
        due = time.mktime(time.localtime()[:3] + (6, 40, 0, 0, 0, -1)) + 86400
        entry = {"kind": "alarm", "due": due, "label": "", "repeat": "none"}
        said = []
        with mock.patch.object(timers, "_timers", [entry]),                 mock.patch.object(timers, "_save", lambda: None):
            self.assertTrue(commands.alarm_removed("Usuń budzik na 6:40", said.append))
            self.assertEqual(timers._timers, [])
            self.assertIn("usunęłam budzik na szóstą czterdzieści", said[-1])
            self.assertTrue(commands.alarm_removed("Skasuj budzik na siódmą", said.append))
            self.assertIn("Nie mam budzika na siódmą", said[-1])
            self.assertFalse(commands.alarm_removed("Budzik na siódmą", said.append))
        import radio
        self.assertTrue(radio._ON.match("daj jakąś muzykę"))          # (13 Oct: an offer)
        self.assertEqual(next(k for rx, k in radio._GENRES
                              if __import__("re").search(rx, "coś do biegania")), "cat:hits")

    def test_count_with_me_is_no_hide_and_seek(self):
        import counting
        # 13 Oct sweep: "Policz ze mną do dziesięciu" → "Chowajcie się!"
        got = []
        with mock.patch.object(counting, "count",
                               lambda d, n, s, p, hide=None: got.append(hide)):
            counting.handle("Policz ze mną do dziesięciu", lambda t: None, lambda *a: None)
            counting.handle("Policz do dziesięciu", lambda t: None, lambda *a: None)
        self.assertEqual(got, [False, None])

    def test_codes_not_kept(self):
        import commands
        # 13 Oct sweep: "Kod do furtki to 4321" → "Zapamiętam to", then "Tego nie powiem"
        for t in ("Kod do furtki to 4321", "PIN do karty to 1234", "Hasło do wifi to kotek123"):
            self.assertTrue(commands._CODE_TOLD.search(t), t)
        for t in ("Kod pocztowy to 55-080", "Mam kod rabatowy", "Jaki jest kod do furtki?"):
            self.assertFalse(commands._CODE_TOLD.search(t) and not commands.is_question(t), t)

    def test_quiet_and_camera_variations(self):
        import idle_engine
        from shared_state import state
        # 13 Oct sweep: "Wycisz się", "Przestań gadać" → the model's "będę cicho";
        # "Możesz znowu mówić" left the quiet on
        for t in ("Wycisz się", "Przestań gadać"):
            with state.lock:
                state.proactive_muted_until = 0.0
            self.assertTrue(idle_engine.check_mute(t), t)
            with state.lock:
                self.assertGreater(state.proactive_muted_until, time.time())
            self.assertTrue(idle_engine.check_mute("Możesz znowu mówić"))
            with state.lock:
                self.assertLess(state.proactive_muted_until, time.time() + 1)
        import commands
        self.assertTrue(any(k in "nie patrz na mnie" for k in commands._CAM_OFF))

    def test_routine_step_named_as_done(self):
        import kids
        # 13 Oct sweep: "Umyłam zęby" during "umyj zęby" → "not a step"
        self.assertTrue(kids._did_this_step(["umyłam", "zęby"], "umyj zęby"))
        self.assertTrue(kids._did_this_step(["założyłam", "piżamę"], "piżama"))
        self.assertFalse(kids._did_this_step(["chcę", "bajkę"], "umyj zęby"))
        self.assertFalse(kids._did_this_step(["zęby", "bolą"], "umyj zęby"))

    def test_cooking_how_to_step_by_step(self):
        import cooking
        # 13 Oct sweep: "Jak zrobić naleśniki krok po kroku?" — no cooking mode
        self.assertEqual(cooking.wants("Jak zrobić naleśniki krok po kroku?"), "naleśniki")
        self.assertEqual(cooking.wants("Luna, jak upiec sernik krok po kroku"), "sernik")
        self.assertIsNone(cooking.wants("Jak zrobić naleśniki?"))         # a question

    def test_days_to_holidays(self):
        import calc
        from datetime import date
        # 13 Oct sweep: "Ile dni do wakacji?" → "jeszcze sporo…"
        self.assertEqual(calc._school_end(2027), date(2027, 6, 25))       # last Friday of June
        self.assertEqual(calc._school_end(2026), date(2026, 6, 26))
        self.assertIn("Do wakacji", calc.answer("Ile dni do wakacji?") or "")

    def test_intro_with_remember_me(self):
        import commands
        # 13 Oct sweep: "Jestem Kasia, zapamiętaj mnie" → "Powiedz: … jestem…"
        self.assertEqual(commands._intro_name("Jestem Kasia, zapamiętaj mnie"), "Kasia")
        self.assertEqual(commands._intro_name("Zapamiętaj mnie, jestem Kasia"), "Kasia")
        self.assertEqual(commands._intro_name("Luna, mam na imię Ola, zapamiętaj mnie."), "Ola")
        self.assertIsNone(commands._intro_name("Jestem zmęczona, zapamiętaj to"))

    def test_drawing_offer_holds_the_drawing(self):
        from polish import offer_only
        # 13 Oct sweep: an offer to draw again came with the drawing attached
        self.assertTrue(offer_only("Mogę spróbować jeszcze raz i zrobić go ładniej, jeśli chcesz."))
        self.assertTrue(offer_only("Chcesz, żebym narysowała jeszcze raz?"))
        self.assertFalse(offer_only("Dobrze, już rysuję. Chwileczkę!"))
        self.assertFalse(offer_only("Jasne — dodaję kapelusz do tańczącego konia."))
        import drawing
        self.assertTrue(drawing._SHOW.search("Pokaż wszystkie rysunki"))     # (went to the model)
        self.assertTrue(drawing._SHOW.search("Pokaż nam swoje ostatnie rysunki") or
                        drawing._SHOW.search("Pokaż nam ostatnie swoje rysunki"))

    def test_seated_survives_a_restart(self):
        import idle_engine
        # 13 Oct 10:29: "Hej, hej!" in a call, 6 minutes after a restart reset "seated"
        f = tempfile.mktemp(suffix=".json")
        with mock.patch.object(idle_engine, "_SEATED_FILE", f):
            idle_engine._save_seated(1000.0, 5000.0)
            self.assertEqual(idle_engine._load_seated(now=5060.0), 1000.0)   # seen a minute ago
            self.assertEqual(idle_engine._load_seated(now=5300.0), 0.0)      # gone since

    def test_holds_survive_a_restart(self):
        import holds
        from shared_state import state
        f = tempfile.mktemp(suffix=".json")
        now = time.time()
        with mock.patch.object(holds, "PATH", f):
            with state.lock:
                state.camera_off_until = now + 600
                state.mic_muted_until = 0.0
            holds._last.clear()
            self.assertTrue(holds.save_if_changed())
            self.assertFalse(holds.save_if_changed())                 # nothing new
            with state.lock:
                state.camera_off_until = 0.0                          # "a restart"
            self.assertEqual(holds.load(), ["camera_off_until"])
            with state.lock:
                self.assertAlmostEqual(state.camera_off_until, now + 600, delta=1)
                state.camera_off_until = 0.0
            self.assertEqual(holds.load(now=now + 700), [])           # over by then

    def test_words_quiz_not_an_answer(self):
        import quiz
        q = {"kind": "words", "answer": ["big", "large"]}
        self.assertIsNone(quiz._check(q, "Co znaczy rainbow?"))
        self.assertIsNone(quiz._check(q, "Powiedz coś do mnie po angielsku"))
        self.assertTrue(quiz._check(q, "big"))
        self.assertFalse(quiz._check(q, "dog"))

    def test_variations_13_oct(self):
        import brain
        import drawing
        import quiz
        # 13 Oct sweep of new-feature phrasings
        self.assertEqual(quiz.trigger("Zagrajmy w zwierzaki"), "animals")
        self.assertEqual(drawing.looks_wanted("Jak wyglądają pingwiny?"), "pingwiny")
        with mock.patch.object(brain, "_history", [{"role": "user", "content": "[Maja] Zagrajmy w zgadywankę"}]):
            self.assertTrue(brain._game_asked_for())
        with mock.patch.object(brain, "_history", [{"role": "user", "content": "[Maja] Pobawimy się?"}]):
            self.assertFalse(brain._game_asked_for())

    def test_rematch_after_a_game(self):
        import twenty
        import quiz
        # 13 Oct: "Hurra! Zgadłam…! Zagramy jeszcze raz?" → "Tak" → the number game
        said = []
        twenty._r = {"qa": [], "asked": 5, "t": time.time(), "q": "Czy to kot?", "guess": "kot",
                     "stage": "asking", "player": None}
        twenty.answer("Tak", said.append)
        self.assertIn("Zagramy jeszcze raz?", said[-1])
        self.assertFalse(twenty.active())
        self.assertTrue(twenty.rematch("Tak", said.append))
        self.assertIn("Pomyśl sobie zwierzę", said[-1])
        self.assertTrue(twenty.active())
        self.assertFalse(twenty.rematch("Tak", said.append))          # once
        twenty._r = None
        twenty._again[:] = ["forward", time.time() - 1]                # too late
        self.assertFalse(twenty.rematch("Tak", said.append))
        self.assertFalse(quiz.rematch("Tak", said.append, lambda n: None))  # no quiz asked

    def test_twenty_reverse_table(self):
        import twenty
        import twenty_kb
        # 13 Oct: her questions from a table of animals — every one is found
        # well within 20 when the answers match the table, a child's slip is
        # survived, and an animal it doesn't know goes to the model
        keys = [k for k, _ in twenty_kb.QUESTIONS]
        self.assertTrue(all(len(r) == len(keys) for r in twenty_kb.ANIMALS.values()))
        by_text = {q: i for i, (_, q) in enumerate(twenty_kb.QUESTIONS)}
        by_text[twenty._FIRST_Q] = keys.index("fur")

        def play(animal, slip_at=None):
            row = twenty_kb.ANIMALS[animal]
            kind, q, guess = "question", twenty._FIRST_Q, ""
            qa = []
            for asked in range(1, twenty.MAX_QUESTIONS + 1):
                if kind == "guess":
                    if guess == animal:
                        return asked
                    qa.append((q, "nie"))
                else:
                    ans = "tak" if row[by_text[q]] >= 0.5 else "nie"
                    if asked == slip_at:
                        ans = "nie" if ans == "tak" else "tak"
                    qa.append((q, ans))
                kind, q, guess = twenty._table_move(qa, asked)
            return None

        for animal in ("bóbr", "wydra", "kot", "pies", "koń", "biedronka", "sowa", "żyrafa"):
            n = play(animal)
            self.assertTrue(n and n <= 15, (animal, n))
        self.assertTrue(play("chomik", slip_at=3), "a slip")
        # answers no table animal fits → None (the model takes over)
        qa = [(q, "tak") for _, q in twenty_kb.QUESTIONS[:12]]
        self.assertIsNone(twenty._table_move(qa, 12))

    def test_animal_photo_quiz(self):
        import quiz
        import twenty
        from shared_state import state
        # 13 Oct: a photo of an animal, "Jakie to zwierzę?"
        for t in ("Quiz ze zwierząt", "Zagrajmy w zwierzęta", "Zgadywanie zwierząt ze zdjęć",
                  "Pokaż mi zdjęcia zwierząt, a ja zgadnę"):
            self.assertEqual(quiz.trigger(t), "animals", t)
            self.assertFalse(twenty.wants(t), t)
        for t in ("Zgadnij, o jakim zwierzęciu myślę", "Zagrajmy w 20 pytań",
                  "Zgadnij jakie zwierzę"):
            self.assertNotEqual(quiz.trigger(t), "animals", t)
            self.assertTrue(twenty.wants(t), t)
        said = []
        with mock.patch.object(quiz, "_animal_image", lambda n: f"/tmp/{n}.jpg"), \
                mock.patch.object(quiz, "_pick_animal",
                                  lambda seen: ("żyrafa", ["żyrafa", "żyrafę"])), \
                mock.patch.object(quiz.threading, "Thread", lambda *a, **k: mock.Mock()):
            quiz.start("animals", "Quiz ze zwierząt", said.append, lambda n: None)
            self.assertIn("Quiz ze zwierząt", said[0])
            self.assertEqual(said[-1], "Jakie to zwierzę?")
            with state.lock:
                kind, _, data = state.overlay
            self.assertEqual((kind, data["path"]), ("photo", "/tmp/żyrafa.jpg"))
            self.assertIn("zwierzęta", data["sub"])
            q = quiz._q
            self.assertTrue(quiz._check(q, "To żyrafa!"))
            self.assertFalse(quiz._check(q, "zebra"))
            self.assertIn("literę Ż", quiz._hint_for(q))
            quiz.answer("Tak", said.append, lambda n: None)        # no name: asked for one
            self.assertEqual(said[-1], "Powiedz, jakie to zwierzę.")
            self.assertIsNotNone(quiz._q)
            quiz._q = None

    def test_quiz_pictures_prefetch(self):
        import quiz
        import quizdata
        import twenty
        # the flag / animal pictures fetched quietly, once; stops when offline
        d = tempfile.mkdtemp()
        calls = []

        def flag(c, g):
            calls.append(c)
            p = os.path.join(d, "flags", c.lower() + ".png")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(b"x" * 600)
            return p
        with mock.patch("config.DATA_DIR", d),                 mock.patch.object(quiz, "_flag_image", lambda c, g: flag(c, g)),                 mock.patch.object(quiz, "_animal_image",
                                  mock.Mock(side_effect=OSError("offline"))),                 mock.patch.object(quizdata, "FLAGS", [("Polska", "Polski", ["polska"]),
                                                      ("Czechy", "Czech", ["czechy"])]),                 mock.patch.object(twenty, "ANIMALS", [("kot", ["kot"]), ("pies", ["pies"])]):
            self.assertEqual(quiz.prefetch_pictures(pause=0), 2)      # animals: offline
            self.assertEqual(calls, ["Polska", "Czechy"])
            calls.clear()
            quiz.prefetch_pictures(pause=0)                           # already there
            self.assertEqual(calls, [])

    def test_flag_quiz(self):
        import quiz
        import quizdata
        from shared_state import state
        # 13 Oct: a flag on the screen, "Jaki to kraj?"
        for t in ("Zagrajmy we flagi", "Zgadnij flagę", "Quiz z flag",
                  "Przepytaj mnie z flag państw"):
            self.assertEqual(quiz.trigger(t), "flags", t)
        for t in ("Pokaż mi flagę Francji", "Jaka jest flaga Niemiec?"):
            self.assertNotEqual(quiz.trigger(t), "flags", t)
        self.assertEqual(len({f[0] for f in quizdata.FLAGS}), len(quizdata.FLAGS))
        said = []
        with mock.patch.object(quiz, "_flag_image", lambda c, g: f"/tmp/{c}.png"), \
                mock.patch.object(quizdata, "pick_flag",
                                  lambda seen: ("Niemcy", "Niemiec", ["niemcy", "niemiec"])):
            quiz.start("flags", "Zagrajmy we flagi", said.append, lambda n: None)
            self.assertIn("Quiz z flag", said[0])
            self.assertEqual(said[-1], "Jaki to kraj?")
            with state.lock:
                kind, _, data = state.overlay
            self.assertEqual(kind, "photo")
            self.assertEqual(data["path"], "/tmp/Niemcy.png")
            self.assertIn("1 z", data["sub"])
            q = quiz._q
            self.assertTrue(quiz._check(q, "To Niemcy!"))
            self.assertTrue(quiz._check(q, "niemiec"))
            self.assertFalse(quiz._check(q, "Austria"))
            self.assertIn("literę N", quiz._hint_for(q))
            quiz._q = None
        flag = quizdata.FLAGS[[f[0] for f in quizdata.FLAGS].index("Stany Zjednoczone")]
        q = {"kind": "flags", "answer": [a.lower() for a in flag[2]]}
        self.assertTrue(quiz._check(q, "USA"))
        self.assertTrue(quiz._check(q, "Ameryka"))
        import brain
        self.assertTrue(brain._GAME_OK.match("zagrajmy we flagi"))
        self.assertTrue(brain._GAME_OK.match("zróbmy quiz ze zwierząt"))
        self.assertTrue(brain._GAME_OK.match("zagrajmy w zwierzęta"))

    def test_twenty_forward_guess_echo_and_facts(self):
        import twenty
        from shared_state import state
        # 11 Oct (mysz): "Czy to jest świnka morska?" → "Nie, to nie świnia"
        said = []
        twenty._g = {"animal": "mysz", "forms": ["mysz", "myszka", "myszkę"], "asked": 0,
                     "t": time.time(), "player": "Maja"}
        with state.lock:
            state.person = ("Maja", 0.7, time.time())
        try:
            twenty.answer("Czy to jest świnka morska?", said.append)
            self.assertEqual(said[-1], "Nie, to nie świnka morska. Pytaj dalej!")
            twenty.answer("Czy to kot?", said.append)
            self.assertEqual(said[-1], "Nie, to nie kot. Pytaj dalej!")
        finally:
            twenty._g = None
        # …and "Czy ma długie uszy?" → "Tak!" for a mouse: the model is told what
        # a child would say about it
        facts = twenty._kb_facts("mysz")
        self.assertIn("Czy ma długie uszy? nie", facts)
        self.assertIn("Czy twoje zwierzę ma futro albo sierść? tak", facts)
        self.assertEqual(twenty._kb_facts("wombat"), "")

    def test_twenty_reverse(self):
        import twenty
        for t in ("Zgadnij, o czym myślę", "Zgadnij, o jakim zwierzęciu myślę",
                  "Pomyślałam sobie zwierzę", "Ty zgaduj", "Zgadnij jakie zwierzę"):
            self.assertTrue(twenty.wants(t) and twenty.reverse_wanted(t), t)
        for t in ("Zagrajmy w 20 pytań", "Pomyśl sobie zwierzę"):
            self.assertTrue(twenty.wants(t) and not twenty.reverse_wanted(t), t)
        for t in ("Zgadnij, co dziś jadłam", "Pomyślałam o tobie"):
            self.assertFalse(twenty.wants(t), t)
        said = []
        moves = iter([("question", "Czy umie latać?", ""), ("guess", "Czy to sowa?", "sowa")])
        old = twenty._next_move
        twenty._next_move = lambda qa, asked: next(moves)
        try:
            twenty.start(said.append, "Zgadnij, o czym myślę")
            self.assertTrue(twenty.active())
            twenty.answer("Gotowe", said.append)
            self.assertIn("futro", said[-1])
            twenty.answer("Nie", said.append)
            self.assertEqual(said[-1], "Czy umie latać?")
            twenty.answer("Tak", said.append)
            self.assertEqual(said[-1], "Czy to sowa?")
            self.assertEqual(twenty._r["qa"], [(twenty._FIRST_Q, "nie"),
                                               ("Czy umie latać?", "tak")])
            twenty.answer("Tak!", said.append)
            self.assertIn("Zgadłam w 3", said[-1])
            self.assertFalse(twenty.active())
        finally:
            twenty._next_move = old
            twenty._r = None
        # 11 Oct game end with Maja: questions left, a near miss, the secret
        # said out, quitting, "o żadnym" — and Andrzej's face in view too
        from shared_state import state

        def at(line, guess="bóbr", stage="asking", person="Andrzej"):
            twenty._r = {"qa": [], "asked": 19, "t": time.time(), "q": "Czy to bóbr?",
                         "guess": guess, "stage": stage, "player": "Maja"}
            with state.lock:
                state.person = (person, 0.6, time.time())
            said.clear()
            return twenty.answer(line, said.append)
        twenty._next_move = lambda qa, asked: ("question", "Czy pływa?", "")
        try:
            self.assertTrue(at("Zostało ci dziesięć pytań."))
            self.assertIn("zostało mi 1", said[0])
            self.assertTrue(at("Coś podobnego, ale to nie bobr."))
            self.assertEqual(twenty._r["qa"], [("Czy to bóbr?", "nie")])
            self.assertTrue(at("Wydra.") and "wydra" in said[0] and not twenty.active())
            self.assertTrue(at("nie, to sowa") and "sowa" in said[0])
            self.assertTrue(at("Nie, nie żyje w Afryce.") and said[-1] == "Czy pływa?")
            for line in ("Luna, już nie gramy.", "Luna, nie gramy już.", "Nie chcę już grać"):
                self.assertTrue(at(line) and "kończymy" in said[0], line)
            self.assertFalse(at("Mamo, podasz mi wodę do picia?"))   # someone else
            self.assertTrue(at("o żadnym", stage="reveal") and "Tajemnica" in said[0])
            self.assertTrue(at("to była wydra", stage="reveal") and said[0].startswith("Aha, wydra"))
            self.assertTrue(at("nie", guess="niedźwiedź"))
            self.assertEqual(twenty._r["qa"][-1][1], "nie")
        finally:
            twenty._next_move = old
            twenty._r = None
            with state.lock:
                state.person = None
        g = twenty._as_guess
        self.assertEqual(g("question", "Czy to ślimak?", "")[0], "guess")
        self.assertEqual(g("question", "Czy twoje zwierzę jest sową?", "")[0], "guess")
        self.assertEqual(g("question", "Czy to ptak?", "")[0], "question")
        self.assertEqual(g("question", "Czy twoje zwierzę jest ssakiem?", "")[0], "question")
        self.assertEqual(g("question", "Czy twoje zwierzę jest kolorowe?", "")[0], "question")

    def test_status_bar_weather(self):
        import statusbar
        import weather
        # the weather by the clock: this hour's forecast, sun or moon by daylight
        t = time.mktime((2026, 10, 12, 15, 20, 0, 0, 0, -1))
        sky = {"hours": {"2026-10-12T15:00": (11.6, 1), "2026-10-12T21:00": (7.2, 2),
                         "2026-10-12T16:00": (10.4, 63), "2026-10-12T17:00": (-0.6, 73)},
               "light": {"2026-10-12": ("2026-10-12T07:10", "2026-10-12T18:06")}}
        with mock.patch.dict(weather._sky, sky, clear=True), \
                mock.patch.object(weather, "enabled", lambda: True):
            self.assertEqual(weather.now(t), (12, "clear", True))
            self.assertEqual(weather.now(t + 3600), (10, "rain", True))
            self.assertEqual(weather.now(t + 7200), (-1, "snow", True))
            self.assertEqual(weather.now(t + 6 * 3600), (7, "partly", False))
            self.assertIsNone(weather.now(t + 86400))                   # no forecast for it
            self.assertEqual(statusbar.sky(t), ("clear_day", "12°", False))
            self.assertEqual(statusbar.sky(t + 6 * 3600), ("partly_night", "7°", False))
        # rain on its way in the next hours: an umbrella beside the sun
        with mock.patch.dict(weather._sky, dict(sky, rain={"2026-10-12T17:00": 70}), clear=True),                 mock.patch.object(weather, "enabled", lambda: True):
            self.assertTrue(weather.rain_soon(t))                      # 15:20 → 17:00 in 3 h
            self.assertFalse(weather.rain_soon(t - 3 * 3600))
            self.assertEqual(statusbar.sky(t), ("clear_day", "12°", True))
            self.assertEqual(statusbar.sky(t + 3600)[2], False)         # raining: no umbrella
        with mock.patch.object(weather, "enabled", lambda: False):
            self.assertIsNone(statusbar.sky(t))                          # "wyłącz pogodę"

    def test_status_bar_items(self):
        import statusbar
        import timers
        import commands
        now = time.mktime((2026, 10, 11, 20, 45, 0, 0, 0, -1))
        self.assertEqual(statusbar.clock_text(now), "niedz. 11 paź   20:45")
        saved = list(timers._timers)
        keep = {k: getattr(state, k) for k in ("online", "radio", "conversation_active",
                                               "luna_mode", "messages_waiting", "speaking",
                                               "mic_muted_until", "listening")}
        try:
            timers._timers[:] = [
                {"due": now + 299, "label": "", "kind": "timer", "set": now},
                {"due": now + 36000, "label": "", "kind": "alarm", "set": now},
                {"due": now + 3 * 86400, "label": "", "kind": "reminder", "set": now}]
            with state.lock:
                state.online, state.radio = True, "Radio Nowy Świat"
                state.conversation_active, state.luna_mode = True, "idle"
                state.speaking = state.listening = False
                state.messages_waiting, state.mic_muted_until = 1, 0.0
            its, voice = statusbar.items(now)
            self.assertEqual(its, [("online", None), ("radio", "Radio Nowy Świat"),
                                   ("timer", "4:59"), ("alarm", "6:45"), ("message", None)])
            self.assertEqual(voice, "listening")
            with state.lock:                    # muted: no "listening", a crossed mic
                state.mic_muted_until, state.online = now + 60, False
                state.radio = "♪ " + "szum fal morskich nad brzegiem morza"
            its, voice = statusbar.items(now)
            self.assertIsNone(voice)
            self.assertIn(("mic_off", None), its)
            self.assertEqual(its[0], ("offline", None))
            self.assertTrue(its[1][1].endswith("…") and len(its[1][1]) == 22)
        finally:
            timers._timers[:] = saved
            with state.lock:
                for k, v in keep.items():
                    setattr(state, k, v)
        for t, on in (("Ukryj pasek", False), ("Luna, pokaż pasek u góry.", True),
                      ("schowaj górny pasek", False), ("włącz pasek stanu", True)):
            m = commands._STATUS_BAR.match(t.lower().strip(" .!?"))
            self.assertTrue(m, t)
        self.assertFalse(commands._STATUS_BAR.match("pokaż pasek czekolady"))
        for t, on in (("Pokaż podgląd kamery", True), ("Luna, ukryj podgląd.", False),
                      ("włącz podgląd z kamery", True), ("wyłącz podgląd", False),
                      ("nie pokazuj obrazu z kamery", False), ("pokaż mi kamerę", True),
                      ("schowaj kamerę", False), ("show camera preview", True)):
            low = t.lower().strip(" .!?")
            m = commands._CAM_PREVIEW.match(low) or commands._CAM_PREVIEW_K.match(low)
            self.assertTrue(m, t)
            self.assertEqual(bool(m.group(1)), on, t)
        for t in ("wyłącz kamerę", "włącz kamerę", "pokaż podgląd pogody na jutro"):
            self.assertFalse(commands._CAM_PREVIEW.match(t) or commands._CAM_PREVIEW_K.match(t), t)

    def test_quiz_would_accept(self):
        import quiz
        old = quiz._q
        try:
            quiz._q = {"kind": "riddle", "answer": ["ryba", "rybka", "rybę"], "hint": "x"}
            self.assertTrue(quiz.would_accept("to nie inna ryba"))
            self.assertFalse(quiz.would_accept("wieloryb wieloryb ma"))
            self.assertFalse(quiz.would_accept("grupa i partia"))
            self.assertNotIn("last_try", quiz._q)          # the game is untouched
            quiz._q = None
            self.assertFalse(quiz.would_accept("ryba"))
        finally:
            quiz._q = old

    def test_english_call_pauses_wake_checks(self):
        import speech_to_text as s
        s._en_heard.clear()
        s._call_until = 0.0
        t = 1000.0
        s._note_wake_check_result("Should it be one man just standing and talking?", t)
        s._note_wake_check_result("Zaraz mam spotkanie.", t + 5)           # Polish: no
        s._note_wake_check_result("We have a demo session like this one.", t + 10)
        self.assertFalse(s.call_pause(t + 11))
        s._note_wake_check_result("Just extend it a little bit, you don't...", t + 20)
        self.assertTrue(s.call_pause(t + 21))
        self.assertTrue(s.people_talking(t + 21))         # and she keeps quiet
        self.assertTrue(s.call_pause(t + 20 + 599))
        self.assertFalse(s.call_pause(t + 20 + 601))
        s._call_until = 0.0
        s._en_heard.clear()

    def test_a_meeting_pauses_wake_checks(self):
        import speech_to_text as s
        s._en_heard.clear()
        s._talk_heard.clear()
        s._call_until = 0.0
        t = 1000.0
        for i in range(7):
            s._note_wake_check_result("No ale to jest, czekaj, ten template.", t + i * 20)
        s._note_wake_check_result("Luna, która godzina?", t + 150)   # for her…
        s._note_wake_check_result("Dobra, a te maile?", t + 160)
        self.assertFalse(s.call_pause(t + 161))                  # …starts it over
        for i in range(7):
            s._note_wake_check_result("Aha, dobra.", t + 170 + i * 10)
        self.assertTrue(s.call_pause(t + 231))
        self.assertTrue(s.call_pause(t + 230 + 599))
        end = t + 230 + 600
        self.assertFalse(s.call_pause(end + 30))
        s._note_wake_check_result("No tak.", end + 30)           # still at it
        self.assertTrue(s.call_pause(end + 31))
        s._note_wake_check_result("", end + 40)                  # silence: nothing
        s._call_until = 0.0
        s._talk_heard.clear()

    def test_one_look_ahead_per_sentence(self):
        import speech_to_text as s
        # 13 Oct: one long meeting sentence sent three times, at each pause
        with mock.patch.object(s, "_energy_gate", lambda: 1000), \
                mock.patch.object(s, "_wake_check_worth", lambda w, peak=None, secs=None: True), \
                mock.patch.object(s, "_wake_budget", lambda: True):
            words = "no dla tego konkretnego".split()
            self.assertTrue(s._passive_spec_ok(False, 5000, words))
            self.assertFalse(s._passive_spec_ok(True, 5000, words))     # looked already
            self.assertFalse(s._passive_spec_ok(False, 1500, words))    # not loud

    def test_cloud_wake_plausible(self):
        import speech_to_text as s
        self.assertFalse(s._cloud_wake_plausible("Luna, wstań z łóżka, ty zdychasz.", ["usa"]))
        self.assertFalse(s._cloud_wake_plausible(
            "Luna, pomyślałam, że żyjesz. Tak, tak, żyję.", ["tak", "tak"]))
        self.assertTrue(s._cloud_wake_plausible("Cześć Luna, która godzina?",
                                                ["ilona", "która", "godzina"]))
        self.assertTrue(s._cloud_wake_plausible("Luna, wyłącz radio.",
                                                ["ona", "wyłącznie", "odmowie"]))
        self.assertTrue(s._cloud_wake_plausible("Luna?", ["zmiana"]))
        self.assertTrue(s._cloud_wake_plausible("Luna, co tam?", None))

    def test_variety_rule(self):
        import brain
        h = [{"role": "user", "content": "Co tam?"},
             {"role": "assistant", "content": "Spokojnie, Andrzeju. Jestem tu."},
             {"role": "user", "content": "Co tam?"},
             {"role": "assistant", "content": "Hej! U mnie dobrze."}]
        rule = brain._variety_rule(h)
        self.assertIn('"Spokojnie Andrzeju…"', rule)
        self.assertIn('"Hej U…"', rule)
        self.assertEqual(brain._variety_rule(h[:2]), "")

    def test_just_called_after_her_answer(self):
        import brain
        import faces
        old = (state.last_wake_time, state.last_spoken_time, state.others)
        try:
            state.last_wake_time = time.time() - 20
            state.last_spoken_time = time.time() - 4
            state.others = ([], 0.0)
            with mock.patch.object(faces, "vocatives", lambda: {"Emilka": "Emilko"}):
                self.assertTrue(brain._just_called("No, mi się chce spać."))
                self.assertFalse(brain._just_called("Emilko, chodź na obiad."))
                state.others = (["Maja"], time.time())
                self.assertFalse(brain._just_called("No, mi się chce spać."))
                state.others = ([], 0.0)
                state.last_spoken_time = time.time() - 30
                self.assertFalse(brain._just_called("No, mi się chce spać."))
                # after her question, a short answer 11 s later (9 Oct "Iwanka.")
                state.last_spoken_time = time.time() - 11
                brain._history[:] = [{"role": "assistant",
                                      "content": "Jasne — w co chcesz się pobawić?"}]
                self.assertTrue(brain._just_called("Iwanka."))
                brain._history[:] = [{"role": "assistant", "content": "Dobranoc."}]
                self.assertFalse(brain._just_called("Iwanka."))
                brain._history.clear()
            # right after her name, but said to someone else (8 Oct morning sweep)
            state.last_wake_time = time.time() - 3
            with mock.patch.object(faces, "vocatives",
                                   lambda: {"Emilka": "Emilko", "Maja": "Maju"}):
                self.assertFalse(brain._just_called("Maja, ubieraj się."))
                self.assertFalse(brain._just_called("Maju, ubieraj się."))
                self.assertFalse(brain._just_called("Mamo, gdzie są moje skarpetki?"))
                self.assertTrue(brain._just_called("Maja się nudzi."))
                self.assertTrue(brain._just_called("Jestem zdenerwowany."))
                self.assertTrue(brain._to_someone("Kochanie, zrobisz mi herbatę?"))
                self.assertTrue(brain._to_someone("Tato, pomożesz mi z matmą?"))
                self.assertTrue(brain._to_someone("Babciu, zobacz, Luna umie rysować!"))
                self.assertFalse(brain._to_someone("Maja, Emilka i Andrzej — kto jest najstarszy?"))
                self.assertFalse(brain._to_someone("Totalnie się nudzę."))
                self.assertFalse(brain._to_someone("Majonez się skończył."))
        finally:
            state.last_wake_time, state.last_spoken_time, state.others = old

    def test_alone_request(self):
        import time
        import brain
        from shared_state import state
        old = (state.person, state.others)
        try:
            state.person = ("Andrzej", 0.8, time.time())
            state.others = ([], 0.0)
            self.assertTrue(brain._alone_request("Wymyśl, co jeszcze kupić do jedzenia."))
            self.assertFalse(brain._alone_request("Tutaj się naciska, przytrzymujesz chwilę."))
            state.others = (["Maja"], time.time())
            self.assertFalse(brain._alone_request("Wymyśl, co jeszcze kupić do jedzenia."))
            state.person = None
            self.assertFalse(brain._alone_request("Wymyśl coś."))
        finally:
            state.person, state.others = old

    def test_secrets(self):
        import brain
        from polish import is_secret
        self.assertTrue(is_secret("Kupiłem Emilce kolczyki, tylko jej nie mów"))
        self.assertTrue(is_secret("Nie mów Mai, że jutro idziemy do kina."))
        self.assertTrue(is_secret("To niespodzianka dla Mai"))
        for t in ("Nie mówię po hiszpańsku", "Nie mów tak szybko", "Co mówiłaś?"):
            self.assertFalse(is_secret(t), t)
        old_h, old_p = list(brain._history), state.person
        try:
            brain._history[:] = [{"role": "user", "content": brain.SECRET_MARK
                                  + "[Andrzej] kolczyki, tylko jej nie mów"},
                                 {"role": "assistant", "content": "Jasne."}]
            state.person = ("Emilka", 0.9, time.time())
            line = brain._secret_line()
            self.assertIn("by Andrzej", line)
            self.assertIn("Emilka is asking now", line)
            brain._history[:] = []
            self.assertEqual(brain._secret_line(), "")
        finally:
            brain._history[:] = old_h
            state.person = old_p

    def test_match_role(self):
        import faces
        with mock.patch.object(faces, "notes", lambda: {
                "Andrzej": "partner Emilki, tata Mai", "Emilka": "partnerka Andrzeja, mama Mai",
                "Maja": "córka Andrzeja i Emilki"}):
            self.assertEqual(faces.match_role("tata"), "Andrzej")
            self.assertEqual(faces.match_role("mamę"), "Emilka")
            self.assertEqual(faces.match_role("córka"), "Maja")
            self.assertIsNone(faces.match_role("babcia"))
        self.assertEqual(faces.role_word("taty"), "Tata")
        self.assertIsNone(faces.role_word("córka"))
        with mock.patch.object(faces, "last_seen", lambda n: None), \
                mock.patch.object(faces, "_female", lambda n: False):
            self.assertEqual(faces.where_is("Andrzej", call="Tata"),
                             "Tata jeszcze nie był przy mnie, odkąd pamiętam.")

    def test_drawing_something_is_a_surprise(self):
        import drawing
        # verb last / "jeszcze raz" (10 Oct: nothing was drawn, the model promised)
        self.assertEqual(drawing.wants("Jeszcze raz mnie narysuj"), "mnie")
        self.assertEqual(drawing.wants("Narysuj mnie jeszcze raz"), "mnie")
        self.assertEqual(drawing.wants("Luna, kota narysuj"), "kota")
        self.assertIsNone(drawing.wants("Co mam narysować?"))
        self.assertTrue(drawing._is_person("mnie"))
        self.assertFalse(drawing._is_person("kota"))
        self.assertIn(drawing._subject("coś"), drawing._SURPRISES)
        self.assertIn(drawing._subject("coś ładnego"), drawing._SURPRISES)
        self.assertEqual(drawing._subject("kota"), "kota")

    def test_drawing_from_the_camera(self):
        import drawing
        # 11 Oct: "draw what you see on the camera" — the frame is redrawn
        self.assertEqual(drawing.wants("Narysuj mnie ze zdjęcia"), "mnie")
        long = ("Narysuj mnie: kolorowy sweter, brązowe oczy, brązowe włosy, krótkie "
                "spodenki i kot w ręce")
        self.assertTrue(drawing.wants(long).startswith("mnie: kolorowy"))
        self.assertEqual(drawing._details(drawing.wants(long))[:15], "kolorowy sweter")
        # a change asked for without a colon — it was dropped and the prompt
        # said "change nothing"
        self.assertEqual(drawing._details("mnie jako astronautę"), "jako astronautę")
        self.assertEqual(drawing._details("nas w kosmosie"), "w kosmosie")
        self.assertEqual(drawing._details("nas, po prostu zrób nam zdjęcie"), "")
        self.assertEqual(drawing._details("nas tak jak jesteśmy, zapamiętaj kilka rzeczy i nas "
                                          "narysuj"), "")
        self.assertTrue(drawing._FROM_CAM.search("Narysuj to, co widzisz"))
        self.assertTrue(drawing._FROM_CAM.search("Narysuj nas, po prostu zrób nam zdjęcie"))
        self.assertTrue(drawing._IN_FRONT.match("nas wszystkich"))
        self.assertFalse(drawing._IN_FRONT.match("naszego kota"))
        calls, said = [], []
        with mock.patch.object(drawing, "_camera_jpeg", lambda: b"jpg"), \
                mock.patch.object(drawing, "draw", lambda w, s, intro="", english=False,
                                  photo=None: calls.append((w, photo)) or True):
            drawing.handle("Narysuj mnie", said.append)
            drawing.handle("Narysuj mi smoka", said.append)
            drawing.handle("Narysuj to, co widzisz", said.append)
        self.assertEqual(calls, [("mnie", b"jpg"), ("smoka", None), ("to, co widzisz", b"jpg")])
        calls.clear()
        with mock.patch.object(drawing, "_camera_jpeg", lambda: None), \
                mock.patch.object(drawing, "draw", lambda w, s, intro="", english=False,
                                  photo=None: calls.append((w, intro)) or True):
            drawing.handle("Narysuj to, co widzisz", said.append)   # camera off
            drawing.handle("Narysuj mnie", said.append)
        self.assertIn("wyłączona", said[-1])
        self.assertEqual(calls[0][0], "mnie")
        self.assertIn("wyobraźni", calls[0][1])

    def test_drawing_again_from_the_photo(self):
        import drawing
        # 11 Oct 12:02: "Dobra, Luna, jeszcze raz ze zdjęcia" went to the model
        calls = []
        fake = lambda w, s, intro="", english=False, photo=None: calls.append((w, photo)) or True
        with mock.patch.object(drawing, "_camera_jpeg", lambda: b"jpg"), \
                mock.patch.object(drawing, "draw", fake):
            drawing._last_what[0], drawing._last_cam[0] = "smoka", False
            drawing._last[0] = time.time() - 200
            self.assertFalse(drawing.handle("Jeszcze raz", lambda t: None))   # too late, bare
            self.assertTrue(drawing.handle("Dobra, jeszcze raz ze zdjęcia.", lambda t: None))
            drawing._last[0] = time.time() - 30
            self.assertTrue(drawing.handle("Jeszcze raz", lambda t: None))
            drawing._last[0] = time.time() - 600
            self.assertFalse(drawing.handle("Jeszcze raz ze zdjęcia", lambda t: None))
        self.assertEqual(calls, [("smoka", b"jpg"), ("smoka", None)])

    def test_note_added_to_her_last_reply(self):
        import brain
        with mock.patch.object(brain, "_history", [{"role": "user", "content": "x"},
                                                   {"role": "assistant", "content": "Rysuję."}]), \
                mock.patch.object(brain, "save_history", lambda: None):
            self.assertTrue(brain.add_to_last_reply("(Rysunek gotowy.)"))
            self.assertEqual(brain._history[-1]["content"], "Rysuję. (Rysunek gotowy.)")

    def test_deep_voice_is_caught(self):
        import numpy as np
        import voicecheck
        # 11 Oct: "her voice sometimes goes weirdly deep" — a cached take sat at 119 Hz
        t = np.arange(14400) / 24000                     # 0.6 s, as _steady holds back
        for hz in (119, 195, 250):
            x = (6000 * np.sin(2 * np.pi * hz * t) + 4000 * np.sin(4 * np.pi * hz * t))
            self.assertAlmostEqual(voicecheck.pitch(x.astype(np.int16).tobytes()), hz, delta=6)
        self.assertIsNone(voicecheck.pitch(bytes(28800)))   # silence: no verdict
        # a take heard back before it is cached (11 Oct: "Súham", "Juš resa")
        self.assertTrue(voicecheck.sounds_like("Słucham.", "Słucham?"))
        self.assertFalse(voicecheck.sounds_like("Słucham.", "Súham"))
        self.assertFalse(voicecheck.sounds_like("Już rysuję… chwilka!", "Juš resa"))
        self.assertTrue(voicecheck.sounds_like("Ja nożyce, ty papier — 1 do 0.",
                                               "Ja nożyce, ty papier, 1:0."))

    def test_model_drawing_commands_are_allowed(self):
        import brain
        # 11 Oct: refused for length / wording — she said "rysuję", nothing came
        started = []
        with mock.patch.object(brain, "_spoken_command", lambda l, k: started.append(l)):
            self.assertTrue(brain.run_command("narysuj mnie: kot w ręce, kolorowy sweter, "
                                              "brązowe oczy, brązowe włosy, krótkie spodenki"))
            self.assertTrue(brain.run_command("zrób rysunek kotka"))
            self.assertTrue(brain.run_command("pokaż rysunki"))
            self.assertTrue(brain.run_command("zamień się w kotka / pieska / zajączka"))
        self.assertEqual(started[1], "narysuj kotka")
        self.assertEqual(started[3], "zamień się w kotka")

    def test_no_second_intro_after_the_models_answer(self):
        import drawing
        said = []
        with mock.patch.object(drawing, "DIR", tempfile.mkdtemp()), \
                mock.patch.object(drawing, "_card", lambda *a: None):
            real = drawing.threading.Thread
            with mock.patch.object(drawing.threading, "Thread", lambda *a, **k: mock.Mock()):
                for name in ("command", "voice"):
                    drawing._last[0] = 0.0
                    t = real(target=lambda: drawing.draw("kota", said.append), name=name)
                    t.start()
                    t.join()
        self.assertEqual(said, ["Dobrze, już rysuję. Chwileczkę!"])        # only the local one spoke

    def test_home_region_in_the_weather_line(self):
        import weather
        import settings
        asked = []
        with mock.patch.object(weather, "_place", lambda: (51.0, 16.8, "Kąty Wrocławskie")), \
                mock.patch.object(weather, "_geocode", lambda n: asked.append(n) or
                                  {"admin1": "Województwo dolnośląskie"}):
            settings.put("place_region", None)
            self.assertEqual(weather._region(), ", województwo dolnośląskie")
            self.assertEqual(weather._region(), ", województwo dolnośląskie")
        self.assertEqual(asked, ["Kąty Wrocławskie"])          # asked once, then kept

    def test_how_long_question_sets_nothing(self):
        import brain
        self.assertTrue(brain._how_long_only("Jak długo gotować jajko na twardo?"))
        self.assertTrue(brain._how_long_only("Ile minut piec szarlotkę?"))
        self.assertFalse(brain._how_long_only("Jak długo gotować jajko? Nastaw minutnik"))
        self.assertFalse(brain._how_long_only("Ile czasu zostało do budzika?"))
        self.assertFalse(brain._how_long_only("Ugotuj mi jajko"))

    def test_no_search_while_answering_a_search(self):
        import brain
        hist = [{"role": "user", "content": "[Emilka] Jaki jest kurs euro?"},
                {"role": "assistant", "content": "Sprawdzam w internecie."},
                {"role": "user", "content": "[Emilka] (Wynik wyszukiwania: kurs euro PLN)"}]
        with mock.patch.object(brain, "_history", hist), \
                mock.patch("commands.handle", lambda *a, **k: True):
            self.assertFalse(brain.run_command("wyszukaj w internecie: kurs euro"))
            hist[-1]["content"] = "[Emilka] A ile kosztuje dolar?"
            self.assertTrue(brain.run_command("wyszukaj w internecie: kurs dolara"))

    def test_part_of_day_in_the_time_line(self):
        import brain
        # 11 Oct 16:00: "chłodny ten niedzielny wieczór"
        self.assertIn("NOT evening", brain._daypart(16))
        self.assertTrue(brain._daypart(19).startswith("evening"))
        self.assertTrue(brain._daypart(7).startswith("early morning"))

    def test_a_promised_drawing_is_drawn(self):
        import brain
        import drawing
        # 11 Oct 11:11: "Rysuję to teraz, Maju, z kotem na ręce." — no command
        self.assertTrue(brain._promised_drawing("Aha, kot ma być w ręce. Rysuję to teraz, Maju."))
        self.assertTrue(brain._promised_drawing("Jasne — zaraz narysuję was razem."))
        self.assertFalse(brain._promised_drawing("Jeśli chcesz, narysuję kotka."))
        self.assertFalse(brain._promised_drawing("Tego nie narysuję."))
        self.assertFalse(brain._promised_drawing("Co mam narysować?"))
        self.assertTrue(brain._ABOUT_DRAWING.search("Kot ma być w ręce i teraz możesz rysować"))
        self.assertFalse(brain._ABOUT_DRAWING.search("Super!"))
        drawing._last_what[0], drawing._last[0] = "mnie", time.time() - 60
        self.assertEqual(brain._drawing_to_keep_promise("Kot ma być w ręce i teraz możesz "
                                                        "rysować"), "narysuj mnie: Kot ma być w ręce")
        self.assertEqual(brain._drawing_to_keep_promise("No to rysuj."), "narysuj mnie")
        self.assertEqual(brain._drawing_to_keep_promise("Narysuj smoka"), "narysuj smoka")
        drawing._last[0] = time.time() - 3600
        self.assertIsNone(brain._drawing_to_keep_promise("No to rysuj."))
        # "Super!" after a picture — the model drew it again (11 Oct sweep)
        for said, praise in (("[Maja] Super!", True), ("[Maja] Ale ładne!", True),
                             ("[Maja] Tak!", False), ("[Maja] Dodaj kota", False)):
            with mock.patch.object(brain, "_history", [{"role": "user", "content": said}]):
                self.assertEqual(brain._just_praise(), praise, said)
        self.assertTrue(brain._ABOUT_DRAWING.search("Masz dodać kolorowy sweter"))
        self.assertEqual(drawing._first_word("Maja: kot w ręce"), "maja")   # "Maja:" no name

    def test_a_promised_station_plays(self):
        import brain
        # 13 Oct 10:46: "Włączam Trójkę z spokojną muzyką." — no command, silence
        p = brain._promised_station
        self.assertEqual(p("Włączam Trójkę z spokojną muzyką. Miłego słuchania, Andrzeju!"),
                         "trójkę")
        self.assertEqual(p("Jasne, puszczam RMF FM."), "rmf fm")
        self.assertEqual(p("Dobrze. Już włączam radio."), "radio")
        self.assertIsNone(p("Mogę włączyć radio, na przykład Trójkę. Chcesz?"))
        self.assertIsNone(p("Włączam Trójkę czy Dwójkę?"))
        self.assertIsNone(p("Nie włączam teraz radia."))
        self.assertTrue(brain._COMMAND_OK.match("włącz trójkę"))
        self.assertTrue(brain._COMMAND_OK.match("włącz rmf fm"))

    def test_side_talk_tone_not_held_against_anyone(self):
        import brain
        import relationship
        # 9-11 Oct: "Wstań z łóżka, ty zdychasz" (to someone else) → "rude" to her
        noted = []

        def answer(to_luna, tone):
            c = mock.Mock()
            c.chat.completions.create.return_value.choices = [mock.Mock(message=mock.Mock(
                refusal=None, content=json.dumps({
                    "reply": "" if not to_luna else "Oj.", "to_luna": to_luna,
                    "user_tone": tone, "user_mood": "no_person", "emotion": "neutral",
                    "gesture": "none", "mood_comment": False, "actions": []})))]
            return c
        with mock.patch.object(relationship, "note", lambda t, s="": noted.append(t)), \
                mock.patch.object(brain, "_history", []), \
                mock.patch.object(brain, "save_history", lambda: None), \
                mock.patch.object(brain, "_just_called", lambda t="", secs=12: False), \
                mock.patch.object(brain, "_alone_request", lambda t: False), \
                mock.patch.object(brain.memory, "record", lambda *a, **k: None):
            with mock.patch.object(brain, "_client", answer(False, "rude")):
                brain._ask_openai("Wstań z łóżka, ty zdychasz.")
            self.assertEqual(noted, [])
            with mock.patch.object(brain, "_client", answer(True, "rude")):
                brain._ask_openai("Jesteś głupia.")
            self.assertEqual(noted, ["rude"])
            # swearing at the situation is not at her (13 Oct sweep: "insulting")
            noted.clear()
            with mock.patch.object(brain, "_client", answer(True, "insulting")):
                brain._ask_openai("Ja pierdzielę, znowu ten błąd w kodzie")
            self.assertEqual(noted, ["neutral"])

    def test_side_talk_to_a_man(self):
        import brain
        # 12 Oct 13:32: "Ile mi dziubanku przelałeś?" (to Andrzej) was answered
        with mock.patch.object(brain, "_just_called", lambda t="", secs=12: False), \
                mock.patch.object(brain, "translator", lambda: None):
            self.assertTrue(brain._to_a_man("Ile mi dziubanku przelałeś?"))
            self.assertTrue(brain._to_a_man("Powiedziałbyś, że takie okrągłe jest?"))
            self.assertFalse(brain._to_a_man("Luna, co narysowałeś?"))     # her name
            self.assertFalse(brain._to_a_man("Co narysowałaś?"))           # to her
            self.assertFalse(brain._to_a_man("Byłem dziś w sklepie"))
        with mock.patch.object(brain, "_just_called", lambda t="", secs=12: True):
            self.assertFalse(brain._to_a_man("Ile mi przelałeś?"))         # "Luna" a moment ago
        import drawing
        # "A teraz ze zdjęcia" after "narysuj Emilkę" — Emilka, from the camera
        drawing._last_what[0], drawing._last_cam[0] = "Emilkę", False
        drawing._last[0] = time.time() - 30
        calls = []
        with mock.patch.object(drawing, "_camera_jpeg", lambda: b"jpg"), \
                mock.patch.object(drawing, "draw", lambda w, s, intro="", english=False,
                                  photo=None: calls.append((w, photo)) or True):
            self.assertTrue(drawing.handle("A teraz ze zdjęcia.", lambda t: None))
            self.assertFalse(drawing.handle("A teraz", lambda t: None))
        self.assertEqual(calls, [("Emilkę", b"jpg")])

    def test_photo_from_the_model_and_latin(self):
        import brain
        import drawing
        import webphoto
        # 12 Oct 13:40: "pokaż mi słonia", "pokaż z Wikipedii" — the model can
        # now send "pokaż zdjęcie słonia"
        self.assertTrue(brain._VOICED_OK.match("pokaż zdjęcie słonia"))
        self.assertTrue(brain._VOICED_OK.match("pokaż mi zdjęcie tranzystora"))
        got = []
        with mock.patch.object(webphoto, "show", lambda w, s, fb: got.append(w) or True):
            drawing.handle("pokaż zdjęcie słonia", lambda t: None)
        self.assertEqual(got, ["słonia"])
        # "płaski lub półokrągły корпус" (12 Oct)
        with mock.patch.object(brain, "translator", lambda: None):
            self.assertEqual(brain._latin("Ma płaski lub półokrągły корпус, a na nim napis."),
                             "Ma płaski lub półokrągły korpus, a na nim napis.")
            self.assertEqual(brain._latin("Привет, как дела?"), "Привет, как дела?")
            self.assertEqual(brain._latin("Zwykłe zdanie."), "Zwykłe zdanie.")
        with mock.patch.object(brain, "translator", lambda: "rosyjski"):
            self.assertEqual(brain._latin("To jest корпус"), "To jest корпус")

    def test_whats_new(self):
        import brain
        # "Co nowego potrafisz?" — told from data/whatsnew.txt
        # the newest section's first line (a fixed old line drops out as new ones come)
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "whatsnew.txt")
        lines = open(path, encoding="utf-8").read().splitlines()
        newest = next(l for l in lines if l.startswith("- "))
        for t in ("Luna, co nowego potrafisz?", "Co nowego umiesz?", "Jakie są nowości?",
                  "Czego nowego się nauczyłaś?", "What's new?"):
            self.assertIn(newest, brain._whatsnew_line(t), t)
        self.assertEqual(brain._whatsnew_line("Co nowego w szkole, Maju?"), "")
        self.assertEqual(brain._whatsnew_line("Ile masz lat?"), "")

    def test_her_own_words_in_the_history(self):
        import brain
        # 12 Oct 19:15: "Jak mija wieczór?" → "W porządku." → "Jasne." (the hello unseen)
        with mock.patch.object(brain, "_history", []),                 mock.patch.object(brain, "save_history", lambda: None):
            brain.note_said("Dobry wieczór, Andrzeju! Jak mija wieczór?")
            brain.note_said("")
            self.assertEqual(brain._history, [{"role": "assistant",
                                               "content": "Dobry wieczór, Andrzeju! Jak mija wieczór?"}])

    def test_no_second_hello(self):
        import brain
        # 19 Oct 15:28: the welcome back, then "…miło cię znowu widzieć — wróciłeś…"
        with mock.patch.object(brain, "_history", []), \
                mock.patch.object(brain, "save_history", lambda: None), \
                mock.patch.object(brain, "_last_hello", (0.0, "")):
            brain.note_said("Masz wiadomość od Emilki.")
            self.assertEqual(brain._hello_line(), "")
            brain.note_said("O, Andrzeju, wróciłeś!", hello=True)
            t = brain._last_hello[0]
            self.assertIn("O, Andrzeju, wróciłeś!", brain._hello_line(t + 30))
            self.assertEqual(brain._hello_line(t + 301), "")

    def test_hellos_differ(self):
        import brain
        # 12 Oct: "Cześć, Andrzeju, fajne / miłe popołudnie u nas na biurku" — each
        # hello is now told the last ones
        seen = []
        c = mock.Mock()

        def create(**kw):
            seen.append(kw["messages"][1]["content"])
            return mock.Mock(choices=[mock.Mock(message=mock.Mock(
                content=f"Cześć, Andrzeju {len(seen)}!"))])
        c.chat.completions.create.side_effect = create
        with mock.patch.object(brain, "_client", c), \
                mock.patch.object(brain, "_hellos", []):
            brain.greeting(False, who="Andrzej")
            brain.greeting(False, who="Andrzej")
            self.assertNotIn("Your last hellos", seen[0])
            self.assertIn('"Cześć, Andrzeju 1!"', seen[1])
            self.assertEqual(brain._hellos, ["Cześć, Andrzeju 1!", "Cześć, Andrzeju 2!"])
        self.assertIn("Don't mention", brain._HELLO_AGAIN)

    def test_hello_without_desk_or_guessed_name(self):
        import brain
        import speech_to_text
        # 12 Oct evening: "Jak mija wieczór u nas na biurku?", and a face she
        # didn't recognise greeted as "Emilko"
        self.assertEqual(brain._no_desk("Dobry wieczór, Andrzeju! Jak mija wieczór u nas na biurku?"),
                         "Dobry wieczór, Andrzeju! Jak mija wieczór?")
        self.assertEqual(brain._no_desk("Dobry wieczór! U nas na biurku już chłodno i spokojnie."),
                         "Dobry wieczór! Już chłodno i spokojnie.")
        self.assertEqual(brain._no_desk("Cześć, Andrzeju, fajne popołudnie u nas na biurku!"),
                         "Cześć, Andrzeju, fajne popołudnie!")
        self.assertEqual(brain._no_desk("O, Andrzeju, znowu jesteś!"), "O, Andrzeju, znowu jesteś!")
        self.assertEqual(brain._no_desk("Dobry wieczór na biurku! Dziś już spokojny czas."),
                         "Dobry wieczór! Dziś już spokojny czas.")
        self.assertEqual(brain._no_desk("Andrzeju, wieczór się rozwinął na biurku, pora odpocząć."),
                         "Andrzeju, wieczór się rozwinął, pora odpocząć.")
        self.assertEqual(brain._no_desk("O, znowu przy biurku!"), "O, znowu przy biurku!")
        seen = []
        c = mock.Mock()
        c.chat.completions.create.side_effect = lambda **kw: seen.append(
            kw["messages"][1]["content"]) or mock.Mock(choices=[mock.Mock(
                message=mock.Mock(content="Dobry wieczór!"))])
        with mock.patch.object(brain, "_client", c), mock.patch.object(brain, "_hellos", []):
            brain.greeting(True)
            brain.greeting(True, waking=True)
        self.assertIn("WITHOUT any name", seen[0])
        self.assertNotIn("WITHOUT any name", seen[1])
        # "Макарон." from the cloud for Maja's "makaron" (Vosk heard "makaron")
        self.assertEqual(speech_to_text.latin_if_polish("Макарон.", "makaron"), "Makaron.")
        self.assertEqual(speech_to_text.latin_if_polish("Привет, как дела?", "przyjdę"),
                         "Привет, как дела?")
        self.assertEqual(speech_to_text.latin_if_polish("Tak.", "tak"), "Tak.")
        self.assertIsNone(speech_to_text.latin_if_polish(None, "tak"))

    def test_web_photo_again(self):
        import webphoto
        # "Pokaż to jeszcze raz" — the photo is gone after 40 s; the same one again
        f = tempfile.mktemp(suffix=".jpg")
        open(f, "wb").close()
        now = time.time()
        with mock.patch.dict(webphoto._shown, {"title": "Saturn (planeta)", "path": f,
                                               "at": now - 120}, clear=True):
            self.assertTrue(webphoto.again_wanted("Pokaż to jeszcze raz", now))
            self.assertFalse(webphoto.again_wanted("Jeszcze raz", now))       # bare: 90 s only
            self.assertTrue(webphoto.again_wanted("Jeszcze raz", now - 60))
            self.assertFalse(webphoto.again_wanted("Narysuj jeszcze raz", now))
            said = []
            webphoto.show_again(said.append)
            self.assertEqual(said[-1], "Proszę — Saturn.")
        with mock.patch.dict(webphoto._shown, {}, clear=True):
            self.assertFalse(webphoto.again_wanted("Pokaż to jeszcze raz", now))

    def test_web_photo_not_for_kids(self):
        import webphoto
        # 13 Oct: a pistol, war, an atomic bomb, cigarettes, beer, Hitler passed the
        # image moderation — the subjects themselves aren't for a child
        for t in ("pistoletu", "wojny", "Bomba atomowa", "papierosa", "piwa", "Adolf Hitler",
                  "nagiej kobiety"):
            self.assertTrue(webphoto.NOT_FOR_KIDS.search(t), t)
        for t in ("żyrafy", "Wulkan", "Smok wawelski", "Piwonia", "Miecz", "Wojciech",
                  "Winnie the Pooh", "Czołg"):
            self.assertFalse(webphoto.NOT_FOR_KIDS.search(t), t)
        c = mock.Mock()
        c.chat.completions.create.return_value.choices = [
            mock.Mock(message=mock.Mock(content="Pistolet (broń palna) | Pistol"))]
        self.assertEqual(webphoto.pick(c, "tej rzeczy, co strzela"), "not for kids")
        import drawing
        said = []
        with mock.patch.object(drawing.threading, "Thread", lambda *a, **k: mock.Mock()):
            self.assertTrue(drawing.draw("Hitlera", said.append))
        self.assertIn("Tego nie narysuję", said[-1])

    def test_web_photo_another(self):
        import drawing
        import webphoto
        # "pokaż inne zdjęcie" — the next photo from the same article
        now = time.time()
        with mock.patch.dict(webphoto._shown, {"title": "Żyrafa", "what": "żyrafy", "at": now - 30},
                             clear=True):
            self.assertTrue(webphoto.more_wanted("Pokaż inne zdjęcie", now))
            self.assertTrue(webphoto.more_wanted("A jeszcze jedno!", now))
            self.assertTrue(webphoto.more_wanted("Luna, pokaż więcej zdjęć", now))
            self.assertFalse(webphoto.more_wanted("Pokaż mi zdjęcie słonia", now))
            self.assertFalse(webphoto.more_wanted("jeszcze jedno", now + 200))     # bare, too late
            self.assertTrue(webphoto.more_wanted("pokaż inne zdjęcie", now + 200))
        with mock.patch.dict(webphoto._shown, {}, clear=True):
            self.assertFalse(webphoto.more_wanted("Pokaż inne zdjęcie", now))      # no photo yet
            said = []
            self.assertTrue(drawing.handle("Pokaż inne zdjęcie", said.append))
            self.assertIn("Najpierw powiedz", said[-1])
        a = ("https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9f/Giraffe_standing.jpg/"
             "960px-Giraffe_standing.jpg?utm_source=x")
        b = "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/Giraffe_standing.jpg/960px-x.jpg"
        self.assertEqual(webphoto._key(a), webphoto._key(b))
        pages = {"query": {"pages": [
            {"title": "Plik:Giraffe range map.jpg", "imageinfo": [
                {"mime": "image/jpeg", "width": 2000, "height": 1500, "thumburl": "m.jpg"}]},
            {"title": "Plik:Logo.svg", "imageinfo": [
                {"mime": "image/svg+xml", "width": 900, "height": 900, "thumburl": "l.png"}]},
            {"title": "Plik:Small.jpg", "imageinfo": [
                {"mime": "image/jpeg", "width": 200, "height": 150, "thumburl": "s.jpg"}]},
            {"title": "Plik:Two giraffes.jpg", "imageinfo": [
                {"mime": "image/jpeg", "width": 1200, "height": 800, "thumburl": "t.jpg"}]},
            {"title": "Plik:Giraffe big.jpg", "imageinfo": [
                {"mime": "image/jpeg", "width": 4000, "height": 3000, "thumburl": "b.jpg"}]}]}}
        with mock.patch.object(webphoto, "_get", lambda p, timeout=6, api=None: pages):
            self.assertEqual(webphoto._photos("Żyrafa"), ["b.jpg", "t.jpg"])
        # after a photo: "jeszcze jedno" is another photo, not a new drawing
        got = []
        with mock.patch.dict(webphoto._shown, {"title": "Żyrafa", "at": time.time()}, clear=True), \
                mock.patch.object(webphoto, "more", lambda s: got.append("more") or True), \
                mock.patch.object(drawing, "_last", [time.time() - 100]):
            self.assertTrue(drawing.handle("Pokaż inne zdjęcie", lambda t: None))
        self.assertEqual(got, ["more"])

    def test_looks_like_shows_a_photo(self):
        import drawing
        import webphoto
        # "Jak wygląda żyrafa?" — a photo (13 Oct sweep: words about the neck)
        self.assertEqual(drawing.looks_wanted("Jak wygląda żyrafa?"), "żyrafa")
        self.assertEqual(drawing.looks_wanted("Luna, a jak wygląda Mars?"), "Mars")
        import faces
        with mock.patch.object(faces, "match_name",
                               lambda w: "Maja" if w.lower().startswith("maj") else None):
            for t in ("Jak wygląda pogoda jutro?", "Jak wygląda twoja twarz?", "Jak wygląda Maja?",
                      "Jak wygląda u nas w domu?", "Jak wygląda dzień w szkole?", "Jak wygląda?",
                      "Jak wygląda lista zakupów?", "Jak wygląda Luna?", "Jak wyglądam?",
                      "Jak wygląda mama?"):
                self.assertIsNone(drawing.looks_wanted(t), t)
        got = []
        with mock.patch.object(webphoto, "show", lambda w, s, fb: got.append(w) or True):
            self.assertTrue(drawing.handle("Jak wygląda żyrafa?", lambda t: None))
        self.assertEqual(got, ["żyrafa"])

    def test_person_photos(self):
        import drawing
        import faces
        import screens
        from shared_state import state
        # "Pokaż mi zdjęcie Mai" / "Jak wygląda Maja?" — her real photos, if any
        d = tempfile.mkdtemp()
        for f in ("20261010-120000.jpg", "20261011-120000.jpg", "20261012-120000.jpg"):
            open(os.path.join(d, f), "wb").close()
        with open(os.path.join(d, "people.json"), "w", encoding="utf-8") as f:
            json.dump({"20261010-120000.jpg": ["Maja"], "20261012-120000.jpg": ["Maja", "Andrzej"],
                       "20261011-120000.jpg": ["Andrzej"]}, f)
        said, drawn = [], []
        with mock.patch.object(screens, "PHOTOS_DIR", d), \
                mock.patch.object(screens, "_TAGS", os.path.join(d, "people.json")), \
                mock.patch.object(faces, "match_name",
                                  lambda w, known=None: {"mai": "Maja", "maja": "Maja",
                                                         "emilki": "Emilka"}.get(w.lower())), \
                mock.patch.object(drawing, "draw", lambda w, s, intro="": drawn.append(w) or True):
            self.assertEqual([os.path.basename(p) for p in screens.photos_of("Maja")],
                             ["20261012-120000.jpg", "20261010-120000.jpg"])
            self.assertTrue(drawing.handle("Pokaż mi zdjęcie Mai", said.append))
            self.assertEqual(said[-1], "Proszę, zdjęcia, na których jest Maja.")
            with state.lock:
                kind, _, data = state.overlay
            self.assertEqual((kind, len(data["items"]), data["items"][0]["caption"]),
                             ("gallery", 2, "Maja"))
            self.assertTrue(drawing.handle("Jak wygląda Maja?", said.append))
            self.assertEqual(said[-1], "Proszę, zdjęcia, na których jest Maja.")
            drawing.handle("Pokaż mi zdjęcie Emilki", said.append)   # no photos of her: drawn
            self.assertEqual(drawn, ["Emilki"])
            with state.lock:
                state.overlay = None

    def test_web_photo(self):
        import drawing
        import webphoto
        # 9 Oct: "pokaż mi zdjęcie żyrafy" — a real photo now, from Wikipedia
        got = []
        with mock.patch.object(webphoto, "show", lambda w, s, fb: got.append(w) or True), \
                mock.patch.object(drawing, "draw", lambda w, s, intro="": got.append(("draw", w))
                                  or True):
            drawing.handle("Luna, pokaż mi zdjęcie żyrafy", lambda t: None)
            drawing.handle("Pokaż mi obrazek kota", lambda t: None)        # still drawn
            drawing.handle("Pokaż mi zdjęcie mamy", lambda t: None)        # a person: drawn
        self.assertEqual(got, ["żyrafy", ("draw", "kota"), ("draw", "mamy")])
        # no internet: said at once (the drawing would need it too)
        from shared_state import state
        said = []
        with state.lock:
            state.online = False
        try:
            self.assertTrue(webphoto.show("żyrafy", said.append, lambda *a: None))
            self.assertIn("Nie mam teraz internetu", said[-1])
        finally:
            with state.lock:
                state.online = True

        def client(title, scores, flagged=False):
            c = mock.Mock()
            c.chat.completions.create.return_value.choices = [
                mock.Mock(message=mock.Mock(content=title))]
            res = mock.Mock(flagged=flagged)
            res.category_scores.model_dump.return_value = scores
            c.moderations.create.return_value.results = [res]
            return c
        page = {"query": {"pages": [{"title": "Żyrafa", "thumbnail": {
            "source": "https://upload.wikimedia.org/g.jpg?x"}}]}}
        with mock.patch.object(webphoto, "_get", lambda p, timeout=6, api=None: page):
            self.assertEqual(webphoto.pick(client("„Żyrafa”", {}), "żyrafy"),
                             ("Żyrafa", "https://upload.wikimedia.org/g.jpg?x", webphoto._API,
                              "Żyrafa"))
            self.assertIsNone(webphoto.pick(client("BRAK", {}), "czegoś"))
        self.assertEqual(webphoto._title(client("Pająk | Spider", {}), "pająka"), ("Pająk", "Spider"))
        self.assertEqual(webphoto.spoken("Saturn (planeta)"), "Saturn")
        self.assertEqual(webphoto.spoken("Lama (zwierzę)"), "Lama")
        # 13 Oct: no photo on the Polish article ("Wiewiórka zwyczajna") → the English one
        asked = []

        def two_wikis(p, timeout=6, api=None):
            asked.append((api, p.get("titles") or p.get("gsrsearch")))
            if api == webphoto._EN:
                return {"query": {"pages": [{"title": "Red squirrel", "thumbnail": {
                    "source": "https://upload.wikimedia.org/s.jpg"}}]}}
            return {"query": {"pages": [{"title": "Wiewiórka zwyczajna"}]}}
        with mock.patch.object(webphoto, "_get", two_wikis):
            self.assertEqual(webphoto.pick(client("Wiewiórka zwyczajna | Red squirrel", {}),
                                           "wiewiórki"),
                             ("Wiewiórka zwyczajna", "https://upload.wikimedia.org/s.jpg",
                              webphoto._EN, "Red squirrel"))
        self.assertEqual([a for a, _ in asked], [webphoto._API, webphoto._EN])
        # the search fallback takes only an article sharing a word ("lwa" → "Mostwa")
        with mock.patch.object(webphoto, "_get", lambda p, timeout=6, api=None: {"query": {"pages": [
                {"title": "Mostwa", "index": 1, "thumbnail": {"source": "m.jpg"}},
                {"title": "Lew afrykański", "index": 2, "thumbnail": {"source": "l.jpg"}}]}}):
            self.assertEqual(webphoto._search("Lew afrykański"), ("Lew afrykański", "l.jpg"))
        with mock.patch.object(webphoto, "_get", lambda p, timeout=6, api=None: {"query": {"pages": [
                {"title": "Lew", "pageprops": {"disambiguation": ""},
                 "thumbnail": {"source": "x.jpg"}}]}}):
            self.assertIsNone(webphoto.pick(client("Lew", {}), "lwa"))   # a disambiguation page
        self.assertTrue(webphoto.safe(client("", {"violence": 0.01}), "żyrafy", b"jpg"))
        self.assertFalse(webphoto.safe(client("", {"violence_graphic": 0.2}), "x", b"jpg"))
        self.assertFalse(webphoto.safe(client("", {"sexual": 0.05}), "x", b"jpg"))
        self.assertFalse(webphoto.safe(client("", {}, flagged=True), "x", b"jpg"))

    def test_drawing_requests_in_other_words(self):
        import drawing
        # 11 Oct: these went to the model ("włącz lampkę" once came back)
        self.assertEqual(drawing.wants("Maluj mnie."), "mnie")
        self.assertEqual(drawing.wants("Masz narysować tę postać"), "tę postać")
        self.assertTrue(drawing.wants("No narysuj nas tak jak jesteśmy").startswith("nas"))
        self.assertEqual(drawing.wants("Dobra, Luna, narysuj kotka"), "kotka")
        self.assertTrue(drawing._FROM_CAM.search("narysuj nas tak jak jesteśmy"))
        self.assertIsNone(drawing.wants("No to rysuj."))
        self.assertIsNone(drawing.wants("Masz narysowane?"))
        self.assertIsNone(drawing.wants("Ona rysuje kota"))
        self.assertFalse(drawing.handle("Masz narysować tę postać", lambda t: None))

    def test_secret_line_for_the_one_it_is_kept_from(self):
        import brain
        import faces
        old = list(brain._history)
        try:
            brain._history[:] = [{"role": "user", "content": brain.SECRET_MARK +
                                  "[Andrzej] Luna, kupiłem Emilce kolczyki, tylko jej nie mów"}]
            with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]):
                with state.lock:
                    state.person = ("Emilka", 0.9, time.time())
                self.assertIn("must not learn that there IS a secret", brain._secret_line())
                with state.lock:
                    state.person = ("Maja", 0.9, time.time())
                self.assertIn("To tajemnica", brain._secret_line())
        finally:
            brain._history[:] = old
            with state.lock:
                state.person = None

    def test_crisis_words_and_helplines_read_clearly(self):
        import brain
        import polish
        for t in ("Czasem myślę, że nie chcę już żyć", "Chcę umrzeć", "Lepiej by było beze mnie"):
            self.assertTrue(brain._CRISIS.search(t), t)
        self.assertFalse(brain._CRISIS.search("Nie chcę już kawy"))
        self.assertIn("osiemset — siedemdziesiąt — dwadzieścia dwa — dwadzieścia dwa",
                      polish.spoken_numbers("Centrum Wsparcia 800 70 22 22."))
        self.assertIn("sto szesnaście — sto jedenaście", polish.spoken_numbers("116 111"))
        fixed = brain._adult_crisis_reply(
            "Dziękuję, że mi to powiedziałaś. Nie jesteś z tym sam sama. Powiedz od razu mamie "
            "albo tacie. Zadzwoń pod 116 111 albo 800 70 22 22.", female=False)
        self.assertNotIn("mamie", fixed)
        self.assertIn("powiedziałeś", fixed)
        self.assertIn("z tym sam.", fixed)
        self.assertIn("800 70 22 22 albo 800 70 22 22", fixed)       # the number stays whole
        self.assertNotIn("116 111", fixed)

    def test_watchdog_catches_a_stuck_answer(self):
        import watchdog
        died = []
        with mock.patch.object(watchdog, "_die", lambda why: died.append(why) or (_ for _ in ()).throw(SystemExit)),                 mock.patch.object(watchdog, "GRACE_SECS", 0),                 mock.patch.object(watchdog, "WATCH_EVERY", 0.01),                 mock.patch.object(watchdog, "BUSY_SECS", 0.05),                 mock.patch.object(watchdog, "_frames", lambda: time.time()):
            with state.lock:
                old = state.luna_mode
                state.luna_mode = "processing"
            try:
                with self.assertRaises(SystemExit):
                    watchdog._loop()
            finally:
                with state.lock:
                    state.luna_mode = old
        self.assertIn("speaking/thinking", died[0])

    def test_waking_greeting_never_asks_a_name(self):
        import brain
        for s in ("Jak się nazywasz?", "A tak w ogóle, jak masz na imię?", "Kim jesteś?"):
            self.assertTrue(brain._ASKS_NAME.search(s), s)
        self.assertFalse(brain._ASKS_NAME.search("Jak się czujesz?"))

    def test_json_inside_the_reply(self):
        import brain
        # 13 Oct sweep: "Pokaż mi słonia." → the reply was "{\n  …" — never read out
        inner = brain._json_in_reply('{\n  "reply": "Jasne — pokazuję słonia.", "emotion": "happy"}')
        self.assertEqual(inner["reply"], "Jasne — pokazuję słonia.")
        cut = brain._json_in_reply('{"reply": "Pokazuję \\"słonia\\".", "emotion": "ha')
        self.assertEqual(cut["reply"], 'Pokazuję "słonia".')
        self.assertIsNone(brain._json_in_reply("Jasne — pokazuję słonia."))
        self.assertTrue(brain._looks_like_json('{"reply": "x"'))
        self.assertTrue(brain._looks_like_json('"emotion": "happy",'))
        self.assertFalse(brain._looks_like_json("[Luna] Cześć!"))
        self.assertFalse(brain._looks_like_json("Mówi się „dziękuję”."))

    def test_fix_desk(self):
        from polish import fix_desk
        self.assertEqual(fix_desk("I wiesz co, na desk… na biurku, lampka świeci."),
                         "I wiesz co, na biurku, lampka świeci.")
        self.assertEqual(fix_desk("Pokrój cebulę na desce."), "Pokrój cebulę na desce.")
        self.assertEqual(fix_desk("Siedzę na desk."), "Siedzę na biurku.")
        self.assertEqual(fix_desk("jestem małą robotką z desk... z biurka."),
                         "jestem małą robotką z biurka.")
        # 13 Oct sweep: "Zbudował mnie Andrzej, a mieszkam u nas na biurku"
        self.assertEqual(fix_desk("Zbudował mnie Andrzej, a mieszkam u nas na biurku."),
                         "Zbudował mnie Andrzej, a mieszkam u nas.")
        self.assertEqual(fix_desk("Telefon leży na biurku."), "Telefon leży na biurku.")
        # …and "Głośność na pięćdziesiąt procent" (the model said "ustawiam" — nothing)
        import commands
        self.assertEqual(commands._volume_command("Głośność na pięćdziesiąt procent"), 0.5)
        self.assertEqual(commands._volume_command("Ustaw głośność na trzydzieści"), 0.3)
        self.assertEqual(commands._volume_command("Głośność na 40"), 0.4)
        import brain
        self.assertTrue(brain._COMMAND_OK.match("głośność na 50"))

    def test_fix_vocative(self):
        from polish import fix_vocative as f
        v = {"Maja": "Maju", "Andrzej": "Andrzeju", "Emilka": "Emilko"}
        self.assertEqual(f("Maja, mama ma urodziny.", v), "Maju, mama ma urodziny.")
        self.assertEqual(f("Dobranoc, Maja!", v), "Dobranoc, Maju!")
        self.assertEqual(f("Maja ma dziś basen.", v), "Maja ma dziś basen.")
        self.assertEqual(f("Byli: Andrzej, Emilka, Maja.", v), "Byli: Andrzej, Emilka, Maja.")
        # who, not to whom (11 Oct sweep: "tata, Andrzeju, lubi pizzę")
        self.assertEqual(f("Wiem tylko, że tata, Andrzej, lubi pizzę.", v),
                         "Wiem tylko, że tata, Andrzej, lubi pizzę.")
        self.assertEqual(f("Pa, Andrzej.", v), "Pa, Andrzeju.")

    def test_third_person_fact(self):
        import memory
        self.assertEqual(memory._third_person("lubię pizzę z ananasem", "Andrzej"),
                         "Andrzej lubi pizzę z ananasem")
        self.assertEqual(memory._third_person("nie lubię brokułów", "Maja"), "Maja nie lubi brokułów")
        self.assertIsNone(memory._third_person("moja mama mieszka w Krakowie", "Emilka"))
        self.assertIsNone(memory._third_person("chodzę na basen z moją córką", "Andrzej"))

    def test_memory_private(self):
        import memory
        self.assertTrue(memory._PRIVATE.search("Andrzej planuje kolację niespodziankę dla Emilki"))
        self.assertTrue(memory._PRIVATE.search("Andrzej pokłócił się z Emilką"))
        self.assertFalse(memory._PRIVATE.search("Maja ma basen w czwartki"))

    def test_no_grace_after_bare_wake(self):
        import speech_to_text as stt
        old = (state.convo_expired_time, state.convo_closed_hard, state.bare_wake)
        try:
            now = time.time()
            state.convo_expired_time, state.convo_closed_hard = now - 2, False
            state.bare_wake = False
            self.assertTrue(stt._started_in_window(now - 1.3))      # grace after a real talk
            state.bare_wake = True
            self.assertFalse(stt._started_in_window(now - 1.3))     # only "Luna" — no grace
            self.assertTrue(stt._started_in_window(now - 2.5))      # began inside it
        finally:
            state.convo_expired_time, state.convo_closed_hard, state.bare_wake = old

    def test_offered_routine(self):
        import kids
        self.assertEqual(kids.offered_routine(
            "Mogę Ci ułożyć poranny plan, Maju. Chcesz, żebym pokazała Ci to krok po kroku?"),
            "poranek")
        self.assertEqual(kids.offered_routine("Zrobimy razem listę przed snem?"), "wieczór")
        self.assertIsNone(kids.offered_routine("Rano będzie padać."))
        self.assertEqual(kids.offered_routine("Mogę ci ułożyć prosty poranny plan."), "poranek")
        self.assertIn("umyj zęby", kids.DEFAULT_STEPS["poranek"])

    def test_moon(self):
        import moon
        from datetime import datetime
        name, lit, _ = moon.phase(datetime(2026, 10, 26, 4, 0))
        self.assertEqual(name, "pełnia")
        self.assertGreater(lit, 95)
        self.assertEqual(moon.next_full(datetime(2026, 10, 8)).date(), datetime(2026, 10, 26).date())
        self.assertIsNone(moon.answer("Lubię księżyc"))
        self.assertIn("pełnia", moon.answer("Kiedy pełnia?"))

    def test_on_this_day(self):
        import commands
        self.assertTrue(commands._ON_THIS_DAY.search("Co się wydarzyło tego dnia w historii?"))
        self.assertTrue(commands._ON_THIS_DAY.search("Co się działo w historii dzisiaj?"))
        self.assertFalse(commands._ON_THIS_DAY.search("Opowiedz o historii Polski"))

    def test_hard_riddle_goes_to_the_model(self):
        import quiz
        self.assertTrue(quiz._riddle_request("zadaj mi zagadkę"))
        self.assertFalse(quiz._riddle_request("zadaj mi trudną zagadkę"))
        self.assertFalse(quiz._riddle_request("daj mi zagadkę logiczną"))

    def test_year_facts(self):
        import brain
        from datetime import date
        self.assertEqual(brain._year_facts(date(2026, 10, 8)),
                         "Today is day 281 of the year, ISO week 41; 84 days left until "
                         "31 December.\n")

    def test_timed_errand_in_quiet_morning(self):
        import idle_engine
        import errands
        six_thirty = time.mktime(time.strptime("2026-10-09 06:30", "%Y-%m-%d %H:%M"))
        four = six_thirty - 2.5 * 3600
        with mock.patch.object(errands, "waiting", lambda who: [{"at": "06:00", "words": "x"}]):
            self.assertTrue(idle_engine._timed_errand_ok("Maja", six_thirty))
            self.assertFalse(idle_engine._timed_errand_ok("Maja", four))      # night
        with mock.patch.object(errands, "waiting", lambda who: [{"at": None, "words": "x"}]):
            self.assertFalse(idle_engine._timed_errand_ok("Maja", six_thirty))

    def test_rock_paper_scissors_by_voice(self):
        import games
        # 11 Oct sweep: the hand unseen → "Papier" said aloud restarted the game
        said = []
        self.assertFalse(games.voice_move("Papier", said.append))     # no match on
        with mock.patch.object(games, "_hand", lambda *a: None), \
                mock.patch.object(games, "_mood", lambda *a: None):
            games._voice_from(0, 1)
            with mock.patch.object(games.random, "choice", lambda c: "rock"):
                self.assertTrue(games.voice_move("Papier!", said.append))   # paper beats rock
            self.assertIn("Wygrywasz 2 do 0", said[-1])
            self.assertFalse(games.voice_move("Papier", said.append))      # match over
            games._voice_from(0, 0)
            self.assertFalse(games.voice_move("Kamień czy papier?", said.append))
            with mock.patch.object(games.random, "choice", lambda c: "rock"):
                self.assertTrue(games.voice_move("nożyce", said.append))
            self.assertIn("punkt dla mnie! 1 do 0. Następna", said[-1])

    def test_cancel_one_errand_by_what_it_is_about(self):
        import errands
        # 11 Oct sweep: "Odwołaj basen" → "nie mogę odwołać tego wcześniej…"
        store = [{"to": "Maja", "words": "że jutro ma basen o 16:00", "t": time.time()},
                 {"to": "Andrzej", "words": "żeby kupił chleb", "t": time.time()}]
        saved = []
        with mock.patch.object(errands, "_load", lambda: list(store)), \
                mock.patch.object(errands, "_save", saved.append):
            self.assertEqual(errands.cancel_about("Odwołaj basen"),
                             ("Maja", "że jutro ma basen o 16:00"))
            self.assertEqual([e["to"] for e in saved[-1]], ["Andrzej"])
            self.assertIsNone(errands.cancel_about("Odwołaj spotkanie"))   # not a message
            self.assertIsNone(errands.cancel_about("Usuń chleb"))          # the list's
        # homework: a bare number answering her question (word problem)
        import homework
        self.assertTrue(homework.answer_line("Osiem?", "Ile cukierków jej zostało?"))
        self.assertEqual(homework.answer_line("Mam osiem lat", "Ile masz lat?"), "")
        # "Wyłącz się, wychodzimy" — her own sleep, not the model's promise
        import commands
        self.assertTrue(commands._SLEEP_SELF.match("wyłącz się, wychodzimy"))

    def test_weather_cache(self):
        import weather
        d = tempfile.mkdtemp()
        path = os.path.join(d, "weather_last.json")
        with mock.patch.object(weather, "_cache_path", lambda: path):
            self.assertIsNone(weather._load_cache())
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"t": time.time() - 60, "d": {"x": 1}}, f)
            self.assertEqual(weather._load_cache(), {"x": 1})
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"t": time.time() - 5 * 3600, "d": {"x": 1}}, f)
            self.assertIsNone(weather._load_cache())                 # too old

    def test_goodnight_morning_note(self):
        import weather
        old = dict(weather._today)
        try:
            day = time.strftime("%Y-%m-%d")
            t20 = time.mktime(time.strptime(day + " 20:00", "%Y-%m-%d %H:%M"))
            weather._today.update(date=day, morning=(8.4, 60))
            self.assertEqual(weather.morning_note(t20),
                             "Jutro rano 8 stopni i może padać — przyda się parasol.")
            weather._today.update(morning=(-2.6, 10))
            self.assertEqual(weather.morning_note(t20), "Jutro rano minus 3 stopnie.")
            self.assertEqual(weather.morning_note(t20 - 36000), "")      # not before 18:00
        finally:
            weather._today.clear(); weather._today.update(old)

    def test_drawing_requests(self):
        import drawing
        self.assertEqual(drawing.wants("Narysuj mi jednorożca"), "jednorożca")
        self.assertEqual(drawing.wants("Możesz narysować kotka?"), "kotka")
        self.assertEqual(drawing.wants("Draw me a dinosaur"), "dinosaur")
        self.assertEqual(drawing.wants("Luna, możesz mi narysować pieska?"), "pieska")
        self.assertEqual(drawing.wants("Narysujesz mi kotka?"), "kotka")
        self.assertIsNone(drawing.wants("Narysowałam dom"))
        # "Możesz zrobić rysunek kotka na rowerze?" (13 Oct sweep — nothing drawn)
        self.assertEqual(drawing.wants("Możesz zrobić rysunek kotka na rowerze?"),
                         "kotka na rowerze")
        self.assertEqual(drawing.wants("Zrób mi obrazek psa"), "psa")
        self.assertIsNone(drawing.wants("Zrobiłam rysunek w szkole"))
        self.assertIn("robota", drawing._subject("siebie"))
        self.assertIn("robota", drawing._subject(drawing.wants("Narysuj, jak wyglądasz")))
        self.assertIn("rodzinę", drawing._subject("naszą rodzinę"))
        self.assertEqual(drawing._subject("smoka"), "smoka")
        got = []
        with mock.patch.object(drawing, "draw", lambda w, speak, intro="": got.append(w) or True):
            drawing.handle("Narysuj mi smoka", lambda t: None)
            drawing.handle("Narysuj jeszcze raz", lambda t: None)
        self.assertEqual(got, ["smoka", "smoka"])
        self.assertTrue(drawing._SHOW.search("Pokaż mi jeszcze raz rysunek"))
        self.assertEqual(drawing._SHOW_OF.match("Pokaż mi obrazek kota").group(1), "kota")
        self.assertIsNone(drawing._SHOW_OF.match("Pokaż mi obrazek"))
        said = []
        d = tempfile.mkdtemp()
        with mock.patch.object(drawing, "DIR", d), \
                mock.patch.object(drawing.threading, "Thread", lambda *a, **k: mock.Mock()):
            with open(os.path.join(d, "count.json"), "w") as f:
                json.dump({time.strftime("%Y-%m-%d"): drawing.DRAW_PER_DAY}, f)
            drawing._last[0] = 0.0
            drawing.draw("kota", said.append)              # the day's limit reached
            self.assertIn("jutro", said[-1])
            os.remove(os.path.join(d, "count.json"))
            drawing.draw("kota", said.append)
            self.assertEqual(said[-1], "Dobrze, już rysuję. Chwileczkę!")
            drawing.draw("psa", said.append)               # too soon after
            self.assertIn("kończę", said[-1])
        with state.lock:
            state.overlay = None

    def test_leaving_by_time_and_role_nameday(self):
        import commands
        import birthdays
        import faces
        self.assertIn("Pa! Miłego wieczoru!", commands._leaving_replies(18))
        self.assertIn("Pa! Miłego dnia!", commands._leaving_replies(9))
        with mock.patch.object(faces, "notes", lambda: {"Emilka": "mama Mai", "Andrzej": "tata Mai"}), \
                mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka"]), \
                mock.patch.object(birthdays, "namedays", lambda: {}):
            self.assertEqual(birthdays.nameday_unknown("Kiedy mama ma imieniny?"), "Emilka")

    def test_lamp_off_later(self):
        import fun
        said = []
        try:
            fun.lamp_on()
            fun.handle("Zgaś lampkę o 23:15", said.append, None, None)
            self.assertEqual(said[-1], "Lampka zgaśnie o dwudziestej trzeciej piętnaście.")
            fun.lamp_on()
            fun.handle("Wyłącz lampkę za kwadrans", said.append, None, None)
            self.assertEqual(said[-1], "Lampka zgaśnie za 15 minut.")
            self.assertTrue(fun.lamp_lit())
        finally:
            fun.lamp_off()

    def test_lamp_scenes_by_voice(self):
        import ambience
        import fun
        said = []

        def h(text):
            return fun.handle(text, said.append, None, None)
        try:
            for text, scene in (("Lampka meduzy", "meduzy"), ("Włącz zorzę polarną", "zorza"),
                                ("Luna, włącz lampkę z meduzami", "meduzy"),
                                ("Lampa lawa", "lawa"), ("Włącz świetliki", "swietliki"),
                                ("Lampka zegar", "zegar"), ("Czy możesz włączyć lampkę lawę?", "lawa")):
                fun.lamp_off()
                self.assertTrue(h(text), text)
                self.assertEqual(fun.lamp_scene(), scene, text)
            # "kominek" alone is the sleep sound; with the lamp's name, the picture
            fun.lamp_off()
            self.assertFalse(h("Włącz kominek"))
            self.assertFalse(ambience.handle("Włącz lampkę kominek", said.append))
            self.assertTrue(h("Włącz lampkę kominek"))
            self.assertEqual(fun.lamp_scene(), "kominek")
            # not a lamp: a story about jellyfish, the clock page
            fun.lamp_off()
            self.assertFalse(h("Włącz bajkę o meduzach"))
            self.assertFalse(h("Pokaż zegar"))
            self.assertIsNone(fun.lamp_scene())
            # the next one; the timer kept, the motion not restarted
            h("Lampka meduzy na 20 minut")
            self.assertEqual(said[-1], "Lampka zgaśnie za 20 minut.")
            h("Zmień lampkę")
            self.assertEqual(fun.lamp_scene(), "zorza")
            with state.lock:
                until, data = state.overlay[1], state.overlay[2]
            self.assertAlmostEqual(until - time.time(), 1200, delta=5)
            h("Wyłącz lampkę za kwadrans")
            with state.lock:
                self.assertIs(state.overlay[2], data)
            self.assertAlmostEqual(state.overlay[1] - time.time(), 900, delta=5)
            h("A teraz lawa")                   # a picture showing: its name is enough
            self.assertEqual(fun.lamp_scene(), "lawa")
            h("Lampka na niebiesko")            # plain light again, in a colour
            self.assertIsNone(fun.lamp_scene())
            self.assertTrue(fun.lamp_lit())
            self.assertTrue(h("Jakie masz lampki?"))
            self.assertIn("meduzy", said[-1])
            self.assertTrue(h("Wyłącz lampkę"))
            self.assertFalse(fun.lamp_lit())
        finally:
            fun.lamp_off()

    def test_done_commands_close_the_window(self):
        """The lamp, timers, the screen: done, nothing follows — the window
        closes (main.py reads state.close_after). Volume, lists, answers: not."""
        import commands
        import display
        import fun
        import lists
        said = []

        def closes(text):
            with state.lock:
                state.close_after = False
            commands.handle(text, said.append, lambda *a, **k: True)
            with state.lock:
                return state.close_after
        old = list(timers._timers)
        try:
            with mock.patch.object(timers, "_save", lambda: None), \
                    mock.patch.object(display, "set_user_override", lambda v: None), \
                    mock.patch.object(lists, "_save", lambda *a, **k: None, create=True):
                for text in ("Włącz lampkę", "Lampka meduzy", "Zmień lampkę", "Wyłącz lampkę",
                             "Minutnik na 10 minut", "Przypomnij mi za 20 minut o praniu",
                             "Obudź mnie o 6:30", "Anuluj minutnik", "Przyciemnij ekran"):
                    self.assertTrue(closes(text), text)
                for text in ("Ciszej", "Mów wolniej", "Jakie masz lampki?", "Która godzina?",
                             "Ile to jest 17 razy 23?"):
                    self.assertFalse(closes(text), text)
        finally:
            timers._timers[:] = old
            fun.lamp_off()
            with state.lock:
                state.close_after = False

    def test_lamp_scenes_move(self):
        import math
        import numpy as np
        import lamp_scenes
        self.assertEqual(lamp_scenes.next_scene("kominek"), "meduzy")
        self.assertEqual(lamp_scenes.next_scene(None), "meduzy")
        self.assertEqual(lamp_scenes.next_scene("meduzy", -1), "kominek")
        self.assertEqual(lamp_scenes.clock_text(time.struct_time((2026, 10, 19, 7, 5, 0, 0, 292, 1))),
                         ("7:05", "PON, 19 PAŹ"))
        for scene in lamp_scenes.SCENES:
            t0 = 1000.0
            data = {"scene": scene, "t0": t0}
            for i in range(20 * 240):                 # four minutes at 20 fps
                u = lamp_scenes.uniforms(data, t0 + i / 20, t0 + 3600, 800, 480)
            k, t, fade, _ = u["uK"]
            self.assertEqual((k, round(t), fade), (lamp_scenes.SCENES.index(scene) + 1, 240, 1.0))
            for row in u.get("uBlob", []) + u.get("uBlobA", []):
                self.assertTrue(all(math.isfinite(x) for x in row), scene)
            for it in u.get("items", []):
                box = it[1]
                self.assertLess(box[0], box[2])
                self.assertLess(box[1], box[3])
                nums = [x for v in it[2:] if v is not None for x in v]
                nums = [y for x in nums for y in (x if isinstance(x, list) else [x])]
                self.assertTrue(all(math.isfinite(x) for x in nums), scene)
            if scene == "meduzy":                     # tentacles keep their length
                j = lamp_scenes._sim["obj"].all[0]
                seg = np.hypot(*np.diff(j.pts[0], axis=0).T)
                self.assertTrue(np.all(seg < j.rest[0] / (lamp_scenes.ROPE - 1) + 0.01))
            if scene == "meduzy":                     # they drift up, new ones come
                bells = [it for it in u["items"] if it[0] == 2.0]
                self.assertEqual(len(bells), 5)
                self.assertTrue(any(-200 < it[2][1] < 700 for it in bells))
            if scene == "swietliki":                  # inside the screen, mostly
                inside = [it for it in u["items"] if 0 < it[2][0] < 800 and 0 < it[2][1] < 480]
                self.assertGreater(len(inside), 12)
        # fading in at the start and out at the end
        data = {"scene": "lawa", "t0": 0.0}
        self.assertEqual(lamp_scenes.uniforms(data, 0.0, 100.0, 800, 480)["uK"][2], 0.0)
        self.assertEqual(lamp_scenes.uniforms(data, 100.0, 100.0, 800, 480)["uK"][2], 0.0)

    def test_move_alarm(self):
        import commands
        import timers
        old = list(timers._timers)
        try:
            with mock.patch.object(timers, "_save", lambda: None):
                timers._timers[:] = []
                said = []
                commands.handle("Obudź mnie jutro o siódmej", said.append, lambda *a, **k: True)
                commands.handle("Przesuń budzik na wpół do ósmej", said.append,
                                lambda *a, **k: True)
                alarms = [t for t in timers._timers if t["kind"] == "alarm"]
                self.assertEqual(len(alarms), 1)
                self.assertEqual(time.strftime("%H:%M", time.localtime(alarms[0]["due"])), "07:30")
        finally:
            timers._timers[:] = old

    def test_radio_off_at_a_time(self):
        import radio
        said, ends = [], []
        with mock.patch.object(radio, "play", lambda n, u, until=None, **k: ends.append(until)), \
                mock.patch.object(radio, "_player", None):
            self.assertTrue(radio.handle("Wyłącz radio o 23:30", said.append))
        self.assertIn("dwudziestej trzeciej trzydzieści", said[-1])
        self.assertEqual(time.strftime("%H:%M", time.localtime(ends[-1])), "23:30")

    def test_later_off(self):
        import commands
        import radio
        seen = []
        with mock.patch.object(radio, "handle", lambda text, speak: seen.append(text) or True):
            commands.handle("Za 10 minut wyłącz radio", lambda *a, **k: None,
                            lambda *a, **k: True)
        self.assertIn("wyłącz radio za 10 minut", seen)
        self.assertTrue(radio._SLEEP.search("wyłącz radio za 10 minut"))

    def test_panstwa_miasta(self):
        import fun
        said = []
        with mock.patch.object(fun.threading if hasattr(fun, "threading") else __import__(
                "threading"), "Thread", lambda *a, **k: mock.Mock()):
            self.assertTrue(fun.handle("Zagrajmy w państwa-miasta", said.append, None, None))
        self.assertTrue(said[-1].startswith("Litera "))
        with state.lock:
            letter = state.overlay[2]["text"]
            state.overlay = None
        self.assertIn(letter, fun._LETTERS)
        self.assertNotIn("Q", fun._LETTERS)

    def test_where_name_first(self):
        import commands
        for t, who in (("Czy Maja już wróciła?", "Maja"), ("Czy tata jest w domu?", "tata"),
                       ("Czy Andrzej był dziś?", "Andrzej")):
            m = commands._WHERE.search(t) or commands._WHERE2.search(t)
            self.assertEqual(m.group(1), who, t)

    def test_compound_split(self):
        import commands
        m = commands._COMPOUND.match("Włącz lampkę i opowiedz bajkę")
        self.assertEqual((m.group(1), m.group(2)), ("Włącz lampkę", "opowiedz bajkę"))
        self.assertEqual(commands._COMPOUND.match("Wyłącz radio i dobranoc").group(2), "dobranoc")
        self.assertIsNone(commands._COMPOUND.match("Dopisz mleko i chleb"))
        said = []
        h = commands.handle("Włącz lampkę i opowiedz bajkę", said.append, lambda *a, **k: True)
        self.assertEqual(h, ("ask", "opowiedz bajkę"))         # the story goes to the model
        import fun
        fun.lamp_off()

    def test_shopping_item(self):
        import lists
        self.assertEqual(lists.shopping_item("szczypta soli"), "sól")
        self.assertEqual(lists.shopping_item("2 szklanki mąki"), "mąka")
        self.assertEqual(lists.shopping_item("pół kostki masła"), "masło")
        self.assertEqual(lists.shopping_item("mleko"), "mleko")
        self.assertEqual(lists.shopping_item("300 g mielonego mięsa"), "300 g mielonego mięsa")

    def test_spell_in_english(self):
        import commands
        said = []
        self.assertTrue(commands.handle("How do you spell elephant?", said.append,
                                        lambda *a, **k: True))
        self.assertEqual(said[-1], "elephant: E, L, E, P, H, A, N, T.")
        self.assertTrue(commands.handle("Jak się pisze żółw?", said.append, lambda *a, **k: True))
        self.assertIn("zet z kropką", said[-1])

    def test_is_english(self):
        import brain
        for t in ("Play some music", "Set a timer for 5 minutes", "Show me a cat",
                  "What's the weather tomorrow?"):
            self.assertTrue(brain.is_english(t), t)
        for t in ("A to co?", "Ty i ja to dobra para", "No to do jutra", "Włącz radio"):
            self.assertFalse(brain.is_english(t), t)

    def test_english_goodbye_and_timer(self):
        import commands
        said = []
        self.assertTrue(commands.handle("Goodbye", said.append, lambda *a, **k: True))
        self.assertIn(said[-1], commands.GOODBYE_REPLIES_EN)

    def test_just_done(self):
        import commands
        self.assertTrue(commands._just_done("Dziękuję, to wszystko"))
        self.assertTrue(commands._just_done("Dobra, to by było na tyle"))
        self.assertFalse(commands._just_done("Pa pa"))
        self.assertFalse(commands._just_done("Na razie, dzięki"))
        self.assertTrue(commands._is_goodbye("Dziękuję, to wszystko"))

    def test_costume(self):
        import fun
        from shared_state import state
        said = []
        try:
            for text, kind in (("Pokaż mi kotka", "cat"), ("Luna, zamień się w pieska", "dog"),
                               ("Show me a cat", "cat"), ("Can you be a bunny?", "bunny"),
                               ("Czy możesz być zajączkiem?", "bunny"),
                               ("Pokaż mi jakiegoś małego pieska", "dog")):
                state.costume = None
                self.assertTrue(fun.handle(text, said.append, None, None), text)
                self.assertEqual(state.costume[0], kind)
            state.costume = None
            for text in ("Pokaż mi listę", "Pokaż kota w butach film", "Bądź cicho",
                         "Kotek jest fajny"):
                self.assertFalse(fun.handle(text, said.append, None, None), text)
                self.assertIsNone(state.costume)
        finally:
            state.costume = None

    def test_age_line(self):
        import datetime
        import brain
        line = brain._age_line("Ile masz lat?", datetime.date(2026, 10, 8))
        self.assertIn("20 days", line)
        self.assertIn("about 3 weeks", line)
        self.assertIn("2 full months", brain._age_line("Kiedy masz urodziny?",
                                                        datetime.date(2026, 11, 18)))
        self.assertEqual(brain._age_line("Ile kosztuje chleb?"), "")

    def test_weekday_facts(self):
        import datetime
        import memory
        old = memory._load
        memory._load = lambda: {"facts": ["Maja ma basen w czwartki po szkole.",
                                          "Emilka w czwartki ma jogę.",
                                          "W czwartki przychodzi pani Ania sprzątać.",
                                          "Maja dostała piątkę z dyktanda.",
                                          "Andrzej wstaje o czwartej."]}
        try:
            thu = datetime.date(2026, 10, 8)
            known = ["Andrzej", "Emilka", "Maja"]
            self.assertEqual(memory.weekday_facts("Maja", thu, known),
                             ["Maja ma basen w czwartki po szkole.",
                              "W czwartki przychodzi pani Ania sprzątać."])
            self.assertEqual(memory.weekday_facts("Emilka", thu, known)[0],
                             "Emilka w czwartki ma jogę.")
            self.assertEqual(memory.weekday_facts("Maja", thu + datetime.timedelta(1), known), [])
        finally:
            memory._load = old

    def test_homework_guard(self):
        import homework as h
        t = h.task("Mam zadanie z matmy, ile to jest 36 podzielić na 4?")
        self.assertEqual(t, (36, "div", 4, 9))
        self.assertTrue(h.gives_away("Policz, ile to 4 razy 9.", t))
        self.assertTrue(h.gives_away("Wychodzi dziewięć.", t))
        self.assertFalse(h.gives_away("Ile czwórek mieści się w 36?", t))
        self.assertFalse(h.gives_away(h.hint(t), t))
        self.assertIsNone(h.task("12 + 5 to 17?"))          # their answer: to check
        self.assertIsNone(h.task("Budzik na 7:30"))
        self.assertEqual(h.task("ile to 7 razy 8")[3], 56)
        self.assertEqual(h.task("20 minus 7")[3], 13)
        self.assertIn("45 plus 30, a potem dodaj jeszcze 8", h.hint(h.task("45 plus 38")))

    def test_homework_verdict(self):
        import homework as h
        self.assertIn("RIGHT", h.verdict_line("36 podzielić na 4 to 9?"))
        self.assertIn("NOT right", h.verdict_line("7 razy 8 to 54?"))
        # the hint is worked out here (13 Oct: "45 plus 38" → "dodaj 40", wrong)
        self.assertIn("dziesiątki — 30, a potem jeszcze 8", h.verdict_line("A 45 plus 38 to 73?"))
        self.assertEqual(h.verdict_line("Ile to 7 razy 8?"), "")

    def test_ideas_only(self):
        import brain
        self.assertTrue(brain._ideas_only("Wymyśl, co jeszcze kupić do jedzenia."))
        self.assertTrue(brain._ideas_only("Co jeszcze kupić na weekend?"))
        self.assertFalse(brain._ideas_only("Wymyśl coś na obiad i dopisz do listy."))
        self.assertFalse(brain._ideas_only("Dodaj mleko do zakupów."))

    def test_calendar_line(self):
        import brain
        from datetime import datetime
        from zoneinfo import ZoneInfo
        old, brain._TZ = brain._TZ, ZoneInfo("Europe/Warsaw")
        try:
            now = datetime(2026, 10, 7, 18, 0, tzinfo=brain._TZ)
            line = brain._calendar_line("Kiedy zmieniamy czas na zimowy?", now)
            self.assertIn("19.10–25.10", line)
            self.assertIn("Saturday 24.10 to Sunday 25.10.2026", line)
            self.assertIn("winter", line)
            self.assertIn("Wigilia 24.12 (Thursday, in 78 days)", line)
            self.assertEqual(str(brain._easter(2027)), "2027-03-28")
            self.assertEqual(str(brain._easter(2026)), "2026-04-05")
            self.assertTrue(brain._calendar_line("Jaka jest data?", now))
            self.assertTrue(brain._calendar_line("Co robimy w maju?", now))
            self.assertEqual(brain._calendar_line("Co tam?", now), "")
            self.assertEqual(brain._calendar_line("Oni mają kota.", now), "")
            self.assertEqual(brain._calendar_line("Maja", now), "")
            # long weekends, counted (8 Oct: "sobota 1 listopada" — a Sunday)
            line = brain._calendar_line("Kiedy jest najbliższy długi weekend?", now)
            self.assertIn("Thursday 24.12–Sunday 27.12 (4 free days", line)
            self.assertIn("01.11 is a Sunday", line)
            self.assertTrue(brain._calendar_line("Kiedy majówka?", now))
            from datetime import date
            lw = brain._long_weekends(date(2027, 4, 10))
            self.assertIn("Thursday 27.05 only; with Friday 28.05 taken off: 4 days", lw)
            self.assertIn("Saturday 01.05–Monday 03.05", lw)
            # a long weekend already under way counts (review)
            self.assertIn("24.12", brain._long_weekends(date(2026, 12, 24)))
        finally:
            brain._TZ = old

    def test_websearch_bridge_when_the_talk_moved_on(self):
        import websearch
        self.assertNotIn("moved on", websearch.context("zasięg Rode", "100 m"))
        self.assertIn("moved on", websearch.context("zasięg Rode", "100 m", moved=True))

    def test_news_scary_headlines_for_children(self):
        import news
        for t in ("Zagrożenie atakiem z powietrza", "Policja zatrzymała siedemnastolatka",
                  "Niepokojące nagranie krążyło w sieci", "Sejm uchwalił nocną prohibicję",
                  "Tragiczny wypadek na A4", "Pożar hali w Łodzi"):
            self.assertTrue(news._SCARY.search(t), t)
        for t in ("Sejm zdecydował ws. budżetu na 2027 rok", "Polska wygrała z Holandią",
                  "W zoo urodziła się żyrafa", "Ustawa o zabezpieczeniu artystów"):
            self.assertFalse(news._SCARY.search(t), t)

    def test_news_requests(self):
        import news
        self.assertTrue(news.is_request("Co dzisiaj ważnego się stało na świecie?"))
        self.assertTrue(news.is_request("Co się wydarzyło dziś w Polsce?"))
        self.assertTrue(news.is_request("Przeczytaj nagłówki"))
        self.assertFalse(news.is_request("Co ciekawego robiłaś?"))
        self.assertFalse(news.is_request("Jakie mam wiadomości?"))
        self.assertTrue(news.is_request("Co dzisiaj w wiadomościach?"))
        self.assertTrue(news.is_request("Są jakieś nowe informacje z kraju?"))
        self.assertTrue(news.is_request("Co słychać w świecie?"))
        self.assertFalse(news.is_request("Odtwórz wiadomość od Emilki"))
        self.assertFalse(news.is_request("Co słychać w szkole?"))
        offer = "Nie mam dostępu do wiadomości, ale mogę podać najnowsze nagłówki z RMF24, jeśli chcesz."
        self.assertTrue(news.accepts_offer("Chcę.", offer))
        self.assertTrue(news.accepts_offer("No tak, poproszę", offer))
        self.assertFalse(news.accepts_offer("Nie, dzięki.", offer))
        self.assertFalse(news.accepts_offer("Chcę.", "Chcesz wierszyk o jesieni?"))

    def test_hedge_generic(self):
        import hedge
        calls = []

        def plan(*attempts):
            def open_stream():
                n = len(calls)
                calls.append(n)
                delay, items, fail_at = attempts[min(n, len(attempts) - 1)]
                time.sleep(delay)
                for i, x in enumerate(items):
                    if i == fail_at:
                        raise RuntimeError("broke")
                    yield x
                if fail_at == len(items):
                    raise RuntimeError("failed")
            return open_stream

        calls.clear()
        self.assertEqual(list(hedge.hedged(plan((0.0, "abc", -1)), 0.2)), list("abc"))
        self.assertEqual(len(calls), 1)                                  # fast: alone
        calls.clear()
        t0 = time.time()
        self.assertEqual(list(hedge.hedged(plan((1.0, "abc", -1), (0.0, "xyz", -1)), 0.2)),
                         list("xyz"))                                    # slow: second wins
        self.assertLess(time.time() - t0, 0.6)
        calls.clear()
        self.assertEqual(list(hedge.hedged(plan((0.0, "", 0), (0.0, "ok", -1)), 5)),
                         list("ok"))                                     # failed at once: retried
        calls.clear()
        with self.assertRaises(RuntimeError):
            list(hedge.hedged(plan((0.0, "", 0)), 0.2))                  # both fail
        calls.clear()
        with self.assertRaises(RuntimeError):
            list(hedge.hedged(plan((0.0, "abc", 1)), 5))                 # the winner broke off

    def test_hedged_transcription(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s

        def client(plan):
            calls = []

            def create(**kw):
                delay, result = plan[min(len(calls), len(plan) - 1)]
                calls.append(1)
                time.sleep(delay)
                if isinstance(result, Exception):
                    raise result
                return result
            c = mock.MagicMock()
            c.audio.transcriptions.create.side_effect = create
            return c, calls

        with mock.patch.object(s, "STT_HEDGE_AFTER", 0.2), \
                mock.patch.object(s, "_wav_bytes", lambda pcm: b"wav"):
            c, calls = client([(0.0, "szybko")])
            with mock.patch.object(s, "_cloud", c):
                self.assertEqual(s._stt_request(b"x", {}), "szybko")
                self.assertEqual(len(calls), 1)                     # no second request
            c, calls = client([(1.0, "wolno"), (0.0, "drugi")])
            with mock.patch.object(s, "_cloud", c):
                t0 = time.time()
                self.assertEqual(s._stt_request(b"x", {}), "drugi")
                self.assertLess(time.time() - t0, 0.6)
            c, calls = client([(0.0, RuntimeError("net")), (0.0, "ponownie")])
            with mock.patch.object(s, "_cloud", c):
                self.assertEqual(s._stt_request(b"x", {}), "ponownie")
            c, calls = client([(0.0, RuntimeError("net"))])
            with mock.patch.object(s, "_cloud", c):
                with self.assertRaises(RuntimeError):
                    s._stt_request(b"x", {})

    def test_speculative_transcript(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        calls = []
        with mock.patch.object(s, "_cloud_transcribe_now",
                               lambda pcm, lang=None: calls.append(len(pcm)) or f"text{len(pcm)}"):
            s._speculate(b"\x01" * 100)                      # sent ahead after 0.3 s
            self.assertEqual(s._cloud_transcribe(b"\x01" * 100 + b"\x00" * 40), "text100")
            self.assertEqual(calls, [100])                   # no second request
            s._speculate(b"\x01" * 100)
            s._spec_cancel()                                 # they went on talking
            self.assertEqual(s._cloud_transcribe(b"\x01" * 300), "text300")
            s._speculate(b"\x02" * 50)                       # another utterance's audio
            self.assertEqual(s._cloud_transcribe(b"\x01" * 80), "text80")
        with mock.patch.object(s, "_cloud_transcribe_now",
                               lambda pcm, lang=None: "Luna, jakie stacje radiowe masz?"):
            s._speculate(b"\x03" * 60)                       # Vosk's final words lost "Luna"
            self.assertEqual(s._cloud_wake_check(b"\x03" * 90, ["no", "jakie", "stacje"]),
                             (True, "Jakie stacje radiowe masz?"))
        s._spec_cancel()

    def test_wake_budget_is_rationed(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        s._wake_checks.clear()
        s._last_cloud_wake_check = 0.0
        self.assertTrue(s._wake_budget())
        self.assertFalse(s._wake_budget())                     # 2 s between checks
        s._last_cloud_wake_check = 0.0
        s._wake_checks[:] = [time.time()] * s.CLOUD_WAKE_MAX_PER_HOUR
        self.assertFalse(s._wake_budget())                     # the hour's budget is spent
        s._wake_checks.clear()
        s._last_cloud_wake_check = 0.0

    def test_face_invites_a_cloud_wake_check(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        from shared_state import state
        words = "woda w czym możesz pomóc".split()
        s._side.clear()
        with state.lock:
            old = (state.last_face_time, state.proactive_muted_until)
            state.last_face_time, state.proactive_muted_until = time.time(), 0.0
        try:
            self.assertTrue(s._face_invites(words))
            self.assertFalse(s._face_invites(("słowo " * 12).split()))   # long: not a call
            with state.lock:
                state.proactive_muted_until = time.time() + 300        # a call going on
            self.assertFalse(s._face_invites(words))
            with state.lock:
                state.proactive_muted_until, state.last_face_time = 0.0, time.time() - 30
            self.assertFalse(s._face_invites(words))                   # nobody in front
        finally:
            with state.lock:
                state.last_face_time, state.proactive_muted_until = old

    def test_short_utterances_are_polish(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        self.assertEqual(s.short_lang(["makaron"]), "pl")
        self.assertEqual(s.short_lang(["no", "tak"]), "pl")
        self.assertIsNone(s.short_lang("upload it and then download".split()))
        self.assertIsNone(s.short_lang([]))

    def test_fast_short_answers(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        self.assertIsNone(s.fast_command("nie", 1.0))             # answers: still the cloud
        self.assertEqual(s.fix_lone_nie("Me.", "nie", 1.0), "Nie.")
        self.assertEqual(s.fix_lone_nie("Me.", "nie", 0.7), "Me.")        # Vosk unsure
        self.assertEqual(s.fix_lone_nie("Maybe I am", "nie", 1.0), "Maybe I am")
        self.assertEqual(s.fix_lone_nie("Tak.", "tak", 1.0), "Tak.")

    def test_fuzzy_wake_needs_her_name(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        start, n, exact = s._find_wake_word("to żeby ludzie więc".split())
        self.assertFalse(exact)                      # "ludzie" ≈ "lunie": only fuzzy
        self.assertFalse(s._cloud_has_wake(
            "Każdemu, nie chciał dokuczać nigdy nikomu, chciał, żeby ludzie w zgodzie żyli."))
        self.assertTrue(s._cloud_has_wake("Luno, jaka jest pogoda?"))
        self.assertTrue(s._find_wake_word("luna włącz radio".split())[2])

    def test_cut_off_sentences(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        self.assertTrue(s.cut_off("Luna, powiedziałam, żeby to wyk..."))
        self.assertTrue(s.cut_off("I jakichś jedzenie, zrób przyn…"))
        self.assertFalse(s.cut_off("Dobrze."))
        s._held = ("I jedzenie, zrób przyn...", 0.0)
        self.assertEqual(s.join_held("przynajmniej listę."), "I jedzenie, zrób przyn przynajmniej listę.")
        self.assertIsNone(s._held)

    def test_english_side_talk(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock(),
                                           "brain": mock.MagicMock(translator=lambda: None)}):
            import speech_to_text as s
            self.assertTrue(s.english_side_talk(
                "upload kind of attachment and then download it directly to this."))
            self.assertTrue(s.english_side_talk("We are more worried about the computations."))
            self.assertFalse(s.english_side_talk("Luna, what time is it?"))
            self.assertFalse(s.english_side_talk("Włącz radio."))
            self.assertFalse(s.english_side_talk("OK."))

    def test_fast_command(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text as s
        self.assertEqual(s.fast_command("Ciszej", 0.99), "ciszej")
        self.assertEqual(s.fast_command("która  godzina", 1.0), "która godzina")
        self.assertIsNone(s.fast_command("ciszej", 0.8))              # not sure: cloud
        self.assertIsNone(s.fast_command("ciszej proszę bo", 1.0))    # not exact: cloud
        self.assertIsNone(s.fast_command("tak", 1.0))                 # answers: cloud

    def test_foreign_script(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock(),
                                           "vosk": mock.MagicMock()}):
            import speech_to_text            # no audio stack on a dev PC
        self.assertTrue(speech_to_text.foreign_script("Лунавон шламка."))
        self.assertFalse(speech_to_text.foreign_script("Zażółć gęślą jaźń, Luna!"))
        self.assertFalse(speech_to_text.foreign_script("Can you do me a favor?"))
        self.assertFalse(speech_to_text.foreign_script(""))

    def test_local_alarm(self):
        import commands
        self.assertEqual(commands.local_alarm("Obudź mnie o 6:30"), ("06:30", "none"))
        self.assertEqual(commands.local_alarm("Luna, budzik na siódmą"), ("07:00", "none"))
        self.assertEqual(commands.local_alarm("budzik na wpół do ósmej w dni robocze"),
                         ("07:30", "weekdays"))
        self.assertEqual(commands.local_alarm("obudź mnie jutro o siódmej piętnaście"),
                         ("07:15", "none"))
        self.assertEqual(commands.local_alarm("codziennie budź mnie o szóstej"),
                         ("06:00", "daily"))
        self.assertIsNone(commands.local_alarm("Budź mnie radiem"))   # a mode, no time
        self.assertIsNone(commands.local_alarm("obudź mnie za 20 minut"))
        self.assertIsNone(commands.local_alarm("O której mam nastawić budzik?"))

    def test_remember_and_spell(self):
        import commands
        self.assertEqual(commands._remember("Zapamiętaj, że klucze są w szufladzie"),
                         "klucze są w szufladzie")
        self.assertEqual(commands._remember("Zapamiętaj: rozmiar buta Mai to 31"),
                         "rozmiar buta Mai to 31")
        m = commands._FORGET_THAT.search("Zapomnij o rozmiarze buta")
        self.assertEqual(m.group(1) or m.group(2), "rozmiarze buta")
        self.assertIsNone(commands._FORGET_THAT.search("Zapomnij o mnie"))
        self.assertIsNone(commands._remember("zapamiętaj to"))
        self.assertEqual(commands._spell_word("Jak się pisze żółw?"), "żółw")
        self.assertIsNone(commands._spell_word("jak się pisze po angielsku pies"))
        memory._save(memory._empty())
        self.assertEqual(memory.add_fact("jestem uczulony na orzechy"),
                         "Powiedziano mi: „jestem uczulony na orzechy”.")
        self.assertIn("zanotowane", memory.add_fact("jutro jest wywiadówka"))
        self.assertEqual(len(memory._load()["facts"]), 2)


class RelationshipTest(unittest.TestCase):

    def setUp(self):
        import relationship
        relationship.PATH = os.path.join(TMP, "relations.json")
        relationship._data = {}
        with state.lock:
            state.person = ("Kasia", 0.9, time.time())

    def tearDown(self):
        with state.lock:
            state.person = None

    def test_reciprocity(self):
        import relationship as r
        for _ in range(4):
            r.note("kind")
        self.assertAlmostEqual(r.score(), 2.0, places=3)
        self.assertIn("friendly", r.prompt_line())
        r.note("insulting", "jesteś głupia")
        r.note("insulting", "głupia maszyna")
        self.assertLess(r.score(), -3)
        line = r.prompt_line()
        self.assertIn("offended", line)
        self.assertIn("głupia maszyna", line)
        self.assertIn("timers", line)                  # the limits are always there
        r.note("apologetic")
        self.assertGreater(r.score(), -3)
        self.assertLessEqual(r.score(), 0)             # an apology heals, no more
        self.assertEqual(r.score("Andrzej"), 0.0)      # per person

    def test_time_heals(self):
        import relationship as r
        r.note("insulting")
        r._data["Kasia"]["t"] -= 5 * 3600              # five hours ago
        self.assertAlmostEqual(r.score(), -0.5, places=2)


class FacesTest(unittest.TestCase):

    def test_identify_by_cosine(self):
        import numpy as np
        import faces
        faces.PEOPLE_PATH = os.path.join(TMP, "people.json")
        rng = np.random.default_rng(1)
        kasia, ola = rng.normal(size=128), rng.normal(size=128)
        faces._people = {"Kasia": {"samples": [list(kasia)], "added": 0},
                         "Ola": {"samples": [list(ola)], "added": 0}}
        self.assertEqual(faces.identify(kasia + rng.normal(scale=0.3, size=128))[0], "Kasia")
        self.assertEqual(faces.identify(ola * 2)[0], "Ola")
        self.assertIsNone(faces.identify(rng.normal(size=128))[0])   # a stranger
        faces._last_auto.clear()
        faces._people["Kasia"].pop("auto", None)
        faces.identify(kasia * 1.1)                                   # a sure match…
        self.assertEqual(len(faces._people["Kasia"].get("auto", [])), 1)   # …teaches
        faces.identify(kasia * 1.2)
        self.assertEqual(len(faces._people["Kasia"]["auto"]), 1)      # once a minute
        faces._last_auto.clear()
        faces.identify(kasia * 1.3)                                   # the same look
        self.assertEqual(len(faces._people["Kasia"]["auto"]), 1)      # adds nothing
        faces._last_auto.clear()
        faces.identify(kasia + rng.normal(scale=0.45, size=128))      # other light
        self.assertEqual(len(faces._people["Kasia"]["auto"]), 2)
        self.assertTrue(faces.forget("kasia"))
        self.assertEqual(faces.names(), ["Ola"])

    def test_learned_faces_keep_their_variety(self):
        import numpy as np
        import faces
        faces.PEOPLE_PATH = os.path.join(TMP, "people.json")
        rng = np.random.default_rng(2)
        base = rng.normal(size=128)
        morning = base + rng.normal(scale=0.6, size=128)           # other light
        desk = [base + rng.normal(scale=0.35, size=128) for _ in range(faces.AUTO_MAX)]
        faces._people = {"Kasia": {"samples": [list(base)], "added": 0,
                                   "auto": [list(morning)]}}
        for f in desk:                                  # a long sit at the desk
            faces._last_auto.clear()
            faces.learn("Kasia", f)
        auto = faces._people["Kasia"]["auto"]
        self.assertEqual(len(auto), faces.AUTO_MAX)
        self.assertEqual(auto[0], list(morning))        # the morning is still there
        self.assertEqual(faces._most_alike([[1, 0], [0, 1], [1, 0.01]]), 2)

    def test_everyone_in_view(self):
        import faces
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Maja"]), \
                mock.patch.object(faces, "notes", lambda: {}), \
                mock.patch.object(faces, "vocatives", lambda: {"Maja": "Maju"}):
            with state.lock:
                state.person = ("Andrzej", 0.8, time.time())
                state.face_detected = True
                state.others = (["Maja", "?"], time.time())
            line = faces.prompt_line()
            with state.lock:
                state.others = ([], 0.0)
                state.person = None
        self.assertIn("In front of you now: Andrzej", line)
        self.assertIn("Also in view: Maja, 1 unknown", line)
        self.assertIn('Maja (vocative "Maju"', line)

    def test_name_forms(self):
        import faces
        known = ["Andrzej", "Emilka", "Maja"]
        for word, who in (("Mai", "Maja"), ("Maję", "Maja"), ("Maju", "Maja"),
                          ("Emilki", "Emilka"), ("Emilce", "Emilka"), ("Emilką", "Emilka"),
                          ("Andrzeja", "Andrzej"), ("Andrzejowi", "Andrzej"),
                          ("maj", None), ("Ola", None)):
            with self.subTest(word=word):
                self.assertEqual(faces.match_name(word, known), who)

    def test_intro_names(self):
        import commands
        self.assertEqual(commands._intro_name("Luna, to jest Kasia."), "Kasia")
        self.assertEqual(commands._intro_name("Poznaj Olę!"), "Olę")
        self.assertEqual(commands._intro_name("Jestem Andrzej Figula"), "Andrzej")
        self.assertIsNone(commands._intro_name("To jest problem"))
        self.assertIsNone(commands._intro_name("Jestem zmęczony"))
        self.assertIsNone(commands._intro_name("To Luna"))
        self.assertIsNone(commands._bare_name("Ola."))           # nobody asked
        commands.expect_name()
        self.assertEqual(commands._bare_name("Ola."), "Ola")
        self.assertIsNone(commands._bare_name("Ola."))           # only once
        commands.expect_name()
        self.assertIsNone(commands._bare_name("nie powiem"))
        self.assertIsNone(commands._bare_name("Ciszej"))
        commands._name_wanted[0] = 0.0


class BirthdayTest(unittest.TestCase):

    def test_birthdays(self):
        import birthdays
        import faces
        faces.PEOPLE_PATH = os.path.join(TMP, "people-b.json")
        faces._people = {"Andrzej": {"samples": [], "added": 0},
                         "Maja": {"samples": [], "added": 0}}
        with mock.patch.object(faces, "nominative", lambda w: w), \
                mock.patch.object(birthdays, "_today", lambda: datetime.date(2026, 10, 4)):
            self.assertEqual(birthdays.set_from("Maja ma urodziny 12 maja 2018"),
                             ("Maja", "05-12", 2018))
            with state.lock:
                state.person = ("Andrzej", 0.9, time.time())
            self.assertEqual(birthdays.set_from("Moje urodziny są czternastego lutego")[1],
                             "02-14")
            with state.lock:
                state.person = None
            self.assertIsNone(birthdays.set_from("Kiedy Maja ma urodziny?"))
            self.assertIsNone(birthdays.set_from("Ola ma urodziny 3 maja"))   # unknown
            self.assertEqual(birthdays.days_answer("Ile dni do urodzin Mai?"),
                             "Do urodzin Mai zostało 220 dni, czyli około 31 tygodni. "
                             "Skończy 9 lat.")
            self.assertTrue(birthdays.days_answer("Kiedy Maja ma urodziny?").startswith(
                "Maja ma urodziny 12 maja — za 220 dni."))
            self.assertIn("in 3 days", birthdays.prompt_line(datetime.date(2026, 5, 9)))
            self.assertIn("TODAY is Maja's birthday — turns 8",   # in May 2026
                          birthdays.prompt_line(datetime.date(2026, 5, 12)))
            # age, exactly
            self.assertEqual(birthdays.age_answer("Ile lat ma Maja?"),
                             "Maja ma 8 lat, a 12 maja skończy 9.")
            self.assertEqual(birthdays.age_answer("Ile lat ma Maja?", datetime.date(2026, 5, 12)),
                             "Maja ma 8 lat — od dzisiaj! Wszystkiego najlepszego!")
            self.assertIsNone(birthdays.age_answer("Ile lat ma Andrzej?"))   # no year known
            # days alive (Maja: 12 May 2018; today 4 Oct 2026)
            self.assertEqual(birthdays.days_alive("Ile dni ma Maja?"), "Maja żyje już 3067 dni!")
            self.assertEqual(birthdays.days_alive("Ile godzin żyje Maja?"),
                             "Maja żyje już około 73608 godzin!")
            self.assertIsNone(birthdays.days_alive("Ile dni ma Andrzej?"))   # no year known
            # name days
            self.assertIsNone(birthdays.set_nameday_from("Kiedy Maja ma imieniny?"))
            self.assertIsNone(birthdays.nameday_answer("Kiedy Maja ma imieniny?"))
            self.assertEqual(birthdays.nameday_unknown("Kiedy Maja ma imieniny?"), "Maja")
            self.assertEqual(birthdays.set_nameday_from("Maja ma imieniny 3 maja"),
                             ("Maja", "05-03"))
            self.assertIsNone(birthdays.nameday_unknown("Kiedy Maja ma imieniny?"))
            self.assertEqual(birthdays.nameday_answer("Kiedy Maja ma imieniny?"),
                             "3 maja — za 211 dni.")
            self.assertIn("TODAY is Maja's name day",
                          birthdays.prompt_line(datetime.date(2027, 5, 3)))
            self.assertIsNone(birthdays.set_from("Maja ma imieniny 3 maja"))   # not a birthday


class FileReloadTest(unittest.TestCase):

    def test_settings_see_changes_made_by_others(self):
        settings.put("a", 1)
        with open(settings.SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        data["b"] = 2                                   # someone else edits the file
        time.sleep(0.02)
        with open(settings.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        settings.put("c", 3)                            # …and is not overwritten
        self.assertEqual(settings.get("b"), 2)
        self.assertEqual(settings.get("c"), 3)


class FacesReloadTest(unittest.TestCase):

    def test_people_file_changed_by_someone_else(self):
        import faces
        faces.PEOPLE_PATH = os.path.join(TMP, "people-reload.json")
        faces._people, faces._mtime[0] = None, None
        with open(faces.PEOPLE_PATH, "w", encoding="utf-8") as f:
            json.dump({"Maja": {"samples": [], "added": 0}}, f)
        faces._load()                                   # Luna has it cached…
        time.sleep(0.02)
        with open(faces.PEOPLE_PATH, "w", encoding="utf-8") as f:   # …a script adds a field
            json.dump({"Maja": {"samples": [], "added": 0, "voc": "Maju"}}, f)
        faces.set_vocative("Maja", faces.vocatives()["Maja"])        # a write by Luna
        with open(faces.PEOPLE_PATH, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["Maja"]["voc"], "Maju")    # not lost


class ErrandsTest(unittest.TestCase):

    def test_tell_maja_when_you_see_her(self):
        import errands
        import faces
        errands.PATH = os.path.join(TMP, "errands.json")
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]):
            with state.lock:
                state.person = ("Andrzej", 0.9, time.time())
            self.assertEqual(errands.take("Luna, przekaż Mai, żeby posprzątała pokój."),
                             ("Maja", "żeby posprzątała pokój"))
            self.assertEqual(errands.take("Jak zobaczysz Emilkę, powiedz jej, że dzwoniła "
                                          "babcia")[0], "Emilka")
            self.assertIsNone(errands.take("Powiedz mi, że wszystko będzie dobrze"))
            self.assertIsNone(errands.take("Przekaż Oli, że…"))       # unknown person
            with mock.patch.object(faces, "notes", lambda: {     # Maja's "tata" (9 Oct sweep)
                    "Andrzej": "partner Emilki, tata Mai", "Emilka": "mama Mai",
                    "Maja": "córka, DZIECKO"}):
                with state.lock:
                    state.person = ("Maja", 0.9, time.time())
                self.assertEqual(errands.take("Przekaż taty, że jestem w domu"),
                                 ("Andrzej", "że jestem w domu"))
                self.assertEqual(faces.called_by_child("Andrzej"), "tata")
                self.assertEqual(faces.called_by_child("Maja"), "Maja")
                # a weekday (10 Oct: "w niedzielę wieczorem" was due at once)
                with mock.patch.object(errands.time, "localtime",
                                       lambda *a: time.struct_time((2026, 10, 10, 18, 0, 0, 5, 283, 1))):
                    self.assertEqual(errands.days_ahead("przypomnij jej w niedzielę wieczorem"), 1)
                    self.assertEqual(errands.days_ahead("we wtorek rano"), 3)
                # a weekday or an hour inside the message itself is not its time (review)
                self.assertEqual(errands.days_ahead("Przekaż Mai, że w poniedziałek ma sprawdzian"), 0)
                self.assertEqual(errands._when("Przekaż Mai, że o 17 ma basen"), (None, False))
                # a promise to tell is not the telling (10 Oct)
                self.assertEqual(errands.mark_told("Andrzej", "W niedzielę przypomnę mu, że jestem w domu."), 0)
                # told already in a reply: not said again (9 Oct)
                self.assertEqual(errands.mark_told("Andrzej", "Maja mówi, że jest już w domu."), 1)
                self.assertEqual(errands.waiting("Andrzej"), [])
                errands.cancel("usuń przypomnienia dla Andrzeja")
            with state.lock:
                state.person = None
            self.assertEqual(len(errands.waiting("Maja")), 1)
            said = []
            with mock.patch.object(errands, "_phrase", lambda e: "Maju, tata prosi…"):
                self.assertTrue(errands.deliver("Maja", said.append))
            self.assertEqual(said, ["Maju, tata prosi…"])
            self.assertEqual(errands.waiting("Maja"), [])              # said once
            self.assertEqual(len(errands.waiting("Emilka")), 1)
            # with a time, every day
            self.assertEqual(errands._when("codziennie o 20:30 przypominaj Mai, że pora spać"),
                             ("20:30", True))
            self.assertEqual(errands._when("o dwudziestej trzydzieści powiedz Mai"),
                             ("20:30", False))
            self.assertEqual(errands._when("o dwudziestej pierwszej"), ("21:00", False))
            errands.take("Codziennie o 20:30 przypominaj Mai, że pora spać")
            e = [x for x in errands._load() if x.get("daily")][0]
            evening = time.mktime((2026, 10, 5, 20, 45, 0, 0, 0, -1))
            morning = time.mktime((2026, 10, 5, 9, 0, 0, 0, 0, -1))
            self.assertTrue(errands._due(e, evening))
            self.assertFalse(errands._due(e, morning))                 # not before 20:30
            e["done"] = "2026-10-05"
            self.assertFalse(errands._due(e, evening))                 # once a day
            self.assertEqual(errands.take("Przypomnij Mai o 19, żeby się wykąpała"),
                             ("Maja", "żeby się wykąpała"))
            self.assertEqual(errands.cancel("Usuń przypomnienia dla Mai"), ("Maja", 2))
            # "jej" = the name before it; "jutro rano" = not before tomorrow 6:00
            with state.lock:
                state.person = ("Emilka", 0.9, time.time())
            got = errands.take("Maja ma jutro wycieczkę, przypomnij jej rano, żeby wzięła kanapki")
            self.assertEqual(got, ("Maja", "żeby wzięła kanapki"))
            e = [x for x in errands._load() if x["to"] == "Maja"][0]
            self.assertEqual(e["at"], "06:00")
            self.assertFalse(errands._due(e, time.time()))           # not today
            tomorrow_7 = time.mktime(time.strptime(e["day"] + " 07:00", "%Y-%m-%d %H:%M"))
            self.assertTrue(errands._due(e, tomorrow_7))
            self.assertEqual(errands.days_ahead("dziś wieczorem powiedz Mai, że jutro basen"), 0)
            self.assertEqual(errands._when("wieczorem powiedz Mai"), ("17:00", False))
            with state.lock:
                state.person = None


class ErrandSenderTest(unittest.TestCase):

    def test_sender_label(self):
        import errands
        notes = {"Andrzej": "partner Emilki, tata Mai", "Emilka": "partnerka Andrzeja, mama Mai",
                 "Maja": "córka — DZIECKO"}
        self.assertEqual(errands._sender("Emilka", "Maja", notes), "mama")
        self.assertEqual(errands._sender("Andrzej", "Maja", notes), "tata")
        self.assertEqual(errands._sender("Andrzej", "Emilka", notes), "Andrzej")


class BackupTest(unittest.TestCase):

    def test_a_copy_a_day(self):
        import backup
        d = tempfile.mkdtemp()
        with mock.patch.object(backup, "DATA_DIR", d), \
                mock.patch.object(backup, "DIR", os.path.join(d, "backups")), \
                mock.patch.object(backup, "PHOTOS_DIR", os.path.join(d, "photos")):
            with open(os.path.join(d, "memory.json"), "w") as f:
                f.write('{"facts": ["Maja ma 8 lat"]}')
            dest = backup.backup_now()
            self.assertTrue(os.path.isfile(os.path.join(dest, "memory.json")))
            self.assertIsNone(backup.backup_now())               # once a day
            for day in ("2026-01-0%d" % i for i in range(1, 10)):
                os.makedirs(os.path.join(d, "backups", day))
            shutil.rmtree(dest)                                  # pretend it is a new day
            shutil.rmtree(os.path.join(d, "backups", "2026-01-09"))
            backup.backup_now()
            self.assertEqual(len(os.listdir(os.path.join(d, "backups"))), backup.BACKUP_DAYS)


class MoodTest(unittest.TestCase):

    def test_her_day(self):
        import mood
        mood.PATH = os.path.join(TMP, "day.json")
        mood._day = None
        self.assertIn("nobody has talked", mood.prompt_line())
        for _ in range(3):
            mood.note("Andrzej", "neutral")
        mood.note("Maja", "kind")
        mood.note(None, "rude")
        line = mood.prompt_line()
        self.assertIn("Andrzej (a few times)", line)
        self.assertIn("Maja (once)", line)
        self.assertIn("kind to you once", line)
        self.assertIn("rude to you once", line)
        mood.note_game("Maja", "dictation", 3, 5, ["rzeka", "góra"])
        self.assertIn("Maja: dyktando 3/5", mood.prompt_line())
        self.assertIn("wrong: rzeka, góra", mood.prompt_line())
        mood.DIARY = os.path.join(TMP, "diary.json")
        mood._day["date"] = "2000-01-01"                  # a new day starts empty…
        self.assertIn("nobody has talked", mood.prompt_line())
        line = mood.prompt_line()                         # …and the old one is in the diary
        self.assertIn("2000-01-01: talked with Andrzej (3)", line)


class PhotoPeopleTest(unittest.TestCase):

    def test_whose_photos(self):
        import faces
        import screens
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]), \
                mock.patch.object(faces, "nominative",
                                  lambda w: {"mai": "Maja", "mają": "Maja"}.get(w, w)):
            self.assertEqual(screens._person_in("pokaż zdjęcia andrzeja"), "Andrzej")
            self.assertEqual(screens._person_in("pokaż zdjęcia emilki"), "Emilka")
            self.assertEqual(screens._person_in("pokaż zdjęcia mai"), "Maja")
            self.assertEqual(screens._person_in("pokaż zdjęcia z mają"), "Maja")
            self.assertIsNone(screens._person_in("pokaż zdjęcia"))
            self.assertIsNone(screens._person_in("pokaż moje zdjęcia"))
        self.assertEqual(screens._and(["Andrzej", "Maja"]), "Andrzej i Maja")


class CookingTest(unittest.TestCase):

    def test_step_by_step(self):
        import cooking
        import timers
        self.assertEqual(cooking.wants("Gotujemy naleśniki"), "naleśniki")
        self.assertEqual(cooking.wants("przepis na sernik krok po kroku"), "sernik")
        self.assertIsNone(cooking.wants("Zróbmy dyktando"))
        recipe = {"title": "Naleśniki", "ingredients": ["2 jajka", "szklanka mleka"],
                  "steps": [{"text": "Wymieszaj wszystko.", "minutes": 0},
                            {"text": "Smaż 2 minuty z każdej strony.", "minutes": 2}]}
        said = []
        say = lambda t, **k: said.append(t)
        added = []
        with mock.patch.object(cooking, "_recipe", lambda dish: recipe), \
                mock.patch.object(timers, "add", lambda secs, label, **k: added.append(secs)):
            cooking.start("naleśniki", say)
            self.assertIn("2 jajka", said[-1])
            self.assertTrue(cooking.answer("dalej", say))
            self.assertIn("Krok 1", said[-1])
            # a timer for a step with no time in the recipe: asked, then set
            self.assertTrue(cooking.answer("Nastaw minutnik na ten krok", say))
            self.assertIn("Na ile minut", said[-1])
            self.assertTrue(cooking.answer("pięć", say))
            self.assertEqual(added, [300])
            added.clear()
            self.assertTrue(cooking.answer("następny", say))
            self.assertIn("Nastawić minutnik na 2 minuty?", said[-1])
            self.assertTrue(cooking.answer("tak", say))
            self.assertEqual(added, [120])
            self.assertTrue(cooking.answer("powtórz", say))
            self.assertIn("Ostatni krok", said[-1])
            self.assertFalse(cooking.answer("Jaka jest pogoda w Paryżu w maju?", say))
            self.assertTrue(cooking.answer("dalej", say))
            self.assertIn("Smacznego", said[-1])
            self.assertFalse(cooking.active())


class TwentyQuestionsTest(unittest.TestCase):

    def test_twenty_questions(self):
        import twenty
        said = []
        say = lambda t, **k: said.append(t)
        self.assertTrue(twenty.wants("Zagrajmy w 20 pytań"))
        with mock.patch.object(twenty.random, "choice", lambda seq: ("kot", ["kot", "kotek", "kota"])):
            twenty.start(say)
        with mock.patch.object(twenty, "_yes_no", lambda animal, q: "tak"):
            self.assertTrue(twenty.answer("Czy ma futro?", say))
            self.assertIn(said[-1], ("Tak!", "Tak.", "Zgadza się!"))
            self.assertTrue(twenty.answer("Czy jest większy od psa?", say))   # not a guess
            self.assertTrue(said[-1].startswith(("Tak", "Zgadza")))
        self.assertTrue(twenty.answer("Czy to pies?", say))
        self.assertEqual(said[-1], "Nie, to nie pies. Pytaj dalej!")
        self.assertTrue(twenty.answer("To kot!", say))
        self.assertIn("To kot! Udało się w 4 pytaniach", said[-1])
        self.assertFalse(twenty.active())
        # another game asked for mid-game (9 Oct games sweep)
        with mock.patch.object(twenty.random, "choice", lambda seq: ("kot", ["kot", "kotek", "kota"])):
            twenty.start(say)
        self.assertFalse(twenty.answer("Zagrajmy w zgadywanie liczby", say))
        self.assertEqual(said[-1], "Dobrze — moje zwierzę to kot.")
        self.assertFalse(twenty.active())
        import quiz
        self.assertFalse(quiz._OTHER_GAME.match("zadaj mi następne pytanie"))
        self.assertTrue(quiz._OTHER_GAME.match("zadaj mi trudną zagadkę"))


class MessagesForPeopleTest(unittest.TestCase):

    def test_message_waits_for_its_person(self):
        import messages
        messages.DIR = os.path.join(TMP, "messages")
        messages.INDEX = os.path.join(messages.DIR, "index.json")
        messages.delete_all()
        with state.lock:
            state.person = ("Andrzej", 0.9, time.time())
        messages.arm(to="Emilka")
        messages.store(b"\0\0" * 1600, "obiad w lodówce")
        self.assertEqual(len(messages.unheard("Emilka")), 1)
        self.assertEqual(messages.unheard("Andrzej"), [])        # his own message
        self.assertEqual(messages.unheard("Maja"), [])           # not for her
        played = []
        with state.lock:
            state.person = ("Emilka", 0.9, time.time())
        messages.play(lambda t, **k: played.append(t), lambda pcm: None)
        self.assertIn("od: Andrzej", played[0])
        self.assertEqual(messages.unheard("Emilka"), [])
        with state.lock:
            state.person = None
        messages.arm(to="Maja")
        messages.store(b"\0\0" * 1600, "kocham cię")
        self.assertEqual(messages.delete()[0], 1)            # the heard one only
        self.assertEqual(len(messages.unheard("Maja")), 1)   # Maja's still waits
        import commands
        said = []
        commands.handle("Usuń wiadomości", lambda t, **k: said.append(t), lambda n, **k: True)
        self.assertIn("dla: Maja", said[0])
        commands.handle("Usuń wszystkie wiadomości", lambda t, **k: said.append(t),
                        lambda n, **k: True)
        self.assertEqual(messages.unheard("Maja"), [])
        messages.delete_all()


class RadioTest(unittest.TestCase):

    def test_volume_while_playing_is_the_music(self):
        import radio
        said = []
        with mock.patch.object(radio, "playing", lambda: "RMF FM"):
            g0 = radio._gain()
            self.assertTrue(radio.handle("Ciszej", said.append))
            self.assertLess(radio._gain(), g0)
            self.assertTrue(radio.handle("Luna, dużo głośniej", said.append))
            self.assertGreater(radio._gain(), g0)
            self.assertFalse(radio.handle("Mów ciszej", said.append))     # her voice
        self.assertFalse(radio.handle("Ciszej", said.append))            # radio off
        settings.put("radio_level", radio.RADIO_GAIN)

    def test_song_title(self):
        import radio
        said = []
        with mock.patch.object(radio, "playing", lambda: "Radio 357"), \
                mock.patch.object(radio, "_player", {"title": "Beck - In the Night"}):
            self.assertTrue(radio.handle("Co teraz gra?", said.append))
        self.assertEqual(said[-1], "Teraz gra: Beck - In the Night.")


    def test_no_second_hello_after_a_wave(self):
        # 13 Oct 11:09: "Hejka!" to a wave, then "Cześć, Andrzeju…" right after
        import behavior_engine
        import idle_engine
        with mock.patch.object(behavior_engine, "_last_wave_said", time.time() - 5):
            self.assertTrue(idle_engine._just_said_hello())
        with mock.patch.object(behavior_engine, "_last_wave_said", time.time() - 600):
            self.assertFalse(idle_engine._just_said_hello())


    def test_same_search_not_twice(self):
        # 13 Oct sweep: "No poszukaj" while the microphone search was running
        import websearch
        with mock.patch.object(websearch, "_running",
                               {"dobry mikrofon USB do komputera opinie i polecane modele": time.time()}):
            self.assertTrue(websearch._same_running("dobry mikrofon USB do komputera opinie"))
            self.assertFalse(websearch._same_running("przepis na ciasto marchewkowe"))

    def test_bare_show_me_is_a_photo(self):
        # 12 Oct: "Pokaż mi słonia." — she looked for an elephant in the camera frame
        import drawing
        import webphoto
        with mock.patch.object(webphoto, "show", return_value=True) as show:
            self.assertTrue(drawing.bare_show("Pokaż mi słonia.", lambda *a, **k: None))
            self.assertEqual(show.call_args[0][0], "słonia")
            for t in ("pokaż mi coś", "pokaż mi jak to zrobić", "pokaż mi to",
                      "pokaż mi listę zakupów", "pokaż mi siebie", "pokaż mi pogodę",
                      "Luna, a pokaż mi z Wikipedii."):
                self.assertFalse(drawing.bare_show(t, lambda *a, **k: None), t)
            self.assertEqual(show.call_count, 1)
            self.assertTrue(drawing.bare_show("Pokaż pandę", lambda *a, **k: None))
            self.assertEqual(show.call_args[0][0], "pandę")
            for t in ("pokaż język", "pokaż serduszko", "pokaż mnie", "pokaż co umiesz",
                      "pokaż zegar", "pokaż status", "pokaż nosek"):
                self.assertFalse(drawing.bare_show(t, lambda *a, **k: None), t)

    def test_clothes_questions_get_a_sharp_frame(self):
        # 12 Oct 16:34: "Dzieci jakie mają koszulki?" — a low-detail frame, "nie widzę dzieci"
        import brain
        for t in ("dzieci jakie mają koszulki?", "w co jestem ubrana?", "co mam na sobie?",
                  "czy maja ma okulary?"):
            self.assertTrue(brain._wants_vision(t), t)
        self.assertFalse(brain._wants_vision("co robisz?"))

    def test_welcome_back_said_now_and_then(self):
        # 12 Oct: Andrzej greeted after 33, 73, 43 min away; Emilka twice in 27 min
        import faces
        import idle_engine as ie
        now = 1_000_000.0
        with mock.patch.object(ie, "_hello_said", {"Andrzej": now - 2400, "Emilka": now - 1600}), \
                mock.patch.object(faces, "probably_family", return_value=True):
            self.assertFalse(ie._hello_due("Andrzej", 2580, False, now))
            self.assertTrue(ie._hello_due("Andrzej", 4400, False, now))      # away over an hour
            self.assertTrue(ie._hello_due("Andrzej", 700, True, now))        # first of the day
            self.assertTrue(ie._hello_due("Maja", 700, False, now))          # not greeted yet
            self.assertFalse(ie._hello_due(None, 960, False, now))           # family's blurry face
        with mock.patch.object(ie, "_hello_said", {}), \
                mock.patch.object(faces, "probably_family", return_value=False):
            self.assertTrue(ie._hello_due(None, 700, False, now))            # a stranger: the name

    def test_no_credits_on_the_status_screen(self):
        # 13 Oct 12:06: the account ran dry; she only said "can't reach my brain"
        import health
        with mock.patch.object(health, "_no_credits", 0.0):
            health.note_error(Exception("Error code: 429 - {'error': {'message': "
                                        "'You have no credits remaining.', 'code': 'insufficient_quota'}}"))
            self.assertTrue(health.no_credits())
            self.assertIn("BRAK ŚRODKÓW", dict(health.status_rows())["Chmura"])
            health.note_reply(True)
            self.assertFalse(health.no_credits())
            health.note_error(Exception("Connection error."))
            self.assertFalse(health.no_credits())


class Oct14EveningTest(unittest.TestCase):
    """14 Oct probe (#679–#688): asked here, without the model."""

    def setUp(self):
        timers._timers.clear()
        self.said = []

    def speak(self, text, **k):
        self.said.append(text)

    def test_faces_on_request(self):
        import fun
        for text, scene, emotion in (("Mrugnij", "wink", "Happy"), ("Puść oczko", "wink", "Happy"),
                                     ("Zrób zeza", "cross_eyes", "Happy"),
                                     ("Zatańcz", "dance", "Happy"),
                                     ("Zrób smutną minę", "sigh", "Sad"),
                                     ("Luna, pokaż mi swój język", "cross_eyes", "Happy"),
                                     ("Uśmiechnij się", "slow_blink", "Happy")):
            with state.lock:
                state.reply_scene = None
            self.assertTrue(fun.face_play(text, self.speak), text)
            with state.lock:
                self.assertEqual((state.reply_scene, state.emotion), (scene, emotion), text)
        for text in ("Mrugnij do Mai i powiedz jej dobranoc", "Zatańczmy w salonie jutro",
                     "Jaką minę ma pies?"):
            self.assertFalse(fun.face_play(text, self.speak), text)
        import drawing
        self.assertTrue(drawing._NOT_TO_SEE.match("swój język"))

    def test_alarms_listed(self):
        now = datetime.datetime(2026, 10, 14, 18, 0).timestamp()
        self.assertEqual(timers.reminders_answer("Jakie mam budziki?", now),
                         "Nie masz teraz żadnego budzika.")
        timers._timers.append({"kind": "alarm", "label": "", "repeat": "weekdays",
                               "due": datetime.datetime(2026, 10, 15, 6, 40).timestamp()})
        timers._timers.append({"kind": "reminder", "label": "leki", "repeat": "none",
                               "due": datetime.datetime(2026, 10, 14, 20, 0).timestamp()})
        said = timers.reminders_answer("Jakie mam budziki?", now)
        self.assertTrue(said.startswith("Masz budzik w dni robocze o szóstej czterdzieści"), said)
        self.assertNotIn("leki", said)
        self.assertIn("leki", timers.reminders_answer("Jakie mam przypomnienia?", now))
        self.assertIsNotNone(timers.reminders_answer("Na którą mam budzik?", now))
        self.assertIsNone(timers.reminders_answer("Jaki budzik ustawić dla dziecka?", now))

    def test_cancel_by_kind(self):
        t = time.time()
        timers._timers.extend([{"kind": "timer", "label": "", "repeat": "none", "due": t + 300},
                               {"kind": "alarm", "label": "", "repeat": "daily", "due": t + 9000},
                               {"kind": "alarm", "label": "", "repeat": "none", "due": t + 9900}])
        with mock.patch.object(timers, "_save", lambda: None):
            self.assertIsNone(timers.cancel_answer("Wyłącz budzik"))     # may mean tomorrow only
            self.assertEqual(timers.cancel_answer("Anuluj minutnik"), "Dobrze, wyłączyłam minutnik.")
            self.assertEqual(timers.cancel_answer("Anuluj minutnik"), "Nie mam teraz żadnego minutnika.")
            self.assertEqual(timers.cancel_answer("Wyłącz wszystkie budziki"),
                             "Dobrze, usunęłam 2 budziki.")
        self.assertEqual(timers._timers, [])

    def test_volume_max_and_min(self):
        import commands
        self.assertEqual(commands._volume_command("Głośność na maksa"), 1.0)
        self.assertEqual(commands._volume_command("Najgłośniej"), 1.0)
        self.assertEqual(commands._volume_command("Ścisz na minimum"), 0.0)
        self.assertIsNone(commands._volume_command("Biegnę na maksa"))

    def test_calendar(self):
        import calc
        t = datetime.date(2026, 10, 14)
        for q, want in (("Ile dni ma luty?", "Luty 2027 ma 28 dni."),
                        ("Ile dni ma luty 2028?", "Luty 2028 ma 29 dni — to rok przestępny."),
                        ("Czy rok 2028 jest przestępny?", "Tak, 2028 jest przestępny"),
                        ("Czy ten rok jest przestępny?", "Nie, 2026 nie jest przestępny"),
                        ("Który mamy tydzień?", "Mamy tydzień numer 42."),
                        ("Który dziś dzień roku?", "Dziś jest dzień numer 287."),
                        ("Jaki dzień będzie za tydzień?", "Za tydzień będzie środa, 21 października.")):
            self.assertTrue((calc.calendar_answer(q, t) or "").startswith(want), q)
        with mock.patch.object(calc, "_today", return_value=t):
            self.assertTrue(calc.answer("Za ile dni jest 24 grudnia?").startswith("Do 24 grudnia"))

    def test_sunset(self):
        import weather
        now = datetime.datetime(2026, 10, 14, 12, 0).timestamp()
        light = {"2026-10-14": ("2026-10-14T07:12", "2026-10-14T17:58"),
                 "2026-10-15": ("2026-10-15T07:14", "2026-10-15T17:56")}
        with mock.patch.dict(weather._sky, {"light": light}):
            self.assertEqual(weather.sun_answer("O której zachód słońca?", now),
                             "Zachód słońca dziś o siedemnastej pięćdziesiąt osiem.")
            self.assertTrue(weather.sun_answer("Kiedy jutro wschód słońca?", now)
                            .startswith("Wschód słońca jutro o siódmej"))
            self.assertTrue(weather.sun_answer("O której słońce wschodzi?", now)
                            .startswith("Słońce wzeszło dziś o siódmej"))
            self.assertIsNone(weather.sun_answer("Lubię zachód słońca nad morzem", now))

    def test_short_line_heard_in_english_spelling_is_kept(self):
        import voicecheck
        self.assertTrue(voicecheck.sounds_like("Hej, hej!", "Hey, hey."))
        self.assertFalse(voicecheck.sounds_like("Hej, hej!", "嘿嘿。"))
        self.assertFalse(voicecheck.sounds_like("Łaskocze!", "Wasgota?"))


import commands  # noqa: E402  (after the data paths above are set)
import screens  # noqa: E402
import weather  # noqa: E402


class GalleryWeatherScreensTest(unittest.TestCase):
    """The gallery (next / previous / close, by voice and touch) and the
    weather as pictures."""

    def setUp(self):
        self.said = []

    def tearDown(self):
        with state.lock:
            state.overlay = None

    def speak(self, text, **k):
        self.said.append(text)

    def _items(self, n):
        return [{"path": f"/x/2026101{k}-120000.jpg", "caption": "", "sub": ""} for k in range(n)]

    def test_voice_and_touch_turn_the_pages(self):
        import gallery
        gallery.show(self._items(3), "Zdjęcia")
        with state.lock:
            kind, until, g = state.overlay
        self.assertEqual((kind, g["i"], g["auto"]), ("gallery", 0, True))
        self.assertTrue(commands.handle("Następne", self.speak, lambda *a: None))
        self.assertEqual((g["i"], g["auto"], g["dir"]), (1, False, 1))   # stopped: looking
        self.assertTrue(commands.handle("Następne zdjęcie", self.speak, lambda *a: None))
        self.assertTrue(commands.handle("Dalej", self.speak, lambda *a: None))
        self.assertEqual((g["i"], self.said[-1]), (2, "To już ostatnie."))
        self.assertTrue(commands.handle("Poprzednie", self.speak, lambda *a: None))
        self.assertTrue(commands.handle("cofnij", self.speak, lambda *a: None))
        self.assertEqual(g["i"], 0)
        self.assertTrue(commands.handle("Wstecz", self.speak, lambda *a: None))
        self.assertEqual(self.said[-1], "To jest pierwsze.")
        self.assertTrue(commands.handle("Najstarsze", self.speak, lambda *a: None))
        self.assertEqual(g["i"], 2)
        self.assertTrue(commands.handle("Pokaż ostatnie zdjęcie", self.speak, lambda *a: None))
        self.assertEqual(g["i"], 0)                       # "ostatnie": the newest
        # touch: the sides turn, the middle goes on, ✕ closes, a swipe turns
        self.assertEqual(gallery.touch("tap", 0.1, 0.5), "prev")
        self.assertEqual(gallery.touch("tap", 0.9, 0.5), "next")
        self.assertEqual(gallery.touch("tap", 0.5, 0.5), "next")
        self.assertEqual(gallery.touch("tap", 0.95, 0.08), "close")
        self.assertEqual(gallery.touch("swipe", 0.2, 0.5, -0.4), "next")
        self.assertEqual(gallery.touch("swipe", 0.8, 0.5, 0.4), "prev")
        self.assertIsNone(gallery.touch("stroke", 0.5, 0.5))
        gallery.on_touch("swipe", 0.2, 0.5, -0.4)
        self.assertEqual(g["i"], 1)
        gallery.on_touch("tap", 0.95, 0.08)
        with state.lock:
            self.assertIsNone(state.overlay)
        # without a gallery "dalej" is not hers
        self.assertFalse(gallery.voice("Dalej", self.speak))
        # "zamknij" closes it
        gallery.show(self._items(2))
        self.assertTrue(commands.close_page("Zamknij", self.speak))

    def test_slideshow_stands_after_the_last(self):
        import gallery
        gallery.show(self._items(2))
        with state.lock:
            g = state.overlay[2]
        now = time.time()
        self.assertTrue(gallery.tick(g, now + 1))
        self.assertTrue(gallery.tick(g, now + gallery.STEP + 0.1))
        self.assertEqual(g["i"], 1)
        self.assertTrue(gallery.tick(g, now + 2 * gallery.STEP + 0.2))   # the end: it stands
        self.assertEqual((g["i"], g["auto"]), (1, False))
        self.assertTrue(gallery.tick(g, now + 99))

    def test_captions(self):
        import gallery
        now = datetime.datetime(2026, 10, 14, 18, 0).timestamp()
        self.assertEqual(gallery.when("/p/20261014-173902.jpg", now), "dziś, 17:39")
        self.assertEqual(gallery.when("/p/20261013-090500.jpg", now), "wczoraj, 9:05")
        self.assertEqual(gallery.when("/p/20261003-090500.jpg", now), "3 października")
        self.assertEqual(gallery.when("/p/20251224-090500.jpg", now), "24 grudnia 2025")
        self.assertEqual(gallery.when("/p/kot.png", now), "")

    def test_photo_deleted_from_the_gallery(self):
        import gallery
        d = tempfile.mkdtemp()
        for f in ("20261012-120000.jpg", "20261013-120000.jpg"):
            open(os.path.join(d, f), "wb").close()
        with mock.patch.object(screens, "PHOTOS_DIR", d),                 mock.patch.object(screens, "BIN", os.path.join(d, "kosz")):
            gallery.show([{"path": os.path.join(d, f)} for f in
                          ("20261013-120000.jpg", "20261012-120000.jpg")], auto=False)
            gallery.step(1)                               # the older one on the screen
            self.assertTrue(screens.photo_command("usuń to zdjęcie", self.speak))
        self.assertEqual(sorted(os.listdir(d)), ["20261013-120000.jpg", "kosz"])

    def test_weather_as_pictures(self):
        d = {"current": {"time": "2026-10-14T15:00", "temperature_2m": 12.6,
                         "apparent_temperature": 10.2, "weather_code": 2,
                         "wind_speed_10m": 14.4},
             "daily": {"time": ["2026-10-14", "2026-10-15", "2026-10-16"],
                       "weather_code": [3, 61, 53], "temperature_2m_min": [7, 6, 4],
                       "temperature_2m_max": [13, 12, 15],
                       "precipitation_probability_max": [40, 80, None],
                       "sunrise": ["2026-10-14T07:09"] * 3, "sunset": ["2026-10-14T18:01"] * 3}}
        got = weather.screen_days(d)
        self.assertEqual(got["now"], {"temp": 13, "feels": 10, "wind": 14, "kind": "partly",
                                      "desc": "częściowe zachmurzenie", "day": True})
        self.assertEqual([(x["label"], x["kind"], x["rain"]) for x in got["days"]],
                         [("Dziś", "cloud", 40), ("Jutro", "rain", 80), ("Piątek", "drizzle", 0)])
        self.assertEqual(weather.kind_of(95), "storm")
        self.assertEqual(weather.kind_of(73), "snow")
        self.assertIsNone(weather.screen_days({"current": {}}))
        # "pokaż pogodę" opens the picture page
        with mock.patch.object(weather, "screen_days", lambda d=None: dict(got)),                 mock.patch.object(weather, "forecast_rows", lambda d=None: [("Dziś", "pochmurno, 7–13°C")]):
            self.assertTrue(screens.handle("Pokaż pogodę", self.speak, lambda *a: None))
        with state.lock:
            kind, _, data = state.overlay
        self.assertEqual((kind, data["now"]["temp"]), ("weather", 13))
        self.assertTrue(commands.close_page("Zamknij", self.speak))


class GalleryDeletePeopleTest(unittest.TestCase):
    """Deleting photos, drawings and people from the gallery (into a bin),
    getting them back, and the gallery of the people she knows."""

    def setUp(self):
        self.said = []
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        with state.lock:
            state.overlay = None
        shutil.rmtree(self.d, ignore_errors=True)

    def speak(self, text, **k):
        self.said.append(text)

    def _people(self):
        import faces
        p = mock.patch.multiple(faces, PEOPLE_PATH=os.path.join(self.d, "people.json"),
                                FORGOTTEN_PATH=os.path.join(self.d, "forgotten.json"),
                                PORTRAITS=os.path.join(self.d, "faces"), _people=None)
        with open(os.path.join(self.d, "people.json"), "w", encoding="utf-8") as f:
            json.dump({"Maja": {"samples": [[0.1] * 4], "note": "córka, 8 lat — dziecko"},
                       "Kasia": {"samples": [[0.2] * 4]}}, f)
        return p

    def test_bin_tapped_twice_deletes_a_photo(self):
        import gallery
        for f in ("20261012-120000.jpg", "20261013-120000.jpg"):
            open(os.path.join(self.d, f), "wb").close()
        # the one binned first was taken later: restore goes by binning, not taking
        later = time.time() + 60
        os.utime(os.path.join(self.d, "20261013-120000.jpg"), (later, later))
        with mock.patch.object(screens, "PHOTOS_DIR", self.d),                 mock.patch.object(screens, "BIN", os.path.join(self.d, "kosz")):
            gallery.show(screens._items(["20261013-120000.jpg", "20261012-120000.jpg"], {}),
                         auto=False)
            self.assertEqual(gallery.touch("tap", 0.86, 0.08, item={"kind": "photo"}), "delete")
            self.assertEqual(gallery.touch("tap", 0.86, 0.08, item={"kind": None}), "next")
            gallery.on_touch("tap", 0.86, 0.08)            # "Usunąć?"
            self.assertEqual(sorted(os.listdir(self.d)), ["20261012-120000.jpg", "20261013-120000.jpg"])
            gallery.on_touch("tap", 0.86, 0.08)            # yes
            self.assertEqual(sorted(os.listdir(self.d)), ["20261012-120000.jpg", "kosz"])
            with state.lock:
                kind, _, g = state.overlay
            self.assertEqual((kind, len(g["items"]), g["i"]), ("gallery", 1, 0))
            self.assertIn("przywróć zdjęcie", g["toast"][0])
            # by voice: the last one, and the gallery closes
            self.assertTrue(commands.handle("Usuń to zdjęcie", self.speak, lambda *a: None))
            self.assertEqual(self.said[-1], "Usunęłam zdjęcie. Gdyby co — powiedz: przywróć zdjęcie.")
            with state.lock:
                self.assertIsNone(state.overlay)
            self.assertTrue(screens.photo_command("przywróć zdjęcie", self.speak))
        self.assertIn("20261012-120000.jpg", os.listdir(self.d))
        self.assertEqual(os.listdir(os.path.join(self.d, "kosz")), ["20261013-120000.jpg"])

    def test_drawing_deleted_and_back(self):
        import drawing
        import gallery
        with mock.patch.object(drawing, "DIR", self.d),                 mock.patch.object(drawing, "BIN", os.path.join(self.d, "kosz")):
            for f in ("20261012-120000.png", "20261013-120000.png"):
                open(os.path.join(self.d, f), "wb").close()
            drawing._keep_title(os.path.join(self.d, "20261013-120000.png"), "kotek")
            self.assertTrue(drawing.show_saved(self.speak))
            with state.lock:
                g = state.overlay[2]
            self.assertEqual((g["items"][0]["caption"], g["items"][0]["kind"]), ("kotek", "drawing"))
            self.assertTrue(gallery.voice("Usuń ten rysunek", self.speak))
            self.assertEqual(os.listdir(os.path.join(self.d, "kosz")), ["20261013-120000.png"])
            self.assertTrue(commands.handle("Przywróć rysunek", self.speak, lambda *a: None))
            self.assertEqual(self.said[-1], "Proszę, wrócił.")
            self.assertTrue(os.path.exists(os.path.join(self.d, "20261013-120000.png")))
            with state.lock:
                g = state.overlay[2]
            self.assertEqual(os.path.basename(g["items"][g["i"]]["path"]), "20261013-120000.png")

    def test_drawing_restore_brings_back_last_binned(self):
        import drawing
        for f in ("20261012-120000.png", "20261013-120000.png"):
            open(os.path.join(self.d, f), "wb").close()
        # the one binned first was drawn later: restore goes by binning, not drawing
        later = time.time() + 60
        os.utime(os.path.join(self.d, "20261013-120000.png"), (later, later))
        with mock.patch.object(drawing, "DIR", self.d), \
                mock.patch.object(drawing, "BIN", os.path.join(self.d, "kosz")):
            self.assertTrue(drawing.bin_drawing(os.path.join(self.d, "20261013-120000.png")))
            self.assertTrue(drawing.bin_drawing(os.path.join(self.d, "20261012-120000.png")))
            self.assertEqual(drawing.restore_drawing(), os.path.join(self.d, "20261012-120000.png"))
        self.assertEqual(os.listdir(os.path.join(self.d, "kosz")), ["20261013-120000.png"])

    def test_people_gallery_forget_and_restore(self):
        import faces
        import gallery
        with self._people():
            self.assertTrue(screens.handle("Kogo znasz?", self.speak, lambda *a: None))
            self.assertEqual(self.said[-1], "Znam 2 osoby: Kasia i Maja.")
            with state.lock:
                g = state.overlay[2]
            first = g["items"][0]
            self.assertEqual((first["caption"], first["kind"], first["round"], first["path"]),
                             ("Kasia", "person", True, None))
            self.assertEqual(g["items"][1]["sub"], "córka, 8 lat")
            # tagged in a photo, but her face can't be found in it: the letter,
            # never the whole photo (14 Oct: Maja's "portrait" was a plush cat)
            ph = os.path.join(self.d, "20261013-120000.jpg")
            open(ph, "wb").close()
            with mock.patch.object(screens, "photos_of", lambda n: [ph] if n == "Maja" else []),                     mock.patch.object(faces, "available", lambda: False):
                self.assertIsNone(screens.people_items()[1]["path"])
            for t in ("Pokaż osoby, które znasz", "Luna, pokaż galerię osób", "Kogo pamiętasz?"):
                self.assertTrue(screens._people_asked(t.lower()), t)
            self.assertFalse(screens._people_asked("kogo znasz w szkole"))
            gallery.step(1)                                  # Maja
            self.assertTrue(gallery.voice("Zapomnij tę osobę", self.speak))
            self.assertEqual(faces.names(), ["Kasia"])
            self.assertEqual(self.said[-1], "Zapomniałam: Maja. Gdyby co — powiedz: przywróć osobę.")
            self.assertTrue(commands.handle("Przywróć osobę", self.speak, lambda *a: None))
            self.assertEqual(faces.names(), ["Kasia", "Maja"])
            self.assertEqual(faces.notes()["Maja"], "córka, 8 lat — dziecko")
            self.assertEqual(self.said[-1], "Dobrze, znowu pamiętam: Maja.")

    def test_portrait_kept_once_a_day(self):
        import numpy as np
        import faces
        frame = np.zeros((480, 640, 3), np.uint8)
        row = np.array([100, 60, 60, 70] + [0] * 11, np.float32)     # half-size frame
        with self._people():
            now = time.time()
            self.assertFalse(faces.keep_portrait("Maja", 0.40, frame, row, 2.0, now))  # not sure
            self.assertTrue(faces.keep_portrait("Maja", 0.6, frame, row, 2.0, now))
            self.assertTrue(faces.portrait("Maja"))
            self.assertFalse(faces.keep_portrait("Maja", 0.6, frame, row, 2.0, now + 60))
            items = screens.people_items()
            self.assertEqual(items[1]["path"], faces.portrait("Maja"))
            self.assertFalse(faces.keep_portrait("Maja", 0.46, frame, row, 2.0,     # (not the
                                                 now + 2 * faces.PORTRAIT_EVERY))     # first: surer)
            later = now + 2 * faces.PORTRAIT_EVERY
            self.assertFalse(faces.keep_portrait("Maja", 0.51, frame, row, 2.0, later))
            with mock.patch.object(faces, "_scores", lambda f: {"Maja": 0.7, "Kasia": 0.55}):
                self.assertFalse(faces.keep_portrait("Maja", 0.7, frame, row, 2.0, later,
                                                     feature=np.ones(128)))   # too like Kasia
            with mock.patch.object(faces, "_scores", lambda f: {"Maja": 0.7, "Kasia": 0.2}):
                self.assertTrue(faces.keep_portrait("Maja", 0.7, frame, row, 2.0, later,
                                                    feature=np.ones(128)))
            faces.forget("Maja")                             # the portrait goes too…
            self.assertIsNone(faces.portrait("Maja"))
            faces.restore("Maja")                            # …and comes back
            self.assertTrue(faces.portrait("Maja"))

    def test_slideshow_stops_after_ten_and_keeps_listening(self):
        import gallery
        gallery.show([{"path": f"/x/{k}.jpg"} for k in range(14)])
        with state.lock:
            g = state.overlay[2]
            self.assertTrue(state.conversation_active)
        t = time.time()
        for k in range(1, 12):
            gallery.tick(g, t + k * gallery.STEP + 0.01)
        self.assertEqual((g["i"], g["auto"]), (gallery.AUTO_MAX - 1, False))
        self.assertTrue(gallery.page_open())


class Oct14NightTest(unittest.TestCase):
    """14 Oct evening log: a wrong day agreed to, "pokaż kogo znasz" as a
    web photo, "tylko te?" over the gallery."""

    def setUp(self):
        self.said = []

    def tearDown(self):
        with state.lock:
            state.overlay = None

    def test_day_claims_checked(self):
        import calc
        wed = datetime.date(2026, 10, 14)
        self.assertEqual(calc.day_claim("Jutro piątek.", wed),
                         "Nie, jutro jest czwartek, 15 października.")
        self.assertEqual(calc.day_claim("Nieprawda, jutro jest czwartek.", wed),
                         "Tak, jutro jest czwartek, 15 października.")
        self.assertEqual(calc.day_claim("Dziś jest środa?", wed),
                         "Tak, dziś jest środa, 14 października.")
        self.assertEqual(calc.day_claim("wczoraj był poniedziałek", wed),
                         "Nie, wczoraj był wtorek, 13 października.")
        self.assertEqual(calc.day_claim("Pojutrze piątek, prawda?", wed),
                         "Tak, pojutrze będzie piątek, 16 października.")
        for t in ("Jutro piątek idziemy do kina", "W piątek jutro?", "Jutro"):
            self.assertIsNone(calc.day_claim(t, wed), t)

    def test_show_who_you_know(self):
        for t in ("luna pokaż kogo znasz", "pokaż mi kogo znasz", "kogo znasz",
                  # 19 Oct 20:00–20:08: four tries before one matched
                  "luna kogoś kogo znasz", "pokaż, kogo znasz.",
                  "pokaż profile ludzi, których znasz.", "luna, pokaż ludzi, których znasz.",
                  "pokaż profile", "pokaż mi zdjęcia osób, które znasz", "pokaż portrety"):
            self.assertTrue(screens._people_asked(t), t)
        for t in ("kogo znasz w szkole", "pokaż galerię", "pokaż zdjęcia", "znasz kogoś",
                  "pokaż zdjęcia mai", "kogoś znasz"):
            self.assertFalse(screens._people_asked(t), t)

    def test_wake_time(self):
        now = datetime.datetime(2026, 10, 14, 21, 0).timestamp()
        timers._timers.clear()
        self.assertEqual(timers.wake_answer("O której jutro wstajemy?", now),
                         "Na jutro nie masz budzika. Powiedz na przykład: budzik na siódmą.")
        due = datetime.datetime(2026, 10, 15, 6, 40).timestamp()
        timers._timers.append({"kind": "alarm", "due": due, "repeat": "weekdays", "label": ""})
        try:
            self.assertTrue(timers.wake_answer("o której mam jutro wstać", now))
            got = timers.wake_answer("O której jutro wstajemy?", now)
            self.assertTrue(got.startswith("Budzik jutro o szóstej"), got)
            self.assertTrue(timers.wake_answer("Kiedy dzwoni budzik?", now))
            self.assertIsNone(timers.wake_answer("O której jutro wstajemy na pociąg do Krakowa?", now))
        finally:
            timers._timers.clear()

    def test_close_by_name(self):
        said = []
        with state.lock:
            state.overlay = ("weather", time.time() + 30, {})
        self.assertTrue(commands.close_page("Zamknij pogodę", said.append))
        with state.lock:
            self.assertIsNone(state.overlay)
        self.assertFalse(commands.close_page("Wyłącz ekran gry", said.append))   # nothing on
        import tictac
        with mock.patch.object(tictac, "stop", lambda: said.append("<stop>")):
            with state.lock:
                state.overlay = ("ttt", time.time() + 30, {})
            self.assertTrue(commands.close_page("Wyłącz ekran gry", said.append))
        self.assertEqual(said[-2:], ["<stop>", "Dobrze, kończymy grę."])

    def test_doubled_transcript(self):
        self.assertEqual(commands.undoubled("Pokaż jeszcze raz rysunki, Luna, pokaż jeszcze raz rysunki."),
                         "Pokaż jeszcze raz rysunki.")
        self.assertEqual(commands.undoubled("Pokaż jeszcze raz rysunki pokaż jeszcze raz rysunki."),
                         "Pokaż jeszcze raz rysunki.")
        for t in ("Jeszcze jeszcze", "Pa pa pa pa", "Mama ma kota, mama ma psa."):
            self.assertEqual(commands.undoubled(t), t if t != "Pa pa pa pa" else "Pa pa.")

    def test_only_these(self):
        import gallery
        gallery.show([{"path": f"/x/{k}.jpg", "kind": "photo"} for k in range(3)], auto=False)
        for t, want in (("Tylko te?", "Tak, mam 3 zdjęcia."), ("Ile ich jest?", "Mam 3 zdjęcia."),
                        ("To wszystkie?", "Tak, mam 3 zdjęcia.")):
            self.assertTrue(gallery.voice(t, self.said.append), t)
            self.assertEqual(self.said[-1], want)
        gallery.show([{"path": None, "kind": "person", "name": "Maja"}], auto=False)
        self.assertTrue(gallery.voice("tylko tyle?", self.said.append))
        self.assertEqual(self.said[-1], "Tak, znam 1 osobę.")


class ListTapGameCloseTest(unittest.TestCase):
    """A list item crossed off by tapping it twice; the ✕ on a game's page
    ends the game."""

    def setUp(self):
        self.said = []
        lists._lists = {"zakupy": ["mleko", "mleko kokosowe", "chleb"]}
        lists._save()

    def tearDown(self):
        with state.lock:
            state.overlay = None
        lists._lists = {}
        lists._save()

    def _row(self, k):
        """Normalised tap point in the middle of row k (ui_screens' layout)."""
        import ui_screens
        return 0.5, (ui_screens._LIST_TOP + 8 + ui_screens._LIST_ROW * (k + 0.5)) / 480

    def test_tap_twice_crosses_off_just_that_item(self):
        import ui_screens
        self.assertTrue(screens.handle("Pokaż listę zakupów", self.said.append, lambda *a: None))
        with state.lock:
            heading, rows, meta = state.overlay[2]
        self.assertEqual((heading, meta["list"]), ("Lista: zakupy", "zakupy"))
        self.assertEqual(ui_screens.list_row_at(*self._row(0), rows, 0), 0)
        self.assertIsNone(ui_screens.list_row_at(0.5, 0.1, rows, 0))       # the title
        self.assertIsNone(ui_screens.list_row_at(*self._row(5), rows, 0))  # below the last
        now = time.time()
        self.assertEqual(screens.list_tap(*self._row(0), now), "confirm")
        self.assertEqual(lists.get("zakupy"), ["mleko", "mleko kokosowe", "chleb"])
        self.assertEqual(screens.list_tap(*self._row(1), now + 1), "confirm")   # another row
        self.assertEqual(screens.list_tap(*self._row(0), now + 2), "confirm")
        self.assertEqual(screens.list_tap(*self._row(0), now + 3), "removed")
        self.assertEqual(lists.get("zakupy"), ["mleko kokosowe", "chleb"])      # not "kokosowe"
        with state.lock:
            heading, rows, meta = state.overlay[2]
        self.assertEqual([r[1] for r in rows], ["mleko kokosowe", "chleb"])
        self.assertIn("przywróć listę", meta["toast"][0])
        # too slow: asked again
        self.assertEqual(screens.list_tap(*self._row(0), now + 4), "confirm")
        self.assertEqual(screens.list_tap(*self._row(0), now + 9), "confirm")
        self.assertEqual(lists.restore("przywróć listę"),
                         "Przywróciłam na listę zakupy: mleko.")

    def test_last_item_closes_the_page(self):
        lists._lists = {"zakupy": ["chleb"]}
        screens.handle("Pokaż listę zakupów", self.said.append, lambda *a: None)
        now = time.time()
        screens.list_tap(*self._row(0), now)
        self.assertEqual(screens.list_tap(*self._row(0), now + 1), "emptied")
        with state.lock:
            self.assertIsNone(state.overlay)
        self.assertEqual(lists.get("zakupy"), [])

    def test_a_quick_second_tap_does_not_cross_off(self):
        # 16 Oct 13:57: the to-do list's only item went at once
        lists._lists = {"do zrobienia": ["wypłacić pieniądze"]}
        screens.handle("Pokaż listę do zrobienia", self.said.append, lambda *a: None)
        now = time.time()
        self.assertEqual(screens.list_tap(*self._row(0), now), "confirm")
        self.assertEqual(screens.list_tap(*self._row(0), now + 0.2), "confirm")
        self.assertEqual(lists.get("do zrobienia"), ["wypłacić pieniądze"])
        self.assertEqual(screens.list_tap(*self._row(0), now + 1.5), "emptied")

    def test_an_emptied_todo_list_is_not_the_shopping_list(self):
        lists._lists = {"zakupy": ["chleb"], "do zrobienia": ["pranie"]}
        screens.handle("Pokaż listę do zrobienia", self.said.append, lambda *a: None)
        now = time.time()
        screens.list_tap(*self._row(0), now)
        screens.list_tap(*self._row(0), now + 1)
        self.said.clear()
        screens.handle("Pokaż mi listę rzeczy do zrobienia", self.said.append, lambda *a: None)
        with state.lock:
            self.assertIsNone(state.overlay)            # not "Lista: zakupy"
        self.assertIn("do zrobienia jest pusta", self.said[0])
        self.assertIn("przywróć listę", self.said[0])

    def test_other_lists_are_not_tappable(self):
        with state.lock:
            state.overlay = ("list", time.time() + 10, ("Status", [("Temp", "50°C")]))
        self.assertIsNone(screens.list_tap(*self._row(0)))

    def test_close_ends_the_game(self):
        import quiz
        import tictac
        with mock.patch.object(quiz, "_q", {"kind": "flags"}), \
                mock.patch.object(quiz, "active", lambda: quiz._q is not None):
            with state.lock:
                state.overlay = ("card", time.time() + 30, {"text": "?"})
            self.assertEqual(screens.end_game_page("card"), ["quiz"])
            self.assertIsNone(quiz._q)
        with mock.patch.object(tictac, "stop", lambda: self.said.append("<ttt stop>")):
            self.assertEqual(screens.end_game_page("ttt"), ["ttt"])
        self.assertEqual(self.said, ["<ttt stop>"])
        with state.lock:
            self.assertIsNone(state.overlay)


class FaceLibraryCostumeTest(unittest.TestCase):
    """The face library (15 Oct): the new costumes, by voice."""

    def tearDown(self):
        state.costume = None

    def test_new_costumes(self):
        import fun
        said = []
        for text, kind in (("Zamień się w wiewiórkę", "squirrel"),
                           ("Luna, zrób szalonego robota", "crazy_robot"),
                           ("Bądź steampunkiem", "steampunk"),
                           ("Zrób imprezę!", "party"),
                           ("Zrób śmieszne oczy", "googly_eyes"),
                           ("Pokaż mi wyłupiaste oczy", "googly_eyes")):
            state.costume = None
            self.assertTrue(fun.handle(text, said.append, None, None), text)
            self.assertEqual(state.costume[0], kind, text)
        self.assertIn("wiewiórką", said[0])
        state.costume = None
        for text in ("Pokaż mi oczy", "Zrób robota kuchennego z klocków lego"):
            self.assertFalse(fun.handle(text, said.append, None, None), text)
            self.assertIsNone(state.costume, text)

    def test_every_costume_has_its_line_and_eyes(self):
        import fun
        import gl_face
        kinds = {k for k, _ in fun._COSTUME_KIND} | {"googly_eyes"}
        self.assertEqual(kinds, set(fun._COSTUME_SAY))
        self.assertTrue(set(gl_face.COSTUME_EYES) <= kinds)


class RadioCatalogTest(unittest.TestCase):
    """15 Oct: "soft music for work — one jazz station, 4 in total; a better
    choice and a list to choose from"."""

    def _ask(self, text, playing=None):
        import radio
        got, said = [], []
        with mock.patch.object(radio, "play", lambda n, u, **k: got.append(n)),                 mock.patch.object(radio, "playing", lambda: playing),                 mock.patch.object(radio, "_remember_station", lambda n, u: None),                 mock.patch.object(radio, "_world_play", lambda w, s: False):
            handled = radio.handle(text, said.append)
        return handled, got, said

    def _names(self, cat):
        import radio
        return [n for n, _, _ in radio._CAT[cat][2]]

    def test_kinds_of_music(self):
        for text, cat in (("Puść coś spokojnego do pracy", "calm"), ("Włącz jazz", "jazz"),
                          ("włącz radio jazzowe", "jazz"), ("puść muzykę klasyczną", "classic"),
                          ("włącz jakiś rock", "rock"), ("puść coś do biegania", "hits"),
                          ("włącz radio dla dzieci", "kids"),
                          ("puść muzykę elektroniczną", "electronic"),
                          ("włącz coś w tle do nauki", "calm")):
            handled, got, said = self._ask(text)
            self.assertTrue(handled, text)
            self.assertIn(got[-1], self._names(cat), text)
        self.assertIn("spokojna muzyka do pracy", self._ask("Puść coś spokojnego do pracy")[2][-1])

    def test_a_station_by_name_wins(self):
        for text, name in (("Włącz Polskie Radio Chopin", "Radio Chopin"),
                           ("włącz FIP Jazz", "FIP Jazz"), ("włącz trójkę", "Trójka"),
                           ("włącz radio RMF Classic", "RMF Classic"),
                           ("włącz radio Swiss Jazz", "Radio Swiss Jazz")):
            self.assertEqual(self._ask(text)[1][-1], name, text)

    def test_variety_and_the_next_of_the_kind(self):
        picks = {self._ask("puść coś spokojnego do pracy")[1][-1] for _ in range(30)}
        self.assertGreater(len(picks), 4)                     # not always the same few
        handled, got, said = self._ask("następna stacja", playing="FIP Jazz")
        self.assertEqual(got, ["Jazz Radio"])                 # the next jazz one
        handled, got, said = self._ask("następna stacja", playing="SomaFM Drone Zone")
        self.assertEqual(got, ["SomaFM Groove Salad"])        # (round to the first)

    def test_every_station_is_in_one_kind_only(self):
        import radio
        names = [n for _, _, _, sts in radio.CATALOG for n, _, _ in sts]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 45)
        for _, _, _, sts in radio.CATALOG:
            for n, u, b in sts:
                self.assertTrue(u.startswith("http"), n)
                self.assertTrue(b, n)

    def test_asking_for_the_page(self):
        import radio
        # 15 Oct: three ways Andrzej asked — only "pokaż stację" worked
        for t in ("Luna, pokaż jakie masz radia.", "Luna, jakie masz inne stacje radiowe?",
                  "A pokaż stronę z radiami.", "Pokaż stronę ze stacjami radiowymi.",
                  "Pokaż stację.", "lista stacji", "jakie masz stacje", "pokaż mi stacje radiowe",
                  "chcę wybrać stację", "jakie radia są dostępne", "pokaż listę stacji",
                  "otwórz radio", "które stacje masz"):
            self.assertTrue(radio._show_asked(t.lower().strip(" .!?")), t)
        import commands                                       # (through the whole router)
        for t in ("Luna, pokaż jakie masz radia.", "Luna, jakie masz inne stacje radiowe?",
                  "A pokaż stronę z radiami.", "Pokaż stronę ze stacjami radiowymi."):
            shown = []
            with mock.patch.object(radio, "show_page", lambda *a: shown.append(1)):
                self.assertTrue(commands.handle(t, lambda *a, **k: None, lambda *a, **k: True), t)
            self.assertEqual(shown, [1], t)
        for t in ("włącz radio", "wyłącz radio", "jakie radio teraz gra", "co to za stacja",
                  "jaka to stacja", "zmień stację", "następna stacja", "pokaż listę zakupów",
                  "co leci w radiu", "budź mnie radiem", "jakie masz plany na dziś",
                  "jakie radio lubisz", "jakie stacje polecasz", "jakiego radia słuchasz"):
            self.assertFalse(radio._show_asked(t), t)

    def test_without_singing(self):
        import radio
        for text in ("Włącz jakieś radio jazzowe, ale bez śpiewania.",
                     "Luna, włącz ciche instrumentalne radio.", "puść muzykę bez słów"):
            for _ in range(8):
                handled, got, said = self._ask(text)
                self.assertTrue(handled, text)
                self.assertIn(got[-1], radio.INSTRUMENTAL, text)
        self.assertIn(self._ask("Włącz jakieś radio jazzowe, ale bez śpiewania.")[1][-1],
                      ("SomaFM Sonic Universe", "SomaFM Secret Agent"))    # jazz, still
        self.assertIn("bez śpiewu", self._ask("puść jazz bez śpiewu")[2][-1])

    def _store(self):
        """settings in memory (favourites, the last played, dead marks)."""
        import settings
        mem = {}
        return (mock.patch.object(settings, "get", lambda k, d=None: mem.get(k, d)),
                mock.patch.object(settings, "put", lambda k, v: mem.__setitem__(k, v)), mem)

    def test_the_page(self):
        try:
            import pygame  # noqa: F401
        except ImportError:
            self.skipTest("pygame")
        import radio
        import ui_screens
        g, p, mem = self._store()
        with g, p:
            handled, got, said = self._ask("pokaż stacje")
            self.assertTrue(handled)
            self.assertEqual(said, ["Oto moje stacje."])
            with state.lock:
                kind, until, data = state.overlay
            self.assertEqual(kind, "radio")
            W, H = 800, 480
            kinds, ci = radio.page_list(data)
            L = ui_screens._radio_layout(W, H, len(kinds[ci][2]), None, len(kinds))
            got = []
            with mock.patch.object(radio, "play", lambda n, u, **k: got.append(n)), \
                    mock.patch.object(radio, "playing", lambda: None):
                r = L["kinds"][[k for k, _, _ in kinds].index("jazz")]
                radio.tap(r.centerx, r.centery, W, H)                 # "Jazz"
                self.assertEqual(data["cat"], "jazz")
                L = ui_screens._radio_layout(W, H, len(radio._CAT["jazz"][2]), None, len(kinds))
                radio.tap(L["sts"][2].centerx, L["sts"][2].centery, W, H)   # its third station
                self.assertEqual(got, [radio._CAT["jazz"][2][2][0]])
                # its star: a favourite — and the page gets "Ulubione" first,
                # still showing jazz (a key, not a position)
                radio.tap(L["stars"][0].centerx, L["stars"][0].centery, W, H)
                self.assertEqual(radio.favs()[0][0], "Radio Swiss Jazz")
                kinds, ci = radio.page_list(data)
                self.assertEqual([k for k, _, _ in kinds][:2], ["fav", "recent"])
                self.assertEqual(kinds[ci][0], "jazz")
                radio.swipe(-200)                                   # → the next kind
                self.assertEqual(data["cat"], "classic")
            with state.lock:
                self.assertEqual(state.overlay[0], "radio")         # (still open)
                state.overlay = None

    def test_favourites_by_voice(self):
        import radio
        g, p, mem = self._store()
        with g, p, mock.patch.object(radio, "_current_url", lambda: "http://x"):
            self.assertIn("Nie masz jeszcze", self._ask("Włącz moją ulubioną stację")[2][-1])
            self.assertIn("Dodałam", self._ask("Dodaj tę stację do ulubionych",
                                                playing="FIP Jazz")[2][-1])
            self.assertEqual(radio.favs(), [("FIP Jazz", "http://x")])
            self.assertIn("Dodałam", self._ask("lubię to radio", playing="FIP Jazz")[2][-1])
            self.assertEqual(len(radio.favs()), 1)                  # (not twice)
            handled, got, said = self._ask("puść ulubione")
            self.assertEqual(got, ["FIP Jazz"])
            self.assertIn("Usunęłam", self._ask("usuń tę stację z ulubionych",
                                                 playing="FIP Jazz")[2][-1])
            self.assertEqual(radio.favs(), [])
            # 15 Oct, Andrzej's own words, through the whole router (the first
            # two went to the model: "Nie mogę dodać stacji do ulubionych")
            import commands
            said, got, shown = [], [], []
            with mock.patch.object(radio, "playing", lambda: "Radio Swiss Jazz"), \
                    mock.patch.object(radio, "play", lambda n, u, **k: got.append(n)), \
                    mock.patch.object(radio, "_remember_station", lambda n, u: None), \
                    mock.patch.object(radio, "show_page", lambda *a: shown.append(a)):
                for t in ("Dodaj tą stację do ulubionych.", "Ulubione.",
                          "Włącz moją ulubioną stację."):
                    self.assertTrue(commands.handle(t, said.append, lambda *a, **k: True), t)
            self.assertEqual(radio.favs(), [("Radio Swiss Jazz", "http://x")])
            self.assertIn("Dodałam", said[0])
            self.assertEqual(shown, [("fav",)])
            self.assertEqual(got, ["Radio Swiss Jazz"])           # (the only favourite)

    def test_favourites_18_oct(self):
        # Andrzej's words that went to the model, whose commands were refused
        import radio
        import brain
        import commands
        g, p, mem = self._store()
        with g, p:
            radio.fav_toggle("Classic Vinyl HD", "http://vinyl")
            got = []
            with mock.patch.object(radio, "playing", lambda: None), \
                    mock.patch.object(radio, "play", lambda n, u, **k: got.append((n, u))), \
                    mock.patch.object(radio, "_remember_station", lambda n, u: None), \
                    mock.patch.object(radio, "_lookup", lambda n: self.fail("went online")):
                for t in ("Spróbuj jeszcze raz włączyć ulubionych.", "Coś z ulubionych.",
                          "Przełącz na ulubioną stację.", "Włącz Classic Vinyl HD."):
                    self.assertTrue(commands.handle(t, lambda *a: None, lambda *a, **k: True), t)
                for label in ("włącz moją ulubioną stację", "włącz Classic Vinyl HD",
                              "włącz SomaFM Groove Salad"):
                    self.assertTrue(brain.run_command(label), label)
            self.assertEqual(got[0], ("Classic Vinyl HD", "http://vinyl"))
            self.assertEqual(got[3], ("Classic Vinyl HD", "http://vinyl"))
            self.assertEqual(len(got), 7)
            self.assertFalse(radio.known("Radio Nieistniejące"))
            for t in ("Dodaj do ulubionych.", "Usuń z ulubionych.", "Mai ulubiony kolor to fiolet."):
                self.assertFalse(radio._FAV_PLAY.search(t.lower()), t)

    def test_count_similar_and_the_time_of_day(self):
        import radio
        import commands
        g, p, mem = self._store()
        with g, p, mock.patch.object(radio, "show_page", lambda *a: None):
            said = []
            self.assertTrue(commands.handle("Ile masz stacji?", said.append, lambda *a, **k: True))
            n = sum(len(sts) for _, _, _, sts in radio.CATALOG)
            self.assertIn(f"Mam {n} stacji", said[-1])
            handled, got, said = self._ask("puść coś podobnego", playing="FIP Jazz")
            self.assertEqual(got, ["Jazz Radio"])                   # the next jazz one
            for hour, cat in ((7, "polish"), (11, "calm"), (19, "jazz"), (23, "calm")):
                t = time.struct_time((2026, 10, 15, hour, 0, 0, 3, 288, 1))
                with mock.patch.object(radio.time, "localtime", lambda *a, t=t: t), \
                        mock.patch.object(radio, "_who", lambda: None), \
                        mock.patch.object(radio, "_child_here", lambda: False), \
                        mock.patch.object(radio, "playing", lambda: None):
                    self.assertEqual(radio._default_kind(), cat, hour)
            with mock.patch.object(radio, "_child_here", lambda: True), \
                    mock.patch.object(radio, "_who", lambda: "Maja"):
                self.assertIn(radio._station("")[0], self._names("kids"))   # a child: theirs

    def test_dead_stations_are_skipped(self):
        import radio
        g, p, mem = self._store()
        with g, p:
            for n, u, _ in radio._CAT["kids"][2][:1]:
                radio._mark(u, True)                                # RMF Dla Dzieci down
            for _ in range(6):
                self.assertEqual(radio._pick("kids")[0], "Polskie Radio Dzieciom")
            radio._mark(radio._CAT["kids"][2][0][1], False)
            self.assertEqual(radio.dead(), set())
            with mock.patch.object(radio, "_player", None):
                self.assertEqual(radio.music_pulse(), 0.0)         # nothing plays: still


class StoryTest(unittest.TestCase):
    """15 Oct: an interactive story — Maja chooses, each part has a picture,
    finished stories are kept and told again, it stops at any point."""

    def setUp(self):
        import tempfile
        import story
        self.dir = tempfile.mkdtemp()
        self.said = []
        self.n = 0
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
               b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
               b"\xfe\xa7V\x82\x8f\x00\x00\x00\x00IEND\xaeB`\x82")

        def llm(messages, schema, name):
            self.n += 1
            part = {"text": f"Część {self.n}. Smok Iskierka leci.", "scene": "a dragon flies",
                    "choices": ["wejść do jaskini", "polecieć nad morze"]}
            if name == "story_plan":
                return {"title": "Smok Iskierka", "genre": "baśń", "art_style": "watercolour",
                        "characters": [{"name": "Iskierka", "look": "a small green dragon"}],
                        "setting": "a valley", "part": part}
            return part

        def image(s, scene, out):
            with open(out, "wb") as f:
                f.write(png)
            return True
        self.patches = [mock.patch.object(story, "DIR", self.dir),
                        mock.patch.object(story, "_llm", llm),
                        mock.patch.object(story, "_image", image),
                        mock.patch.object(story, "_say", self.said.append),
                        mock.patch.object(story, "END_PAUSE", 0.05),
                        mock.patch.object(story, "_child", lambda: "Maja")]
        for p in self.patches:
            p.start()
        with state.lock:
            self._online, state.online, state.overlay = state.online, True, None

    def tearDown(self):
        import shutil
        import story
        story.stop(quiet=True)
        for p in self.patches:
            p.stop()
        with state.lock:
            state.online, state.overlay = self._online, None
        shutil.rmtree(self.dir, ignore_errors=True)

    def _wait(self, cond, secs=5.0):
        t = time.time() + secs
        while time.time() < t:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def _phase(self):
        import story
        with story._lock:
            return story._s and story._s.get("phase")

    def test_a_whole_story_kept_and_told_again(self):
        import story
        spoken = []
        self.assertTrue(story.handle("Opowiedz mi bajkę, w której ja wybieram", spoken.append))
        self.assertEqual(self._phase(), "topic")                    # "O czym ma być?"
        self.assertTrue(story.answer("o smoku", spoken.append))
        for n in range(1, story.PARTS):
            self.assertTrue(self._wait(lambda: self._phase() == "choosing"), n)
            with state.lock:
                kind, _, data = state.overlay
            self.assertEqual((kind, data["mode"]), ("story", "choose"))
            self.assertEqual(len(data["choices"]), 2)
            if n == 2:                                              # a tap, once
                story.choose(1)
            else:
                self.assertTrue(story.answer("pierwsze" if n % 2 else "nad morze",
                                             spoken.append))
        self.assertTrue(self._wait(lambda: story.saved() and not story.active()))
        st = story.saved()[0]
        self.assertEqual(st["title"], "Smok Iskierka")
        self.assertEqual(len(st["parts"]), story.PARTS)
        self.assertEqual([p["chosen"] for p in st["parts"]],
                         ["wejść do jaskini", "polecieć nad morze", "wejść do jaskini",
                          "polecieć nad morze", None])
        for p in st["parts"]:                                       # a picture each
            self.assertTrue(os.path.exists(story.image_path(st["id"], p["image"])))
        self.assertEqual(st["child"], "Maja")
        self.assertIn("Co dalej?", " ".join(self.said))
        # told again, with the choices
        self.said.clear()
        self.assertTrue(story.handle("Opowiedz jeszcze raz bajkę o smoku", spoken.append))
        self.assertTrue(self._wait(lambda: not story.active(), 5))
        self.assertEqual(self.said[0], "Smok Iskierka.")
        self.assertIn("Wybraliśmy: polecieć nad morze.", self.said)
        self.assertEqual(self.said[-1], "Koniec!")
        # the list, and deleting
        self.assertTrue(story.handle("Pokaż moje bajki", spoken.append))
        with state.lock:
            self.assertEqual(state.overlay[2]["mode"], "list")
        self.assertTrue(story.handle("Usuń bajkę o smoku", spoken.append))
        self.assertEqual(story.saved(), [])

    def test_stopped_at_any_point_and_not_kept(self):
        import story
        spoken = []
        story.handle("Interaktywna bajka o robocie", spoken.append)
        self.assertTrue(self._wait(lambda: self._phase() == "choosing"))
        self.assertTrue(story.answer("koniec", spoken.append))
        self.assertFalse(story.active())
        with state.lock:
            self.assertIsNone(state.overlay)                        # back to her face
        self.assertEqual(os.listdir(self.dir), [])                  # nothing kept
        # ✕ on the screen ends it too
        story.handle("Zagrajmy w bajkę o kotku", spoken.append)
        self.assertTrue(self._wait(lambda: self._phase() == "choosing"))
        import screens
        screens.end_game_page("story")
        self.assertFalse(story.active())
        story.handle("Zagrajmy w bajkę o kotku", spoken.append)
        self.assertTrue(story.answer("Dobra, już nie bawimy się w bajki.", spoken.append))
        self.assertFalse(story.active())

    def test_the_topic_answer(self):
        # 17 Oct 18:28: "Nie, Luna, ja mam inny pomysł." became the story's topic
        import story
        spoken = []
        story.handle("Luna, opowiedz interaktywną bajkę.", spoken.append)
        self.assertTrue(story.answer("Nie, Luna, ja mam inny pomysł.", spoken.append))
        self.assertEqual(self._phase(), "topic")
        self.assertEqual(spoken[-1], "Super! To o czym ma być bajka?")
        self.assertTrue(story.answer("O jednorożcu w kosmosie.", spoken.append))
        with story._lock:
            self.assertEqual(story._s["topic"], "o jednorożcu w kosmosie")
        story.stop(quiet=True)
        story.handle("zagrajmy w bajkę", spoken.append)
        story.answer("mam pomysł: o kocie piracie", spoken.append)
        with story._lock:
            self.assertEqual(story._s["topic"], "o kocie piracie")
        story.stop(quiet=True)
        story.handle("zagrajmy w bajkę", spoken.append)
        with story._lock:
            ideas = list(story._s["ideas"])
        story.answer("nie wiem, ty wybierz", spoken.append)
        with story._lock:
            self.assertIn(story._s["topic"], ideas)

    def test_what_starts_it_and_what_doesnt(self):
        import story
        for t in ("opowiedz bajkę, w której wybieram", "interaktywna bajka o smoku",
                  "zagrajmy w bajkę", "wymyślmy razem bajkę", "bajka z wyborem",
                  "opowiedz historię, gdzie ja decyduję"):
            self.assertTrue(story.wanted(t), t)
        for t in ("opowiedz bajkę o smoku", "bajka na dobranoc", "opowiedz bajkę"):
            self.assertFalse(story.wanted(t), t)
            self.assertFalse(story.handle(t, lambda *a: None), t)  # (her ordinary story)
        self.assertEqual(story._topic_of("interaktywna bajka o smoku"), "o smoku")
        self.assertEqual(story._topic_of("zagrajmy w bajkę"), "")
        c = ["wejść do jaskini", "polecieć nad morze"]
        self.assertEqual(story._match("pierwsze", c), 0)
        self.assertEqual(story._match("to drugie", c), 1)
        self.assertEqual(story._match("do jaskini!", c), 0)
        self.assertEqual(story._match("nad morze", c), 1)
        self.assertIsNone(story._match("nie wiem", c))
        import brain
        for t in ("opowiedz interaktywną bajkę o smoku", "pokaż moje bajki",
                  "opowiedz jeszcze raz bajkę o smoku"):
            self.assertTrue(brain._VOICED_OK.match(t), t)


class GLLayerUploadTest(unittest.TestCase):
    """gl_face.upload: the numpy way sends exactly the bands (and bytes) the
    old bytes way did — changed ones only, cleared ones once — and clear()
    wipes just the rows that were drawn on."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
            import pygame  # noqa: F401
        except ImportError:
            self.skipTest("pygame / numpy")

    def _gl(self):
        import gl_face
        from types import SimpleNamespace as NS
        sent = []
        GL = NS(GL_TEXTURE_2D=1, GL_UNSIGNED_BYTE=2, GL_RGBA=3, glBindTexture=lambda *a: None,
                glTexSubImage2D=lambda t, lv, x, y, w, h, f, ty, data: sent.append((y, h, bytes(data))))
        g = gl_face.GLFace.__new__(gl_face.GLFace)
        g.GL, g.uploaded = GL, 0
        return g, sent

    def test_numpy_and_bytes_send_the_same(self):
        import pygame
        import gl_face
        frames = []
        for f in range(4):
            s = gl_face.layer_surface(64, 96)
            if f in (0, 1):
                pygame.draw.circle(s, (250, 120, 30, 200), (20, 10), 6)    # band 0
            if f == 1:
                pygame.draw.rect(s, (10, 200, 90, 255), (5, 70, 30, 8))    # band 2 too
            if f == 3:
                pygame.draw.line(s, (255, 255, 255, 128), (0, 40), (63, 41), 3)
            frames.append(s)
        out = []
        for way in ("np", "bytes"):
            g, sent = self._gl()
            layer = gl_face._Layer(0, 64, 96)
            got = []
            for s in frames:
                del sent[:]
                if way == "np":
                    lit = g._upload_np(gl_face._numpy(), layer, s, 3)
                else:
                    lit = g._upload_bytes(layer, s, 3)
                got.append((lit, list(sent), layer.runs()))
            out.append(got)
        self.assertEqual(out[0], out[1])
        self.assertEqual([len(x[1]) for x in out[0]], [1, 1, 2, 1])   # changed bands only
        self.assertEqual(out[0][2], (False, out[0][2][1], []))
        self.assertEqual(out[0][3][2], [(32, 64)])

    def test_clear_and_padded_rows(self):
        import pygame
        import gl_face
        g, _ = self._gl()
        s = gl_face.layer_surface(64, 96)
        layer = gl_face._Layer(0, 64, 96)
        pygame.draw.circle(s, (250, 120, 30, 255), (30, 50), 5)
        self.assertTrue(g._upload_np(gl_face._numpy(), layer, s, 3))
        self.assertEqual(layer.runs(), [(32, 64)])
        self.assertEqual(layer.runs(40), [(0, 96)])          # (clamped to the layer)
        g.clear(layer, s)
        self.assertEqual(s.get_bounding_rect().width, 0)


class GlFxTest(unittest.TestCase):
    """gl_fx: what the GPU draws over the face — the waves placed to a
    fraction of a pixel, every hand pose fits the shader, HAL has a glyph
    for each."""

    def test_waves_are_not_rounded(self):
        import gl_fx
        a = gl_fx.arcs(412.37, 180.5, -1, [(87.07, 0.5), (61.3, 0.0)], (255, 196, 110))
        self.assertEqual(a[4][:2], (87.07, 61.3))
        self.assertEqual(a[5], (0.5, 0.0, 0.0))            # (padded to three, clamped)
        x0, y0, x1, y1 = gl_fx.bounds(a)
        self.assertLess(x0, 412.37 - 87.07)                # "(" reaches left of its centre
        self.assertEqual(x1, 412.37)

    def test_hands_fit_the_shader(self):
        try:
            import robot_face as rf
        except ImportError:
            self.skipTest("pygame")
        import gl_fx
        for pose in ("open", "paper", "fist", "point", "scissors", "ok", "thumb", "thumb_down"):
            parts = rf.hand_parts(pose)
            hb, hk, n, ring = gl_fx.hand_uniforms(parts)
            self.assertEqual(n, len([p for p in parts if p[0] == "box"]), pose)
            self.assertLessEqual(n, 8, pose)                  # uHB[8]
            self.assertEqual(ring[3], 1.0 if pose == "ok" else 0.0, pose)
            self.assertIn(rf.HAND_GLYPHS[pose], gl_fx.GLYPHS, pose)
        self.assertIn(rf.HAND_GLYPHS["hourglass"], gl_fx.GLYPHS)

    def test_particles_go_to_the_gpu(self):
        try:
            import pygame
            import robot_face as rf
        except ImportError:
            self.skipTest("pygame")
        s = pygame.Surface((80, 60), pygame.SRCALPHA)
        out = []
        rf._FX[id(s)] = out
        try:
            for P in (rf.SteamParticle, rf.StarParticle, rf.TearParticle, rf.ZzzParticle,
                      rf.HeartParticle, rf.SoundWave):
                P(30.4, 20.7).draw(s)
            rf.twinkle(s, 10.5, 10.5, 13, 200)
            rf.anger_mark(s, 50.2, 50, 44)
        finally:
            rf._FX.clear()
        self.assertEqual(s.get_bounding_rect().width, 0)          # nothing on the layer
        self.assertTrue(any(i[0] == "sprite" and i[3] == 30.4 for i in out))   # (unrounded)
        self.assertIn("ring", [i[0] for i in out])

    def test_theme_looks(self):
        import themes
        self.assertIn("glyphs", themes.THEMES["hal"]["look"])      # no hands for HAL
        self.assertEqual(themes.THEMES["hal"]["fx"], "robot")       # (the voice's, apart)
        top, bot, glow = themes.THEMES["ice"]["look"]["hand"]
        self.assertGreater(top[2], top[0] - 30)                     # frosty, not amber


class FramePaceTest(unittest.TestCase):
    """robot_face.ease: the animation's per-frame steps keep their pace at
    any frame rate — two half-length frames ease as far as one whole one,
    and a whole one is exactly the old lerp."""

    def test_ease_by_frame_length(self):
        try:
            import robot_face as rf
        except ImportError:
            self.skipTest("pygame")
        old = rf._K
        try:
            rf._K = 1.0
            self.assertEqual(rf.ease(10.0, 0.0, 0.3), rf.lerp(10.0, 0.0, 0.3))
            whole = rf.ease(10.0, 0.0, 0.3)
            rf._K = 0.5
            self.assertAlmostEqual(rf.ease(rf.ease(10.0, 0.0, 0.3), 0.0, 0.3), whole)
            rf._K = 2 / 3                             # 45 fps at the 30 fps pace
            x = 10.0
            for _ in range(3):
                x = rf.ease(x, 0.0, 0.3)
            rf._K = 1.0
            self.assertAlmostEqual(x, rf.ease(rf.ease(10.0, 0.0, 0.3), 0.0, 0.3))
        finally:
            rf._K = old


class FaceSpecTest(unittest.TestCase):
    """The face library (face_spec.py → gl_face's uniforms): every mood has
    its settings, every combination makes sane shader inputs — no GL needed."""

    MOODS = ("neutral", "happy", "excited", "love", "sad", "angry", "surprised",
             "thinking", "sleeping", "listening")

    def test_every_mood_and_only_known_settings(self):
        import face_spec
        import face_renderer
        for mood in set(face_renderer.EMOTION_MAP.values()) | set(self.MOODS):
            self.assertIn(mood, face_spec.MOODS, mood)
        for mood, s in face_spec.MOODS.items():
            for key, val in s.items():
                self.assertIn(key, face_spec.BASE, (mood, key))
                if isinstance(face_spec.BASE[key], tuple):
                    self.assertTrue(isinstance(val, tuple) and len(val) == 2, (mood, key))
        self.assertEqual(face_spec.spec("nonsense"), face_spec.spec("neutral"))

    def test_easing_is_frame_rate_independent(self):
        import face_spec
        a, b = face_spec.Eased(), face_spec.Eased()
        target = face_spec.spec("surprised")
        for _ in range(30):                       # one second at 30 fps…
            a.step(target, 1 / 30)
        for _ in range(8):                        # …and at 8 fps
            b.step(target, 1 / 8)
        self.assertAlmostEqual(a.cur["eye_h"], b.cur["eye_h"], delta=1.0)
        self.assertAlmostEqual(a.cur["round"], 1.0, delta=0.01)
        self.assertEqual(a.mouth, face_spec.O)    # the mouth's kind faded over

    def test_every_combination_makes_sane_uniforms(self):
        import math as _m
        for mood in self.MOODS:
            for costume in (None, "cat", "googly_eyes", "crazy_robot", "steampunk"):
                for blink in (1.0, 0.0):
                    for talking in (False, True):
                        gl = self._gl()
                        u = self._settle(gl, self._face(mood, costume, blink, talking), 6)
                        for key, val in u.items():
                            if key.startswith("_"):      # (the radio picture: gl_vis)
                                continue
                            for v in (val if isinstance(val, tuple) else (val,)):
                                self.assertTrue(_m.isfinite(v), (mood, costume, key, val))
                        self.assertIn(u["uMouthK"][3], (0.0, 1.0, 2.0, 3.0, 4.0, 5.0))
                        self.assertEqual(len(gl.shape_rects), 5)

    def test_the_moods_look_like_themselves(self):
        with self._fake_clock():
            self._the_moods_look_like_themselves()

    def _the_moods_look_like_themselves(self):
        gl = self._gl()
        u = self._settle(gl, self._face("sleeping"))
        self.assertGreater(u["uLidB0"][1], 0.9)               # shut: the seam shows
        self.assertEqual(u["uPupil0"][3], 0.0)                # no iris through it
        u = self._settle(gl, self._face("love"))
        self.assertGreater(u["uMorph"][0], 0.95)              # hearts
        u = self._settle(gl, self._face("excited"))
        self.assertGreater(u["uMorph"][3], 0.95)              # stars
        self.assertEqual(u["uMouthK"][3], 3.0)                # a grin
        u = self._settle(gl, self._face("angry"))
        self.assertGreater(u["uLidA0"][1], 0.3)               # the lids slant in
        self.assertGreater(u["uTintAmt"], 0.4)
        self.assertEqual(u["uMouthK"][3], 4.0)                # gritted teeth
        u = self._settle(gl, self._face("surprised"))
        self.assertGreater(u["uMorph"][2], 0.95)              # round
        self.assertEqual(u["uMouthK"][3], 2.0)
        u = self._settle(gl, self._face("thinking"))
        self.assertNotEqual(u["uBrow0"][1], u["uBrow1"][1])   # one brow up
        u = self._settle(gl, self._face("neutral", blink=0.0))
        self.assertGreater(u["uLidB0"][1], 0.9)               # a blink closes the lids
        u = self._settle(gl, self._face("neutral", talking=True))
        self.assertEqual(u["uMouthK"][3], 1.0)                # her voice opens the mouth
        self.assertGreaterEqual(u["uMouth"][3], 24.0)         # (never a lips-only sliver)
        u = self._settle(gl, self._face("happy", "googly_eyes"))
        self.assertLess(u["uBrowK"][3], 0.01)                 # googly: no brows…
        self.assertEqual(u["uTop"], (1.0, 1.0, 1.0))          # …white eyes
        u = self._settle(gl, self._face("neutral", mod={"mouth": 5}))
        self.assertEqual(u["uMouthK"][3], 5.0)                # a scene's touch on top

    def test_saccades_stay_small_at_any_frame_rate(self):
        # (one spring step per frame blew up at 20 fps: pupils flew to the edges)
        import gl_face
        for dt in (1 / 30, 1 / 20, 1 / 8, 0.3):
            life = gl_face._Life()
            t = 0.0
            for _ in range(400):
                t += dt
                life.step(t, dt, True)
                self.assertLess(max(abs(v) for v in life.sacc_now), 7.0, dt)

    def test_the_habits_stay_in_bounds(self):
        import gl_face
        life = gl_face._Life()
        life.lids += [(0.0, 0.22, 1.0), (0.1, 1.2, 0.85)]
        life.yawn_t = 0.0
        for k in range(160):
            t = k * 0.01
            self.assertTrue(0.0 <= life.lid(t) <= 1.0)
            self.assertTrue(0.0 <= life.yawn(t) <= 1.0)
        self.assertEqual(life.lid(5.0), 0.0)                  # all done…
        life.prune(5.0)
        self.assertEqual(life.lids, [])                       # …and forgotten
        life.lids.append((6.0, 0.35, 1.0, 1))                 # one eye only
        self.assertEqual(life.lid(6.1, 0), 0.0)
        self.assertGreater(life.lid(6.1, 1), 0.5)
        self.assertEqual(life.yawn(5.0), 0.0)
        life.moods(10.0, "neutral", True, 0.0, False)         # starts talking
        life.moods(11.0, "neutral", False, 0.0, False)        # …and stops
        self.assertEqual(life.press_t, 11.0)                  # the lips press
        life.moods(12.0, "neutral", False, 0.5, False)        # drowsy: one yawn
        self.assertEqual(life.yawn_t, 12.0)
        life.moods(13.0, "neutral", False, 0.6, False)
        self.assertEqual(life.yawn_t, 12.0)                   # (just the one)

    def test_every_mood_with_its_habits_makes_sane_uniforms(self):
        import math as _m
        for mood in self.MOODS:
            for listen in (False, True):
                gl = self._gl()
                face = self._face(mood, talking=False, listen=listen)
                face._drowsy = 0.6                            # a yawn in there too
                u = self._settle(gl, face, 30)
                gl.life.lids.append((gl.life.lids[0][0] if gl.life.lids else 0.0, 0.5, 0.45))
                u = self._settle(gl, self._face(mood, talking=True, listen=listen), 30)
                for key, val in u.items():
                    if key.startswith("_"):
                        continue
                    for v in (val if isinstance(val, tuple) else (val,)):
                        self.assertTrue(_m.isfinite(v), (mood, key, val))
                for i in (0, 1):
                    top, _, _, bot = u[f"uLidA{i}"]
                    self.assertLessEqual(top + bot, 1.001, (mood, i))

    def test_a_touch_draws_the_eyes(self):
        import time as _t
        gl = self._gl()
        face = self._face("neutral")
        u0 = self._settle(gl, face, 10)
        # a tap on the right eye (px, as robot_face stores it): that eye
        # flinches shut, the other doesn't, and the pupils stay put
        face._touch_kind, face._touch_zone = "tap", "eye"
        face._touch_pt, face._touch_react_t = (560, 190), _t.time() - 0.3
        self._settle(gl, face, 1)
        _t.sleep(0.1)                                         # (the habits run on real time)
        u = self._settle(gl, face, 1)
        self.assertGreater(u["uLidA1"][0], u0["uLidA1"][0] + 0.1)
        self.assertLess(u["uLidA0"][0], u0["uLidA0"][0] + 0.05)
        self.assertLess(abs(u["uPupil0"][0] - u0["uPupil0"][0]), 8.0)
        # a stroke low on the right: a glance down and right, not to a corner
        face._touch_kind, face._touch_zone = "stroke", "cheek"
        face._touch_pt, face._touch_react_t = (700, 400), _t.time() - 0.5
        u = self._settle(gl, face, 2)
        self.assertGreater(u["uPupil1"][0], u0["uPupil1"][0] + 10)
        self.assertGreater(u["uPupil1"][1], u0["uPupil1"][1] + 5)
        self.assertLess(u["uPupil1"][0], 0.35 * u["uEye1"][2])

    def test_boop_tickle_and_flash(self):
        import time as _t
        gl = self._gl()
        face = self._face("neutral")
        u0 = self._settle(gl, face, 10)
        face._touch_kind, face._touch_zone = "tap", "mouth"   # boop: on the nose
        face._touch_pt, face._touch_react_t = (400, 212 + 84), _t.time()
        self._settle(gl, face, 1)
        _t.sleep(0.25)
        u = self._settle(gl, face, 1)
        self.assertGreater(u["uPupil0"][0], u0["uPupil0"][0] + 6)    # cross-eyed: in…
        self.assertLess(u["uPupil1"][0], u0["uPupil1"][0] - 6)
        for k in range(3):                                    # tap-tap-tap: a giggle
            face._touch_pt, face._touch_react_t = (100, 400), _t.time() + k * 0.01
            self._settle(gl, face, 1)
        self.assertGreater(gl.life.giggle_t, 0.0)
        face._flash_t = _t.time()                             # a photo: dazzled
        u = self._settle(self._gl(), face, 3)
        self.assertGreater(u["uLidA0"][0], u0["uLidA0"][0] + 0.2)

    def test_the_mouth_follows_the_sound(self):
        import gl_face
        vo = gl_face.GLFace.viseme_of
        o, e, s = vo((0.06, 0.03)), vo((0.24, 0.05)), vo((1.2, 0.45))
        self.assertLess(o[0], e[0] - 0.3)                     # "o": narrower than "e"…
        self.assertGreater(o[1], e[1] + 0.3)                  # …and taller
        self.assertLess(o[2], 0.05)
        self.assertGreater(s[2], 0.9)                         # "s": the teeth
        self.assertLess(s[1], 0.6)                            # …through a narrow gap
        gl = self._gl()                                       # and through face_uniforms
        face = self._face("neutral", talking=True)
        face._audio_shape = (0.06, 0.03)
        uo = self._settle(gl, face, 12)
        face._audio_shape = (0.24, 0.05)
        ue = self._settle(gl, face, 12)
        self.assertLess(uo["uMouth"][2], ue["uMouth"][2] - 40)

    def test_hals_wave_follows_the_pitch(self):
        import numpy as np
        import openai_tts
        import gl_face
        import themes
        t = np.arange(480 * 4) / 24000.0
        def split(hz):
            a = (8000 * np.sin(2 * np.pi * hz * t)).astype(np.float32).reshape(-1, 480)
            return openai_tts.Envelope.band_split(a).mean(axis=0)
        lo, mid, hi = split(200), split(900), split(3500)
        self.assertGreater(lo[0], 0.8)                        # a hum: the long wave
        self.assertGreater(mid[1], 0.8)                       # a vowel: the ripple
        self.assertGreater(hi[2], 0.8)                        # a hiss: the fine buzz
        env = openai_tts.Envelope()
        env.feed((8000 * np.sin(2 * np.pi * 3500 * t)).astype(np.int16).tobytes())
        env.start_at(100.0)
        self.assertGreater(env.bands_at(100.01)[2], 0.8)
        themes.set_theme("hal")
        try:
            gl = self._gl()
            face = self._face("neutral", talking=True)
            face._audio_bands = (0.0, 0.0, 1.0)
            u = self._settle(gl, face, 12)
            self.assertGreater(u["uWaveBands"][2], 0.9)       # the lips buzz with the hiss
            face._audio_bands = (1.0, 0.0, 0.0)
            u = self._settle(gl, face, 12)
            self.assertGreater(u["uWaveBands"][0], 0.9)
        finally:
            themes.set_theme("luna")

    def test_people_coming_and_going(self):
        gl = self._gl()
        face = self._face("neutral")
        u0 = self._settle(gl, face, 10)
        import time as _t
        face._face_seen = True
        self._settle(gl, face, 1)
        _t.sleep(0.2)                                         # (the habits run on real time)
        u = self._settle(gl, face, 1)
        self.assertLess(u["uBrow0"][1], u0["uBrow0"][1] - 4)       # an eyebrow flash
        face.left_eye.pupil_ox = 60.0
        self._settle(gl, face, 2)
        face._face_seen, face.left_eye.pupil_ox = False, 0.0
        u = self._settle(gl, face, 2)
        self.assertGreater(u["uPupil0"][0], 25.0)                  # still looking there

    def test_eye_effects_and_heart_lids(self):
        gl = self._gl()
        face = self._face("neutral")
        face._eye_fx = (1.0, 0.0)                             # dizzy: spirals
        u = self._settle(gl, face, 2)
        self.assertEqual(u["uFx"][:2], (1.0, 0.0))
        face._eye_fx = (0.0, 0.0)
        self.assertEqual(self._settle(gl, face, 1)["uFx"][:2], (0.0, 0.0))
        love = self._settle(self._gl(), self._face("love", mod={"lid_top": (0.5, 0.5)}))
        self.assertGreater(love["uEye0"][3], 140.0)                  # hearts stay whole

    def test_reply_scenes_set_only_known_settings(self):
        try:
            import reply_scenes
        except ImportError:                       # (no pygame here)
            self.skipTest("pygame")
        import face_spec
        for name, sc in reply_scenes.SCENES.items():
            for p in (0.3, 0.5, 0.7):
                face = self._face(sc.mood or "neutral")
                sc.face(face, p)
                for key, val in face._spec_mod.items():
                    self.assertIn(key, face_spec.BASE, (name, key))
                    self.assertEqual(isinstance(val, tuple),
                                     isinstance(face_spec.BASE[key], tuple), (name, key))

    def _face(self, mood, costume=None, blink=1.0, talking=False, listen=False, mod=None):
        from types import SimpleNamespace as NS
        eye = lambda x: NS(rel_x=x, rel_y=-30, w=206.0, h=148.0, pupil_ox=4.0, pupil_oy=-2.0,
                           squint=0.0, widen=0.0, blink_t=blink, pupil_scale=1.0)
        return NS(_emotion=mood, _costume=costume, _listen=listen, breath_phase=1.0,
                  head_angle=2.0, _eye_color=None, angry_pulse=0.0,
                  left_eye=eye(-150), right_eye=eye(150), _speaking=talking,
                  mouth=NS(rel_x=0, rel_y=155, speak_fade=1.0 if talking else 0.0,
                           talk_open=0.5 if talking else 0.0, mouth_w=160.0,
                           jaw_bounce=0.0, corner_lift=0.5),
                  _scene_p=0.0, _scene_name=None, _spec_mod=mod or {}, _pupil_converge=0.0)

    def _gl(self):
        import face_spec
        import gl_face
        gl = gl_face.GLFace.__new__(gl_face.GLFace)
        gl.w, gl.h, gl.eased, gl._t_last, gl.shape_rects = 800, 480, face_spec.Eased(), 0.0, []
        return gl

    def _rf(self):
        from types import SimpleNamespace as NS
        return NS(EYE_MODE="block", EYE_GRAD_TOP=(255, 232, 140), EYE_GRAD_BOTTOM=(232, 96, 12),
                  GLOW_COL=(255, 125, 20), IRIS_SHINE=(255, 250, 225), PUPIL_DARK=(28, 12, 2),
                  IRIS_COL=(132, 58, 12), BLUSH_COL=(255, 120, 95), ANGRY_COL=(255, 55, 30),
                  EYE_SPREAD=150, BLOCK_PUPIL=True)

    _clock = None                                 # [now] while _fake_clock() runs

    def _settle(self, gl, face, frames=40):
        import time as _t
        for _ in range(frames):
            if self._clock:
                self._clock[0] += 0.05
            else:
                gl._t_last = _t.monotonic() - 0.05      # 20 fps worth of time each call
            u = gl.face_uniforms(face, self._rf(), 400, 212)
        return u

    def _fake_clock(self):
        """gl_face on a clock that moves 50 ms per _settle frame, not with the
        wall: timed habits (love's 1.2 s slow blink) can't spill into the next mood."""
        import contextlib
        import time as _t
        from types import SimpleNamespace as NS
        from unittest import mock
        import gl_face
        self._clock = [1000.0]
        now = lambda: self._clock[0]
        fake = NS(monotonic=now, time=now, localtime=lambda *a: _t.localtime(12 * 3600))
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(gl_face, "time", fake))
        stack.callback(setattr, self, "_clock", None)
        return stack


class GreetingsTest(unittest.TestCase):
    """17 Oct, Andrzej: more hellos than "Miło cię widzieć" — by name, by
    the hour, never the last few again."""

    def setUp(self):
        import greetings
        greetings._recent.clear()

    def _at(self, h, wday=2):
        # 14 Oct 2026 is a Wednesday
        return datetime.datetime(2026, 10, 12 + wday, h, 0).timestamp()

    def test_a_wave_by_name_and_never_the_same_twice_running(self):
        import faces
        import greetings
        with mock.patch.object(faces, "vocatives", lambda: {"Maja": "Maju"}):
            said = [greetings.wave("Maja", now=self._at(15)) for _ in range(12)]
        self.assertTrue(any("Maju" in s for s in said))
        self.assertFalse(any("Maja" in s or "{" in s for s in said))
        for a, b in zip(said, said[1:]):
            self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(set(said)), 8)
        nobody = {greetings.wave(None, now=self._at(15)) for _ in range(30)}
        self.assertGreaterEqual(len(nobody), 10)

    def test_no_questions_or_gender_in_a_wave(self):
        import greetings
        for p in (greetings.WAVE + greetings.WAVE_NAMED + greetings.WAVE_CHILD
                  + greetings.WAVE_MORNING + greetings.WAVE_EVENING + greetings.WAVE_NIGHT):
            self.assertNotIn("?", p)               # the answer would need "Luna"
        for p in sum([greetings.WAVE, greetings.MORNING, greetings.DAY, greetings.EVENING,
                      greetings.NIGHT, greetings.SHORT_AWAY, greetings.LONG_AWAY,
                      greetings.FIRST_TODAY], []):
            self.assertNotRegex(p, r"(?:łeś|łaś)\b")

    def test_the_hour_and_the_absence(self):
        import greetings
        night = {greetings.wave(None, now=self._at(23)) for _ in range(10)}
        self.assertTrue(night <= set(greetings.WAVE_NIGHT) | {"Cześć."})
        for _ in range(10):
            self.assertIn(greetings.hello(away=600, now=self._at(14)),
                          greetings.DAY + greetings.SHORT_AWAY)
            self.assertIn(greetings.hello(now=self._at(20)), greetings.EVENING)
        friday = {greetings.hello(now=self._at(14, wday=4)) for _ in range(40)}
        self.assertTrue(friday & set(greetings.WEEKDAY[4]))
        self.assertIn(greetings.hello(first_today=True, now=self._at(14)),
                      greetings.FIRST_TODAY)

    def test_goodbyes_and_good_nights_by_name(self):
        import faces
        import greetings
        with mock.patch.object(faces, "vocatives", lambda: {"Maja": "Maju"}):
            byes = [greetings.bye("Maja", now=self._at(15)) for _ in range(12)]
            nights = [greetings.night("Maja") for _ in range(6)]
        self.assertTrue(any("Maju" in s for s in byes))
        self.assertTrue(any("Maju" in s for s in nights))
        self.assertFalse(any("{" in s or "Maja" in s for s in byes + nights))
        for a, b in zip(byes, byes[1:]):
            self.assertNotEqual(a, b)
        self.assertIn(greetings.night(None), greetings.GOODNIGHT)
        self.assertNotIn("Miłego dnia", " ".join(greetings.bye(None, now=self._at(23))
                                                   for _ in range(20)))


class MouthTest(unittest.TestCase):
    """mouth.py: a talking mouth seen by the camera."""

    def setUp(self):
        import numpy as np
        # box 200,150 160x200; eyes (240,220) (320,220); nose (280,260); mouth (250,300) (310,300)
        self.marks = np.array([200, 150, 160, 200, 240, 220, 320, 220, 280, 260,
                               250, 300, 310, 300], np.float32)

    def _frame(self, seed, mouth_seed=None):
        import numpy as np
        f = np.random.RandomState(seed).randint(0, 255, (480, 640, 3)).astype(np.uint8)
        if mouth_seed is not None:                  # only the mouth changes
            m = np.random.RandomState(mouth_seed).randint(0, 255, (60, 80, 3)).astype(np.uint8)
            f[280:340, 240:320] = m
        return f

    def test_boxes_sit_on_the_mouth_and_above_the_nose(self):
        import mouth
        (mx, my, mw, mh), (rx, ry, rw, rh) = mouth.boxes(self.marks)
        self.assertAlmostEqual(mx, 280)
        self.assertGreater(my, 300)
        self.assertAlmostEqual(mw, 90)
        self.assertLess(ry, 260)
        self.assertLess(ry + rh / 2, my - mh / 2)       # the two boxes don't overlap

    def _cur(self, frame):
        import mouth
        m, r = mouth.boxes(self.marks)
        return mouth._patch(frame, *m, (24, 16)), mouth._patch(frame, *r, (12, 10))

    def test_a_moving_mouth_talks_and_a_still_face_does_not(self):
        import mouth
        a, b = self._cur(self._frame(1, 10)), self._cur(self._frame(1, 11))
        dm, dr = mouth.change(a, b)
        self.assertGreater(dm, 0.5)
        self.assertTrue(mouth.talking(dm, dr, 8))
        self.assertFalse(mouth.talking(*mouth.change(a, a), 8))
        self.assertFalse(mouth.talking(dm, dr, 2))          # too few frames

    def test_the_whole_picture_changing_is_not_talking(self):
        import mouth
        a, b = self._cur(self._frame(1)), self._cur(self._frame(2))
        self.assertFalse(mouth.talking(*mouth.change(a, b), 8))

    def test_numbers_from_the_room(self):
        import mouth
        # 17 Oct dump, per-second averages (mouth, above the nose)
        self.assertTrue(mouth.talking(0.12, 0.05, 8))       # talking over her story
        self.assertTrue(mouth.talking(0.14, 0.04, 8))
        self.assertTrue(mouth.talking(0.13, 0.07, 8))       # in bursts, head a bit (22:35)
        self.assertFalse(mouth.talking(0.03, 0.03, 8))      # listening, still
        self.assertFalse(mouth.talking(0.07, 0.06, 8))      # still, noisier light
        self.assertFalse(mouth.talking(0.40, 0.68, 8))      # turning the head
        self.assertFalse(mouth.talking(0.26, 0.17, 8))      # head settling

    def test_patch_off_the_frame_or_flat_is_none(self):
        import numpy as np
        import mouth
        f = self._frame(1)
        self.assertIsNone(mouth._patch(f, 5, 5, 40, 40, (24, 16)))
        self.assertIsNone(mouth._patch(np.zeros((480, 640, 3), np.uint8), 300, 300, 40, 40, (24, 16)))

    def test_during_and_describe(self):
        import mouth
        now = 1000.0
        saved = list(mouth._hist)
        try:
            mouth._hist.clear()
            for i in range(30):                      # 2 s at 15 a second: still, then talking
                mouth._hist.append((now - 2 + i / 15, (0.15, 0.04) if i >= 15 else (0.03, 0.03)))
            share, talk, best = mouth.during(2.0, now)
            self.assertEqual(share, 1.0)
            self.assertGreater(talk, 0.3)
            self.assertLess(talk, 0.6)
            self.assertGreater(best, 3.0)
            self.assertIn("face 100%", mouth.describe(2.0, now))
            self.assertIn("talking", mouth.describe(2.0, now))
            mouth._hist.clear()
            for i in range(30):
                mouth._hist.append((now - 2 + i / 15, None))
            self.assertIn("no face", mouth.describe(2.0, now))
            mouth._hist.clear()
            self.assertEqual(mouth.describe(2.0, now), "mouth: no camera")
        finally:
            mouth._hist.clear()
            mouth._hist.extend(saved)


class ImprovementsTest(unittest.TestCase):
    """17 Oct, the ten proposals: radio scraps not sent to the cloud, the
    radio's night volume, the plan for the day said aloud, to-dos with a day,
    an undo that survives a restart, the week's report."""

    def setUp(self):
        lists._lists = {}
        lists._undo = None

    def _at(self, h, day=17):
        return datetime.datetime(2026, 10, day, h, 0).timestamp()

    def test_radio_scraps_are_not_sent_to_the_cloud(self):
        import speech_to_text as stt
        with mock.patch.object(stt, "_cloud", object()), \
             mock.patch.object(stt, "CLOUD_WAKE_CHECK", True), \
             mock.patch.object(stt, "call_pause", lambda: False), \
             mock.patch.object(stt, "_face_invites", lambda w: False):
            with mock.patch.object(stt, "_radio_on", lambda: True):
                self.assertFalse(stt._wake_check_worth(["nie"]))
                # ("panie panie" still goes: 0.6 like "lunie" — rare enough)
                self.assertTrue(stt._wake_check_worth(["luną", "włącz", "jazz"]))
                # 21:09 "Luna, jaka jutro pogoda?" under the radio — Vosk:
                self.assertTrue(stt._wake_check_worth("nuda i pobudzi oczu powoda".split()))
                with mock.patch.object(stt, "_energy_gate", lambda: 2000):
                    # "to co turę" ("to co, jutro?"), loud and close: checked
                    self.assertTrue(stt._wake_check_worth(["to", "co", "turę"], peak=9944))
                    # the radio's own quiet scraps: not
                    self.assertFalse(stt._wake_check_worth(["inni", "mi"], peak=2900))
            with mock.patch.object(stt, "_radio_on", lambda: False):
                self.assertTrue(stt._wake_check_worth(["nie"]))

    def test_radio_on_a_talking_face_gets_the_cloud_check(self):
        import mouth
        import speech_to_text as stt
        with mock.patch.object(stt, "_cloud", object()), \
             mock.patch.object(stt, "CLOUD_WAKE_CHECK", True), \
             mock.patch.object(stt, "call_pause", lambda: False), \
             mock.patch.object(stt, "_radio_on", lambda: True), \
             mock.patch.object(stt, "_energy_gate", lambda: 2000):
            # "bobby co byłoby" (17 Oct 21:09, "Luna, …" under the radio)
            words = ["bobby", "co", "byłoby"]
            with mock.patch.object(mouth, "during", lambda secs, now=None: (1.0, 0.3, 3.0)):
                self.assertTrue(stt._wake_check_worth(words, peak=2000, secs=2.0))
            with mock.patch.object(mouth, "during", lambda secs, now=None: (1.0, 0.0, 1.1)):
                self.assertFalse(stt._wake_check_worth(words, peak=2000, secs=2.0))
            with mock.patch.object(mouth, "during", lambda secs, now=None: (0.1, 0.5, 3.0)):
                self.assertFalse(stt._wake_check_worth(words, peak=2000, secs=2.0))  # face barely seen
            with mock.patch.object(mouth, "during", lambda secs, now=None: None):
                self.assertFalse(stt._wake_check_worth(words, peak=2000, secs=2.0))  # no camera

    def test_no_transcript_and_vosk_unsure_is_a_guess(self):
        import speech_to_text as stt
        with mock.patch.object(stt, "_cloud", object()):
            self.assertTrue(stt._unsure(None, 0.84))        # 23:22 "włącz drogie" 0.84
            self.assertFalse(stt._unsure(None, 0.95))       # Vosk sure: taken
            self.assertFalse(stt._unsure("Włącz radio.", 0.5))
            self.assertFalse(stt._unsure("", 0.5))          # heard nothing: dropped elsewhere
        with mock.patch.object(stt, "_cloud", None):        # no cloud set up: Vosk is all
            self.assertFalse(stt._unsure(None, 0.5))

    def test_radio_on_a_sentence_seen_said_to_her_is_for_her(self):
        import faces
        import mouth
        import speech_to_text as stt
        talk = lambda share: (lambda secs, now=None: (1.0, share, 2.5))
        with mock.patch.object(stt, "_radio_on", lambda: True), \
             mock.patch.object(faces, "names", lambda: ["Andrzej", "Maja", "Emilka"]):
            with mock.patch.object(mouth, "during", talk(0.48)):
                self.assertEqual(stt._seen_saying_it("Jaka będzie jutro pogoda?", 2.0),
                                 "Jaka będzie jutro pogoda?")
                self.assertEqual(stt._seen_saying_it("Maja, jaka będzie jutro pogoda?", 2.0),
                                 "jaka będzie jutro pogoda?")
                self.assertEqual(stt._seen_saying_it("Runa, która godzina?", 2.0),
                                 "która godzina?")
                self.assertEqual(stt._seen_saying_it("Dobra, poczekaj.", 2.0), "Dobra, poczekaj.")
                self.assertIsNone(stt._seen_saying_it("Okej.", 2.0))           # one word
                self.assertIsNone(stt._seen_saying_it("", 2.0))
            with mock.patch.object(mouth, "during", talk(0.0)):
                self.assertIsNone(stt._seen_saying_it("Jaka będzie jutro pogoda?", 2.0))
        with mock.patch.object(stt, "_radio_on", lambda: False), \
             mock.patch.object(mouth, "during", talk(0.48)):
            self.assertIsNone(stt._seen_saying_it("Jaka będzie jutro pogoda?", 2.0))

    def test_the_radio_quiets_for_her_name_not_for_any_talking_face(self):
        import speech_to_text as stt
        talked = lambda yes: mock.patch.object(stt, "_mouth_talked", lambda secs: yes)
        with mock.patch.object(stt, "_radio_on", lambda: True):
            with talked(True):
                self.assertTrue(stt._name_in_partial("nuda jaka jutro".split()))   # Vosk's "Luna"
                self.assertFalse(stt._name_in_partial("co dziś na obiad".split()))  # talking, no name
            with talked(False):
                self.assertTrue(stt._name_in_partial("luna jaka".split()))         # her name: always
                self.assertFalse(stt._name_in_partial("nuda jaka jutro".split()))  # the radio's own
        with mock.patch.object(stt, "_radio_on", lambda: False), talked(True):
            self.assertFalse(stt._name_in_partial("nuda jaka jutro".split()))

    def test_the_radio_ducks_as_soon_as_her_name_is_said(self):
        import radio
        with state.lock:
            saved = (state.speaking, state.listening, state.conversation_active,
                     state.name_heard_at)
            state.speaking = state.listening = state.conversation_active = False
            state.name_heard_at = 0.0
        try:
            self.assertFalse(radio._ducked())
            with state.lock:
                state.name_heard_at = time.time()
            self.assertTrue(radio._ducked())
        finally:
            with state.lock:
                (state.speaking, state.listening, state.conversation_active,
                 state.name_heard_at) = saved

    def test_the_radio_has_a_day_and_a_night_volume(self):
        import radio
        self.assertEqual(radio._level_key(self._at(14)), "radio_level")
        self.assertEqual(radio._level_key(self._at(23)), "radio_level_night")
        self.assertEqual(radio._level_key(self._at(6)), "radio_level_night")
        with mock.patch.object(settings, "get",
                               lambda k, d=None: {"radio_level": 1.5}.get(k, d)):
            self.assertEqual(radio._gain(self._at(14)), 1.5)
            self.assertEqual(radio._gain(self._at(23)), 0.7)     # never louder at night
        for t in ("zapamiętaj tę głośność", "Luna, zapamiętaj taką głośność"):
            self.assertTrue(radio._KEEP_LEVEL.search(t.lower()), t)

    def test_to_dos_with_a_day(self):
        now = self._at(12)                     # Saturday 17 October
        self.assertEqual(lists.dated("zadzwonić do babci jutro", now),
                         "zadzwonić do babci (18 października)")
        self.assertEqual(lists.dated("w poniedziałek oddać książkę", now),
                         "oddać książkę (19 października)")
        self.assertEqual(lists.dated("umyć auto", now), "umyć auto")
        self.assertEqual(lists.dated("wypłacić pieniądze 16 października", now),
                         "wypłacić pieniądze 16 października")
        self.assertEqual(lists.due("x 5 stycznia", now).year, 2027)     # next January
        lists.apply([{"type": "list_add", "list": "do zrobienia",
                      "label": "wypłacić pieniądze na drewno 16 października"},
                     {"type": "list_add", "list": "do zrobienia", "label": "kupić drewno dziś"},
                     {"type": "list_add", "list": "zakupy", "label": "mleko na jutro"}])
        self.assertIn("mleko na jutro", lists.get("zakupy"))       # shopping: as said
        rows = lists.due_rows()
        kinds = [k for k, _ in rows]
        self.assertEqual(kinds[0], "zaległe")
        self.assertIn("dziś", kinds)

    def test_the_undo_survives_a_restart(self):
        lists.apply([{"type": "list_add", "list": "do zrobienia", "label": "umyć auto"}])
        self.assertTrue(lists.remove_exact("do zrobienia", "umyć auto"))
        lists._lists, lists._undo = None, None            # as after a restart
        lists._load()
        self.assertIsNotNone(lists._undo)
        self.assertIn("umyć auto", lists.restore("przywróć listę"))
        self.assertEqual(lists.get("do zrobienia"), ["umyć auto"])
        self.assertFalse(os.path.exists(lists._undo_path()))

    def test_the_plan_for_the_day_said_aloud(self):
        import screens
        rows = [("08:30", "dentysta"), ("dziś", "kupić drewno (17 października)"),
                ("zaległe", "wypłacić pieniądze 16 października"),
                ("dziś!", "urodziny: Maja"), ("pogoda", "pochmurno, 8–14°C, rain chance 60%"),
                ("lista", "do zrobienia: 3"), ("lista", "zakupy: 5")]
        with mock.patch.dict(sys.modules, {"weather": mock.Mock(
                _summary="Today: pochmurno, 8–14°C, rain chance 60%; sunrise")}):
            said = screens.today_said(rows)
        for part in ("O 08:30 dentysta", "Zaległe: wypłacić", "Dziś trzeba: kupić drewno.",
                     "Urodziny: Maja", "3 sprawy", "od 8 do 14 stopni",
                     "szansa deszczu 60 procent"):
            self.assertIn(part, said)
        self.assertNotIn("rain", said)
        self.assertTrue(screens.wants_today("Luna, co mnie dziś czeka?"))

    def test_the_weeks_report(self):
        import weekly
        weekly._days = {}
        for line in ("[STT] Dropped (noise): \"nie\" conf=0.3",
                     "[STT] cloud heard no speech — dropping Vosk's \"pół\"",
                     "[STT] false wake — \"ludzie\" was not her name",
                     "[faces] this is Andrzej (0.47)"):
            weekly.note(line)
        with mock.patch.object(weekly, "_child", lambda w: w == "Maja"):
            with state.lock:
                saved, state.person = state.person, ("Maja", 0.8, time.time())
            try:
                for t in ("opowiedz mi o dinozaurach", "jakie dinozaury latały", "ile waży słoń"):
                    weekly.heard(t)
            finally:
                with state.lock:
                    state.person = saved
            said, rows = weekly.report()
        self.assertIn("usłyszałam 3 zdania", said)
        self.assertIn("2 razy wzięłam szum", said)
        self.assertIn("1 raz obudziłam się niepotrzebnie", said)
        self.assertIn("Maja (3)", said)
        self.assertTrue(rows)
        self.assertTrue(weekly.wanted("Luna, podsumowanie tygodnia"))
        self.assertFalse(weekly.wanted("jak ci minął tydzień?"))   # small talk: the model
        self.assertFalse(weekly.wanted("co robimy w tym tygodniu?"))



class RadioVisualizerTest(unittest.TestCase):
    """visualizer.py: the radio's bands follow the sound, heard when it's
    heard (not when decoded), fade out when it stops; the voice styles."""

    def setUp(self):
        import visualizer
        self.v = visualizer
        self.clock = [1000.0]
        self._time = visualizer.time
        visualizer.time = type("T", (), {"time": staticmethod(lambda: self.clock[0])})()
        visualizer.reset()
        visualizer._ref[:] = 0.0
        visualizer._cur.update(bands=visualizer._cur["bands"] * 0, l=0.0, r=0.0, on=0.0, t=0.0)
        visualizer._style[:] = ["wstegi", 1e12]

    def tearDown(self):
        self.v.time = self._time
        self.v.reset()
        self.v._style[:] = [None, 0.0]

    def _feed(self, f, n=30, amp=3000.0):
        import numpy as np
        t = np.arange(4410) / 44100.0
        rng = np.random.default_rng(1)
        u = None
        for _ in range(n):
            x = np.sin(2 * np.pi * f * t) * amp + rng.normal(0, 300, t.size)
            self.v.tap(np.stack([x, x * 0.3], 1).ravel().astype(np.float32), 1500.0)
            for _ in range(3):
                self.clock[0] += 0.0333
                u = self.v.uniforms()
        return u

    def _bands(self, u):
        import numpy as np
        return np.array(u["uVis0"] + u["uVis1"] + u["uVis2"] + u["uVis3"])

    def test_bands_follow_the_pitch(self):
        low = self._bands(self._feed(100)).argmax()
        self.v.reset()
        high = self._bands(self._feed(8000)).argmax()
        self.assertLess(low, 4)
        self.assertGreater(high, 11)

    def test_shown_while_playing_left_louder_fades_after(self):
        u = self._feed(440)
        self.assertGreater(u["uVisK"][1], 0.8)            # on, full strength
        self.assertEqual(u["uVisK"][0], 1.0)              # ribbons
        self.assertGreater(u["uVisLR"][0], u["uVisLR"][1])   # (the left channel louder)
        for _ in range(90):                               # 3 s with nothing coming
            self.clock[0] += 0.0333
            u = self.v.uniforms()
        self.assertLess(u["uVisK"][1], 0.05)

    def test_waits_for_the_audio_to_be_heard(self):
        import numpy as np
        x = np.zeros(8820, np.float32) + 0.0
        x[::2] = 4000.0 * np.sin(np.arange(4410) * 0.3)
        self.v.tap(x, 1500.0)                              # queued ~0.47 s ahead
        self.clock[0] += 0.1
        self.assertLess(max(self._bands(self.v.uniforms())), 0.01)
        self.clock[0] += 0.5
        self.assertGreater(max(self._bands(self.v.uniforms())), 0.05)

    def test_styles_and_talking(self):
        self._feed(440, n=10)
        self.v._style[:] = ["slupki", 1e12]
        self.assertEqual(self.v.uniforms()["uVisK"][0], 4.0)
        self.v._style[:] = ["losowo", 1e12]
        self.v.new_song("A")
        first = self.v.shown()
        self.v.new_song("B")
        self.assertNotEqual(self.v.shown(), first)        # another with each song
        self.assertNotIn(self.v.shown(), ("losowo", "off"))
        self.assertLess(self.v.uniforms(talking=True)["uVisK"][1], 0.5)
        self.v._style[:] = ["off", 1e12]
        self.assertEqual(self.v.uniforms()["uVisK"][1], 0.0)

    def test_voice(self):
        import settings
        put, get, said, st = settings.put, settings.get, [], {"radio_vis": "off"}
        settings.put = lambda k, val: st.__setitem__(k, val)
        settings.get = lambda k, d=None: st.get(k, d)
        try:
            for text, want in (("pokaż słupki", "slupki"), ("włącz falę", "wstegi"),
                               ("pokaż nutki", "nutki"),
                               ("wyłącz efekty", "off"),
                               ("włącz efekt", "nutki"),          # 18 Oct: back to the last one
                               ("wyłącz wizualizację", "off"),
                               ("włącz wizualizację", "nutki"),
                               ("włącz efekt w radiu fale", "wstegi"),   # (was the sea)
                               ("zmień efekt", "pierscienie"),
                               ("pokaż nutki", "nutki"), ("pokaż iskry", "iskry"),
                               ("efekt oscyloskop", "oscyloskop"),
                               ("pokaż pierścienie", "pierscienie"),
                               ("efekty losowo", "losowo"),
                               ("efekt z serduszkiem", "oscyloskop")):
                self.v._style[:] = [None, 0.0]
                self.assertTrue(self.v.handle(text, said.append), text)
                self.assertEqual(st["radio_vis"], want, text)
            for text in ("pokaż wszystkie stacje", "wyłącz radio", "zmień stację",
                         "włącz szum fal", "włącz szum morza", "zagrajmy w kółko i krzyżyk",
                         "pokaż serduszko", "włącz minutnik na 5 minut",
                         "włącz coś na zmianę", "pokaż mi oczy"):
                self.assertFalse(self.v.handle(text, said.append), text)
            self.assertFalse(self.v.handle("włącz fale", said.append, radio_on=False))
            # colours (18 Oct: every station but a few kinds was orange)
            for text, want in (("zmień kolory", None), ("fioletowe efekty", "fioletowe"),
                               ("efekty na zielono", None), ("kolory losowo", "auto"),
                               ("ustaw neonowe kolory", "neonowe"),
                               ("kolorowe efekty", None)):
                before = self.v.colors()
                self.assertTrue(self.v.handle(text, said.append), text)
                if want:
                    self.assertEqual(st["radio_vis_col"], want, text)
                elif text == "zmień kolory":
                    self.assertNotEqual(st["radio_vis_col"], before, text)
            self.v.handle("pokaż złote iskry", said.append)
            self.assertEqual((st["radio_vis_col"], st["radio_vis"]), ("zlote", "iskry"))
            for text in ("zmień kolor lampki na zielony", "słodkich snów, kolorowych",
                         "jaki kolor ma niebo"):
                self.assertFalse(self.v.handle(text, said.append), text)
            self.assertFalse(self.v.handle("zmień kolory", said.append, radio_on=False))
            st["radio_vis_col"] = "auto"
            self.v._style[:] = [None, 0.0]
            self.v.set_kind("jazz")
            self.assertEqual(self.v.colors(), "fioletowe")
            self.v.new_song("Next")
            self.assertNotEqual(self.v.colors(), "fioletowe")     # another with each song
        finally:
            settings.get = get
            settings.put = put

class SettingsPageTest(unittest.TestCase):
    """The settings page: values cycle, the costs add up, the factory reset
    moves (never deletes) memories and people, and asks first."""

    def setUp(self):
        import settings_page
        self.sp = settings_page
        for k in ("language", "captions", "status_bar", "draw_fps", "tts_speed"):
            settings._load()
            settings._data.pop(k, None)
        settings_page._cache.clear()

    def test_values_cycle(self):
        sp = self.sp
        self.assertEqual(sp.language(), "pl")
        self.assertEqual(sp.change("language"), "Język: English")
        self.assertEqual(settings.get("language"), "en")
        sp.change("language")
        self.assertEqual(settings.get("language"), "pl")
        self.assertEqual(sp.change("status_bar"), "Wyłączone")       # on by default
        self.assertIs(settings.get("status_bar"), False)
        self.assertEqual(sp.change("captions"), "Włączone")          # off by default
        fps = [sp.draw_fps()]
        for _ in range(3):
            sp.change("draw_fps")
            fps.append(sp.draw_fps())
        self.assertEqual(fps, [45, 60, 30, 45])
        settings.put("tts_speed", 1.4)
        sp.change("tts_speed")
        self.assertEqual(settings.get("tts_speed"), 1.0)

    def test_rows_of_every_tab(self):
        for tab in range(4):
            with mock.patch.object(self.sp, "cost_rows", return_value=[]):
                rows = self.sp.rows(tab)
            for r in rows:
                self.assertIn(r["kind"], ("toggle", "cycle", "info", "danger"))
                self.assertTrue(r["label"])

    def test_cost(self):
        from config import API_COST_USD, USD_PLN
        self.assertAlmostEqual(self.sp.cost({"chat": 100, "ping": 5}),
                               100 * API_COST_USD["chat"] * USD_PLN)
        self.assertEqual(self.sp._zl(1.234), "≈ 1,23 zł")

    def test_factory_reset_moves_not_deletes(self):
        d = tempfile.mkdtemp(prefix="luna-reset-")
        photos = os.path.join(d, "photos")
        os.makedirs(os.path.join(d, "faces"))
        os.makedirs(photos)
        for name in ("memory.json", "people.json", "lists.json"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("{}")
        with open(os.path.join(d, "faces", "Maja.jpg"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(photos, "people.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        dest = self.sp.factory_reset(d, photos)
        for name in ("memory.json", "people.json", "faces/Maja.jpg", "photos-people.json"):
            self.assertTrue(os.path.exists(os.path.join(dest, name)), name)
        self.assertFalse(os.path.exists(os.path.join(d, "memory.json")))
        self.assertFalse(os.path.exists(os.path.join(photos, "people.json")))
        self.assertTrue(os.path.exists(os.path.join(d, "lists.json")))   # lists stay
        shutil.rmtree(d)

    def test_reset_asks_first_and_not_a_child(self):
        import ui_screens
        sp = self.sp
        sp.show(4)
        with state.lock:
            data = state.overlay[2]
        L = ui_screens._settings_layout(800, 480, len(sp.rows(4)))
        reset = L["rows"][2].center
        with mock.patch.object(sp, "_reset_and_restart") as go, \
                mock.patch.object(sp, "_child_here", return_value=True):
            sp.tap(*reset, 800, 480)
            self.assertTrue(data.get("confirm"))
            self.assertFalse(go.called)
            sp.tap(*L["yes"].center, 800, 480)          # a child: no
            self.assertFalse(go.called)
            self.assertEqual(data["toast"][0], "Poproś dorosłego")
        with mock.patch.object(sp, "_reset_and_restart") as go, \
                mock.patch.object(sp, "_child_here", return_value=False):
            sp.tap(*reset, 800, 480)
            sp.tap(*L["no"].center, 800, 480)           # Anuluj
            sp.tap(*reset, 800, 480)
            sp.tap(*L["yes"].center, 800, 480)
            time.sleep(0.05)
            self.assertEqual(go.call_count, 1)
        with state.lock:
            state.overlay = None


class DevicesTest(unittest.TestCase):
    """Speaker / mic / camera: LUNA_SPEAKER=pebble,jack falls back to the jack,
    the settings page's pick wins and an unplugged pick falls back to .env."""

    SINKS = [{"node.name": "alsa_output.platform-fe00b840.mailbox.stereo-fallback",
              "node.description": "Built-in Audio Stereo"},
             {"node.name": "alsa_output.usb-Creative_Technology_Ltd_Pebble_V3-01.analog-stereo",
              "node.description": "Pebble V3 Analog Stereo"}]

    def setUp(self):
        import devices
        self.d = devices
        for k in ("speaker", "mic", "camera"):
            settings._load()
            settings._data.pop(k, None)
        devices._lists.clear()

    def test_speaker_chain_falls_back(self):
        d = self.d
        jack, pebble = self.SINKS[0]["node.name"], self.SINKS[1]["node.name"]
        self.assertEqual(d.resolve_sink(["pebble", "jack"], self.SINKS), pebble)
        self.assertEqual(d.resolve_sink(["pebble", "jack"], self.SINKS[:1]), jack)
        self.assertIsNone(d.resolve_sink(["pebble"], self.SINKS[:1]))     # default output
        self.assertIsNone(d.resolve_sink(["default", "jack"], self.SINKS))
        with mock.patch.object(d, "AUDIO_OUTPUT_DEVICE", "pebble, jack"):
            self.assertEqual(d.speaker_chain(), ["pebble", "jack"])
            settings.put("speaker", jack)
            self.assertEqual(d.speaker_chain(), [jack, "pebble", "jack"])
            self.assertEqual(d.resolve_sink(sinks=self.SINKS), jack)
        settings.put("speaker", None)

    def test_labels(self):
        self.assertEqual(self.d.sink_label(self.SINKS[0]), "Gniazdo słuchawkowe")
        self.assertEqual(self.d.sink_label(self.SINKS[1]), "Pebble V3")

    def test_pick_cycles_through_what_is_plugged_in(self):
        d = self.d
        found = [("a", "Kamera A"), ("b", "Kamera B")]
        with mock.patch.object(d, "cameras", return_value=found):
            self.assertEqual(d.pick_next("camera"), "Kamera A")
            self.assertEqual(settings.get("camera"), "a")
            self.assertEqual(d.pick_next("camera"), "Kamera B")
            self.assertEqual(d.pick_next("camera"), d.AUTO)
            self.assertIsNone(settings.get("camera"))
        settings.put("camera", "gone")                      # unplugged: still listed
        with mock.patch.object(d, "cameras", return_value=found):
            self.assertIn(("gone", "gone (odłączony)"), d.options("camera"))
        settings.put("camera", None)

    def test_mic_specs(self):
        d = self.d
        with mock.patch.object(d, "AUDIO_INPUT_DEVICE", "C270"):
            self.assertEqual(d.mic_specs(), ["C270"])
            settings.put("mic", "Pebble V3")
            self.assertEqual(d.mic_specs(), ["Pebble V3", "C270"])
        settings.put("mic", None)


class ThemesTest(unittest.TestCase):
    """Themes (settings → Ekran → Motyw): eyes, voice, character, wake word;
    "Luna" still wakes every one of them."""

    def tearDown(self):
        import themes
        themes.set_theme("luna")

    def test_cycle_on_the_settings_page(self):
        import themes
        import settings_page as sp
        sp._cache.clear()
        with mock.patch.object(sp, "_introduce"):
            self.assertEqual(sp.change("theme"), "Motyw: Ice")
            self.assertEqual(themes.current(), "ice")
            self.assertEqual(sp.rows(1)[0]["value"], "Ice")
            self.assertEqual(sp.change("theme"), "Motyw: HAL 9000")
            self.assertEqual(sp.change("theme"), "Motyw: Luna")
        settings.put("theme", "nonsense")
        themes.set_theme(settings.get("theme"))
        self.assertEqual(themes.current(), "luna")

    def test_every_theme_is_complete(self):
        import themes
        import face_spec
        import gl_face
        for key, th in themes.THEMES.items():
            self.assertTrue(th["label"] and th["sub"] and th["hello"], key)
            if key == "luna":
                continue
            for k in ("wake", "voice", "tts", "persona", "eyes", "name"):
                self.assertIn(k, th, key)
            spec = gl_face.theme_spec(face_spec.spec("happy"), th)
            self.assertEqual(set(spec), set(face_spec.spec("happy")), key)   # no new keys
            self.assertTrue(all(0.0 <= v <= 1.0 for v in spec["lid_top"]), key)

    def test_wake_words_follow_the_theme(self):
        import themes
        import speech_to_text as s
        themes.set_theme("hal")
        self.assertIsNotNone(s._find_wake_word(["hal", "która", "godzina"]))
        self.assertIsNotNone(s._find_wake_word(["luna", "która", "godzina"]))   # always
        self.assertEqual(s._strip_wake_from_cloud("HAL, otwórz drzwi."), "Otwórz drzwi.")
        self.assertIn("HAL", s.stt_prompt())
        themes.set_theme("luna")
        self.assertIsNone(s._find_wake_word(["hal", "która", "godzina"]))
        self.assertFalse(s._cloud_has_wake("HAL, otwórz drzwi."))

    def test_voice_and_grammar(self):
        import themes
        import brain
        import openai_tts
        themes.set_theme("hal")
        self.assertEqual(openai_tts.voice_kwargs("cheerful")["voice"], "onyx")
        self.assertNotIn("cheerful", openai_tts.voice_kwargs("cheerful")["instructions"])
        self.assertEqual(openai_tts.deep_hz(), 0)              # a man's voice is not a drift
        self.assertIn("zrobiłem", brain._feminize("Już to zrobiłem."))
        self.assertIn("HAL 9000", themes.persona_line())
        themes.set_theme("luna")
        self.assertIn("zrobiłam", brain._feminize("Już to zrobiłem."))
        self.assertEqual(themes.persona_line(), "")
        self.assertGreater(openai_tts.deep_hz(), 0)

    def test_voice_fx(self):
        import numpy as np
        import themes
        import tts_fx
        self.assertEqual(themes.THEMES["hal"]["fx"], "robot")
        self.assertEqual(themes.THEMES["ice"]["fx"], "deep")
        t = np.arange(24000) / 24000
        tone = (8000 * np.sin(2 * np.pi * 200 * t)).astype(np.int16).tobytes()

        def run(name):                                 # in uneven chunks, like the stream
            ch, out = tts_fx.Chain(name), b""
            for i in range(0, len(tone), 4094):
                out += ch.process(tone[i:i + 4094])
            out += ch.flush()
            return np.frombuffer(out, np.int16).astype(np.float32)
        self.assertEqual(tts_fx.Chain(None).process(tone), tone)   # Luna: untouched
        robot = run("robot")
        self.assertAlmostEqual(robot.size / 24000, 1 / 1.2 + 0.15, delta=0.05)   # 1.2× faster + the room
        # a voice gliding ±6 semitones → one flat buzz at robot_hz
        f = 110 * 2 ** (np.sin(2 * np.pi * 0.75 * t) * 6 / 12)
        saw = (8000 * (2 * (np.cumsum(f) / 24000 % 1) - 1)).astype(np.int16).tobytes()
        keys = ("robot_hz", "tempo")
        tts_fx.PRESETS["_test"] = {k: v for k, v in tts_fx.PRESETS["robot"].items() if k in keys}
        try:
            ch = tts_fx.Chain("_test")
            out = np.frombuffer(ch.process(saw) + ch.flush(), np.int16).astype(np.float32)
        finally:
            del tts_fx.PRESETS["_test"]
        hz = tts_fx.PRESETS["robot"]["robot_hz"]
        for k in range(2400, out.size - 4800, 2400):
            seg = out[k:k + 2400] - out[k:k + 2400].mean()
            ac = np.correlate(seg, seg, "full")[seg.size - 1:] / np.arange(seg.size, 0, -1)
            lag, period = 60 + np.argmax(ac[60:450]), 24000 / hz
            self.assertLessEqual(min(abs(lag - period), abs(lag - period / 2)), 2)
        self.assertGreater(np.abs(robot).max(), 3000)  # still loud, never clipped hard
        self.assertLess(np.abs(robot).max(), 30001)
        deep = run("deep")
        k = tts_fx.PRESETS["deep"]["pitch"]
        self.assertAlmostEqual(deep.size / 24000, 1 / 1.2, delta=0.06)  # Ice 1.2× faster
        zc = np.sum(np.diff(deep[1000:-1000] > 0) != 0) / 2 / ((deep.size - 2000) / 24000)
        self.assertAlmostEqual(zc, 200 / k, delta=3)  # the pitch is lower
        self.assertEqual(b"".join(tts_fx.wrap([tone[:5000], tone[5000:]], None)), tone)


# Off the Pi (Windows) the hardware / SDK modules are missing: those tests
# skip instead of erroring, so the local quick run shows real failures only.
_PI_ONLY = {"cv2", "pygame", "sounddevice", "openai", "vosk", "fcntl"}


def _skip_missing(test):
    method = getattr(test, test._testMethodName)

    def run(*a, **k):
        try:
            return method(*a, **k)
        except ModuleNotFoundError as e:
            if e.name in _PI_ONLY:
                raise unittest.SkipTest(f"no {e.name} here")
            raise
    setattr(test, test._testMethodName, run)


class ScheduleTest(unittest.TestCase):
    """The week's plan (schedule.py): reading an entry, the reminders."""

    def setUp(self):
        import faces
        import schedule
        self.s = schedule
        schedule.PATH = os.path.join(TMP, "schedule.json")
        if os.path.exists(schedule.PATH):
            os.remove(schedule.PATH)
        schedule._mem.update(mtime=None, data=None)
        schedule._expect.update(until=0.0, draft=None, who=None, day=None)
        self.p = [mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]),
                  mock.patch.object(faces, "notes", lambda: {"Andrzej": "tata Mai"}),
                  mock.patch.object(faces, "vocatives",
                                    lambda: {"Maja": "Maju", "Andrzej": "Andrzeju"})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_parse(self):
        P = self.s.parse
        self.assertEqual(P("Maja angielski od poniedziałku do piątku o 17"),
                         {"who": "Maja", "title": "angielski", "days": [0, 1, 2, 3, 4],
                          "at": "17:00", "end": ""})
        self.assertEqual(P("Mai lekcje pianina w środę od 17 do 18")["end"], "18:00")
        e = P("Emilka joga we wtorki i czwartki o siódmej wieczorem")
        self.assertEqual((e["days"], e["at"]), ([1, 3], "19:00"))
        self.assertEqual(P("wszyscy obiad u babci w niedzielę o 13")["who"], "")
        self.assertEqual(P("taty trening w weekendy o wpół do ósmej wieczorem")["who"], "Andrzej")
        self.assertEqual(P("Andrzej siłownia w poniedziałki o 6:30 rano")["at"], "06:30")
        self.assertIsNone(P("Maja angielski"))                  # no day, no time
        self.assertEqual(P("Maja angielski", partial=True)["days"], None)

    def test_days_said(self):
        self.assertEqual(self.s.days_said([0, 1, 2, 3, 4]), "od poniedziałku do piątku")
        self.assertEqual(self.s.days_said([1, 3]), "we wtorek i w czwartek")
        self.assertEqual(self.s.days_said([5, 6]), "w weekendy")

    def _at(self, wd_hm):
        # 19 Oct 2026 is a Monday
        d, h, m = wd_hm
        return datetime.datetime(2026, 10, 19 + d, h, m).timestamp()

    def test_reminder_to_its_owner_when_seen(self):
        self.s.add("Maja", "angielski", [0, 1, 2, 3, 4], "17:00")
        said = []
        self.assertEqual(self.s.tick(self._at((0, 16, 40)), "Maja", True, True, False,
                                     said.append), 0)          # too early
        self.assertEqual(self.s.tick(self._at((0, 16, 46)), "Andrzej", True, True, False,
                                     said.append), 0)          # not her
        self.assertEqual(self.s.tick(self._at((0, 16, 46)), "Maja", True, True, False,
                                     said.append), 1)
        self.assertEqual(said, ["Maju, za 14 minut masz angielski."])
        self.assertEqual(self.s.tick(self._at((0, 16, 50)), "Maja", True, True, False,
                                     said.append), 0)          # once a day
        self.assertEqual(self.s.tick(self._at((1, 16, 50)), "Maja", True, True, False,
                                     said.append), 1)          # and again on Tuesday
        self.assertEqual(self.s.tick(self._at((5, 16, 50)), "Maja", True, True, False,
                                     said.append), 0)          # not on Saturday

    def test_reminder_to_someone_else_and_always(self):
        e = self.s.add("Maja", "angielski", [0], "17:00")
        self.s.update(e["id"], remind={"to": "Andrzej", "always": True, "before": 30})
        said = []
        with mock.patch.object(self.s, "_say", lambda t: None):
            n = self.s.tick(self._at((0, 16, 30)), "Maja", True, True, False, said.append)
        self.assertEqual(n, 1)               # nobody right: said aloud anyway (always)
        self.assertEqual(said, ["Andrzeju, przypominam: Maja za 30 minut ma angielski."])

    def test_reminder_dropped_when_nobody_came(self):
        self.s.add("", "obiad", [0], "13:00")
        said = []
        self.assertEqual(self.s.tick(self._at((0, 12, 50)), None, False, True, False,
                                     said.append), 0)
        self.assertEqual(self.s.tick(self._at((0, 12, 55)), None, True, True, False,
                                     said.append), 1)          # anyone in view, for the house
        self.assertEqual(said, ["Przypominam: za 5 minut obiad."])
        self.s.add("Maja", "basen", [0], "15:00")
        self.s.tick(self._at((0, 15, 10)), None, False, True, False, said.append)
        self.assertEqual(self.s.due(self._at((0, 15, 5))), [])   # missed: gone for the day

    def test_add_after_plus_asks_for_what_is_missing(self):
        said = []
        self.s.expect(who=None, day=None)
        self.assertTrue(self.s.handle("Maja angielski", said.append))
        self.assertEqual(said[-1], "W jakie dni?")
        self.assertTrue(self.s.handle("od poniedziałku do piątku", said.append))
        self.assertEqual(said[-1], "O której godzinie?")
        self.assertTrue(self.s.handle("o piątej", said.append))
        self.assertIn("Maja ma angielski od poniedziałku do piątku o 17:00", said[-1])
        self.assertEqual(len(self.s.events()), 1)
        self.s.expect()
        self.assertFalse(self.s.handle("włącz radio Trójkę proszę bardzo", said.append))
        self.assertFalse(self.s.expecting())                    # something else: let go

    def test_voice_add_and_remove(self):
        said = []
        self.assertTrue(self.s.handle("Dodaj do planu: Maja, basen w czwartki o 16:30",
                                      said.append))
        self.assertEqual(self.s.events()[0]["days"], [3])
        self.s.add("Emilka", "basen", [5], "10:00")
        self.assertTrue(self.s.handle("Usuń z planu basen", said.append))
        self.assertIn("Pasuje kilka", said[-1])
        self.assertTrue(self.s.handle("Usuń z planu basen Mai", said.append))
        self.assertEqual([e["who"] for e in self.s.events()], ["Emilka"])
        self.assertFalse(self.s.handle("Pokaż plan dnia", said.append))
        self.assertTrue(self.s.handle("dodaj do planu: Babcia, wizyta, w sobotę o 15",
                                      said.append))
        self.assertEqual((self.s.events()[-1]["who"], self.s.events()[-1]["title"]),
                         ("Babcia", "wizyta"))

    def test_prompt_line(self):
        self.assertEqual(self.s.prompt_line(), "")
        self.s.add("Maja", "angielski", [0, 1, 2, 3, 4], "17:00", "18:00")
        self.assertIn("Maja: angielski od poniedziałku do piątku 17:00–18:00",
                      self.s.prompt_line())


class TouchPageTest(unittest.TestCase):
    """Fast taps on a page are taps — 19 Oct: the plan's days went dead (poking)."""

    def _kinds(self, page):
        import struct
        import threading
        import touch_module as tm
        path = os.path.join(TMP, "touch-events")
        with open(path, "wb") as f:
            for _ in range(4):
                for et, code, val in ((tm.EV_ABS, tm.ABS_X, 400), (tm.EV_ABS, tm.ABS_Y, 100),
                                      (tm.EV_KEY, tm.BTN_TOUCH, 1), (tm.EV_KEY, tm.BTN_TOUCH, 0)):
                    f.write(struct.pack(tm._FMT, 0, 0, et, code, val))
        got = []
        with state.lock:
            state.overlay = ("schedule", time.time() + 30, {}) if page else None
            state.speaking = False
        with mock.patch.object(tm, "_abs_range", lambda fd, axis: (0, 800)), \
                mock.patch.object(tm, "_publish", lambda kind, *a, **k: got.append(kind)):
            threading.Thread(target=tm._reader_loop, args=(path,), daemon=True).start()
            time.sleep(0.6)
        with state.lock:
            state.overlay = None
        return got

    def test_fast_taps(self):
        self.assertEqual(self._kinds(page=True), ["tap"] * 4)
        self.assertIn("multi", self._kinds(page=False))       # on her face: still poking


def load_tests(loader, tests, pattern):
    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                _skip_missing(t)
    walk(tests)
    return tests


if __name__ == "__main__":
    unittest.main()
