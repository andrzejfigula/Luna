"""
echo.py — was that her own voice coming back through the microphone?

Defense-in-depth against Luna hearing herself (text_to_speech.py blocks the
mic while she speaks — that is the primary fix; this catches trailing echo
and reverb that slips past the blocking window). Pure, so it is tested.

Requires a contiguous word run AND overall word overlap with her last reply
— either alone swallows ordinary short sentences full of common words — and
the run must reach the END of what she said: that is what leaks back. Words
from the middle of her answer are someone answering it ("kurczak z
warzywami", one of the two dinners she offered, was swallowed on 5 Oct).
"""

import difflib
import re


def is_echo(heard, last, run_thresh=0.5, overlap_thresh=0.6, tail=3):
    """True when `heard` looks like the tail of `last` (her last reply)."""
    heard_words = re.findall(r"\w+", (heard or "").lower())   # no punctuation
    last_words = re.findall(r"\w+", (last or "").lower())
    if not heard_words or not last_words:
        return False
    overlap = sum(1 for w in heard_words if w in set(last_words)) / len(heard_words)
    sm = difflib.SequenceMatcher(None, heard_words, last_words, autojunk=False)
    match = sm.find_longest_match(0, len(heard_words), 0, len(last_words))
    at_end = match.b + match.size >= len(last_words) - tail
    if (last or "").rstrip().endswith("?"):
        # after a question the answer often repeats its last words — "po
        # pracy czy już po trybie kanapowym?" → "w trybie kanapowym" was
        # dropped as echo and she went silent (7 Oct 20:59). Only a long,
        # word-for-word copy of her words counts then; every "echo" in the
        # log so far was someone answering (the mic is off while she speaks)
        return (len(heard_words) >= 4 and match.size == len(heard_words) and at_end)
    return (match.size / len(heard_words) >= run_thresh and overlap >= overlap_thresh
            and at_end)
