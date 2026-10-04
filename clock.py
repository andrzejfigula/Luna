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
         "dzisiaj", "is", "it", "now", "please"}


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


def answer(text):
    """The spoken answer to a bare time/date question, or None."""
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
