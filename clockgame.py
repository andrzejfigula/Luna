"""
clockgame.py — reading an analogue clock, for a child.

"Pobawmy się w zegar" / "naucz mnie zegara": a clock face with hands on her
screen (robot_face.py, overlay "clockface"), "Która godzina jest na zegarze?",
and the answer in any way a Polish child says it:

  "siódma trzydzieści", "wpół do ósmej", "kwadrans po siódmej",
  "za piętnaście ósma", "za kwadrans ósma", "dziesięć po siódmej",
  "dwadzieścia przed ósmą", "7:30", "siódma", "dziewiętnasta trzydzieści"

The quiz engine (quiz.py, kind "clock") asks and scores; this module turns
words into (hour, minute) and makes the questions.
"""

import random
import re

# hour as said: nominative ("siódma"), and genitive/locative ("siódmej")
_NOM = {"pierwsza": 1, "druga": 2, "trzecia": 3, "czwarta": 4, "piąta": 5, "szósta": 6,
        "siódma": 7, "ósma": 8, "dziewiąta": 9, "dziesiąta": 10, "jedenasta": 11,
        "dwunasta": 12, "trzynasta": 13, "czternasta": 14, "piętnasta": 15,
        "szesnasta": 16, "siedemnasta": 17, "osiemnasta": 18, "dziewiętnasta": 19,
        "dwudziesta": 20, "północ": 12, "południe": 12}
_LOC = {"pierwszej": 1, "drugiej": 2, "trzeciej": 3, "czwartej": 4, "piątej": 5,
        "szóstej": 6, "siódmej": 7, "ósmej": 8, "dziewiątej": 9, "dziesiątej": 10,
        "jedenastej": 11, "dwunastej": 12, "trzynastej": 13, "czternastej": 14,
        "piętnastej": 15, "szesnastej": 16, "siedemnastej": 17, "osiemnastej": 18,
        "dziewiętnastej": 19, "dwudziestej": 20, "północy": 12, "południa": 12}
_ACC = {k[:-1] + "ą": v for k, v in _NOM.items() if k.endswith("a")}   # "przed ósmą"
_UNITS = {"pierwsza": 1, "druga": 2, "trzecia": 3, "pierwszej": 1, "drugiej": 2,
          "trzeciej": 3, "pierwszą": 1, "drugą": 2, "trzecią": 3}


def _hour_at(words, i):
    """(hour, words used) for the hour word(s) at i: "dwudziesta pierwsza" too."""
    if i >= len(words):
        return None, 0
    w = words[i]
    for table in (_NOM, _LOC, _ACC):
        if w in table:
            h = table[w]
            if h == 20 and i + 1 < len(words) and words[i + 1] in _UNITS:
                return 20 + _UNITS[words[i + 1]], 2
            return h, 1
    if w.isdigit() and 0 <= int(w) <= 24:
        return int(w), 1
    return None, 0


def _minutes_at(words, i):
    """(minutes, words used) for "trzydzieści", "piętnaście", "kwadrans", "15"…"""
    import calc
    if i >= len(words):
        return None, 0
    if words[i] == "kwadrans":
        return 15, 1
    if words[i].isdigit():
        return int(words[i]), 1
    j = i
    while j < len(words) and words[j] in calc._ONES:
        j += 1
    if j > i:
        n = calc._words_number(words[i:j])
        return (n, j - i) if 0 <= n < 60 else (None, 0)
    return None, 0


def parse(text):
    """(hour 0-23, minute) from a spoken time, or None."""
    low = text.lower()
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", low)
    if m:
        return int(m.group(1)) % 24, int(m.group(2))
    words = re.findall(r"[a-ząćęłńóśźż0-9]+", low)
    for i, w in enumerate(words):
        if w in ("wpół", "wpol") and i + 2 < len(words) and words[i + 1] == "do":
            h, _ = _hour_at(words, i + 2)                   # wpół do ósmej = 7:30
            if h is not None:
                return (h - 1) % 24, 30
        if w == "za":                                       # za piętnaście ósma
            mins, k = _minutes_at(words, i + 1)
            if mins:
                h, _ = _hour_at(words, i + 1 + k)
                if h is not None:
                    return (h - 1) % 24, 60 - mins
        if w in ("po", "przed") and i > 0:                  # dziesięć po siódmej
            mins, _ = _minutes_at(words, i - 1)
            if mins is None and i > 1:
                mins, _ = _minutes_at(words, i - 2)
            h, _ = _hour_at(words, i + 1)
            if mins and h is not None:
                return (h % 24, mins) if w == "po" else ((h - 1) % 24, 60 - mins)
    for i in range(len(words)):                             # siódma trzydzieści
        h, k = _hour_at(words, i)
        if h is not None and not words[i].isdigit():
            mins, _ = _minutes_at(words, i + k)
            if words[i + k:i + k + 1] == ["zero"] and i + k + 1 < len(words):
                mins, _ = _minutes_at(words, i + k + 1)     # siódma zero pięć
            return h % 24, mins or 0
    m = re.search(r"\b(\d{1,2})\s+(\d{1,2})\b", low)         # "7 30"
    if m and int(m.group(2)) < 60:
        return int(m.group(1)) % 24, int(m.group(2))
    m = re.search(r"\b(\d{1,2})\b", low)
    if m and int(m.group(1)) <= 24:
        return int(m.group(1)) % 24, 0
    return None


def same(said, want):
    """On a clock 7:30 and 19:30 look the same."""
    return said is not None and said[0] % 12 == want[0] % 12 and said[1] == want[1]


def question(seen, level=1):
    """A time to show: full and half hours first, then quarters, then fives."""
    for _ in range(30):
        h = random.randint(1, 12)
        m = random.choice([0, 30] if level == 0 else
                          [0, 15, 30, 45] if level == 1 else list(range(0, 60, 5)))
        if (h, m) not in seen:
            return h, m
    return h, m


def say(h, m):
    """How she says it back: "wpół do ósmej, czyli siódma trzydzieści"."""
    import clock
    h12 = h % 12 or 12
    hour = clock._HOURS[h12]
    if m == 0:
        return f"{hour}"
    plain = f"{hour} {clock._minutes(m)}"
    nxt = (h12 % 12) + 1
    loc = {v: k for k, v in _LOC.items() if v <= 12 and k not in ("północy", "południa")}
    if m == 30:
        return f"wpół do {loc[nxt]}, czyli {plain}"
    if m == 15:
        return f"kwadrans po {loc[h12]}, czyli {plain}"
    if m == 45:
        return f"za kwadrans {clock._HOURS[nxt]}, czyli {plain}"
    return plain
