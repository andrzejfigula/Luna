"""
bargein.py — "stop!" (or "Luna!") while she talks: she stops and listens at once.

While she speaks, the microphone's blocks go here instead of to the normal
listener (speech_to_text drops them there — they are mostly her own voice).
A small Vosk recogniser that knows only a handful of words (BARGE_WORDS +
"[unk]") listens to them. Alone it can't tell your "stop" from her own voice
(6–17 Oct, log mode: "Hejka!" → "stop"; "…piętnaście stopni…" → "stop"), so
a word it hears — in its running guess or its final one, at least
BARGE_OVER_ECHO × her voice's level in the microphone — is only a CANDIDATE,
and the camera decides (mouth.confirms_voice): the face in front of her moved
its mouth in the last moments. A word like one she is saying needs the
camera's full "talking"; any other word a looser sign (the mouth changing
more than the head — 17 Oct 22:59 Andrzej said "Luna, stop" over a story
with the radio on, his head moving: the strict rule saw nothing, Vosk heard
"luna" and "stop").

Then her voice is cut (mouth.cut_short) and the conversation window opens:
what they say next is heard without "Luna". The camera alone stops her too,
when it sees a longer sentence said over her (mouth.py).
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
    # (0.5 made "luna" like her "nas" — 17 Oct 23:09, every "luna" over her
    # weather answer needed the camera's strictest verdict)
    if difflib.SequenceMatcher(None, word, hers).ratio() >= 0.7:
        return True
    m = difflib.SequenceMatcher(None, word, hers).find_longest_match(0, len(word), 0, len(hers))
    return m.size >= 4                       # "stop" in "stopni"


class Detector:
    """Feed it 16 kHz int16 blocks while she speaks; feed() returns
    (word, like one of hers) for a candidate, or None."""

    def __init__(self, model, rate=16000, rec=None):
        if rec is None:
            from vosk import KaldiRecognizer
            rec = KaldiRecognizer(model, rate, json.dumps(list(BARGE_WORDS) + ["[unk]"],
                                                         ensure_ascii=False))
            rec.SetWords(True)
        self.rec = rec
        self.echo = collections.deque(maxlen=60)     # her voice's levels, recent blocks
        self.levels = collections.deque(maxlen=3)    # the last 0.75 s
        self.seen = 0                                # words of the running guess looked at
        self.blocks = 0

    def reset(self):
        """Her reply ended (the echo level stays — it is the room's)."""
        self.rec.Reset()
        self.levels.clear()
        self.seen = 0

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
        self.levels.append(level)
        # only words NEW since the last block: the running guess repeats the
        # whole segment each time
        if self.rec.AcceptWaveform(block):
            res = json.loads(self.rec.Result())
            words = [(w.get("word", ""), float(w.get("conf", 0)))
                     for w in res.get("result", []) if w.get("word") != "[unk]"]
            words, self.seen = words[self.seen:], 0
        else:                                # its running guess: sooner, no confidence
            words = [(w, None) for w in json.loads(self.rec.PartialResult())
                     .get("partial", "").split() if w != "[unk]"]
            words, self.seen = words[self.seen:], max(self.seen, len(words))
        mine = [_norm(w) for w in (her_text or "").split()]
        loud = max(self.levels)
        for word, conf in words:
            if not word or (conf is not None and conf < BARGE_MIN_CONF):
                continue
            # (her echo, not the noise gate: with the radio on the gate was
            # above Andrzej's "luna" — 1383 against her 592, 17 Oct 22:59)
            if loud < echo * BARGE_OVER_ECHO:
                print(f"[barge] {word!r} quieter than her voice "
                      f"(peak {loud:.0f}, echo {echo:.0f})", flush=True)
                continue
            return word, any(_alike(_norm(word), m) for m in mine)
        return None
