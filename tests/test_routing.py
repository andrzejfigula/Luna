"""Which utterances does Luna handle herself, and which go to the model?
The local commands must never swallow an ordinary question."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import commands
import games
import idle_engine
import memory
import screens
from shared_state import state

LOCAL = {
    "Ciszej": "volume",
    "Ustaw głośność na 30": "volume",
    "Mów wolniej": "speed",
    "Luna, mów trochę szybciej proszę": "speed",
    "Jeszcze trochę głośniej": "volume",
    "Dobranoc, Luna": "sleep",
    "Pa!": "bye",
    "Zrób mi zdjęcie": "screen",
    "Pokaż lustro": "screen",
    "Pokaż zegar": "screen",
    "Pokaż przypomnienia": "screen",
    "Pokaż listę zakupów": "screen",
    "Włącz tryb skupienia": "focus",
    "Pomodoro na 50 minut": "focus",
    "Luna, ćwiczenie oddechowe": "breath",
    "Pomóż mi się uspokoić": "breath",
    "Zagrajmy w kamień, papier, nożyce": "game",
}
MODEL = [
    "Co widzisz?",
    "Pokaż mi, co potrafisz",
    "Jaka jest teraz głośność?",
    "Czy w lustrze widać odbicie?",
    "Dlaczego w nocy jest ciszej?",
    "Zrób mi zdjęcie tego kubka i powiedz, co na nim jest napisane",
    "Na razie nie, dzięki",
    "Ile kosztuje kamień do zapalniczki?",
    "Dzień dobry!",
    "Dlaczego samoloty latają szybciej?",
    "Mów mi więcej o kotach",
    "Co to jest pomodoro?",
    "Jak działa tryb skupienia",
    "Czy ćwiczenie oddechowe pomaga na stres?",
    "Dopisz mleko do listy zakupów",
    "Co mam na liście?",
]


class RoutingTest(unittest.TestCase):

    def setUp(self):
        import breathing
        import lists
        import timers
        self.hit = None
        stubs = [
            (commands, "set_volume", lambda v: self._mark("volume") or v),
            (commands, "get_volume", lambda: 0.5),
            (commands.settings, "put", lambda k, v: self._mark("speed")),
            (commands, "go_to_sleep", lambda: self._mark("sleep")),
            (commands, "GOODBYE_REPLIES", ["<BYE>"]),
            (screens, "_take_photo", lambda *a: self._mark("screen")),
            (screens, "_show", lambda *a, **k: self._mark("screen")),
            (games, "play_match", lambda *a: self._mark("game")),
            (games, "_rematch_until", 0),
            (timers, "screen_lines", lambda: [("1:00", "test")]),
            (timers, "add", lambda *a, **k: self._mark("focus")),
            (timers, "remove", lambda *a, **k: None),
            (lists, "find", lambda text: "zakupy"),
            (lists, "get", lambda name=None: ["mleko"]),
            (breathing, "run", lambda *a: self._mark("breath")),
        ]
        # patched for this test only — other test modules see the real ones
        for obj, name, value in stubs:
            p = mock.patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _mark(self, what):
        if self.hit is None:
            self.hit = what

    def route(self, text):
        self.hit = None
        if idle_engine.check_mute(text):
            return "mute"
        said = []
        handled = commands.handle(text, lambda t, **k: said.append(t),
                                  lambda n, **k: True)
        if "<BYE>" in said:
            self._mark("bye")
        if not handled:
            return "model"
        return self.hit or "handled-but-unknown"

    def test_local_commands(self):
        for text, want in LOCAL.items():
            with self.subTest(text=text):
                with state.lock:
                    state.sleep_mode = False
                self.assertEqual(self.route(text), want)

    def test_questions_go_to_the_model(self):
        for text in MODEL:
            with self.subTest(text=text):
                with state.lock:
                    state.sleep_mode = False
                self.assertEqual(self.route(text), "model")

    def test_mute(self):
        self.assertEqual(self.route("Luna, cicho"), "mute")


if __name__ == "__main__":
    unittest.main()
