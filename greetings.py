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

# ── goodbyes ("pa", "do zobaczenia") and good nights ─────────────────────────
BYE = ["Pa pa!", "Do zobaczenia!", "Na razie!", "Papa, wracaj szybko!", "Pa! Będę tu czekać.",
       "Do zobaczonka!", "Trzymaj się!", "Pa, pa! Macham!", "Do usłyszenia!", "Hej, pa!"]
BYE_NAMED = ["Pa, {v}!", "Do zobaczenia, {v}!", "Pa pa, {v}! Wracaj szybko.",
             "Trzymaj się, {v}!", "Na razie, {v}!", "{V}, pa! Macham!"]
BYE_CHILD = ["Pa, {v}! Piątka na do widzenia!", "Papa, {v}! Będę tęsknić!"]
BYE_DAY = ["Miłego dnia!", "Udanego dnia!"]
BYE_EVENING = ["Miłego wieczoru!", "Udanego wieczoru!"]
GOODNIGHT = ["Dobranoc! Śpij dobrze.", "Dobranoc, słodkich snów!", "Dobranoc. To ja też się zdrzemnę.",
         "Kolorowych snów!", "Dobranoc! Do jutra.", "Śpij dobrze — ja popilnuję domu."]
GOODNIGHT_NAMED = ["Dobranoc, {v}! Kolorowych snów.", "Dobranoc, {v}. Śpij dobrze!",
               "Słodkich snów, {v}! Do jutra.", "Dobranoc, {v}! Wyśpij się.",
               "{V}, dobranoc! Do jutra rana."]
GOODNIGHT_CHILD = ["Dobranoc, {v}! Niech ci się przyśni coś wesołego.",
               "Dobranoc, {v}! Przytulam na sen.", "Śpij słodko, {v}! Jutro znowu się pobawimy."]

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


def _named(pool, child_pool, who):
    """The pool with the name put in (and the child's extra lines), or []."""
    v = _voc(who)
    if not v:
        return []
    named = pool + (child_pool if _child(who) else [])
    return [p.replace("{v}", v).replace("{V}", v[:1].upper() + v[1:]) for p in named]


def bye(who=None, now=None):
    """"Pa, Maju! Miłego wieczoru!" — by name when she knows the face, and
    now and then a wish for the rest of the day."""
    h = time.localtime(now if now is not None else time.time()).tm_hour
    named = _named(BYE_NAMED, BYE_CHILD, who)
    said = _pick(named + random.sample(BYE, 3) if named else BYE)
    wish = BYE_DAY if 5 <= h < 17 else BYE_EVENING if h < 22 else []
    if wish and random.random() < 0.4 and not said.endswith("szybko.") and "!" in said[-1:]:
        said += " " + random.choice(wish)
    return said


def night(who=None):
    """Good night — by name, a child gets a warmer one."""
    named = _named(GOODNIGHT_NAMED, GOODNIGHT_CHILD, who)
    return _pick(named + random.sample(GOODNIGHT, 2) if named else GOODNIGHT)


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
    if h < 18:                 # a later morning hello: no "Jak się spało?" (31 Oct)
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
