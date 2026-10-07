"""
bargein.py — "stop!" while she talks: she stops and listens at once.

While she speaks, the microphone's blocks go here instead of to the normal
listener (speech_to_text drops them there — they are mostly her own voice).
A small Vosk recogniser that knows only a handful of words (BARGE_WORDS +
"[unk]") listens to them; a word counts only when

  - Vosk is sure of it (≥ BARGE_MIN_CONF),
  - it was louder than her own voice in the microphone (the echo level is
    measured while she speaks — ≥ BARGE_OVER_ECHO × its median), and
  - she isn't saying that word herself right now (her current text).

Then her voice is cut and the conversation window opens: what they say next
is heard without "Luna". The touch equivalent (a held finger) already existed;
6 Oct: Andrzej wanted to stop her mid-sentence by voice.
"""

import collections
import difflib
import json
import re

from config import BARGE_WORDS, BARGE_MIN_CONF, BARGE_OVER_ECHO


def _rms(block):
    import numpy as np
    a = np.frombuffer(block, np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if len(a) else 0.0


def _norm(w):
    return re.sub(r"[^\wąćęłńóśźż]", "", w.lower())


def _alike(word, hers):
    """Could the recogniser have heard `word` in her word `hers`?"""
    if difflib.SequenceMatcher(None, word, hers).ratio() >= 0.5:
        return True
    m = difflib.SequenceMatcher(None, word, hers).find_longest_match(0, len(word), 0, len(hers))
    return m.size >= 4                       # "stop" in "stopni"


class Detector:
    """Feed it 16 kHz int16 blocks while she speaks; feed() returns the word
    that should stop her, or None."""

    def __init__(self, model, rate=16000):
        from vosk import KaldiRecognizer
        self.rec = KaldiRecognizer(model, rate, json.dumps(list(BARGE_WORDS) + ["[unk]"], ensure_ascii=False))
        self.rec.SetWords(True)
        self.echo = collections.deque(maxlen=60)     # her voice's levels, recent blocks
        self.peak = 0.0                              # loudest block of the current segment
        self.blocks = 0

    def reset(self):
        self.rec.Reset()
        self.peak = 0.0

    def echo_level(self):
        if not self.echo:
            return 0.0
        s = sorted(self.echo)
        return s[len(s) // 2]

    def feed(self, block, her_text="", gate=0.0):
        level = _rms(block)
        self.blocks += 1
        echo = self.echo_level()
        self.echo.append(level)
        self.peak = max(self.peak, level)
        if not self.rec.AcceptWaveform(block):
            return None
        res = json.loads(self.rec.Result())
        peak, self.peak = self.peak, 0.0
        words = [w for w in res.get("result", []) if w.get("word") != "[unk]"]
        if not words:
            return None
        mine = [_norm(w) for w in (her_text or "").split()]
        for w in words:
            word, conf = w.get("word", ""), float(w.get("conf", 0))
            if conf < BARGE_MIN_CONF:
                continue
            if peak < max(gate * 2.0, echo * BARGE_OVER_ECHO):
                print(f"[barge] {word!r} ({conf:.2f}) not louder than her voice "
                      f"(peak {peak:.0f}, echo {echo:.0f})", flush=True)
                continue
            if any(_alike(word, m) for m in mine):
                print(f"[barge] {word!r} is in what she says — ignored", flush=True)
                continue
            print(f"[barge] {word!r} ({conf:.2f}, peak {peak:.0f}, her echo {echo:.0f}) "
                  "— she stops and listens", flush=True)
            return word
        return None
