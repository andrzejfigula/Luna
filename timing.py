"""
timing.py — where the time goes between "they stopped talking" and "her voice".

Stages are marked as they happen (speech_to_text, main, brain); the first
sound of her answer prints them all on the "[latency]" line, e.g.

    [latency] end of speech → her voice 2.31s (text 0.42, model 0.55, sentence 1.62, voice 2.31)

each number counted from the end of their speech. Six Oct, evening: answers
took 3.6–3.9 s although the model streamed within ~1 s — "she hangs".
"""

import time

_marks = {}


def mark(stage):
    """Note when `stage` happened — first time only: "text" (transcript ready),
    "model" (request sent), "sentence" (first one written), "tts" (voice
    requested), "audio" (its first bytes in)."""
    _marks.setdefault(stage, time.time())


def waiting_for_reply():
    """The model was asked but hasn't written a sentence: a sound now is a
    "hmm" filler, not the answer."""
    return "model" in _marks and "sentence" not in _marks


def reset():
    _marks.clear()


def report(heard):
    """The breakdown since `heard` (end of speech), then forget the marks."""
    parts = [f"{k} {_marks[k] - heard:.2f}" for k in ("text", "model", "sentence", "tts",
                                                       "audio")
             if k in _marks and _marks[k] >= heard]
    _marks.clear()
    return ", ".join(parts)
