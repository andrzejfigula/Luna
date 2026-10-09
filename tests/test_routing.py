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
    "Czy możesz rzucić kostką?": "fun",
    "Czy możesz nastawić minutnik na 10 minut?": "timer",
    "Możesz mi przypomnieć za 20 minut o praniu?": "timer",
    "Czy możesz włączyć szum deszczu?": "ambience",
    "Możesz włączyć lampkę?": "fun",
    "Możesz zrobić mi zdjęcie?": "screen",
    "Czy możesz obudzić mnie o 6:30?": "timer",
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
    "Ile zostało do siedemnastej?": "calc",
    "Ile czasu do 17:30?": "calc",
    "Przepytaj mnie z tabliczki mnożenia": "quiz",
    "Pobawmy się w rachunki": "quiz",
    "Zapamiętaj, że klucze są w szufladzie": "remember",
    "Luna, zapamiętaj sobie że mama ma urodziny 12 maja": "remember",
    "Jak się pisze żółw?": "spell",
    "Przeliteruj chrząszcz": "spell",
    "Zagrajmy w zgadywankę": "quiz",
    "Przepytaj mnie ze słówek angielskich": "quiz",
    "Zadaj mi zagadkę": "quiz",
    "Pobawmy się w zagadki": "quiz",
    "Zagadka!": "quiz",
    "Pobawmy się w zegar": "quiz",
    "Naucz mnie zegara": "quiz",
    "Przepytaj mnie z zadań z treścią": "quiz",
    "Quiz ze stolic": "quiz",
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
    "Za wolno mówisz": "speed",
    "Mówisz za szybko": "speed",
    "Za cicho": "volume",
    "Nie słychać cię": "volume",
    "Dlaczego tak krzyczysz?": "volume",
    "Nie krzycz tak": "volume",
    "Czemu tak szepczesz?": "volume",
    "Przywróć listę zakupów": "lists",
    "Ile zostało na minutniku?": "asked",
    "Ile zostało do końca minutnika?": "asked",
    "Ile mam gwiazdek?": "asked",
    "Co mam na liście?": "asked",
    "Co mam na liście zakupów?": "asked",
    "Jakie to radio?": "asked",
    "Co o mnie wiesz?": "asked",
    "Kto dziś zmywa: Maja, tata czy mama?": "asked",
    "Wylosuj liczbę od 1 do 6": "asked",
    "Która godzina w Tokio?": "asked",
    "Jaki dzień tygodnia będzie 24 grudnia?": "calc",
    "Obudź mnie o 6:30": "timer",
    "Nastaw minutnik na 10 minut na makaron": "timer",
    "Przypomnij mi za 20 minut o praniu": "timer",
    "Obudź mnie radiem o siódmej": "radio",     # the radio mode, and the alarm locally
    "Budź mnie radiem jutro o 6:30": "radio",
    "Budzik na wpół do ósmej w dni robocze": "timer",
    "Pokaż plan dnia": "screen",
    "Jaki jest plan na dziś?": "screen",
    "Zagrajmy w 20 pytań": "twenty",
    "Zgadnij, o jakim zwierzęciu myślę": "twenty",
    "Gotujemy naleśniki": "cooking",
    "Przepis na sernik krok po kroku": "cooking",
    "Luna, nie słuchaj": "mic",
    "Przestań słuchać na 30 minut": "mic",
    "Wyłącz kamerę": "camera",
    "Czy możesz wyłączyć kamerę na 20 minut?": "camera",
    "Włącz kamerę": "camera",
    "Mów do mnie po angielsku": "language",
    "Mów po polsku": "language",
    "Włącz szum deszczu": "ambience",
    "Szum morza na 30 minut": "ambience",
    "Biały szum": "ambience",
    "Wyłącz szum": "ambience",
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
    "Powtórz mi tabliczkę mnożenia przez siedem",
    "Ile ścian ma kostka do gry?",
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
    "Dlaczego mówisz krócej niż wczoraj?",
    "Mów mi więcej o kotach i psach",
    "Jaki kolor ma niebo?",
    # ordinary conversation — no local command may grab these
    "Opowiedz mi o dinozaurach",
    "Co jadłaś na śniadanie?",
    "Lubisz muzykę?",
    "Jaka jest najwyższa góra świata?",
    "Czy możesz mi pomóc wybrać prezent dla mamy?",
    "Gdzie są moje klucze?",
    "Jak się czujesz?",
    "Co dzisiaj robimy?",
    "Kim jesteś?",
    "Ile masz lat?",
    "Czy umiesz śpiewać?",
    "Powiedz coś śmiesznego",
    "Dziękuję ci bardzo",
    "Jestem głodny",
    "Mam dzisiaj urodziny",
    "Co mamy dzisiaj?",
    "Ile mamy czasu do wyjścia?",
    "Co wiesz o dinozaurach?",
    "Kontynuuj, proszę, co mówiłaś o planetach",
    "Wybierz mi dobry film na wieczór",
    "Czy pizza czy makaron jest zdrowszy?",
    "Jutro mamy dyktando w szkole",
    "Maja lubi zagadki o zwierzętach",
    "Babcia ma w kuchni stary zegar",
    "Radio w samochodzie przestało działać",
    "Ile kosztuje nowe radio?",
    "Muszę kupić nowy budzik",
    "Pani w szkole mówi, że tabliczka mnożenia jest ważna",
    "Mój tata zawsze gotuje naleśniki w niedzielę",
    "Przypomniało mi się, że jutro jest wycieczka",
    "Wczoraj oglądaliśmy zdjęcia z wakacji",
    "Lampka w moim pokoju się zepsuła",
    "Koniec lekcji jest o czternastej",
    "Zrobiłam dziś pyszne ciasto",
    "Lubię słuchać radia w samochodzie",
    "Wczoraj w radiu grali fajną piosenkę",
    "Zrobiłam zdjęcie kotu sąsiadów",
    "Kupiłam nową lampkę do pokoju",
    "Minutnik w kuchni dzwoni za głośno",
    "Napisy w filmie były za małe",
    "Moja siostra ma urodziny w maju",
    "Mój budzik nie zadzwonił",
    "Wiadomość od babci przyszła wczoraj",
    "Plan na weekend jest taki, że jedziemy nad morze",
    "Lista rzeczy do spakowania jest długa",
    "W sobotę gotujemy naleśniki u babci",
    "Szum morza mnie uspokaja",
    "Babcia zawsze opowiadała mi bajki na dobranoc",
    "Pomodoro to fajna metoda nauki",
    "Ćwiczenia oddechowe robimy na WF-ie",
    "Lustro w łazience jest brudne",
    "W szkole robili quiz ze stolic",
    "Myjemy zęby dwa razy dziennie",
    "Moja koleżanka gra w kółko i krzyżyk na lekcjach",
    "Gotujemy obiad, bo zaraz przyjdą goście",
    "Gdzie jest pilot?",
    "Gdzie jest najbliższa apteka?",
    "Widziałaś mój telefon?",
    "Nie zapomnij, że jutro idziemy do dentysty",
    "Obudź mnie za 20 minut, dobrze?",
    "O której mam nastawić budzik?",
    "Wiesz co, miałam dziś ciężki dzień w pracy",
    "Przypomnij mi jutro o dentyście",
    "Co to jest fotosynteza?",
    "Maja dostała piątkę z matematyki",
    "Emilka pojechała do sklepu po mleko",
    "Zróbmy coś fajnego",
    "Pomóż mi przygotować prezentację",
    "Ile kalorii mają naleśniki?",
    "Dlaczego Maja nie słucha mamy?",
    "Czy jutro będzie padał deszcz?",
    "Dlaczego morze jest słone?",
    "To jest problem",
    "Jestem zmęczony",
    "Jestem Polakiem i mieszkam w Krakowie od lat",
    "Kim jestem?",
    "To bardzo zagadkowe",
    "Lubisz zagadki?",
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
        import cooking
        import twenty
        import radio
        import ambience
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
            (commands, "DONE_REPLIES", ["<BYE>"]),
            (commands, "GOODBYE_REPLIES_EN", ["<BYE>"]),
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
            (lists, "get", lambda name=None: ["mleko"] if name else {"zakupy": ["mleko"]}),
            (breathing, "run", lambda *a: self._mark("breath")),
            (screens, "PHOTOS_DIR", self._photos_dir()),
            (fun, "lamp_on", lambda *a: self._mark("fun")),
            (health, "status_rows", lambda: [("CPU", "ok")]),
            (fun, "high_five", lambda *a: self._mark("fun")),
            (fun, "roll", lambda *a: self._mark("fun")),
            (fun, "flip", lambda *a, **k: self._mark("fun")),
            (calc, "answer", self._calc(calc.answer)),
            (news, "context", lambda *a: self._mark("news") or "headlines"),
            (weather, "set_place", lambda t: self._mark("weather") or "Kraków"),
            (weather, "enabled", lambda: True),     # weather questions → the model
            (commands, "_learn_face", lambda *a: self._mark("face") or True),
            (weather, "forecast_for", self._forecast),
            (quiz, "start", lambda *a: self._mark("quiz")),
            (counting, "count", lambda *a, **k: self._mark("count")),
            (kids, "_brush", lambda *a: self._mark("kids")),
            (kids, "threading", self._sync_threads()),
            (kids, "start_routine", lambda *a: self._mark("kids")),
            (cooking, "start", lambda *a: self._mark("cooking")),
            (twenty, "start", lambda *a: self._mark("twenty")),
            (radio, "play", lambda *a, **k: self._mark("radio")),
            (ambience, "play", lambda *a, **k: self._mark("ambience")),
            (ambience, "stop", lambda: self._mark("ambience") or True),
            (radio, "stop", lambda: self._mark("radio") or True),
            (counting, "_watch", {"t0": None}),
            (memory, "add_fact", lambda f: self._mark("remember")),
            (commands, "_spell", lambda *a, **k: self._mark("spell")),
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
        fake_brain.last_reply = lambda: ""
        fake_brain.english_wanted = lambda: False
        fake_brain.set_english = lambda on, hours=2: self._mark("language")
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
        if any(t.startswith(("Nie mam teraz żadnego minutnika", "Zostało", "Zostały",
                             "Nie poznaję cię", "Losuję", "Wybieram", "W Tokio",
                             "24 grudnia wypada", "Jeszcze niczego o tobie", "Emilka",
                             "Nie wiem, kim jesteś", "Radio nie gra", "Gra ", "Na liście",
                             "Maja"))
               for t in said):
            self._mark("asked")
        if any(t.startswith(("Przywróciłam", "Nie mam czego przywrócić")) for t in said):
            self._mark("lists")
        if any(t.startswith("Stoper") for t in said):
            self._mark("count")
        if any(t.startswith("Dobrze, nie słucham") for t in said):
            self._mark("mic")
            with state.lock:
                state.mic_muted_until = 0.0
        if any(t.startswith(("Dobrze, wyłączam kamerę", "Kamera jest", "Dobrze, znowu widzę"))
               for t in said):
            self._mark("camera")
            with state.lock:
                state.camera_off_until = 0.0
        if not handled:
            return "model"
        return self.hit or "handled-but-unknown"

    # words from the local triggers, glued at random: no sentence may make a
    # handler throw (a crash there used to look like "she didn't hear me")
    _FUZZ = ("luna przypomnij mi obudź budzik o za na do w z że żeby nie co ile gdzie jest "
             "kiedy wiesz pamiętasz zapomnij wszystko tak przywróć listę zakupów usuń "
             "wiadomości wszystkie pokaż plan dnia zdjęcia minutnik 20 minut 17 6:30 "
             "wpół ósmej piątej Maja Mai Andrzej Emilka mnie mi imieniny urodziny maja "
             "3 12 kółko i krzyżyk koniec radio włącz wyłącz szum deszczu ciszej głośniej "
             "dobranoc pa jestem to zagadka dyktando quiz tabliczka gotujemy naleśniki "
             "dalej ? , . ! jutro codziennie godzin pół kwadrans dni robocze memory pary "
             "jeszcze raz rewanż ile lat ma zostało minutniku makaron Tokio Nowym Jorku "
             "wylosuj wybierz liczbę kto zmywa : czy albo na czas angielskiego "
             "za cicho wolno szybko głośno mówisz cię możesz mówić radijko spokojną muzyką").split()

    def test_random_sentences_never_crash(self):
        import random as _r
        import faces
        rng = _r.Random(1234)
        with mock.patch.object(faces, "nominative", lambda w: w.capitalize()):
            for _ in range(400):
                text = " ".join(rng.choice(self._FUZZ) for _ in range(rng.randint(1, 9)))
                with state.lock:
                    state.overlay = None
                    state.person = rng.choice((None, ("Maja", 0.9, 0), ("Andrzej", 0.9, 0)))
                try:
                    self.route(text)
                except Exception as e:                     # noqa: BLE001
                    self.fail(f"{text!r} → {type(e).__name__}: {e}")
        import tictac
        tictac.stop()
        with state.lock:
            state.person = None

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

    def test_questions_go_to_the_model_with_the_family_known(self):
        """The same with Andrzej, Emilka and Maja known by face — the
        person-aware commands (birthdays, notes, photos) must still leave
        ordinary sentences alone."""
        import faces
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]),                 mock.patch.object(faces, "nominative", lambda w: w):
            for text in MODEL:
                with self.subTest(text=text):
                    with state.lock:
                        state.sleep_mode = False
                    self.assertEqual(self.route(text), "model")

    def test_family_questions_answered_locally(self):
        """"Gdzie jest Emilka?" with the family known: answered here, before
        the question guard (it once sent these to the model)."""
        import faces
        with mock.patch.object(faces, "names", lambda: ["Andrzej", "Emilka", "Maja"]):
            for text in ("Gdzie jest Emilka?", "Widziałaś dziś Maję?",
                         "Czy była już Maja?"):
                with self.subTest(text=text):
                    self.assertEqual(self.route(text), "asked")
            self.assertEqual(self.route("Gdzie jest pilot?"), "model")

    def test_mute(self):
        self.assertEqual(self.route("Luna, cicho"), "mute")

    def test_doorbell_for_a_child(self):
        """A child at the door gets the fixed safe answer; a grown-up the model."""
        said = []
        with mock.patch.object(commands, "_child_here", lambda: True):
            self.assertTrue(commands.handle("Ktoś puka do drzwi, otworzyć?",
                                            lambda t, **k: said.append(t), lambda n, **k: True))
        self.assertIn("Nie otwieraj", said[-1])
        with mock.patch.object(commands, "_child_here", lambda: False):
            self.assertEqual(self.route("Ktoś dzwoni do drzwi"), "model")


if __name__ == "__main__":
    unittest.main()
