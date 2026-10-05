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
        ("procent z", "%"), ("procent od", "%"), ("pierwiastek z", "√"),
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


def arithmetic(text):
    """The spoken answer to a bare arithmetic question, or None."""
    toks = _tokens(text)
    if not toks or not any(isinstance(t, str) for t in toks):
        return None
    try:
        spoken, value = _evaluate(toks)
    except ZeroDivisionError:
        return "Przez zero nie da się dzielić."
    except (_Bad, OverflowError, ValueError):
        return None
    if abs(value) >= 1e15:
        exp = int(math.floor(math.log10(abs(value))))
        return (f"To ogromna liczba: około {_fmt(round(value / 10 ** exp, 2))} "
                f"razy dziesięć do potęgi {exp}.")
    result = _fmt(value)
    if result.startswith("-"):
        result = "minus " + result[1:]
    return f"{spoken[0].upper()}{spoken[1:]} to {result}."


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
    r"(?:będzie|bedzie|jest|wypada|wypadnie|przypada|przypadnie)\s+(?:w\s+)?(.+?)[?.!]*$",
    re.I)
_WD_ACC = ["poniedziałek", "wtorek", "środę", "czwartek", "piątek", "sobotę", "niedzielę"]


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
    weeks = f", czyli około {round(days / 7)} {_plural(round(days / 7), 'tydzień', 'tygodnie', 'tygodni')}" \
        if days >= 14 else ""
    verb = _plural(days, "minął", "minęły", "minęło")
    return (f"{since[0].upper()}{since[1:]} {verb} {days} "
            f"{_plural(days, 'dzień', 'dni', 'dni')}{weeks}.")


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
            return (f"{nom[0].upper()}{nom[1:]} wypada {d.day} {_MONTHS_GEN[d.month - 1]}"
                    f"{year}, w {_WD_ACC[d.weekday()]} {far}")
    return None


def weekday_of(text, today=None):
    """"Jaki dzień tygodnia będzie 24 grudnia?", "w jaki dzień wypada Wigilia?"
    → "24 grudnia 2026 to czwartek." None when it isn't that."""
    m = _WEEKDAY_Q.search(text.lower())
    if not m:
        return None
    today = today or _today()
    what = m.group(1).strip()
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
    if re.search(r"[^\W\d_]", rest.replace("roku", "").replace(str(d.year), "")):
        return None                        # more than a date: the model
    label = nom or f"{d.day} {_MONTHS_GEN[d.month - 1]}"
    year = f" {d.year}" if d.year != today.year else ""
    day = _WEEKDAY_NOM[d.weekday()]
    if d == today:
        return f"{label[0].upper()}{label[1:]} to dzisiaj — {day}."
    return f"{label[0].upper()}{label[1:]}{year} wypada w {_WD_ACC[d.weekday()]}."


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
    now = now or datetime.now()
    goal = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
    if goal <= now and h < 12:                       # "do ósmej" in the evening: 20:00
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
    return f"Do {goal.hour}:{goal.minute:02d} {verb} {' i '.join(parts)}."


def answer(text):
    return (arithmetic(text) or days_until(text) or time_until(text) or weekday_of(text)
            or holiday_when(text) or days_since(text))
