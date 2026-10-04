"""
quiz.py — "przepytaj mnie z tabliczki mnożenia": a spoken maths quiz.

  "Przepytaj mnie z tabliczki mnożenia"   → 7 × 8, 6 × 9 …
  "Quiz z dodawania" / "z odejmowania"     → up to 100 ("do dwudziestu": 20)
  "Pobawmy się w rachunki"                 → a mix of all three

Five questions. Each one is shown big on her screen and asked aloud; the
answer is just said ("pięćdziesiąt sześć", "56", "to będzie 56"). A wrong
answer gets one more try, then she tells the right one. "Nie wiem" moves on,
"koniec" stops. At the end: the score.

Lives between utterances: commands.handle passes each new utterance here
while a quiz is on (answer()), so the normal voice loop keeps running. An
utterance with no number in it ends the quiz and goes to the model as usual.
"""

import random
import re
import threading
import time

from shared_state import state

QUESTIONS   = 5
THINK_SECS  = 15          # extra listening time after each question
EXPIRE_SECS = 60          # no answer this long → the quiz is over

_TRIGGERS = ("przepytaj", "quiz", "kwiz", "sprawdź mnie", "sprawdz mnie", "pytaj mnie",
             "zadawaj mi", "zagadki z", "pobawmy się w", "pobawmy sie w",
             "zagrajmy w", "pytania z", "ćwiczyć", "cwiczyc", "poćwiczyć",
             "pocwiczyc", "poćwiczmy", "pocwiczmy", "test z")
_KINDS = [("mul", ("tabliczk", "mnożeni", "mnozeni", "mnożyć", "mnozyc")),
          ("add", ("dodawani", "dodawać", "dodawac")),
          ("sub", ("odejmowani", "odejmować", "odejmowac")),
          ("mix", ("rachunk", "matematyk", "matm", "liczeni", "liczyć", "liczyc",
                   "działa", "dziala"))]
_STOP = ("koniec", "stop", "wystarczy", "nie chcę", "nie chce", "przestań",
         "przestan", "dość", "dosc", "kończymy", "konczymy")
_DONT_KNOW = ("nie wiem", "poddaję się", "poddaje sie", "pomiń", "pomin", "następne",
              "nastepne", "dalej", "nie mam pojęcia", "nie mam pojecia")
_PRAISE = ["Brawo!", "Dobrze!", "Super!", "Tak jest!", "Świetnie!", "Zgadza się!",
           "Bingo!"]
_SYM = {"mul": "×", "add": "+", "sub": "−"}
_WORD = {"mul": "razy", "add": "plus", "sub": "minus"}

_lock = threading.Lock()
_q = None                 # the quiz going on, or None


def trigger(text):
    """The kind of quiz asked for ("mul", "add", "sub", "mix"), or None."""
    low = text.lower()
    if not any(t in low for t in _TRIGGERS) or len(re.findall(r"\w+", low)) > 10:
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


def _problem(kind, limit):
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


def _card(text, sub="", tone=None, secs=EXPIRE_SECS):
    """The quiz card on her screen (robot_face.py, overlay "card")."""
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


def _ask(speak):
    q = _q
    seen = q["seen"]
    for _ in range(20):                                   # no repeats
        op, a, b, res = _problem(q["kind"], q["limit"])
        if (op, a, b) not in seen and (op != "mul" or (b, a) not in seen):
            break
    seen.add((op, a, b))
    q.update(op=op, a=a, b=b, res=res, tries=0, asked=time.time())
    q["n"] += 1
    _card(f"{a} {_SYM[op]} {b} = ?", f"pytanie {q['n']} z {QUESTIONS}")
    speak(f"Ile to jest {a} {_WORD[op]} {b}?")
    _listen_longer()


def start(kind, text, speak, play_sound_async):
    global _q
    limit = 20 if re.search(r"\b(20|dwudziestu|dwadzieścia)\b", text.lower()) else 100
    with _lock:
        _q = {"kind": kind, "limit": limit, "n": 0, "score": 0, "seen": set(),
              "asked": time.time()}
    with state.lock:
        state.emotion = "Happy"
    name = {"mul": "tabliczki mnożenia", "add": "dodawania", "sub": "odejmowania",
            "mix": "rachunków"}[kind]
    print(f"[quiz] start: {kind} up to {limit}", flush=True)
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
        said, emo = f"Świetnie! {score} na {QUESTIONS} punktów!", "Happy"
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


def answer(text, speak, play_sound_async):
    """An utterance while a quiz is on. True when it was part of the quiz."""
    global _q
    import calc
    low = text.lower()
    with _lock:
        if _q is None:
            return False
        if any(s in low for s in _STOP) and len(re.findall(r"\w+", low)) <= 5:
            speak("Dobrze, kończymy.")
            _finish(speak, play_sound_async)
            return True
        q = _q
        right = f"{q['a']} {_WORD[q['op']]} {q['b']} to {q['res']}."
        if any(s in low for s in _DONT_KNOW):
            _card(f"{q['a']} {_SYM[q['op']]} {q['b']} = {q['res']}", "", None, secs=4)
            speak(f"Nic nie szkodzi. {right}")
        else:
            n = calc.number_in(text)
            if n is None:
                print("[quiz] no number in the answer — quiz over", flush=True)
                _q = None
                _card(None)
                return False
            if n == q["res"]:
                q["score"] += 1
                _card(f"{q['a']} {_SYM[q['op']]} {q['b']} = {q['res']}", "", "ok", secs=4)
                with state.lock:
                    state.emotion = "Happy"
                play_sound_async("chime")
                speak(random.choice(_PRAISE))
            elif q["tries"] == 0:
                q["tries"] = 1
                q["asked"] = time.time()
                _card(f"{q['a']} {_SYM[q['op']]} {q['b']} = ?", "spróbuj jeszcze raz", "bad")
                speak(f"Hmm, nie {n}. Spróbuj jeszcze raz!")
                _listen_longer()
                return True
            else:
                _card(f"{q['a']} {_SYM[q['op']]} {q['b']} = {q['res']}", "", "bad", secs=4)
                speak(f"Niestety nie. {right}")
        with state.lock:
            state.emotion = "Neutral"
        if q["n"] >= QUESTIONS:
            _finish(speak, play_sound_async)
        else:
            _ask(speak)
        return True
