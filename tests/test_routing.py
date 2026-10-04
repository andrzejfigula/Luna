"""Which utterances does Luna handle herself, and which go to the model?
The local commands must never swallow an ordinary question."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
os.environ.setdefault("LUNA_DATA_DIR", tempfile.mkdtemp(prefix="luna-tests-"))  # never real data

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
    "No to dobranoc, idę już spać": "sleep",
    "Czy możesz pokazać zegar?": "screen",
    "Pa!": "bye",
    "Zrób mi zdjęcie": "screen",
    "Pokaż lustro": "screen",
    "Pokaż zegar": "screen",
    "Pokaż przypomnienia": "screen",
    "Pokaż listę zakupów": "screen",
    "Pokaż zdjęcia": "screen",
    "Pokaż status": "screen",
    "Włącz lampkę": "fun",
    "Przybij piątkę!": "fun",
    "Rzuć kostką": "fun",
    "Rzuć dwiema kostkami": "fun",
    "Orzeł czy reszka?": "fun",
    "Włącz tryb skupienia": "focus",
    "Minutnik na 10 minut": "timer",
    "Jeszcze 5 minut": "snooze",
    "Włącz napisy": "captions",
    "Luna, wyłącz napisy": "captions",
    "Opowiedz mi bajkę na dobranoc": "story",
    "Drzemka": "snooze",
    "Dodaj 5 minut do minutnika": "extend",
    "Tłumacz na angielski": "translate",
    "Czy możesz tłumaczyć na niemiecki?": "translate",
    "Pomodoro na 50 minut": "focus",
    "Luna, ćwiczenie oddechowe": "breath",
    "Powtórz": "repeat",
    "Co powiedziałaś?": "repeat",
    "Pomóż mi się uspokoić": "breath",
    "Zagrajmy w kamień, papier, nożyce": "game",
    "Ile to jest 17 razy 23?": "calc",
    "dwanaście razy siedem": "calc",
    "Ile dni do Wigilii?": "calc",
    "Ile jeszcze do weekendu?": "calc",
    "15% z 80": "calc",
    "Przepytaj mnie z tabliczki mnożenia": "quiz",
    "Pobawmy się w rachunki": "quiz",
    "Zapamiętaj, że klucze są w szufladzie": "remember",
    "Luna, zapamiętaj sobie że mama ma urodziny 12 maja": "remember",
    "Jak się pisze żółw?": "spell",
    "Przeliteruj chrząszcz": "spell",
    "Zagrajmy w zgadywankę": "quiz",
    "Przepytaj mnie ze słówek angielskich": "quiz",
    "Policz do dwudziestu": "count",
    "Odliczaj od dziesięciu": "count",
    "Włącz stoper": "count",
    "Myjemy zęby!": "kids",
    "Zacznij poranek": "kids",
    "Luna, włącz rutynę wieczorną": "kids",
    "Włącz radio": "radio",
    "Włącz Trójkę": "radio",
    "Puść radio Nowy Świat": "radio",
    "Wyłącz radio": "radio",
    "Wyłącz radio za 30 minut": "radio",
    "Włącz muzykę": "radio",
    "Budź mnie radiem": "radio",
    "Mów krócej": "length",
    "Luna, to jest Kasia": "face",
    "Jestem Andrzej": "face",
    "Poznaj Olę!": "face",
    "Zapamiętaj moją twarz, mam na imię Ola": "face",
    "Luna, pogoda dla Krakowa": "weather",
    "Mieszkam w Zielonej Górze": "weather",
    "Ustaw pogodę na Gdańsk": "weather",
    "Jaka jest pogoda w Berlinie?": "forecast",
    "Czy jutro pada w Zakopanem?": "forecast",
    "Jaka będzie jutro pogoda w Krakowie?": "forecast",
    "Jakie są wiadomości?": "news",
    "Luna, co słychać na świecie?": "news",
    "Co słychać w sporcie?": "news",
    "Przeczytaj mi trzy najważniejsze wiadomości na dzisiaj": "news",
    "Super, to na razie wszystko": "bye",
    "Dobra, dzięki, to by było na tyle": "bye",
    "To teraz idziemy spać": "sleep",
    "Pora spać, Luna": "sleep",
    "Lampka na niebiesko": "fun",
    "Zmień kolor lampki na zielony": "fun",
    "Włącz lampkę na 20 minut": "fun",
    "Luna, odpowiadaj dłużej": "length",
    "Normalne odpowiedzi proszę": "length",
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
    "Powtórz mi tabliczkę mnożenia przez siedem",
    "Ile ścian ma kostka do gry?",
    "Nastaw minutnik na 10 minut na makaron",
    "Jak się mówi kot po angielsku?",
    "Jak się zrestartować komputer?",
    "Dodaj mleko do listy zakupów",
    "Kto wymyślił lampkę nocną?",
    "Ile trwa jedno pomodoro",
    "Co jest mocniejsze, papier czy kamień?",
    "Co to jest lustro?",
    "Powiedz dobranoc mojej córce",
    "Co było wczoraj na dobranockę?",
    "Dlaczego bajki na dobranoc pomagają zasnąć?",
    "Czy zegar w kuchni się spieszy?",
    "Ile razy dziennie mam podlewać kwiatki?",
    "Ile kosztuje bilet do Krakowa?",
    "Ile dni do moich urodzin?",
    "Ile minut ma godzina?",
    "Dwa razy w tygodniu chodzę na basen",
    "Ile jest planet w układzie słonecznym?",
    "Przepytaj mnie z historii",
    "Czy pamiętasz, co mówiłem wczoraj?",
    "Zapamiętaj to",
    "Jak się pisze list motywacyjny do pracy w banku?",
    "Jak się pisze po angielsku pies?",
    "Policz do pięciu po angielsku",
    "Odlicz mi dni do wakacji",
    "Ile minęło lat od bitwy pod Grunwaldem?",
    "Jak dobrze myć zęby?",
    "Dlaczego trzeba myć zęby dwa razy dziennie?",
    "Zacznij od początku",
    "Jakie radio lubisz?",
    "Włącz mi coś śmiesznego",
    "Kto założył Radio ZET?",
    "Obudź mnie radiem o siódmej",
    "Budź mnie radiem jutro o 6:30",
    "Dlaczego mówisz krócej niż wczoraj?",
    "Mów mi więcej o kotach i psach",
    "Jaki kolor ma niebo?",
    "To jest problem",
    "Jestem zmęczony",
    "Jestem Polakiem i mieszkam w Krakowie od lat",
    "Kim jestem?",
    "Jaka jest pogoda?",
    "Jaka pogoda będzie na weekend?",
    "Mieszkam w Krakowie od dziesięciu lat i bardzo to lubię, a ty?",
    "Czy lubisz oglądać wiadomości?",
    "Co słychać u ciebie?",
    "Na razie nie",
    "Dlaczego dzieci idą spać wcześniej?",
    "O której pora spać dla sześciolatka?",
    "To wszystko co wiesz o kotach?",
    "Ile kosztuje lampka nocna?",
]


class RoutingTest(unittest.TestCase):

    def setUp(self):
        import breathing
        import calc
        import news
        import weather
        import quiz
        import counting
        import kids
        import radio
        import fun
        import health
        import lists
        import timers
        self.hit = None
        stubs = [
            (commands, "set_volume", lambda v: self._mark("volume") or v),
            (commands, "get_volume", lambda: 0.5),
            (commands.settings, "put", lambda k, v: self._mark(
                {"captions": "captions", "tts_speed": "speed",
                 "reply_length": "length"}.get(k, "radio"))),
            (commands, "go_to_sleep", lambda: self._mark("sleep")),
            (commands, "GOODBYE_REPLIES", ["<BYE>"]),
            (screens, "_take_photo", lambda *a: self._mark("screen")),
            (screens, "_show", lambda *a, **k: self._mark("screen")),
            (games, "play_match", lambda *a: self._mark("game")),
            (games, "_rematch_until", 0),
            (timers, "screen_lines", lambda: [("1:00", "test")]),
            (timers, "add", lambda *a, **k: self._mark("focus")),
            (timers, "remove", lambda *a, **k: None),
            (timers, "apply", lambda *a, **k: self._mark("timer")),
            (timers, "snooze", lambda s: self._mark("snooze") or True),
            (timers, "extend", lambda s: self._mark("extend") or True),
            (lists, "find", lambda text: "zakupy"),
            (lists, "get", lambda name=None: ["mleko"]),
            (breathing, "run", lambda *a: self._mark("breath")),
            (screens, "PHOTOS_DIR", self._photos_dir()),
            (fun, "lamp_on", lambda *a: self._mark("fun")),
            (health, "status_rows", lambda: [("CPU", "ok")]),
            (fun, "high_five", lambda *a: self._mark("fun")),
            (fun, "roll", lambda *a: self._mark("fun")),
            (fun, "flip", lambda *a: self._mark("fun")),
            (calc, "answer", self._calc(calc.answer)),
            (news, "context", lambda: self._mark("news") or "headlines"),
            (weather, "set_place", lambda t: self._mark("weather") or "Kraków"),
            (commands, "_learn_face", lambda *a: self._mark("face") or True),
            (weather, "forecast_for", self._forecast),
            (quiz, "start", lambda *a: self._mark("quiz")),
            (counting, "count", lambda *a: self._mark("count")),
            (kids, "_brush", lambda *a: self._mark("kids")),
            (kids, "threading", self._sync_threads()),
            (kids, "start_routine", lambda *a: self._mark("kids")),
            (radio, "play", lambda *a, **k: self._mark("radio")),
            (radio, "stop", lambda: self._mark("radio") or True),
            (counting, "_watch", {"t0": None}),
            (memory, "add_fact", lambda f: self._mark("remember")),
            (commands, "_spell", lambda *a: self._mark("spell")),
        ]
        fake_tts = type(sys)("text_to_speech")
        fake_tts.replay_last = lambda: self._mark("repeat") or True
        fake_tts.play_sound_async = lambda name: None
        # brain needs cv2 and the OpenAI SDK; routing only needs its
        # translator switch
        fake_brain = type(sys)("brain")
        fake_brain.set_translator = lambda lang: self._mark("translate")
        fake_brain.translator = lambda: None
        fake_brain.process = lambda text, **k: self._mark("story")
        stubs_dict = mock.patch.dict(sys.modules, {"text_to_speech": fake_tts,
                                                   "brain": fake_brain})
        stubs_dict.start()
        self.addCleanup(stubs_dict.stop)
        # patched for this test only — other test modules see the real ones
        for obj, name, value in stubs:
            p = mock.patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _photos_dir():
        import tempfile
        d = tempfile.mkdtemp(prefix="luna-photos-")
        open(os.path.join(d, "20260101-120000.jpg"), "wb").close()
        return d

    @staticmethod
    def _sync_threads():
        """threading for kids.py whose Thread runs at once (no race in tests)."""
        class Now:
            def __init__(self, target, args=(), **k):
                self.go = lambda: target(*args)

            def start(self):
                self.go()
        return type("SyncThreading", (), {"Thread": Now})

    def _forecast(self, text):
        # a real place after "w"/"na": the test's stand-in for the geocoder
        import re
        if re.search(r"\b(berlinie|zakopanem|krakowie)\b", text.lower()):
            self._mark("forecast")
            return "forecast"
        return None

    def _calc(self, real):
        def answer(text):
            said = real(text)
            if said:
                self._mark("calc")
            return said
        return answer

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
        if any(t.startswith("Stoper") for t in said):
            self._mark("count")
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
