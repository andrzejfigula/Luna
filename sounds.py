"""
sounds.py — Luna's non-verbal sounds: "mhm", "hmm", a giggle, "oh!"…

Until now she either said a whole sentence or nothing. These little sounds
fill the space in between: a questioning "hm?" when you call her name, a
"hmm" while the answer is still coming, a giggle when you stroke her.

Each sound is made ONCE by the same TTS voice she speaks with (so it is
recognisably her), trimmed, and cached as raw 24 kHz PCM in data/sounds/.
From then on it plays locally — no network, no cost, no delay. The file name
carries a hash of the voice and the text/instructions, so changing the voice
(LUNA_TTS_VOICE) or a definition below regenerates just what changed.
"""

import hashlib
import os
import threading

import numpy as np
from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TTS_INSTRUCTIONS,
    OPENAI_TTS_TIMEOUT,
    SOUNDS_ENABLED,
    SOUNDS_DIR,
)

RATE = 24000                   # the API's fixed PCM rate
MAX_SECS = 2.6                 # anything longer is trimmed

# name → (what the voice "says", how to perform it[, longest it may run, s])
SOUNDS = {
    "mhm":    ("Mhm.",
               "A short, warm, closed-mouth 'mhm' — attentive listening, "
               "agreeing softly. Not a word, just the hum."),
    "hmm":    ("Hmmm...",
               "A thoughtful, pondering hum, as if thinking about the answer. "
               "About one second long.", 1.2),   # a filler must not delay the reply
    "huh":    ("Hm?",
               "A short, curious 'hm?' with a rising tone, as if someone just "
               "called your name and you are listening."),
    "giggle": ("Hihihi!",
               "A short, genuine, cute giggle — ticklish and delighted."),
    "aww":    ("Oooch...",
               "A soft, pleased, affectionate 'aww' — like being petted. "
               "Warm and a little melting."),
    "oh":     ("Oh!",
               "A short, surprised 'oh!' — caught off guard, a small gasp."),
    "hey":    ("Ej!",
               "A short, playful protest 'hey!' — mildly annoyed at being poked, "
               "but not really angry."),
    # the breathing exercise (breathing.py): calm guidance, exactly on time
    "inhale": ("Wdech...",
               "Very calm, soft and slow, like a yoga teacher guiding a breathing "
               "exercise. A gentle, drawn-out word.", 2.5),
    "exhale": ("I wydech...",
               "Very calm, soft and slow, like a yoga teacher guiding a breathing "
               "exercise, a relaxed out-breath in the voice.", 2.8),
    # not a sound but a sentence: recorded while online, played when the
    # cloud is unreachable (TTS would fail too, leaving her silent)
    "offline": ("Przepraszam, nie mogę teraz połączyć się z moim mózgiem w chmurze. "
                "Sprawdź proszę internet.",
                "Normal speech, apologetic and gentle, a little sad.", 7.0),
    # a local command did its job, but its spoken confirmation can't be made
    # (TTS needs the cloud): said instead of silence (openai_tts.py)
    "offline_done": ("Zrobione! Tylko nie mam teraz internetu, więc mówię krótko.",
                     "Normal speech, friendly, a little apologetic.", 5.0),
}

_cache = {}                    # name → PCM bytes, ready to play
_client = (OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TTS_TIMEOUT, max_retries=1)
           if (OPENAI_API_KEY and SOUNDS_ENABLED) else None)


def _path(name):
    text, how = SOUNDS[name][:2]
    key = "|".join((OPENAI_TTS_MODEL, OPENAI_TTS_VOICE, text, how,
                    OPENAI_TTS_INSTRUCTIONS or "", repr(SOUNDS[name][2:])))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return os.path.join(SOUNDS_DIR, f"{name}-{digest}.pcm")


def _trim(pcm, max_secs=MAX_SECS):
    """Cut the silence the TTS leaves around a sound, cap the length and fade
    the edges so it starts and stops without a click. b"" = nothing usable."""
    a = np.frombuffer(pcm, dtype=np.int16)
    loud = np.flatnonzero(np.abs(a) > 500)
    if loud.size == 0 or loud[-1] - loud[0] < 0.15 * RATE:
        return b""
    start = max(0, loud[0] - int(0.01 * RATE))
    end = min(len(a), loud[-1] + int(0.12 * RATE), start + int(max_secs * RATE))
    a = a[start:end].astype(np.float32)
    fi, fo = min(len(a), int(0.005 * RATE)), min(len(a), int(0.04 * RATE))
    a[:fi] *= np.linspace(0.0, 1.0, fi)
    a[len(a) - fo:] *= np.linspace(1.0, 0.0, fo)
    return a.astype(np.int16).tobytes()


def _generate(name):
    text, how = SOUNDS[name][:2]
    max_secs = SOUNDS[name][2] if len(SOUNDS[name]) > 2 else MAX_SECS
    instructions = ((OPENAI_TTS_INSTRUCTIONS or "") +
                    "\nThis is a non-verbal sound, not speech: " + how).strip()
    # the voice is not deterministic: a tiny input like "Hm?" sometimes comes
    # back as pure silence, so try a few times
    for _ in range(3):
        r = _client.audio.speech.create(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                                        input=text, response_format="pcm",
                                        instructions=instructions)
        pcm = _trim(r.content, max_secs)
        if pcm:
            break
    else:
        raise RuntimeError("the voice returned only silence, 3 times")
    tmp = _path(name) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(pcm)
    os.replace(tmp, _path(name))
    return pcm


def _chime():
    """A soft two-note bell ("ding-dong", twice) made right here — the timer
    must ring even with no network and with LUNA_SOUNDS=0."""
    def bell(freq, secs):
        t = np.arange(int(secs * RATE)) / RATE
        tone = (np.sin(2 * np.pi * freq * t)
                + 0.45 * np.sin(2 * np.pi * freq * 2.0 * t) * np.exp(-t * 3.0)
                + 0.18 * np.sin(2 * np.pi * freq * 3.01 * t) * np.exp(-t * 5.0))
        env = np.minimum(1.0, t / 0.005) * np.exp(-t * 3.2)
        return tone * env
    notes = [(1318.5, 0.42), (1046.5, 0.70), (1318.5, 0.42), (1046.5, 1.1)]
    out = np.concatenate([bell(f, d) for f, d in notes])
    out = out / np.abs(out).max() * 0.42 * 32767
    return out.astype(np.int16).tobytes()


def _tick():
    """A short, soft wooden tick for countdowns (made here, no network)."""
    t = np.arange(int(0.07 * RATE)) / RATE
    tone = np.sin(2 * np.pi * 1760 * t) + 0.5 * np.sin(2 * np.pi * 2640 * t)
    out = tone * np.exp(-t * 70.0) * 0.35 * 32767 / 1.5
    return out.astype(np.int16).tobytes()


_SYNTH = {"chime": _chime, "tick": _tick}

_clips = {}                    # path → PCM: spoken words made once (counting)
_CLIP_HOW = ("Counting out loud for children playing hide and seek: say just the "
             "number, briskly and clearly, cheerful.")


def _clip_path(text, how):
    key = "|".join((OPENAI_TTS_MODEL, OPENAI_TTS_VOICE, text, how))
    return os.path.join(SOUNDS_DIR, f"clip-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}.pcm")


def clip(text, how=_CLIP_HOW):
    """A word or two in her voice, made once and kept on disk — the numbers
    she counts with. None when it can't be had (offline, first time)."""
    path = _clip_path(text, how)
    if path in _clips:
        return _clips[path]
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                pcm = f.read()
        elif _client is not None:
            instructions = ((OPENAI_TTS_INSTRUCTIONS or "") + "\n" + how).strip()
            r = _client.audio.speech.create(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                                            input=text, response_format="pcm",
                                            instructions=instructions)
            pcm = _trim(r.content, 3.0)
            if not pcm:
                return None
            os.makedirs(SOUNDS_DIR, exist_ok=True)
            with open(path + ".tmp", "wb") as f:
                f.write(pcm)
            os.replace(path + ".tmp", path)
        else:
            return None
    except Exception as e:
        print(f"[sounds] clip {text!r}: {e}", flush=True)
        return None
    _clips[path] = pcm
    return pcm


def get(name):
    """PCM for a sound, or None if it isn't ready (or sounds are off).
    The synthesised ones (chime, tick) are always available."""
    if name in _SYNTH and name not in _cache:
        _cache[name] = _SYNTH[name]()
    return _cache.get(name)


def _warm():
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    made = []
    for name in SOUNDS:
        p = _path(name)
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    _cache[name] = f.read()
            elif _client is not None:
                _cache[name] = _generate(name)
                made.append(name)
        except Exception as e:
            print(f"[sounds] {name}: {e}")
    # drop files from older voices / definitions
    keep = {os.path.basename(_path(n)) for n in SOUNDS}
    for fn in os.listdir(SOUNDS_DIR):
        if fn.endswith(".pcm") and fn not in keep and not fn.startswith("clip-"):
            try:
                os.remove(os.path.join(SOUNDS_DIR, fn))
            except OSError:
                pass
    print(f"[sounds] {len(_cache)}/{len(SOUNDS)} ready"
          + (f" (generated: {', '.join(made)})" if made else ""), flush=True)


def start_sounds():
    if not SOUNDS_ENABLED:
        print("[sounds] off")
        return
    threading.Thread(target=_warm, daemon=True, name="sounds").start()
