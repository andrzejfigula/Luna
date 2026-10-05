"""
messages.py — voice messages left with Luna for someone at home.

  "nagraj wiadomość dla Emilki" → the same, for one person: she tells Emilka
                                  when she recognises her face (faces.py)
  "Luna, nagraj wiadomość"      → she says "mów", and your next sentence is
                                  recorded as it is (your own voice, up to
                                  CLOUD_STT_MAX_SECS, pauses allowed)
  next time someone comes by    → "masz nową wiadomość" with the greeting, and
                                  a small envelope on her screen meanwhile
  "odtwórz wiadomość"           → plays the new ones (or the last one), with
                                  when it was left
  "usuń wiadomości"             → deletes the ones already heard; one still
                                  waiting for someone stays ("usuń wszystkie
                                  wiadomości" deletes those too)

Stored on the Pi only: DATA_DIR/messages/*.wav (16 kHz mono) and index.json
with the time, the transcript and whether it was heard.
"""

import json
import os
import threading
import time
import wave

import numpy as np

from config import DATA_DIR
from shared_state import state

DIR = os.path.join(DATA_DIR, "messages")
INDEX = os.path.join(DIR, "index.json")
KEEP = 20

_lock = threading.Lock()
_waiting = [False, 0.0, None, None]   # recording armed, when, for whom, from whom


def _load():
    try:
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items):
    os.makedirs(DIR, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX)
    with state.lock:                      # the envelope on her screen
        state.messages_waiting = sum(1 for m in items if not m.get("heard"))


def refresh():
    """At start: how many unheard messages wait (for the envelope)."""
    with _lock:
        items = _load()
    with state.lock:
        state.messages_waiting = sum(1 for m in items if not m.get("heard"))


def arm(to=None):
    """The next utterance is a message (for 20 s), for `to` if given."""
    with state.lock:
        frm = state.person[0] if state.person else None
    _waiting[:] = [True, time.time(), to, frm]


def armed():
    if _waiting[0] and time.time() - _waiting[1] > 20:
        _waiting[0] = False
    return _waiting[0]


def store(pcm16k, transcript):
    """Save the recorded utterance. Returns its length in seconds."""
    _waiting[0] = False
    os.makedirs(DIR, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S") + ".wav"
    with wave.open(os.path.join(DIR, name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm16k)
    with _lock:
        items = _load()
        items.append({"file": name, "t": time.time(), "text": transcript, "heard": False,
                      "to": _waiting[2], "from": _waiting[3]})
        for old in items[:-KEEP]:
            try:
                os.remove(os.path.join(DIR, old["file"]))
            except OSError:
                pass
        _save(items[-KEEP:])
    secs = len(pcm16k) / 32000
    print(f"[messages] saved {name} ({secs:.1f}s): {transcript!r}", flush=True)
    return secs


def unheard(who=None):
    """Unheard messages — with `who`: those for them or for everyone (not
    the ones they left themselves)."""
    with _lock:
        items = [m for m in _load() if not m.get("heard")]
    if who is None:
        return items
    return [m for m in items if m.get("to") in (None, who) and m.get("from") != who]


def _when(t):
    lt, now = time.localtime(t), time.localtime()
    hm = time.strftime("%H:%M", lt)
    if lt.tm_yday == now.tm_yday and lt.tm_year == now.tm_year:
        return f"dzisiaj o {hm}"
    if (time.time() - t) < 2 * 86400 and lt.tm_yday == (now.tm_yday - 1):
        return f"wczoraj o {hm}"
    return time.strftime("%d.%m o %H:%M", lt)


def _pcm24(path):
    """The WAV (16 kHz) as 24 kHz PCM for the player."""
    with wave.open(path, "rb") as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    if a.size == 0:
        return b""
    n = int(a.size * 24000 / 16000)
    b = np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a)
    return b.astype(np.int16).tobytes()


def play(speak, play_clip):
    """Play the unheard messages, or the latest one. Returns False if none."""
    with _lock:
        items = _load()
    with state.lock:
        who = state.person[0] if state.person else None
    todo = (unheard(who) if who else [m for m in items if not m.get("heard")]) or items[-1:]
    if not todo:
        return False
    for m in todo:
        path = os.path.join(DIR, m["file"])
        if not os.path.exists(path):
            continue
        frm = f" od: {m['from']}" if m.get("from") else ""
        to = f" dla: {m['to']}" if m.get("to") else ""
        speak(f"Wiadomość{frm}{to}, {_when(m['t'])}:")
        play_clip(_pcm24(path))
    with _lock:
        items = _load()
        for m in items:
            if m["file"] in {t["file"] for t in todo}:
                m["heard"] = True
        _save(items)
    return True


def delete(everything=False):
    """Delete the heard messages (all with everything=True).
    → (deleted, kept): kept are the unheard ones left for someone."""
    with _lock:
        items = _load()
        gone = [m for m in items if everything or m.get("heard")]
        keep = [m for m in items if m not in gone]
        for m in gone:
            try:
                os.remove(os.path.join(DIR, m["file"]))
            except OSError:
                pass
        _save(keep)
    return len(gone), keep


def delete_all():
    delete(everything=True)
