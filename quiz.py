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
             "pocwiczyc", "poćwiczmy", "pocwiczmy", "test z", "na czas", "szybka tabliczk",
             "wyścig", "wyscig")
_KINDS = [("div", ("dzieleni", "dzielić", "dzielic")),
          ("mul", ("tabliczk", "mnożeni", "mnozeni", "mnożyć", "mnozyc")),
          ("add", ("dodawani", "dodawać", "dodawac")),
          ("sub", ("odejmowani", "odejmować", "odejmowac")),
          ("story", ("z treścią", "z trescia", "tekstow", "zadań z", "zadan z")),
          ("capitals", ("stolic", "stolica")),
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
_SYM = {"mul": "×", "add": "+", "sub": "−", "div": ":"}
_WORD = {"mul": "razy", "add": "plus", "sub": "minus", "div": "podzielić przez"}

# reading practice: short sentences for a second-grader, written for Luna
READING = [
    "Kot śpi na kanapie.", "Pies biega po łące.", "Mama piecze ciasto.",
    "Na drzewie siedzi ptak.", "Lubię lody truskawkowe.", "Słońce świeci jasno.",
    "Żaba skacze do stawu.", "Wiewiórka zbiera orzechy.", "Tata czyta gazetę.",
    "W ogrodzie rosną róże.", "Rybka pływa w akwarium.", "Jutro jedziemy nad morze.",
    "Mój rower jest czerwony.", "Zima jest biała i zimna.", "Babcia robi pierogi.",
    "Chomik je ziarenka.", "Księżyc świeci w nocy.", "Lubię rysować kredkami.",
    "Pada deszcz, weź parasol.", "Dzieci bawią się w chowanego.", "Krowa daje mleko.",
    "Biedronka ma kropki.", "W lesie mieszka jeż.", "Po burzy pojawiła się tęcza.",
    "Pszczoły zbierają miód.", "Nasz dom ma zielone drzwi.", "Konik je marchewkę.",
    "W szkole uczymy się pisać.", "Wieczorem gasimy światło.", "Luna jest małym robotem.",
]

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


_WORDS_SET = re.compile(r"\b(?:słowa|slowa|słówka|slowka)\s+(?:do|na)\s+dyktand\w*\s*:?\s*(.+)$|"
                        r"\bdyktand\w*\s+(?:ze|z)\s+(?:słów|slow|wyrazów|wyrazow)\s*:?\s*(.+)$",
                        re.I)
_WORDS_CLEAR = re.compile(r"\b(?:wyczyść|wyczysc|usuń|usun|zapomnij)\s+słowa\s+do\s+dyktand", re.I)


_LIMITS = {"dziesięciu": 10, "dziesieciu": 10, "dwudziestu": 20, "trzydziestu": 30,
           "pięćdziesięciu": 50, "piecdziesieciu": 50, "stu": 100, "tysiąca": 1000,
           "tysiaca": 1000}


def quiz_limit(text):
    """"dodawanie do 20", "w zakresie 50", "do tysiąca" → the range (10–1000);
    100 when not said."""
    m = re.search(r"\b(?:do|zakresie|zakres)\s+(\d{2,4}|\w+)\b", text.lower())
    if m:
        w = m.group(1)
        n = int(w) if w.isdigit() else _LIMITS.get(w)
        if n and 10 <= n <= 1000:
            return n
    return 100


def table_row(text):
    """"…tabliczki przez 7", "…mnożenia przez siedem" → 7 (2–10), else None."""
    import calc
    m = re.search(r"\bprzez\s+(\d{1,2}|\w+)\b", text.lower())
    if not m:
        return None
    w = m.group(1)
    n = int(w) if w.isdigit() else calc._ONES.get(w)
    return n if n and 2 <= n <= 10 else None


def custom_words(text):
    """"…słowa do dyktanda: rzeka, góra i żaba" → ["rzeka", "góra", "żaba"],
    or None."""
    m = _WORDS_SET.search(text)
    if not m:
        return None
    raw = re.split(r",|\s+i\s+|\s+oraz\s+|;", m.group(1) or m.group(2))
    words = [w.strip(" .!?").lower() for w in raw if w.strip(" .!?")]
    words = [w for w in words if 1 <= len(w.split()) <= 2 and len(w) <= 25]
    return words or None


def dictation_words(text, speak):
    """"Zapamiętaj słowa do dyktanda: …" / "wyczyść słowa do dyktanda" —
    handled (True) or not."""
    import settings
    if _WORDS_CLEAR.search(text):
        settings.put("dictation_words", [])
        speak("Dobrze, w dyktandzie znowu będą moje słowa.")
        return True
    words = custom_words(text)
    if words and not re.search(r"\b(?:zróbmy|zrobmy|zrób|zrob|zagrajmy|przepytaj|"
                               r"podyktuj|daj)\b", text, re.I):
        settings.put("dictation_words", words)
        import calc
        n = len(words)
        speak(f"Zapamiętałam {n} {calc._plural(n, 'słowo', 'słowa', 'słów')} do dyktanda: "
              f"{', '.join(words)}. "
              "Powiedz: zróbmy dyktando.")
        return True
    return False


def trigger(text):
    """The game asked for: "mul", "add", "sub", "mix", "words", "guess", or None."""
    low = text.lower()
    if len(re.findall(r"\w+", low)) > 10:
        return None
    if any(g in low for g in _GUESS):
        return "guess"
    if re.search(r"\b(?:czytani\w*|poczytaj\w*|czytać|czytac)\b", low) and re.search(
            r"\b(?:poćwiczmy|pocwiczmy|ćwicz\w*|cwicz\w*|uczmy|nauka|naucz|pobawmy|zagrajmy|"
            r"przepytaj|sprawdź|sprawdz)\b", low) and len(re.findall(r"\w+", low)) <= 8:
        return "read"                          # "poćwiczmy czytanie" — she listens to you
    if re.search(r"\bdyktand|\bortograf", low) and (
            len(re.findall(r"\w+", low)) <= 2 and "?" not in low or re.search(
                r"\b(?:zróbmy|zrobmy|zrób|zrob|pobawmy|zagrajmy|przepytaj|poćwicz\w*|"
                r"pocwicz\w*|ćwicz\w*|cwicz\w*|podyktuj|dyktuj|napiszmy|daj|chcę|chce|"
                r"możemy|mozemy|piszemy|zacznijmy)\b", low)):
        if re.search(r"\b(angielsk\w*|english|po\s+angielsku)\b", low):
            return "dictation_en"              # "dyktando z angielskiego"
        return "dictation"                     # not "jutro mamy dyktando w szkole"
    if re.search(r"\bzegar", low) and re.search(
            r"\b(?:pobawmy|zagrajmy|naucz|ucz|uczyć|przepytaj|ćwicz\w*|cwicz\w*|gra\w*|"
            r"odczytywa\w*|czytać|czytac)\b", low):
        return "clock"                         # not "pokaż zegar" (screens.py)
    if _riddle_request(low):
        return "riddle"
    if ("tabliczk" in low and table_row(text) and len(re.findall(r"\w+", low)) <= 6
            and not re.search(r"\b(?:powtórz|powtorz|wyrecytuj|powiedz|przeczytaj|pokaż|"
                              r"pokaz)\b", low)):        # "powtórz mi tabliczkę": recite it
        return "mul"                           # "tabliczka przez 7" — a request already
    if not any(t in low for t in _TRIGGERS):
        return None
    # "quiz"/"test z" alone is often just told ("w szkole robili quiz ze
    # stolic"): then a request word, or a few words only, is needed
    if not any(t in low for t in _TRIGGERS if t not in ("quiz", "kwiz", "test z",
                                                         "pytania z", "na czas", "wyścig",
                                                         "wyscig", "szybka tabliczk")) and \
            len(re.findall(r"\w+", low)) > 4 and not re.search(
                r"\b(?:zróbmy|zrobmy|zrób|zrob|zagrajmy|pobawmy|daj|chcę|chce|możemy|"
                r"mozemy|zacznijmy|poproszę|poprosze|zadaj|włącz|wlacz)\b", low):
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
    if re.search(r"\b(?:trudn\w*|logiczn\w*|podchwytliw\w*|dla\s+dorosł\w*|matematyczn\w*|"
                 r"na\s+myślenie|łamigłówk\w*)\b", low):
        return False                       # "trudną zagadkę" — the model's, not a child's list
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

def _math_problem(kind, limit, row=None):
    op = random.choice(["mul", "add", "sub"]) if kind == "mix" else kind
    if op == "div":                                    # always a whole answer: 56 : 7
        b = row or random.randint(2, 9)
        c = random.randint(1, 10)
        return op, b * c, b, c
    if op == "mul":
        if row:                                       # "tabliczka przez 7": that row only
            a, b = row, random.randint(1, 10)
            if random.random() < 0.5:
                a, b = b, a
            return op, a, b, a * b
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


def _past_misses(game):
    """What the person in front of her got wrong lately in this game (her day
    and diary, mood.py): ["rzeka", "7 × 8 = 56", …], most recent first."""
    try:
        import mood
        with state.lock:
            who = state.person[0] if state.person else None
        if not who:
            return []
        with mood._lock:
            today = list(mood._load().get("games", []))
        past = [g for e in mood._diary() for g in (e.get("games") or [])]
        out = []
        for g in reversed(past + today):
            if g.get("who") == who and g.get("game") == game:
                out += [m for m in g.get("misses", []) if m not in out]
        return out
    except Exception:
        return []


REPEAT_MISSES = 0.5        # how often a question is one they got wrong lately


def _new_question(q):
    """Fills q with the next question: card, spoken, answer, reveal."""
    seen = q["seen"]
    if q["kind"] == "read":
        pool = [s for s in READING if s not in seen] or READING
        sentence = random.choice(pool)
        seen.add(sentence)
        q.update(card=sentence, say="Przeczytaj na głos, co jest na ekranie.",
                 answer=sentence, reveal=sentence, right=f"Tu jest napisane: {sentence}")
        return
    if q["kind"] == "dictation_en":
        pool = [w for w in WORDS if w[0] not in seen] or WORDS
        again = [w for w in pool if w[1][0] in _past_misses("dyktando angielskie")]
        pl, en = (random.choice(again) if again and random.random() < REPEAT_MISSES
                  else random.choice(pool))
        seen.add(pl)
        q.update(card="pisz!", say=f"Napisz po angielsku: {pl}. Kiedy skończysz, pokaż "
                 "mi kartkę i powiedz: gotowe.", answer=en[0], accept=en,
                 hint=f"Podpowiem: zaczyna się na literę {en[0][0].upper()} "
                      f"i ma {len(en[0])} liter.",
                 reveal=en[0], right=f"{pl.capitalize()} po angielsku to {en[0]}: "
                 + ", ".join(en[0].upper()) + ".")
        return
    if q["kind"] == "dictation":
        import commands
        import settings
        mine = q.get("words") or settings.get("dictation_words") or []
        source = mine or DICTATION                  # the teacher's list, if given
        pool = [w for w in source if w not in seen] or source
        again = [w for w in _past_misses("dyktando") if w in pool]
        word = (random.choice(again) if again and random.random() < REPEAT_MISSES
                else random.choice(pool))
        seen.add(word)
        letters = ", ".join(commands._LETTERS.get(c, c) for c in word)
        traps = _traps(word)
        q.update(card="pisz!", say=f"Napisz na kartce słowo: {word}. Kiedy skończysz, "
                 "pokaż mi kartkę i powiedz: gotowe.", answer=word,
                 hint=f"Podpowiem: piszemy {traps}." if traps else "",
                 reveal=word, right=f"{word.capitalize()} piszemy tak: {letters}"
                 + (f" — {traps}." if traps else "."))
        return
    if q["kind"] == "story":
        import quizdata
        problem, value, how = quizdata.word_problem(seen)
        seen.add(problem[:40])
        q.update(card="?", say=problem, answer=value, reveal=str(value),
                 right=f"Odpowiedź to {value}, bo {how} to {value}.")
        return
    if q["kind"] == "capitals":
        import quizdata
        question, accept = quizdata.pick_capital(seen)
        seen.add(question)
        q.update(card="stolica?", say=question, answer=[a.lower() for a in accept],
                 reveal=accept[0], right=f"To {accept[0]}.")
        return
    if q["kind"] == "clock":
        import clockgame
        h, m = clockgame.question(seen, q.get("level", 1))
        seen.add((h, m))
        q.update(card=f"{h}:{m:02d}", say="Która godzina jest na zegarze?", answer=(h, m),
                 reveal=f"{h}:{m:02d}", right=f"To {clockgame.say(h, m)}.")
        return
    if q["kind"] == "riddle":
        riddle, answer, accept, hint = _riddle(seen)
        seen.add(answer)
        q.update(card="?", say=riddle, answer=accept, hint=hint,
                 reveal=answer, right=f"To {answer}!")
        return
    if q["kind"] == "words":
        pool = [w for w in WORDS if w[0] not in seen] or WORDS
        missed = {m.split(" = ")[0] for m in _past_misses("angielskie słówka")}
        again = [w for w in pool if w[0] in missed]
        pl, en = (random.choice(again) if again and random.random() < REPEAT_MISSES
                  else random.choice(pool))
        seen.add(pl)
        q.update(card=f"{pl} = ?", say=f"Jak jest po angielsku: {pl}?", answer=en,
                 reveal=f"{pl} = {en[0]}",
                 right=f"{pl[0].upper()}{pl[1:]} to po angielsku {en[0]}.")
        return
    for _ in range(20):                                   # no repeats
        op, a, b, res = _math_problem(q["kind"], q["limit"], q.get("row"))
        if q["kind"] == "mul" and not q.get("row") and random.random() < REPEAT_MISSES:
            again = [tuple(int(x) for x in re.findall(r"\d+", m)[:2])
                     for m in _past_misses("tabliczka mnożenia")]
            again = [p for p in again if len(p) == 2 and ("mul",) + p not in seen]
            if again:                                     # one they got wrong lately
                a, b = random.choice(again)
                res = a * b
        if (op, a, b) not in seen and (op != "mul" or (b, a) not in seen):
            break
    seen.add((op, a, b))
    q.update(card=f"{a} {_SYM[op]} {b} = ?", say=f"Ile to jest {a} {_WORD[op]} {b}?",
             answer=res, reveal=f"{a} {_SYM[op]} {b} = {res}",
             right=f"{a} {_WORD[op]} {b} to {res}.")


def would_accept(text):
    """Would `text` be the right answer to the question on now? (a copy is
    judged — the game is untouched). speech_to_text: when the cloud hears
    nothing, Vosk's words still count if they are the right answer — 7 Oct
    18:58 "to nie inna ryba" (Vosk, loud) was dropped, the riddle's answer
    was "ryba", and Maja and Andrzej thought she had got stuck."""
    import copy
    with _lock:
        if _q is None or not _q.get("answer"):
            return False
        q = copy.deepcopy(_q)
    try:
        return _check(q, text) is True
    except Exception:
        return False


def _check(q, text):
    """True / False, or None when the utterance is no answer at all."""
    if q["kind"] == "clock":
        import clockgame
        t = clockgame.parse(text)
        if t is None:
            return None
        q["last_try"] = f"{t[0]}:{t[1]:02d}"
        ok = clockgame.same(t, q["answer"])
        q["streak"] = q.get("streak", 0) + 1 if ok else 0
        if q["streak"] >= 2 and q.get("level", 1) < 2:
            q["level"] = 2                     # two right in a row: five-minute steps
        return ok
    if q["kind"] == "capitals":
        # every letter, not only Polish ones: "Brasília", "Reykjavík" (_norm
        # dropped the í and a right answer didn't count)
        said = " ".join(w for w in re.findall(r"\w+", text.lower()) if w not in _EN_FILL)
        if not said:
            return None
        for a in q["answer"]:
            stem = a[:max(3, len(a) - 2)]
            if stem in said or difflib.SequenceMatcher(None, said.split()[-1], a).ratio() >= 0.8:
                return True
        if len(said.split()) > 6:
            return None
        q["last_try"] = said.split()[-1]
        return False
    if q["kind"] == "read":
        want = re.findall(r"\w+", q["answer"].lower())
        got = re.findall(r"\w+", text.lower())
        if not got:
            return None
        hits = sum(1 for w in want if any(
            difflib.SequenceMatcher(None, w, g).ratio() >= 0.8 for g in got))
        missing = [w for w in want if not any(
            difflib.SequenceMatcher(None, w, g).ratio() >= 0.8 for g in got)]
        q["last_try"] = "„" + text.strip(" .") + "”"
        q["hint"] = (f"Spójrz jeszcze raz na słowo: {missing[0]}." if missing else "")
        return hits >= max(1, round(0.8 * len(want)))
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
    global _q
    q = _q
    try:
        _new_question(q)
    except Exception as e:                   # word problems need the cloud
        print(f"[quiz] no question ({e}) — game over", flush=True)
        _q = None
        _card(None)
        speak("Nie mogę teraz wymyślić pytania — chyba nie mam internetu. "
              "Spróbujmy później albo zagrajmy w zagadki.")
        return
    q.update(tries=0, asked=time.time())
    if q.get("race") and not q.get("timed"):
        q["timed"] = time.time()             # the clock starts at the first question
    q["n"] += 1
    total = q["total"]
    sub = (f"zagadka {q['n']} z {total}" if q["kind"] == "riddle" else
           f"dyktando · słowo {q['n']} z {total} · pokaż kartkę i powiedz „gotowe”"
           if q["kind"] in ("dictation", "dictation_en") else f"pytanie {q['n']} z {total}")
    if q["kind"] == "clock":                 # the clock face, not the answer
        h, m = q["answer"]
        with state.lock:
            state.overlay = ("clockface", time.time() + EXPIRE_SECS,
                             {"h": h, "m": m, "sub": f"zegar · {q['n']} z {q['total']}"})
    else:
        _card(q["card"], ("po angielsku · " if q["kind"] == "words" else "") + sub)
    speak(q["say"])
    _listen_longer()


# ── start / answer / finish ───────────────────────────────────────────────────

def start(kind, text, speak, play_sound_async):
    global _q
    limit = quiz_limit(text)
    with _lock:
        _q = {"kind": kind, "limit": limit, "n": 0, "score": 0, "seen": set(),
              "asked": time.time(), "tries": 0,
              "total": RIDDLES if kind == "riddle" else QUESTIONS}
        if kind == "guess":
            _q.update(secret=random.randint(1, 100), lo=1, hi=100)
        if kind in ("mul", "div"):
            row = table_row(text)                    # "tabliczka mnożenia przez 7"
            if row:
                _q["row"] = row
        if kind == "dictation":
            words = custom_words(text)               # "dyktando ze słów: …" — just these
            if words:
                _q["words"] = words
                _q["total"] = min(len(words), 10)
        if kind in ("mul", "div", "add", "sub", "mix", "words", "capitals") and re.search(
                r"\b(na\s+czas|szybk\w*|wyścig\w*|wyscig\w*|na\s+wyścigi)\b", text.lower()):
            _q["race"] = True                  # a race: the time counts, records kept
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
    elif kind == "read":
        speak(f"Ćwiczymy czytanie! Na ekranie pojawi się zdanie — przeczytaj je na głos. "
              f"{total} zdań.")
    elif kind == "dictation_en":
        speak(f"Dyktando z angielskiego! Powiem słowo po polsku, a ty napisz je "
              f"po angielsku. Przygotuj kartkę. {total} słów.")
    elif kind == "story":
        speak(f"Zadania z treścią! Słuchaj uważnie, {total} zadań.")
    elif kind == "capitals":
        speak(f"Quiz ze stolic! {total} pytań.")
    elif kind == "clock":
        speak(f"Uczymy się zegara! Krótka wskazówka to godziny, długa to minuty. "
              f"{total} pytań.")
    else:
        name = {"mul": "tabliczki mnożenia", "add": "dodawania", "sub": "odejmowania",
                "div": "dzielenia",
                "mix": "rachunków", "words": "angielskich słówek"}[kind]
        speak(f"Super, quiz z {name}! {total} pytań"
              + (" na czas — liczę sekundy!" if _q.get("race") else " — zaczynamy!"))
    with _lock:
        if _q:
            _ask(speak)


def race_result(kind, perfect, secs, who=None):
    """"Czas: 48 sekund — nowy rekord!" A record needs a perfect round; kept per
    person (by face) and game in settings "race_best"."""
    import settings
    secs = int(round(secs))
    import calc
    sek = lambda n: f"{n} {calc._plural(n, 'sekunda', 'sekundy', 'sekund')}"   # noqa: E731
    said = f"Czas: {sek(secs)}."
    if not perfect:
        return said + " Rekord liczy się tylko bez błędu."
    if who is None:
        with state.lock:
            who = state.person[0] if state.person else "?"
    best = settings.get("race_best", {}) or {}
    key = f"{who}:{kind}"
    old = best.get(key)
    if old is None or secs < old:
        best[key] = secs
        settings.put("race_best", best)
        return said + (f" Nowy rekord! Poprzedni: {sek(old)}." if old else
                       " To twój pierwszy rekord!")
    return said + f" Rekord to {sek(old)}."


def _finish(speak, play_sound_async, early=False):
    global _q
    score, total = _q["score"], _q["total"]
    if early:
        # "Koniec" after 3 of 5 questions: "0 na 5" counted questions never asked
        # (7 Oct probe); no star and no perfect-round count for a cut-short round
        answered = max(0, int(_q.get("n", total)) - 1)
        _q = None
        if answered:
            _card(f"{score} / {answered}", "do tej pory", None, secs=5)
            # "0 na 2" alone was flat for a child: a kind word with a low score
            speak(f"Do tej pory {score} na {answered}."
                  + (" Następnym razem pójdzie lepiej — ćwiczenie czyni mistrza!"
                     if score * 2 < answered or score == 0 else "")
                  + " Zagramy kiedy indziej do końca?")
        else:
            _card(None)
        return
    try:                                    # for "jak Mai poszło dyktando?"
        import mood
        with state.lock:
            who = state.person[0] if state.person else None
        mood.note_game(who, _q["kind"], score, total, _q.get("misses", []))
    except Exception as e:
        print(f"[quiz] result not noted: {e}", flush=True)
    timed = _q.get("timed")
    kind = _q["kind"]
    _q = None
    if score == total:
        said, emo = f"Bezbłędnie! {score} na {total}! Mistrzowski wynik!", "Happy"
    elif score >= total - 1:
        said, emo = f"Pięknie! {score} na {total}!", "Happy"
    elif score >= total // 2:
        said, emo = f"Nieźle! {score} na {total}. Jeszcze trochę ćwiczeń i będzie komplet.", "Happy"
    else:
        said, emo = (f"{score} na {total}. Nic nie szkodzi — ćwiczenie czyni mistrza. "
                     "Zagramy jeszcze raz?"), "Neutral"
    if timed:
        said += " " + race_result(kind, score == total, time.time() - timed)
    print(f"[quiz] done: {score}/{total}", flush=True)
    stars = award_star() if score == total else None
    if stars:                                    # a perfect round: a star
        said += f" Dostajesz gwiazdkę! Masz już {stars}."
    if score == total and not stars:       # (stars count perfect rounds already)
        import settings
        with state.lock:
            who = state.person[0] if state.person else "_"
        recs = settings.get("records", {}) or {}
        mine = recs.setdefault(who, {})
        mine["perfect"] = mine.get("perfect", 0) + 1
        settings.put("records", recs)
        if mine["perfect"] > 1:
            said += f" To już {mine['perfect']}. bezbłędna runda!"
    if not stars:                          # the star is on the screen instead
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


def _star_for(now=None):
    """Who gets the star: the person in front of her — but with a child in
    view as well, the child (the games are theirs: 7 Oct 18:58 Maja and
    Andrzej solved riddles together and the star went to Andrzej, the one
    recognised first)."""
    now = now or time.time()
    with state.lock:
        main = state.person[0] if state.person else None
        others, seen_at = state.others
    if not main:
        return None
    try:
        import faces
        notes = faces.notes()
        recent = now - seen_at < 3 * faces.RECOGNISE_EVERY
    except Exception:
        return main
    def child(n):
        return "dziecko" in (notes.get(n, "") or "").lower()
    if child(main) or not recent:
        return main
    kids = [o for o in (others or []) if o != "?" and child(o)]
    if kids:
        print(f"[quiz] {main} and {kids[0]} in view — the star goes to {kids[0]}", flush=True)
        return kids[0]
    return main


def award_star():
    """+1 star for the person in front of her (by face) — None for someone
    unknown. Shown big on the screen; "pokaż moje gwiazdki" shows them all."""
    import settings
    who = _star_for()
    if not who:
        return None
    stars = settings.get("stars", {}) or {}
    stars[who] = stars.get(who, 0) + 1
    settings.put("stars", stars)
    with state.lock:
        state.overlay = ("stars", time.time() + 5,
                         {"n": stars[who], "name": who, "new": True, "t0": time.time()})
    print(f"[quiz] a star for {who}: {stars[who]}", flush=True)
    return stars[who]


def show_stars(speak):
    """"Pokaż moje gwiazdki" / "ile mam gwiazdek?"."""
    import settings
    import faces
    with state.lock:
        who = state.person[0] if state.person else None
    if not who:
        speak("Nie wiem, kim jesteś — gwiazdki zbiera każdy osobno. Powiedz: jestem…")
        return
    n = (settings.get("stars", {}) or {}).get(who, 0)
    voc = faces.vocatives().get(who) or who
    with state.lock:
        state.overlay = ("stars", time.time() + 8,
                         {"n": n, "name": who, "new": False, "t0": time.time()})
    if n:
        speak(f"Masz {n} {_stars_pl(n)}, {voc}! Każda za bezbłędną rundę.")
    else:
        speak(f"Jeszcze nie masz gwiazdek, {voc}. Bezbłędna runda w quizie, zagadkach "
              "albo dyktandzie daje gwiazdkę!")


def _stars_pl(n):
    if n == 1:
        return "gwiazdkę"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "gwiazdki"
    return "gwiazdek"


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
    words = re.findall(r"\w+", low)
    if n is None and _HINT_Q.search(low):
        # (7 Oct probe: "Podpowiedz" ended the game, and "50" went to the model)
        q["asked"] = time.time()
        even = "parzysta" if q["secret"] % 2 == 0 else "nieparzysta"
        speak(f"Podpowiedź: to liczba między {q['lo']} a {q['hi']}, i jest {even}.")
        _listen_longer()
        return True
    if n is None and (_REPEAT_Q.match(low.strip(" .!?")) or len(words) <= 3):
        q["asked"] = time.time()
        speak(f"Szukamy liczby od {q['lo']} do {q['hi']}. Zgaduj!")
        _listen_longer()
        return True
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
    import time
    english = bool(_q and _q["kind"] == "dictation_en")
    # two looks 0.5 s apart: a paper still moving into view blurs one frame
    # (the same trouble rock-paper-scissors had with a single frame, 7 Oct)
    imgs = []
    for i in range(2):
        if i:
            time.sleep(0.5)
        img = brain._camera_jpeg_b64()
        if img:
            imgs.append(img)
    return brain.read_written_word(imgs, english=english)


_REPEAT_Q = re.compile(r"^(?:luna,?\s+)?(?:powtórz|powtorz|jeszcze\s+raz|co\s+mówiłaś|"
                       r"co\s+mowilas|nie\s+słyszałam|nie\s+słyszałem|nie\s+dosłyszałam|"
                       r"nie\s+dosłyszałem)(?:\s+(?:pytanie|zagadkę|zagadke|słowo|proszę|"
                       r"prosze|jeszcze\s+raz))*$", re.I)
_HINT_Q = re.compile(r"\b(?:podpowie\w*|podpowiedź|podpowiedz|pomóż|pomoz|pomocy|"
                     r"daj\s+wskazówkę|wskazówk\w*)\b", re.I)


def _hint_for(q):
    """A hint that helps without telling the answer."""
    kind = q.get("kind")
    if kind in ("dictation", "dictation_en"):
        # the stored hint names the tricky letters — that IS the test
        return ("Podpowiedź: posłuchaj słowa jeszcze raz i pomyśl o trudnych literach — "
                "ó czy u, rz czy ż, ch czy h." if kind == "dictation" else
                "Podpowiedź: napisz tak, jak to słowo wygląda w książce — nie tak, jak słychać.")
    if kind == "clock":
        return ("Podpowiedź: najpierw krótka wskazówka — pokazuje godzinę. "
                "Potem długa — każda cyfra to pięć minut.")
    if q.get("hint"):
        h = q["hint"]
        return h if h.lower().startswith("podpowi") else "Podpowiedź: " + h
    ans = q.get("answer")
    if kind == "capitals" and isinstance(ans, list) and ans:
        return f"Podpowiedź: to miasto zaczyna się na literę {ans[0][0].upper()}."
    if isinstance(ans, list) and ans and isinstance(ans[0], str):
        return f"Podpowiedź: to słowo zaczyna się na literę {ans[0][0].upper()}."
    if isinstance(ans, str) and ans:
        return f"Podpowiedź: to słowo zaczyna się na literę {ans[0].upper()}."
    m = re.match(r"\s*(\d+)\s*([×x·*])\s*(\d+)", str(q.get("card", "")))
    if m:
        a, b = int(m.group(1)), int(m.group(3))
        return (f"Podpowiedź: {a} razy {b} to tyle, co {b} dodane {a} razy. "
                "Policz po kolei!")
    # "71 − 23": tens first, then ones (8 Oct: "Policz krok po kroku" was all she said)
    m = re.match(r"\s*(\d+)\s*([+−:])\s*(\d+)", str(q.get("card", "")))
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        tens, ones = b // 10 * 10, b % 10
        if op == ":":
            return f"Podpowiedź: ile razy {b} mieści się w {a}? Albo: {b} razy ile daje {a}?"
        verb, word = ("dodaj", "w górę") if op == "+" else ("odejmij", "w dół")
        if tens and ones:
            return (f"Podpowiedź: najpierw {verb} dziesiątki — {tens}, a potem jeszcze {ones}.")
        if tens:                          # "40 − 20": two tens, not twenty steps
            n = tens // 10
            return (f"Podpowiedź: {verb} {n} "
                    f"{'dziesiątkę' if n == 1 else 'dziesiątki' if n < 5 else 'dziesiątek'}.")
        return f"Podpowiedź: zacznij od {a} i policz {b} {word}."
    return "Pomyśl jeszcze chwilkę — dasz radę! Policz krok po kroku."


def answer(text, speak, play_sound_async):
    """An utterance while a game is on. True when it was part of the game."""
    global _q
    low = text.lower()
    words = re.findall(r"\w+", low)
    with _lock:
        if _q is None:
            return False
        if re.search(r"\b(?:" + "|".join(map(re.escape, _STOP)) + r")\b", low) and len(words) <= 5:
            # the open question's answer — a child wants to know it was a tortoise
            # (8 Oct probe: "Koniec" mid-riddle → just "Dobrze, kończymy.")
            if _q["kind"] == "guess":
                tell = f" Myślałam o liczbie {_q.get('secret')}." if _q.get("secret") else ""
            else:
                right = str(_q.get("right") or "")
                tell = ("" if not right else f" {right}" if right.startswith("To ")
                        else f" A odpowiedź: {right}")
            speak("Dobrze, kończymy." + tell)
            if _q["kind"] == "guess":
                _q = None
                _card(None)
            else:
                _finish(speak, play_sound_async, early=True)
            return True
        q = _q
        if q["kind"] == "guess":
            return _guess(text, speak, play_sound_async)
        # "Powtórz" / "podpowiedz" are part of the game, not an answer (7 Oct
        # probe: "Powtórz" ended the maths quiz as "not an answer", and in the
        # riddles "Powtórz zagadkę" and "Podpowiedź" were judged as guesses)
        if _REPEAT_Q.match(low.strip(" .!?")) and q.get("say"):
            q["asked"] = time.time()
            speak(q["say"])
            _listen_longer()
            return True
        if _HINT_Q.search(low) and len(words) <= 5:
            q["asked"] = time.time()
            speak(_hint_for(q))
            _listen_longer()
            return True
        if any(s in low for s in _DONT_KNOW):
            _card(q["reveal"], "", None, secs=5)
            q.setdefault("misses", []).append(q["reveal"])
            speak(f"Nic nie szkodzi. {q['right']}")
        else:
            if q["kind"] in ("dictation", "dictation_en"):
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
                    ok = (any(_same_word(written, a) for a in q["accept"])
                          if q.get("accept") else _same_word(written, q["answer"]))
                    if not ok and not q.get("accept") and \
                            _plain(written) == _plain(q["answer"]):
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
                if q["kind"] in ("dictation", "dictation_en"):
                    speak(f"Na kartce widzę {q['last_try']}. "
                          + (q.get("hint") or "") + " Popraw i pokaż jeszcze raz.")
                else:
                    hint = q.get("hint") if q["kind"] in ("riddle", "read") else None
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
