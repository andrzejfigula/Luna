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
"""

import json
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
_GIVE_UP = ("poddaję się", "poddaje sie", "nie wiem", "powiedz co to", "co to było",
            "zdradź", "zdradz")
_STOP = ("koniec", "kończymy", "konczymy", "stop", "wystarczy")

_lock = threading.Lock()
_g = None              # {"animal", "forms", "asked", "t", "said_no": set()}


def wants(text):
    low = text.lower()
    return any(k in low for k in _START) and len(re.findall(r"\w+", low)) <= 10


def active():
    global _g
    with _lock:
        if _g and time.time() - _g["t"] > EXPIRE_SECS:
            _g = None
        return _g is not None


def start(speak):
    global _g
    name, forms = random.choice(ANIMALS)
    with _lock:
        _g = {"animal": name, "forms": forms, "asked": 0, "t": time.time()}
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
                   "tego gatunku. Zwróć JSON {\"answer\": \"tak\" | \"nie\" | \"czasem\"}."}])
    return json.loads(r.choices[0].message.content).get("answer", "?")


def _guessed(text, forms):
    words = re.findall(r"\w+", text.lower())
    return any(f in words for f in forms)


def _names_an_animal(text):
    words = set(re.findall(r"\w+", text.lower()))
    return next((n for n, forms in ANIMALS if words & set(forms)), None)


def answer(text, speak):
    """An utterance during the game. True when it belonged to it."""
    global _g
    low = text.lower().strip(" .!?")
    with _lock:
        g = _g
        if g is None:
            return False
        g["t"] = time.time()
        words = re.findall(r"\w+", low)
        if any(k in low for k in _STOP) and len(words) <= 4:
            _g = None
            speak(f"Dobrze. Myślałam o: {g['animal']}.")
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
            speak(f"Nie, to nie {named}. Pytaj dalej!")
            _listen_longer()
            return True
        if not re.search(r"\b(czy|jest|ma|mieszka|potrafi|umie|je|lata|pływa|plywa)\b", low) \
                or len(words) > 15:
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
            speak(f"{said} To było ostatnie pytanie! Myślałam o: {g['animal']}.")
            return True
        if left in (10, 5, 3, 1):
            said += f" Zostało {left} {'pytanie' if left == 1 else 'pytania' if left in (3,) else 'pytań'}."
        speak(said)
        _listen_longer()
        return True
