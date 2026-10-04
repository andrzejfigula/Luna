"""
quiz.py — spoken games played one utterance at a time.

  maths    "Przepytaj mnie z tabliczki mnożenia"   → 7 × 8, 6 × 9 …
           "Quiz z dodawania" / "z odejmowania"     → up to 100 ("do dwudziestu": 20)
           "Pobawmy się w rachunki"                 → a mix of all three
  words    "Przepytaj mnie ze słówek angielskich"   → "Jak jest po angielsku: pies?"
  guess    "Zagrajmy w zgadywankę" / "zgadnij liczbę" → she thinks of a number
           from 1 to 100, you guess, she says "więcej" / "mniej"

Quizzes have five questions, each shown big on her screen and asked aloud;
a wrong answer gets one more try, then she tells the right one. "Nie wiem"
moves on, "koniec" stops. At the end: the score.

Lives between utterances: commands.handle passes each new utterance here
while a game is on (answer()), so the normal voice loop keeps running. An
utterance that is clearly not an answer ends the game and goes to the model
as usual.
"""

import difflib
import random
import re
import threading
import time

from shared_state import state

QUESTIONS   = 5
THINK_SECS  = 15          # extra listening time after each question
EXPIRE_SECS = 60          # no answer this long → the game is over

_TRIGGERS = ("przepytaj", "quiz", "kwiz", "sprawdź mnie", "sprawdz mnie", "pytaj mnie",
             "zadawaj mi", "zagadki z", "pobawmy się w", "pobawmy sie w",
             "zagrajmy w", "pytania z", "ćwiczyć", "cwiczyc", "poćwiczyć",
             "pocwiczyc", "poćwiczmy", "pocwiczmy", "test z")
_KINDS = [("mul", ("tabliczk", "mnożeni", "mnozeni", "mnożyć", "mnozyc")),
          ("add", ("dodawani", "dodawać", "dodawac")),
          ("sub", ("odejmowani", "odejmować", "odejmowac")),
          ("words", ("słówek", "słówka", "slowek", "slowka", "słówkach",
                     "angielskiego", "angielskich", "angielski", "english")),
          ("mix", ("rachunk", "matematyk", "matm", "liczeni", "liczyć", "liczyc",
                   "działa", "dziala"))]
_GUESS = ("zgadywank", "zgadnij liczb", "zgadywać liczb", "zgadywac liczb",
          "zgadywanie liczb", "pomyśl liczbę", "pomysl liczbe", "pomyśl sobie liczbę",
          "wymyśl liczbę", "wymysl liczbe", "guess the number", "guess a number")
_STOP = ("koniec", "stop", "wystarczy", "nie chcę", "nie chce", "przestań",
         "przestan", "dość", "dosc", "kończymy", "konczymy")
_DONT_KNOW = ("nie wiem", "poddaję się", "poddaje sie", "pomiń", "pomin", "następne",
              "nastepne", "dalej", "nie mam pojęcia", "nie mam pojecia", "i don't know")
_PRAISE = ["Brawo!", "Dobrze!", "Super!", "Tak jest!", "Świetnie!", "Zgadza się!",
           "Bingo!"]
_SYM = {"mul": "×", "add": "+", "sub": "−"}
_WORD = {"mul": "razy", "add": "plus", "sub": "minus"}

# Polish → English (alternatives accepted). Everyday words a child learns first.
WORDS = [
    ("pies", ["dog"]), ("kot", ["cat"]), ("koń", ["horse"]), ("krowa", ["cow"]),
    ("ptak", ["bird"]), ("ryba", ["fish"]), ("mysz", ["mouse"]), ("królik", ["rabbit", "bunny"]),
    ("słoń", ["elephant"]), ("małpa", ["monkey"]), ("lew", ["lion"]), ("niedźwiedź", ["bear"]),
    ("czerwony", ["red"]), ("niebieski", ["blue"]), ("zielony", ["green"]),
    ("żółty", ["yellow"]), ("czarny", ["black"]), ("biały", ["white"]),
    ("różowy", ["pink"]), ("pomarańczowy", ["orange"]),
    ("jabłko", ["apple"]), ("banan", ["banana"]), ("chleb", ["bread"]), ("mleko", ["milk"]),
    ("woda", ["water"]), ("ser", ["cheese"]), ("jajko", ["egg"]), ("ciastko", ["cookie", "cake"]),
    ("dom", ["house", "home"]), ("szkoła", ["school"]), ("książka", ["book"]),
    ("stół", ["table"]), ("krzesło", ["chair"]), ("okno", ["window"]), ("drzwi", ["door"]),
    ("łóżko", ["bed"]), ("samochód", ["car"]), ("rower", ["bike", "bicycle"]),
    ("słońce", ["sun"]), ("księżyc", ["moon"]), ("gwiazda", ["star"]), ("drzewo", ["tree"]),
    ("kwiat", ["flower"]), ("deszcz", ["rain"]), ("śnieg", ["snow"]),
    ("mama", ["mom", "mother", "mum"]), ("tata", ["dad", "father"]), ("brat", ["brother"]),
    ("siostra", ["sister"]), ("przyjaciel", ["friend"]), ("dziecko", ["child", "kid", "baby"]),
    ("ręka", ["hand"]), ("noga", ["leg"]), ("głowa", ["head"]), ("oko", ["eye"]),
    ("duży", ["big", "large"]), ("mały", ["small", "little"]), ("szczęśliwy", ["happy"]),
    ("smutny", ["sad"]), ("zimno", ["cold"]), ("gorąco", ["hot"]),
    ("jeden", ["one"]), ("dwa", ["two"]), ("trzy", ["three"]), ("pięć", ["five"]),
    ("dziesięć", ["ten"]), ("poniedziałek", ["monday"]), ("niedziela", ["sunday"]),
]
_EN_FILL = {"the", "a", "an", "it", "is", "it's", "its", "to", "jest", "chyba", "po",
            "angielsku", "mówi", "się", "sie", "mowi", "myślę", "mysle", "że", "ze",
            "luna", "luno", "hmm", "yyy", "eee", "no", "to"}

_lock = threading.Lock()
_q = None                 # the game going on, or None


def trigger(text):
    """The game asked for: "mul", "add", "sub", "mix", "words", "guess", or None."""
    low = text.lower()
    if len(re.findall(r"\w+", low)) > 10:
        return None
    if any(g in low for g in _GUESS):
        return "guess"
    if not any(t in low for t in _TRIGGERS):
        return None
    for kind, stems in _KINDS:
        if any(s in low for s in stems):
            return kind
    return None


def active():
    global _q
    with _lock:
        if _q and time.time() - _q["asked"] > EXPIRE_SECS:
            print("[quiz] expired", flush=True)
            _q = None
            _card(None)
        return _q is not None


def _card(text, sub="", tone=None, secs=EXPIRE_SECS):
    """The game card on her screen (robot_face.py, overlay "card")."""
    with state.lock:
        if text is None:
            if state.overlay and state.overlay[0] == "card":
                state.overlay = None
            return
        state.overlay = ("card", time.time() + secs, {"text": text, "sub": sub, "tone": tone})


def _listen_longer():
    """Children think — keep the conversation open a bit longer."""
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time() + THINK_SECS)


def _norm(s):
    return " ".join(w for w in re.findall(r"[a-ząćęłńóśźż']+", s.lower()) if w not in _EN_FILL)


# ── one question ──────────────────────────────────────────────────────────────

def _math_problem(kind, limit):
    op = random.choice(["mul", "add", "sub"]) if kind == "mix" else kind
    if op == "mul":
        a, b = random.randint(2, 9), random.randint(2, 9)
        return op, a, b, a * b
    if op == "add":
        a = random.randint(2, limit - 2)
        b = random.randint(1, limit - a)
        return op, a, b, a + b
    a = random.randint(3, limit)
    b = random.randint(1, a - 1)
    return op, a, b, a - b


def _new_question(q):
    """Fills q with the next question: card, spoken, answer, reveal."""
    seen = q["seen"]
    if q["kind"] == "words":
        pool = [w for w in WORDS if w[0] not in seen] or WORDS
        pl, en = random.choice(pool)
        seen.add(pl)
        q.update(card=f"{pl} = ?", say=f"Jak jest po angielsku: {pl}?", answer=en,
                 reveal=f"{pl} = {en[0]}",
                 right=f"{pl[0].upper()}{pl[1:]} to po angielsku {en[0]}.")
        return
    for _ in range(20):                                   # no repeats
        op, a, b, res = _math_problem(q["kind"], q["limit"])
        if (op, a, b) not in seen and (op != "mul" or (b, a) not in seen):
            break
    seen.add((op, a, b))
    q.update(card=f"{a} {_SYM[op]} {b} = ?", say=f"Ile to jest {a} {_WORD[op]} {b}?",
             answer=res, reveal=f"{a} {_SYM[op]} {b} = {res}",
             right=f"{a} {_WORD[op]} {b} to {res}.")


def _check(q, text):
    """True / False, or None when the utterance is no answer at all."""
    if q["kind"] == "words":
        said = _norm(text)
        if not said:
            return None
        for en in q["answer"]:
            if en in said.split() or difflib.SequenceMatcher(None, said, en).ratio() >= 0.8:
                return True
        if len(said.split()) > 4:                          # a sentence, not a word
            return None
        q["last_try"] = said
        return False
    import calc
    n = calc.number_in(text)
    if n is None:
        return None
    q["last_try"] = n
    return n == q["answer"]


def _ask(speak):
    q = _q
    _new_question(q)
    q.update(tries=0, asked=time.time())
    q["n"] += 1
    sub = f"pytanie {q['n']} z {QUESTIONS}"
    _card(q["card"], ("po angielsku · " if q["kind"] == "words" else "") + sub)
    speak(q["say"])
    _listen_longer()


# ── start / answer / finish ───────────────────────────────────────────────────

def start(kind, text, speak, play_sound_async):
    global _q
    limit = 20 if re.search(r"\b(20|dwudziestu|dwadzieścia)\b", text.lower()) else 100
    with _lock:
        _q = {"kind": kind, "limit": limit, "n": 0, "score": 0, "seen": set(),
              "asked": time.time(), "tries": 0}
        if kind == "guess":
            _q.update(secret=random.randint(1, 100), lo=1, hi=100)
    with state.lock:
        state.emotion = "Happy"
    print(f"[quiz] start: {kind}" + (f" up to {limit}" if kind not in ("guess", "words") else ""),
          flush=True)
    if kind == "guess":
        _card("1 – 100", "zgadnij liczbę")
        speak("Dobrze! Pomyślałam sobie liczbę od 1 do 100. Zgaduj!")
        _listen_longer()
        return
    name = {"mul": "tabliczki mnożenia", "add": "dodawania", "sub": "odejmowania",
            "mix": "rachunków", "words": "angielskich słówek"}[kind]
    speak(f"Super, quiz z {name}! {QUESTIONS} pytań — zaczynamy!")
    with _lock:
        if _q:
            _ask(speak)


def _finish(speak, play_sound_async):
    global _q
    score = _q["score"]
    _q = None
    if score == QUESTIONS:
        said, emo = f"Bezbłędnie! {score} na {QUESTIONS}! Mistrzowski wynik!", "Happy"
    elif score >= QUESTIONS - 1:
        said, emo = f"Pięknie! {score} na {QUESTIONS} punktów!", "Happy"
    elif score >= QUESTIONS // 2:
        said, emo = f"Nieźle! {score} na {QUESTIONS}. Jeszcze trochę ćwiczeń i będzie komplet.", "Happy"
    else:
        said, emo = (f"{score} na {QUESTIONS}. Nic nie szkodzi — ćwiczenie czyni mistrza. "
                     "Zagramy jeszcze raz?"), "Neutral"
    print(f"[quiz] done: {score}/{QUESTIONS}", flush=True)
    _card(f"{score} / {QUESTIONS}", "wynik", "ok" if score >= QUESTIONS - 1 else None, secs=6)
    with state.lock:
        state.emotion = emo
    if score >= QUESTIONS - 1:
        play_sound_async("chime")
    speak(said)


def _tries_pl(n):
    if n == 1:
        return "za pierwszym razem"
    return f"w {n} próbach"


def _guess(text, speak, play_sound_async):
    """One guess in the number game. False when it was no guess at all."""
    global _q
    import calc
    q = _q
    low = text.lower()
    if any(s in low for s in _DONT_KNOW):
        _card(str(q["secret"]), "to była ta liczba", None, secs=5)
        speak(f"Pomyślałam {q['secret']}. Zagramy jeszcze raz?")
        _q = None
        return True
    n = calc.number_in(text)
    if n is None:
        print("[quiz] no number in the guess — game over", flush=True)
        _q = None
        _card(None)
        return False
    q["asked"] = time.time()
    if not 1 <= n <= 100:
        speak("Od 1 do 100!")
        _listen_longer()
        return True
    q["tries"] += 1
    if n == q["secret"]:
        _card(str(n), _tries_pl(q["tries"]), "ok", secs=6)
        with state.lock:
            state.emotion = "Happy"
        play_sound_async("chime")
        print(f"[quiz] number guessed in {q['tries']}", flush=True)
        extra = " Niesamowite!" if q["tries"] <= 3 else (" Sprytnie!" if q["tries"] <= 7 else "")
        speak(f"Brawo, to {n}! Udało się {_tries_pl(q['tries'])}.{extra}")
        _q = None
        return True
    if n < q["secret"]:
        q["lo"] = max(q["lo"], n + 1)
        word = random.choice(["Więcej!", "Więcej.", "Wyżej!"])
    else:
        q["hi"] = min(q["hi"], n - 1)
        word = random.choice(["Mniej!", "Mniej.", "Niżej!"])
    _card(f"{q['lo']} – {q['hi']}", f"próba {q['tries']}", None)
    speak(word)
    _listen_longer()
    return True


def answer(text, speak, play_sound_async):
    """An utterance while a game is on. True when it was part of the game."""
    global _q
    low = text.lower()
    with _lock:
        if _q is None:
            return False
        if any(s in low for s in _STOP) and len(re.findall(r"\w+", low)) <= 5:
            speak("Dobrze, kończymy.")
            if _q["kind"] == "guess":
                _q = None
                _card(None)
            else:
                _finish(speak, play_sound_async)
            return True
        q = _q
        if q["kind"] == "guess":
            return _guess(text, speak, play_sound_async)
        if any(s in low for s in _DONT_KNOW):
            _card(q["reveal"], "", None, secs=4)
            speak(f"Nic nie szkodzi. {q['right']}")
        else:
            ok = _check(q, text)
            if ok is None:
                print("[quiz] not an answer — quiz over", flush=True)
                _q = None
                _card(None)
                return False
            if ok:
                q["score"] += 1
                _card(q["reveal"], "", "ok", secs=4)
                with state.lock:
                    state.emotion = "Happy"
                play_sound_async("chime")
                speak(random.choice(_PRAISE))
            elif q["tries"] == 0:
                q["tries"] = 1
                q["asked"] = time.time()
                _card(q["card"], "spróbuj jeszcze raz", "bad")
                speak(f"Hmm, nie {q['last_try']}. Spróbuj jeszcze raz!")
                _listen_longer()
                return True
            else:
                _card(q["reveal"], "", "bad", secs=4)
                speak(f"Niestety nie. {q['right']}")
        with state.lock:
            state.emotion = "Neutral"
        if q["n"] >= QUESTIONS:
            _finish(speak, play_sound_async)
        else:
            _ask(speak)
        return True
