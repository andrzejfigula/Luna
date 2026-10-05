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
RIDDLES     = 3           # a round of riddles is shorter

# dictation: words with a Polish spelling trap (ó/u, rz/ż, ch/h, ą/ę)
DICTATION = ["żółw", "góra", "rzeka", "chmura", "herbata", "ogórek", "drzewo", "żaba",
             "książka", "pszczoła", "morze", "chleb", "hulajnoga", "róża", "jeż",
             "mróz", "brzoza", "łódka", "ręka", "wąż", "chomik", "ósemka", "wieża",
             "rzodkiewka", "księżyc", "ołówek", "ptaszek", "góral", "huśtawka", "żółty"]
_TRAPS = [("ó", "przez ó z kreską"), ("rz", "przez rz"), ("ż", "przez ż z kropką"),
          ("ch", "przez ch"), ("h", "przez samo h"), ("ą", "z ą"), ("ę", "z ę")]
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
    if re.search(r"\bdyktand|\bortograf", low):
        return "dictation"
    if _riddle_request(low):
        return "riddle"
    if not any(t in low for t in _TRIGGERS):
        return None
    for kind, stems in _KINDS:
        if any(s in low for s in stems):
            return kind
    return None


def _same_word(written, want):
    return re.sub(r"[^\wąćęłńóśźż]", "", written.lower()) == want


def _plain(word):
    """Without Polish diacritics: "żółw" → "zolw"."""
    return word.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))


def _traps(word):
    """"żółw" → "przez ż z kropką, przez ó z kreską" (the spelling traps in it)."""
    found, rest = [], word
    for t, say in _TRAPS:
        if t in rest:
            found.append(say)
            rest = rest.replace(t, " ")
    return ", ".join(found)


def _riddle_request(low):
    """"zadaj mi zagadkę", "pobawmy się w zagadki", "zagadka!" (not "zagadki z
    matematyki" — that's a maths quiz)."""
    words = re.findall(r"\w+", low)
    if not re.search(r"\bzagad(?:ka|kę|ki|ek|kami|kach)\b", low) or len(words) > 8:
        return False                       # "to zagadkowe" isn't a request
    if any(s in low for _, stems in _KINDS for s in stems):
        return False
    asked = re.search(r"\b(?:zadaj|zadasz|opowiedz|powiedz|daj|wymyśl|wymysl|pobawmy|"
                      r"zagrajmy|chcę|chce|jeszcze|kolejn\w*|następn\w*|nastepn\w*)\b", low)
    return bool(asked) or [w for w in words if w not in ("luna", "luno")] in (
        ["zagadka"], ["zagadki"])


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


def _riddle(seen):
    """The next riddle (riddles.py, written by hand — the model's were too often
    untrue): one not asked in this round nor in the last rounds (settings)."""
    import random
    import riddles
    import settings
    recent = set(settings.get("riddles_recent", []) or []) | seen
    pool = [r for r in riddles.RIDDLES if r[1][0] not in recent] or \
           [r for r in riddles.RIDDLES if r[1][0] not in seen] or riddles.RIDDLES
    riddle, accept, hint = random.choice(pool)
    settings.put("riddles_recent", (list(settings.get("riddles_recent", []) or [])
                                    + [accept[0]])[-20:])
    return riddle, accept[0], accept, hint


def _new_question(q):
    """Fills q with the next question: card, spoken, answer, reveal."""
    seen = q["seen"]
    if q["kind"] == "dictation":
        import commands
        pool = [w for w in DICTATION if w not in seen] or DICTATION
        word = random.choice(pool)
        seen.add(word)
        letters = ", ".join(commands._LETTERS.get(c, c) for c in word)
        traps = _traps(word)
        q.update(card="pisz!", say=f"Napisz na kartce słowo: {word}. Kiedy skończysz, "
                 "pokaż mi kartkę i powiedz: gotowe.", answer=word,
                 hint=f"Podpowiem: piszemy {traps}." if traps else "",
                 reveal=word, right=f"{word.capitalize()} piszemy tak: {letters}"
                 + (f" — {traps}." if traps else "."))
        return
    if q["kind"] == "riddle":
        riddle, answer, accept, hint = _riddle(seen)
        seen.add(answer)
        q.update(card="?", say=riddle, answer=accept, hint=hint,
                 reveal=answer, right=f"To {answer}!")
        return
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
    if q["kind"] == "riddle":
        said = _norm(text).split()
        if not said:
            return None
        for a in q["answer"]:
            stem = a[:max(3, len(a) - 2)]          # "kot" / "kotek" / "kotka"
            if any(w.startswith(stem) or difflib.SequenceMatcher(None, w, a).ratio() >= 0.8
                   for w in said):
                return True
        if len(said) > 6:                           # a sentence, not a guess
            return None
        q["last_try"] = " ".join(said[-2:])
        return False
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
    total = q["total"]
    sub = (f"zagadka {q['n']} z {total}" if q["kind"] == "riddle" else
           f"dyktando · słowo {q['n']} z {total} · pokaż kartkę i powiedz „gotowe”"
           if q["kind"] == "dictation" else f"pytanie {q['n']} z {total}")
    _card(q["card"], ("po angielsku · " if q["kind"] == "words" else "") + sub)
    speak(q["say"])
    _listen_longer()


# ── start / answer / finish ───────────────────────────────────────────────────

def start(kind, text, speak, play_sound_async):
    global _q
    limit = 20 if re.search(r"\b(20|dwudziestu|dwadzieścia)\b", text.lower()) else 100
    with _lock:
        _q = {"kind": kind, "limit": limit, "n": 0, "score": 0, "seen": set(),
              "asked": time.time(), "tries": 0,
              "total": RIDDLES if kind == "riddle" else QUESTIONS}
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
    total = _q["total"]
    if kind == "riddle":
        speak(f"Uwielbiam zagadki! {total} zagadki — słuchaj uważnie.")
    elif kind == "dictation":
        speak(f"Dyktando! Przygotuj kartkę i coś do pisania. {total} słów.")
    else:
        name = {"mul": "tabliczki mnożenia", "add": "dodawania", "sub": "odejmowania",
                "mix": "rachunków", "words": "angielskich słówek"}[kind]
        speak(f"Super, quiz z {name}! {total} pytań — zaczynamy!")
    with _lock:
        if _q:
            _ask(speak)


def _finish(speak, play_sound_async):
    global _q
    score, total = _q["score"], _q["total"]
    try:                                    # for "jak Mai poszło dyktando?"
        import mood
        with state.lock:
            who = state.person[0] if state.person else None
        mood.note_game(who, _q["kind"], score, total, _q.get("misses", []))
    except Exception as e:
        print(f"[quiz] result not noted: {e}", flush=True)
    _q = None
    if score == total:
        said, emo = f"Bezbłędnie! {score} na {total}! Mistrzowski wynik!", "Happy"
    elif score >= total - 1:
        said, emo = f"Pięknie! {score} na {total} punktów!", "Happy"
    elif score >= total // 2:
        said, emo = f"Nieźle! {score} na {total}. Jeszcze trochę ćwiczeń i będzie komplet.", "Happy"
    else:
        said, emo = (f"{score} na {total}. Nic nie szkodzi — ćwiczenie czyni mistrza. "
                     "Zagramy jeszcze raz?"), "Neutral"
    print(f"[quiz] done: {score}/{total}", flush=True)
    if score == total:                     # how many perfect rounds so far
        import settings
        with state.lock:
            who = state.person[0] if state.person else "_"
        recs = settings.get("records", {}) or {}
        mine = recs.setdefault(who, {})
        mine["perfect"] = mine.get("perfect", 0) + 1
        settings.put("records", recs)
        if mine["perfect"] > 1:
            said += f" To już {mine['perfect']}. bezbłędna runda!"
    _card(f"{score} / {total}", "wynik", "ok" if score >= total - 1 else None, secs=6)
    with state.lock:
        state.emotion = emo
    if score >= total - 1:
        play_sound_async("chime")
    speak(said)


def _record(field, value, better):
    """Keep a per-person best (by face; "_" for someone unknown) in settings.
    Returns the previous best when `value` beats it, True for the first one,
    else None."""
    import settings
    with state.lock:
        who = state.person[0] if state.person else "_"
    recs = settings.get("records", {}) or {}
    mine = recs.setdefault(who, {})
    old = mine.get(field)
    if old is None or better(value, old):
        mine[field] = value
        settings.put("records", recs)
        print(f"[quiz] record for {who}: {field} = {value} (was {old})", flush=True)
        return old if old is not None else True
    return None


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
        prev = _record("guess", q["tries"], lambda new, old: new < old)
        if prev is not None and prev is not True:
            extra += f" Nowy rekord! Poprzedni: {prev} prób."
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


_READY = ("gotowe", "gotowa", "gotowy", "już", "juz", "sprawdź", "sprawdz", "patrz",
          "zobacz", "pokazuję", "pokazuje", "napisałam", "napisałem", "napisane", "jest")


def _read_paper():
    """The word on the paper held up to the camera (brain.read_written_word)."""
    import brain
    return brain.read_written_word(brain._camera_jpeg_b64())


def answer(text, speak, play_sound_async):
    """An utterance while a game is on. True when it was part of the game."""
    global _q
    low = text.lower()
    words = re.findall(r"\w+", low)
    with _lock:
        if _q is None:
            return False
        if any(s in low for s in _STOP) and len(words) <= 5:
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
            _card(q["reveal"], "", None, secs=5)
            q.setdefault("misses", []).append(q["reveal"])
            speak(f"Nic nie szkodzi. {q['right']}")
        else:
            if q["kind"] == "dictation":
                # the answer is on paper: "gotowe" → read it from the camera
                if not any(w in words for w in _READY):
                    if len(words) <= 4:
                        q["asked"] = time.time()
                        speak("Kiedy napiszesz, pokaż mi kartkę i powiedz: gotowe.")
                        _listen_longer()
                        return True
                    ok = None
                else:
                    written = _read_paper()
                    print(f"[quiz] on the paper: {written!r} (want {q['answer']!r})", flush=True)
                    if not written:
                        q["asked"] = time.time()
                        speak("Nie widzę dobrze napisu. Pokaż kartkę bliżej kamery "
                              "i powiedz: gotowe.")
                        _listen_longer()
                        return True
                    ok = _same_word(written, q["answer"])
                    if not ok and _plain(written) == _plain(q["answer"]):
                        # only dots and strokes differ — the webcam may have
                        # missed them (it read "żeka" as "zeka"): look again
                        again = _read_paper()
                        print(f"[quiz] second look: {again!r}", flush=True)
                        if again and _same_word(again, q["answer"]):
                            ok, written = True, again
                    q["last_try"] = f"„{written}”"
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
                if q["kind"] == "dictation":
                    speak(f"Na kartce widzę {q['last_try']}. "
                          + (q.get("hint") or "") + " Popraw i pokaż jeszcze raz.")
                else:
                    hint = q.get("hint") if q["kind"] == "riddle" else None
                    speak(f"Hmm, nie {q['last_try']}. "
                          + (f"Podpowiedź: {hint}" if hint else "Spróbuj jeszcze raz!"))
                _listen_longer()
                return True
            else:
                _card(q["reveal"], "", "bad", secs=6)
                q.setdefault("misses", []).append(q["reveal"])
                speak(f"Niestety nie. {q['right']}")
        with state.lock:
            state.emotion = "Neutral"
        if q["n"] >= q["total"]:
            _finish(speak, play_sound_async)
        else:
            _ask(speak)
        return True
