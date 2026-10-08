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
                    r"przypomn|zapis|ustaw|puści|pusci|skreśl|skresl|usun)\w*[^.!?]*\?|"
                    # "Mogę za to włączyć szum deszczu, jeśli chcesz." / "Mogę włączyć…?"
                    # (7 Oct probe: an offer like this came with the command attached)
                    r"\bmogę\b[^.!?]*\b(?:dopis|doda|włącz|wlacz|nastaw|przypomn|zapis|ustaw|"
                    r"puści|pusci|skreśl|skresl|usun)\w*[^.!?]*(?:\?|\b(?:jeśli|jeżeli|jesli)\s+"
                    r"(?:chcesz|zechcesz|wolisz))|"
                    # "Jeśli chcesz, mogę to od razu skreślić." (8 Oct: said after
                    # the milk was already crossed off)
                    r"\b(?:jeśli|jeżeli|jesli)\s+(?:chcesz|zechcesz|wolisz)\W+(?:to\s+)?mogę\b"
                    r"[^.!?]*\b(?:dopis|doda|włącz|wlacz|nastaw|przypomn|zapis|ustaw|puści|"
                    r"pusci|skreśl|skresl|usun)", re.I)
_DONE_VERB = (r"dodałam|dopisałam|włączam|wlaczam|nastawiam|nastawiłam|ustawiam|ustawiłam|"
              r"zapisałam|przypomnę|skreśliłam|usunęłam|puszczam|gotowe|dopisuję|dodaję|"
              r"zapisuję|usuwam|skreślam")
_DONE = re.compile(rf"\b(?:{_DONE_VERB}|jasne)\b", re.I)
# "dorzuciłabym jajka…" / "można dorzucić ser" / "dorzuć jajka" — ideas asked
# for ("Wymyśl, co kupić"), not a list change (8 Oct probe: 3 of 4 times the
# items went straight onto the list). Opens with "Jasne —" too, so only a real
# done-verb says otherwise.
_SUGGEST = re.compile(r"\b(?:dorzuci|dopisa|doda|kupi|wzię)\w*(?:łabym|łbym)\b|"
                      r"\bmożna\b[^.!?]*\b(?:dorzucić|dodać|dopisać|kupić|wziąć)\b|"
                      r"\bdorzuć\b", re.I)
_DONE_ONLY = re.compile(rf"\b(?:{_DONE_VERB})\b", re.I)


_PROMISE = re.compile(r"(?<!nie )\bprzypomnę\b(?!\s+sobie)", re.I)


def empty_promise(reply, actions):
    """"Dobrze, przypomnę ci o tym, jeśli chcesz." with no action at all —
    they hear a promise and nothing would ring (the prompt forbids it, and
    the model still said it in 2 of 5 tries). A reply that already asks
    ("…o której?") is fine."""
    return bool(_PROMISE.search(reply or "")) and not actions and "?" not in (reply or "")


_ONES = ["", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem", "dziewięć"]
_TEENS = ["dziesięć", "jedenaście", "dwanaście", "trzynaście", "czternaście", "piętnaście",
          "szesnaście", "siedemnaście", "osiemnaście", "dziewiętnaście"]
_TENS = ["", "", "dwadzieścia", "trzydzieści", "czterdzieści", "pięćdziesiąt",
         "sześćdziesiąt", "siedemdziesiąt", "osiemdziesiąt", "dziewięćdziesiąt"]
_HUNDREDS = ["", "sto", "dwieście", "trzysta", "czterysta", "pięćset", "sześćset",
             "siedemset", "osiemset", "dziewięćset"]
_SCALES = [("", "", ""), ("tysiąc", "tysiące", "tysięcy"),
           ("milion", "miliony", "milionów"), ("miliard", "miliardy", "miliardów")]


def _below_1000(n):
    h, rest = divmod(n, 100)
    t, o = divmod(rest, 10)
    words = [_HUNDREDS[h]]
    words += [_TEENS[o]] if t == 1 else [_TENS[t], _ONES[o]]
    return " ".join(w for w in words if w)


def number_words(n):
    """1234567 → "milion dwieście trzydzieści cztery tysiące pięćset
    sześćdziesiąt siedem" (nominative)."""
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + number_words(-n)
    parts, i = [], 0
    while n and i < len(_SCALES):
        n, chunk = divmod(n, 1000)
        if chunk:
            one, few, many = _SCALES[i]
            if i == 0:
                parts.append(_below_1000(chunk))
            elif chunk == 1:
                parts.append(one)
            else:
                last2, last = chunk % 100, chunk % 10
                form = few if last in (2, 3, 4) and last2 not in (12, 13, 14) else many
                parts.append(f"{_below_1000(chunk)} {form}")
        i += 1
    return " ".join(reversed([p for p in parts if p]))


# (a full stop after it is the end of a sentence, not a decimal: "…to 7006652.")
_BIG = re.compile(r"(?<![\d,.:/])(\d{4,12})(?!\d)(?![,.:/]\d)")


_ABBR = [(re.compile(r"\bnp\.\s*", re.I), "na przykład "),
         (re.compile(r"\bok\.\s*(?=\d)", re.I), "około "),
         (re.compile(r"\bitp\.", re.I), "i tak dalej"),
         (re.compile(r"\bitd\.", re.I), "i tak dalej"),
         (re.compile(r"\btj\.\s*", re.I), "to jest "),
         (re.compile(r"\bgodz\.\s*", re.I), "godzina ")]
_FRACTIONS = [(re.compile(r"(?<![\d/])(?:1/2|½)(?![\d/])"), "pół"),
              (re.compile(r"(?<![\d/])(?:1/4|¼)(?![\d/])"), "ćwierć"),
              (re.compile(r"(?<![\d/])(?:3/4|¾)(?![\d/])"), "trzy czwarte"),
              (re.compile(r"(?<![\d/])1/3(?![\d/])"), "jedna trzecia"),
              (re.compile(r"(?<![\d/])2/3(?![\d/])"), "dwie trzecie")]
_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
_TEMP = re.compile(r"(-?\d{1,3})\s*°\s*C?")
_DATE = re.compile(r"(?<![\d.,])([0-3]?\d)\.([01]\d)(?:\.(\d{4}))?(?![\d,])")


def _ord_gen(word):
    """"piętnasty" → "piętnastego", "trzeci" → "trzeciego"."""
    return " ".join(w[:-1] + "ego" if w.endswith("y") else w + "ego" if w.endswith("i") else w
                    for w in word.split())


def _spoken_forms(text):
    """What the voice reads badly (8 Oct round trip, nothing played): "Jest
    12:30." came out in English, "22°C" garbled, "Np." as letters, "15.11" as
    "piętnastego piętnastego". Written out in Polish instead."""
    import clock
    for rx, rep in _ABBR:
        text = rx.sub(rep, text)
    # recipe fractions: "1/2 szklanki" came back "jedną poora szklanki"
    for rx, rep in _FRACTIONS:
        text = rx.sub(rep, text)

    def time_(m):
        h, mi = int(m.group(1)), int(m.group(2))
        before = text[max(0, m.start() - 4):m.start()].lower()
        if re.search(r"\b(?:o|od|do|po|przed)\s+$", before):
            return clock.hour_locative(h, mi)        # "o dziewiątej", "do siedemnastej"
        if re.search(r"\b(?:na|za)\s+$", before):
            return clock.hour_accusative(h, mi)      # "na siódmą trzydzieści"
        if h == 0 and mi == 0:
            return "północ"
        return clock._HOURS[h] + ("" if mi == 0 else
                                  f" {'zero ' if mi < 10 else ''}{clock._minutes(mi)}")
    text = _TIME.sub(time_, text)

    def temp(m):
        n = int(m.group(1))
        last, last2 = abs(n) % 10, abs(n) % 100
        unit = ("stopień" if abs(n) == 1 else "stopnie"
                if last in (2, 3, 4) and last2 not in (12, 13, 14) else "stopni")
        return f"{number_words(n)} {unit}"
    text = _TEMP.sub(temp, text)

    def date(m):
        d, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        out = f"{_ord_gen(clock._ordinal_day(d))} {clock._MONTHS[mo - 1]}"
        return out + (f" {m.group(3)}" if m.group(3) else "")
    return _DATE.sub(date, text)


def spoken_numbers(text):
    """Long integers in words for the voice: "7006652" was read digit by digit
    or garbled ("osiem sześć czterysta" for 86400 — 8 Oct check). Years,
    decimals, phone numbers stay as they are; times, temperatures, dates and
    abbreviations are written out (_spoken_forms)."""
    text = _spoken_forms(text or "")

    def words(m):
        before = text[max(0, m.start() - 16):m.start()].lower()
        digits = m.group(1)
        if re.search(r"\b(?:tel|telefon\w*|numer\w*|nr|pin|kod\w*)\b\.?\s*:?\s*$", before) or (
                len(digits) == 9 and digits[0] in "45678"):
            return digits                     # a phone number / code: as digits
        if len(digits) == 4 and 1900 <= int(digits) <= 2099:
            return digits                     # a year: the voice reads those well
        # (four digits too: "Liczba 1234" came back as "dwanaście trzy cztery")
        return number_words(int(digits))
    return _BIG.sub(words, text)


def offer_only(reply):
    """The reply offers to do something ("Może dopiszmy warzywa?", "Chcesz,
    żebym nastawiła minutnik?") and confirms nothing — then any action the
    model attached is premature."""
    reply = reply or ""
    if _SUGGEST.search(reply) and not _DONE_ONLY.search(reply):
        return True
    return bool(_OFFER.search(reply)) and not _DONE.search(reply)


_EN = {"the", "a", "an", "is", "are", "what", "how", "can", "you", "me", "my", "to", "for",
        "set", "add", "turn", "on", "off", "tell", "please", "it", "do", "does", "time",
        "timer", "list", "radio", "weather", "minutes", "joke", "play", "in", "of", "and",
        # "Play some music" was answered in Polish (8 Oct sweep): more everyday words
        "some", "music", "show", "who", "where", "when", "why", "your", "i'm", "this",
        "that", "there", "be", "have", "will", "would", "could", "good", "morning",
        "night", "thanks", "thank", "hello", "hi", "open", "stop", "start", "today",
        "tomorrow", "give", "need", "want", "like", "let's", "us", "we", "it's", "what's",
        "song", "story", "cat", "dog", "with", "about", "know", "say", "minute", "hour"}


def looks_english(text):
    """3+ words, no Polish letters, enough common English words — and one that
    isn't also Polish ("A to co?" is Polish: a / to / on / do / no)."""
    low = (text or "").lower()
    words = re.findall(r"[a-ząćęłńóśźż']+", low)
    if len(words) < 3 or re.search(r"[ąćęłńóśźż]", low):
        return False
    if sum(w in _EN for w in words) < max(2, len(words) // 3):
        return False
    return any(w in _EN and w not in ("a", "to", "on", "do", "me", "no") for w in words)


_SECRET = re.compile(r"\bnie\s+(?:mów|mow|zdradzaj|wygadaj|wspominaj|pisnij)"
                     # "…tylko jej nie mów", "nie mów Mai" — not "nie mów tak szybko"
                     r"(?:\s+(?!tak\b|tyle\b|szybko|wolno|głośn|glosn|ciszej|cicho|po\b)\w+){0,3}"
                     r"\s*(?:[.!,?]|$)|\bto\s+(?:jest\s+)?(?:tajemnica|sekret|niespodzianka)\b|"
                     r"\b(?:tylko\s+)?między\s+nami\b|\bw\s+tajemnicy\b|\bdon'?t\s+tell\b|"
                     r"\bit'?s\s+a\s+(?:secret|surprise)\b", re.I)


def is_secret(text):
    """"…tylko jej nie mów", "to niespodzianka", "między nami" — what follows
    is not to be passed on (8 Oct sweep: Emilka asked and heard about her
    own birthday earrings)."""
    return bool(_SECRET.search(text or ""))
