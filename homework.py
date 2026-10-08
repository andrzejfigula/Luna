"""
A child's sum: the answer is theirs to find. The prompt says so (faces.py),
yet the model still slipped now and then (8 Oct scenario: "36 podzielić na
4" → "policz, ile to 4 razy 9"), so a sentence that gives the result away is
swapped for a hint made here, before it is spoken.
"""

import re

from polish import number_words

_OPS = (
    ("div", r"(?:podzielić|podzielic|podzielone|dzielone)\s+(?:na|przez)|przez|:|/|÷"),
    ("mul", r"razy|pomnożyć\s+przez|pomnozyc\s+przez|pomnożone\s+przez|x|\*|×"),
    ("add", r"plus|dodać|dodac|\+"),
    ("sub", r"minus|odjąć|odjac|-|−"),
)
_TASK = re.compile(r"(\d{1,4})\s*(" + "|".join(f"(?P<{k}>{v})" for k, v in _OPS) + r")\s*(\d{1,4})",
                   re.I)


def task(text):
    """(a, op, b, result) for "ile to jest 36 podzielić na 4?", or None —
    also None when they already said a result ("… to 9?": theirs to check)."""
    m = _TASK.search(text or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(m.lastindex))
    op = next(k for k, _ in _OPS if m.group(k))
    if op == "div":
        if b == 0 or a % b:
            return None
        r = a // b
    elif op == "mul":
        r = a * b
    elif op == "add":
        r = a + b
    else:
        r = a - b
        if r < 0:
            return None
    if r in (a, b) or _says(text[m.end():], r):
        return None
    return a, op, b, r


def _says(text, r):
    words = number_words(r) if r < 1000 else ""
    return bool(re.search(rf"(?<![\d,.]){r}(?![\d,.]\d)", text or "")) or bool(
        words and re.search(rf"\b{re.escape(words)}\b", text or "", re.I))


def gives_away(sentence, t):
    return bool(t) and _says(sentence, t[3])


def hint(t):
    a, op, b, _ = t
    if op == "div":
        return f"Pomyśl: ile razy {b} mieści się w {a}? Możesz liczyć po {b} na palcach. Ile ci wychodzi?"
    if op == "mul":
        return f"Spróbuj dodać {a} do siebie {b} razy. Ile ci wychodzi?"
    tens, ones = b // 10 * 10, b % 10
    verb = "dodaj" if op == "add" else "odejmij"
    if tens and ones:                     # "45 + 38": tens first, then ones
        return (f"Najpierw do {a} {verb} {tens}, a potem jeszcze {ones}. Ile ci wychodzi?"
                if op == "add" else
                f"Najpierw od {a} {verb} {tens}, a potem jeszcze {ones}. Ile zostaje?")
    if op == "add":
        return f"Zacznij od {a} i policz jeszcze {b} w górę. Ile ci wychodzi?"
    return f"Zacznij od {a} i odliczaj {b} w dół. Ile zostaje?"
