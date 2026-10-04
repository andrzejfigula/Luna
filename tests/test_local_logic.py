"""The parts of Luna that are pure logic — no Pi, no network, no audio."""

import datetime
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import games
import memory
import settings
import timers
from shared_state import state

TMP = tempfile.mkdtemp(prefix="luna-tests-")
timers.TIMERS_PATH = os.path.join(TMP, "timers.json")
memory.MEMORY_PATH = os.path.join(TMP, "memory.json")
settings.SETTINGS_PATH = os.path.join(TMP, "settings.json")


class TimersTest(unittest.TestCase):

    def setUp(self):
        timers._timers.clear()

    def test_timer_reminder_and_cancel_by_label(self):
        timers.apply([{"type": "timer", "seconds": 600, "at": "", "label": "makaron"}])
        timers.apply([{"type": "reminder", "seconds": 0, "at": "23:59", "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron", "piekarnik"])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": "piekarnik"}])
        self.assertEqual([t["label"] for t in timers._timers], ["makaron"])

    def test_cancel_without_label_clears_all(self):
        for s in (60, 120):
            timers.apply([{"type": "timer", "seconds": s, "at": "", "label": ""}])
        timers.apply([{"type": "cancel", "seconds": 0, "at": "", "label": ""}])
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

    def test_forget(self):
        memory._save({"facts": ["Ma kota."], "episodes": [], "threads": [], "_wiped_at": 0})
        self.assertFalse(memory.check_forget("Zapomnij o tym, nieważne"))
        self.assertTrue(memory.check_forget("Luna, zapomnij wszystko"))
        self.assertEqual(memory._load()["facts"], [])


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

    def test_speech_speed(self):
        settings.put("tts_speed", 1.0)
        self.assertTrue(self.handle("Mów wolniej"))
        self.assertAlmostEqual(settings.get("tts_speed"), 0.9)
        self.assertTrue(self.handle("mów normalnie"))
        self.assertAlmostEqual(settings.get("tts_speed"), 1.0)


if __name__ == "__main__":
    unittest.main()
