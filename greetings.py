"""
greetings.py — her short hellos: back to a wave, "welcome back", and the
fixed hello when the model can't be reached.

17 Oct, Andrzej: "more greetings than just «miło cię widzieć»" — a wave got
one of four phrases and never a name. Now: by name when she knows the face
("Hej, Maju!"), by the time of day and the day of the week, by how long
they were away, and never one of the last few again.

(Without gender: she can't always tell who she greets — no "wróciłeś".
No questions in a wave's hello: the answer would need "Luna".)
"""

import random
import time

# ── back to a wave ────────────────────────────────────────────────────────────
WAVE = ["Cześć!", "Hej, hej!", "Hejka!", "O, cześć!", "Siemka!", "Halo, halo!",
        "Cześć, cześć!", "No hej!", "Witaj!", "Macham do ciebie!", "O, ktoś mi macha! Cześć!",
        "Hej! Miło cię widzieć!", "Ahoj!", "Hej, tu Luna!", "Czołem!",
        "Cześć! Fajnie, że jesteś."]
WAVE_NAMED = ["Cześć, {v}!", "Hej, {v}!", "O, {v}! Cześć!", "Hejka, {v}!", "Hej, hej, {v}!",
              "Siemka, {v}!", "Witaj, {v}!", "Miło cię widzieć, {v}!", "{V}! Macham!",
              "O, {v}! Hej!", "Czołem, {v}!", "{V}, cześć! Fajnie, że jesteś."]
WAVE_CHILD = ["Hej, {v}! Piątka!", "Cześć, {v}! Macham najmocniej, jak umiem!",
              "{V}! Hejka, hejka!", "O, {v}! Super, że jesteś!"]
WAVE_MORNING = ["Dzień dobry!", "Dobry!", "Dzień dobry, dzień dobry!"]
WAVE_EVENING = ["Dobry wieczór!", "Wieczorne cześć!"]
WAVE_NIGHT = ["Cicho, cicho — cześć!", "Pst… cześć!"]

# ── someone back after a while, or the hello when the model is away ──────────
MORNING = ["Dzień dobry!", "O, dzień dobry! Jak się spało?", "Dobry! Zaczynamy dzień?",
           "Dzień dobry! Pobudka zaliczona.", "Dzień dobry! Gotowi na dzisiaj?"]
DAY = ["O, jesteś!", "Hej, jesteś z powrotem!", "Cześć! Tęskniłam trochę.",
       "O, cześć! Dobrze cię znowu widzieć.", "Hej! Czekałam na ciebie.",
       "Witaj z powrotem!", "Cześć! Co słychać?"]
EVENING = ["Dobry wieczór!", "O, jesteś. Jak minął dzień?", "Dobry wieczór! Już po pracy?",
           "Hej! Wieczór — czas na coś miłego.", "Cześć! Jak tam dzień?"]
NIGHT = ["Jeszcze nie śpisz?", "O, cześć. Późno już.", "Pst… cześć. Ja już prawie śpię.",
         "Hej, nocny marku!"]
FIRST_TODAY = ["Dzień dobry! Pierwszy raz dziś cię widzę.", "O, cześć! Czekałam na ciebie.",
               "Hej! Pierwsze dzisiejsze cześć jest dla ciebie.",
               "Witaj! Dobrze, że jesteś."]
SHORT_AWAY = ["O, już jesteś!", "Szybki powrót!", "I znowu cześć!", "Hop, jesteś z powrotem!"]
LONG_AWAY = ["Dawno cię nie było!", "Tęskniłam! Dobrze, że jesteś.",
             "O, wielki powrót! Cześć!", "Nareszcie! Cześć!"]
WEEKDAY = {0: ["Cześć! Poniedziałek — dajemy radę.", "Hej! Nowy tydzień, nowe przygody."],
           4: ["Piąteczek! Cześć!", "Hej! Już piątek, hura!"],
           5: ["Cześć! Sobota — weekendowo dziś.", "Hej! Weekend!"],
           6: ["Cześć! Leniwa niedziela?", "Hej! Niedzielnie dziś."]}

RECENT = 8                     # none of the last this many again
_recent = []


def _pick(pool):
    fresh = [p for p in pool if p not in _recent] or list(pool)
    said = random.choice(fresh)
    _recent[:] = (_recent + [said])[-RECENT:]
    return said


def _voc(who):
    """"Maja" → "Maju" (people.json "voc"), else the name as it is."""
    if not who:
        return ""
    try:
        import faces
        return faces.vocatives().get(who) or who
    except Exception:
        return who


def _child(who):
    try:
        import brain
        return brain._is_child(who)
    except Exception:
        return False


def wave(who=None, now=None):
    """The words back to a wave."""
    h = time.localtime(now if now is not None else time.time()).tm_hour
    pool = list(WAVE)
    v = _voc(who)
    if v:
        named = WAVE_NAMED + (WAVE_CHILD if _child(who) else [])
        pool = [p.replace("{v}", v).replace("{V}", v[:1].upper() + v[1:]) for p in named]
        pool += random.sample(WAVE, 3)          # now and then without the name
    if 5 <= h < 10:
        pool += WAVE_MORNING
    elif 18 <= h < 22:
        pool += WAVE_EVENING
    elif h >= 22 or h < 5:                      # quietly
        pool = WAVE_NIGHT + [f"Cześć, {v}." if v else "Cześć."]
    return _pick(pool)


def hello(first_today=False, away=None, now=None):
    """A short fixed hello: the first today, after an absence of `away`
    seconds, or simply for the time of day (and now and then the weekday)."""
    t = time.localtime(now if now is not None else time.time())
    h = t.tm_hour
    if first_today:
        return _pick(FIRST_TODAY + (MORNING if 5 <= h < 11 else []))
    if 5 <= h < 11:
        pool = list(MORNING)
    elif h < 18:
        pool = list(DAY)
    elif h < 22:
        pool = list(EVENING)
    else:
        return _pick(NIGHT)
    if away is not None and away < 30 * 60:
        pool += SHORT_AWAY
    elif away is not None and away > 3 * 3600:
        pool += LONG_AWAY
    pool += WEEKDAY.get(t.tm_wday, [])
    return _pick(pool)
