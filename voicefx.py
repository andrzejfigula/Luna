"""
voicefx.py — "Luna, zmień mój głos": your next sentence played back changed.

  "zmień mój głos", "pobawmy się głosem"  → a surprise effect
  "…jak wiewiórka" / "…jak olbrzym"      → higher and faster / lower and slower
  "…jak robot"                            → a metallic ring
  "…od tyłu", "odwróć mój głos"           → backwards

She says "Powiedz coś!", and the next sentence (up to 20 s later) is not
answered but played back with the effect (main.py, like a voice message).
All local: the audio never leaves her. "Jeszcze raz" in the same breath
works as a new request.
"""

import random
import re
import time

import numpy as np

EFFECTS = ("wiewiórka", "olbrzym", "robot", "od tyłu")
_START = re.compile(r"\b(?:zmień|zmien|zmieniaj|odwróć|odwroc|pobawmy\s+się|pobawmy\s+sie|"
                    r"przerób|przerob|zrób|zrob)\b.{0,20}\b(?:głos\w*|glos\w*)\b", re.I)
_armed = [None, 0.0]           # effect, when


def wants(text):
    """The effect asked for ("wiewiórka", …, or "?" for a surprise), or None."""
    low = text.lower()
    if not _START.search(low) and not re.search(r"\bgłos\w*\s+jak\s+(?:wiewiórka|robot|olbrzym)",
                                                low):
        return None
    if len(low.split()) > 10:
        return None
    if "wiewiór" in low or "wiewior" in low or "myszk" in low or "szybk" in low:
        return "wiewiórka"
    if "olbrzym" in low or "niedźwied" in low or "gruby" in low or "nisk" in low:
        return "olbrzym"
    if "robot" in low:
        return "robot"
    if "tyłu" in low or "tylu" in low or "odwr" in low:
        return "od tyłu"
    return "?"


def arm(effect):
    _armed[:] = [random.choice(EFFECTS) if effect == "?" else effect, time.time()]
    return _armed[0]


def armed():
    if _armed[0] and time.time() - _armed[1] > 20:
        _armed[0] = None
    return _armed[0]


def apply(pcm16k, effect):
    """16 kHz int16 mono bytes → 24 kHz int16 bytes with the effect."""
    a = np.frombuffer(pcm16k[:len(pcm16k) // 2 * 2], np.int16).astype(np.float32)
    if a.size < 1600:
        return b""
    if effect == "od tyłu":
        a = a[::-1]
    elif effect == "robot":
        t = np.arange(a.size) / 16000
        a = a * (0.6 + 0.4 * np.sin(2 * np.pi * 55 * t))          # a ring modulator
    speed = {"wiewiórka": 1.6, "olbrzym": 0.7}.get(effect, 1.0)
    n = int(a.size * 24000 / 16000 / speed)                       # to 24 kHz, faster/slower
    out = np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a)
    peak = float(np.max(np.abs(out))) or 1.0
    out = out * min(3.0, 26000 / peak)                            # a quiet voice made audible
    return out.clip(-32768, 32767).astype(np.int16).tobytes()


def play(pcm16k, speak, play_clip):
    effect = _armed[0]
    _armed[0] = None
    pcm = apply(pcm16k, effect) if effect else b""
    if not pcm:
        speak("Nic nie usłyszałam. Powiedz: zmień mój głos — i spróbuj jeszcze raz.")
        return
    print(f"[voicefx] {effect}, {len(pcm) / 48000:.1f} s", flush=True)
    speak({"wiewiórka": "Jak wiewiórka:", "olbrzym": "Jak olbrzym:", "robot": "Jak robot:",
           "od tyłu": "Od tyłu:"}[effect])
    play_clip(pcm, label=f"(twój głos: {effect})")
