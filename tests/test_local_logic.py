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

    def test_timer_reminder_and_cancel_by_label(self):
        timers.apply([{"type": "timer", "seconds": 60, "at": "", "label": "makaron"}])   # sooner than 23:59 even at 23:49
        timers.apply([{"type": "reminder", "seconds": 0, "at": "23:59", "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron", "piekarnik"])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron"])

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

    def test_radio_genres(self):
        import radio
        said = []
        played = []
        old = radio.play
        radio.play = lambda name, url, **k: played.append(name)
        try:
            self.assertTrue(radio.handle("Włącz radio z jakąś spokojną muzyką", said.append))
            self.assertTrue(radio.handle("Włącz radijko", said.append))
        finally:
            radio.play = old
        self.assertEqual(played[0], "Dwójka")

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

    def test_say_duration(self):
        self.assertEqual([timers.say_duration(s) for s in (60, 300, 120, 1800, 3600, 5400, 45)],
                         ["minutę", "5 minut", "2 minuty", "30 minut", "godzinę",
                          "półtorej godziny", "45 sekund"])

    def test_weekly_monthly_yearly(self):
        fri = datetime.datetime(2026, 10, 9, 18, 0).timestamp()
        nxt = datetime.datetime.fromtimestamp(timers._next_matching(fri, "weekly"))
        self.assertEqual((nxt.month, nxt.day, nxt.hour), (10, 16, 18))
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

    def test_where_is_thing(self):
        memory._save({"facts": ["Andrzej lubi żarty.", "Klucze są w szufladzie w kuchni.",
                                "Andrzej mówi: „mój paszport leży w szafie”."],
                      "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertEqual(memory.where_is_thing("Gdzie są klucze?"),
                         "Zapisałam: Klucze są w szufladzie w kuchni.")
        self.assertEqual(memory.where_is_thing("Gdzie jest mój paszport?"),
                         "Zapisałam: mój paszport leży w szafie.")
        self.assertIsNone(memory.where_is_thing("Gdzie jest Polska?"))
        self.assertIsNone(memory.where_is_thing("Gdzie są żarty?"))     # no place in it
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
        self.assertTrue(echo.is_echo("pomogła z przepisem?", last))       # the tail
        self.assertTrue(echo.is_echo("z przepisem", last))                # no "?" needed
        self.assertFalse(echo.is_echo("Tak, poproszę przepis", last))
        self.assertFalse(echo.is_echo("", last))


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
                      lists.restore("cofnij skreślenie", now=time.time() + 4000))

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
        quiz.answer("koniec", say, lambda n: None)

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
        self.assertTrue(s.call_pause(t + 20 + 599))
        self.assertFalse(s.call_pause(t + 20 + 601))
        s._call_until = 0.0
        s._en_heard.clear()

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
        finally:
            brain._TZ = old

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
            self.assertIn("Nie wiem", birthdays.nameday_answer("Kiedy Maja ma imieniny?"))
            self.assertEqual(birthdays.set_nameday_from("Maja ma imieniny 3 maja"),
                             ("Maja", "05-03"))
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
        self.assertIn("Andrzej (3 razy)", line)
        self.assertIn("Maja (raz)", line)
        self.assertIn("kind to you raz", line)
        self.assertIn("rude to you raz", line)
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
        settings.put("radio_gain", radio.RADIO_GAIN)

    def test_song_title(self):
        import radio
        said = []
        with mock.patch.object(radio, "playing", lambda: "Radio 357"), \
                mock.patch.object(radio, "_player", {"title": "Beck - In the Night"}):
            self.assertTrue(radio.handle("Co teraz gra?", said.append))
        self.assertEqual(said[-1], "Teraz gra: Beck - In the Night.")


if __name__ == "__main__":
    unittest.main()
