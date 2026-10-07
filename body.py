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
    except (OSError, AttributeError):        # AttributeError: no loadavg on Windows
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


def _settings():
    """Her adjustable state, so "jak głośno mówisz?" has an answer."""
    out = []
    try:
        import commands
        v = commands.cached_volume()
        if v is not None:
            out.append(f"speaker volume {round(v * 100)}%")
    except Exception:
        pass
    try:
        import settings
        from config import OPENAI_TTS_SPEED
        out.append(f"speech speed {settings.get('tts_speed', OPENAI_TTS_SPEED)}")
    except Exception:
        pass
    try:
        import display
        b = display.get_percent()
        if b is not None:
            out.append(f"screen brightness {b}%")
    except Exception:
        pass
    try:
        from shared_state import state
        with state.lock:
            if time.time() < state.focus_until:
                out.append(f"focus mode for {int((state.focus_until - time.time()) / 60)} more min")
            if state.overlay and time.time() < state.overlay[1]:
                out.append(f"showing {state.overlay[0]} on your screen")
    except Exception:
        pass
    return out


def prompt_line():
    parts = []
    t = cpu_temp()
    if t is not None:
        # 55–70 °C is simply her normal (the Pi sits at ~60–66): calling it
        # "warm" had her mention the warmth in 3 of 10 everyday replies (7 Oct)
        feel = ("normal" if t < 70 else
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
    parts += _settings()
    return ("Your body right now (Raspberry Pi 4): " + ", ".join(parts) + ". "
            "Keep it to yourself almost always: \"jak się masz?\", \"co tam?\", "
            "\"co robisz?\" get an ordinary friendly answer with no hardware "
            "details. Mention one such detail, playfully, only when they ask about "
            "your body itself (temperature, how long you've been on, how much you "
            "talked today) — or once if you are hot, VERY hot or throttling.\n")
