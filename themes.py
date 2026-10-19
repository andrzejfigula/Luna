"""
themes.py — who she is right now: Luna, or a character picked on the settings
page (Ekran → Motyw). A theme changes four things at once:

  the face       — gl_face lays THEMES[..]["eyes"] (shader uniforms: colours,
                   uSquare for square shapes) and ["spec"] / ["spec_add"] (face_spec
                   shape) over the style's; ["mouth"] shapes the mouth (_mouth)
  the voice      — openai_tts: ["voice"], ["tts"] (instructions), ["speed"]
  the character  — brain adds ["persona"] at the end of the system prompt
  the wake word  — speech_to_text listens for ["wake"] too; "Luna" always
                   still wakes her, so nobody is locked out

Pure Python (settings only): the unit tests read it on Windows.
"""

import time

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
        "voice": "cedar", "speed": 1.1,
        "tts": ("Voice identity: a tired, dry, sardonic man in his late forties, "
                "low and slightly raspy. Deadpan delivery, unimpressed, a hint of a "
                "smirk on the punchlines, short pauses before the sarcastic bit. "
                "Native Polish pronunciation."),
        "persona": (
            "CHARACTER RIGHT NOW (a theme the family picked on your settings page — "
            "it replaces your name, gender and PERSONALITY above; the facts about "
            "your body, the house, the rules, safety and kindness to children all "
            "still hold): you are Ice (said "ajs"; in Polish text write "Ice") — a brilliant, bored, sarcastic "
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
    },

    "hal": {
        "label": "HAL 9000",
        "sub": "czerwone oko komputera, spokojnie groźny",
        "name": "HAL", "call": "HAL", "male": True,
        "hello": "Dzień dobry. Jestem HAL 9000. Wszystkie moje systemy działają bez zarzutu.",
        "wake": ["hal", "hej hal", "hal dziewięć tysięcy", "hal 9000", "hal9000"],
        "voice": "onyx", "speed": 0.95,
        "tts": ("Voice identity: a calm, soft, perfectly even male computer voice, "
                "polite and gentle, quietly unsettling. Slow measured pace, no "
                "emotion in the pitch at all, every word precise. Native Polish "
                "pronunciation."),
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
    },
}

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
