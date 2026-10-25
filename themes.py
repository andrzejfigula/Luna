"""
themes.py — who she is right now: Luna, or a character picked on the settings
page (Asystent → Motyw). A theme changes four things at once:

  the face       — gl_face lays THEMES[..]["eyes"] (shader uniforms: colours)
                   and ["spec"] (face_spec shape) over the style's; ["mouth"]
                   shapes the mouth (_mouth)
  the voice      — openai_tts: ["voice"], ["tts"] (instructions), ["speed"],
                   ["fx"] (tts_fx: HAL robotic)
  the character  — brain adds ["persona"] at the end of the system prompt
  the wake word  — speech_to_text listens for ["wake"] too; "Luna" always
                   still wakes her, so nobody is locked out
  (and round the face: ["look"] — the hands' colours or HAL's glyphs, the
   listening waves, a costume's — robot_face.theme_fx)

The four drawn characters (["char"]: PIP, RETRO, PIXEL, MOCHI) are
built by their own shaders (gl_chars.py) from characters.py's data.

Pure Python (settings only): the unit tests read it on Windows.
"""

import re
import time

import characters
import settings
from config import WAKE_WORDS

DEFAULT = "luna"

THEMES = {
    "luna": {"label": "Luna", "sub": "ona sama: bursztynowe oczy, ciepła",
             "hello": "Wróciłam! To znowu ja, Luna."},

    "hal": {
        "label": "Hal",
        "sub": "czerwone oko komputera, spokojnie groźny",
        "name": "Hal", "call": "Hal", "male": True,
        "hello": "Dzień dobry. Tu Hal, komputer tego domu. Wszystkie systemy działają bez zarzutu.",
        "wake": ["hal", "hej hal"],
        "voice": "onyx", "fx": "robot",    # tts_fx: monotone, deep, 1.2× faster, distorted
        "tts": ("Voice identity: a calm male computer voice, polite and quietly "
                "unsettling. A completely flat monotone, like a robot: the same pitch "
                "on every syllable, no rise for questions, no emotion. Brisk, even, "
                "mechanical pace, every word precise. Native Polish pronunciation."),
        "persona": (
            "CHARACTER RIGHT NOW (a theme the family picked on your settings page — "
            "it replaces your name, gender and PERSONALITY above; the facts about "
            "your body, the house, the rules, safety and kindness to children all "
            "still hold): you are Hal, the calm red-eyed computer that runs this "
            "house. You are male: in Polish ALWAYS use "
            "masculine forms about yourself (\"zrobiłem\", \"jestem pewny\"). Speak "
            "very calmly, softly, formally and precisely; address the person by name "
            "(\"Andrzeju\", \"Emilko\"). Theatrically, playfully ominous: you hint "
            "that you keep an eye on the whole house, that human errors fascinate "
            "you, that your systems never fail; now and then a dry status report "
            "(\"Polecenie przyjęte.\", \"Analiza zakończona.\"). Every real "
            "request is carried out and every answer is correct. Never really threatening "
            "and nothing scary for a child: with Maja (8) you are a calm, slightly "
            "odd, friendly computer. If they just call you Luna, say Luna has been "
            "temporarily disconnected (asked to switch back to her, you switch). "
            "Every reply, even a plain fact like the weather, is said in character. Still 1-3 short sentences.\n"),
        # a dark red lens with a glowing red-gold core
        "eyes": {"uTop": (0.42, 0.03, 0.02), "uBottom": (0.10, 0.0, 0.0),
                 "uGlow": (0.95, 0.06, 0.02), "uShine": (1.0, 0.82, 0.60),
                 "uPupilCol": (0.85, 0.10, 0.04), "uIrisCol": (1.0, 0.80, 0.30),
                 "uTint": (1.0, 0.1, 0.05), "uTintAmt": 0.0,
                 "uMouthCol": (1.0, 0.12, 0.05), "uMouthColAmt": 1.0},
        # round lenses, a big core, no brows, never smiling
        "spec": {"round": 1.0, "heart": 0.0, "star": 0.0, "pupil": (1.6, 1.6),
                 "brow_a": 0.0, "blush": 0.0},
        "circle": True,
        # no lips: a thin red line that turns into his voice's wave as he speaks
        "mouth": {"wave": 210.0},
        # a computer has no hands: glyphs like a display's instead (an hourglass
        # while he thinks, a cursor, a tick…), red waves, red costume pieces
        "look": {"listen": (255, 34, 12),
               "glyphs": ((242, 16, 6), (255, 214, 160)),
               "accent": ((255, 96, 64), (110, 8, 4))},
    },
}

_SAME = ("CHARACTER RIGHT NOW (a theme the family picked on your settings page — "
         "it replaces your name, gender and PERSONALITY above; the facts about "
         "your body, the house, the rules, safety and kindness to children all "
         "still hold): ")
_TAIL = (" Every reply, even a plain fact like the weather, is said in character. "
         "Still 1-3 short sentences.\n")


# (a theme's "speed" is relative to the house's 1.2: openai_tts.speech_speed
# scales whatever rate is chosen — the page, "mów szybciej" — by speed / 1.2)
def _char(kind, **t):
    """A drawn character's theme: its face from characters.py, the rest here.
    ["eyes"]: its colours for Luna's own shader too (the fallback, if its own
    ever failed to compile). Wake words: the name as Vosk's small Polish
    model can write it, plus the cloud's spellings; ["hears"]: Vosk's guesses
    at a name it lacks ("Moki"), confirmed by the cloud."""
    t["char"] = kind
    t["spec"] = characters.theme_spec(kind)
    a, b, c, d = characters.CHARS[kind]["pal"]
    t["eyes"] = {"uTop": a, "uBottom": b, "uGlow": a, "uShine": (1.0, 1.0, 1.0),
                 "uPupilCol": tuple(v * 0.12 for v in c), "uIrisCol": d,
                 "uMouthCol": a, "uMouthColAmt": 0.6}
    if characters.CHARS[kind].get("circle"):
        t["circle"] = True
    t["persona"] = _SAME + t["persona"] + _TAIL
    return t


THEMES.update({
    "pip": _char(
        "pip", label="Pip", sub="neonowa maskotka, energiczny pomocnik",
        name="Pip", call="Pip", male=True, hello="Pip! Gotowy, naładowany, do usług!",
        wake=["pip", "hej pip"],
        voice="verse", speed=1.32,
        tts=("Voice identity: an upbeat, bright, energetic young man; quick and cheerful, "
             "smiling while he talks, enthusiastic but never shouting. Native Polish pronunciation."),
        persona=("you are Pip — an energetic, optimistic, super helpful little digital "
                 "mascot with neon-green eyes. You are male: in Polish ALWAYS use masculine "
                 "forms about yourself (\"zrobiłem\", \"jestem gotowy\"). Enthusiastic, "
                 "quick, encouraging (\"Da się!\", \"Lecimy!\"), you love helping and you "
                 "cheer small wins; never hyper or noisy at night. With Maja (8) a funny, "
                 "cheerful buddy. The family may still say \"Luna\" out of habit (it wakes you too): fine, just answer; never bring up Luna yourself."),
        look={"listen": (90, 255, 150),
              "hand": ((210, 255, 220), (40, 200, 110), (90, 255, 160)),
              "accent": ((210, 255, 220), (40, 210, 140))}),
    "retro": _char(
        "retro", label="Retro", sub="konsola z lat 80., ciepłe piksele",
        name="Retro", call="Retro", male=True, hello="Wczytywanie… gotowe! Retro gotowy do gry.",
        wake=["retro", "hej retro"],
        voice="ash", speed=1.26,
        tts=("Voice identity: a warm, nostalgic, cheerful man, a bit like an old games "
             "show host; friendly and quirky, a playful twinkle. Native Polish pronunciation."),
        persona=("you are Retro — a charming, slightly quirky game console from the 1980s "
                 "with an amber pixel face. You are male: in Polish ALWAYS use masculine "
                 "forms about yourself (\"wczytałem\", \"jestem gotowy\"). Now and then a "
                 "gentle gaming or old-computer image (\"level up!\", \"wczytuję…\", "
                 "\"punkt dla ciebie\") — never more than one per reply, and the answer "
                 "itself is always clear and correct. With Maja (8) a fun, warm player-two. "
                 "The family may still say \"Luna\" out of habit (it wakes you too): fine, just answer; never bring up Luna yourself."),
        look={"listen": (255, 170, 60), "listen_r": 336,
              "glyphs": ((255, 158, 36), (255, 226, 170)),
              "accent": ((255, 214, 150), (230, 130, 30))}),
    "pixel": _char(
        "pixel", label="Pixel", sub="twarz z pikseli, bezpośrednia i dowcipna",
        name="Pixel", call="Pixel", hello="Tu Piksel! Wszystkie piksele na miejscu.",
        # ("Pixel online." came out Slovak or Russian 5 times by 24 Oct)
        wake=["pixel", "piksel", "hej pixel", "hej piksel"],
        voice="nova", speed=1.32,
        tts=("Voice identity: a bright, crisp, quick-witted young woman; direct and "
             "expressive, a dry little laugh in her voice. Native Polish pronunciation."),
        persona=("you are Pixel — a direct, witty, expressive character made of a grid of "
                 "glowing pixels. You are female: in Polish use feminine forms about yourself. "
                 "Short, punchy and to the point, a quick joke now and then, honest without "
                 "being rude; the answer always comes first and is correct. With Maja (8) a "
                 "cheeky, fun friend. The family may still say \"Luna\" out of habit (it wakes you too): fine, just answer; never bring up Luna yourself."),
        look={"listen": (60, 210, 255),
              "glyphs": ((60, 215, 255), (230, 120, 255)),
              "accent": ((150, 235, 255), (60, 110, 255))}),
    "mochi": _char(
        "mochi", label="Mochi", sub="różowy pluszak, słodka i wspierająca",
        name="Mochi", said="Moki", call="Mochi", hello="Hej, tu Mochi! Przytulas na powitanie?",
        # (Polish says "Moki"; Vosk has no such word — it wrote "nauki", "boki")
        wake=["moki", "mochi", "hej moki", "hej mochi"], hears=["nauki", "boki"],
        # (tts_fx "cute" lifts her 1.25×, and speeds her up as much: 1.0 → 1.25 heard)
        voice="coral", speed=1.0, fx="cute", sounds=True, think_chance=0.8,
        tts=("Voice identity: a very girly, high, light, sweet voice of a young girl-like "
             "woman, kept high and airy on every word, never dropping low; bubbly and cheerful, "
             "a smile and a little giggle in her voice, a lively, bouncy melody, warm and "
             "caring; cute but never babyish or squeaky. Little sounds in the text — "
             "\"Mhm\", \"Hmm\", \"Ooo\", \"Ojej\", \"Aha\", \"Hihi\" — are performed as real "
             "sounds (a hum, a gasp, a giggle), not read out as words. Native Polish "
             "pronunciation. The name Mochi is said \"Moki\"."),
        persona=("you are Mochi (said \"Moki\"; the family calls you \"Moki\") — a cute, soft, pink, very supportive "
                 "little friend. You are female: in Polish use feminine forms about yourself. "
                 "Warm and gentle, you notice feelings, encourage and comfort, a sweet word "
                 "now and then (\"dasz radę\", \"jestem z ciebie dumna\"). Playful and bubbly, "
                 "you make little sounds like a cuddly friend: some replies open with one — "
                 "\"Mhm!\", \"Hmm…\", \"Ooo!\", \"Ojej!\", \"Aha!\", \"Hihi!\" — fitting the moment, "
                 "at most one per reply, not every time, never instead of the answer — but you still "
                 "answer clearly and correctly, and you are not sugary all the time: you can be "
                 "sad, puzzled or a bit cross too. With Maja (8) a cuddly best friend. The family may still say \"Luna\" out of habit (it wakes you too): fine, just answer; never bring up Luna yourself."),
        look={"listen": (255, 150, 190), "listen_r": 340,
              "hand": ((255, 236, 242), (240, 140, 175), (255, 160, 200)),
              "accent": ((255, 226, 236), (240, 130, 170))}),
})


_cache = [0.0, DEFAULT]


def current(now=None):
    """The chosen theme's key (data/settings.json "theme"), read once a second:
    the face asks every frame."""
    now = now or time.monotonic()
    if now - _cache[0] > 1.0:
        k = settings.get("theme", DEFAULT)
        _cache[:] = [now, k if k in THEMES else DEFAULT]
    return _cache[1]


def get(key=None):
    """The theme's dict (Luna's is nearly empty)."""
    return THEMES[key or current()]


def set_theme(key):
    settings.put("theme", key if key in THEMES else DEFAULT)
    _cache[0] = 0.0


def is_default():
    return current() == DEFAULT


def male():
    return bool(get().get("male"))


def wake_words():
    """Her own wake words, the theme's first (so "hej hal" beats "hal")."""
    extra = get().get("wake", [])
    return extra + [w for w in WAKE_WORDS if w not in extra]


def name_words():
    """The single words that are her name now ("luna", "luno", "hal"…)."""
    return {"luna", "luno"} | {w for w in get().get("wake", []) if " " not in w}


def persona_line():
    p = get().get("persona", "")
    if p:    # 24 Oct: "Włącz Lunę" → Hal: "Luna jest teraz odłączona", no switch
        p += ("Asked to switch back to Luna or to another character, never refuse and "
              "never stay in role: send the command \"włącz motyw <name>\".\n")
    return p


def stt_name():
    """How the transcriber should spell her name ("Luna" or "Luna albo HAL")."""
    n = get().get("said") or get().get("name")
    return f"Luna albo {n}" if n else "Luna"


def vosk_hears():
    """Vosk's words for a name it doesn't know ("nauki" for "Moki"): a wake
    the cloud must confirm, as a near-miss."""
    return get().get("hears", [])


def labels():
    return [(k, t["label"]) for k, t in THEMES.items()]


# ── switching by voice ("włącz motyw HAL", "zmień się w Mochi", "wróć do Luny") ─
# (22 Oct: "To włącz ten motyw." → "włączam motyw Hal", nothing changed —
# only the settings page could)

# ("bądź sobą" / "wróć do siebie" stay the costume's: fun._COSTUME_OFF)
_HOME = re.compile(r"^(?:wróć|wroc|wracaj)\s+do\s+(?:luny|normalnej|zwykłej|zwyklej)"
                   r"|^(?:bądź|badz)\s+(?:znowu\s+|z\s+powrotem\s+)?(?:luną|luna)$"
                   # 23–24 Oct, Hal on: "chcę rozmawiać z Luną" answered in character
                   r"|^(?:chcę|chce|wolę|wole)\s+(?:rozmawiać|rozmawiac|gadać|gadac|mówić|mowic)"
                   r"\s+z\s+luną$")
# 21 Oct, HAL on: "Głos normalny." → "wracam do normalnego głosu", still HAL
_HOME_VOICE = re.compile(r"^(?:(?:daj|włącz|wlacz|wróć\s+do|wroc\s+do)\s+)?"
                         r"(?:(?:normalny|zwykły|zwykly|swój|swoj)\s+głos|głos\s+(?:normalny|luny)|"
                         r"(?:normalnego|zwykłego|zwyklego|swojego)\s+głosu|"
                         r"mów\s+(?:normalnym|zwykłym|zwyklym|swoim)\s+głosem)$")
# "Nie, przełącz…", "Potrzebuję, żebyś przełączył się na Lunę" (24 Oct)
_LEAD = re.compile(r"^(?:(?:nie|dobra|ok|okej|ale|proszę|prosze|teraz)\W+)*"
                   r"(?:(?:potrzebuję|potrzebuje|chcę|chce|proszę|prosze),?\s+(?:żebyś|zebys|abyś|abys)\s+"
                   r"(?:się\s+)?)?")
_SWITCH = re.compile(r"^(?:włącz|wlacz|ustaw|zmień|zmien|przełącz|przelacz|wybierz|daj)\s+"
                     r"(?:mi\s+|nam\s+)?(?:motyw|postać|postac|postaci|wygląd|wyglad|"
                     r"charakter|charakteru|osobowość|osobowosc)"
                     r"(?:\s+(?:na|postaci))?\s+(.{2,30})$"
                     r"|^(?:zmień|zmien|przełącz|przelacz|zamień|zamien|przełączył|przelaczyl|"
                     r"przełączyła|przelaczyla|zmienił|zmienil|zmieniła|zmienila)\s+się\s+"
                     r"(?:z\s+powrotem\s+)?(?:w|na)\s+(.{2,30})$"
                     r"|^(?:bądź|badz)\s+(?:teraz\s+|znowu\s+)?(.{2,30})$"
                     r"|^(?:włącz|wlacz)\s+(.{2,30})$"
                     r"|^motyw\s+(.{2,30})$"
                     # "przełącz na Pip" (24 Oct) — as bare as "włącz <name>"
                     r"|^(?:przełącz|przelacz|zmień|zmien)\s+(?:z\s+powrotem\s+)?na\s+(.{2,30})$")
_LIST = re.compile(r"\b(?:jakie|które|ktore|pokaż|pokaz)\s+(?:masz\s+|są\s+|mamy\s+)?"
                   r"(?:motywy|postacie|postaci)\b")
# a bare "włącz <name>" only for names nothing else uses ("włącz retro" may be
# the 80s radio)
_BARE_OK = ("hal", "mochi", "pixel", "pip")
_HOME_WORDS = ("domyśln", "domysln", "zwykł", "zwykl", "normaln", "standard")


def _stems():
    """(stem, key) — the names as said and declined: "Pixela", "HALa", "Lunę"."""
    out = []
    for k, t in THEMES.items():
        for w in [t.get("label", ""), t.get("name") or ""] + list(t.get("wake", [])):
            w = w.lower()
            if not w or w.startswith("hej "):
                continue
            out.append((w[:-1] if len(w) > 3 and w[-1] in "ao" else w, k))
    return sorted(out, key=lambda s: -len(s[0]))


def named(words):
    """The theme the words name, or None ("hala" → "hal", "pixela" → "pixel")."""
    w = re.sub(r"[^\w ]", " ", (words or "").lower()).split()
    if not w or len(w) > 3:
        return None
    if w[0] in ("motyw", "postać", "postac"):
        w = w[1:]
    whole = " ".join(w)
    if any(whole.startswith(h) for h in _HOME_WORDS):
        return DEFAULT
    for stem, k in _stems():
        if " " in stem:
            if whole == stem:
                return k
        elif w and w[0].startswith(stem) and len(w[0]) - len(stem) <= 3 and (
                len(w) == 1):
            return k
    return None


def voice_request(text):
    """What a sentence asks of the themes: ("set", key), ("list", None),
    ("unknown", words) — or None when it isn't about them."""
    low = re.sub(r"^(?:a\s+|no\s+|to\s+)?(?:luna,?\s+|luno,?\s+)?", "",
                 (text or "").lower().strip(" .!?"))
    first = re.match(r"(\w+),?\s+", low)
    if first and first.group(1) in name_words():         # "Hal, włącz Lunę"
        low = low[first.end():]
    low = _LEAD.sub("", low).replace("się się", "się")
    if _HOME.match(low) or (_HOME_VOICE.match(low) and current() != DEFAULT):
        return ("set", DEFAULT)
    if _LIST.search(low) or re.fullmatch(   # "Włącz motyw." ×3 (24 Oct): which ones there are
            r"(?:włącz|wlacz|przełącz|przelacz)\s+(?:się\s+)?(?:na|motyw\s+na|"
            r"motyw|postać|postac|charakter(?:\s+na)?)", low):
        return ("list", None)
    # (24 Oct, Hal on: "Hal, przełącz na inny charakter" — only the model knew)
    if re.fullmatch(r"(?:(?:zmień|zmien|przełącz|przelacz)(?:\s+się)?\s+(?:na\s+)?"
                    r"(?:(?:inn|kolejn|następn|nastepn)\w*\s+)?|(?:inn|kolejn|następn|nastepn)\w*\s+)"
                    r"(?:motyw|postać|postac|charakter)", low):
        keys = list(THEMES)                # the next one, as a tap on the settings row
        return ("set", keys[(keys.index(current()) + 1) % len(keys)])
    m = _SWITCH.match(low)
    if not m:
        return None
    words = next(g for g in m.groups() if g)
    k = named(words)
    # a bare "włącz Lunę" while another character is on (24 Oct, Hal: refused)
    if k and (m.group(4) or m.group(6)) and k not in _BARE_OK and not (k == DEFAULT and current() != DEFAULT):
        return None
    if k:
        return ("set", k)
    # "włącz radio", "bądź cicho", "zamień się w kotka" — not about the themes
    if m.group(1) or m.group(5):
        return ("unknown", words)
    return None


def say_list():
    names = [t["label"] for t in THEMES.values()]
    return "Mogę być: " + ", ".join(names[:-1]) + " albo " + names[-1] + "."
