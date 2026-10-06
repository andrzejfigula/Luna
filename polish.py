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




# "Co chciałbyś przeczytać?" to someone she doesn't recognise (6 Oct: most
# likely Maja) — the conditional "you" forms guess a gender; the plain present
# says the same without guessing
_NEUTRAL_YOU = {"chciałbyś": "chcesz", "chciałabyś": "chcesz", "mógłbyś": "możesz",
                "mogłabyś": "możesz", "wolałbyś": "wolisz", "wolałabyś": "wolisz"}
_NEUTRAL_YOU_RE = re.compile(r"\b(" + "|".join(_NEUTRAL_YOU) + r")\b", re.I)


def neutral_you(text):
    """Gender-free "you" for an unrecognised listener (only forms that map
    cleanly onto the present tense)."""
    def swap(m):
        w = _NEUTRAL_YOU[m.group(1).lower()]
        return w.capitalize() if m.group(1)[0].isupper() else w
    return _NEUTRAL_YOU_RE.sub(swap, text or "")


_OFFER = re.compile(r"(?:chcesz|może|moze|czy|mam)\b[^.!?]*\b(?:dopis|doda|włącz|wlacz|nastaw|"
                    r"przypomn|zapis|ustaw|puści|pusci|skreśl|skresl|usun)\w*[^.!?]*\?", re.I)
_DONE = re.compile(r"\b(?:dodałam|dopisałam|włączam|wlaczam|nastawiam|nastawiłam|ustawiam|"
                   r"ustawiłam|zapisałam|przypomnę|skreśliłam|usunęłam|puszczam|gotowe|jasne)\b",
                   re.I)


_PROMISE = re.compile(r"(?<!nie )\bprzypomnę\b(?!\s+sobie)", re.I)


def empty_promise(reply, actions):
    """"Dobrze, przypomnę ci o tym, jeśli chcesz." with no action at all —
    they hear a promise and nothing would ring (the prompt forbids it, and
    the model still said it in 2 of 5 tries). A reply that already asks
    ("…o której?") is fine."""
    return bool(_PROMISE.search(reply or "")) and not actions and "?" not in (reply or "")


def offer_only(reply):
    """The reply offers to do something ("Może dopiszmy warzywa?", "Chcesz,
    żebym nastawiła minutnik?") and confirms nothing — then any action the
    model attached is premature."""
    return bool(_OFFER.search(reply or "")) and not _DONE.search(reply or "")
