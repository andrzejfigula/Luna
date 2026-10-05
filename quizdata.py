"""
quizdata.py — content for quiz.py that must be right: capitals written by
hand, and word problems from the model checked by arithmetic here.
"""

import ast
import operator
import random

# (question, accepted answers — the first is said back)
CAPITALS = [
    ("Jaka jest stolica Polski?", ["Warszawa", "warszawa", "warszawie"]),
    ("Jaka jest stolica Niemiec?", ["Berlin"]),
    ("Jaka jest stolica Francji?", ["Paryż", "paryz", "paris"]),
    ("Jaka jest stolica Włoch?", ["Rzym", "rome", "roma"]),
    ("Jaka jest stolica Hiszpanii?", ["Madryt", "madrid"]),
    ("Jaka jest stolica Wielkiej Brytanii?", ["Londyn", "london"]),
    ("Jaka jest stolica Czech?", ["Praga", "prague"]),
    ("Jaka jest stolica Słowacji?", ["Bratysława", "bratyslawa", "bratislava"]),
    ("Jaka jest stolica Ukrainy?", ["Kijów", "kijow", "kyiv", "kiev"]),
    ("Jaka jest stolica Litwy?", ["Wilno", "vilnius"]),
    ("Jaka jest stolica Austrii?", ["Wiedeń", "wieden", "vienna", "wien"]),
    ("Jaka jest stolica Węgier?", ["Budapeszt", "budapest"]),
    ("Jaka jest stolica Grecji?", ["Ateny", "athens"]),
    ("Jaka jest stolica Portugalii?", ["Lizbona", "lisbon"]),
    ("Jaka jest stolica Holandii?", ["Amsterdam"]),
    ("Jaka jest stolica Belgii?", ["Bruksela", "brussels"]),
    ("Jaka jest stolica Szwecji?", ["Sztokholm", "stockholm"]),
    ("Jaka jest stolica Norwegii?", ["Oslo"]),
    ("Jaka jest stolica Danii?", ["Kopenhaga", "copenhagen"]),
    ("Jaka jest stolica Finlandii?", ["Helsinki"]),
    ("Jaka jest stolica Irlandii?", ["Dublin"]),
    ("Jaka jest stolica Szwajcarii?", ["Berno", "bern"]),
    ("Jaka jest stolica Rosji?", ["Moskwa", "moscow"]),
    ("Jaka jest stolica Stanów Zjednoczonych?", ["Waszyngton", "washington"]),
    ("Jaka jest stolica Kanady?", ["Ottawa"]),
    ("Jaka jest stolica Japonii?", ["Tokio", "tokyo"]),
    ("Jaka jest stolica Chin?", ["Pekin", "beijing"]),
    ("Jaka jest stolica Egiptu?", ["Kair", "cairo"]),
    ("Jaka jest stolica Australii?", ["Canberra", "kanbera", "kanberra"]),
    ("Jaka jest stolica Brazylii?", ["Brasília", "brasilia", "brazylia"]),
    ("Jaka jest stolica Argentyny?", ["Buenos Aires", "buenos"]),
    ("Jaka jest stolica Turcji?", ["Ankara"]),
    ("Jaka jest stolica Chorwacji?", ["Zagrzeb", "zagreb"]),
    ("Jaka jest stolica Islandii?", ["Reykjavik", "rejkiawik", "reykjavík"]),
]

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}


def _eval(expr):
    """+ - * / on whole numbers only — the model's sum, worked out here."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        raise ValueError("not plain arithmetic")
    return ev(ast.parse(expr.replace("×", "*").replace(":", "/"), mode="eval"))


def word_problem(seen):
    """(text, answer, explanation) — a short story sum for a second-grader,
    from the model, kept only when its own arithmetic checks out here."""
    import json
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=15, max_retries=1)
    for _ in range(4):
        r = c.chat.completions.create(
            model=OPENAI_MODEL, temperature=0.9, max_tokens=200,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content":
                       "Wymyśl jedno krótkie zadanie z treścią po polsku dla ucznia "
                       "2. klasy (dodawanie, odejmowanie, mnożenie albo dzielenie w "
                       "zakresie 100, jeden lub dwa kroki), o zwierzętach, owocach, "
                       "zabawkach albo szkole; odpowiedź to liczba całkowita od 0 do "
                       "100. Inne niż: " + ("; ".join(seen) or "—") + ". Zwróć JSON "
                       '{"problem": "treść kończąca się pytaniem", "expression": '
                       '"działanie z samymi liczbami, np. 3*4+2", "answer": liczba}'}])
        d = json.loads(r.choices[0].message.content)
        try:
            value = _eval(str(d["expression"]))
        except (ValueError, SyntaxError, KeyError, ZeroDivisionError):
            continue
        if value != int(value) or not 0 <= value <= 100 or int(d.get("answer", -1)) != value:
            continue                       # the model's sum is wrong: another one
        expr = str(d["expression"]).replace("*", " razy ").replace("/", " podzielić przez ") \
            .replace("+", " plus ").replace("-", " minus ")
        return d["problem"].strip(), int(value), " ".join(expr.split())
    raise RuntimeError("no checked word problem")


def pick_capital(seen):
    pool = [c for c in CAPITALS if c[0] not in seen] or CAPITALS
    return random.choice(pool)
