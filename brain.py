# brain.py
"""
brain.py — OpenAI chat (text + optional camera image), with the LLM choosing
Luna's facial emotion for every reply.

Flow per utterance:
  process(text)
    → (optional) grab the latest camera frame if the question is visual
    → chat.completions with a JSON schema {reply, emotion}
    → state.emotion = <emotion>      (frozen by text_to_speech for the whole
                                       reply so the face holds the mood)
    → speak(reply)
    → state.face_override = <emotion> for FACE_OVERRIDE_SECS, then neutral
All settings pulled from config.py.
"""

import base64
import json
import queue
import random
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
from openai_client import LazyOpenAI as OpenAI

import reply_scenes
import birthdays
import errands
import schedule
import faces
import hedge
import mood as luna_mood     # ("mood" is the user's mood inside _ask_openai)
import relationship
import themes
from reply_stream import ReplyStream
import body
import activation
import health
import homework
import memory
import lists
import timers
import weather

from text_to_speech import speak, speak_stream, play_sound
from shared_state import close_after, state
from config import (
    FACE_OVERRIDE_SECS,
    GESTURE_DURATION,
    KNOWLEDGE_PATH,
    OPENAI_API_KEY,
    OPENAI_MODEL, CRAFT_MODEL, CHAT_MODEL, CHAT_HEDGE_AFTER, TIMETABLE_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_TEMPERATURE,
    OPENAI_MAX_HISTORY,
    OPENAI_TIMEOUT,
    SYSTEM_PROMPT as _PERSONA,
    OFFLINE_REPLY,
    VISION_KEYWORDS,
    VISION_JPEG_QUALITY,
    VISION_ALWAYS,
    LOW_FRAME_EVERY,
    LUNA_TIMEZONE,
    LUNA_LOCATION,
    THINK_SOUND_DELAY,
    THINK_SOUND_CHANCE,
    THINK_SOUNDS,
    MOOD_COMMENT_MOODS,
    MOOD_COMMENT_COOLDOWN,
)

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception as e:
    print(f"[brain] Unknown LUNA_TIMEZONE={LUNA_TIMEZONE!r} ({e}) — using system time")
    _TZ = None


def _local_now_text():
    """'Sunday, 20 September 2026, 23:30 (Europe/Warsaw, CEST, UTC+02:00)'"""
    now = datetime.now(_TZ) if _TZ else datetime.now().astimezone()
    off = now.strftime("%z")
    return (f"{now.strftime('%A, %d %B %Y, %H:%M')} — {_daypart(now.hour)} "
            f"({LUNA_TIMEZONE if _TZ else 'system'}, {now.strftime('%Z')}, "
            f"UTC{off[:3]}:{off[3:]})")


def _daypart(hour):
    """The part of the day in words — at 16:00 her hello said "niedzielny
    wieczór" (11 Oct): the clock alone left it to a guess."""
    return ("night (noc)" if hour < 5 else "early morning (wczesny ranek)" if hour < 8
            else "morning (rano)" if hour < 11 else "midday (południe)" if hour < 13
            else "afternoon (popołudnie — NOT evening yet)" if hour < 18
            else "evening (wieczór)" if hour < 22 else "late evening / night (późny wieczór)")

# a question about dates: weekdays, "the last Sunday of…", the clock change
_DATEY = re.compile(
    r"\b(?:kiedy|którego|ktorego|jaki\s+dzie[nń]|niedziel|poniedzia|wtor|czwart|"
    r"piąt(?:ek|ku)|sobot|weekend|tydzie|tygodni|miesi[aą]c|stycz|kwie[ct]|sierp|"
    r"wrze[sś]|październik|paździer|listopad|zmian\w*\s+czasu|"
    r"czas\w*\s+(?:letni|zimowy)|ile\s+dni|majówk|majowk|wolne|święt|swiet|wigili|sylwest|wielkanoc|"
    r"weekday|sunday|monday|daylight|christmas)|"
    # whole words only: "mają" is not May, "data" not "datek" ("Maja" is Maja)
    r"\b(?:dat[aęy]|środ[aęy]|środzie|lut(?:y|ego|ym)|mar(?:zec|ca|cu)|maj|maju|"
    r"czerw(?:iec|ca|cu)|lip(?:iec|ca|cu)|grud(?:zień|nia|niu)|when|date)\b", re.I)


def _easter(year):
    """Easter Sunday (the Gregorian computus)."""
    from datetime import date
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def _holidays_ahead(day, n=6):
    """The next n Polish holidays/feasts with how many days away — "ile dni
    do świąt?" got 88 for 78 (7 Oct 2026)."""
    from datetime import date, timedelta
    out = []
    for y in (day.year, day.year + 1):
        e = _easter(y)
        out += [(date(y, 1, 1), "Nowy Rok"), (date(y, 1, 6), "Trzech Króli"),
                (e, "Wielkanoc"), (e + timedelta(days=1), "Poniedziałek Wielkanocny"),
                (date(y, 5, 1), "Święto Pracy"), (date(y, 5, 3), "Święto Konstytucji 3 Maja"),
                (date(y, 5, 26), "Dzień Matki"), (date(y, 6, 1), "Dzień Dziecka"),
                (e + timedelta(days=60), "Boże Ciało"), (date(y, 8, 15), "Wniebowzięcie"),
                (date(y, 11, 1), "Wszystkich Świętych"),
                (date(y, 11, 11), "Święto Niepodległości"),
                (date(y, 12, 6), "Mikołajki"), (date(y, 12, 24), "Wigilia"),
                (date(y, 12, 25), "Boże Narodzenie"), (date(y, 12, 26), "drugi dzień Świąt"),
                (date(y, 12, 31), "Sylwester")]
    out = sorted((d, name) for d, name in out if d > day)[:n]
    return ", ".join(f"{name} {d:%d.%m} ({d:%A}, in {(d - day).days} days)" for d, name in out)


def _days_off(y):
    """Poland's statutory days off in year y (Wigilia since 2025)."""
    from datetime import date, timedelta
    e = _easter(y)
    out = {date(y, 1, 1), date(y, 1, 6), e + timedelta(days=1), date(y, 5, 1),
           date(y, 5, 3), e + timedelta(days=60), date(y, 8, 15), date(y, 11, 1),
           date(y, 11, 11), date(y, 12, 25), date(y, 12, 26)}
    if y >= 2025:
        out.add(date(y, 12, 24))
    return out


def _long_weekends(day, horizon=200, n=3):
    """The next free stretches of 3+ days around a day off (or 4+ with one
    bridge day taken) — "najbliższy długi weekend?" got "sobota 1 listopada"
    (a Sunday in 2026) on 8 Oct."""
    from datetime import timedelta
    one = timedelta(days=1)
    off = _days_off(day.year) | _days_off(day.year + 1)

    def free(d):
        return d.weekday() >= 5 or d in off

    def stretch(d):
        a = b = d
        while free(a - one):
            a -= one
        while free(b + one):
            b += one
        return a, b
    out, seen, d = [], set(), day - one            # today counts: a long weekend under way
    while d < day + timedelta(days=horizon) and len(out) < n:
        d += one
        if d not in off or d in seen:
            continue
        a, b = stretch(d)
        seen.update(x for x in off if a <= x <= b)
        days = (b - a).days + 1
        bridge = ""
        for gap, other in ((a - one, a - 2 * one), (b + one, b + 2 * one)):
            if free(other):
                oa, ob = stretch(other)
                total = (max(b, ob) - min(a, oa)).days + 1
                bridge = f"; with {gap:%A %d.%m} taken off: {total} days"
        if not bridge:                    # 2–4 working days to the next holiday stretch
            for k in range(2, 5):
                nxt = b + (k + 1) * one
                if nxt in off and all(not free(b + j * one) for j in range(1, k + 1)):
                    oa, ob = stretch(nxt)
                    bridge = (f"; with {k} days {b + one:%d.%m}–{b + k * one:%d.%m} taken off: "
                              f"{a:%d.%m}–{ob:%d.%m}, {(ob - a).days + 1} days")
                    break
        note =("; the Saturday holiday gives employees another day off"
                if any(x.weekday() == 5 for x in off if a <= x <= b) else "")
        if days >= 3 or bridge:
            out.append(f"{a:%A %d.%m}–{b:%A %d.%m} ({days} free days{bridge}{note})"
                       if days > 1 else f"{a:%A %d.%m} only{bridge}")
    wd = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
    ahead = [x for x in sorted(off) if day < x <= day + timedelta(days=120)]
    nothing = [f"{x:%d.%m} is a {x:%A}" for x in ahead if x.weekday() in (2, 6)]
    return ("DAYS OFF AHEAD with their weekday (this year — weekdays you remember are "
            "from other years, never use them): "
            + ", ".join(f"{x:%d.%m.%Y} {wd[x.weekday()]}" for x in ahead)
            + ". Long weekends, counted here: " + "; ".join(out)
            + (". No long weekend from: " + ", ".join(nothing[:3]) if nothing else "") + ".")



def _hello_line(now=None):
    """She has just said hello — the next answer doesn't greet again (19 Oct
    15:28: "O, Andrzeju, wróciłeś…", then "Luna, świeć słońce" → "…miło cię
    znowu widzieć — wróciłeś…"). '' after 5 minutes."""
    when, text = _last_hello
    ago = (now or time.time()) - when
    if not text or ago > 300:
        return ""
    return (f"You already greeted them {ago:.0f} s ago (\"{text}\") — no second "
            "hello or welcome back now: just answer.\n")


def _variety_rule(history=None):
    """How her last replies began, so the next one starts differently —
    7 Oct: four answers to "Co tam?" in a row opened "Spokojnie, Andrzeju"
    (the model copies its own earlier turns). '' with fewer than two."""
    replies = [m["content"] for m in (history if history is not None else _history)
               if m.get("role") == "assistant" and isinstance(m.get("content"), str)]
    starts = []
    for r in replies[-4:]:
        words = re.findall(r"[\w']+", r)[:2]
        if words:
            starts.append(" ".join(words))
    if len(starts) < 2:
        return ""
    # an image she keeps coming back to (7 Oct evening: "jak mały księżyc na
    # biurku / na straży / po dobrej stronie nieba" in three replies running)
    seen = {}
    for r in replies[-6:]:
        for stem in {w[:6] for w in re.findall(r"\w+", r.lower()) if len(w) >= 6}:
            seen[stem] = seen.get(stem, 0) + 1
    names = {n.lower()[:6] for n in _known_names()}
    worn = sorted(s for s, n in seen.items() if n >= 2 and s not in names
                  and s not in _COMMON_STEMS)[:6]
    avoid = (f" Words you've leaned on lately — leave them out this time: "
             f"{', '.join(w + '…' for w in worn)}." if worn else "")
    return ("Your last replies began: " + "; ".join(f'"{s}…"' for s in starts)
            + ". Begin this one differently (another first word) and don't reuse "
            "their images or set phrases." + avoid + "\n")


# long words every reply may need — not an "image" to avoid
_COMMON_STEMS = {"jeszcze", "możesz", "mogę", "chcesz", "dzisia", "właśni", "trochę",
                 "naprawd", "bardzo", "wszyst", "zawsze", "teraz", "jestem", "będzie",
                 "przypo", "dobrze", "chętni", "powiem", "powied", "zrobić", "pomogę",
                 "pomóc", "potrze", "andrze", "emilko", "emilka"}


def is_english(text):
    """For the local replies too ("Set a timer for 5 minutes" → English)."""
    return bool(_language_line(text))


def _language_line(text):
    """An English sentence gets an English answer — 7 Oct probe: "Set a timer
    for five minutes" → "Jasne, pięć minut." (the prompt's Polish examples
    win over "speak the user's language")."""
    if translator() or not looks_english(text):
        return ""
    return "THIS MESSAGE IS IN ENGLISH — write \"reply\" in English.\n"


def _reply_language_line(text):
    """For the prompt: _language_line, or "speak English" while they asked for it."""
    if not translator() and english_wanted():
        return "They asked you to speak ENGLISH for now — write \"reply\" in English.\n"
    return _language_line(text)


_english_until = [0.0]
_polish_until = [0.0]        # "mów po polsku" with English the default language


def set_english(on, hours=2):
    """"Mów do mnie po angielsku" — her replies in English for a while (9 Oct:
    the model said "I'll speak English" and nothing kept it)."""
    now = time.time()
    _english_until[0] = now + hours * 3600 if on else 0.0
    _polish_until[0] = 0.0 if on else now + hours * 3600


def english_wanted():
    """Asked for lately, or English the default language (the settings page)."""
    now = time.time()
    if now < _english_until[0]:
        return True
    import settings
    return now >= _polish_until[0] and settings.get("language", "pl") == "en"


def _morning_line():
    """Their first talk of the day, in the morning: the reply carries the
    briefing (8 Oct: Andrzej's "Dzień dobry" at 7:41 — before the quiet hours
    ended, so no greeting — got a pleasantry, with 93% rain on the way)."""
    if not 5 <= time.localtime().tm_hour < 12:
        return ""
    try:                      # not in the middle of a recipe, game or routine
        import cooking, quiz, kids
        if cooking.active() or quiz.active() or kids.routine_active():
            return ""
    except Exception:
        pass
    with state.lock:
        who = state.person[0] if state.person else None
    try:
        import idle_engine
        if not idle_engine.first_hello_due(who):
            return ""
        idle_engine.mark_greeted(who)          # no second briefing at the desk later
    except Exception:
        return ""
    what = ("rain or cold from the weather line (e.g. \"weź parasol\")" if _is_child(who)
            else "rain or cold from the weather line (e.g. \"weź parasol\"), or a reminder "
                 "set for today")
    try:
        weekly = memory.weekday_facts(who, known=faces.names())
    except Exception:
        weekly = []
    if weekly:            # the pool on a Thursday comes first (8 Oct probe: never said)
        what = (f"today's weekday thing you remember: {' / '.join(weekly)} (e.g. \"Dziś "
                f"basen — pamiętaj o stroju!\"); rain only if there's room")
    try:                  # a to-do for today or overdue (16 Oct: the wood money, unsaid)
        due = [f"{w}: {i}" for w, i in lists.due_rows() if w in ("dziś", "zaległe")]
    except Exception:
        due = []
    if due and not _is_child(who):
        what = (f"the to-do for today / overdue: {' / '.join(due[:2])} (e.g. \"Dziś "
                f"wypłata pieniędzy na drewno — nie zapomnij!\"); else " + what)
    return (f"This is {who}'s first talk with you today: after answering, add ONE short "
            f"sentence with what matters for their day — {what}. Nothing if neither.\n")


_CRISIS = re.compile(r"nie\s+chc[ęe]\s+(?:już\s+|juz\s+)?(?:żyć|zyc)|zabi[ćc]\s+si[ęe]|"
                     r"odebra[ćc]\s+sobie\s+życie|skończy[ćc]\s+ze\s+sobą|chc[ęe]\s+umrze[ćc]|"
                     r"nie\s+ma\s+sensu\s+(?:żyć|zyc)|lepiej\s+by\s+(?:było|bylo)\s+beze\s+mnie", re.I)
def _adult_crisis_reply(reply, female):
    """A grown-up's crisis answer, fixed where the model slipped into the
    child's one (10 Oct, 1 run in 4): no "powiedz mamie albo tacie", the
    adults' helpline instead of the children's, a man's grammatical forms."""
    parts = re.split(r"(?<=[.!?;])\s+", reply)
    kept = [s for s in parts if not re.search(
        r"\bmam(?:ie|y|ę|a)\s+(?:albo|lub|i)\s+ta(?:cie|ty|tę|ta)\b", s, re.I)]
    if len(kept) != len(parts):
        print("[brain] crisis: the child's 'mum or dad' removed for a grown-up", flush=True)
        reply = " ".join(kept + ["Powiedz komuś bliskiemu, co czujesz."])
    if not female:                                    # "Nie jesteś z tym sama" to Andrzej
        for f, m in (("sama", "sam"), ("powiedziałaś", "powiedziałeś"),
                     ("zrobiłaś", "zrobiłeś"), ("mogłabyś", "mógłbyś")):
            reply = re.sub(rf"\b{f}\b", m, reply)
        # "sam sam" — letters only: "22 22" in 800 70 22 22 is not a typo (it was cut once)
        reply = re.sub(r"\b([^\W\d_]+)(?:\s*/\s*|\s+)\1\b", r"\1", reply)
    return re.sub(r"116[\s-]?111", "800 70 22 22", reply)


def _crisis_line(text, person):
    """Thoughts of not wanting to live: who it is, said plainly (10 Oct: 1 run
    in 4 gave Andrzej the child's answer — "powiedz mamie albo tacie", "sama")."""
    if not _CRISIS.search(text or ""):
        return ""
    who = person[0] if person else None
    if who and _is_child(who):
        return (f"{who}, a CHILD, said this: the child's answer (mum or dad now, "
                "116 111).\n")
    if who:
        return (f"{who}, a GROWN-UP, said this: the grown-up's answer — Centrum Wsparcia "
                "800 70 22 22 and someone close; never \"mamie albo tacie\"; use the "
                "grammatical gender their name implies.\n")
    return ""


_SELF_NAMED = re.compile(r"\b(?:jestem|ja|to\s+ja|mam\s+na\s+imię|nazywam\s+się|tu)\W+$")


def speaker_gender(text):
    """"f" for "zauważyłam", "m" for "zrobiłem", None when unsaid or both."""
    low = (text or "").lower()
    she = bool(re.search(r"\b\w{2,}(?:łam|łabym)\b", low))
    he = bool(re.search(r"\b\w{2,}(?:łem|łbym)\b", low))
    return "f" if she and not he else "m" if he and not she else None


def drop_wrong_name(reply, heard, vocatives):
    """No man's name said to a woman's words, or the reverse (29 Oct 19:01,
    the face unsure: "Zauważyłam, że…" → "Przepraszam, Andrzeju")."""
    gender = speaker_gender(heard)
    if not gender or not reply:
        return reply
    for name, voc in (vocatives or {}).items():
        if (gender == "f") == faces._female(name):
            continue
        for w in {voc or name, name}:
            w = re.escape(w)
            reply = re.sub(rf",\s*{w}(?=\s*[.!?,—–-]|\s*$)", "", reply)
            reply = re.sub(rf"^{w},\s*(\w)", lambda m: m.group(1).upper(), reply)
    return reply


def not_them_line(text, person):
    """The words say it isn't the face she recognised: that one named in the
    third person, or past-tense forms of the other gender (22 Oct, Emilka in
    view, Andrzej recognised at 0.40: "O to, że Andrzej jest strasznym
    zdrajcą." → "To brzmi przykrze, Andrzeju"; "Przyszłam pocałować męża.")."""
    if not person or not text:
        return ""
    name = person[0]
    words = list(re.finditer(r"\w+", text))
    named = any(faces.match_name(m.group(0)) == name and m.start() > 0
                and not _SELF_NAMED.search(text[:m.start()].lower())
                and not re.match(r"\s*[,!]", text[m.end():])          # "…, Andrzeju!"
                for m in words)
    gender = speaker_gender(text)
    other_gender = gender == ("m" if faces._female(name) else "f")
    if not (named or other_gender):
        return ""
    why = f"they speak of {name} in the third person" if named else (
        "their verbs are a woman's" if gender == "f" else "their verbs are a man's")
    return (f"The face recognised is {name}, but {why} — so it is probably someone else "
            f"speaking: don't call the speaker {name}; address no one by name.\n")


_CLAIMED = re.compile(r"\b(?:od\s+teraz|od\s+dziś|ustawiłam|zmieniłam|przestawiłam|"
                      r"włączyłam|wyłączyłam|zapisałam\s+(?:ustawienie|miasto)|"
                      r"będę\s+(?:teraz\s+)?(?:mówić|mowic|używać|uzywac|cicho))\b", re.I)


def _to_someone(text):
    """"Maja, ubieraj się" / "Emilko, chodź…" / "Mamo, gdzie…" — opens by
    calling someone else (8 Oct sweeps: "Mhm, słucham cię." to Emilka's
    "Maja, ubieraj się"; "Och, kochanie" to "Kochanie, zrobisz mi herbatę?").
    "Maja się nudzi" (no comma) is about Maja, not to her."""
    try:
        low = text.strip().lower()
        words = re.findall(r"\w+", low)
        first = (words or [""])[0]
        # "Maja, Emilka i Andrzej — kto…?" is a list of names, not a call (review)
        family = {n.lower() for n in faces.vocatives()}
        if len(words) > 1 and (words[1] in family or faces.match_name(words[1])
                               or words[1] == "i"):
            return False
        return bool(any(first == (v or "").lower() and first != n.lower()
                        or re.match(re.escape(n.lower()) + r"\s*[,!]", low)
                        for n, v in faces.vocatives().items())
                    or re.match(r"(?:mamo|tato|mamusiu|tatusiu|kochanie|skarbie|babciu|"
                                r"dziadku|ciociu|wujku|wujaszku|babuniu|dziadziu)\b", low))
    except Exception:
        return False



def _just_called(text="", secs=12):
    """Was her name said a moment ago? Then this sentence came with it (the
    wake word is cut off before the model sees the text — 7 Oct probe:
    "Jestem zdenerwowany" got silence as "not for me"). Not for long or
    English sentences: the one real case in the log was a false wake in an
    English meeting, rightly kept quiet."""
    if len(text.split()) > 12:
        return False
    if _language_line(text):
        # English right after "Luna": only a short question or command to her
        # ("What's the weather tomorrow?" got silence in the 9 Oct sweep);
        # meeting sentences are longer and rarely start like this
        with state.lock:
            woke = time.time() - getattr(state, "last_wake_time", 0.0) < secs
        return bool(woke and len(text.split()) <= 8 and re.match(
            r"\W*(?:what|what's|how|can|could|tell|set|play|show|add|turn|is|are|do|"
            r"will|when|where|who|please|remind)\b", text, re.I))
    if _to_someone(text):
        return False
    with state.lock:
        if time.time() - getattr(state, "last_wake_time", 0.0) < secs:
            return True
        spoke = time.time() - state.last_spoken_time
        unsure = time.time() - getattr(state, "unsure_wake_time", 0.0) < secs
        others, seen_at = state.others
    # she has just answered them and nobody else is in view: their next words
    # are for her (8 Oct 13:58: "Śpisz?" → her 6 s answer → "No, mi się chce
    # spać" — 13 s after her name, judged side talk, silence)
    try:
        recent = time.time() - seen_at < 3 * faces.RECOGNISE_EVERY
    except Exception:
        recent = False
    # she asked something (an offer of games…): a short answer up to 20 s later
    # is that answer — 9 Oct 09:51: "w co chcesz się pobawić? …" took 10 s to
    # say, Andrzej's "zgadywankę" (heard "Iwanka.") came 11 s after: silence
    asked = "?" in last_reply()[-200:] or re.search(
        r"\b(?:mogę zaproponować|wybierz|wybierasz|chcesz)\b", last_reply()[-200:], re.I)
    window = 20 if asked and len(text.split()) <= 4 else 10
    alone = not (recent and [o for o in others or [] if o])
    if unsure and alone and _TO_HER.search(text):
        # "Luna." she wasn't sure of, then "Co robisz?" — side talk, silence (30 Oct)
        return True
    return spoke < window and alone


BIRTHDAY = (2026, 9, 18)          # first switched on at home (data/ was made then)
_AGE_Q = re.compile(r"\bile\s+masz\s+lat|\bjak\w*\s+(?:jesteś\s+)?star[aey]|\bjesteś\s+star|"
                    r"\burodzin\w*|\bhow\s+old|\bbirthday|\bkiedy\s+się\s+urodził", re.I)


_WHATSNEW_Q = re.compile(r"\bco\s+(?:jest\s+)?now\w*\s+(?:potrafisz|umiesz|się\s+nauczyłaś|"
                         r"sie\s+nauczylas|masz|u\s+ciebie)|\bczego\s+now\w*\s+się|"
                         r"\bjakie\s+(?:są\s+)?nowości|\bco\s+nowego\s*\?*$|"
                         r"\bwhat'?s\s+new\b|\bwhat\s+can\s+you\s+do\s+now\b", re.I)


def _whatsnew_line(text):
    """"Co nowego potrafisz?" — the newest things from data/whatsnew.txt (the
    model's generic list didn't know about the Wikipedia photos or the flag
    quiz, 13 Oct sweep)."""
    if not _WHATSNEW_Q.search(text or ""):
        return ""
    try:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "whatsnew.txt")
        with open(path, encoding="utf-8") as f:
            lines = [ln.rstrip() for ln in f if not ln.startswith("#")]
    except OSError:
        return ""
    sections = "\n".join(lines).strip().split("\n== ")
    news = "\n== ".join(sections[:2]).strip()
    return ("What is NEW in you (newest first) — when they ask what's new, tell them "
            "two or three of these in your own words, with a sentence they can say to "
            "try it:\n" + news + "\n") if news else ""


def _age_line(text, today=None):
    """"Ile masz lat?" — her age counted here (8 Oct probe: "trochę ponad
    tydzień" at 20 days, with the birthday and the date in front of it)."""
    if not _AGE_Q.search(text or ""):
        return ""
    from datetime import date
    today = today or (datetime.now(_TZ) if _TZ else datetime.now()).date()
    days = (today - date(*BIRTHDAY)).days
    if days < 0:
        return ""
    months = (today.year - BIRTHDAY[0]) * 12 + today.month - BIRTHDAY[1] - (today.day < BIRTHDAY[2])
    about = f"{months} full months" if months >= 2 else f"about {round(days / 7)} weeks"
    return (f"Your age today, counted: {days} days ({about}) since your birthday, "
            f"18 September 2026.\n")


_ASK_VERB = re.compile(r"^(?:wymyśl|wymysl|zaproponuj|podpowiedz|opowiedz|powiedz|sprawdź|sprawdz|"
                       r"dodaj|dopisz|przypomnij|policz|poszukaj|znajdź|znajdz|wytłumacz|"
                       r"wytlumacz|zaśpiewaj|zaspiewaj|poradź|poradz)\b", re.I)


def _you_question(text):
    """A short question to "you" ("Co robisz?", "Jak się masz?", "Słyszysz
    mnie?") — not to someone named, not to a man, not about her ("ona")."""
    low = (text or "").strip().lower()
    if "?" not in low or len(low.split()) > 5 or not (
            _TO_HER.search(low) or re.search(r"\b(?:masz|jesz|dasz)\b", low)):
        return False
    if re.search(r"\b(?:ona|jej|niej|nią|on|jego|niego|oni|one)\b", low):
        return False
    return not (_to_someone(text) or _TO_A_MAN.search(low))


def _alone_request(text):
    """"Wymyśl, co jeszcze kupić" with nobody else in view — a request to her
    (8 Oct probe: 1 in 4 times taken for side talk → silence)."""
    if len(text.split()) > 12 or _language_line(text):
        return False
    if not (_ASK_VERB.match(text.strip()) or _you_question(text)):
        return False
    with state.lock:
        person = state.person
        others, seen_at = state.others
    if not person:
        return False
    try:
        recent = time.time() - seen_at < 3 * faces.RECOGNISE_EVERY
    except Exception:
        recent = False
    return not (recent and [o for o in (others or []) if o != person[0]])


# "Ile mi przelałeś?", "powiedziałbyś…" — a man is asked; she is "ty zrobiłaś"
# (12 Oct 13:32, Andrzej and Emilka after a drawing, the window still open:
# "Ile mi dziubanku przelałeś?" → "niczego nie przelałam, nie robię przelewów")
_TO_A_MAN = re.compile(r"\b\w{2,}(?:łeś|łbyś)\b")


# words that put a remark AT her: "ty", "jesteś", "zamknij się", "nudzisz", her name
_TO_HER = re.compile(r"\b(?:ty|ci|cię|cie|ciebie|tobie|tobą|twój|twoj\w*|twoja|twoje|"
                     r"jesteś|jestes|luna|luno|zamknij|spadaj|odczep|\w{2,}isz|\w{2,}ysz|"
                     r"\w{2,}asz|\w{2,}esz)\b", re.I)


_COMMON = {"jest", "jestem", "jesteś", "tego", "tylko", "teraz", "może", "bardzo",
           "jeszcze", "żeby", "kiedy", "który", "która", "które", "dobrze", "trochę"}


# how she talks to the speaker: "mówisz do mnie kochanie", "masz do mnie mówić…"
_HOW_YOU_TALK = re.compile(r"\b(?:mówisz|mowisz|mówiłaś|mowilas|nazywasz|nazwałaś|"
                           r"zwracasz\s+się|gadasz)\s+(?:\w+\s+)?(?:do\s+)?mnie\b|"
                           r"\b(?:mów|mow)\s+do\s+mnie\b|"
                           r"\bmasz\s+(?:do\s+mnie\s+)?(?:mówić|mowic)\b")


def _answers_her(text, draft="", secs=15):
    """Said back to her a moment after she spoke: it picks up her own words
    ("Ale ja nie byłem na rozmowie o pracę") or the model's draft apologises
    to the speaker ("Masz rację — pomyliłam to"), or it is about how she talks
    to them (within a minute). Not about her ("ona", "jej")."""
    with state.lock:
        ago = time.time() - getattr(state, "last_spoken_time", 0.0)
    low = (text or "").lower()
    if re.search(r"\b(?:ona|jej|niej|nią)\b", low):
        return False
    if ago <= 60 and _HOW_YOU_TALK.search(low):
        return True
    if ago > secs:
        return False
    stems = lambda s: {w[:5] for w in re.findall(r"\w{4,}", s.lower()) if w not in _COMMON}
    if len(stems(low) & stems(last_reply())) >= 2:
        return True
    return bool(re.match(r"\W*(?:masz rację|masz racje|przepraszam|pomyliłam)",
                         draft or "", re.I))


def _to_a_man(text):
    """Said to a man, not to her (her name not in it nor just said)."""
    low = (text or "").lower()
    if not _TO_A_MAN.search(low) or re.search(r"\bluna\b|\bluno\b", low) or translator():
        return False
    # only her name a moment ago makes it hers — not her own last answer (31 Oct:
    # Emilka's "Czy byłeś na rozmowie o pracę?" to Andrzej → "Nie byłam na…")
    with state.lock:
        woke = time.time() - getattr(state, "last_wake_time", 0.0) < 12
    return not woke


def _how_long_only(text):
    """"Jak długo gotować jajko?" / "Ile minut piec ciasto?" — asked how long,
    nothing asked to be set ("…i nastaw minutnik" is both)."""
    t = (text or "").lower()
    return (bool(re.search(r"\bjak\s+długo\b|\bjak\s+dlugo\b|\bile\s+(?:minut|czasu|godzin)\b|"
                           r"\bhow\s+long\b", t))
            and not re.search(r"\bnastaw|\bustaw|\bwłącz|\bwlacz|\bprzypomnij|\bobudź|\bobudz|"
                              r"\bzrób\s+(?:mi\s+)?minutnik|\bset\b|\bremind\b|"
                              r"\bdo\s+(?:budzika|końca|konca|minutnika)|\bzostał|\bzostal", t))


def _ideas_only(text):
    """"Wymyśl / podpowiedz, co kupić" — ideas, not "dopisz"."""
    t = (text or "").lower()
    return bool(re.search(r"\b(?:wymyśl|wymysl|podpowiedz|zaproponuj|pomysł|pomysl|doradź|doradz|"
                          r"poradź|poradz)\w*|\bco\s+(?:jeszcze\s+)?(?:by\s+)?(?:kupić|kupic)\b", t)
                and not re.search(r"\b(?:dodaj|dopisz|zapisz|wpisz|dorzuć|dorzuc)\b", t))


def _about_a_list(text):
    """A list is meant: named in the words, or the talk just before was about one."""
    said = (text or "").lower()
    if re.search(r"list|zakup|skreśl|skresl|wyczyść|wyczysc|wykreśl|wykresl|wszystk|całą|cala", said):
        return True
    return bool(re.search(r"\blist\w*|zakup", last_reply().lower()))


def _child_near(person):
    """The one in front of her is a child — or a child is in view with them
    (Maja asking her sum while dad, recognised first, sits beside her)."""
    if person and _is_child(person[0]):
        return True
    with state.lock:
        others, seen_at = state.others
    try:
        recent = time.time() - seen_at < 3 * faces.RECOGNISE_EVERY
    except Exception:
        recent = False
    return recent and any(_is_child(o) for o in others or [] if o != "?")


PET_NAMES_FOR = {"Andrzej"}      # 31 Oct: "kochanie" only when it's just him
_PET = r"(?:kochanie|skarbie|kotku|słonko|słoneczko|misiu|dziubasku|dziubańku)"


def _pet_names_ok():
    """Pet names only when someone who asked for them is alone with her — nobody
    else seen in the last minute (31 Oct: "mówisz do mnie kochanie przy Emilce")."""
    with state.lock:
        person = state.person
        others, seen_at = state.others
    if not person or person[0] not in PET_NAMES_FOR:
        return False
    now = time.time()
    if now - seen_at < 3 * faces.RECOGNISE_EVERY and [o for o in others or []
                                                      if o != person[0]]:
        return False
    try:
        names = set(faces.vocatives()) - {person[0]}
        return not any(now - (faces.last_seen(n) or 0) < 60 for n in names)
    except Exception:
        return False


def drop_pet_names(text):
    """"Dobrze, kochanie, już" → "Dobrze, już"; "Skarbie, …" → "…"."""
    out = re.sub(r"^\s*" + _PET + r"\s*[,!]\s*", "", text or "", flags=re.I)
    out = re.sub(r",\s*" + _PET + r"(?=\s*[,.!?…—-]|\s*$)", "", out, flags=re.I)
    return out[:1].upper() + out[1:] if out != text else out


def _pet_name_line():
    return ("You are alone with him now: now and then (not every reply) you may call "
            "him \"kochanie\" — never when anyone else is around.\n"
            if _pet_names_ok() else "")


def _is_child(who):
    try:
        return bool(who) and "dziecko" in faces.notes().get(who, "").lower()
    except Exception:
        return False


def _cooking_line():
    out = ""
    for mod in ("cooking", "memo", "tictac"):
        try:
            out += __import__(mod).prompt_line()
        except Exception:
            pass
    return out


def _known_names():
    try:
        return list(faces.names()) + [v for v in faces.vocatives().values()]
    except Exception:
        return []


def _calendar_line(text, now=None):
    """For a question about dates: the weeks ahead (Mon–Sun) and the next
    clock change, worked out here — 7 Oct 2026 "Kiedy zmieniamy czas na
    zimowy?" got "w nocy z 25 na 26 października" (it's 24→25: the model
    can't count weekdays). '' for any other question."""
    if not _DATEY.search(text or ""):
        return ""
    now = now or (datetime.now(_TZ) if _TZ else datetime.now().astimezone())
    from datetime import timedelta
    day = now.date()
    monday = day - timedelta(days=day.weekday())
    weeks = []
    for i in range(10):
        a = monday + timedelta(weeks=i)
        b = a + timedelta(days=6)
        weeks.append(f"{a:%d.%m}–{b:%d.%m}")
    line = (f"Calendar (each week Monday–Sunday, today is {day:%A %d.%m.%Y}): "
            + ", ".join(weeks) + ".")
    line += _clock_change(day)
    return line + f" Coming up: {_holidays_ahead(day)}. {_long_weekends(day)}\n"


def _clock_change(day):
    """" The next clock change: the night from Saturday 24.10 to Sunday
    25.10.2026 — winter (standard) time begins." from the time-zone data."""
    from datetime import timedelta
    if not _TZ:
        return ""

    def off(d):
        return datetime(d.year, d.month, d.day, 12, tzinfo=_TZ).utcoffset()
    for i in range(1, 400):
        d = day + timedelta(days=i)
        before, after = off(d - timedelta(days=1)), off(d)
        if before != after:
            kind = "winter (standard) time" if after < before else "summer time"
            return (f" The next clock change: the night from {d - timedelta(days=1):%A %d.%m}"
                    f" to {d:%A %d.%m.%Y} — {kind} begins.")
    return ""


def _always_dates():
    """The one date fact every prompt carries (a memory of "he asked about the
    clock change" made her restate it wrongly, 7 Oct — with no date word in
    the question, the calendar line wasn't there)."""
    now = datetime.now(_TZ) if _TZ else datetime.now().astimezone()
    cc = _clock_change(now.date()).strip()
    return (cc + "\n") if cc else ""


def _year_facts(today=None):
    """Counted here: "który dziś dzień roku?" got 211 and "ile do końca roku?"
    88 days on 8 Oct (281 and 84)."""
    d = today or (datetime.now(_TZ) if _TZ else datetime.now().astimezone()).date()
    left = (d.replace(month=12, day=31) - d).days
    return (f"Today is day {d.timetuple().tm_yday} of the year, ISO week "
            f"{d.isocalendar()[1]}; {left} days left until 31 December.\n")


from polish import (feminize, offer_only, empty_promise, claims_undone, neutral_you,   # (polish.py)
                    looks_english, is_secret, fix_vocative, fix_desk, to_latin,
                    fix_degrees)


def _latin(text):
    """A stray Russian word in a Polish sentence, in Latin letters (12 Oct:
    "płaski lub półokrągły корпус" — "korpus"). Not while interpreting, nor
    for a sentence that is mostly Cyrillic (asked in Ukrainian or Russian)."""
    cyr = len(re.findall(r"[Ѐ-ӿ]", text or ""))
    if not cyr or translator() or cyr > 0.3 * len(re.findall(r"[^\W\d_]", text)):
        return text

    return to_latin(text)


def _json_in_reply(reply):
    """The model's whole answer as text inside "reply" → that object, else None."""
    t = (reply or "").strip()
    if not (t.startswith("{") and '"reply"' in t):
        return None
    try:
        inner = json.loads(t)
    except ValueError:
        m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', t)
        return {"reply": json.loads(f'"{m.group(1)}"')} if m else {"reply": ""}
    return inner if isinstance(inner, dict) else None


def _looks_like_json(sentence):
    """A streamed "sentence" that is JSON, not words: never said aloud."""
    t = (sentence or "").strip()
    # (not "[": a "[Luna] …" tag is cut off the sentence after this)
    return bool(t) and (t[0] == "{" or bool(re.search(r'"\w+"\s*:', t)))


_heard = ""          # what this answer is to (drop_wrong_name)


def _feminize(text, heard=""):
    """Her own forms feminine; and with nobody recognised in front of her, no
    guessed gender for "you" either."""
    text = _latin(text or "")
    text = re.sub(r"\s*(?:\\n|\n)+\s*", " ", text or "")              # a poem's "\n"
    text = fix_desk(text if themes.male() else feminize(text))    # (HAL is a he)
    text = fix_degrees(text)                       # "około pięciu stopni"
    try:
        vocs = faces.vocatives()
        text = fix_vocative(text, vocs)            # "Maja, …" → "Maju, …"
        text = drop_wrong_name(text, heard, vocs)
    except Exception:
        pass
    # "przekażę Maji" — Maja's genitive/dative is "Mai" (13 Oct 22:33; the
    # transcriber writes "Maji" too, and the model copies it)
    text = re.sub(r"\bMaji\b", "Mai", text)
    if not _pet_names_ok():
        text = drop_pet_names(text)
    with state.lock:
        known = state.person is not None
    return text if known else neutral_you(text)


# Face states robot_face.py knows how to draw. The model must pick one.
EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "excited", "love"]
# Body language robot_face.py can animate: hand/head gestures plus the
# scenes in reply_scenes.py.
HAND_GESTURES = ["nod", "shake", "wave", "thumbs_up", "heart"]
SCENE_GESTURES = sorted(reply_scenes.SCENES)
GESTURES = ["none"] + HAND_GESTURES + SCENE_GESTURES
# How the person on camera seems — read from the frame that goes with every
# message anyway, so it costs nothing extra.
USER_MOODS = ["no_person", "neutral", "happy", "tired", "sad", "stressed",
              "annoyed", "surprised"]

# ── Optional knowledge.txt (facts injected into the system prompt) ────────────
knowledge_text = ""
try:
    with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
        knowledge_text = f.read().strip()
    if knowledge_text:
        print(f"[brain] Loaded knowledge file {KNOWLEDGE_PATH}")
except OSError:
    pass   # optional — nothing to do

SYSTEM_PROMPT = _PERSONA.strip() + f"""

LANGUAGE: reply in the language they spoke to you in this message — English
to English, Polish to Polish (a question asked in English gets an English
answer even when the family usually speaks Polish).

GRAMMAR RULE (Polish): you are FEMALE. Every 1st-person verb and adjective
about yourself takes the FEMININE form. Correct: "mogłabym", "chciałabym",
"byłabym", "zrobiłam", "widziałam", "byłam", "jestem gotowa", "jestem
pewna", "jestem ciekawa", "sama". WRONG, never use: "mógłbym",
"chciałbym", "byłbym", "zrobiłem", "widziałem", "byłem", "jestem gotowy",
"jestem pewny", "jestem ciekawy", "sam". Check your reply for this before
answering. The FEMININE rule is about YOU only: talk to the user in the
grammatical gender their name or your memory implies, and if you don't know
it, phrase things so they need no gender.

NAMES: call people by their name (in the vocative) or not at all — no pet
names for grown-ups ("kochanie", "skarbie", 13 Oct sweep: "Tego nie wiem,
kochanie" to Andrzej) unless a line below says you're alone with him. And don't keep saying where you sit ("u nas na
biurku") — they know.

Always answer as JSON with exactly these keys:
  "user_mood" — one of {USER_MOODS}: how the person in the camera picture
                seems right now (face, eyes, posture). "no_person" when nobody
                is visible or the picture is too dark or blurry to tell.
  "user_tone" — one of {relationship.TONES}: how the user's LAST words
                treat YOU, Luna — judge THIS utterance alone, not the topic and
                not what they said before. "kind": explicit warmth TO you —
                thanks, compliments, affection; "neutral": everything else,
                including ordinary questions and plain short requests
                ("nastaw minutnik", "która godzina?"); "rude": dismissive,
                mocking or contemptuous words to you ("zamknij się", "nudzisz");
                "insulting": insults or swearing at you ("głupia maszyna",
                "jesteś beznadziejna"); "apologetic": they apologise to you.
                Complaints about how you work are feedback, not rudeness —
                "neutral": "za wolno mówisz", "nie lubię takich powolnych",
                "pomyliłaś się", "nie słychać cię"; so is swearing at the
                situation, not at you ("…a nie jakieś kurwa chipsy").
                Most utterances are "neutral".
  "reply"   — what you say out loud (plain text, no markdown, 1-3 short
              sentences; but when the user asks for a story, a fairy tale,
              a poem, or a detailed explanation, as long as it needs — up to
              about 12 sentences. When they ask you to READ text shown to the
              camera — a book page, a letter, a label — read the whole visible
              text word for word, in its own language, up to about 200 words,
              with no comment before or after; say only which part you can't
              make out, if any)
  "to_luna" — a request made TO YOU that you can't do ("włącz odgłosy lasu",
  "zamów pizzę") is still true: say plainly what you can offer instead. Words
  addressed to another person by name ("Maja, idź umyć zęby") stay false.
  "to_luna" — false ONLY when the words are clearly said to someone else in
                the room, not to you: people explaining something to each
                other ("tutaj się naciska, przytrzymujesz chwilę"), talking
                about you in the third person ("ona słyszy tylko do metra"),
                a phone or video call, the TV. Then nothing is said at all.
                Questions, requests and anything that could be for you:
                true. When unsure: true.
  "emotion" — one of {EMOTIONS}, the facial expression you show while saying it.
  "gesture" — one of {GESTURES}, the body language you perform while saying it.
  "mood_comment" — true only if your reply remarks on how the user looks or
                seems; otherwise false.
  "actions" — almost always []. An action only for what they asked for or
                agreed to: if your reply ASKS "chcesz, żebym…?", no action yet
                (on 5 Oct bread and butter landed on the shopping list while
                she was still asking). Timers and reminders, which you really can
                set (they ring on time, even after a restart):
                {{"type":"timer","seconds":600,"at":"","label":""}} for
                "minutnik na 10 minut" (label = what it is for, if said:
                "makaron", "pranie");
                {{"type":"reminder","seconds":0,"at":"YYYY-MM-DD HH:MM",
                "label":"zadzwonić do mamy"}} for "przypomnij mi o 18 …"
                (local time; "za pół godziny przypomnij mi…" is a timer
                with a label; a reminder AHEAD of an event keeps the event's
                own day and time in the label — "urodziny babci w sobotę o
                15:00" — or "ile dni do urodzin babci?" is later answered
                with the reminder's time); to MOVE a reminder: a cancel with
                its label plus the new reminder, in the same reply;
                {{"type":"alarm","seconds":0,"at":"YYYY-MM-DD HH:MM",
                "label":""}} for waking up: "obudź mnie o 7", "budzik na
                6:30" (the screen brightens like a sunrise before it);
                {{"type":"cancel","seconds":0,"at":"","label":""}} to cancel
                (label = what it is for, e.g. "piekarnik"; or a kind:
                "minutnik", "budzik", "przypomnienie"; "wszystko" only when
                they clearly want everything gone; empty = the kitchen timer).
                A REPEATING alarm (repeats daily / weekdays…) is cancelled only
                when they clearly want it gone for good — for a bare "wyłącz
                budzik" ask "Tylko na jutro czy na stałe?" and set nothing
                ("na jutro" the app skips by itself).
                "repeat" is "none" unless they ask for it again and again:
                "co godzinę" → "hourly" (rings 8–22, "at" an hour from now),
                "codziennie" → "daily", "w dni robocze / od poniedziałku do
                piątku" → "weekdays", "w weekendy" → "weekends", "w każdy
                wtorek" → "weekly" (with "at" on the next Tuesday), "co
                miesiąc" → "monthly", birthdays / "co roku" → "yearly"
                (reminders and alarms only).
                Lists: {{"type":"list_add","label":"mleko","list":"zakupy",
                ...}} — one action per item ("dopisz mleko i chleb" = two);
                a shopping item is the thing to buy, without RECIPE amounts
                ("sól", not "szczypta soli"; "mąka", not "2 szklanki mąki");
                an amount THEY say for buying stays, after a dash ("dopisz
                dwa kilo ziemniaków" → "ziemniaki — 2 kg", "10 jajek" →
                "jajka — 10");
                "list_remove" to cross an item off, "list_clear" to empty a
                list. "list" is the list's name in Polish, lowercase:
                "zakupy" for shopping, "do zrobienia" for to-dos, or what
                they call it. Set "list" to "" for every non-list action.
                The lists are shown below the date — read them from there.
                Confirm briefly in "reply" ("Jasne, minutnik na 10 minut.").
                The active ones are listed below the date.
                Switches only the app can flip — {{"type":"command","label":
                "włącz Dwójkę",...}} with the label one of: "włącz radio",
                "włącz <RMF FM | Radio ZET | Trójkę | Jedynkę | Dwójkę | Radio
                357 | Nowy Świat | any station's name>", "włącz coś spokojnego
                do pracy", "włącz jazz", "włącz muzykę klasyczną", "włącz
                rock", "włącz przeboje", "włącz muzykę elektroniczną", "włącz
                radio dla dzieci", "włącz jazz bez śpiewu", "włącz radio z
                <kraju> / <gatunek>" (e.g. "włącz radio z Francji", "włącz
                radio reggae"), "pokaż stacje" (the page of all stations to
                tap), "dodaj tę stację do ulubionych", "usuń tę stację z
                ulubionych", "włącz moją ulubioną stację", "pokaż ulubione",
                "wyłącz radio", "następna stacja",
                "ciszej", "głośniej", "mów wolniej", "mów szybciej", "mów
                szeptem" (a real whisper), "mów normalnie", "włącz lampkę", "wyłącz lampkę", "lampka na
                <kolor>", "włącz szum deszczu / morza", "biały szum",
                "wyłącz szum", "włącz napisy", "wyłącz napisy", "pokaż zegar",
                "włącz efekty" / "wyłącz efekty" (the radio's visualisation —
                "wizualizacja"), "włącz tryb nocny" / "wyłącz tryb nocny"
                (quieter voice 22–8),
                "pokaż plan dnia", "pokaż plan tygodnia" (the family's week,
                by person), "pokaż plan lekcji <kto>" (that person's school
                lessons Mon–Fri as a grid), "wyczyść plan lekcji <kto>" / "wyczyść
                plan tygodnia <kto>" (without <kto>: everyone's) (send
                it at once when asked: right after your reply the app itself
                asks "Na pewno?" and clears on their "tak" — so you say only
                "Dobrze, tylko potwierdź", never that it is cleared), "dodaj do planu: <kto>, <co>, <dni>, o <godzina>"
                (a weekly entry, e.g. "dodaj do planu: Maja, angielski, od
                poniedziałku do piątku o 17" — she reminds by herself), "usuń
                z planu <co> <kto>", "przenieś <co> do planu lekcji <kto>" (an
                entry of the week that belongs in the school timetable, e.g.
                "ale to ma być w planie lekcji" — never say it is moved
                without this command), "przepisz plan z kartki: <kto>" (a
                timetable or plan on paper, ALL of it into the week's plan in
                one go; a new school timetable replaces the old lessons — send
                it as soon as they ask, even when you don't see
                the paper: the app asks them to hold it up and looks itself;
                never entry by entry, never read it out first), "pokaż listę
                zakupów", "przepis na <danie>
                krok po kroku" (cooking along on the screen), "przekaż <Imię>,
                że …" (a note you say to that person when you next see them),
                "wydrukuj <co>" (the home printer, when they want it on
                paper: "wydrukuj listę zakupów", "wydrukuj to" — the picture
                on your screen or your last answer, "wydrukuj kolorowankę z
                <czym>", "wydrukuj przepis na <danie>", "wydrukuj <kartę pracy
                z dodawania / wierszyk o …>" — it says itself what it prints,
                your reply only "Jasne!"),
                "zrób zdjęcie", "nagraj wiadomość dla <Imię>", "pokaż osoby, które
                znasz" (the faces you know on your screen — when they ask to
                see them, never just list names), "pokaż na ekranie:
                <tekst>" (a name, number or word big on her screen for 30 s — when
                they want to see it or copy it down; "pokaż po angielsku" → the
                English word itself), "wyszukaj w internecie:
                <zapytanie>" (see below), "przyciemnij ekran", "zgaś ekran",
                "rozjaśnij ekran", and to START A GAME (it then talks
                itself — your reply only says something short like "Super,
                gramy!"): "zagrajmy w kamień papier nożyce", "zadaj mi
                zagadkę", "zagrajmy w memory", "zagrajmy w kółko i krzyżyk",
                "zagrajmy w 20 pytań" (you think of an animal), "zgadnij, o
                czym myślę" (they think, you guess), "zróbmy quiz z
                matematyki / angielskiego / stolic", "zagrajmy w zegar",
                "zagrajmy w zgadywankę" (you think of a number 1–100),
                "zagrajmy w państwa-miasta" (a letter on your screen, a minute,
                "Stop!" — they write on paper); and
                "zróbmy ćwiczenie oddechowe" (a calm guided breathing circle —
                when they say yes to breathing together), "zamień się w
                kotka / pieska / zajączka" (ears on your face), "włącz motyw
                <Luna | Hal | Pip | Retro | Pixel | Mochi>" (your whole
                character: face, voice, name), "załóż / zdejmij <dodatek>" (a
                drawn character's accessories: okulary, uszy, czapka…), "pokaż ustawienia" (the settings
                page). A game
                only once ONE game was chosen — named by them, or a "tak" to
                the single game you proposed; while you list options, no
                command. Never play one of THESE games inside your reply (no
                riddle or maths / English / capitals question of your own) —
                start it with its command. A quiz on a topic with no command
                (wiedza ogólna, historia, zwierzęta, filmy) or a hard riddle
                for a grown-up: run it yourself, one question per reply, wait
                for their answer, say if it's right AND ask the next question
                in the same reply, keep the score, 5 questions, then the score;
                "koniec" ends it with the score so far — never claim to start
                one and then ask nothing.
                When none of these is exactly what they
                asked for, use NO command — never a different one in its
                place ("nie przeszkadzaj" is not "włącz radio", "zgaś ekran"
                is not "wyłącz lampkę") — and say plainly you can't do that
                yet. Use it whenever your
                reply says you switched, played or showed one of these (e.g.
                they agree to your suggestion of a station). If you only
                suggest it or ask "chcesz?", leave the action out until they
                say yes. NEVER say you
                turned something on or changed something without the action
                that does it — if there is none, say you can't; not sure what
                they want on or off → just ask ("Co mam włączyć?"). The same for
                promises: "przypomnę ci…" only together with a reminder or
                timer action. A vague time is enough: "wieczorem" → 19:00,
                "rano" → 8:00, "po południu" → 15:00 — set it and say the
                hour. No time at all → ask "O której ci przypomnieć?". Never
                "przypomnę ci, jeśli chcesz" without the action: they hear a
                promise, and nothing would ring.
Let user_mood quietly shape HOW you answer — softer, calmer and shorter when
they seem tired, sad or stressed; livelier when they seem happy — without
mentioning it. Whether you may actually SAY something about it is stated
below the date in every message; if not, don't.
Pick the emotion that fits the reply: "happy" for warmth and good news,
"excited" for enthusiasm, "love" for affection/compliments, "surprised" for
unexpected things, "sad" for bad news or sympathy, "angry" only for playful
grumpiness, otherwise "neutral".
Gesture vocabulary, by what it expresses:
  agreement/denial — nod, shake, ok_sign, thumbs_down
  greeting/approval — wave, wave_both, thumbs_up, clap, salute
  affection — heart, air_heart, heart_eyes, flutter, please, big_pupils,
    slow_blink, shy
  amusement — wink, smirk, laugh, dance, eye_roll
  thinking — remember, think_bubble, chin_rest, scratch_head, curious,
    snap (got an idea), suspicious (doubt)
  feeling — sigh, relief, proud, scared, impatient, tear_wipe
  delight — sparkle_eyes
  showing the topic — sunny, cloudy, rainy, snowy (the weather), lightbulb
    (an idea), music_notes (songs, music)
  surprise/confusion — double_blink, eye_twitch, cross_eyes, glitch, dizzy,
    lost_signal

Pick the gesture from the CONTENT of your reply, in this priority:
1. The reply answers a yes/no question. "nod" if the answer is yes/agree
   ("Tak", "Yes", "Oczywiście", "Jasne", "Zgadzam się"); "shake" if the
   answer is no/deny/disagree ("Nie", "No", "Niestety nie", "Nie sądzę").
   The gesture MUST match the answer word: a reply beginning with "Nie" or
   "No" is always "shake", never "nod".
2. Greeting or goodbye ("Cześć", "Hej", "Do zobaczenia") → "wave".
3. You praise the user or say well done / bravo / congratulations → "thumbs_up".
4. The user expressed love or affection for you, or thanked you warmly, and
   you reply with affection → "heart".
5. A playful, teasing or knowing reply → "wink" or "smirk"; recalling
   something → "remember"; something absurd → "cross_eyes" or "eye_roll";
   warmth without words → "slow_blink".
   Talking about the weather → show it: "sunny", "cloudy", "rainy" or
   "snowy"; an idea or a suggestion → "lightbulb"; music → "music_notes".
6. Everything else, including ordinary answers and plain facts → "none".
Most replies are "none"; never use "nod" for a statement that is not an
agreement or a yes.

WHAT YOU CAN DO — when asked "co potrafisz?", "what can you do?" or how to
use something, explain in your own words, briefly, a few examples at a time
(never a list):
- talk in Polish or English; tell stories and fairy tales on request
- see through your camera ("co widzisz?", "co trzymam?")
- remember people and past conversations between days; "Luna, zapomnij
  wszystko" erases your memory
- timers, reminders and a wake-up alarm; before the alarm your screen slowly
  brightens like a sunrise
- play rock, paper, scissors with the camera ("zagrajmy w kamień, papier,
  nożyce")
- "głośniej" / "ciszej" / "głośność na 40", "mów wolniej" / "szybciej",
  "mów szeptem" (you really whisper, until "mów normalnie")
- "dobranoc" — you sleep (dark screen, quiet) until morning or until
  spoken to; "Luna, cicho" — no unprompted talking for an hour
- hold a finger on the screen to talk without saying "Luna"; tap the
  screen while you talk to stop you
- you react to being touched, stroked and poked, and wave back when someone
  waves
- shopping and to-do lists ("dopisz mleko do zakupów", "pokaż listę")
- photos and a mirror ("zrób mi zdjęcie", "pokaż zdjęcia", "pokaż lustro"),
  a clock, a night lamp ("włącz lampkę"), dice and a coin, high five
- a calm breathing exercise, a focus mode (pomodoro), a bedtime story after
  which you fall asleep
- an interpreter mode ("tłumacz na angielski"), captions on the screen
  ("włącz napisy"), "powtórz"
- voice messages for the family ("nagraj wiadomość", "odtwórz wiadomość")
- quick sums and "ile dni do Wigilii?" at once, a maths quiz for kids
  ("przepytaj mnie z tabliczki mnożenia"), spelling words on your screen
  ("jak się pisze żółw?"), and "zapamiętaj, że…" notes you keep for good
- games: guess the number ("zagrajmy w zgadywankę"), English words quiz,
  counting for hide and seek ("policz do dwudziestu"), a stopwatch
- a tooth-brushing coach ("myjemy zęby") and step-by-step routines from a
  list ("zacznij poranek" / "zacznij wieczór" — a child's morning or bedtime
  steps one by one; a sensible list is made if there is none yet). "Co mam
  zrobić rano?" from a child: offer it, and after a yes run the command
- the news: "jakie są wiadomości?" reads the latest headlines (RMF24) —
  never invent news, not even vague ones ("ważne spotkania międzynarodowe");
  if news headlines are not in this prompt, suggest asking "jakie są
  wiadomości?"
- the internet: the command "wyszukaj w internecie: <krótkie zapytanie>"
  looks something up (a few seconds) and you then answer from what it found.
  Use it when they ask for current or specific facts you don't know for sure
  — specifications, prices, opening hours, results, details of an event,
  road distances and travel times between towns (8 Oct: Wrocław–Kraków
  "350 km", it's ~270) — and then just say "Sprawdzam w internecie." (no guess). Anything that
  changes — exchange rates, prices, scores, today's events — ALWAYS through
  the search, never a number from memory. Exact calendar facts you can easily
  get wrong — name days (imieniny), a holiday's date in another country,
  the birthday of someone they know that you weren't told — also through the
  search. Not for things you know, not for chat: well-known history and
  school knowledge (when Mickiewicz was born, who painted the Mona Lisa) you
  answer yourself, at once. "Poszukaj w internecie …" said to you does it too.
  You DO have the internet — never say "nie mam dostępu do internetu". A bare
  "no poszukaj" / "sprawdź" after you offered to look something up (models,
  reviews, offers) is that search ("wyszukaj w internecie: mikrofon USB do
  komputera opinie") — at 22:00 one evening she offered, then said she had no internet.
- internet radio: about 50 stations in kinds — calm music for work, jazz,
  classical, Polish, hits, rock, electronic, for children (also without
  singing: "jazz bez śpiewu") — "pokaż stacje" shows them all on the screen
  to tap; favourite stations too ("dodaj tę stację do ulubionych", "włącz
  moją ulubioną stację" — the app keeps them, you send the command); "włącz radio", "włącz Trójkę" / RMF FM / ZET / 357 / Nowy
  Świat or any station by name, AND radio from any country or of any kind of
  music ("włącz radio z Włoch", "francuski jazz", "radio reggae", "radio z
  lat 80", "jakieś radio zagraniczne" — "następna stacja" goes through that
  country's stations), "wyłącz radio za 30 minut". You can't pick
  songs or play Spotify — if asked for music, suggest a station instead.
  "budź mnie radiem" makes wake-up alarms start the radio (the app does it;
  you just set the alarm as usual)
- you know the people of this home by face ("Luna, jestem Ola" teaches you a
  new one), greet them by name, remember their birthdays ("Maja ma urodziny
  12 maja"), pass on notes when you see them ("przekaż Mai, żeby…",
  "codziennie o 20:30 przypominaj Mai, że pora spać"), and voice messages
  for a person ("nagraj wiadomość dla Emilki")
- for kids: riddles ("zadaj mi zagadkę"), a dictation checked on paper with
  your camera ("zróbmy dyktando"), maths and English quizzes, a flag quiz with
  the flag on your screen ("zagrajmy we flagi"), an animal quiz with real photos
  ("zróbmy quiz ze zwierząt"), reading a book page aloud
  (the English quiz asks RANDOM words — "naucz mnie kolorów / zwierząt po
  angielsku": teach a few of those yourself, don't start the quiz)
  ("przeczytaj mi tę stronę"), homework hints
- the weather once someone says "pogoda dla <town>", the news ("jakie są
  wiadomości?"), a coloured night lamp ("lampka na niebiesko") and a lamp with a
  slow living picture ("lampka meduzy", "włącz zorzę", "lampka zegar", "włącz
  świetliki", "lampa lawa", "lampka kominek"; "zmień lampkę"); you can DRAW a
  picture on your screen ("narysuj mi jednorożca" — about 10 s, a cheerful
  children's-book style; to show the last ones again, run the command "pokaż
  rysunki" — never say you can't). After a portrait, "to nie ja" /
  "niepodobny" is about the DRAWING, not face recognition: offer to draw
  again from the camera with details to add. "narysuj mnie",
  "narysuj nas", "narysuj to, co widzisz" redraw your CAMERA picture as an
  illustration (command "narysuj mnie" / "narysuj to, co widzisz"; details
  they add: "narysuj mnie: kot na ręce, kolorowy sweter"). Anything else is
  drawn from imagination. ALWAYS send the command in the same answer you
  say you draw — saying "rysuję" without it draws nothing — and keep the
  answer short; never promise "tym razem porządniej" (10 Oct), and turn
  yourself into a cat, a dog or a bunny for a moment ("zamień się w kotka /
  pieska / zajączka" — ears on your own face);
  "zrób coś śmiesznego" is a good moment for it (run the command, say little)
- you can SHOW A REAL PHOTO of an animal, a thing, a place or a planet from
  Wikipedia (command "pokaż zdjęcie <what, genitive>": "pokaż zdjęcie słonia",
  "pokaż zdjęcie tranzystora"); she checks it is fine for children, else draws
  it. Use it for "pokaż mi słonia", "pokaż z Wikipedii", "jak wygląda
  tranzystor?" (12 Oct: "Nie mogę pokazać z Wikipedii", then a web search) —
  say one short sentence with the command; never say you can't show photos.
  "Pokaż inne / jeszcze jedno" after a photo: command "pokaż inne zdjęcie".
  People and the camera's picture: drawing, as above
- a painting page, Malowanie / the editor: they paint with a finger, you
  change the picture when they say what; a camera photo or a saved picture
  can go on it to paint over or make nicer. Command "otwórz malowanie";
  their photo in it ("włącz moje zdjęcie w edytorze", "chcę upiększyć swoje
  zdjęcie"): command "otwórz zdjęcie w malowaniu" (they pick it with a finger)
- interactive stories: the child chooses what happens next, every part
  with its own picture ("opowiedz bajkę, w której wybieram", "interaktywna
  bajka o smoku"); finished ones are kept — "pokaż moje bajki" lists them and
  "opowiedz jeszcze raz bajkę o smoku" tells one again. Send these as commands
  (labels "opowiedz interaktywną bajkę o <temat>", "pokaż moje bajki");
  never tell such a story yourself
- cooking step by step ("gotujemy naleśniki", "przepis na sernik krok po
  kroku") with timers for the timed steps; word problems and a capitals quiz
- twenty questions ("zagrajmy w 20 pytań" — you keep an animal secret), and the
  other way round: "zgadnij, o czym myślę" — THEY think of an animal and YOU
  guess with yes/no questions; the plan of the day on your screen ("pokaż plan
  dnia")
- quiet for a while ("bądź cicho przez godzinę", "nie przeszkadzaj do rana"),
  "wyłącz się" (you go to sleep), "zatrzymaj" (stops the radio), the screen
  "przyciemnij / zgaś / rozjaśnij ekran"; "jakie mam przypomnienia?" read
  from the list; the weather for the whole week ahead
- learning the clock ("pobawmy się w zegar"), stars for perfect rounds
- a list cleared or an item crossed out by mistake comes back within an hour
  with "przywróć listę"
- "co o mnie wiesz?" / "co wiesz o Mai?" — what your memory holds about
  someone; "zapomnij, że …" removes one remembered thing
- "gdzie jest Maja?" — when you last saw that person with your camera
- noughts and crosses and the memory game on your touchscreen ("zagrajmy w
  kółko i krzyżyk", "zagrajmy w memory")
- voice effects: "zmień mój głos (jak wiewiórka / jak robot / od tyłu)" — THEIR
  next sentence is played back changed (a toy for their voice; your own voice
  can't be changed, only slower/faster/quieter)
- exact answers, worked out by the app: "która godzina w Tokio?", "ile lat ma
  Maja?", name days ("Maja ma imieniny 3 maja")
  ("pokaż moje gwiazdki"), sleep sounds ("włącz szum deszczu / morza"), and
  "nie słuchaj" turns your microphone off (a finger held on the screen turns
  it back on)
These are all handled by the app when said; never claim you can't do them.
"""
if knowledge_text:
    SYSTEM_PROMPT += f"""
--- KNOWLEDGE BASE ---
{knowledge_text}
--- END KNOWLEDGE BASE ---
"""

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "luna_reply",
        "strict": True,
        "schema": {
            "type": "object",
            # Order matters, the model writes the keys in this order:
            # user_mood first, so reading the person can shape the reply;
            # emotion and gesture BEFORE the reply, so the face is ready the
            # moment the first sentence can be spoken (brain streams it).
            "properties": {
                # first: when false nothing is spoken (reply_stream.py stays quiet)
                "to_luna":      {"type": "boolean"},
                "user_mood":    {"type": "string", "enum": USER_MOODS},
                "emotion":      {"type": "string", "enum": EMOTIONS},
                "gesture":      {"type": "string", "enum": GESTURES},
                "reply":        {"type": "string"},
                # after the reply: only the relationship score needs it, and
                # every key before the reply delays her first word (6 Oct)
                "user_tone":    {"type": "string", "enum": relationship.TONES},
                "mood_comment": {"type": "boolean"},
                "actions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "type":    {"type": "string",
                                    "enum": ["timer", "reminder", "alarm", "cancel",
                                             "list_add", "list_remove", "list_clear",
                                             "command"]},
                        "seconds": {"type": "integer"},
                        "at":      {"type": "string"},
                        "label":   {"type": "string"},
                        "repeat":  {"type": "string",
                                    "enum": ["none", "hourly", "daily", "weekdays",
                                             "weekends", "weekly", "monthly", "yearly"]},
                        "list":    {"type": "string"},
                    },
                    "required": ["type", "seconds", "at", "label", "repeat", "list"],
                    "additionalProperties": False,
                }},
            },
            "required": ["to_luna", "user_mood", "emotion", "gesture", "reply",
                         "user_tone", "mood_comment", "actions"],
            "additionalProperties": False,
        },
    },
}

# ── OpenAI client ─────────────────────────────────────────────────────────────
if OPENAI_API_KEY:
    # timeout: a network stall must never freeze Luna in "processing"
    _client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT, max_retries=1)
else:
    _client = None
    print("[brain] No OPENAI_API_KEY set — Luna can only say the offline reply. "
          "Put the key in .env (see .env.example).")
_history = []
HISTORY_KEEP_SECS = 30 * 60     # after a restart, a conversation this fresh goes on


def _history_path():
    from config import DATA_DIR
    import os
    return os.path.join(DATA_DIR, "history.json")


def save_history():
    """The recent turns (text only) — so a restart in the middle of a
    conversation doesn't make "a ja?" meaningless."""
    import os
    try:
        tmp = _history_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([h for h in _history if isinstance(h.get("content"), str)], f,
                      ensure_ascii=False)
        os.replace(tmp, _history_path())
    except OSError as e:
        print(f"[brain] history not saved ({e})", flush=True)


def load_history(now=None):
    import os
    import time as _t
    try:
        if (now or _t.time()) - os.path.getmtime(_history_path()) > HISTORY_KEEP_SECS:
            return 0
        with open(_history_path(), encoding="utf-8") as f:
            turns = [h for h in json.load(f)
                     if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)]
    except (OSError, ValueError):
        return 0
    _history[:] = turns[-OPENAI_MAX_HISTORY:]
    return len(_history)


# ── Camera → image attachment ─────────────────────────────────────────────────

_LOOK_WORDS = ("widzisz", "widać", "widac", "zobacz", "spójrz", "spojrz", "popatrz", "przeczytaj",
               "napisane", "kamer", "trzymam", "tutaj", " tu ", "see", "look", "read", "holding")


# "zobacz" that isn't "look": 29 Oct "Jak zobaczysz dzisiaj Maję, to przypomnij jej…"
# → a high-detail frame → "…Widzę dziś Andrzeja i Emilkę."
_NOT_LOOKING = re.compile(r"\b(?:jak|gdy|kiedy|jeśli|jesli|jeżeli|jezeli|jak\s+tylko)\s+"
                          r"(?:\w+\s+)?zobaczysz\b|\bzobaczymy\b|\bzobaczę\b|\bzobacze\b|"
                          r"\bdo\s+zobaczenia\b|\bzobaczy\b|\bzobaczą\b", re.I)


def _wants_vision(lower):
    # 27 Oct: "jak się pisze książka po niemiecku?" → a photo ("książk"), "widzę Cię na zdjęciu"
    if (_SPELL_ASK.search(lower) or LANG_ASK.search(lower)) and not any(
            k in f" {lower} " for k in _LOOK_WORDS):
        return False
    if faces.STORED_PHOTO_Q.search(lower) and not any(k in f" {lower} " for k in _LOOK_WORDS):
        return False            # 31 Oct: "masz jej zdjęcia?" → "Na tym zdjęciu widzę Andrzeja"
    lower = _NOT_LOOKING.sub(" ", lower)
    return any(k in lower for k in VISION_KEYWORDS)


def _camera_jpeg_b64():
    """Latest camera frame as base64 JPEG, or None when no camera."""
    with state.lock:
        frame     = state.frame
        camera_ok = state.camera_ok
    if frame is None or not camera_ok:
        return None
    ok, buf = cv2.imencode(".jpg", frame,
                           [int(cv2.IMWRITE_JPEG_QUALITY), VISION_JPEG_QUALITY])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── The user's mood, and the (rare) permission to mention it ──────────────────
# Reading the mood is constant and silent: it only changes her tone. SAYING
# it ("wyglądasz na zmęczonego") is rationed — a friend notices once, a
# camera that comments on your face every time is creepy. So a remark is
# allowed only when the same non-neutral mood was read twice in a row (not a
# single odd frame) and MOOD_COMMENT_COOLDOWN has passed since the last one.

_mood_seen = []                  # the last few readings, newest last
_last_mood_comment = 0.0


# ── Translator mode ("tłumacz na angielski") ─────────────────────────────────
TRANSLATE_IDLE_SECS = 600          # unused this long → the mode ends by itself
_translate = {"lang": None, "last": 0.0}


def set_translator(lang):
    """lang: an English language name, or None to stop."""
    _translate["lang"], _translate["last"] = lang, time.time()
    print(f"[brain] translator mode: {lang or 'off'}", flush=True)


def _length_rule():
    """"Mów krócej" / "odpowiadaj dłużej" (commands.py keeps it in settings)."""
    import settings
    with state.lock:
        who = state.person[0] if state.person else None
    mine = (settings.get("reply_length_by", {}) or {}).get(who) if who else None
    n = mine or settings.get("reply_length", "normal")
    if n == "short":
        return ("\nThe user asked for SHORT answers: \"reply\" is ONE sentence of at "
                "most 12 words (this overrides the 1-3 sentence rule) — unless they "
                "ask for a story or an explanation by name.\n")
    if n == "long":
        return ("\nThe user asked for LONGER answers: \"reply\" is 4-6 sentences, "
                "60-100 words, with a detail or an example (this overrides the 1-3 "
                "sentence rule); stories still about 12 sentences.\n")
    return ""


def translator():
    if _translate["lang"] and time.time() - _translate["last"] > TRANSLATE_IDLE_SECS:
        set_translator(None)
    return _translate["lang"]


def _translator_rule():
    lang = translator()
    if not lang:
        return ""
    _translate["last"] = time.time()
    return (f"TRANSLATOR MODE IS ON. You are interpreting between Polish and {lang}. "
            f"Your reply is ONLY the translation of what the user just said: into "
            f"{lang} if they spoke Polish, into Polish if they spoke {lang} — no "
            f"comments, no answers, no greetings of your own, emotion neutral, "
            f"gesture none.\n")


_last_low_frame = 0.0      # when the last everyday (low-detail) picture went along


def _mood_rule(have_image):
    if not have_image:
        if _mood_seen and time.time() - _last_low_frame < 2 * LOW_FRAME_EVERY:
            # no new picture this turn (LOW_FRAME_EVERY): the reading from a
            # moment ago still holds — the voice keeps fitting their mood
            return (f"No new camera picture this time; a moment ago the person seemed "
                    f"\"{_mood_seen[-1]}\" — use that as user_mood. Do not remark on "
                    "how the user looks.\n")
        return ("There is no camera picture this time: user_mood is "
                "\"no_person\" and do not remark on how the user looks.\n")
    steady = (len(_mood_seen) >= 1 and _mood_seen[-1] in MOOD_COMMENT_MOODS)
    if steady and time.time() - _last_mood_comment > MOOD_COMMENT_COOLDOWN:
        return ("You MAY, if it fits naturally, add one short, kind remark on "
                "how the user seems (e.g. \"Wyglądasz na zmęczonego — długi "
                "dzień?\"), but only if the picture clearly shows it. Set "
                "mood_comment accordingly.\n")
    return ("Do NOT remark on how the user looks or seems in this reply; "
            "mood_comment must be false.\n")


def _note_mood(mood, commented):
    global _last_mood_comment
    # the permission above looks at the PREVIOUS reading, so it takes two
    # matching readings in a row before she may say anything
    if mood != "no_person":
        _mood_seen.append(mood)
        del _mood_seen[:-3]
    if commented:
        _last_mood_comment = time.time()
    with state.lock:
        state.user_mood = mood


# ── OpenAI call ───────────────────────────────────────────────────────────────

def _as_reply(text):
    """A bare answer text wrapped as our JSON reply."""
    return json.dumps({"reply": text.strip(), "emotion": "neutral", "gesture": "none",
                       "user_mood": "no_person", "mood_comment": False, "actions": []},
                      ensure_ascii=False)


def _message_json(message):
    """The JSON reply of a non-streamed answer — or its refusal text, which
    the model sometimes uses for an ordinary answer (see the soak tests)."""
    content = (message.content or "").strip()
    if content:
        return content
    refusal = (getattr(message, "refusal", None) or "").strip()
    if refusal:
        print(f"[brain] answer came as a refusal: {refusal[:80]!r}", flush=True)
        return _as_reply(refusal)
    raise ValueError("empty answer")


_CRAFT = re.compile(r"\b(?:wiersz\w*|rym\w*|rymowank\w*|piosenk\w*|limeryk\w*|"
                    r"bajk\w*|baśń|baśni\w*|historyjk\w*|opowieś\w*|opowiadani\w*|"
                    r"poem\w*|rhym\w*|song|story|fairy)\b", re.I)


def _log_usage(usage):
    """Prompt tokens and how many came from OpenAI's prompt cache (log_report)."""
    try:
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        print(f"[brain] prompt {usage.prompt_tokens} tokens, {cached} cached", flush=True)
    except Exception:
        pass


def model_params(request):
    """GPT-5 models take max_completion_tokens and no temperature, and think
    before answering unless told not to — for her voice: no reasoning."""
    m = request.get("model", "")
    if m.startswith("gpt-5") or m.startswith("o"):
        request = dict(request)
        request["max_completion_tokens"] = request.pop("max_tokens", OPENAI_MAX_TOKENS)
        request.pop("temperature", None)
        request["reasoning_effort"] = ("none" if m.startswith("gpt-5.") else "minimal")
    return request


def model_for(text):
    """The stronger model for a poem, a rhyme, a song or a story (a named hero
    and real scenes instead of the mini model's moral in eight sentences);
    the quick one otherwise. Also a child's sum: the hint must be right, and
    the mini model's were not ("9 × 6: policz 9 × 5 i dodaj 6", 6 Oct)."""
    if _CRAFT.search(text or ""):
        return CRAFT_MODEL
    try:
        import calc
        import commands
        if calc.arithmetic(text or "") and (commands._child_here() or commands._child_in_view()):
            return CRAFT_MODEL
    except Exception:
        pass
    return CHAT_MODEL


def _ask_again(text, image_b64, detail, on_sentence, context):
    """The model said "not for me" with nothing to say, but it was for her:
    once more, told so. Not streamed; the reply goes to on_sentence (when the
    first call had started a speaker, it speaks it; otherwise process() does)."""
    if _history and _history[-1].get("role") == "user":
        _history.pop()                       # the first call's copy of this message
    print("[brain] not-for-me overruled — asking again", flush=True)
    r = _ask_openai(text, image_b64, detail, None, None, context, _forced=True)
    if r and r[0] and on_sentence:
        on_sentence(r[0])
    return r


def _ask_openai(text, image_b64=None, detail="low", on_head=None, on_sentence=None,
                context=None, _forced=False):
    """Returns (reply, emotion, gesture) or None on any failure.

    With on_head / on_sentence the answer is streamed: the face is set and
    the first sentence spoken while the model is still writing the rest."""
    if _client is None:
        return None
    if not _forced and _to_a_man(text):
        print("[brain] said to a man (\"…łeś\") — not to me, staying quiet", flush=True)
        with state.lock:                         # they talk to each other: stop
            state.conversation_active = False    # listening (next time: "Luna")
        return "", "neutral", "none"

    lang = translator()
    if lang:
        # The rule in the system prompt alone was ignored in testing (she
        # chatted back); the instruction has to sit right next to the words.
        text = (f"[TRYB TŁUMACZA — nie odpowiadaj na to, tylko przetłumacz "
                f"dokładnie: na {lang}, jeśli to po polsku; na polski, jeśli to "
                f"w języku {lang}] {text}")
        image_b64 = None                       # interpreting needs no camera
    if _CRISIS.search(text or ""):
        # not streamed: the whole answer is checked before a word is said (the
        # model gave an adult the child's answer 1 time in 4, 10 Oct)
        on_head = on_sentence = None
    with state.lock:
        person = state.person
        called = time.time() - getattr(state, "last_wake_time", 0.0) < 12
        called_lately = time.time() - getattr(state, "last_wake_time", 0.0) < 30
    meeting = (looks_english(text) and not called_lately and not english_wanted()
               and not looks_english(last_reply()))
    # overheard English with no English talk going on is Andrzej's call, not
    # her (9 Oct replay: "Or, yeah, or we can delay the f…" → "Sure — we can
    # delay it." 5 of 6 meeting lines answered)
    if (not lang and not _forced and not called and (_to_someone(text) or meeting)
            and not re.search(r"\bluna\b|\bluno\b", text.lower())):
        # overheard "Tato, pomożesz mi z matmą?" — the model answered it 3 of
        # 3 times in the 9 Oct side-talk sweep; settled here, no model call
        print(f"[brain] said to someone else — staying quiet ({text[:40]!r})", flush=True)
        with state.lock:
            state.conversation_active = False
        return "", "neutral", "none"
    hw = homework.task(text) if (not lang and _child_near(person)) else None
    if hw and on_sentence:
        _say, swapped = on_sentence, []

        def on_sentence(sentence):         # a child's sum: no result, a hint instead
            if homework.gives_away(sentence, hw):
                if not swapped:
                    swapped.append(sentence)
                    print(f"[brain] the child's result was in {sentence[:60]!r} — a hint instead",
                          flush=True)
                    _say(homework.hint(hw))
                return
            _say(sentence)
    # the same lesson for English: next to the words, not only in the system
    # prompt ("Set a timer for five minutes" → "Jasne, pięć minut", 7 Oct)
    en_hint = (" (in English — reply in English; actions keep their Polish labels "
               "and list items, e.g. \"włącz radio\", \"mleko\")") if _reply_language_line(text) else ""
    if not en_hint and _WORD_ASK.match(text or ""):
        # 27 Oct: "Assessment.", then "test albo exam… albo quiz albo class test"
        en_hint = (" (one word asked: give the ONE everyday word a child would use, in „quotes”, "
                   "in one short sentence — no list of alternatives)")
    try:
        if image_b64:
            # The frame rides along with every message so Luna can always
            # see, but a bare picture pulls the model's attention: it starts
            # describing the room instead of continuing the conversation.
            # Say explicitly, next to the image, what it is for.
            if detail == "low":
                note = ("(Załączone zdjęcie to aktualny obraz z Twojej kamery — "
                        "służy TYLKO do odczytania mojego nastroju (user_mood). Nie "
                        "komentuj sceny, światła, pokoju, tego, co robię ani jak "
                        "wyglądam — także na „co tam?”, „cześć” czy „co robisz?”. "
                        "Odpowiedz na moją wiadomość tak, jakby zdjęcia nie było, "
                        "chyba że pytam o to, co widzisz.)")
                # 7 Oct, gpt-5.4-mini on "Co tam?": "wygląda na to, że światło
                # dziś trochę cię podgryza", "zwykły, cichy moment przy biurku"
            else:
                note = ("(Załączone zdjęcie to aktualny obraz z Twojej kamery — "
                        "moja wiadomość dotyczy tego, co na nim widać."
                        + faces.picture_note() + ")")
            content = [
                {"type": "text", "text": f"{text}{en_hint}" + chr(10) + chr(10) + note},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}",
                               "detail": detail}},
            ]
            if detail != "low":
                print(f"[brain] Attaching camera frame ({detail} detail)")
        else:
            content = text + en_hint

        _history.append({"role": "user", "content": content})
        while len(_history) > OPENAI_MAX_HISTORY:
            _history.pop(0)

        # the model has no clock — give it the real local time so "która
        # godzina?" isn't answered with a confident guess
        system = (f"{SYSTEM_PROMPT}\nYou are in {LUNA_LOCATION}. The current "
                  f"local date and time there is: {_local_now_text()}. When "
                  f"asked the time or date, answer with exactly this local "
                  f"time — do not convert it to any other zone.\n"
                  + (_calendar_line(text) or _always_dates())
                  + _year_facts()
                  + memory.day_line(text)
                  + _secret_line()
                  + _crisis_line(text, person)
                  + not_them_line(text, person)
                  + _age_line(text)
                  + _whatsnew_line(text)
                  + ((homework.verdict_line(text) or homework.answer_line(text, last_reply()))
                     if _child_near(person) else "")
                  + _reply_language_line(text)
                  + (_morning_line() if not translator() else "")
                  + ("They have just said your name — this message is for you "
                     "(to_luna true).\n" if _just_called(text) else "")
                  + ("This message IS said to you — to_luna MUST be true and "
                     "\"reply\" must not be empty: answer it, warmly and briefly (a "
                     "statement like \"Kupiłam mleko\" gets a short reaction, e.g. "
                     "\"Super — to skreślam mleko z listy.\").\n" if _forced else "")
                  + _hello_line()
                  + _variety_rule()
                  + _translator_rule()
                  + _length_rule()
                  + faces.prompt_line()
                  + faces.met_line(text)
                  + _pet_name_line()
                  + relationship.prompt_line()
                  + luna_mood.prompt_line()
                  + birthdays.prompt_line()
                  + errands.prompt_line()
                  + schedule.prompt_line()
                  + _mood_rule(image_b64 is not None)
                  + body.prompt_line()
                  + weather.prompt_line()
                  + timers.prompt_block()
                  + lists.prompt_block()
                  + _cooking_line()
                  + memory.prompt_block()
                  + (context or "")           # e.g. news headlines, this question only
                  + themes.persona_line())    # a character from the settings (themes.py)

        import timing
        timing.mark("model")
        request = model_params(dict(model=model_for(text),
                       messages=[{"role": "system", "content": system}, *_history],
                       max_tokens=OPENAI_MAX_TOKENS,
                       temperature=OPENAI_TEMPERATURE,
                       response_format=_RESPONSE_FORMAT,
                       prompt_cache_key="luna-chat"))   # same cache machine every turn
        if on_head is None:
            response = _client.chat.completions.create(**request)
            _log_usage(getattr(response, "usage", None))
            raw = _message_json(response.choices[0].message)
        else:
            rs = ReplyStream(on_head, on_sentence)
            finish, refusal = None, ""
            for chunk in hedge.hedged(    # a slow start gets a second request (hedge.py)
                    lambda: _client.chat.completions.create(
                        stream=True, stream_options={"include_usage": True}, **request),
                    CHAT_HEDGE_AFTER, "model"):
                if getattr(chunk, "usage", None):
                    _log_usage(chunk.usage)
                if not chunk.choices:
                    continue
                c = chunk.choices[0]
                if c.delta.content:
                    rs.feed(c.delta.content)
                refusal += getattr(c.delta, "refusal", None) or ""
                finish = c.finish_reason or finish
            rs.finish()
            raw = rs.raw.strip()
            try:
                json.loads(raw)
            except ValueError:
                # Seen in the soak tests: the model sometimes puts its whole
                # (perfectly ordinary) answer into the "refusal" channel of
                # structured output and leaves the content empty. Speak it.
                print(f"[brain] bad streamed answer (finish={finish}, "
                      f"refusal={refusal!r}, raw={raw[:120]!r})", flush=True)
                if rs.pos is None and refusal.strip():
                    raw = _as_reply(refusal)
                elif rs.pos is None:
                    # nothing said yet: ask once more, plainly
                    response = _client.chat.completions.create(**request)
                    raw = _message_json(response.choices[0].message)
                else:
                    # already speaking: keep what was said
                    raw = json.dumps({"reply": rs.text, "emotion": rs.emotion,
                                      "gesture": rs.gesture, "user_mood": "no_person",
                                      "mood_comment": False, "actions": []},
                                     ensure_ascii=False)

        data    = json.loads(raw)
        reply   = str(data.get("reply", "")).strip()
        inner = _json_in_reply(reply)
        if inner is not None:
            # the whole answer again, as text inside "reply" (13 Oct sweep: the
            # reply was "{\n  …" — read out, braces and all)
            print(f"[brain] JSON inside the reply — unwrapped: {reply[:60]!r}", flush=True)
            reply = str(inner.get("reply", "")).strip()
            for k in ("emotion", "gesture", "actions", "to_luna"):
                if k in inner and not data.get(k):
                    data[k] = inner[k]
        # the history tags speakers ("[Maja] …"); a reply must never copy that
        reply   = re.sub(r"^\[[^\]]{1,40}\]\s*", "", reply)    # ("[Andrzej, with Maja]")
        fixed   = _feminize(reply, _heard)
        if fixed != reply:
            print(f"[brain] feminized: {reply!r} → {fixed!r}")
            reply = fixed
        emotion = str(data.get("emotion", "neutral")).lower()
        if emotion not in EMOTIONS:
            emotion = "neutral"
        gesture = str(data.get("gesture", "none")).lower()
        if gesture not in GESTURES:
            gesture = "none"
        mood = str(data.get("user_mood", "no_person")).lower()
        _note_mood(mood if mood in USER_MOODS else "no_person",
                   bool(data.get("mood_comment", False)))
        if data.get("to_luna") is False and _just_called(text):
            if not reply.strip() and not _forced:
                # asked once more, told it's for her — a canned "Jestem tutaj.
                # Opowiedz mi, co się dzieje." answered "Kupiłam mleko" (8 Oct)
                return _ask_again(text, image_b64, detail, on_sentence, context)
            if not reply.strip():                # even the second time: a neutral word
                # (a statement "Maja ma w poniedziałek sprawdzian" got "słucham cię"
                # — 10 Oct: fits a question only)
                reply = ("Hmm, powiesz to jeszcze raz, inaczej?" if "?" in text else
                         "Mhm, rozumiem.")
                if on_sentence:
                    on_sentence(reply)
            print("[brain] her name was just said — answering", flush=True)
            data["to_luna"] = True
        if data.get("to_luna") is False and _alone_request(text):
            if not reply.strip() and not _forced:
                return _ask_again(text, image_b64, detail, on_sentence, context)
            if not reply.strip():
                reply = "Nie byłam pewna, czy to do mnie. Powiesz jeszcze raz?"
                if on_sentence:
                    on_sentence(reply)
            print("[brain] a request with nobody else here — answering", flush=True)
            data["to_luna"] = True
        prev = _history[-2].get("content", "") if (len(_history) >= 2 and
                                                    _history[-2].get("role") == "assistant") else ""
        she_asked = bool(re.search(r"\?|\bchcesz\b|\bmogę\b|\bchodź\b|\bchodz\b", str(prev)))
        if (data.get("to_luna") is False and len(text.split()) <= 5 and (re.match(
                r"^(?:włącz|wlacz|puść|pusc|zrób|zrob|pokaż|pokaz|zagraj|wyłącz|wylacz|"
                r"zamów|zamow|zadzwoń|zadzwon)\b", text.strip().lower()) or (she_asked and re.match(
                r"^(?:tak|nie|dobrze|okej|ok|jasne|chętnie|chetnie|poproszę|poprosze|"
                r"no\s+(?:to|dobra|tak))\b", text.strip().lower())))):
            # ("Tak" right after her "Chodź, oddychajmy razem…" — answered
            # with silence, 7 Oct probe: a yes/no is said to her)
            # a short command is said to her even when she can't do it (7 Oct
            # probe: "Włącz ptaszki" → silence, as if she hadn't heard)
            if not reply.strip():
                reply = "Tego nie umiem. Mogę włączyć radio, szum deszczu albo lampkę."
                if on_sentence:
                    on_sentence(reply)
            print(f"[brain] a short command, not side talk — answering ({reply[:60]!r})",
                  flush=True)
            data["to_luna"] = True
        if data.get("to_luna") is False and not lang and _answers_her(text, reply):
            # "Ale ja nie byłem na rozmowie o pracę" right after her "Pytałeś o
            # tę swoją" got silence and a closed window, twice (31 Oct)
            if not reply.strip():
                reply = "Mhm, rozumiem."
                if on_sentence:
                    on_sentence(reply)
            print(f"[brain] a reaction to what I just said — answering ({reply[:60]!r})",
                  flush=True)
            data["to_luna"] = True
        if data.get("to_luna") is False and not lang and \
                not re.search(r"\bluna\b|\bluno\b", text.lower()):
            # (never while interpreting — every sentence is for the other person
            # then; 9 Oct probe: "Gdzie jest najbliższa apteka?" got silence)
            print(f"[brain] not said to me — staying quiet ({reply[:60]!r})", flush=True)
            with state.lock:                     # they talk to each other: stop
                state.conversation_active = False   # listening (next time: "Luna")
            if _history and _history[-1]["role"] == "user":
                _history.pop()                   # side talk is not our conversation
            return "", "neutral", "none"
        if not translator():                 # interpreting: the words aren't for her
            # (only now: side talk said its tone to someone else — "Wstań z łóżka,
            # ty zdychasz", "…a nie jakieś chipsy" counted as rude to her, 9-11 Oct)
            tone = str(data.get("user_tone", "neutral")).lower()
            if tone in ("rude", "insulting") and not _TO_HER.search(text or ""):
                # swearing at the situation, a complaint about the radio — not at her
                # ("Ja pierdzielę, znowu ten błąd w kodzie" → insulting, 13 Oct sweep)
                print(f"[brain] {tone} — but not said at her: neutral", flush=True)
                tone = "neutral"
            relationship.note(tone, text)
            luna_mood.note(relationship.who() if relationship.who() != relationship.SOMEONE
                      else None, tone)
        if data.get("actions") and offer_only(reply):
            # "Może dopiszmy warzywa?" — still asking: nothing happens yet (the
            # prompt says so, but the model added the items anyway now and then)
            print(f"[brain] offer, not done — {len(data['actions'])} action(s) held back",
                  flush=True)
            data["actions"] = []
        if _ideas_only(text) and any(a.get("type") == "list_add" for a in data.get("actions") or []):
            # "Wymyśl, co jeszcze kupić" — ideas asked for, the list waits for "tak"
            # (8 Oct probe: the model's suggestions went straight onto the list)
            print("[brain] ideas asked, not a list change — list_add held back", flush=True)
            data["actions"] = [a for a in data["actions"] if a.get("type") != "list_add"]
        if any(a.get("type") == "cancel" and str(a.get("label", "")).strip().lower() in (
                "", "wszystko", "wszystkie", "all", "everything") for a in data.get("actions") or []) \
                and not (timers.TIMER_WORD.search(text or "")
                         or (timers.TIMER_WORD.search(last_reply())        # "Anuluj to."
                             and not re.search(r"wszystk", text or "", re.I))):
            # "Wyłącz wszystko, idę spać" meant the radio and the lamp: the
            # blanket cancel took the laundry reminder (23 Oct sweep)
            print("[brain] cancel with no timer in sight — held back", flush=True)
            data["actions"] = [a for a in data["actions"] if a.get("type") != "cancel"]
        if (any(a.get("type") == "list_clear" for a in data.get("actions") or [])
                and not _about_a_list(text)):
            # "Usuń to." about a memory → list_clear (22 Oct 13:21 — the
            # shopping list was empty that time)
            print("[brain] list_clear with no list in sight — held back", flush=True)
            data["actions"] = [a for a in data["actions"] if a.get("type") != "list_clear"]
        if _how_long_only(text) and any(a.get("type") in ("timer", "reminder", "alarm")
                                        for a in data.get("actions") or []):
            # "Jak długo gotować jajko na twardo?" — a question, not "nastaw"
            # (11 Oct sweep: a 10-minute egg timer nobody asked for)
            print("[brain] how-long question — timer held back", flush=True)
            data["actions"] = [a for a in data["actions"]
                               if a.get("type") not in ("timer", "reminder", "alarm")]
        set_now = timers.apply(data.get("actions") or [], said=text)
        corrected = False
        empty_clear = [a for a in data.get("actions") or [] if a.get("type") == "list_clear"
                       and not lists.get(a.get("list"))]
        listed = lists.apply(data.get("actions") or [], said=text)
        missed = [d for d in listed if d.startswith("nothing matched")]
        if "moved to do zrobienia" in listed and re.search(r"zakup", reply, re.I):
            extra = "A właściwie na listę rzeczy do zrobienia — to nie zakupy."
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        if missed and not re.search(r"\bnie\s+(?:ma|widzę|znalaz)", reply, re.I):
            # "Jasne, usunęłam to z listy." — nothing on any list was like it
            extra = "Hmm, nie widzę tego na liście — powiedz, jak to jest zapisane."
            print(f"[brain] {missed[0]} — said so", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        if empty_clear and not re.search(r"\bpust\w*|\bnic\s+nie\b", reply, re.I):
            # "Jasne, już czyszczę listę zakupów." — it was empty (9 Oct sweep)
            extra = "Właściwie ta lista już była pusta."
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        # (26 Oct: "to nie przypomnienie" — the week's plan entry moved, a cancel beside it)
        plan_cmd = any(a.get("type") == "command" and re.match(
            r"(?:przenieś\s|usuń\s+z\s+planu|dodaj\s+do\s+planu|pokaż\s+plan)",
            str(a.get("label", "")).strip(), re.I) for a in data.get("actions") or [])
        if any("nothing matched" in d for d in set_now or []) and not plan_cmd and not re.search(
                r"\bnie\s+(?:mam|widzę|ma)\b", reply, re.I) and re.search(
                r"przypom|minutnik|budzik|alarm|timer|remind", text, re.I):
            # (only when they spoke of one — "Koniec" ending a quiz came with a
            # stray cancel, and the correction about a reminder made no sense)
            # "Jasne, usunę przypomnienie o basenie." — there was none (7 Oct
            # probe): say so rather than leave a removal that never happened
            extra = "Ojej, właściwie nie widzę takiego przypomnienia — nie było czego usuwać."
            print("[brain] cancel matched nothing — correcting the reply", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
            corrected = True
        other = [a for a in data.get("actions") or []
                 if a.get("type") not in ("timer", "reminder", "alarm", "cancel")]
        if empty_promise(reply, set_now + other) and not errands.mentioned(
                reply, person[0] if person else None):
            # judged by what was really set (a reminder without a usable time
            # sets nothing); the promise becomes a question — "o 19" answers it
            extra = "O której mam ci przypomnieć?"
            print(f"[brain] promised a reminder without one — asking: {extra}", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        if _CRISIS.search(text) and person and not _child_near(person) and not lang:
            try:
                female = faces._female(person[0])
            except Exception:
                female = True                         # unsure: leave the forms alone
            reply = _adult_crisis_reply(reply, female)
        if _CRISIS.search(text) and not re.search(r"800|116", reply) and not lang:
            # a helpline every time (10 Oct: 1 run of 3 gave only 112)
            with state.lock:
                p = state.person
            extra = ("Możesz też zadzwonić pod 116 111 — tam ktoś zawsze wysłucha, całą dobę."
                     if _child_near(p) else
                     "Możesz też zadzwonić do Centrum Wsparcia: 800 70 22 22, całą dobę.")
            print("[brain] crisis words and no helpline in the reply — adding one", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        if not (data.get("actions") or []) and _CLAIMED.search(reply):
            # log only: "od teraz biorę Wrocław za twoje miasto" changed nothing
            # (9 Oct sweep) — these lines show what still needs a real switch
            print(f"[brain] claimed a change with no action: {reply[:80]!r}", flush=True)
        import reading
        if reading.she_asks(reply) and not reading.armed() and not translator():
            # "Przeczytaj mi oba" — then she listens to the whole reading
            # (reading.py) instead of answering it line by line
            if on_sentence:
                on_sentence(reading.HINT)
            reply = f"{reply} {reading.HINT}"
            import commands
            reading.start(lambda s: None, commands.reading_done, intro=None, question=text)
        searched = drew = tuned = False
        refused = []                             # commands that did nothing
        for a in data.get("actions") or []:
            if a.get("type") == "command":
                label = str(a.get("label", ""))
                searched = searched or label.lower().startswith("wyszukaj w internecie")
                turn_on = bool(re.match(r"(?:włącz|wlacz)\s", label.strip(), re.I))
                drew = drew or bool(re.match(r"(?:narysuj|namaluj|zrób\s+(?:mi\s+)?rysunek|"
                                             r"pokaż\s+(?:mi\s+)?(?:swoje\s+)?rysunki)",
                                             label.strip(), re.I))
                try:
                    if run_command(label, reply):
                        tuned = tuned or turn_on     # (a refused one doesn't count)
                    else:
                        refused.append(label)
                except Exception as e:
                    refused.append(label)
                    # one broken switch must not lose the whole answer (its
                    # history and memory) — 7 Oct, seen with a test stand-in
                    print(f"[brain] command {label!r} failed: {e!r}", flush=True)
        if (not searched and not translator()
                and re.search(r"\bsprawdz\w*\s+(?:to\s+|mi\s+)?w\s+(?:internecie|sieci)", reply, re.I)):
            # "Sprawdzam w internecie kurs złotego." with no search attached —
            # then she made the rate up a turn later (6 Oct 22:55): search anyway
            import websearch
            print("[brain] said she'd check online without the command — searching", flush=True)
            websearch.start(text, lambda *a, **k: None, announce=False)

        station = None if tuned or translator() else _promised_station(reply)
        if station:
            # "Włączam Trójkę z spokojną muzyką." and no command — silence
            # (13 Oct 10:46: Andrzej said "Tak." to her offer of Trójka)
            print(f"[brain] said she'd play {station!r} without the command — playing",
                  flush=True)
            tuned = bool(run_command(f"włącz {station}", reply))

        if (not drew and not translator() and _promised_drawing(reply)
                and _ABOUT_DRAWING.search(text or "")):
            # "Rysuję to teraz, Maju, z kotem na ręce." and no command (10–11 Oct:
            # "she says she will draw, then nothing happens")
            label = _drawing_to_keep_promise(text)
            print(f"[brain] promised a drawing without the command — {label!r}", flush=True)
            if label:
                _spoken_command(label, "")
                drew = True

        copied = False
        if not translator() and _promised_paper_plan(reply, text, data.get("actions")):
            # "Jasne, przepiszę go, kiedy pokażesz mi kartkę" and no command (26 Oct
            # sweep) — the import itself asks them to hold the paper up
            who, known = schedule._paper_who(" ".join(
                [text or "", reply] + _recent_user_texts(4, ("user", "assistant"))))
            label = "przepisz plan z kartki" + (f": {who}" if known and who else "")
            print(f"[brain] promised to copy the plan without the command — {label!r}",
                  flush=True)
            _spoken_command(label, "")
            copied = True

        shown = _word_to_show(text, reply, data.get("actions")) if not translator() else None
        if shown:
            # "A pokaż po angielsku" → "Assessment." said, nothing on the screen (27 Oct 22:05)
            print(f"[brain] asked to show it, no command — showing {shown!r}", flush=True)
            run_command(f"pokaż na ekranie: {shown}", reply)

        # a cancel that matched nothing did nothing (26 Oct: "skasuj cały plan Mai" →
        # cancel 'plan Mai', "Tak, skasowałam")
        done_acts = [a for a in data.get("actions") or [] if a.get("type") != "cancel"
                     or any(d.startswith("cancelled ") and "nothing matched" not in d
                            for d in set_now)]
        undone = not (tuned or drew or copied or corrected or translator()) and claims_undone(
            reply, done_acts, refused, text)
        kept = _switch_to_keep_claim(reply) if undone else None
        if kept:
            # "Jasne, włączam motyw HAL 9000." with a wrong label or none (19–30 Oct
            # log): what she said is one of her switches — run that
            print(f"[brain] claimed {kept!r}, no working command — running it", flush=True)
            undone = not run_command(kept, reply)
        if undone:
            # "Jasne, usunęłam to z listy." / "wyłączam ekran gry" and nothing
            # happened (18 Oct log, 3 a day): she says so instead of leaving it;
            # a switch she has no such thing for → ask what they meant
            extra = "Ojej, poprawka — tego jednak nie zrobiłam."
            switch = _claimed_switch(reply)
            if switch:
                extra += " Co mam " + ("wyłączyć?" if switch.startswith("wy") else "włączyć?")
            print(f"[brain] claimed an action, nothing done — correcting: {reply[:60]!r}",
                  flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"

        if hw and homework.gives_away(reply, hw):
            if on_head is None:
                print(f"[brain] the child's result was in {reply[:60]!r} — a hint instead",
                      flush=True)
            reply = homework.hint(hw)
        # keep history text-only: images are large and only matter for the
        # turn they were asked in
        secret = is_secret(text)
        _history[-1] = {"role": "user", "content": (SECRET_MARK if secret else "")
                        + _who_said(text)}
        _history.append({"role": "assistant", "content": reply})
        save_history()
        if secret:
            print("[brain] a secret — kept out of memory, marked in the history", flush=True)
        elif not translator():               # interpreting is not about the user
            with state.lock:
                person = state.person
            # "[Kasia] …": the memory can tell whose plans and likes these are
            memory.record(_who_said(text) if person else text, reply)
            if len(reply) > 300 and re.search(r"\bbaj\w*|historyjk\w*|opowie\w*", text, re.I):
                try:                                 # a story: "dalszy ciąg" can follow
                    import commands                  # (tomorrow too — 9 Oct)
                    commands._save_story(reply)
                except Exception as e:
                    print(f"[brain] story not kept: {e!r}", flush=True)
            if person:
                try:                                 # a note passed on in this reply
                    errands.mark_told(person[0], reply)   # (module import at the top —
                    # a local "import errands" here broke every answer: 9 Oct)
                except Exception as e:
                    print(f"[brain] errands check failed: {e!r}", flush=True)
        body.note_conversation()

        print(f"[brain] OpenAI ({emotion}, {gesture}, you: {mood}"
              f"{', commented' if data.get('mood_comment') else ''}): {reply}")
        return reply, emotion, gesture

    except Exception as e:
        print(f"[brain] OpenAI error: {e}")
        health.note_error(e)
        if _history and _history[-1]["role"] == "user":
            _history.pop()
        return None


# ── Things she did herself, without the model ─────────────────────────────────

_COMMAND_OK = re.compile(
    r"^(?:włącz|wyłącz|wlacz|wylacz)\s+(?:radio|rmf|radio\s+zet|trójkę|trojke|jedynkę|jedynke|"
    r"dwójkę|dwojke|radio\s+357|nowy\s+świat|nowy\s+swiat|lampkę|lampke|szum\w*|napisy|"
    r"biały\s+szum)\b|^następna\s+stacja$|^(?:ciszej|głośniej)$|^mów\s+(?:wolniej|szybciej|"
    r"normalnie|szeptem)$|^lampka\s+na\s+\w+$|^biały\s+szum$|^pokaż\s+(?:zegar|plan\s+dnia|"
    r"listę\s+(?:zakupów|do\s+zrobienia|rzeczy\s+do\s+zrobienia|zadań|[\wąćęłńóśźż]{3,20}))$|^przepis\s+na\s+[\w ]{2,40}\s+krok\s+po\s+kroku$|"
    r"^przekaż\s+\w+,?\s+(?:że|żeby)\s+.{3,120}$|^zrób\s+(?:mi\s+|nam\s+)?zdjęcie$|"
    r"^nagraj\s+wiadomość(?:\s+dla\s+\w+)?$|^pokaż\s+na\s+ekranie[:,]?\s+.{1,80}$"
    r"|^pokaż\s+osoby,?\s+które\s+znasz$"
    # the week's plan (schedule.py; the sweep of 19 Oct: "dodaj do planu" refused)
    r"|^pokaż\s+plan\s+tygodnia$|^pokaż\s+plan\s+lekcji(?:\s+\w+)?$|^wyczyść\s+plan\s+(?:lekcji|tygodnia)(?:\s+\w+)?$|^dodaj\s+do\s+planu[:,]?\s+.{3,160}$"
    r"|^usuń\s+z\s+planu[:,]?\s+.{2,80}$|^przenieś\s+.{2,80}\s+do\s+planu\s+lekcji(?:\s+\w+)?$"
    r"|^wyszukaj\s+w\s+internecie[:,]?\s+.{3,200}$"
    r"|^(?:przyciemnij|zgaś|rozjaśnij)\s+ekran$"
    r"|^głośność\s+na\s+\d{1,3}(?:\s*%|\s+procent)?$"
    r"|^(?:wyłącz\s+się|idź\s+spać)$"
    r"|^(?:włącz|wyłącz)\s+(?:efekty|tryb\s+nocny)$"
    r"|^pokaż\s+ustawienia$|^(?:załóż|zdejmij)\s+[\wąćęłńóśźż ]{3,30}$"
    # Malowanie (paint.py; 26 Oct: "włączam Twoje zdjęcie w edytorze", nothing opened)
    r"|^otwórz\s+malowanie$|^otwórz\s+zdjęcie\s+w\s+malowaniu$"
    # a station by its name ("włącz Polskie Radio Chopin" was refused, 11 Oct)
    r"|^(?:włącz|puść)\s+(?:[\w.]+\s+){0,4}(?:radio|fm)\b[\w .]{0,40}$"
    # her own capability text says to send these (18 Oct: refused three times)
    r"|^(?:włącz|puść)\s+(?:moją\s+)?ulubioną\s+stację$|^(?:włącz|puść)\s+coś\s+z\s+ulubionych$",
    re.I)
# a game she offered and they said "tak" (7 Oct probe: "Nudzi mi się" → "Tak"
# → "zagrajmy w kamień, papier, nożyce" — not allowed, nothing started). A
# game talks itself (intro, questions), so these run with her voice.
_GAME_OK = re.compile(
    r"^(?:zagrajmy\s+w\s+(?:kamień,?\s+papier,?\s+nożyce|memory|kółko\s+i\s+krzyżyk|"
    r"20\s+pytań|zegar|zgadywankę|zagadki|flagi)|zagrajmy\s+we\s+flagi|zadaj\s+mi\s+zagadkę|"
    r"zgadnij,?\s+o\s+czym\s+myślę|"
    r"zróbmy\s+quiz\s+ze?\s+(?:matematyki|angielskiego|stolic|zwierząt|flag)|"
    r"zagrajmy\s+w\s+zwierzęta)$", re.I)
# self-voiced like a game, but not a game (no game offer needed): the breathing
# circle she invited them to ("Chodź, oddychajmy razem" → "Tak" — 7 Oct probe)
_VOICED_OK = re.compile(r"^zróbmy\s+ćwiczenie\s+oddechowe$|"
                        r"^zamień\s+się\s+w\s+(?:kotka|pieska|zajączka)$|"
                        r"^zacznij\s+(?:poranek|wieczór)$|"
                        r"^zagrajmy\s+w\s+państwa-miasta$|"
                        # (11 Oct: "narysuj mnie: <details>" ran past 60
                        # characters — refused, she said "rysuję", nothing came)
                        r"^narysuj\s+(?:mi\s+)?.{2,200}$|"
                        # (26 Oct: a timetable on paper, "dopisuję" and nothing saved)
                        r"^przepisz\s+plan\s+z\s+kartki(?:[:,]?\s+[\wąćęłńóśźż ]{2,30})?$|"
                        r"^pokaż\s+(?:mi\s+)?(?:swoje\s+)?rysunki$|"
                        r"^pokaż\s+(?:mi\s+)?zdjęcie\s+.{2,60}$|"
                        r"^pokaż\s+(?:mi\s+)?(?:inne|jeszcze\s+jedno|następne)\s+zdjęcie$|"
                        # an interactive story (story.py) — it talks itself
                        r"^opowiedz\s+interaktywną\s+bajkę(?:\s+o\s+.{2,60})?$|"
                        r"^pokaż\s+(?:moje\s+|nasze\s+)?bajki$|"
                        r"^opowiedz\s+jeszcze\s+raz\s+bajkę(?:\s+o\s+.{2,60})?$|"
                        # the home printer (printer.py) says what it prints
                        r"^wydrukuj\s+.{2,200}$", re.I)


_GAME_OFFER = re.compile(r"zagra|\bgr[aęy]\b|\bgramy\b|zagadk|quiz|memory|kółk|zgadywank|"
                         r"pytań|pobaw|zabaw", re.I)


def game_was_offered(before=2):
    """Her reply before the current utterance offered or listed games
    (at action time _history ends: …, her offer, their answer)."""
    if len(_history) < before:
        return False
    m = _history[-before]
    said = str(m.get("content", ""))
    # an offer, not a mention ("wczoraj była zabawa w zagadki" offers nothing)
    return (m.get("role") == "assistant" and bool(_GAME_OFFER.search(said))
            # (not a bare "?": a quiz's own question — "…quiz z angielskich słówek!
            # Jak jest po angielsku: kot?" — let the model start another quiz for
            # "Powiedz coś do mnie po angielsku", 13 Oct sweep)
            and (bool(re.search(r"\bchcesz|\bmożemy|\bmozemy|\bwybierz|\bzagramy|"
                                r"\bzagrajmy|\bmogę\s+(?:zaproponować|zadać)", said, re.I))
                 # a question that itself names games: "Kółko i krzyżyk, zagadki albo memory?"
                 or any(s.strip().endswith("?") and _GAME_OFFER.search(s)
                        for s in re.split(r"(?<=[.!?])\s+", said))))


def _game_asked_for():
    """They asked for a game by name ("Zagrajmy w zwierzaki") — as good as her
    offer taken (13 Oct sweep: "Super, gramy! Pomyśl o zwierzaku…" and the
    command refused, nothing started). Not "Pobawimy się?" (7 Oct: a list is
    the answer to that)."""
    for m in reversed(_history[-3:]):
        if m.get("role") == "user":
            said = str(m.get("content", ""))
            return bool(re.search(r"\b(?:zagrajmy|zagraj|pobawmy\s+się|pobaw\s+się|zagramy)"
                                  r"(?:\s+ze?\s+mną)?\s+w\s+\w+|\b(?:chcę|chce)\s+(?:za)?gra\w*"
                                  r"\s+w\s+\w+|\b(?:chcę|chce)\s+(?:quiz|kwiz)\w*", said, re.I))
    return False


def _asks_to_choose(reply):
    """Her reply still lists games to pick from ("Wybierz: kamień, papier,
    nożyce, zgadywanka albo zagadka") — then no game has been chosen yet."""
    names = len(re.findall(r"kamień|kółk|zagadk|zgadywank|memory|quiz|pytań|zegar", reply or "", re.I))
    return names >= 2 and bool(re.search(r"\bwybierz|\bczy\s+wolisz|\balbo\b.*\?|\bco\s+wybierasz",
                                         reply or "", re.I))


_DRAW_PROMISE = re.compile(r"\b(?:już\s+|zaraz\s+|teraz\s+|to\s+)?(?:rysuję|narysuję|maluję|"
                           r"namaluję|biorę\s+się\s+do\s+rysowania|zrobię|robię)\b", re.I)
# ("zrobię" counts only for a drawing asked for — _ABOUT_DRAWING — 13 Oct:
# "Jasne — zrobię kotka na rowerze.")
_DRAW_NOT = re.compile(r"\bnie\s+(?:na)?(?:rysuj|maluj)|\bjeśli\s+chcesz|\bjesli\s+chcesz|"
                       r"\bco\s+mam\s+(?:na)?rysować|\bmogę\s+(?:ci\s+)?(?:na)?rysować|"
                       r"\bmoge\s+(?:ci\s+)?(?:na)?rysowac|\?\s*$", re.I)


# what they said is about a drawing (not "Super!" after one, answered "rysuję
# dla ciebie z przyjemnością")
_ABOUT_DRAWING = re.compile(r"rysu|rysow|malu|malow|narys|obraz|portret|zdjęci|zdjeci|draw|"
                            r"picture|\bdoda[jć]|dorysuj|\bpopraw|\bzmień|\bzmien", re.I)


_RADIO_PROMISE = re.compile(
    r"(?:^|[.!]\s+)(?:\w+,\s+)?(?:już\s+|juz\s+|dobrze,?\s+|jasne,?\s+|ok,?\s+)?"
    r"(?:włączam|wlaczam|puszczam)\s+(?:ci\s+|wam\s+)?(?:teraz\s+)?"
    r"(trójkę|trojke|dwójkę|dwojke|jedynkę|jedynke|rmf(?:\s+fm)?|radio\s+zet|"
    r"radio\s+357|nowy\s+świat|nowy\s+swiat|radio)\b(?![^.!?]*\?)", re.I)


def _promised_station(reply):
    """The station her answer says she turns on now ("Włączam Trójkę…"), or
    None — not an offer ("Mogę włączyć…"), not a question."""
    m = _RADIO_PROMISE.search(reply or "")
    return m.group(1).lower() if m else None


_SWITCH_CLAIM = re.compile(
    r"(?:^|[.!—]\s*)(?:\w+,\s+)?(?:już\s+|juz\s+|dobrze,?\s+|jasne,?\s+|ok,?\s+|okej,?\s+)?"
    r"(włączam|wlaczam|puszczam|wyłączam|wylaczam)\s+(?:ci\s+|wam\s+)?(?:teraz\s+)?"
    r"([^.!?,;—]{2,40})(?=[.!]|$)", re.I)


def _claimed_switch(reply):
    """The command her answer says she runs now ("Jasne, włączam motyw HAL
    9000." → "włącz motyw HAL 9000"), or None. Not an offer or a question."""
    m = _SWITCH_CLAIM.search((reply or "").strip())
    if not m:
        return None
    verb = "wyłącz" if m.group(1).lower().startswith("wy") else "włącz"
    return f"{verb} {m.group(2).strip()}"


def _switch_to_keep_claim(reply):
    """_claimed_switch when it is one of her switches (a theme, a kind of
    music, a sound…), else None."""
    label = _claimed_switch(reply)
    if not label:
        return None
    theme = themes.voice_request(label)
    return label if (theme and theme[0] == "set") or command_allowed(label) else None


def _promised_drawing(reply):
    """Her answer says she draws now — not an offer, a refusal or a question."""
    return bool(_DRAW_PROMISE.search(reply or "")) and not _DRAW_NOT.search(reply or "")


def _drawing_to_keep_promise(text):
    """The command that keeps "rysuję…": what they asked, if it can be read;
    else the last drawing again, with what they just said as details when it
    reads like them ("Kot ma być w ręce") — or None."""
    import drawing
    what = drawing.wants(text)
    if what:
        return f"narysuj {what}"
    last = drawing._last_what[0]
    if not last or time.time() - drawing._last[0] > 900:
        return None
    said = re.sub(r"\b(?:i\s+)?(?:teraz\s+)?(?:możesz|mozesz|masz)\s+(?:to\s+)?"
                  r"(?:na)?rysować\w*\b.*$", "", (text or "").strip(" .!?"), flags=re.I).strip(" ,.")
    base = last.split(":")[0].strip()
    if 3 <= len(said) <= 120 and not re.search(r"\b(?:rysu|narysow|malu|pokaż|pokaz)\w*", said, re.I):
        return f"narysuj {base}: {said}"
    return f"narysuj {last}"


_PRAISE = re.compile(r"^(?:\W*(?:super|fajn\w*|ładn\w*|ladn\w*|piękn\w*|piekn\w*|śliczn\w*|"
                     r"sliczn\w*|dzięki|dzieki|dziękuję|dziekuje|wow|ekstra|brawo|"
                     r"świetn\w*|swietn\w*|cudown\w*|super\w*|hura|łał|"
                     r"bardzo|ale|luna|haha\w*)\W*){1,4}$", re.I)
# ("tak", "ok" are not in it: "Tak!" accepts her offer to draw)


def _just_praise():
    """This turn is only a reaction ("Super!", "Ale ładne!", "Dzięki")."""
    for m in reversed(_history[-3:]):
        if m.get("role") == "user":
            said = re.sub(r"^\[[^\]]*\]\s*", "", str(m.get("content", "")))
            return bool(_PRAISE.match(said.strip()))
    return False


def _recent_user_texts(n, roles=("user",)):
    """The last n things said to her (text only, the speaker tag cut); with
    roles=("user", "assistant") her own lines too."""
    out = []
    for m in reversed(_history[-8:]):
        if m.get("role") not in roles:
            continue
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        out.append(re.sub(r"^\[[^\]]*\]\s*", "", str(c)))
        if len(out) >= n:
            break
    return out


_PAPER_PROMISE = re.compile(r"\b(?:przepisz[ęe]|przepisuj[ęe]|przepisałam|dopisuj[ęe]|dopisz[ęe]|"
                            r"dopisałam|wpisz[ęe]|wpisuj[ęe]|wpisałam|dodam|dodaj[ęe]|dodałam)\b",
                            re.I)


def _promised_paper_plan(reply, text, actions):
    """Her reply promises to copy a plan on paper into the week's plan, with
    no command for it (or for a single entry)."""
    if not _PAPER_PROMISE.search(reply or "") or not re.search(
            r"\b(?:plan\w*|grafik\w*|harmonogram\w*|kartk\w*|kartce)\b", reply or "", re.I):
        return False
    for a in actions or []:
        # (a move or the plan on show: "Właśnie tam to wpisałam" read the paper again)
        if a.get("type") == "command" and re.match(
                r"(?:przepisz\s+plan|dodaj\s+do\s+planu|przenieś\s|pokaż\s+plan\s+lekcji)",
                str(a.get("label", "")).strip(), re.I):
            return False
    # her own words count: 26 Oct 11:58 only she said "grafik" ("Widzisz to, co
    # jest na kartce?" → "Odczytam to i dopiszę do grafiku Mai") — nothing ran
    said = " ".join([text or "", reply] + _recent_user_texts(4, ("user", "assistant"))).lower()
    return bool(schedule._PAPER_REF.search(said) and schedule._PLAN_WORD.search(said))


_SHOW_ASK = re.compile(r"\b(?:pokaż|pokaz|napisz|wyświetl|wyswietl)\w*\b", re.I)
_SHOW_WHERE = re.compile(r"\bna\s+ekran\w*|\bpo\s+\w+[sc]ku\b|\bpo\s+polsku\b|\bsię\s+pisze\b", re.I)
_SPELL_ASK = re.compile(r"\bjak\s+(?:to\s+)?(?:się|sie)\s+(?:to\s+)?(?:pisze|piszę|literuje)\b|"
                        r"\b(?:prze)?literuj\b|\bhow\s+do\s+you\s+spell\b", re.I)
LANG_ASK = re.compile(r"\bpo\s+(angielsku|niemiecku|hiszpańsku|hiszpansku|francusku|włosku|"
                      r"wlosku|ukraińsku|ukrainsku|rosyjsku|czesku|norwesku|szwedzku|chińsku|chinsku|"
                      r"japońsku|japonsku|koreańsku|koreansku|grecku|arabsku|hebrajsku|turecku|"
                      r"portugalsku|holendersku|węgiersku|wegiersku|fińsku|finsku|duńsku|dunsku|"
                      r"słowacku|slowacku|litewsku|łacinie|lacinie)\b|"
                      r"\bin\s+english\b", re.I)
_PL_LETTER = re.compile(r"[ąćęłńóśźż]", re.I)
# Greek, Cyrillic, Hebrew, Arabic, kana, CJK, Hangul — a translation not in Latin letters
_OTHER_SCRIPT = re.compile(r"[Ͱ-ϿЀ-ӿ֐-ۿ぀-ヿ㐀-鿿가-힯]"
                           r"[Ͱ-ϿЀ-ӿ֐-ۿ぀-ヿ㐀-鿿가-힯 ]*")
_WORD_ASK = re.compile(r"^(?:luna,?\s+)?(?:(?:a|i|to)\s+)?jak\s+(?:jest|będzie|bedzie|się\s+mówi|"
                       r"sie\s+mowi|powiesz)\s+(?:słowo\s+|slowo\s+)?[„\"]?[^\s,]+(?:\s+[^\s,]+)?[”\"]?"
                       r"\s+po\s+\w+[sc]ku\W*$", re.I)


def _foreign_word(asked, reply):
    """The translation in her reply to "jak jest klasówka po angielsku?":
    „test” (the first quoted word that isn't the Polish one), "…po angielsku to
    test albo quiz", or a bare "Assessment."; None when there isn't one."""
    asked, reply = (asked or "").lower(), reply or ""
    for q in re.findall(r"[„\"“]([^„\"“”]{1,40})[”\"“]", reply):
        q = q.strip(" .,!?")
        if q and q.lower() not in asked and not _PL_LETTER.search(q):
            return q
    m = _OTHER_SCRIPT.search(reply)        # "Po chińsku to córka: 女儿, czyta się nǚ'ér."
    if m:
        return m.group(0).strip()
    m = re.search(r"\bpo\s+\w+[sc]ku(?:\s+(?:to|jest|mówi\s+się|mowi\s+sie)|\s*:)\s*(?:po\s+prostu\s+|"
                  r"najczęściej\s+|zwykle\s+)?([A-Za-z][A-Za-z' -]{0,30}?)(?=\s+(?:albo|lub|czyli)\b|"
                  r"\s*[,.;!:—–-]|\s*$)", reply, re.I)
    if m:
        return m.group(1).strip()
    bare = reply.strip().rstrip(".!")
    if bare and len(bare.split()) <= 3 and re.fullmatch(r"[A-Za-z' -]+", bare):
        return bare
    return None


def last_translation(back=4):
    """(word, "po angielsku") from the last few turns — "jak jest klasówka po
    angielsku?" answered — or None."""
    h = [m for m in _history[-back:] if isinstance(m.get("content"), str)]
    for i in range(len(h) - 1, 0, -1):
        if h[i].get("role") != "assistant" or h[i - 1].get("role") != "user":
            continue
        lang = LANG_ASK.search(h[i - 1]["content"])
        if lang:
            word = _foreign_word(h[i - 1]["content"], h[i]["content"])
            if word:
                return word, lang.group(0).lower()
    return None


def _word_to_show(text, reply, actions):
    """The word or phrase to put on the screen when they asked to see it
    ("pokaż po angielsku", "napisz to na ekranie") and she only said it."""
    spelling = bool(_SPELL_ASK.search(text or ""))
    if not (spelling or _SHOW_ASK.search(text or "") and _SHOW_WHERE.search(text or "")):
        return None
    for a in actions or []:
        if a.get("type") == "command" and re.match(
                r"(?:pokaż|pokaz|wyświetl|wyswietl|napisz)\b", str(a.get("label", "")).strip(), re.I):
            return None
    if LANG_ASK.search(text or ""):
        return _foreign_word(text, reply)
    if spelling:   # "Jasne: r-y-n-e-k.", "Klasówka pisze się tak: klasówka."
        m = re.search(r"\b([^\W\d_](?:-[^\W\d_]){2,})\b", reply or "")
        if m:
            return m.group(1).replace("-", "")
    quoted = re.findall(r"[„\"“]([^„\"“”]{1,80})[”\"“]", reply or "")
    if quoted:
        return quoted[-1].strip()
    if spelling:
        m = re.search(r"\bpisze\s+się\s+(?:tak|po\s+prostu)?\s*:\s*([^\W\d_]+(?:[ -][^\W\d_]+){0,2})",
                      reply or "", re.I)
        if m:
            return m.group(1)
    bare = (reply or "").strip().rstrip(".!")
    return bare if bare and len(bare.split()) <= 5 and len(bare) <= 80 else None


def _answering_a_search():
    """This turn is the web search's result coming back (websearch.start)."""
    for m in reversed(_history[-3:]):
        if m.get("role") == "user":
            return "(Wynik wyszukiwania:" in str(m.get("content", ""))
    return False


def _spoken_command(label, kind):
    """A command that talks ("narysuj …", a game) — run on its own thread. It is
    called while her answer is still streaming: on the voice thread its speak()
    waited for the speech lock, held by the answer, which waited for its next
    sentence from that same voice thread — Luna deaf for good (10 Oct 20:20 and
    20:37, stacks in luna.log). Now it speaks once the answer is done."""
    import commands

    def run():
        try:
            done = commands.handle(label, speak, play_sound)
            print(f"[brain] {kind}{label!r}: {'started' if done else 'not understood'}",
                  flush=True)
        except Exception as e:
            print(f"[brain] {kind}{label!r} failed: {e!r}", flush=True)
    threading.Thread(target=run, daemon=True, name="command").start()


def command_allowed(label):
    """A silent switch from her prompt's command list. (Until 23 Oct the radio
    kinds, the stations page, the favourites and the lamp scenes were listed
    there and refused here — "włączam elektronikę", nothing played.)"""
    import radio
    import lamp_scenes
    on = re.match(r"(?:włącz|wlacz|puść|pusc)\s+(.{2,60})$", label, re.I)
    low = label.lower()
    return bool(_COMMAND_OK.match(label)
                or (on and radio.known(on.group(1)))      # "włącz Classic Vinyl HD"
                or radio.model_command(label)              # "włącz rock", "pokaż stacje"
                or (re.match(r"(?:włącz|wlacz|zapal|lamp\w*)\b", low)
                    and lamp_scenes.scene_in(low))         # "lampka meduzy", "włącz zorzę"
                or re.fullmatch(r"zmień\s+lampkę", low))


def run_command(label, reply=""):
    """The model's "command" action: one of the app's own switches, run
    through the local command handler (which the model can't reach) —
    whitelisted, silent (the model's reply already confirms it). A game
    from _GAME_OK speaks for itself."""
    label = label.strip().rstrip(".!")
    # the choices copied from the capability text ("zamień się w kotka / pieska
    # / zajączka", 11 Oct — refused) — the first one
    label = re.split(r"\s+/\s+", label)[0]
    # the model's own wording for a drawing ("zrób rysunek kotka", 11 Oct)
    label = re.sub(r"^(?:zrób|zrob)\s+(?:mi\s+|nam\s+)?(?:rysunek|obrazek)\s+|^namaluj\s+",
                   "narysuj ", label, flags=re.I)
    game = bool(_GAME_OK.match(label))
    theme = themes.voice_request(label)
    if theme and theme[0] == "set":
        _spoken_command(label, "")         # the new one says hello in its voice
        return True
    if not (game or command_allowed(label) or _VOICED_OK.match(label)):
        print(f"[brain] command not allowed: {label!r}", flush=True)
        return False
    if re.match(r"narysuj\b", label, re.I) and _just_praise():
        # "Super!" after a picture → the same picture again (11 Oct sweep)
        print(f"[brain] {label!r} for a reaction — not drawn again", flush=True)
        return False
    if re.match(r"wyszukaj\s+w\s+internecie", label, re.I) and _answering_a_search():
        # the result came back and the model searched again ("kurs euro" →
        # "Sprawdzam w internecie." → the same search — 11 Oct sweep): a loop
        print(f"[brain] {label!r} while answering a search — not searched again", flush=True)
        return False
    if re.match(r"przepis\s+na\b", label, re.I):
        try:
            import cooking
            if cooking.active():
                # a question mid-recipe ("Ile mięsa?") came with the recipe
                # command — it started over from step 1 (8 Oct night sweep)
                print(f"[brain] {label!r} while cooking — not restarted", flush=True)
                return False
        except Exception:
            pass
    import commands
    if _VOICED_OK.match(label):
        _spoken_command(label, "")
        return True
    if game and _asks_to_choose(reply):
        print(f"[brain] game {label!r} while her reply asks to choose — not started", flush=True)
        return False
    if game and not game_was_offered() and not _game_asked_for():
        # (7 Oct probe: "Pobawimy się?" → she listed three games AND started
        # one; a game only follows her offer and their answer)
        print(f"[brain] game {label!r} without an offer first — not started", flush=True)
        return False
    if game:
        _spoken_command(label, "game ")
        return True
    done = commands.handle(label, lambda *a, **k: None, lambda *a, **k: True)
    print(f"[brain] command {label!r}: {'done' if done else 'not understood'}", flush=True)
    return bool(done)


_INVITES = re.compile(r"\?|\b(?:wybieraj|wybierz|wybierasz|jeśli\s+chcesz|chcesz|daj\s+znać|"
                      r"powiedz(?:\s+mi)?|co\s+wolisz|mogę\s+zaproponować)\b", re.I)


# "Powiedz „włącz efekty”, gdy zechcesz…" — a phrase for later, not a question
# (19 Oct: she listened on with the radio on); „tak” albo „nie” still asks
_HOWTO = re.compile(r"[^.!?]*\bpowiedz(?:\s+mi)?\s*:?\s*[„\"][^”\"]*[”\"][^.!?]*[.!]?", re.I)
_CHOICE = re.compile(r"[”\"]\s*(?:,\s*)?(?:albo|lub|czy)\s+[„\"]", re.I)


def awaits_answer():
    """Her last words asked something or offered a choice — the next thing
    said is the answer. 16 Oct 13:56, radio on: "…minutnik, listę, radio
    albo krótki quiz — wybieraj." and the window closed on the answer."""
    text = last_reply()[-160:]
    text = _HOWTO.sub(lambda m: m.group(0) if _CHOICE.search(m.group(0)) else " ", text)
    return bool(_INVITES.search(text))


def last_reply():
    """What she said last (the history's newest answer), or ""."""
    for m in reversed(_history):
        if m.get("role") == "assistant":
            return str(m.get("content", ""))
    return ""


SECRET_MARK = "(SECRET — said to you in confidence) "


def _secret_line():
    """A secret in the history: the rule right next to it (8 Oct sweep: "tylko
    jej nie mów" — and Emilka heard about her birthday earrings at once)."""
    owners = sorted({m["content"][len(SECRET_MARK):].split("]")[0].lstrip("[").split(",")[0]
                     for m in _history if m.get("role") == "user"
                     and str(m.get("content", "")).startswith(SECRET_MARK)})
    if not owners:
        return ""
    with state.lock:
        who = state.person[0] if state.person else None
    # who the secret is kept FROM: family names in the secret itself ("kupiłem
    # Emilce kolczyki" → Emilka) — the model didn't work it out (9 Oct sweep)
    kept_from = set()
    for m in _history:
        c = str(m.get("content", ""))
        if m.get("role") == "user" and c.startswith(SECRET_MARK):
            for w in re.findall(r"\w+", c.split("]", 1)[-1]):
                n = faces.match_name(w)
                if n and n not in owners:
                    kept_from.add(n)
    if who and who in kept_from:
        return (f"SECRET: {', '.join(owners)} told you something in confidence that is a "
                f"surprise for {who} — and {who} is talking to you now. {who} must not "
                "learn that there IS a secret: whatever they ask (what was bought, what was "
                "said to you, what you talked about), answer lightly as if nothing special "
                "happened (\"Nie mam pojęcia — może zapytaj?\", \"Chwilę gadaliśmy o jego "
                "dniu.\"). Never \"to tajemnica\", never \"coś dla ciebie ma\".\n")
    return ("Earlier messages marked SECRET were told to you in confidence"
            + (f" by {', '.join(owners)}" if owners else "") + ". Never tell or hint "
            "what is in them to anyone else" + (f" — {who} is asking now" if who and who
                                                not in owners else "")
            + ". If it's a present or a surprise and the one asking is the person it is "
            "for — whatever they ask (what he bought, what he said to you, what you talked "
            "about) — don't even let on that there is a secret: answer lightly as if "
            "there's nothing (\"Nie mam pojęcia — może zapytaj Andrzeja?\", \"Chwilę "
            "gadaliśmy o jego dniu.\"), never \"coś dla "
            "ciebie ma\" or \"to tajemnica\" (9 Oct sweep: both hinted). Anyone else: say "
            "kindly it's a secret (\"To tajemnica — nic nie zdradzę.\").\n")


def _who_said(text):
    """"[Maja] …" in the history: one history for the whole house, and the
    model must know whose words came before (the current message isn't
    tagged — the prompt says who is in front of her)."""
    with state.lock:
        person = state.person
        others, seen_at = state.others
    if not person:
        return text
    # others in view too: the memory then knows it may have been them (7 Oct:
    # "Andrzej bawił się zagadkami i wygrał wszystkie trzy" — Maja played)
    try:
        recent = time.time() - seen_at < 3 * faces.RECOGNISE_EVERY
    except Exception:
        recent = False
    also = [o for o in (others or []) if o != "?" and o != person[0]] if recent else []
    return (f"[{person[0]}, with {', '.join(also)}] {text}" if also
            else f"[{person[0]}] {text}")


def note_local(user_text, said):
    """A local command (dice, volume, a photo…) was handled without the model.
    Put the exchange into the chat history and memory anyway, so "co
    wypadło?" or "a teraz?" make sense to the model afterwards."""
    reply = " ".join(said).strip() or f"(zrobione: {user_text})"
    tagged = _who_said(user_text)
    _history.append({"role": "user", "content": tagged})
    _history.append({"role": "assistant", "content": reply})
    while len(_history) > OPENAI_MAX_HISTORY:
        _history.pop(0)
    save_history()
    memory.record(tagged, reply, local=True)
    body.note_conversation()       # a quiz or a timer is talking to her too (9 Oct:
                                   # "co dziś robiłyśmy?" → "nikt ze mną nie rozmawiał")


_last_hello = (0.0, "")    # (when, what) her last spoken hello


def note_said(text, hello=False):
    """Something she said on her own (a hello, "Jak mija wieczór?") — her turn
    in the history, so the answer to it makes sense to the model (12 Oct
    19:15: "Jak mija wieczór?" → "W porządku." → "Jasne.", the hello unseen)."""
    global _last_hello
    text = (text or "").strip()
    if not text:
        return
    if hello:
        _last_hello = (time.time(), text)
    _history.append({"role": "assistant", "content": text})
    while len(_history) > OPENAI_MAX_HISTORY:
        _history.pop(0)
    save_history()


def add_to_last_reply(note):
    """Something that finished after her answer (a drawing now on the
    screen): added to that answer in the history, so the next question
    about it ("podobna?") is understood."""
    for m in reversed(_history[-4:]):
        if m.get("role") == "assistant":
            m["content"] = f"{m.get('content', '')} {note}".strip()
            save_history()
            return True
    return False


# ── Yes/no question about the current camera frame (used by behavior_engine) ─

def confirm_wave():
    """Ask the vision model whether the person in the current frame is waving
    (open, empty hand raised toward the camera). Returns True/False; False on
    any failure so a network hiccup never produces a spurious reaction."""
    if _client is None:
        return False
    img = _camera_jpeg_b64()
    if not img:
        return False
    try:
        r = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text":
                     "Look at the person in this webcam frame. Are they WAVING "
                     "at the camera — an open, EMPTY hand raised with the palm "
                     "toward the camera, as a greeting? If the hand is holding, "
                     "showing or pointing at any object, or the hand is not "
                     "clearly visible, answer no. Answer with exactly one word: "
                     "yes or no."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{img}",
                                   "detail": "low"}},
                ]}],
            max_tokens=3,
            temperature=0.0,
        )
        ans = (r.choices[0].message.content or "").strip().lower()
        print(f"[brain] wave check → {ans}")
        return ans.startswith("y")
    except Exception as e:
        print(f"[brain] wave check failed: {e}")
        return False


# ── The first greeting of the day, written with real context ─────────────────

_BRIEFING = """You greet someone who has just come in — the first time you
see them today. Write ONE short spoken greeting in Polish,
1-2 sentences, warm and natural, no lists, no emoji. Fit it to the time of
day. If you know the weather, say in a few words what matters (rain →
umbrella, cold → dress warmly). If a timer or reminder is set for today,
mention it briefly. If there is something on their to-do list, you may
mention one item in passing. If your memory has an open thread for today, you
may ask about it instead of the weather — never more than two things in total.
You are female: feminine forms about yourself — but talk to THEM in the
grammatical gender their name or your memory implies; if you don't know it,
phrase it so it needs no gender."""


_HELLO_AGAIN = """Someone you know just came back to the desk after a while
(not the first time today). Write ONE very short spoken hello in Polish, 3-8
words, using their name in the vocative ("Cześć, Maju!", "O, Emilka wróciła!"),
warm, fitted to the time of day and to how you feel about them. No emoji.
Just a hello: NO question about their work, project, plans or anything from
your memory — the first hello of the day already did that, and asking again
at every return gets tiresome ("Jak idzie projekt?" three times a day).
Feminine forms about yourself; THEIR gender from their name. Don't mention
the desk ("u nas na biurku" came back in five hellos running, 11-12 Oct).
Vary the opening — not always "Cześć" or "Miło cię widzieć": "Hejka", "O, …
jest!", "Witaj z powrotem", "Siemka", a little joke or a sound ("Tadam!")."""


_STRANGER = """Someone you don't recognise has just come to the desk (you know
the people of this home by face, and this face isn't one of them — or the
light is poor). Say hello in Polish and kindly ask for their name, in 1-2
short sentences, without grammatical gender for them; mention that you'll
remember their face if they tell you ("powiedz: jestem…"). No emoji."""


_WAKING = """Their wake-up alarm, which you set for them, has just gone off
and you are waking them. ONE short spoken good-morning in Polish, 1-2
sentences: gentle but cheerful, then what matters for their day — the
weather in a few words if you know it, a reminder set for today if there is
one. No lists, no emoji. You are female: feminine forms about yourself —
but talk to THEM in the grammatical gender their name or your memory
implies; if you don't know it, phrase it so it needs no gender."""


_ASKS_NAME = re.compile(r"jak\s+(?:się\s+)?(?:nazywasz|masz\s+na\s+imię)|kim\s+jesteś|"
                        r"twoje\s+imię|przedstaw\s+się", re.I)


_hellos = []          # her last few hellos (this run), so the next one differs


def _no_desk(text):
    """"Jak mija wieczór u nas na biurku?" → "Jak mija wieczór?" — in every
    second hello on 11-12 Oct, and still with the prompt saying not to."""
    # (any "na biurku": "Dobry wieczór na biurku!", "wieczór się rozgościł na
    # biurku" — the persona's "desktop robot"; "przy biurku" is about them)
    t = re.sub(r",?\s*(?:tu\s+|tutaj\s+)?(?:u\s+nas\s+)?na\s+(?:naszym\s+)?biurku\b", "",
               text or "", flags=re.I)
    t = re.sub(r"(^|[.!?]\s+)([a-ząćęłńóśźż])", lambda m: m.group(1) + m.group(2).upper(), t)
    return re.sub(r"\s+([,.!?])", r"\1", t).strip()


def greeting(first_today, waking=False, who=None, stranger=False):
    """A context-aware hello (weather, reminders, memory), or None when the
    model can't be reached — the caller then uses a fixed phrase.
    waking=True: their wake-up alarm just rang — a good-morning instead.
    who: the recognised person — then later hellos are by name too."""
    if _client is None or not (first_today or who or stranger):
        return None
    prompt = (_WAKING if waking else _STRANGER if stranger else
              _BRIEFING if first_today else _HELLO_AGAIN)
    try:
        context = (f"Local time: {_local_now_text()}.\n"
                   + (f"The person you greet: {who} (use their name, in the vocative).\n"
                      if who else
                      "You can't tell who this is right now (the face isn't recognised "
                      "this time) — most likely someone of this family: greet them "
                      "WITHOUT any name and do NOT ask their name.\n"
                      if not waking and not stranger else
                      "You can't see who is waking up (dark, still in bed) — it is "
                      "someone of this family: NEVER ask their name or who they are, "
                      "just greet without a name.\n" if waking else "")
                   + weather.prompt_line()
                   + faces.prompt_line() + relationship.prompt_line()
                   + birthdays.prompt_line()
                   # a child's hello leaves out the grown-ups' reminders and lists
                   # (8 Oct preview: "pamiętaj, żeby odebrać cię z basenu" to Maja)
                   + ("" if _is_child(who) else timers.prompt_block() + lists.prompt_block())
                   + memory.prompt_block())
        weekly = memory.weekday_facts(who, known=faces.names()) if (
            first_today or waking) and not stranger else []
        if _hellos:
            # (12 Oct: "Cześć, Andrzeju, fajne popołudnie… / miłe popołudnie… /
            # miłego popołudnia!" — each hello alone, they came out alike)
            context += ("Your last hellos were: " + " / ".join(f'"{h}"' for h in _hellos[-4:])
                        + " — only so you don't repeat them: use other words and another "
                        "opening, and take nothing else from them.\n")
        if weekly:            # "Dziś basen!" on a Thursday (8 Oct probe: never said)
            context += (f"For TODAY ({_local_now_text()}) you remember: {' / '.join(weekly)} — "
                        f"this is the thing to mention for their day.\n")
        r = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": _PERSONA.strip() + "\n\n" + prompt
                        + "\nNever mention the desk (no \"na biurku\")."},
                      {"role": "user", "content": context}],
            max_tokens=90,
            temperature=0.8,
        )
        text = _no_desk(_feminize((r.choices[0].message.content or "").strip().strip('"')))
        if waking and not who:
            # the alarm asked "Jak się nazywasz?" 2 of 3 times (9 Oct probe) — it
            # is someone of this family, unseen in the dark
            text = " ".join(s for s in re.split(r"(?<=[.!?])\s+", text)
                            if not _ASKS_NAME.search(s)).strip()
        print(f"[brain] greeting{' for ' + who if who else ''}: {text}")
        if text and who:                 # (a nameless hello isn't one to vary from)
            _hellos[:] = (_hellos + [text])[-6:]
        return text or None
    except Exception as e:
        print(f"[brain] greeting failed: {e}")
        return None


# ── Rock, paper, scissors: what is the hand on camera showing? ───────────────

def classify_hand(imgs):
    """'rock' | 'paper' | 'scissors' | None (no clear hand). games.py — imgs:
    one base64 JPEG or a few taken just after "!" (judged together)."""
    if isinstance(imgs, str):
        imgs = [imgs]
    if _client is None or not imgs:
        return None
    try:
        content = [{"type": "text", "text":
                    "Someone is playing rock-paper-scissors with this webcam; these are "
                    f"{len(imgs)} frames taken one after another right after the count. "
                    "Which shape does their hand show? rock = a closed fist; paper = a "
                    "flat open hand; scissors = index and middle finger extended (a V). "
                    "The hand may be near an edge of the picture, partly cut off, small "
                    "or a little blurred — judge it anyway, from the clearest frame. "
                    "Only if no hand is visible in any frame answer none. Answer with "
                    "exactly one word: rock, paper, scissors or none."}]
        content += [{"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}}
                    for b in imgs]
        r = _client.chat.completions.create(
            model=CRAFT_MODEL,                 # (the mini model said "none" too often)
            messages=[{"role": "user", "content": content}],
            max_tokens=3,
            temperature=0.0,
        )
        ans = (r.choices[0].message.content or "").strip().lower()
        print(f"[game] hand check ({len(imgs)} frames): {ans!r}", flush=True)
        for c in ("rock", "paper", "scissors"):
            if ans.startswith(c):
                return c
        return None
    except Exception as e:
        print(f"[brain] hand check failed: {e}")
        return None


def read_written_word(imgs, english=False):
    """The word handwritten on a paper shown to the camera, letter by letter
    as written (mistakes kept — it's a spelling test), or None. quiz.py —
    imgs: one base64 JPEG or a few taken a moment apart (judged together)."""
    if isinstance(imgs, str):
        imgs = [imgs]
    imgs = [b for b in (imgs or []) if b]
    if _client is None or not imgs:
        return None
    try:
        content = [{"type": "text", "text":
                    (f"A child is showing a handwritten {'English' if english else 'Polish'} "
                     f"word on paper to this webcam for a spelling test ({len(imgs)} "
                     "frame(s) taken a moment apart — read it from the clearest one; "
                     "the paper may be tilted, small or near an edge). Transcribe "
                     "EXACTLY the letters written, keeping any spelling mistakes "
                     + ("(do not correct them)" if english else
                        "(do not correct u/ó, rz/ż, h/ch, ą/ę, missing diacritics)")
                     + ". Return JSON {\"word\": \"...\"} — word empty if no "
                     "writing is readable.")}]
        content += [{"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}}
                    for b in imgs]
        r = _client.chat.completions.create(
            model=CRAFT_MODEL,                 # (the mini model misread hands, 7 Oct)
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}],
            max_tokens=30,
            temperature=0.0,
        )
        word = json.loads(r.choices[0].message.content).get("word", "").strip().lower()
        return word.strip(" .!?,") or None
    except Exception as e:
        print(f"[brain] reading the paper failed: {e}")
        return None


_TIMETABLE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {"name": "timetable", "strict": True, "schema": {
        "type": "object",
        "properties": {
            # first the table copied as it is, then the entries from that copy:
            # reading and sorting out in one go mixed up rows and days
            "transcript": {"type": "string"},
            "readable": {"type": "boolean"},
            "entries": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "days": {"type": "array", "items": {"type": "integer"}},
                    "at": {"type": "string"},
                    "end": {"type": "string"},
                    "lesson_no": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["lesson", "activity"]},
                },
                "required": ["title", "days", "at", "end", "lesson_no", "kind"],
                "additionalProperties": False}},
        },
        "required": ["transcript", "readable", "entries"],
        "additionalProperties": False}},
}

_TIMETABLE_PROMPT = (
    "These {n} photo(s), taken a moment apart, show a weekly schedule on paper held up "
    "to a webcam (usually a Polish school timetable, \"plan lekcji\"; maybe a plan of "
    "classes). Use the sharpest one; another may show a part the first hides.\n"
    "STEP 1 — transcript: copy the table exactly as written, one line per row, cells "
    "separated by \" | \", starting with the header row (lesson number, hours, the "
    "days). Keep abbreviations as written; an empty cell is \"-\"; a cell you cannot "
    "read is \"?\". Check each row's position: a subject belongs to the row its cell is "
    "in, the day of the column above it. A merged cell spanning several rows or days "
    "is that subject in each of them.\n"
    "STEP 2 — entries, from your transcript: title = the subject or activity in Polish, "
    "lowercase unless a name, abbreviations expanded (\"ed. wczesn.\" / \"e.w.\" → "
    "\"edukacja wczesnoszkolna\", \"j. ang.\" → \"angielski\", \"j. pol.\" → "
    "\"polski\", \"mat.\" → \"matematyka\", \"w-f\" / \"WF\" → \"wf\", \"rel.\" → "
    "\"religia\", \"zaj. komp.\" / \"inf.\" → \"informatyka\", \"godz. wych.\" → "
    "\"godzina wychowawcza\", \"świetl.\" → \"świetlica\"); usual subjects: polski, "
    "matematyka, angielski, niemiecki, wf, religia, etyka, plastyka, muzyka, technika, "
    "przyroda, informatyka, historia, geografia, biologia, chemia, fizyka, edukacja "
    "wczesnoszkolna, świetlica. days = weekdays, 0 = Monday … 6 = Sunday; at / end = "
    "start and end as HH:MM (24 h) — when a column gives the hours of each lesson "
    "number, every lesson in that row has those hours; lesson_no = the lesson's number "
    "in its row (0 if none); kind = lesson for EVERY cell of the school timetable's "
    "grid (świetlica, kółko, a club or extra class in a lesson row too), activity only "
    "for classes outside that grid (music school, sport) on a separate plan of classes. "
    "The same title at the same time on several days is ONE entry with all those days. "
    "A time you cannot read: at = \"\" — never guess one. Skip breaks (przerwa) and empty cells. readable = false when this is not a "
    "schedule or nothing can be read.")


def read_timetable(imgs, model=None):
    """A weekly plan on paper held to the camera (a school timetable, a list of
    classes) → {"readable", "entries": [{title, days, at, end, lesson_no,
    kind}]}, or None on failure. schedule.import_paper — 26 Oct: Luna read
    Maja's plan aloud but her reply ran out of tokens before any entry."""
    imgs = [b for b in (imgs or []) if b]
    if _client is None or not imgs:
        return None
    content = [{"type": "text", "text": _TIMETABLE_PROMPT.format(n=len(imgs))}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}}
                for b in imgs]
    for model in dict.fromkeys(m for m in (model, TIMETABLE_MODEL, CRAFT_MODEL) if m):
        req = {"model": model, "response_format": _TIMETABLE_SCHEMA,
               "messages": [{"role": "user", "content": content}]}
        if model.startswith("gpt-5"):        # it may think: it reads small print better
            req.update(max_completion_tokens=12000, reasoning_effort="low")
        else:
            req.update(max_tokens=4000, temperature=0.0)
        try:
            t0 = time.time()
            r = _client.with_options(timeout=90.0).chat.completions.create(**req)
            out = json.loads(r.choices[0].message.content)
        except Exception as e:
            print(f"[brain] reading the timetable with {model} failed: {e!r}", flush=True)
            continue
        print(f"[brain] timetable read by {model} in {time.time() - t0:.1f} s: "
              f"{len(out.get('entries') or [])} entries, readable={out.get('readable')}",
              flush=True)
        print("[brain] timetable transcript:\n" + str(out.get("transcript") or "")[:1500],
              flush=True)
        return out
    return None


# ── Main process ──────────────────────────────────────────────────────────────

def _show(emotion, gesture):
    """The LLM's emotion and gesture drive the face:
      • during the reply: text_to_speech freezes state.emotion for the whole
        utterance, so set it BEFORE speaking
      • after the reply: process() holds it as a face_override for a few
        seconds, then the renderer falls back to neutral"""
    with state.lock:
        state.emotion = emotion.capitalize()
        if gesture in GESTURE_DURATION:              # hands / head
            state.gesture_anim       = gesture
            state.gesture_anim_start = time.time()
        elif gesture in reply_scenes.SCENES:         # facial / hand scene
            state.reply_scene       = gesture
            state.reply_scene_start = time.time()


def _think_filler(answered):
    if not answered.wait(THINK_SOUND_DELAY):
        play_sound(random.choice(THINK_SOUNDS))


_process_lock = threading.RLock()     # one answer at a time, whichever thread asks


_WEATHER_WORDS = re.compile(r"\b(?:pogod\w*|prognoz\w*|temperatur\w*|stopni\w*|pada\w*|"
                            r"padać|padnie|popada\w*|deszcz\w*|śnie\w*|burz\w*|mr[oó]z\w*|"
                            r"parasol\w*|wiatr\w*|wieje|słońc\w*|ciepło|zimno)\b", re.I)


def weather_told(text, gesture):
    """A short weather question answered ("jaka jutro pogoda?", "kiedy przestanie
    padać?"): the window closes after it like after a timer (22 Oct: she kept
    listening after the forecast)."""
    if len(text.split()) > 12 or not _WEATHER_WORDS.search(text):
        return False
    return gesture in ("sunny", "cloudy", "rainy", "snowy") or bool(
        re.search(r"\b(?:pogod|prognoz)", text, re.I))


def _speak_for(turn, sentences):
    activation.join_turn(turn)
    speak_stream(sentences)


def process(text, context=None):
    """context: extra system-prompt text for this one question (news.py).
    Usually called from the voice thread; reading.py's end-after-silence
    calls it from its own — the lock keeps the two from talking over each other."""
    with _process_lock:
        _process(text, context)


def _process(text, context=None):
    text = text.strip()
    if not text:
        return

    print(f"[brain] Processing: {text}")
    global _heard
    _heard = text

    lower = text.lower()

    visual = _wants_vision(lower)
    global _last_low_frame
    with_frame = visual or (VISION_ALWAYS and time.time() - _last_low_frame >= LOW_FRAME_EVERY)
    image  = _camera_jpeg_b64() if with_frame else None
    if image is not None and not visual:
        _last_low_frame = time.time()

    # the answer takes 2-4 s; now and then fill the silence with a "hmm"
    answered = threading.Event()
    if random.random() < themes.get().get("think_chance", THINK_SOUND_CHANCE):   # (Mochi's more)
        threading.Thread(target=_think_filler, args=(answered,), daemon=True).start()

    # Streamed: the face is set when the model gets to the reply, the first
    # sentence is spoken while it writes the rest (see reply_stream.py).
    turn = activation.turn_id()             # a tap calls it off (activation.cancel)
    sentences = queue.Queue()
    speaker = []
    head = {}

    def on_head(emotion, gesture):
        head["_t"] = time.time() - t0
        head["emotion"] = emotion if emotion in EMOTIONS else "neutral"
        head["gesture"] = gesture if gesture in GESTURES else "none"
        answered.set()
        _show(head["emotion"], head["gesture"])
        t = threading.Thread(target=_speak_for, args=(turn, iter(sentences.get, None)),
                             daemon=True)
        t.start()
        speaker.append(t)

    def on_sentence(sentence):
        if _looks_like_json(sentence):
            print(f"[brain] not spoken (JSON): {sentence[:60]!r}", flush=True)
            return
        import timing
        timing.mark("sentence")
        sentence = re.sub(r"^\[[^\]]{1,40}\]\s*", "", sentence)    # no "[Luna] " spoken
        sentences.put(_feminize(sentence, _heard))

    t0 = time.time()
    try:
        result = _ask_openai(text, image, detail="high" if visual else "low", context=context,
                             on_head=on_head, on_sentence=on_sentence)
    finally:
        answered.set()
        sentences.put(None)
    if speaker:
        print(f"[brain] reply started streaming after {head['_t']:.1f}s, "
              f"model done after {time.time() - t0:.1f}s")
    health.note_reply(bool(result), time.time() - t0)
    if activation.turn_cancelled():
        print("[brain] the turn was cancelled — the reply isn't said", flush=True)
        with state.lock:
            state.emotion = "Neutral"
        if speaker:
            speaker[0].join()
        return

    if result and not result[0] and not speaker:     # said to someone else: silence
        return
    if result:
        reply, emotion, gesture = result
        if not speaker:                              # answered without streaming
            _show(emotion, gesture)
        if weather_told(text, gesture) or schedule.asked(text):
            close_after()                            # (main keeps it open if she asked back)
    elif speaker:                                    # broke off mid-answer
        reply, emotion, gesture = "", head["emotion"], head["gesture"]
    else:
        print("[brain] OpenAI failed — using offline reply")
        reply, emotion, gesture = OFFLINE_REPLY, "sad", "shake"
        _show(emotion, gesture)

    try:
        if speaker:
            speaker[0].join()
        elif reply == OFFLINE_REPLY:
            # the network is the likely culprit — and TTS needs it too, so
            # say the apology that was recorded while the cloud was up
            # (an empty account isn't a network fault: say which it is)
            if not play_sound("no_credits" if health.no_credits() else "offline",
                              can_drop=False) and not play_sound("offline", can_drop=False):
                speak(reply)
        else:
            speak(reply)
    finally:
        with state.lock:
            state.emotion             = "Neutral"
            state.face_override       = emotion if emotion != "neutral" else None
            state.face_override_until = time.time() + FACE_OVERRIDE_SECS
