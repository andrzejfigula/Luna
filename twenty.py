"""
twenty.py — "Zgadnij, o czym myślę": twenty questions, Luna keeps the secret.

  "Zagrajmy w 20 pytań" / "zgadnij, o jakim zwierzęciu myślę" / "pomyśl
  sobie zwierzę"  → she picks an animal (here, so it never changes mid-game)
  "Czy ma futro?"  → "Tak!" / "Nie." / "Trudno powiedzieć…" — the model
                     answers yes/no about THAT animal only
  "Czy to kot?"    → right: praise, the number of questions; wrong: "Nie, to
                     nie kot."
  "Poddaję się"    → she tells it; "koniec" stops

Lives between utterances like the quizzes (commands.py).

The other way round — "zgadnij, o czym myślę", "pomyślałam sobie zwierzę":
the CHILD keeps the secret and Luna asks (7 Oct: both phrasings started the
game above, so Maja's "guess what I'm thinking of" got Luna's own animal).
  "Gotowe"         → her first question; "tak" / "nie" / "nie wiem" → the next
                     one (the model picks it from all answers so far) or a guess
  "Tak" to a guess → she cheers; after 20 questions she asks what it was
"""

import json
import math
import random
import re
import threading
import time

from shared_state import state

MAX_QUESTIONS = 20
EXPIRE_SECS = 120

# (nominative, accusative/“to …” forms accepted in a guess)
ANIMALS = [
    ("kot", ["kot", "kotek", "kota"]), ("pies", ["pies", "piesek", "psa"]),
    ("słoń", ["słoń", "słonia"]), ("żyrafa", ["żyrafa", "żyrafę"]),
    ("lew", ["lew", "lwa"]), ("tygrys", ["tygrys", "tygrysa"]),
    ("koń", ["koń", "konia"]), ("krowa", ["krowa", "krowę"]),
    ("świnia", ["świnia", "świnię", "świnka"]), ("owca", ["owca", "owcę"]),
    ("kura", ["kura", "kurę", "kurczak"]), ("kaczka", ["kaczka", "kaczkę"]),
    ("sowa", ["sowa", "sowę"]), ("pingwin", ["pingwin", "pingwina"]),
    ("delfin", ["delfin", "delfina"]), ("rekin", ["rekin", "rekina"]),
    ("wieloryb", ["wieloryb", "wieloryba"]), ("żaba", ["żaba", "żabę"]),
    ("wąż", ["wąż", "węża"]), ("żółw", ["żółw", "żółwia"]),
    ("motyl", ["motyl", "motyla"]), ("pszczoła", ["pszczoła", "pszczołę"]),
    ("mrówka", ["mrówka", "mrówkę"]), ("ślimak", ["ślimak", "ślimaka"]),
    ("wiewiórka", ["wiewiórka", "wiewiórkę"]), ("jeż", ["jeż", "jeża"]),
    ("zając", ["zając", "zająca"]), ("królik", ["królik", "królika"]),
    ("niedźwiedź", ["niedźwiedź", "niedźwiedzia", "miś"]), ("lis", ["lis", "lisa"]),
    ("wilk", ["wilk", "wilka"]), ("małpa", ["małpa", "małpę"]),
    ("zebra", ["zebra", "zebrę"]), ("krokodyl", ["krokodyl", "krokodyla"]),
    ("kangur", ["kangur", "kangura"]), ("papuga", ["papuga", "papugę"]),
    ("chomik", ["chomik", "chomika"]), ("mysz", ["mysz", "myszka", "myszkę"]),
    ("biedronka", ["biedronka", "biedronkę"]), ("ryba", ["ryba", "rybę", "rybka"]),
]

_START = ("20 pytań", "dwadzieścia pytań", "o czym myślę", "o jakim zwierzęciu myślę",
          "pomyśl sobie zwierzę", "pomyśl jakieś zwierzę", "pomysl sobie zwierze",
          "zgadnę zwierzę", "zgadywanie zwierząt", "o kim myślę")
# the child has the secret: "zgadnij, o czym myślę", "pomyślałam sobie
# zwierzę", "ty zgaduj" — Luna asks the questions
_REVERSE = re.compile(
    r"\b(?:o\s+(?:czym|kim|jakim\s+\w+)\s+(?:teraz\s+)?myśl[eę]|"
    r"pomyśla[łl](?:am|em)\s+(?:sobie\s+)?(?:jakieś\s+|o\s+)?zwierz\w*|"
    r"ty\s+zgaduj|ty\s+zgadnij|zgadnij\s+jakie\s+zwierz\w*|"
    r"(?:co|kogo)\s+mam\s+na\s+myśli)", re.I)
_GIVE_UP = ("poddaję się", "poddaje sie", "nie wiem", "powiedz co to", "co to było",
            "zdradź", "zdradz")
_STOP = ("koniec", "kończymy", "konczymy", "stop", "wystarczy")
# "Luna, już nie gramy" / "nie chcę już grać" — the "nie" read as an answer
# (11 Oct: "Odpowiedz mi: tak, nie albo nie wiem", then "wygrywasz!")
_QUIT = re.compile(r"^(?:luna,?\s+|luno,?\s+)?(?:(?:no\s+)?(?:już\s+|juz\s+)?nie\s+(?:gramy|gram|"
                   r"chcę\s+(?:już\s+)?grać|chce\s+(?:juz\s+)?grac)|koniec\s+(?:gry|zabawy)|"
                   r"skończmy|skonczmy|przestańmy|przestanmy)\b", re.I)
# a revealed secret that isn't on Luna's own list ("Wydra." after "Czy to bóbr?")
_MORE_ANIMALS = ("wydra", "bóbr", "bobr", "foka", "sarna", "jeleń", "dzik", "kret", "borsuk",
                 "łoś", "nietoperz", "gołąb", "wróbel", "bocian", "kogut", "koza", "osioł",
                 "hipopotam", "nosorożec", "gepard", "panda", "koala", "wielbłąd", "mors",
                 "ośmiornica", "meduza", "pająk", "dżdżownica", "kuna", "łasica", "jaszczurka",
                 "orzeł", "kruk", "sroka", "łabędź", "gęś", "indyk", "świnka morska",
                 "szczur", "lama", "alpaka", "flaming", "struś", "leniwiec")

_lock = threading.Lock()
_g = None              # {"animal", "forms", "asked", "t", "said_no": set()}


def wants(text):
    low = text.lower()
    return ((any(k in low for k in _START) or bool(_REVERSE.search(low)))
            and len(re.findall(r"\w+", low)) <= 10)


def reverse_wanted(text):
    return bool(_REVERSE.search(text.lower()))


def active():
    global _g, _r
    with _lock:
        if _g and time.time() - _g["t"] > EXPIRE_SECS:
            _g = None
        if _r and time.time() - _r["t"] > EXPIRE_SECS:
            _r = None
        return _g is not None or _r is not None


def start(speak, text=""):
    global _g
    if text and reverse_wanted(text):
        return _start_reverse(speak)
    name, forms = random.choice(ANIMALS)
    with _lock:
        with state.lock:
            player = state.person[0] if state.person else None
        _g = {"animal": name, "forms": forms, "asked": 0, "t": time.time(), "player": player}
    print(f"[twenty] thinking of: {name}", flush=True)
    with state.lock:
        state.overlay = ("card", time.time() + EXPIRE_SECS,
                         {"text": "?", "sub": "zgadnij zwierzę · pytaj: „czy ma…?”, „czy to…?”",
                          "tone": None})
    speak("Dobrze, pomyślałam sobie zwierzę! Zadawaj pytania, na które odpowiem tak "
          "albo nie. Masz dwadzieścia pytań.")
    _listen_longer()


def _listen_longer():
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time() + 15)


def _yes_no(animal, question):
    """The model answers a yes/no question about THIS animal: "tak" / "nie" / "?"."""
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=10, max_retries=1)
    r = c.chat.completions.create(
        model=OPENAI_MODEL, temperature=0, max_tokens=20,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   f"Gra w 20 pytań. Sekretne zwierzę to: {animal}. Dziecko pyta: "
                   f"\"{question}\". Odpowiedz zgodnie z prawdą o typowym przedstawicielu "
                   "tego gatunku, tak jak zrozumie to 8-latek. " + _kb_facts(animal) +
                   "Zwróć JSON {\"answer\": \"tak\" | \"nie\" | \"czasem\"}."}])
    return json.loads(r.choices[0].message.content).get("answer", "?")


def _kb_facts(animal):
    """What a child would answer about it (twenty_kb), for the model to stay
    consistent: "Czy ma długie uszy?" → "Tak!" for a mouse (11 Oct, Maja then
    guessed a rabbit)."""
    try:
        import twenty_kb
        row = twenty_kb.ANIMALS.get(animal)
        if not row:
            return ""
        said = [f"{q} {'tak' if v == 1 else 'nie'}" for (_, q), v in zip(twenty_kb.QUESTIONS, row)
                if v in (0, 1)]
        return "Jak odpowiada dziecko o tym zwierzęciu: " + "; ".join(said) + ". "
    except Exception:
        return ""


def _guessed(text, forms):
    words = re.findall(r"\w+", text.lower())
    return any(f in words for f in forms)


def _names_an_animal(text):
    words = set(re.findall(r"\w+", text.lower()))
    return next((n for n, forms in ANIMALS if words & set(forms)), None)


def _revealed(text):
    """The animal a child just told ("Wydra." / "to jest sowa"), or None."""
    low = text.lower().strip(" .!?")
    low = re.sub(r"^(?:luna,?\s+)?(?:nie,?\s+)?(?:no\s+)?(?:a\s+)?(?:to\s+)?(?:jest\s+|był[aoy]?\s+)?", "", low)
    if len(re.findall(r"\w+", low)) > 2:
        return None
    return _names_an_animal(low) or next((a for a in _MORE_ANIMALS if low == a), None)


def _for_game(low, game):
    """Plainly part of this game, whoever says it."""
    guess = game.get("guess") or game.get("animal") or ""
    return bool(_QUIT.match(low) or _revealed(low) or re.search(r"\bpyta[ńn]\b", low)
                or ("q" in game and (_YES.match(low) or _NO.match(low))
                    and len(low.split()) <= 6)                  # "Nie, nie żyje w Afryce"
                # "Czasem żyję w górach…", "Prawie takie samo jak kot" (11 Oct: to the
                # model, which played its own game — "Czy ma rogi?", "Czy to niedźwiedź?")
                or ("q" in game and _UNSURE.search(low) and len(low.split()) <= 9)
                or (guess and any(_same_animal(w, guess) for w in re.findall(r"\w+", low))))


def _same_animal(a, b):
    """"bóbr" / "bobr" / "bobra" — the same animal, case endings aside."""
    plain = str.maketrans("ąćęłńóśźż", "acelnoszz")
    a, b = a.lower().translate(plain), b.lower().translate(plain)
    if min(len(a), len(b)) < 3 or {a, b} & _COMMON:
        return False
    n = min(4, len(a), len(b))                       # "kot" / "kota"
    return a[:n] == b[:n]


_COMMON = {"nie", "tak", "ale", "jest", "cos", "czy", "moze", "jeszcze", "teraz", "tez"}


# ── the other way round: the child thinks, Luna asks ─────────────────────────
_r = None              # {"qa": [(question, answer)], "asked", "t", "q", "guess", "stage"}

# "raczej tak", "chyba nie" — a yes / no all the same
_YES = re.compile(r"^(?:no\s+)?(?:(?:raczej|chyba|prawie\s+że|chyba\s+że)\s+)?(?:tak|taak|jasne|"
                  r"pewnie|zgadza\s+się|dokładnie|owszem|zgadłaś|zgadlas|brawo|"
                  r"udało\s+ci\s+się)\b", re.I)
_NO = re.compile(r"^(?:no\s+)?(?:(?:raczej|chyba)\s+)?(?:nie|pudło|pudlo)\b(?!\s+wiem)", re.I)
# (11 Oct: "Troszeczkę jego ma." — "Odpowiedz mi: tak, nie albo nie wiem")
_UNSURE = re.compile(r"\b(?:nie\s+wiem|czasem|czasami|trochę|troche|troszkę|troszke|troszeczkę|"
                     r"troszeczke|nie\s+jestem\s+pew\w+|może|moze|to\s+zależy|zalezy|prawie|"
                     r"tak\s+jakby|po\s+części|po\s+czesci|nie\s+do\s+końca|nie\s+do\s+konca)\b",
                     re.I)
_READY = re.compile(r"\b(?:gotowe|gotowa|gotowy|już|juz|mam|wymyśli\w*|pomyśla\w*|dobra|ok|"
                    r"okej|tak|start|zaczynaj)\b", re.I)
_FIRST_Q = "Czy twoje zwierzę ma futro?"
_GROUPS = {"ptak", "ryba", "gad", "płaz", "plaz", "owad", "ssak", "zwierzę", "zwierze",
           "pajęczak", "mięczak", "robak", "drapieżnik", "roślinożerca", "zwierzątko"}


def _start_reverse(speak):
    global _r
    with state.lock:
        player = state.person[0] if state.person else None
    with _lock:
        _r = {"qa": [], "asked": 0, "t": time.time(), "q": None, "guess": None,
              "stage": "ready", "player": player}
    print("[twenty] reverse: the child thinks, Luna asks", flush=True)
    with state.lock:
        state.overlay = ("card", time.time() + EXPIRE_SECS,
                         {"text": "?", "sub": "ja zgaduję · odpowiadaj: tak / nie / nie wiem",
                          "tone": None})
    speak("Super! Pomyśl sobie zwierzę, a ja będę zgadywać. Odpowiadaj tak albo nie. "
          "Powiedz: gotowe, kiedy już wymyślisz.")
    _listen_longer()


def _next_move(qa, asked):
    """The next question or a guess: ("question" | "guess", text, animal) —
    from the table of animals, or the model's when the table has none."""
    try:
        move = _table_move(qa, asked)
        if move:
            return move
        print("[twenty] reverse: not an animal from the table — the model asks", flush=True)
    except Exception as e:
        print(f"[twenty] reverse: table failed ({e}) — the model asks", flush=True)
    return _model_move(qa, asked)


def _model_move(qa, asked):
    """The model's next question or a guess: ("question" | "guess", text, animal)."""
    from openai import OpenAI
    from config import OPENAI_API_KEY, CRAFT_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=12, max_retries=1)
    facts = "\n".join(f"- {q} → {a}" for q, a in qa) or "- (jeszcze nic)"
    must = asked >= MAX_QUESTIONS - 1
    r = c.chat.completions.create(
        model=CRAFT_MODEL, temperature=0.3, max_tokens=80,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   "Grasz z 8-letnim dzieckiem w 20 pytań. Dziecko pomyślało o zwierzęciu, "
                   "ty zgadujesz. Dotychczasowe pytania i odpowiedzi dziecka:\n" + facts +
                   f"\nZadano już {asked} z {MAX_QUESTIONS} pytań. Zadaj JEDNO następne "
                   "proste pytanie tak/nie, które najlepiej dzieli pozostałe zwierzęta "
                   "(nie powtarzaj pytań, nie pytaj o to, co już wiadomo), albo — gdy jesteś "
                   "dość pewna — zgadnij jedno konkretne zwierzę pytaniem \"Czy to …?\". "
                   "Najpierw ustal gromadę, pytając wprost (\"Czy to ptak?\", \"Czy to "
                   "owad?\", \"Czy to ryba?\", \"Czy to ssak, który ma sierść?\"), dopiero "
                   "potem pytaj o wygląd i miejsce życia. Nie zakładaj cech, których dziecko "
                   "nie potwierdziło (np. nie pytaj o pióra, dopóki nie wiesz, że to ptak). "
                   "Myśl o zwierzętach, które zna 8-latek (z podwórka, wsi, zoo, książeczek "
                   "— nie głuszec czy jarząbek), i zgaduj dopiero, gdy zostały 1–2 takie "
                   "możliwości. Zgadując, pytaj ZAWSZE \"Czy to …?\" (np. \"Czy to sowa?\"). "
                   + ("To ostatnie pytanie: MUSISZ zgadywać. " if must else "") +
                   "Dziecko może się mylić, więc nie odrzucaj zwierzęcia przez jedną dziwną "
                   "odpowiedź. Prosty język dla dziecka. Zwróć JSON {\"type\": \"question\" | "
                   "\"guess\", \"text\": \"Czy …?\", \"animal\": \"(przy zgadywaniu: nazwa "
                   "zwierzęcia w mianowniku)\"}."}])
    d = json.loads(r.choices[0].message.content)
    kind = "guess" if d.get("type") == "guess" else "question"
    text = (d.get("text") or "").strip()
    if not text:
        raise ValueError("empty move")
    return _as_guess(kind, text, (d.get("animal") or "").strip())


# ── her questions from a table of animals (13 Oct) ────────────────────────────
# The model alone asked 15–17 questions for an otter or a beaver, spent half of
# them on where it lives (11 Oct with Maja: lost on the 20th). twenty_kb has
# what a child would answer about ~110 animals; each answer reweighs them (a
# child's slip costs an animal weight, it doesn't rule it out) and the next
# question is the one that splits what is left best. An animal not in the
# table (too many answers against every one) → the model asks, as before.

def _kb():
    import twenty_kb
    keys = [k for k, _ in twenty_kb.QUESTIONS]
    by_text = {q.lower(): i for i, (_, q) in enumerate(twenty_kb.QUESTIONS)}
    by_text[_FIRST_Q.lower()] = keys.index("fur")
    return twenty_kb, by_text


_FANTASY = {"smok", "jednorożec", "dinozaur"}
_P_SLIP = 0.12         # a child's answer against the table: that likely


def _weights(qa):
    """{animal: weight} after the answers so far (wrong guesses: 0), and the
    fewest answers any animal contradicts outright."""
    kb, by_text = _kb()
    w = {a: (0.4 if a in _FANTASY else 1.0) for a in kb.ANIMALS}
    against = dict.fromkeys(kb.ANIMALS, 0)
    for q, ans in qa:
        i = by_text.get((q or "").lower())
        if i is None:
            m = re.match(r"czy\s+to\s+(?:jest\s+)?(.+?)\s*\?*$", (q or "").lower())
            if m and ans == "nie":                     # a wrong guess
                for a in w:
                    if _same_animal(a, m.group(1)) and len(a.split()) == len(m.group(1).split()):
                        w[a] = 0.0
            continue
        if ans not in ("tak", "nie"):
            continue                                   # "nie wiem": no news
        for a, row in kb.ANIMALS.items():
            v = row[i]
            p = _P_SLIP + (1 - 2 * _P_SLIP) * v
            p = p if ans == "tak" else 1 - p
            w[a] *= p
            if (v == 1 and ans == "nie") or (v == 0 and ans == "tak"):
                against[a] += 1
    return w, min(against[a] for a in w if w[a] > 0) if any(w.values()) else 99


def _entropy(ps):
    return -sum(p * math.log2(p) for p in ps if p > 0)


def _table_move(qa, asked):
    """("question" | "guess", text, animal) from the table, or None (→ the model)."""
    kb, by_text = _kb()
    w, least_against = _weights(qa)
    total = sum(w.values())
    if total <= 0 or least_against >= 4:
        return None                                    # not an animal it knows
    post = sorted(((v / total, a) for a, v in w.items() if v > 0), reverse=True)
    p1, top = post[0]
    p2 = post[1][0] if len(post) > 1 else 0.0
    if p1 >= 0.5 or (p1 >= 0.3 and p1 > 3 * p2) or asked >= MAX_QUESTIONS - 1:
        return "guess", f"Czy to {top}?", top
    asked_i = {by_text.get((q or "").lower()) for q, _ in qa}
    best, best_h = None, None
    for i, (_, q) in enumerate(kb.QUESTIONS):
        if i in asked_i:
            continue
        yes = sum((w[a] / total) * (_P_SLIP + (1 - 2 * _P_SLIP) * kb.ANIMALS[a][i])
                  for a in w if w[a] > 0)
        h = 0.0
        for ans_p, lik in ((yes, lambda v: _P_SLIP + (1 - 2 * _P_SLIP) * v),
                           (1 - yes, lambda v: 1 - _P_SLIP - (1 - 2 * _P_SLIP) * v)):
            if ans_p <= 0:
                continue
            ps = [(w[a] / total) * lik(kb.ANIMALS[a][i]) / ans_p for a in w if w[a] > 0]
            h += ans_p * _entropy(ps)
        if best_h is None or h < best_h:
            best, best_h = q, h
    if best is None:
        return "guess", f"Czy to {top}?", top
    return "question", best, ""


def _as_guess(kind, text, animal):
    """A "question" that names one animal is a guess: (kind, text, animal)."""
    # "Czy to ślimak?" sent as a question is a guess all the same (a "tak" to
    # it went on asking) — but "Czy to ptak?" asks about the group
    m = re.match(r"czy\s+to\s+(?:jest\s+)?(\w+)\s*\?*$", text.lower())
    if kind == "question" and m and m.group(1) not in _GROUPS:
        kind, animal = "guess", m.group(1)
    # "Czy twoje zwierzę jest sową / dzięciołem?" — a noun in the instrumental
    m = re.match(r"czy\s+twoje\s+zwierzę\s+(?:to\s+)?jest\s+(\w+(?:ą|em|iem))\s*\?*$",
                 text.lower())
    if kind == "question" and m and m.group(1) not in ("ssakiem", "ptakiem", "owadem",
                                                       "gadem", "płazem", "pająkiem",
                                                       "drapieżnikiem", "zwierzątkiem"):
        kind, animal = "guess", m.group(1)
    return kind, text, animal


def _ask_next(r, speak):
    """Say the next question or guess (from the model). False when there is none."""
    try:
        kind, q, animal = _next_move(r["qa"], r["asked"])
    except Exception as e:
        print(f"[twenty] reverse: no next move ({e})", flush=True)
        speak("Ojej, zgubiłam myśl. Zagrajmy jeszcze raz za chwilę!")
        return False
    r["asked"] += 1
    r["q"], r["guess"] = q, ((animal or q) if kind == "guess" else None)
    print(f"[twenty] reverse Q{r['asked']} ({kind}): {q}", flush=True)
    speak(q)
    _listen_longer()
    return True


def _answer_reverse(text, speak):
    """An utterance while Luna is guessing (called under _lock)."""
    global _r
    r = _r
    low = text.lower().strip(" .!?")
    words = re.findall(r"\w+", low)
    r["t"] = time.time()
    if (re.search(r"\b(?:" + "|".join(map(re.escape, _STOP)) + r")\b", low) and len(words) <= 4) \
            or _QUIT.match(low):
        _r = None
        speak("Dobrze, kończymy. Dzięki za grę!")
        return True
    if r["stage"] == "ready":
        if _READY.search(low) or len(words) <= 2:
            r["stage"], r["asked"] = "asking", 1
            r["q"], r["guess"] = _FIRST_Q, None
            speak("To zaczynam. " + _FIRST_Q)
            _listen_longer()
            return True
        _r = None
        return False
    if r["stage"] == "reveal":                       # what it was, after she gave up
        name = re.sub(r"^(?:no\s+)?(?:to\s+)?(?:był[aoy]?|jest|myślał\w*\s+o)\s+", "",
                      text.strip(" .!?"), flags=re.I).strip()
        if (_YES.match(low) or _NO.match(low)) and not r.get("asked_name"):
            r["asked_name"] = True                    # "nie" is no animal: ask once more
            speak("A jakie to było zwierzę? Powiedz mi!")
            _listen_longer()
            return True
        _r = None
        if re.search(r"\b(?:żadnym|zadnym|nic|niczym|nie\s+powiem|tajemnic\w*|sekret\w*)\b", low):
            # "O żadnym" became "Aha, O żabnie!" (11 Oct)
            speak("Tajemnica? Dobrze! Następnym razem zgadnę!")
            return True
        name = _revealed(text) or (name[:1].lower() + name[1:])
        speak(f"Aha, {name or 'rozumiem'}! Sprytnie. Następnym razem zgadnę!")
        return True
    if any(k in low for k in ("poddajesz", "poddaj się", "poddaj sie")):
        r["stage"] = "reveal"
        speak("Dobrze, poddaję się! O jakim zwierzęciu myślisz?")
        _listen_longer()
        return True
    if re.search(r"\bpyta[ńn]\b|\bpytania\b", low) and not _YES.match(low) and not _NO.match(low):
        # "Zostało ci dziesięć pytań" went to the model, which guessed on its own
        left = MAX_QUESTIONS - r["asked"]
        speak(f"Zadałam już {r['asked']}, zostało mi {left}. " + (r["q"] or ""))
        _listen_longer()
        return True
    told = _revealed(text)
    if told and not (r["guess"] and _same_animal(told, r["guess"])):
        # "Wydra." — the secret said straight out (11 Oct: "Odpowiedz mi: tak,
        # nie albo nie wiem", and the model played on without the game)
        _r = None
        speak(f"Aha, {told}! Nie wpadłam na to — sprytnie. Zagramy jeszcze raz?")
        return True
    yes, no = bool(_YES.match(low)), bool(_NO.match(low))
    # "Coś podobnego, ale to nie bóbr" — a no to the guess, said in a sentence
    if r["guess"] and not (yes or no) and any(
            re.search(r"\bnie\s+(?:\w+\s+)?" + re.escape(w) + r"\b", low)
            for w in re.findall(r"\w+", low) if _same_animal(w, r["guess"])):
        no = True
    unsure = bool(_UNSURE.search(low)) and not yes
    if not (yes or no or unsure):
        if len(words) > 8:
            _r = None                                 # not an answer: something else
            return False
        r["unclear"] = r.get("unclear", 0) + 1
        if r["unclear"] < 2:
            speak("Odpowiedz mi: tak, nie albo nie wiem. " + (r["q"] or ""))
            _listen_longer()
            return True
        # the second time: taken as "nie wiem", and on (11 Oct: "Czy to bóbr?"
        # asked three times running)
        unsure = True
    r["unclear"] = 0
    if r["guess"] and yes:
        _r = None
        with state.lock:
            state.overlay = ("card", time.time() + 6,
                             {"text": r["guess"], "sub": f"zgadłam w {r['asked']} pytaniach",
                              "tone": "ok"})
            state.emotion = "Happy"
        speak(f"Hurra! Zgadłam w {r['asked']} pytaniach! Zagramy jeszcze raz?")
        return True
    r["qa"].append((r["q"], "tak" if yes else "nie wiem" if unsure else "nie"))
    if r["asked"] >= MAX_QUESTIONS:
        r["stage"] = "reveal"
        speak("Ojej, skończyły mi się pytania — wygrywasz! O jakim zwierzęciu myślisz?")
        _listen_longer()
        return True
    if r["guess"]:
        speak(random.choice(["Hmm, pudło.", "Nie? To myślę dalej.", "Ojej, nie zgadłam."]))
    if not _ask_next(r, speak):
        _r = None
    return True


def answer(text, speak):
    """An utterance during the game. True when it belonged to it."""
    global _g
    global _r
    low = text.lower().strip(" .!?")
    with _lock:
        if (_g or _r) and len(low.split()) >= 2 and not wants(text) and \
                __import__("quiz")._OTHER_GAME.match(low):
            # "Zagrajmy w zgadywanie liczby" / "Zadaj mi zagadkę" mid-game got
            # "Zadaj pytanie, na które odpowiem tak albo nie" (9 Oct games sweep)
            animal = _g["animal"] if _g else None
            _g = _r = None
            print("[twenty] another game asked for — game over", flush=True)
            if animal:
                speak(f"Dobrze — moje zwierzę to {animal}.")
            return False
        with state.lock:
            speaker = state.person[0] if state.person else None
        game = _g or _r
        # (a game word — "nie gramy", "ale to nie bóbr", "wydra" — is the game's
        # whoever the camera thinks is talking: with Maja and Andrzej both at
        # the desk her answers went to the model, 11 Oct)
        if game and game.get("player") and speaker and speaker != game["player"] \
                and len(low.split()) >= 4 and not _for_game(low, game):
            return False                         # someone else talks: the game waits (#514)
        if _r is not None:
            return _answer_reverse(text, speak)
        g = _g
        if g is None:
            return False
        g["t"] = time.time()
        words = re.findall(r"\w+", low)
        if (re.search(r"\b(?:" + "|".join(map(re.escape, _STOP)) + r")\b", low)
                and len(words) <= 4) or _QUIT.match(low):
            _g = None
            speak(f"Dobrze. Moje zwierzę to {g['animal']}.")
            return True
        if any(k in low for k in _GIVE_UP) and len(words) <= 6:
            _g = None
            with state.lock:
                state.overlay = ("card", time.time() + 5,
                                 {"text": g["animal"], "sub": "to było to zwierzę", "tone": None})
            speak(f"Myślałam o zwierzęciu: {g['animal']}! Zagramy jeszcze raz?")
            return True
        named = _names_an_animal(low)
        # a guess is "czy to kot?", "to kot", "zgaduję kot", "kot?" — not "czy jest
        # większy od psa?" (a question that happens to name an animal)
        guess = named and (len(words) <= 2 or re.match(
            r"(?:czy\s+)?(?:to\b|zgaduj\w*|myśl\w*|mysl\w*|może\s+to|moze\s+to)", low))
        if guess:
            g["asked"] += 1
            if _guessed(low, g["forms"]):
                _g = None
                with state.lock:
                    state.overlay = ("card", time.time() + 6,
                                     {"text": g["animal"], "sub": f"zgadnięte w {g['asked']} pytaniach",
                                      "tone": "ok"})
                    state.emotion = "Happy"
                import quiz
                stars = quiz.award_star() if g["asked"] <= 10 else None
                speak(f"Tak! To {g['animal']}! Udało się w {g['asked']} pytaniach." +
                      (f" Za tak szybkie zgadnięcie gwiazdka! Masz już {stars}." if stars else ""))
                return True
            # their own words: "Czy to jest świnka morska?" got "Nie, to nie świnia"
            # (11 Oct — "świnka" is one of świnia's forms)
            m = re.search(r"(?:\bto(?:\s+jest)?|zgaduj\w*|może\s+to|moze\s+to)\s+"
                          r"((?:\w+\s+){0,2}\w+)\s*\W*$", low)
            said = m.group(1) if m and _names_an_animal(m.group(1)) else named
            speak(f"Nie, to nie {said}. Pytaj dalej!")
            _listen_longer()
            return True
        # hint / questions left / repeat are part of the game (7 Oct probe:
        # "Podpowiedz" ended it, and "Czy ma futro?" then went to the model)
        if re.search(r"\b(?:podpowie\w*|podpowiedź|podpowiedz|pomóż|pomoz|wskazówk\w*)\b", low):
            g["asked"] += 1                                # a hint costs a question
            speak(f"Podpowiedź: to zwierzę zaczyna się na literę {g['animal'][0].upper()}. "
                  f"Zostało ci {MAX_QUESTIONS - g['asked']} pytań.")
            _listen_longer()
            return True
        if re.search(r"\bile\b.*\bpyta[ńn]", low):
            left = MAX_QUESTIONS - g["asked"]
            speak(f"Pytań już zadanych: {g['asked']}, zostało {left}." if g["asked"] else
                  f"Masz jeszcze wszystkie {left} pytań.")
            _listen_longer()
            return True
        if re.match(r"^(?:powtórz|powtorz|jeszcze\s+raz|nie\s+rozumiem|jak\s+się\s+gra)\b", low):
            speak("Pomyślałam sobie zwierzę. Pytaj o nie, na przykład: czy ma futro? "
                  "Czy umie latać? Albo zgaduj: czy to kot?")
            _listen_longer()
            return True
        if not re.search(r"\b(czy|jest|ma|mieszka|potrafi|umie|je|lata|pływa|plywa)\b", low) \
                or len(words) > 15:
            if len(words) <= 4:                            # a short slip: still playing
                speak("Zadaj pytanie, na które odpowiem tak albo nie — albo zgaduj: czy to…?")
                _listen_longer()
                return True
            _g = None                                      # not a game question
            return False
        g["asked"] += 1
        try:
            yn = _yes_no(g["animal"], text)
        except Exception as e:
            print(f"[twenty] yes/no failed: {e}", flush=True)
            yn = "?"
        left = MAX_QUESTIONS - g["asked"]
        said = {"tak": random.choice(["Tak!", "Tak.", "Zgadza się!"]),
                "nie": random.choice(["Nie.", "Nie!", "Niestety nie."]),
                "czasem": "Czasami tak, czasami nie."}.get(yn, "Trudno powiedzieć…")
        if left <= 0:
            _g = None
            speak(f"{said} To było ostatnie pytanie! Moje zwierzę to {g['animal']}.")
            return True
        if left in (10, 5, 3, 1):
            said += f" Zostało {left} {'pytanie' if left == 1 else 'pytania' if left in (3,) else 'pytań'}."
        speak(said)
        _listen_longer()
        return True
