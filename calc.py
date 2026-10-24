"""
calc.py — two kinds of questions answered on the spot, with no cloud:

  arithmetic   "ile to jest 17 razy 23?", "15 procent z 80", "pierwiastek
               z 144", "dwa do potęgi dziesięć", "100 podzielić przez 8"
               → "17 razy 23 to 391."
  days until   "ile dni do Wigilii?", "ile jeszcze do weekendu?", "ile dni
               do 15 marca?", "ile do Wielkanocy?" → "Do Wigilii zostało
               81 dni, czyli około 12 tygodni."

Both are strict: every word of the utterance has to belong to the question
(numbers, operators, a few fillers), so "ile razy dziennie mam podlewać
kwiatki?" still goes to the model. Instant, and they work offline — the
words Vosk writes ("dwanaście razy siedem") are understood as well as the
digits the cloud writes.
"""

import math
import re
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Warsaw")
except Exception:
    _TZ = None


def _today():
    return (datetime.now(_TZ) if _TZ else datetime.now()).date()


# ── Polish number words ───────────────────────────────────────────────────────

_ONES = {"zero": 0, "jeden": 1, "jedna": 1, "jedno": 1, "jedną": 1, "dwa": 2, "dwie": 2,
         "trzy": 3, "cztery": 4, "pięć": 5, "sześć": 6, "siedem": 7, "osiem": 8,
         "dziewięć": 9, "dziesięć": 10, "jedenaście": 11, "dwanaście": 12,
         "trzynaście": 13, "czternaście": 14, "piętnaście": 15, "szesnaście": 16,
         "siedemnaście": 17, "osiemnaście": 18, "dziewiętnaście": 19,
         "dwadzieścia": 20, "trzydzieści": 30, "czterdzieści": 40,
         "pięćdziesiąt": 50, "sześćdziesiąt": 60, "siedemdziesiąt": 70,
         "osiemdziesiąt": 80, "dziewięćdziesiąt": 90,
         "sto": 100, "dwieście": 200, "trzysta": 300, "czterysta": 400,
         "pięćset": 500, "sześćset": 600, "siedemset": 700, "osiemset": 800,
         "dziewięćset": 900}
# the same numbers after "z", "od", "przez" ("piętnaście procent z osiemdziesięciu")
_ONES.update({"dwóch": 2, "dwoch": 2, "trzech": 3, "czterech": 4, "pięciu": 5,
              "sześciu": 6, "siedmiu": 7, "ośmiu": 8, "dziewięciu": 9, "dziesięciu": 10,
              "jedenastu": 11, "dwunastu": 12, "trzynastu": 13, "czternastu": 14,
              "piętnastu": 15, "szesnastu": 16, "siedemnastu": 17, "osiemnastu": 18,
              "dziewiętnastu": 19, "dwudziestu": 20, "trzydziestu": 30,
              "czterdziestu": 40, "pięćdziesięciu": 50, "sześćdziesięciu": 60,
              "siedemdziesięciu": 70, "osiemdziesięciu": 80, "dziewięćdziesięciu": 90,
              "stu": 100, "dwustu": 200, "trzystu": 300, "czterystu": 400,
              "pięciuset": 500, "jednego": 1, "jednej": 1})
_SCALES = {"tysiąc": 1000, "tysiące": 1000, "tysięcy": 1000, "tysiąca": 1000,
           "milion": 10**6, "miliony": 10**6, "milionów": 10**6}


def _words_number(words):
    """["dwa", "tysiące", "pięćset"] → 2500."""
    total = cur = 0
    for w in words:
        if w in _ONES:
            cur += _ONES[w]
        else:
            total += max(cur, 1) * _SCALES[w]
            cur = 0
    return total + cur


def number_in(text):
    """The first number said in the text — "56", "pięćdziesiąt sześć", "to
    będzie czterdzieści dwa" — as an int/float, or None."""
    words = re.findall(r"-?\d+(?:[.,]\d+)?|[^\W\d_]+", text.lower())
    for i, w in enumerate(words):
        if re.fullmatch(r"-?\d+(?:[.,]\d+)?", w):
            x = float(w.replace(",", "."))
            return int(x) if x == int(x) else x
        if w in _ONES or w in _SCALES:
            j = i
            while j < len(words) and (words[j] in _ONES or words[j] in _SCALES):
                j += 1
            n = _words_number(words[i:j])
            return -n if i and words[i - 1] == "minus" else n
    return None


# ── arithmetic ────────────────────────────────────────────────────────────────

# operator phrases, longest first (matched on the joined words)
_OPS = [("pomnożone przez", "*"), ("pomnożyć przez", "*"), ("pomnóż przez", "*"),
        ("podzielone przez", "/"), ("podzielić przez", "/"), ("podziel przez", "/"),
        ("dzielone przez", "/"), ("dzielić przez", "/"),
        ("do potęgi", "^"), ("do kwadratu", "²"), ("do sześcianu", "³"),
        ("procent z", "%"), ("procent ze", "%"), ("procent od", "%"), ("pierwiastek z", "√"),
        ("pierwiastek kwadratowy z", "√"),
        ("plus", "+"), ("dodać", "+"), ("dodac", "+"), ("minus", "-"), ("odjąć", "-"),
        ("odjac", "-"), ("razy", "*"), ("przez", "/"),
        ("times", "*"), ("divided by", "/"), ("multiplied by", "*")]
_SPOKEN = {"+": "plus", "-": "minus", "*": "razy", "/": "przez", "^": "do potęgi",
           "%": "procent z"}
_FILL = {"ile", "to", "jest", "będzie", "bedzie", "wynosi", "luna", "luno", "policz",
         "oblicz", "powiedz", "mi", "proszę", "prosze", "a", "równa", "rowna", "się",
         "sie", "równe", "rowne", "wynik", "what", "is", "how", "much", "no", "hej",
         "czy", "wiesz", "możesz", "mozesz", "szybko", "ile", "oblicz", "tak"}


def _tokens(text):
    """Numbers and operators, or None if anything else is said."""
    low = text.lower().replace("%", " procent ").replace("√", " pierwiastek z ")
    # "23 procent VAT od 2400 złotych" (9 Oct: went to the model, which said
    # "Dwudziestotrzy procent…")
    low = re.sub(r"\bprocent\s+(?:vat|vatu|podatku|napiwku|rabatu|zniżki|znizki|marży|marzy)\b",
                 "procent", low)
    low = re.sub(r"\b(?:złotych|zlotych|złote|zlote|złoty|zloty|zł|zl|pln)\b", " ", low)
    low = re.sub(r"(\d)\s*[x×*]\s*(?=\d)", r"\1 razy ", low)
    low = re.sub(r"(\d)\s*[:÷/]\s*(?=\d)", r"\1 przez ", low)
    low = re.sub(r"(\d)\s*\+\s*(?=\d)", r"\1 plus ", low)
    low = re.sub(r"(\d)\s*[-−–]\s*(?=\d)", r"\1 minus ", low)
    low = re.sub(r"(\d)\s*\^\s*(?=\d)", r"\1 do potęgi ", low)
    while re.search(r"\d \d{3}\b", low):                       # "1 000 000"
        low = re.sub(r"(\d) (\d{3})\b", r"\1\2", low)
    words = re.findall(r"\d+(?:[.,]\d+)?|[^\W\d_]+", low)
    out, i = [], 0
    while i < len(words):
        w = words[i]
        op = next(((sym, len(p.split())) for p, sym in _OPS
                   if words[i:i + len(p.split())] == p.split()), None)
        if op:
            out.append(op[0])
            i += op[1]
        elif re.fullmatch(r"\d+(?:[.,]\d+)?", w):
            out.append(float(w.replace(",", ".")))
            i += 1
        elif w in _ONES or w in _SCALES:
            j = i
            while j < len(words) and (words[j] in _ONES or words[j] in _SCALES):
                j += 1
            out.append(float(_words_number(words[i:j])))
            i = j
        elif w in _FILL:
            i += 1
        else:
            return None
    return out


def _fmt(x):
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


class _Bad(Exception):
    pass


def _evaluate(toks):
    """(spoken expression, value). Usual precedence: unary √ ² ³ %, then ^,
    then * /, then + -."""
    # unary and percent first, into a flat list of numbers and + - * / ^
    flat, spoken, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if t == "√":
            if i + 1 >= len(toks) or not isinstance(toks[i + 1], float):
                raise _Bad
            if toks[i + 1] < 0:
                raise _Bad
            flat.append(math.sqrt(toks[i + 1]))
            spoken.append(f"pierwiastek z {_fmt(toks[i + 1])}")
            i += 2
        elif isinstance(t, float):
            if flat and isinstance(flat[-1], float):
                raise _Bad                          # "6:30 3": two numbers, no operator
            if i + 1 < len(toks) and toks[i + 1] in ("²", "³"):
                n = 2 if toks[i + 1] == "²" else 3
                flat.append(t ** n)
                spoken.append(f"{_fmt(t)} do {'kwadratu' if n == 2 else 'sześcianu'}")
                i += 2
            elif (i + 2 < len(toks) and toks[i + 1] == "%"
                  and isinstance(toks[i + 2], float)):
                flat.append(t / 100 * toks[i + 2])
                spoken.append(f"{_fmt(t)} procent z {_fmt(toks[i + 2])}")
                i += 3
            else:
                flat.append(t)
                spoken.append(_fmt(t))
                i += 1
        elif t in ("+", "-", "*", "/", "^"):
            if not flat or not isinstance(flat[-1], float):
                if t == "-" and (not flat or flat[-1] in ("+", "*", "/", "^")):
                    # "minus pięć razy dwa"
                    if i + 1 < len(toks) and isinstance(toks[i + 1], float):
                        flat.append(-toks[i + 1])
                        spoken.append(f"minus {_fmt(toks[i + 1])}")
                        i += 2
                        continue
                raise _Bad
            flat.append(t)
            spoken.append(_SPOKEN[t])
            i += 1
        else:
            raise _Bad
    if not flat or not isinstance(flat[-1], float):
        raise _Bad
    if len(flat) == 1 and len(toks) == 1:
        raise _Bad                                  # just a number, no question

    def fold(items, ops, fn):
        out = [items[0]]
        for k in range(1, len(items), 2):
            if items[k] in ops:
                out[-1] = fn(out[-1], items[k], items[k + 1])
            else:
                out += [items[k], items[k + 1]]
        return out

    def power(a, _, b):
        if abs(b) > 64 or (a == 0 and b < 0):
            raise _Bad
        return a ** b

    def muldiv(a, op, b):
        if op == "/" and b == 0:
            raise ZeroDivisionError
        return a * b if op == "*" else a / b

    flat = fold(flat, ("^",), power)
    flat = fold(flat, ("*", "/"), muldiv)
    flat = fold(flat, ("+", "-"), lambda a, op, b: a + b if op == "+" else a - b)
    value = flat[0]
    if isinstance(value, complex) or math.isinf(value) or math.isnan(value):
        raise _Bad
    return " ".join(spoken), value


_last_sum = {"first": None, "t": 0.0}
_FOLLOW = re.compile(r"^\W*(?:a|i|to)\s+(?:jak\s+|gdyby\s+)?((?:razy|plus|minus|dodać|odjąć|"
                     r"podzielić|przez)\b.*)$", re.I)


_N = r"(\d+(?:[.,]\d+)?)"
# a sum said as an order — 13 Oct probe, all to the model ("Pomnóż 12 przez 12",
# "Odejmij 8 od 20" — the way homework is read out)
_ORDERS = [
    (re.compile(rf"^(?:luna,?\s+)?(?:pomnóż|pomnoz)\s+{_N}\s+(?:przez|razy|i)\s+{_N}\W*$", re.I),
     r"\1 razy \2"),
    (re.compile(rf"^(?:luna,?\s+)?podziel\s+{_N}\s+(?:przez|na)\s+{_N}\W*$", re.I),
     r"\1 przez \2"),
    (re.compile(rf"^(?:luna,?\s+)?(?:dodaj|zsumuj)\s+{_N}\s+(?:i|do|plus|oraz)\s+{_N}\W*$", re.I),
     r"\1 plus \2"),
    (re.compile(rf"^(?:luna,?\s+)?odejmij\s+{_N}\s+od\s+{_N}\W*$", re.I), r"\2 minus \1"),
    (re.compile(rf"^(?:luna,?\s+)?odejmij\s+od\s+{_N}\s+{_N}\W*$", re.I), r"\1 minus \2"),
]
_FRACTIONS = {"połowa": (1, 2), "polowa": (1, 2), "pół": (1, 2), "pol": (1, 2),
              "ćwierć": (1, 4), "cwierc": (1, 4), "jedna trzecia": (1, 3),
              "jedna czwarta": (1, 4), "jedna piąta": (1, 5), "dwie trzecie": (2, 3),
              "trzy czwarte": (3, 4), "dwie piąte": (2, 5), "trzy piąte": (3, 5),
              "jedna dziesiąta": (1, 10)}
_FRACTION_OF = re.compile(r"^(?:luna,?\s+)?(?:ile\s+(?:to\s+)?(?:jest\s+)?|policz\s+|"
                          r"oblicz\s+)?(?:(\d+)\s*/\s*(\d+)|([^\W\d_]+(?:\s+[^\W\d_]+)?))"
                          rf"\s+(?:z|ze)\s+{_N}\W*$", re.I)


def fraction_of(text):
    """"Ile to jest trzy czwarte z 80?", "ćwierć z 200", "1/4 z 200" → the
    answer, or None (13 Oct probe: to the model)."""
    text = text.strip()
    # the number in words: "trzy czwarte z ośmiu" (24 Oct probe: to the model)
    w = re.search(r"\s(?:z|ze)\s+([^\W\d_]+(?:\s+[^\W\d_]+){0,3})\W*$", text)
    if w and all(x in _ONES or x in _SCALES for x in w.group(1).lower().split()):
        text = text[:w.start(1)] + str(_words_number(w.group(1).lower().split()))
    m = _FRACTION_OF.match(text)
    if not m:
        return None
    if m.group(1):
        a, b = int(m.group(1)), int(m.group(2))
        said = f"{a}/{b}"
    else:
        said = m.group(3).lower()
        if said not in _FRACTIONS:
            return None
        a, b = _FRACTIONS[said]
    if not b:
        return "Przez zero nie da się dzielić."
    n = float(m.group(4).replace(",", "."))
    value = n * a / b
    shown = round(value, 2)
    about = "około " if abs(shown - value) > 1e-9 else ""
    return f"{said[0].upper()}{said[1:]} z {_fmt(n)} to {about}{_fmt(shown)}."


def arithmetic(text):
    """The spoken answer to a bare arithmetic question, or None."""
    import time as _t
    frac = fraction_of(text)
    if frac:
        return frac
    for rx, said in _ORDERS:
        if rx.match(text.strip()):
            text = rx.sub(said, text.strip())
            break
    # "100 podzielić na 3" (13 Oct probe: to the model; "przez" worked)
    text = re.sub(r"\b(podzieli[ćc]|podzielone|dzielone|dzieli[ćc])\s+na\b", r"\1 przez", text,
                  flags=re.I)
    f = _FOLLOW.match(text.strip())
    if f and _last_sum["first"] is not None and _t.time() - _last_sum["t"] < 120:
        # "A razy 5?" right after "15 razy 4" → 15 razy 5 (7 Oct probe: the model
        # asked "jaka jest ta liczba A?")
        text = f"{_fmt(_last_sum['first'])} {f.group(1)}"
    toks = _tokens(text)
    if not toks or not any(isinstance(t, str) for t in toks):
        return None
    try:
        spoken, value = _evaluate(toks)
        _last_sum.update(first=next((t for t in toks if not isinstance(t, str)), None),
                         t=_t.time())
    except ZeroDivisionError:
        return "Przez zero nie da się dzielić."
    except (_Bad, OverflowError, ValueError):
        return None
    if abs(value) >= 1e15:
        exp = int(math.floor(math.log10(abs(value))))
        return (f"To ogromna liczba: około {_fmt(round(value / 10 ** exp, 2))} "
                f"razy dziesięć do potęgi {exp}.")
    shown = round(value, 2) if abs(value) >= 1 else round(value, 3)
    result = _fmt(shown)                    # "3,33", not "3,3333" — easier to hear
    about = "około " if abs(shown - value) > 1e-9 else ""
    if result.startswith("-"):
        result = "minus " + result[1:]
    return f"{spoken[0].upper()}{spoken[1:]} to {about}{result}."


# ── days until ────────────────────────────────────────────────────────────────

def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _school_end(y):
    """The school year ends on the last Friday of June (Polish rule)."""
    d = date(y, 6, 30)
    return d - timedelta((d.weekday() - 4) % 7)


# stem in "do …" → (date for a year, genitive "do X", nominative "dziś jest X")
_DAYS_OF = [
    # Easter first: "świąt wielkanocnych" must not be taken for Christmas
    (("wielkanocy", "wielkiej nocy", "świąt wielkanocnych", "swiat wielkanocnych"), _easter,
     "Wielkanocy", "Wielkanoc"),
    (("tłustego czwartku", "tlustego czwartku"), lambda y: _easter(y) - timedelta(52),
     "tłustego czwartku", "tłusty czwartek"),
    (("popielca", "środy popielcowej", "srody popielcowej"),
     lambda y: _easter(y) - timedelta(46), "Popielca", "Popielec"),
    (("zielonych świątek", "zielonych swiatek"), lambda y: _easter(y) + timedelta(49),
     "Zielonych Świątek", "Zielone Świątki"),
    (("bożego ciała", "bozego ciala"), lambda y: _easter(y) + timedelta(60),
     "Bożego Ciała", "Boże Ciało"),
    (("dnia babci",), lambda y: date(y, 1, 21), "Dnia Babci", "Dzień Babci"),
    (("dnia dziadka",), lambda y: date(y, 1, 22), "Dnia Dziadka", "Dzień Dziadka"),
    (("dnia nauczyciela",), lambda y: date(y, 10, 14), "Dnia Nauczyciela", "Dzień Nauczyciela"),
    (("dnia chłopaka", "dnia chlopaka"), lambda y: date(y, 9, 30), "Dnia Chłopaka",
     "Dzień Chłopaka"),
    (("święta niepodległości", "swieta niepodleglosci"), lambda y: date(y, 11, 11),
     "Święta Niepodległości", "Święto Niepodległości"),
    (("wigilii", "świąt", "swiat", "bożego narodzenia", "gwiazdki"),
     lambda y: date(y, 12, 24), "Wigilii", "Wigilia"),
    (("sylwestra",), lambda y: date(y, 12, 31), "Sylwestra", "Sylwester"),
    (("nowego roku",), lambda y: date(y, 1, 1), "Nowego Roku", "Nowy Rok"),
    (("walentynek",), lambda y: date(y, 2, 14), "Walentynek", "Walentynki"),
    (("dnia kobiet",), lambda y: date(y, 3, 8), "Dnia Kobiet", "Dzień Kobiet"),
    (("wiosny",), lambda y: date(y, 3, 21), "pierwszego dnia wiosny",
     "pierwszy dzień wiosny"),
    (("prima aprilis",), lambda y: date(y, 4, 1), "prima aprilis", "prima aprilis"),
    # "Ile dni do wakacji?" (13 Oct sweep: "jeszcze sporo… mogę policzyć dokładnie")
    (("końca roku szkolnego", "konca roku szkolnego", "zakończenia roku szkolnego",
      "zakonczenia roku szkolnego"), _school_end, "końca roku szkolnego",
     "koniec roku szkolnego"),
    (("wakacji", "wakacje", "wakacyj"), lambda y: _school_end(y) + timedelta(1), "wakacji",
     "pierwszy dzień wakacji"),
    (("dnia matki",), lambda y: date(y, 5, 26), "Dnia Matki", "Dzień Matki"),
    (("dnia dziecka",), lambda y: date(y, 6, 1), "Dnia Dziecka", "Dzień Dziecka"),
    (("lata",), lambda y: date(y, 6, 21), "lata", "pierwszy dzień lata"),
    (("dnia ojca",), lambda y: date(y, 6, 23), "Dnia Ojca", "Dzień Ojca"),
    (("jesieni",), lambda y: date(y, 9, 23), "jesieni", "pierwszy dzień jesieni"),
    (("halloween",), lambda y: date(y, 10, 31), "Halloween", "Halloween"),
    (("wszystkich świętych", "wszystkich swietych"), lambda y: date(y, 11, 1),
     "Wszystkich Świętych", "Wszystkich Świętych"),
    (("andrzejek",), lambda y: date(y, 11, 30), "andrzejek", "andrzejki"),
    (("mikołajek", "mikolajek", "mikołajków"), lambda y: date(y, 12, 6),
     "mikołajek", "mikołajki"),
    (("zimy",), lambda y: date(y, 12, 22), "zimy", "pierwszy dzień zimy"),
    # (13 Oct probe: "Ile dni do końca roku?" went to the model; after the
    # school year above, which starts the same)
    (("końca roku", "konca roku"), lambda y: date(y, 12, 31), "końca roku", "koniec roku"),
]
_WEEKDAYS = [("poniedziałku", "poniedzialku"), ("wtorku",), ("środy", "srody"),
             ("czwartku",), ("piątku", "piatku"), ("soboty",), ("niedzieli",)]
_WEEKDAY_NOM = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota",
                "niedziela"]
_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
               "sierpnia", "września", "października", "listopada", "grudnia"]
_ORD = {"pierwszego": 1, "drugiego": 2, "trzeciego": 3, "czwartego": 4, "piątego": 5,
        "szóstego": 6, "siódmego": 7, "ósmego": 8, "dziewiątego": 9, "dziesiątego": 10,
        "jedenastego": 11, "dwunastego": 12, "trzynastego": 13, "czternastego": 14,
        "piętnastego": 15, "szesnastego": 16, "siedemnastego": 17,
        "osiemnastego": 18, "dziewiętnastego": 19, "dwudziestego": 20,
        "trzydziestego": 30}
_UNTIL_FILL = {"ile", "jeszcze", "zostało", "zostalo", "zostanie", "dni", "dnia",
               "czasu", "do", "luna", "luno", "a", "powiedz", "mi", "już", "juz",
               "mamy", "jest", "tygodni", "tylko", "nam", "jak", "długo", "dlugo",
               "czekać", "czekac", "trzeba", "zostaje", "no", "hej", "dzisiaj", "dziś",
               "zostały", "zostal", "został"}


def _plural(n, one, few, many):
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _say_left(gen, days):
    verb = _plural(days, "został", "zostały", "zostało")
    out = f"Do {gen} {verb} {days} {'dzień' if days == 1 else 'dni'}"
    if days >= 14:
        w = round(days / 7)
        out += f", czyli około {w} {_plural(w, 'tygodnia', 'tygodni', 'tygodni')}"
    return out + "."


def _target(low, today):
    """(date, genitive, nominative) the question is about, or None; also
    returns the words the target used up."""
    m = re.search(r"\bdo (.+)$", low)
    if not m:
        return None
    after = m.group(1)
    for stems, when, gen, nom in _DAYS_OF:
        for s in stems:
            if after.startswith(s):
                d = when(today.year)
                if d < today:
                    d = when(today.year + 1)
                return d, gen, nom, s
    for s in ("końca miesiąca", "konca miesiaca"):
        if after.startswith(s):
            nxt = date(today.year + today.month // 12, today.month % 12 + 1, 1)
            return nxt - timedelta(1), "końca miesiąca", "koniec miesiąca", s
    if after.startswith("weekendu"):
        if today.weekday() >= 5:
            return "weekend", None, None, "weekendu"
        return today + timedelta(5 - today.weekday()), "weekendu", "weekend", "weekendu"
    for wd, stems in enumerate(_WEEKDAYS):
        for s in stems:
            if after.startswith(s):
                ahead = (wd - today.weekday()) % 7
                return (today + timedelta(ahead), _WEEKDAYS[wd][0], _WEEKDAY_NOM[wd], s)
    m = re.match(r"(\d{1,2})(?:\.|go)?\s+(\w+)", after)
    words = after.split()
    day = None
    if m:
        day, month_word = int(m.group(1)), m.group(2)
        used = m.group(0)
    elif words and words[0] in _ORD:
        day, k = _ORD[words[0]], 1
        if day in (20, 30) and len(words) > 1 and words[1] in _ORD and _ORD[words[1]] < 10:
            day += _ORD[words[1]]
            k = 2
        month_word = words[k] if len(words) > k else ""
        used = " ".join(words[:k + 1])
    if day is not None and month_word in _MONTHS_GEN:
        month = _MONTHS_GEN.index(month_word) + 1
        try:
            d = date(today.year, month, day)
            if d < today:
                d = date(today.year + 1, month, day)
        except ValueError:
            return None
        return d, f"{day} {month_word}", None, used
    return None


_WEEKDAY_Q = re.compile(
    r"\b(?:jaki\s+dzień\s+(?:tygodnia\s+)?|w\s+jakim\s+dniu\s+(?:tygodnia\s+)?|"
    r"w\s+jaki\s+dzień\s+(?:tygodnia\s+)?|"
    r"jaki\s+to\s+dzień\s+(?:tygodnia\s+)?)"
    r"(będzie|bedzie|jest|wypada|wypadnie|przypada|przypadnie|był|była|było|byl|byla|bylo|"
    r"wypadł|wypadła|wypadl|wypadla|przypadł|przypadła)\s+(?:w\s+)?(.+?)[?.!]*$",
    re.I)
_PAST = {"był", "była", "było", "byl", "byla", "bylo", "wypadł", "wypadła", "wypadl",
         "wypadla", "przypadł", "przypadła"}
_WD_ACC = ["poniedziałek", "wtorek", "środę", "czwartek", "piątek", "sobotę", "niedzielę"]


# plural names take a plural verb: "Andrzejki wypadają…" (13 Oct probe: "wypada")
_PLURAL_NOM = {"Zielone Świątki", "Walentynki", "andrzejki", "mikołajki"}


def _falls(label, past=False):
    plural = label in _PLURAL_NOM
    if past:
        return "były" if plural else None
    return "wypadają" if plural else "wypada"


def _on_day(d):
    """"w czwartek", but "we wtorek" (it was "wypada w wtorek")."""
    return ("we " if d.weekday() == 1 else "w ") + _WD_ACC[d.weekday()]


_WHEN_Q = re.compile(r"\bkiedy\s+(?:w\s+tym\s+roku\s+)?(?:jest|będzie|bedzie|wypada|"
                     r"wypadnie|są|sa|przypada|mamy|będą|beda)\s+(?:w\s+tym\s+roku\s+)?"
                     r"(.+?)(?:\s+w\s+tym\s+roku)?[?.!]*$", re.I)


_SINCE_Q = re.compile(r"\bile\s+(?:dni\s+|już\s+|juz\s+)*(?:minęło|minelo|upłynęło|uplynelo|"
                      r"jest|mamy)\s+(?:dni\s+)?od\s+(.+?)[?.!]*$", re.I)


def days_since(text, today=None):
    """"Ile dni minęło od 1 września?", "…od Wigilii?" → the count back to the
    last time that date was; None for anything else."""
    m = _SINCE_Q.search(text.lower())
    if not m:
        return None
    today = today or _today()
    what = m.group(1).strip()
    year_ago = date(today.year - 1, today.month, min(today.day, 28))
    hit = _target("do " + what, year_ago)       # the next one after a year ago…
    if hit is None or hit[0] == "weekend" or hit[2] in _WEEKDAY_NOM:
        return None
    d, gen, nom, used = hit
    if what.replace(used, "").strip():
        return None
    for stems, when, g, n in _DAYS_OF:           # …a holiday: its own date this year
        if g == gen:
            d = when(today.year)
            if d > today:
                d = when(today.year - 1)
            break
    else:
        try:
            d2 = d.replace(year=today.year)
        except ValueError:                       # 29 February
            d2 = d
        d = d2 if d2 <= today else d2.replace(year=today.year - 1)
    days = (today - d).days
    since = f"od {gen}"
    if days == 0:
        return "To dzisiaj!"
    weeks = f", czyli około {round(days / 7)} {_plural(round(days / 7), 'tygodnia', 'tygodni', 'tygodni')}" \
        if days >= 14 else ""
    verb = _plural(days, "minął", "minęły", "minęło")
    return (f"{since[0].upper()}{since[1:]} {verb} {days} "
            f"{_plural(days, 'dzień', 'dni', 'dni')}{weeks}.")


# unit stem → (kind, factor to the base unit, forms: 1 / 2–4 / 5+ / a fraction)
_UNITS = [
    ("milimetr", "len", 0.001, ("milimetr", "milimetry", "milimetrów", "milimetra")),
    ("centymetr", "len", 0.01, ("centymetr", "centymetry", "centymetrów", "centymetra")),
    ("kilometr", "len", 1000.0, ("kilometr", "kilometry", "kilometrów", "kilometra")),
    ("metr", "len", 1.0, ("metr", "metry", "metrów", "metra")),
    ("cal", "len", 0.0254, ("cal", "cale", "cali", "cala")),
    ("stopa", "len", 0.3048, ("stopa", "stopy", "stóp", "stopy")),
    ("stopy", "len", 0.3048, ("stopa", "stopy", "stóp", "stopy")),
    ("stóp", "len", 0.3048, ("stopa", "stopy", "stóp", "stopy")),
    ("jard", "len", 0.9144, ("jard", "jardy", "jardów", "jarda")),
    ("mil", "len", 1609.344, ("mila", "mile", "mil", "mili")),
    ("kilogram", "mass", 1000.0, ("kilogram", "kilogramy", "kilogramów", "kilograma")),
    ("dekagram", "mass", 10.0, ("dekagram", "dekagramy", "dekagramów", "dekagrama")),
    ("deko", "mass", 10.0, ("dekagram", "dekagramy", "dekagramów", "dekagrama")),
    ("gram", "mass", 1.0, ("gram", "gramy", "gramów", "grama")),
    ("funt", "mass", 453.59237, ("funt", "funty", "funtów", "funta")),
    ("uncj", "mass", 28.349523, ("uncja", "uncje", "uncji", "uncji")),
    ("mililitr", "vol", 0.001, ("mililitr", "mililitry", "mililitrów", "mililitra")),
    ("litr", "vol", 1.0, ("litr", "litry", "litrów", "litra")),
    ("galon", "vol", 3.785411784, ("galon", "galony", "galonów", "galona")),
    ("celsjusz", "temp", None, ("stopień Celsjusza", "stopnie Celsjusza", "stopni Celsjusza",
                                "stopnia Celsjusza")),
    ("fahrenheit", "temp", None, ("stopień Fahrenheita", "stopnie Fahrenheita",
                                  "stopni Fahrenheita", "stopnia Fahrenheita")),
]
_UNITS_BY_LEN = sorted(_UNITS, key=lambda u: -len(u[0]))   # "mililitr" before "mil"


def _unit_form(x, forms):
    if abs(x - round(x)) > 1e-9:
        return forms[3]                                    # "2,5 kilograma"
    return _plural(int(abs(round(x))), forms[0], forms[1], forms[2])


_CONVERT_Q = re.compile(r"\b(?:ile\s+(?:to\s+)?(?:jest\s+)?|zamień\s+|zamien\s+|przelicz\s+)(.+?)[?.!]*$",
                        re.I)


def _unit(word):
    w = word.lower()
    for stem, kind, factor, forms in _UNITS_BY_LEN:
        if w.startswith(stem):
            return stem, kind, factor, forms
    return None


def convert(text):
    """"Ile to cali 30 centymetrów?", "zamień 5 mil na kilometry", "ile to 20
    stopni Celsjusza w Fahrenheitach?" → exact; None for anything else."""
    m = _CONVERT_Q.search(text)
    if not m:
        return None
    words = re.findall(r"[\w,.]+", m.group(1).lower())
    num, src, dst = None, None, None
    for i, w in enumerate(words):
        n = w.replace(",", ".")
        if num is None and re.fullmatch(r"-?\d+(?:\.\d+)?", n):
            num = float(n)
            # the unit right after the number is the source ("30 centymetrów",
            # "20 stopni Celsjusza")
            for w2 in words[i + 1:i + 3]:
                u = _unit(w2)
                if u:
                    src = u
                    break
    if num is None or src is None:
        return None
    for w in words:
        u = _unit(w)
        if u and u[3] != src[3] and u[1] == src[1]:
            dst = u
            break
    if dst is None:
        return None
    if src[1] == "temp":
        value = num * 9 / 5 + 32 if src[0] == "celsjusz" else (num - 32) * 5 / 9
    else:
        value = num * src[2] / dst[2]
    shown = round(value, 2) if abs(value) >= 1 else round(value, 3)
    about = "około " if abs(shown - value) > 1e-9 else ""
    return (f"{_fmt(num)} {_unit_form(num, src[3])} to {about}{_fmt(shown)} "
            f"{_unit_form(shown, dst[3])}.")


def holiday_when(text, today=None):
    """"Kiedy jest Wielkanoc?", "kiedy wypada tłusty czwartek?" → the date,
    the weekday and how far; None for anything else. (Movable feasts are
    where a model guesses.)"""
    m = _WHEN_Q.search(text.lower())
    if not m:
        return None
    what = m.group(1).strip()
    today = today or _today()
    for stems, when, gen, nom in _DAYS_OF:
        if what == nom.lower() or what.startswith(nom.lower() + " "):
            d = when(today.year)
            if d < today:
                d = when(today.year + 1)
            days = (d - today).days
            year = f" {d.year}" if d.year != today.year else ""
            far = ("— to dzisiaj!" if days == 0 else "— już jutro." if days == 1 else
                   f"— za {days} dni.")
            return (f"{nom[0].upper()}{nom[1:]} {_falls(nom)} {d.day} {_MONTHS_GEN[d.month - 1]}"
                    f"{year}, {_on_day(d)} {far}")
    return None


def weekday_of(text, today=None):
    """"Jaki dzień tygodnia będzie 24 grudnia?", "w jaki dzień wypada Wigilia?"
    → "24 grudnia 2026 to czwartek." None when it isn't that."""
    # "Jaki był dzień tygodnia 13 października 2000?" — the verb first (13 Oct probe)
    low = re.sub(r"\bjaki\s+(był|będzie|bedzie|jest)\s+dzień(\s+tygodnia)?",
                 r"jaki dzień\2 \1", text.lower())
    m = _WEEKDAY_Q.search(low)
    if not m:
        return None
    today = today or _today()
    past = m.group(1).lower() in _PAST       # "jaki dzień był 1 stycznia?" (13 Oct probe)
    what = m.group(2).strip()
    hit = _target("do " + what, today)
    if hit is None:                        # a holiday said in the nominative
        for stems, when, gen, nom in _DAYS_OF:
            if what.startswith(nom.lower()):
                d = when(today.year)
                hit = (d if d >= today else when(today.year + 1), gen, nom, nom.lower())
                break
    if hit is None or hit[0] == "weekend" or hit[2] in _WEEKDAY_NOM:
        return None                        # "jaki dzień będzie w piątek?" — no question
    d, gen, nom, used = hit
    rest = what.replace(used, " ", 1)
    said_year = re.search(r"\b(1[89]\d\d|20\d\d|21\d\d)\b", rest)
    if re.search(r"[^\W\d_]", re.sub(r"\d+", " ", rest).replace("roku", "")):
        return None                        # more than a date: the model
    try:
        if said_year:                      # "24 grudnia 2030" — that year's, not the next
            d = d.replace(year=int(said_year.group(1)))
        elif past and d > today:           # "był 1 stycznia" — this year's, gone by
            d = d.replace(year=d.year - 1)
            if d > today:
                d = d.replace(year=d.year - 1)
    except ValueError:                     # 29 lutego in a year without it
        return None
    label = nom or f"{d.day} {_MONTHS_GEN[d.month - 1]}"
    year = f" {d.year}" if d.year != today.year else ""
    day = _WEEKDAY_NOM[d.weekday()]
    if d == today:
        return f"{label[0].upper()}{label[1:]} to dzisiaj — {day}."
    if d < today:
        verb = _falls(label, past=True) or ("była" if d.weekday() in (2, 5, 6) else "był")
        return f"{label[0].upper()}{label[1:]}{year} {verb} {day}."
    return f"{label[0].upper()}{label[1:]}{year} {_falls(label)} {_on_day(d)}."


def days_until(text, today=None):
    """The spoken answer to "ile dni do …?", or None."""
    low = " ".join(re.findall(r"[\w.]+", text.lower()))
    if not low.startswith("ile") and " ile " not in f" {low} ":
        return None
    if " do " not in f" {low} ":
        return None
    today = today or _today()
    hit = _target(low, today)
    if not hit:
        return None
    d, gen, nom, used = hit
    rest = low.replace(used, " ", 1)
    if any(w not in _UNTIL_FILL for w in re.findall(r"[^\W\d_]+", rest)):
        return None
    if d == "weekend":
        return "Przecież już jest weekend!"
    days = (d - today).days
    if days == 0:
        return f"Dziś jest {nom}!" if nom else "To dzisiaj!"
    if days == 1:
        return (f"{nom[0].upper()}{nom[1:]} jest już jutro!" if nom
                else "To już jutro!")
    return _say_left(gen, days)


def time_until(text, now=None):
    """"Ile zostało do siedemnastej?", "ile czasu do 17:30?" → the answer, or None."""
    import clockgame
    low = text.lower()
    m = re.search(r"\bile\b(?:\s+\w+){0,3}?\s+do\s+(?:godziny\s+)?(.+?)[?.!]*$", low)
    if not m or re.search(r"\b(dni|dnia|tygodni|urodzin|świąt|swiat|wigilii|końca|konca)\b",
                          low):
        return None
    target = m.group(1)
    if len(target.split()) > 4 or not re.match(r"[\dpdtcśsjoóg]", target):
        return None
    t = clockgame.parse(target)
    if t is None:
        return None
    h, mi = t
    # "do północy", "do dwunastej w nocy": 0:00, not noon (13 Oct probe: "Ile
    # minut do północy?" at 19:20 → "Do 12:00 zostało 16 godzin i 40 minut")
    midnight = h % 12 == 0 and mi == 0 and bool(
        re.search(r"p[óo]łno|w\s+nocy", target))
    if midnight:
        h = 0
    now = now or datetime.now()
    goal = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
    if goal <= now and h < 12 and not midnight:      # "do ósmej" in the evening: 20:00
        later = goal.replace(hour=h + 12)
        goal = later if later > now else goal
    if goal <= now:
        goal = goal + timedelta(days=1)
    mins = math.ceil((goal - now).total_seconds() / 60)    # a part of a minute is one
    hh, mm = divmod(mins, 60)
    parts = []
    if hh:
        parts.append(f"{hh} {_plural(hh, 'godzina', 'godziny', 'godzin')}")
    if mm or not parts:
        parts.append(f"{mm} {_plural(mm, 'minuta', 'minuty', 'minut')}")
    verb = _plural(hh if hh else mm, "został", "zostały", "zostało")
    if hh and mm:
        verb = _plural(hh, "została", "zostały", "zostało")
    when = "północy" if midnight else f"{goal.hour}:{goal.minute:02d}"
    return f"Do {when} {verb} {' i '.join(parts)}."


_CLOCK_CHANGE = re.compile(
    r"\b(?:zmian\w*\s+czasu|przestawi\w*\s+(?:zegar\w*|czas\w*)|przestawia\w*\s+zegar\w*|"
    r"zmienia\w*\s+(?:się\s+)?czas|zmieni\w*\s+(?:się\s+)?czas|cofa\w*\s+zegar\w*|"
    r"czas\w*\s+(?:zimow\w*|letni\w*)|przesuwa\w*\s+zegar\w*)", re.I)


def _last_sunday(y, month):
    d = date(y, month, 31)
    return d - timedelta((d.weekday() + 1) % 7)


def clock_change(text, today=None):
    """"Kiedy zmiana czasu?", "kiedy przestawiamy zegarki?" → the next one (13 Oct
    probe: to the model, which guesses). None when it isn't that question."""
    low = text.lower()
    if not _CLOCK_CHANGE.search(low) or not re.search(r"\b(?:kiedy|którego|ktorego|"
                                                      r"jak|czy|o\s+której)\b", low):
        return None
    today = today or _today()
    y = today.year
    changes = sorted([(_last_sunday(y, 3), "letni"), (_last_sunday(y, 10), "zimowy"),
                      (_last_sunday(y + 1, 3), "letni")])
    d, kind = next((d, k) for d, k in changes if d >= today)
    days = (d - today).days
    when = ("tej nocy" if days == 0 else "w nocy z soboty na niedzielę, "
            f"{d.day} {_MONTHS_GEN[d.month - 1]}{f' {d.year}' if d.year != y else ''}")
    how = ("o trzeciej cofamy zegarki na drugą — śpimy godzinę dłużej" if kind == "zimowy"
           else "o drugiej przestawiamy zegarki na trzecią — śpimy godzinę krócej")
    return f"Zmiana na czas {kind} jest {when}: {how}."


# ── the calendar itself (14 Oct probe: all to the model) ─────────────────────

_MONTHS_NOM = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec",
               "sierpień", "wrzesień", "październik", "listopad", "grudzień"]
_MONTH_STEMS = ["stycz", "lut", "mar", "kwie", "maj", "czerw", "lip", "sierp", "wrze",
                "październik|pazdziernik|październik", "listopad", "grud"]
_MONTH_LEN_Q = re.compile(r"^(?:luna,?\s+)?ile\s+(?:dni\s+)?(?:ma|liczy|trwa)\s+(?:dni\s+)?"
                          r"(?:ten\s+|obecny\s+)?(?:miesiąc\s+|miesiac\s+)?(\w+)(?:\s+(?:w\s+tym\s+roku|"
                          r"(?:w\s+)?(?:roku\s+)?(\d{4})))?(?:\s+dni)?\W*$", re.I)
_LEAP_Q = re.compile(r"\b(?:czy|jest)\s+(?:rok\s+)?(\d{4}|ten\s+rok|w\s+tym\s+roku|"
                     r"(?:przyszły|przyszly|następny|nastepny)\s+rok)\s+(?:rok\s+)?"
                     r"(?:jest\s+|będzie\s+|bedzie\s+|był\s+|byl\s+)?(?:rokiem\s+)?"
                     r"przestępn\w*|\bkiedy\s+(?:będzie\s+|bedzie\s+|jest\s+)?"
                     r"(?:następny\s+|nastepny\s+|najbliższy\s+|najblizszy\s+)?rok\s+przestępn\w*",
                     re.I)
_WEEK_NO_Q = re.compile(r"^(?:luna,?\s+)?(?:który|ktory|jaki)\s+(?:mamy|jest|to)\s+(?:teraz\s+|dziś\s+|"
                        r"dzis\s+)?(?:numer\s+)?tydzień(?:\s+roku)?\W*$|^(?:luna,?\s+)?(?:który|ktory|"
                        r"jaki)\s+(?:to\s+|jest\s+)?(?:numer\s+)?tygodnia\W*$", re.I)
_DAY_NO_Q = re.compile(r"^(?:luna,?\s+)?(?:który|ktory)\s+(?:dziś|dzis|dzisiaj|to|jest|mamy)\s+"
                       r"(?:jest\s+|mamy\s+)?(?:dziś\s+|dzis\s+|dzisiaj\s+)?dzień\s+roku\W*$", re.I)
_DAYS_AHEAD_Q = re.compile(r"^(?:luna,?\s+)?(?:jaki|jaka|który|ktory)\s+(?:dzień|dzien|data|"
                           r"dzień\s+tygodnia)\s+(?:będzie|bedzie|jest)\s+za\s+(.+?)\W*$", re.I)


def _leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _month_of(word):
    word = word.lower()
    for i, stem in enumerate(_MONTH_STEMS):
        if re.match(rf"(?:{stem})", word):
            return i + 1
    return None


# "Jutro piątek." / "Nieprawda, jutro jest czwartek." / "Dziś jest środa?" — a
# day said as a fact, checked (14 Oct 18:39: "Jutro piątek." → the model: "Tak,
# jutro jest piątek, 16 października" — on a Wednesday)
_DAY_CLAIM = re.compile(r"^(?:luna,?\s+)?(?:(?:nie|nieprawda|no|tak|a|ale|przecież|przeciez|czyli)\W+)*"
                        r"(dziś|dzis|dzisiaj|jutro|pojutrze|wczoraj)\s+(?:jest|będzie|bedzie|był|"
                        r"byl|była|byla|mamy|miałeś|wypada)?\s*(?:chyba\s+)?"
                        r"(poniedziałek|poniedzialek|wtorek|środa|sroda|środę|srode|czwartek|piątek|"
                        r"piatek|sobota|sobotę|sobote|niedziela|niedzielę|niedziele)"
                        r"(?:,?\s+(?:prawda|tak|nie|chyba))?\W*$", re.I)
_CLAIM_WD = {"poniedziałek": 0, "poniedzialek": 0, "wtorek": 1, "środa": 2, "sroda": 2,
             "środę": 2, "srode": 2, "czwartek": 3, "piątek": 4, "piatek": 4, "sobota": 5,
             "sobotę": 5, "sobote": 5, "niedziela": 6, "niedzielę": 6, "niedziele": 6}


def day_claim(text, today=None):
    """"Jutro piątek." → "Nie, jutro jest czwartek, 15 października." (or "Tak, …")."""
    m = _DAY_CLAIM.match((text or "").strip())
    if not m:
        return None
    today = today or _today()
    when = m.group(1).lower()
    k = {"wczoraj": -1, "jutro": 1, "pojutrze": 2}.get(when, 0)
    d = today + timedelta(k)
    verb = "był" if k < 0 else "będzie" if k > 1 else "jest"
    if k < 0 and d.weekday() in (2, 5, 6):
        verb = "była"                      # (środa, sobota, niedziela)
    word = {"dzis": "dziś", "dzisiaj": "dziś"}.get(when, when)
    yes = _CLAIM_WD[m.group(2).lower()] == d.weekday()
    return (f"{'Tak' if yes else 'Nie'}, {word} {verb} {_WEEKDAY_NOM[d.weekday()]}, "
            f"{d.day} {_MONTHS_GEN[d.month - 1]}.")


def calendar_answer(text, today=None):
    """"Ile dni ma luty?", "Czy 2028 jest przestępny?", "Który mamy tydzień?",
    "Który dziś dzień roku?", "Jaki dzień będzie za tydzień?" → the answer, or
    None."""
    import calendar
    today = today or _today()
    low = text.lower().strip()
    m = _MONTH_LEN_Q.match(low)
    if m and m.group(1) in ("miesiąc", "miesiac"):
        n = calendar.monthrange(today.year, today.month)[1]
        return f"{_MONTHS_NOM[today.month - 1].capitalize()} ma {n} dni."
    if m and (m.group(1) == "rok" or _month_of(m.group(1))):
        y = int(m.group(2)) if m.group(2) else today.year
        if m.group(1) == "rok":
            return f"Rok {y} ma {366 if _leap(y) else 365} dni."
        mo = _month_of(m.group(1))
        if not m.group(2) and mo < today.month and mo == 2:
            y += 1                                # "luty" in October: the next one
        n = calendar.monthrange(y, mo)[1]
        name = _MONTHS_NOM[mo - 1].capitalize()
        when = f" {y}" if m.group(2) or y != today.year else ""
        extra = " — to rok przestępny" if mo == 2 and n == 29 else ""
        return f"{name}{when} ma {n} dni{extra}."
    m = _LEAP_Q.search(low)
    if m:
        what = (m.group(1) or "").lower()
        if what.isdigit():
            y = int(what)
        elif what.startswith(("przyszły", "przyszly", "następny", "nastepny")):
            y = today.year + 1
        elif what:
            y = today.year
        else:                                     # "kiedy następny rok przestępny?"
            y = today.year + 1
            while not _leap(y):
                y += 1
            return f"Następny rok przestępny to {y}."
        past = y < today.year
        if _leap(y):
            return f"Tak, {y} {'był' if past else 'jest'} przestępny — luty ma wtedy 29 dni."
        nxt = y + 1
        while not _leap(nxt):
            nxt += 1
        return f"Nie, {y} {'nie był' if past else 'nie jest'} przestępny. Najbliższy po nim to {nxt}."
    if _WEEK_NO_Q.match(low):
        return f"Mamy tydzień numer {today.isocalendar()[1]}."
    if _DAY_NO_Q.match(low):
        n = today.timetuple().tm_yday
        left = (date(today.year, 12, 31) - today).days
        return (f"Dziś jest dzień numer {n}. Do końca roku "
                f"{'zostało' if left != 1 else 'został'} {left} {_plural(left, 'dzień', 'dni', 'dni')}.")
    m = _DAYS_AHEAD_Q.match(low)
    if m:
        span = m.group(1)
        k = {"tydzień": 7, "tydzien": 7, "dwa tygodnie": 14, "miesiąc": None,
             "jutro": 1, "pojutrze": 2}.get(span)
        if k is None:
            mm = re.match(r"(\w+(?:\s+\w+)?)\s+(dni|dzień|dzien|tygodnie|tygodni)$", span)
            n = number_in(mm.group(1)) if mm else None
            if not n or n > 3660:
                return None
            k = int(n) * (7 if mm.group(2).startswith("tygod") else 1)
        d = today + timedelta(k)
        year = f" {d.year}" if d.year != today.year else ""
        return (f"Za {span} będzie {_WEEKDAY_NOM[d.weekday()]}, "
                f"{d.day} {_MONTHS_GEN[d.month - 1]}{year}.")
    return None


def answer(text):
    # "za ile dni jest 24 grudnia?" — the same as "ile dni do 24 grudnia?"
    alt = re.sub(r"^(luna,?\s+)?za\s+ile\s+dni\s+(?:jest|będzie|bedzie|mamy|są|sa|wypada)\s+",
                 r"\1ile dni do ", text.strip(), flags=re.I)
    return (arithmetic(text) or days_until(alt) or time_until(text) or weekday_of(text)
            or holiday_when(text) or days_since(text) or convert(text)
            or clock_change(text) or calendar_answer(text) or day_claim(text))
