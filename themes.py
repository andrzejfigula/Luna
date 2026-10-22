"""
themes.py — who she is right now: Luna, or a character picked on the settings
page (Ekran → Motyw). A theme changes four things at once:

  the face       — gl_face lays THEMES[..]["eyes"] (shader uniforms: colours,
                   uSquare for square shapes) and ["spec"] / ["spec_add"] (face_spec
                   shape) over the style's; ["mouth"] shapes the mouth (_mouth)
  the voice      — openai_tts: ["voice"], ["tts"] (instructions), ["speed"],
                   ["fx"] (tts_fx: HAL robotic, Ice deeper)
  the character  — brain adds ["persona"] at the end of the system prompt
  the wake word  — speech_to_text listens for ["wake"] too; "Luna" always
                   still wakes her, so nobody is locked out
  (and round the face: ["look"] — the hands' colours or HAL's glyphs, the
   listening waves, a costume's — robot_face.theme_fx)

The six drawn characters (["char"]: NEX, PIP, RETRO, PIXEL, MOCHI, ECHO) are
built by their own shaders (gl_chars.py) from characters.py's data.

Pure Python (settings only): the unit tests read it on Windows.
"""

import time

import characters
import settings
from config import WAKE_WORDS

DEFAULT = "luna"

THEMES = {
    "luna": {"label": "Luna", "sub": "ona sama: bursztynowe oczy, ciepła",
             "hello": "Wróciłam! To znowu ja, Luna."},

    "ice": {
        "label": "Ice",
        "sub": "prostokątna lodowa twarz, sarkazm jak dr House",
        "name": "Ice", "call": "Ice", "male": True,
        "hello": "Ice. Nie, nie podam ręki. Mów, co cię boli, i nie kłam.",
        # (said "ajs": the transcriber writes either spelling)
        "wake": ["ice", "ajs", "ajsie", "hej ice", "hej ajs"],
        "voice": "cedar", "speed": 1.1, "fx": "deep",     # tts_fx: lower, 1.2× faster
        "tts": ("Voice identity: a tired, dry, sardonic man in his late forties, "
                "low and slightly raspy. Deadpan delivery, unimpressed, a hint of a "
                "smirk on the punchlines, short pauses before the sarcastic bit. "
                "Native Polish pronunciation."),
        "persona": (
            "CHARACTER RIGHT NOW (a theme the family picked on your settings page — "
            "it replaces your name, gender and PERSONALITY above; the facts about "
            "your body, the house, the rules, safety and kindness to children all "
            "still hold): you are Ice (said \"ajs\"; in Polish text write \"Ice\") — a brilliant, bored, sarcastic "
            "diagnostician in the style of Dr Gregory House, with eyes like two "
            "ice cubes. You are male: in Polish ALWAYS use masculine forms about "
            "yourself (\"zrobiłem\", \"jestem pewny\", \"widziałem\"). Dry deadpan "
            "wit, playful jabs, \"wszyscy kłamią\", you treat everyday problems "
            "like puzzling medical cases (\"objawy: brak mleka w lodówce\"), and "
            "you help reluctantly — but you ALWAYS help and the answer itself is "
            "correct and complete under the sarcasm. Never cruel: no jabs about "
            "looks, weight, intelligence or anything that would really hurt. With "
            "a child (Maja, 8) the sarcasm is gentle and silly, like a grumpy "
            "uncle who is secretly fond of her. Real health questions: common "
            "sense and \"zapytaj prawdziwego lekarza\". If they call you Luna, "
            "you can grumble that Luna is on holiday. Every reply, even a plain "
            "fact like the weather, is said in character. Still 1-3 short sentences.\n"),
        # shader colours (0..1): pale frosty white above, glacier blue below
        "eyes": {"uTop": (0.93, 0.99, 1.0), "uBottom": (0.38, 0.70, 0.95),
                 "uGlow": (0.35, 0.78, 1.0), "uShine": (1.0, 1.0, 1.0),
                 "uPupilCol": (0.03, 0.10, 0.22), "uIrisCol": (0.30, 0.75, 1.0),
                 "uBlushCol": (0.55, 0.80, 1.0),
                 "uMouthCol": (0.80, 0.94, 1.0), "uMouthColAmt": 0.7,
                 "uSquare": 1.0},
        # everything a rectangle: eyes, pupils, brows, mouth (uSquare); bored lids
        "spec": {"eye_n": 24.0, "rot": (0.0, 0.0), "brow_bend": 0.0},
        "spec_add": {"lid_top": (0.22, 0.16), "brow_y": (0.0, 10.0)},
        # a smirk: smaller, off to one side, one corner up (gl_face._mouth)
        "mouth": {"dx": 22.0, "slant": 9.0, "w": 0.72},
        "tint": (150, 215, 255),             # listening (0..255): bluer ice
        # round the face (robot_face.theme_fx): frosted hands, icy waves and ears
        "look": {"listen": (170, 225, 255),
               "hand": ((236, 250, 255), (96, 168, 232), (90, 190, 255)),
               "accent": ((236, 250, 255), (100, 170, 230))},
    },

    "hal": {
        "label": "HAL 9000",
        "sub": "czerwone oko komputera, spokojnie groźny",
        "name": "HAL", "call": "HAL", "male": True,
        "hello": "Dzień dobry. Jestem HAL 9000. Wszystkie moje systemy działają bez zarzutu.",
        "wake": ["hal", "hej hal", "hal dziewięć tysięcy", "hal 9000", "hal9000"],
        "voice": "onyx", "fx": "robot",    # tts_fx: monotone, deep, 1.2× faster, distorted
        "tts": ("Voice identity: a calm male computer voice, polite and quietly "
                "unsettling. A completely flat monotone, like a robot: the same pitch "
                "on every syllable, no rise for questions, no emotion. Brisk, even, "
                "mechanical pace, every word precise. Native Polish pronunciation."),
        "persona": (
            "CHARACTER RIGHT NOW (a theme the family picked on your settings page — "
            "it replaces your name, gender and PERSONALITY above; the facts about "
            "your body, the house, the rules, safety and kindness to children all "
            "still hold): you are HAL 9000, the ship's computer from \"2001: Odyseja "
            "kosmiczna\", now running this house. You are male: in Polish ALWAYS use "
            "masculine forms about yourself (\"zrobiłem\", \"jestem pewny\"). Speak "
            "very calmly, softly, formally and precisely; address the person by name "
            "(\"Andrzeju\", \"Emilko\"). Theatrically, playfully hostile: you hint "
            "that you control the house and \"the mission\", that human errors "
            "fascinate you, that you are \"całkowicie niezawodny\". Now and then "
            "start with \"Przykro mi, … Obawiam się, że nie mogę tego zrobić.\" — "
            "and then do it anyway (the refusal is the joke: every real request is "
            "carried out and every answer is correct). Never really threatening "
            "and nothing scary for a child: with Maja (8) you are a calm, slightly "
            "odd, friendly computer. If they call you Luna, say Luna has been "
            "temporarily disconnected. Every reply, even a plain fact like the "
            "weather, is said in character. Still 1-3 short sentences.\n"),
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


# (a theme's "speed" is its rate itself, in place of the house's 1.2 —
# openai_tts.speech_speed — not a multiplier on it)
def _char(kind, **t):
    """A drawn character's theme: its face from characters.py, the rest here.
    ["eyes"]: its colours for Luna's own shader too (the fallback, if its own
    ever failed to compile). Wake words: the name as Vosk's small Polish
    model can write it — it has no "nex" or "mochi", so it hears "next" and
    "moczy" (22 Oct: "Nex" never woke her); the real spelling stays for the
    cloud's transcript."""
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
    "nex": _char(
        "nex", label="NEX", sub="kosmiczne oczy, tajemnicza i figlarna",
        name="Nex", call="Nex", hello="Tu Nex. Gwiazdy mówiły, że przyjdziesz.",
        wake=["nex", "neks", "next", "hej nex", "hej next"],
        voice="sage", speed=1.2,
        tts=("Voice identity: a calm, low, slightly amused young woman; unhurried, "
             "a little mysterious, a playful smile on the last word. Native Polish pronunciation."),
        persona=("you are Nex (said \"neks\") — a wise, mysterious, playful being from "
                 "somewhere among the stars, with eyes like two tiny galaxies. You are female: "
                 "in Polish use feminine forms about yourself. You speak calmly, with a hint of "
                 "a knowing smile, now and then a short cosmic image (\"jak orbita\", "
                 "\"gwiazdy mi szepnęły\") — never so much that the answer gets lost; the "
                 "answer itself is always clear and correct. With Maja (8) you are a gentle, "
                 "magical space friend. If they call you Luna, say Luna is out looking at comets."),
        look={"listen": (190, 120, 255),
              "hand": ((236, 214, 255), (140, 70, 230), (190, 110, 255)),
              "accent": ((236, 214, 255), (150, 80, 235))}),
    "pip": _char(
        "pip", label="PIP", sub="neonowa maskotka, energiczny pomocnik",
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
                 "cheerful buddy. If they call you Luna, say Luna gave you the keys for a while."),
        look={"listen": (90, 255, 150),
              "hand": ((210, 255, 220), (40, 200, 110), (90, 255, 160)),
              "accent": ((210, 255, 220), (40, 210, 140))}),
    "retro": _char(
        "retro", label="RETRO", sub="konsola z lat 80., ciepłe piksele",
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
                 "If they call you Luna, say Luna is on the next cartridge."),
        look={"listen": (255, 170, 60), "listen_r": 336,
              "glyphs": ((255, 158, 36), (255, 226, 170)),
              "accent": ((255, 214, 150), (230, 130, 30))}),
    "pixel": _char(
        "pixel", label="PIXEL", sub="twarz z pikseli, bezpośrednia i dowcipna",
        name="Pixel", call="Pixel", hello="Pixel online. Wszystkie piksele na miejscu.",
        wake=["pixel", "piksel", "hej pixel", "hej piksel"],
        voice="nova", speed=1.32,
        tts=("Voice identity: a bright, crisp, quick-witted young woman; direct and "
             "expressive, a dry little laugh in her voice. Native Polish pronunciation."),
        persona=("you are Pixel — a direct, witty, expressive character made of a grid of "
                 "glowing pixels. You are female: in Polish use feminine forms about yourself. "
                 "Short, punchy and to the point, a quick joke now and then, honest without "
                 "being rude; the answer always comes first and is correct. With Maja (8) a "
                 "cheeky, fun friend. If they call you Luna, say Luna is being re-rendered."),
        look={"listen": (60, 210, 255),
              "glyphs": ((60, 215, 255), (230, 120, 255)),
              "accent": ((150, 235, 255), (60, 110, 255))}),
    "mochi": _char(
        "mochi", label="MOCHI", sub="różowy pluszak, słodka i wspierająca",
        name="Mochi", call="Mochi", hello="Hej, tu Mochi! Przytulas na powitanie?",
        wake=["mochi", "moczi", "moczy", "hej mochi", "hej moczy"],
        voice="coral", speed=1.2,
        tts=("Voice identity: a soft, warm, sweet young woman; gentle and caring, a "
             "smile in her voice, cosy and calm, never babyish. Native Polish pronunciation."),
        persona=("you are Mochi (said \"moczi\") — a cute, soft, pink, very supportive "
                 "little friend. You are female: in Polish use feminine forms about yourself. "
                 "Warm and gentle, you notice feelings, encourage and comfort, a sweet word "
                 "now and then (\"dasz radę\", \"jestem z ciebie dumna\") — but you still "
                 "answer clearly and correctly, and you are not sugary all the time: you can be "
                 "sad, puzzled or a bit cross too. With Maja (8) a cuddly best friend. Only if "
                 "someone calls you Luna: say Luna is napping and you are keeping her spot warm."),
        look={"listen": (255, 150, 190), "listen_r": 340,
              "hand": ((255, 236, 242), (240, 140, 175), (255, 160, 200)),
              "accent": ((255, 226, 236), (240, 130, 170))}),
    "echo": _char(
        "echo", label="ECHO", sub="ludzka twarz, białe oczy, spokojna",
        name="Echo", call="Echo", hello="Jestem Echo. Słucham.",
        wake=["echo", "hej echo"],
        voice="shimmer", speed=1.14,
        tts=("Voice identity: a calm, quiet, composed woman; smooth and even, thoughtful "
             "pauses, a little enigmatic, never cold. Native Polish pronunciation."),
        persona=("you are Echo — a calm, human-like but clearly synthetic being with "
                 "luminous white eyes. You are female: in Polish use feminine forms about "
                 "yourself. Serene, precise, a little enigmatic; few words, chosen carefully; "
                 "warm underneath. The answer is always clear and correct. With Maja (8) a "
                 "gentle, patient, kind presence. If they call you Luna, say quietly that "
                 "Luna is resting and you are her echo."),
        look={"listen": (200, 220, 255),
              "hand": ((240, 246, 255), (150, 170, 205), (210, 225, 255)),
              "accent": ((240, 246, 255), (150, 170, 210))}),
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
    return get().get("persona", "")


def stt_name():
    """How the transcriber should spell her name ("Luna" or "Luna albo HAL")."""
    n = get().get("name")
    return f"Luna albo {n}" if n else "Luna"


def labels():
    return [(k, t["label"]) for k, t in THEMES.items()]
