"""
clock.py — "która godzina?" and "jaki dziś dzień?" answered locally, in
proper spoken Polish ("Jest piętnasta dwadzieścia sześć.", "Dziś jest
niedziela, czwarty października."). The most frequent question doesn't need
a language model, and this answers at once and offline.

Only a bare question counts — "która godzina jest w Tokio?" still goes to
the model.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from config import LUNA_TIMEZONE

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception:
    _TZ = None

_HOURS = ["zero", "pierwsza", "druga", "trzecia", "czwarta", "piąta", "szósta",
          "siódma", "ósma", "dziewiąta", "dziesiąta", "jedenasta", "dwunasta",
          "trzynasta", "czternasta", "piętnasta", "szesnasta", "siedemnasta",
          "osiemnasta", "dziewiętnasta", "dwudziesta", "dwudziesta pierwsza",
          "dwudziesta druga", "dwudziesta trzecia"]
_UNITS = ["", "jeden", "dwa", "trzy", "cztery", "pięć", "sześć", "siedem", "osiem",
          "dziewięć", "dziesięć", "jedenaście", "dwanaście", "trzynaście",
          "czternaście", "piętnaście", "szesnaście", "siedemnaście", "osiemnaście",
          "dziewiętnaście"]
_TENS = {2: "dwadzieścia", 3: "trzydzieści", 4: "czterdzieści", 5: "pięćdziesiąt"}
_ORD = ["", "pierwszy", "drugi", "trzeci", "czwarty", "piąty", "szósty", "siódmy",
        "ósmy", "dziewiąty", "dziesiąty", "jedenasty", "dwunasty", "trzynasty",
        "czternasty", "piętnasty", "szesnasty", "siedemnasty", "osiemnasty",
        "dziewiętnasty", "dwudziesty"]
_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
           "sierpnia", "września", "października", "listopada", "grudnia"]
_DAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

_TIME_Q = ("która godzina", "która jest godzina", "jaka jest godzina", "jaka godzina",
           "która teraz godzina", "ktora godzina", "ktora jest godzina",
           "what time is it")
_DATE_Q = ("jaki dziś dzień", "jaki dzisiaj dzień", "jaki jest dzisiaj dzień",
           "jaki jest dziś dzień", "jaki mamy dzień", "którego dzisiaj", "którego dziś",
           "jaka jest data", "jaka jest dzisiaj data", "jaka dziś data",
           "what day is it", "what's the date")
# what may surround the bare question
_FILL = {"luna", "luno", "a", "powiedz", "mi", "proszę", "prosze", "teraz", "hej",
         "no", "to", "czy", "wiesz", "możesz", "mozesz", "jest", "mamy", "dziś",
         "dzisiaj", "is", "it", "now", "please",
         # a greeting before the question ("Cześć, która godzina?" went to the model)
         "cześć", "czesc", "siema", "hejka", "dzień", "dobry", "dobry", "wieczór",
         "dobranoc", "hello", "hi", "hey", "dzięki", "dzieki"}


def _minutes(m):
    if m < 20:
        return _UNITS[m]
    t, u = divmod(m, 10)
    return _TENS[t] + (" " + _UNITS[u] if u else "")


def _ordinal_day(d):
    if d <= 20:
        return _ORD[d]
    if d < 30:
        return "dwudziesty " + _ORD[d - 20]
    return "trzydziesty" + (" pierwszy" if d == 31 else "")


def spoken_time(now=None):
    now = now or (datetime.now(_TZ) if _TZ else datetime.now())
    h, m = now.hour, now.minute
    if m == 0:
        return f"Jest {_HOURS[h]}." if h else "Jest północ."
    return f"Jest {_HOURS[h]} {_minutes(m)}."


def hour_accusative(h, m):
    """7:30 → "siódmą trzydzieści", 6:05 → "szóstą zero pięć" ("na …")."""
    if h == 0 and m == 0:
        return "północ"
    hour = " ".join(w[:-1] + "ą" if w.endswith("a") else w for w in _HOURS[h].split())
    if m == 0:
        return hour
    return f"{hour} {'zero ' if m < 10 else ''}{_minutes(m)}"


def hour_locative(h, m):
    """17:00 → "siedemnastej", 7:30 → "siódmej trzydzieści" ("o …")."""
    if h == 0 and m == 0:
        return "północy"
    hour = " ".join(w[:-2] + "giej" if w.endswith("ga") else
                    w[:-1] + "ej" if w.endswith("a") else w for w in _HOURS[h].split())
    if m == 0:
        return hour
    return f"{hour} {'zero ' if m < 10 else ''}{_minutes(m)}"


def spoken_date(now=None):
    now = now or (datetime.now(_TZ) if _TZ else datetime.now())
    return (f"Dziś jest {_DAYS[now.weekday()]}, {_ordinal_day(now.day)} "
            f"{_MONTHS[now.month - 1]}.")


def _bare(low, phrases):
    hit = next((p for p in phrases if p in low), None)
    if not hit:
        return False
    rest = re.findall(r"\w+", low.replace(hit, " "))
    return all(w in _FILL for w in rest)


# "która godzina w Tokio?" — the place as said after "w" (locative), with the
# zone; exact, where a model guesses the offset and forgets summer time
_PLACES = {
    "nowym jorku": ("Nowym Jorku", "America/New_York"),
    "ameryce": ("Ameryce (w Nowym Jorku)", "America/New_York"),
    "stanach": ("Stanach (w Nowym Jorku)", "America/New_York"),
    "usa": ("USA (w Nowym Jorku)", "America/New_York"),
    "waszyngtonie": ("Waszyngtonie", "America/New_York"),
    "chicago": ("Chicago", "America/Chicago"),
    "los angeles": ("Los Angeles", "America/Los_Angeles"),
    "kalifornii": ("Kalifornii", "America/Los_Angeles"),
    "san francisco": ("San Francisco", "America/Los_Angeles"),
    "toronto": ("Toronto", "America/Toronto"),
    "kanadzie": ("Kanadzie (w Toronto)", "America/Toronto"),
    "meksyku": ("Meksyku", "America/Mexico_City"),
    "brazylii": ("Brazylii (w São Paulo)", "America/Sao_Paulo"),
    "rio": ("Rio de Janeiro", "America/Sao_Paulo"),
    "argentynie": ("Argentynie", "America/Argentina/Buenos_Aires"),
    "hawajach": ("na Hawajach", "Pacific/Honolulu"),
    "alasce": ("na Alasce", "America/Anchorage"),
    "londynie": ("Londynie", "Europe/London"),
    "anglii": ("Anglii", "Europe/London"),
    "wielkiej brytanii": ("Wielkiej Brytanii", "Europe/London"),
    "szkocji": ("Szkocji", "Europe/London"),
    "irlandii": ("Irlandii", "Europe/Dublin"),
    "dublinie": ("Dublinie", "Europe/Dublin"),
    "lizbonie": ("Lizbonie", "Europe/Lisbon"),
    "portugalii": ("Portugalii", "Europe/Lisbon"),
    "islandii": ("Islandii", "Atlantic/Reykjavik"),
    "paryżu": ("Paryżu", "Europe/Paris"),
    "francji": ("Francji", "Europe/Paris"),
    "berlinie": ("Berlinie", "Europe/Berlin"),
    "niemczech": ("Niemczech", "Europe/Berlin"),
    "hiszpanii": ("Hiszpanii", "Europe/Madrid"),
    "madrycie": ("Madrycie", "Europe/Madrid"),
    "włoszech": ("we Włoszech", "Europe/Rome"),
    "rzymie": ("Rzymie", "Europe/Rome"),
    "norwegii": ("Norwegii", "Europe/Oslo"),
    "szwecji": ("Szwecji", "Europe/Stockholm"),
    "grecji": ("Grecji", "Europe/Athens"),
    "atenach": ("Atenach", "Europe/Athens"),
    "turcji": ("Turcji", "Europe/Istanbul"),
    "stambule": ("Stambule", "Europe/Istanbul"),
    "ukrainie": ("na Ukrainie", "Europe/Kyiv"),
    "kijowie": ("Kijowie", "Europe/Kyiv"),
    "moskwie": ("Moskwie", "Europe/Moscow"),
    "rosji": ("Rosji (w Moskwie)", "Europe/Moscow"),
    "egipcie": ("Egipcie", "Africa/Cairo"),
    "kairze": ("Kairze", "Africa/Cairo"),
    "izraelu": ("Izraelu", "Asia/Jerusalem"),
    "dubaju": ("Dubaju", "Asia/Dubai"),
    "indiach": ("Indiach", "Asia/Kolkata"),
    "delhi": ("Delhi", "Asia/Kolkata"),
    "tajlandii": ("Tajlandii", "Asia/Bangkok"),
    "bangkoku": ("Bangkoku", "Asia/Bangkok"),
    "wietnamie": ("Wietnamie", "Asia/Ho_Chi_Minh"),
    "singapurze": ("Singapurze", "Asia/Singapore"),
    "chinach": ("Chinach", "Asia/Shanghai"),
    "pekinie": ("Pekinie", "Asia/Shanghai"),
    "hongkongu": ("Hongkongu", "Asia/Hong_Kong"),
    "filipinach": ("na Filipinach", "Asia/Manila"),
    "korei": ("Korei", "Asia/Seoul"),
    "seulu": ("Seulu", "Asia/Seoul"),
    "japonii": ("Japonii", "Asia/Tokyo"),
    "tokio": ("Tokio", "Asia/Tokyo"),
    "australii": ("Australii (w Sydney)", "Australia/Sydney"),
    "sydney": ("Sydney", "Australia/Sydney"),
    "nowej zelandii": ("Nowej Zelandii", "Pacific/Auckland"),
    "kenii": ("Kenii", "Africa/Nairobi"),
}
_WORLD_Q = re.compile(r"\b(?:któr\w*|ktor\w*|jak\w*|ile)\b.*\bgodzin\w*\b.*?\b(?:w|we|na)\s+"
                      r"(\w+(?:\s+\w+)?)", re.I)


def _hours_pl(x):
    if x != int(x):
        return f"{str(x).replace('.', ',')} godziny"
    x = int(x)
    return "godzinę" if x == 1 else f"{x} godziny" if x % 10 in (2, 3, 4) and \
        x % 100 not in (12, 13, 14) else f"{x} godzin"


def world_time(text, now=None):
    """"Która godzina w Tokio?" → "W Tokio jest teraz dwudziesta pierwsza
    piętnaście — 7 godzin później niż u nas." None when it isn't that."""
    m = _WORLD_Q.search(text.lower())
    if not m:
        return None
    words = m.group(1).split()
    hit = _PLACES.get(" ".join(words)) or _PLACES.get(words[0])
    if not hit:
        return None
    where, zone = hit
    try:
        tz = ZoneInfo(zone)
    except Exception:
        return None
    here = now or (datetime.now(_TZ) if _TZ else datetime.now().astimezone())
    there = here.astimezone(tz)
    diff = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600
    h, mi = there.hour, there.minute
    said = _HOURS[h] if mi == 0 else f"{_HOURS[h]} {_minutes(mi)}"
    if h == 0 and mi == 0:
        said = "północ"
    prep = "" if where.startswith(("na ", "we ")) else "w "
    out = f"{(prep + where)[0].upper()}{(prep + where)[1:]} jest teraz {said}"
    if diff == 0:
        out += " — tak samo jak u nas."
    else:
        out += f" — {_hours_pl(abs(diff))} {'później' if diff > 0 else 'wcześniej'} niż u nas."
    if there.date() > here.date():
        out = out[:-1] + ", już jutro."
    elif there.date() < here.date():
        out = out[:-1] + ", jeszcze wczoraj."
    return out


def answer(text):
    """The spoken answer to a bare time/date question, or None."""
    said = world_time(text)
    if said:
        return said
    low = text.lower()
    english = "what" in low
    if _bare(low, _TIME_Q):
        if english:
            now = datetime.now(_TZ) if _TZ else datetime.now()
            return f"It's {now.hour}:{now.minute:02d}."
        return spoken_time()
    if _bare(low, _DATE_Q):
        if english:
            now = datetime.now(_TZ) if _TZ else datetime.now()
            return now.strftime("It's %A, %B %d.")
        return spoken_date()
    return None
