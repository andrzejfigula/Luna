"""
holds.py — what someone asked to last for a while survives a restart.

  "bądź cicho do 15"     → state.proactive_muted_until
  "nie słuchaj"          → state.mic_muted_until
  "wyłącz kamerę"        → state.camera_off_until
  "tryb skupienia"       → state.focus_until

These lived only in memory: a restart (a deploy, the watchdog, lwrespawn after
a crash) quietly ended them — the camera back on an hour early, a hello in the
middle of a call (13 Oct, found while looking at "Hej, hej!" at 10:29). Kept
in DATA_DIR/holds.json, checked every few seconds and written only on a change;
at start the ones still in the future are put back.
"""

import json
import os
import threading
import time

from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "holds.json")
FIELDS = ("proactive_muted_until", "mic_muted_until", "camera_off_until", "focus_until")
EVERY = 3.0
_last = {}


def _now_values():
    with state.lock:
        return {f: float(getattr(state, f, 0.0) or 0.0) for f in FIELDS}


def load(now=None):
    """Put back what is still running; returns the names put back."""
    now = now or time.time()
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return []
    back = []
    with state.lock:
        for f in FIELDS:
            until = float(saved.get(f, 0.0) or 0.0)
            if until > now and until > float(getattr(state, f, 0.0) or 0.0):
                setattr(state, f, until)
                back.append(f)
    if back:
        print(f"[holds] still on after the restart: {', '.join(back)}", flush=True)
    _last.update(_now_values())
    return back


def save_if_changed():
    vals = _now_values()
    if vals == _last:
        return False
    _last.clear()
    _last.update(vals)
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(vals, f)
        os.replace(tmp, PATH)
    except OSError:
        return False
    return True


def _loop():
    while True:
        try:
            save_if_changed()
        except Exception as e:
            print(f"[holds] {e}", flush=True)
        time.sleep(EVERY)


def start_holds():
    load()
    threading.Thread(target=_loop, daemon=True, name="holds").start()
