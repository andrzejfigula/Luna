"""
body.py — what Luna knows about her own body: the Raspberry Pi she runs on.

A short line goes into every request, so "jak się czujesz?" gets a true
answer ("trochę mi gorąco, procesor ma 74 stopnie") instead of an invented
one, and she can mention it herself if she really is overheating.
"""

import os
import subprocess
import time

_STARTED = time.time()
_talks_today = [time.strftime("%Y-%m-%d"), 0]


def cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def throttled():
    """True when the Pi is (or has been, since boot) throttling for heat or
    low voltage — vcgencmd get_throttled, non-zero = something happened."""
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=2).stdout
        return int(out.strip().split("=")[1], 16) & 0xF != 0      # happening NOW
    except Exception:
        return None


def load_percent():
    try:
        return round(100 * os.getloadavg()[0] / (os.cpu_count() or 4))
    except OSError:
        return None


def _span(secs):
    secs = int(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


def note_conversation():
    """Called by brain for every answered utterance."""
    today = time.strftime("%Y-%m-%d")
    if _talks_today[0] != today:
        _talks_today[:] = [today, 0]
    _talks_today[1] += 1


def prompt_line():
    parts = []
    t = cpu_temp()
    if t is not None:
        feel = ("cool" if t < 55 else "warm" if t < 70 else
                "hot" if t < 80 else "VERY hot, close to overheating")
        parts.append(f"CPU {t:.0f}°C ({feel})")
    th = throttled()
    if th:
        parts.append("the Pi is throttling right now (heat or weak power)")
    ld = load_percent()
    if ld is not None:
        parts.append(f"load {ld}%")
    parts.append(f"running for {_span(time.time() - _STARTED)} since your last start")
    parts.append(f"{_talks_today[1]} things said to you today")
    return ("Your body right now (Raspberry Pi 4): " + ", ".join(parts) + ". "
            "Bring it up only when asked how you are or about yourself — then "
            "weave in one such detail playfully, like a person mentioning "
            "being sleepy or warm — or, once, if you are VERY hot or "
            "throttling.\n")
