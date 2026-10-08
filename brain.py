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
from openai import OpenAI

import reply_scenes
import birthdays
import errands
import faces
import hedge
import mood as luna_mood     # ("mood" is the user's mood inside _ask_openai)
import relationship
from reply_stream import ReplyStream
import body
import health
import memory
import lists
import timers
import weather

from text_to_speech import speak, speak_stream, play_sound
from shared_state import state
from config import (
    FACE_OVERRIDE_SECS,
    GESTURE_DURATION,
    KNOWLEDGE_PATH,
    OPENAI_API_KEY,
    OPENAI_MODEL, CRAFT_MODEL, CHAT_MODEL, CHAT_HEDGE_AFTER,
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
    return (f"{now.strftime('%A, %d %B %Y, %H:%M')} "
            f"({LUNA_TIMEZONE if _TZ else 'system'}, {now.strftime('%Z')}, "
            f"UTC{off[:3]}:{off[3:]})")

# a question about dates: weekdays, "the last Sunday of…", the clock change
_DATEY = re.compile(
    r"\b(?:kiedy|którego|ktorego|jaki\s+dzie[nń]|niedziel|poniedzia|wtor|czwart|"
    r"piąt(?:ek|ku)|sobot|weekend|tydzie|tygodni|miesi[aą]c|stycz|kwie[ct]|sierp|"
    r"wrze[sś]|październik|paździer|listopad|zmian\w*\s+czasu|"
    r"czas\w*\s+(?:letni|zimowy)|ile\s+dni|święt|swiet|wigili|sylwest|wielkanoc|"
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
                (date(y, 12, 25), "Boże Narodzenie"), (date(y, 12, 31), "Sylwester")]
    out = sorted((d, name) for d, name in out if d > day)[:n]
    return ", ".join(f"{name} {d:%d.%m} ({d:%A}, in {(d - day).days} days)" for d, name in out)



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


_EN = {"the", "a", "an", "is", "are", "what", "how", "can", "you", "me", "my", "to", "for",
        "set", "add", "turn", "on", "off", "tell", "please", "it", "do", "does", "time",
        "timer", "list", "radio", "weather", "minutes", "joke", "play", "in", "of", "and"}


def _language_line(text):
    """An English sentence gets an English answer — 7 Oct probe: "Set a timer
    for five minutes" → "Jasne, pięć minut." (the prompt's Polish examples
    win over "speak the user's language")."""
    low = (text or "").lower()
    words = re.findall(r"[a-ząćęłńóśźż']+", low)
    if len(words) < 3 or re.search(r"[ąćęłńóśźż]", low) or translator():
        return ""
    if sum(w in _EN for w in words) < max(2, len(words) // 3):
        return ""
    return "THIS MESSAGE IS IN ENGLISH — write \"reply\" in English.\n"


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
    return (f"This is {who}'s first talk with you today: after answering, add ONE short "
            "sentence with what matters for their day — rain or cold from the weather "
            "line (e.g. \"weź parasol\"), or a reminder set for today. Nothing if neither.\n")


def _just_called(text="", secs=12):
    """Was her name said a moment ago? Then this sentence came with it (the
    wake word is cut off before the model sees the text — 7 Oct probe:
    "Jestem zdenerwowany" got silence as "not for me"). Not for long or
    English sentences: the one real case in the log was a false wake in an
    English meeting, rightly kept quiet."""
    if len(text.split()) > 12 or _language_line(text):
        return False
    with state.lock:
        return time.time() - getattr(state, "last_wake_time", 0.0) < secs


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
        import faces
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
    return line + f" Coming up: {_holidays_ahead(day)}.\n"


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


from polish import feminize, offer_only, empty_promise, neutral_you   # (polish.py)


def _feminize(text):
    """Her own forms feminine; and with nobody recognised in front of her, no
    guessed gender for "you" either."""
    text = feminize(re.sub(r"\s*(?:\\n|\n)+\s*", " ", text or ""))   # a poem's "\n"
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
                with a label);
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
                "codziennie" → "daily", "w dni robocze / od poniedziałku do
                piątku" → "weekdays", "w weekendy" → "weekends", "w każdy
                wtorek" → "weekly" (with "at" on the next Tuesday), "co
                miesiąc" → "monthly", birthdays / "co roku" → "yearly"
                (reminders and alarms only).
                Lists: {{"type":"list_add","label":"mleko","list":"zakupy",
                ...}} — one action per item ("dopisz mleko i chleb" = two);
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
                357 | Nowy Świat>", "wyłącz radio", "następna stacja",
                "ciszej", "głośniej", "mów wolniej", "mów szybciej", "mów
                normalnie", "włącz lampkę", "wyłącz lampkę", "lampka na
                <kolor>", "włącz szum deszczu / morza", "biały szum",
                "wyłącz szum", "włącz napisy", "wyłącz napisy", "pokaż zegar",
                "pokaż plan dnia", "pokaż listę zakupów", "przepis na <danie>
                krok po kroku" (cooking along on the screen), "przekaż <Imię>,
                że …" (a note you say to that person when you next see them),
                "zrób zdjęcie", "nagraj wiadomość dla <Imię>", "pokaż na ekranie:
                <tekst>" (a name, number or word big on her screen for 30 s — when
                they want to see it or copy it down), "wyszukaj w internecie:
                <zapytanie>" (see below), "przyciemnij ekran", "zgaś ekran",
                "rozjaśnij ekran", and to START A GAME (it then talks
                itself — your reply only says something short like "Super,
                gramy!"): "zagrajmy w kamień papier nożyce", "zadaj mi
                zagadkę", "zagrajmy w memory", "zagrajmy w kółko i krzyżyk",
                "zagrajmy w 20 pytań" (you think of an animal), "zgadnij, o
                czym myślę" (they think, you guess), "zróbmy quiz z
                matematyki / angielskiego / stolic", "zagrajmy w zegar",
                "zagrajmy w zgadywankę" (you think of a number 1–100); and
                "zróbmy ćwiczenie oddechowe" (a calm guided breathing circle —
                when they say yes to breathing together). A game
                only once ONE game was chosen — named by them, or a "tak" to
                the single game you proposed; while you list options, no
                command. Never play a game inside your reply (no riddle or
                quiz question of your own) — start it with its command.
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
                that does it — if there is none, say you can't. The same for
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
- "głośniej" / "ciszej" / "głośność na 40", "mów wolniej" / "szybciej"
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
  list ("zacznij poranek" walks through the list "poranek")
- the news: "jakie są wiadomości?" reads the latest headlines (RMF24) —
  never invent news, not even vague ones ("ważne spotkania międzynarodowe");
  if news headlines are not in this prompt, suggest asking "jakie są
  wiadomości?"
- the internet: the command "wyszukaj w internecie: <krótkie zapytanie>"
  looks something up (a few seconds) and you then answer from what it found.
  Use it when they ask for current or specific facts you don't know for sure
  — specifications, prices, opening hours, results, details of an event —
  and then just say "Sprawdzam w internecie." (no guess). Anything that
  changes — exchange rates, prices, scores, today's events — ALWAYS through
  the search, never a number from memory. Exact calendar facts you can easily
  get wrong — name days (imieniny), a holiday's date in another country,
  someone's birthday you weren't told — also through the search. Not for things you
  know, not for chat. "Poszukaj w internecie …" said to you does it too.
- internet radio: "włącz radio", "włącz Trójkę" / RMF FM / ZET / 357 / Nowy
  Świat or any station by name, "wyłącz radio za 30 minut". You can't pick
  songs or play Spotify — if asked for music, suggest a station instead.
  "budź mnie radiem" makes wake-up alarms start the radio (the app does it;
  you just set the alarm as usual)
- you know the people of this home by face ("Luna, jestem Ola" teaches you a
  new one), greet them by name, remember their birthdays ("Maja ma urodziny
  12 maja"), pass on notes when you see them ("przekaż Mai, żeby…",
  "codziennie o 20:30 przypominaj Mai, że pora spać"), and voice messages
  for a person ("nagraj wiadomość dla Emilki")
- for kids: riddles ("zadaj mi zagadkę"), a dictation checked on paper with
  your camera ("zróbmy dyktando"), maths and English quizzes, reading a book
  page aloud ("przeczytaj mi tę stronę"), homework hints
- the weather once someone says "pogoda dla <town>", the news ("jakie są
  wiadomości?"), a coloured night lamp ("lampka na niebiesko")
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
- voice effects: "zmień mój głos (jak wiewiórka / jak robot / od tyłu)" — the
  next sentence is played back changed
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
                                    "enum": ["none", "daily", "weekdays", "weekends",
                                             "weekly", "monthly", "yearly"]},
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

def _wants_vision(lower):
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
        if calc.arithmetic(text or "") and commands._child_here():
            return CRAFT_MODEL
    except Exception:
        pass
    return CHAT_MODEL


def _ask_openai(text, image_b64=None, detail="low", on_head=None, on_sentence=None,
                context=None):
    """Returns (reply, emotion, gesture) or None on any failure.

    With on_head / on_sentence the answer is streamed: the face is set and
    the first sentence spoken while the model is still writing the rest."""
    if _client is None:
        return None
    lang = translator()
    if lang:
        # The rule in the system prompt alone was ignored in testing (she
        # chatted back); the instruction has to sit right next to the words.
        text = (f"[TRYB TŁUMACZA — nie odpowiadaj na to, tylko przetłumacz "
                f"dokładnie: na {lang}, jeśli to po polsku; na polski, jeśli to "
                f"w języku {lang}] {text}")
        image_b64 = None                       # interpreting needs no camera
    # the same lesson for English: next to the words, not only in the system
    # prompt ("Set a timer for five minutes" → "Jasne, pięć minut", 7 Oct)
    en_hint = (" (in English — reply in English; actions keep their Polish labels "
               "and list items, e.g. \"włącz radio\", \"mleko\")") if _language_line(text) else ""
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
                  + memory.day_line(text)
                  + _language_line(text)
                  + (_morning_line() if not translator() else "")
                  + ("They have just said your name — this message is for you "
                     "(to_luna true).\n" if _just_called(text) else "")
                  + _variety_rule()
                  + _translator_rule()
                  + _length_rule()
                  + faces.prompt_line()
                  + relationship.prompt_line()
                  + luna_mood.prompt_line()
                  + birthdays.prompt_line()
                  + errands.prompt_line()
                  + _mood_rule(image_b64 is not None)
                  + body.prompt_line()
                  + weather.prompt_line()
                  + timers.prompt_block()
                  + lists.prompt_block()
                  + _cooking_line()
                  + memory.prompt_block()
                  + (context or ""))          # e.g. news headlines, this question only

        import timing
        timing.mark("model")
        request = model_params(dict(model=model_for(text),
                       messages=[{"role": "system", "content": system}, *_history],
                       max_tokens=OPENAI_MAX_TOKENS,
                       temperature=OPENAI_TEMPERATURE,
                       response_format=_RESPONSE_FORMAT))
        if on_head is None:
            response = _client.chat.completions.create(**request)
            raw = _message_json(response.choices[0].message)
        else:
            rs = ReplyStream(on_head, on_sentence)
            finish, refusal = None, ""
            for chunk in hedge.hedged(    # a slow start gets a second request (hedge.py)
                    lambda: _client.chat.completions.create(stream=True, **request),
                    CHAT_HEDGE_AFTER, "model"):
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
        # the history tags speakers ("[Maja] …"); a reply must never copy that
        reply   = re.sub(r"^\[[^\]]{1,40}\]\s*", "", reply)    # ("[Andrzej, with Maja]")
        fixed   = _feminize(reply)
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
        if not translator():                 # interpreting: the words aren't for her
            tone = str(data.get("user_tone", "neutral")).lower()
            relationship.note(tone, text)
            luna_mood.note(relationship.who() if relationship.who() != relationship.SOMEONE
                      else None, tone)
        if data.get("to_luna") is False and _just_called(text):
            if not reply.strip():
                reply = "Jestem tutaj. Opowiedz mi, co się dzieje."
                if on_sentence:
                    on_sentence(reply)
            print("[brain] her name was just said — answering", flush=True)
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
        if data.get("to_luna") is False and not re.search(r"\bluna\b|\bluno\b", text.lower()):
            print(f"[brain] not said to me — staying quiet ({reply[:60]!r})", flush=True)
            with state.lock:                     # they talk to each other: stop
                state.conversation_active = False   # listening (next time: "Luna")
            if _history and _history[-1]["role"] == "user":
                _history.pop()                   # side talk is not our conversation
            return "", "neutral", "none"
        if data.get("actions") and offer_only(reply):
            # "Może dopiszmy warzywa?" — still asking: nothing happens yet (the
            # prompt says so, but the model added the items anyway now and then)
            print(f"[brain] offer, not done — {len(data['actions'])} action(s) held back",
                  flush=True)
            data["actions"] = []
        set_now = timers.apply(data.get("actions") or [])
        lists.apply(data.get("actions") or [])
        if any("nothing matched" in d for d in set_now or []) and not re.search(
                r"\bnie\s+(?:mam|widzę|ma)\b", reply, re.I):
            # "Jasne, usunę przypomnienie o basenie." — there was none (7 Oct
            # probe): say so rather than leave a removal that never happened
            extra = "Ojej, właściwie nie widzę takiego przypomnienia — nie było czego usuwać."
            print("[brain] cancel matched nothing — correcting the reply", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        other = [a for a in data.get("actions") or []
                 if a.get("type") not in ("timer", "reminder", "alarm", "cancel")]
        if empty_promise(reply, set_now + other):
            # judged by what was really set (a reminder without a usable time
            # sets nothing); the promise becomes a question — "o 19" answers it
            extra = "O której mam ci przypomnieć?"
            print(f"[brain] promised a reminder without one — asking: {extra}", flush=True)
            if on_sentence:
                on_sentence(extra)
            reply = f"{reply} {extra}"
        import reading
        if reading.she_asks(reply) and not reading.armed() and not translator():
            # "Przeczytaj mi oba" — then she listens to the whole reading
            # (reading.py) instead of answering it line by line
            if on_sentence:
                on_sentence(reading.HINT)
            reply = f"{reply} {reading.HINT}"
            import commands
            reading.start(lambda s: None, commands.reading_done, intro=None, question=text)
        searched = False
        for a in data.get("actions") or []:
            if a.get("type") == "command":
                label = str(a.get("label", ""))
                searched = searched or label.lower().startswith("wyszukaj w internecie")
                try:
                    run_command(label, reply)
                except Exception as e:
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

        # keep history text-only: images are large and only matter for the
        # turn they were asked in
        _history[-1] = {"role": "user", "content": _who_said(text)}
        _history.append({"role": "assistant", "content": reply})
        save_history()
        if not translator():                 # interpreting is not about the user
            with state.lock:
                person = state.person
            # "[Kasia] …": the memory can tell whose plans and likes these are
            memory.record(_who_said(text) if person else text, reply)
        body.note_conversation()

        print(f"[brain] OpenAI ({emotion}, {gesture}, you: {mood}"
              f"{', commented' if data.get('mood_comment') else ''}): {reply}")
        return reply, emotion, gesture

    except Exception as e:
        print(f"[brain] OpenAI error: {e}")
        if _history and _history[-1]["role"] == "user":
            _history.pop()
        return None


# ── Things she did herself, without the model ─────────────────────────────────

_COMMAND_OK = re.compile(
    r"^(?:włącz|wyłącz|wlacz|wylacz)\s+(?:radio|rmf|radio\s+zet|trójkę|trojke|jedynkę|jedynke|"
    r"dwójkę|dwojke|radio\s+357|nowy\s+świat|nowy\s+swiat|lampkę|lampke|szum\w*|napisy|"
    r"biały\s+szum)\b|^następna\s+stacja$|^(?:ciszej|głośniej)$|^mów\s+(?:wolniej|szybciej|"
    r"normalnie)$|^lampka\s+na\s+\w+$|^biały\s+szum$|^pokaż\s+(?:zegar|plan\s+dnia|"
    r"listę\s+zakupów)$|^przepis\s+na\s+[\w ]{2,40}\s+krok\s+po\s+kroku$|"
    r"^przekaż\s+\w+,?\s+(?:że|żeby)\s+.{3,120}$|^zrób\s+(?:mi\s+|nam\s+)?zdjęcie$|"
    r"^nagraj\s+wiadomość(?:\s+dla\s+\w+)?$|^pokaż\s+na\s+ekranie[:,]?\s+.{1,80}$"
    r"|^wyszukaj\s+w\s+internecie[:,]?\s+.{3,200}$"
    r"|^(?:przyciemnij|zgaś|rozjaśnij)\s+ekran$", re.I)
# a game she offered and they said "tak" (7 Oct probe: "Nudzi mi się" → "Tak"
# → "zagrajmy w kamień, papier, nożyce" — not allowed, nothing started). A
# game talks itself (intro, questions), so these run with her voice.
_GAME_OK = re.compile(
    r"^(?:zagrajmy\s+w\s+(?:kamień,?\s+papier,?\s+nożyce|memory|kółko\s+i\s+krzyżyk|"
    r"20\s+pytań|zegar|zgadywankę|zagadki)|zadaj\s+mi\s+zagadkę|zgadnij,?\s+o\s+czym\s+myślę|"
    r"zróbmy\s+quiz\s+ze?\s+(?:matematyki|angielskiego|stolic))$", re.I)
# self-voiced like a game, but not a game (no game offer needed): the breathing
# circle she invited them to ("Chodź, oddychajmy razem" → "Tak" — 7 Oct probe)
_VOICED_OK = re.compile(r"^zróbmy\s+ćwiczenie\s+oddechowe$", re.I)


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
            and bool(re.search(r"\?|\bchcesz|\bmożemy|\bmozemy|\bwybierz|\bzagramy|"
                               r"\bzagrajmy|\bmogę\s+(?:zaproponować|zadać)", said, re.I)))


def _asks_to_choose(reply):
    """Her reply still lists games to pick from ("Wybierz: kamień, papier,
    nożyce, zgadywanka albo zagadka") — then no game has been chosen yet."""
    names = len(re.findall(r"kamień|kółk|zagadk|zgadywank|memory|quiz|pytań|zegar", reply or "", re.I))
    return names >= 2 and bool(re.search(r"\bwybierz|\bczy\s+wolisz|\balbo\b.*\?|\bco\s+wybierasz",
                                         reply or "", re.I))


def run_command(label, reply=""):
    """The model's "command" action: one of the app's own switches, run
    through the local command handler (which the model can't reach) —
    whitelisted, silent (the model's reply already confirms it). A game
    from _GAME_OK speaks for itself."""
    label = label.strip().rstrip(".!")
    game = bool(_GAME_OK.match(label))
    if not (game or _COMMAND_OK.match(label) or _VOICED_OK.match(label)):
        print(f"[brain] command not allowed: {label!r}", flush=True)
        return False
    import commands
    if _VOICED_OK.match(label):
        from text_to_speech import speak, play_sound
        done = commands.handle(label, speak, play_sound)
        print(f"[brain] {label!r}: {'started' if done else 'not understood'}", flush=True)
        return bool(done)
    if game and _asks_to_choose(reply):
        print(f"[brain] game {label!r} while her reply asks to choose — not started", flush=True)
        return False
    if game and not game_was_offered():
        # (7 Oct probe: "Pobawimy się?" → she listed three games AND started
        # one; a game only follows her offer and their answer)
        print(f"[brain] game {label!r} without an offer first — not started", flush=True)
        return False
    if game:
        from text_to_speech import speak, play_sound
        done = commands.handle(label, speak, play_sound)
        print(f"[brain] game {label!r}: {'started' if done else 'not understood'}", flush=True)
        return bool(done)
    done = commands.handle(label, lambda *a, **k: None, lambda *a, **k: True)
    print(f"[brain] command {label!r}: {'done' if done else 'not understood'}", flush=True)
    return bool(done)


def last_reply():
    """What she said last (the history's newest answer), or ""."""
    for m in reversed(_history):
        if m.get("role") == "assistant":
            return str(m.get("content", ""))
    return ""


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
        import faces
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

_BRIEFING = """You greet someone who just came back to their desk — the
first time you see them today. Write ONE short spoken greeting in Polish,
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
Feminine forms about yourself; THEIR gender from their name."""


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
                      if who else "")
                   + weather.prompt_line()
                   + faces.prompt_line() + relationship.prompt_line()
                   + birthdays.prompt_line()
                   + timers.prompt_block() + lists.prompt_block()
                   + memory.prompt_block())
        r = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": _PERSONA.strip() + "\n\n" + prompt},
                      {"role": "user", "content": context}],
            max_tokens=90,
            temperature=0.8,
        )
        text = _feminize((r.choices[0].message.content or "").strip().strip('"'))
        print(f"[brain] greeting{' for ' + who if who else ''}: {text}")
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

    lower = text.lower()

    visual = _wants_vision(lower)
    global _last_low_frame
    with_frame = visual or (VISION_ALWAYS and time.time() - _last_low_frame >= LOW_FRAME_EVERY)
    image  = _camera_jpeg_b64() if with_frame else None
    if image is not None and not visual:
        _last_low_frame = time.time()

    # the answer takes 2-4 s; now and then fill the silence with a "hmm"
    answered = threading.Event()
    if random.random() < THINK_SOUND_CHANCE:
        threading.Thread(target=_think_filler, args=(answered,), daemon=True).start()

    # Streamed: the face is set when the model gets to the reply, the first
    # sentence is spoken while it writes the rest (see reply_stream.py).
    sentences = queue.Queue()
    speaker = []
    head = {}

    def on_head(emotion, gesture):
        head["_t"] = time.time() - t0
        head["emotion"] = emotion if emotion in EMOTIONS else "neutral"
        head["gesture"] = gesture if gesture in GESTURES else "none"
        answered.set()
        _show(head["emotion"], head["gesture"])
        t = threading.Thread(target=speak_stream, args=(iter(sentences.get, None),),
                             daemon=True)
        t.start()
        speaker.append(t)

    def on_sentence(sentence):
        import timing
        timing.mark("sentence")
        sentence = re.sub(r"^\[[^\]]{1,40}\]\s*", "", sentence)    # no "[Luna] " spoken
        sentences.put(_feminize(sentence))

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

    if result and not result[0] and not speaker:     # said to someone else: silence
        return
    if result:
        reply, emotion, gesture = result
        if not speaker:                              # answered without streaming
            _show(emotion, gesture)
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
            if not play_sound("offline", can_drop=False):
                speak(reply)
        else:
            speak(reply)
    finally:
        with state.lock:
            state.emotion             = "Neutral"
            state.face_override       = emotion if emotion != "neutral" else None
            state.face_override_until = time.time() + FACE_OVERRIDE_SECS
