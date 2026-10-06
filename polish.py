"""
polish.py — the safety net for Luna's grammar: she is female, and a model
slipping into masculine 1st-person forms ("zrobiłem", "żebym zaczął") is
corrected here. Pure, so it is tested (tests/test_local_logic.py).

It must never touch other words: on 5 Oct "-łem" → "-łam" turned "masłem"
(with butter) into "masłam" — only verb-like endings now.
"""

import re

# Safety net for the model slipping into masculine 1st-person forms.
# Irregular / high-frequency ones first, then the regular "-łem" → "-łam"
# and "-łbym" → "-łabym" endings.
_FEM_SPECIAL = {
    "mógłbym": "mogłabym", "mogłem": "mogłam", "poszedłem": "poszłam",
    "poszedłbym": "poszłabym", "szedłem": "szłam", "wziąłem": "wzięłam",
    "wziąłbym": "wzięłabym", "zacząłem": "zaczęłam", "zdjąłem": "zdjęłam",
    "jestem gotowy": "jestem gotowa", "jestem pewny": "jestem pewna",
    "jestem ciekawy": "jestem ciekawa", "jestem zmęczony": "jestem zmęczona",
    "jestem szczęśliwy": "jestem szczęśliwa", "jestem zadowolony": "jestem zadowolona",
    "byłbym": "byłabym", "chciałbym": "chciałabym", "wolałbym": "wolałabym",
    "powinienem": "powinnam", "mogłem": "mogłam",
    "zacząłbym": "zaczęłabym", "wziąłbym": "wzięłabym", "jadłem": "jadłam",
    "zjadłem": "zjadłam", "niosłem": "niosłam", "przyniosłem": "przyniosłam",
    "upadłem": "upadłam", "znalazłem": "znalazłam", "usiadłem": "usiadłam",
    "przeczytałbym": "przeczytałabym", "byłem gotowy": "byłam gotowa",
    "byłem pewny": "byłam pewna", "byłem ciekawy": "byłam ciekawa",
}
_FEM_SPECIAL_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _FEM_SPECIAL),
                                                    key=len, reverse=True)) + r")\b",
                             re.IGNORECASE)
# only after a, e, i, y, u: verbs ("zrobiłem", "czytałem"), never nouns in the
# instrumental ("masłem" became "masłam", "stołem", "kołem", "mydłem")
_FEM_ENDINGS_RE = re.compile(r"\b(\w+?[aeiyu])(łem|łbym)\b")
# "Chcesz, żebym zaczął…?" — the past form after żebym / abym / bym
_FEM_BYM_RE = re.compile(r"\b(żebym|zebym|abym|bym)(\s+(?:się\s+|ci\s+|go\s+|to\s+)?)(\w+ł)\b",
                         re.IGNORECASE)
_FEM_PAST = {"mógł": "mogła", "poszedł": "poszła", "szedł": "szła", "przyszedł": "przyszła",
             "wyszedł": "wyszła", "niósł": "niosła", "przyniósł": "przyniosła"}


def _fem_past(word):
    """A masculine past form → feminine: zaczął → zaczęła, zrobił → zrobiła."""
    low = word.lower()
    if low in _FEM_PAST:
        return _FEM_PAST[low]
    if low.endswith("ął"):
        return word[:-2] + "ęła"
    return word + "a"


def feminize(text):
    """Turn masculine 1st-person forms into feminine ones ("zrobiłem" →
    "zrobiłam", "chciałbym" → "chciałabym"). Only touches endings that are
    unambiguous 1st-person masculine in Polish."""
    def special(m):
        src = m.group(1); rep = _FEM_SPECIAL[src.lower()]
        return rep.capitalize() if src[0].isupper() else rep
    text = _FEM_SPECIAL_RE.sub(special, text)
    text = _FEM_ENDINGS_RE.sub(lambda m: m.group(1) + ("łam" if m.group(2) == "łem"
                                                       else "łabym"), text)
    text = _FEM_BYM_RE.sub(lambda m: m.group(1) + m.group(2) + _fem_past(m.group(3)), text)
    return text


