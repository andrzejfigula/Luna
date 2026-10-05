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
        for text in ("Przypomnij mi jutro o dentyście",          # a day: the model
                     "Przypomnij mi o 17, żebym zadzwonił do mamy",   # to turn round
                     "Przypomnij mi codziennie o 8 o tabletkach",
                     "Przypomnij mi o praniu",                    # no time
                     "Przypomnij mi za 10 minut",                 # nothing to remind
                     "Przypomnij mi o 5 rzeczach na zakupy"):
            self.assertIsNone(r(text, at15), text)
        import clock
        self.assertEqual([clock.hour_locative(*t) for t in ((2, 0), (21, 0), (7, 5), (0, 0))],
                         ["drugiej", "dwudziestej pierwszej", "siódmej zero pięć", "północy"])

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
        self.assertEqual(memory.forget_fact("Maja ma chomika"),
                         "Maja ma chomika o imieniu Pestka.")
        self.assertEqual(memory.facts_about("Maja"), ["Mai ulubiony kolor to fiolet."])

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


class ListsTest(unittest.TestCase):

    def setUp(self):
        lists._lists = {}
        lists._undo = None

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
        self.assertIsNone(clock.answer("Która godzina w Tokio?"))

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
        self.assertIsNone(clock.answer("Która godzina jest teraz w Tokio?"))
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
        self.assertAlmostEqual(settings.get("tts_speed"), 1.0)


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
