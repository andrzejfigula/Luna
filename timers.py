"""
timers.py — kitchen timers and reminders.

  "Luna, minutnik na 10 minut"                    → timer, 600 s
  "przypomnij mi o 18 żeby zadzwonić do mamy"     → reminder at 18:00
  "za pół godziny przypomnij mi o praniu"         → timer with a label
  "wyłącz minutnik" / "ile zostało?"              → the model sees the list

The model asks for them through the "actions" field of its JSON reply (see
brain.py); this module keeps them in data/timers.json so they survive a
restart, shows the nearest one as a small countdown in the corner of the
screen, and when one is due: a chime, her face lights up, and she says what
it was for. If nobody reacts (touch or speech) she reminds once more a minute
later. Timers ring even in quiet hours or after "Luna, cicho" — you asked for
them.
"""

import json
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared_state import state
from config import TIMERS_PATH, TIMERS_MAX, TIMER_REPEAT_SECS, LUNA_TIMEZONE

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception:
    _TZ = None

_lock   = threading.Lock()
_timers = []        # [{"due": epoch, "label": str, "kind": "timer"|"reminder", "set": epoch}]


# ── persistence ──────────────────────────────────────────────────────────────

def _load():
    global _timers
    try:
        with open(TIMERS_PATH, encoding="utf-8") as f:
            _timers = [t for t in json.load(f) if "due" in t]
    except FileNotFoundError:
        _timers = []
    except (OSError, ValueError) as e:
        print(f"[timers] could not read {TIMERS_PATH} ({e})")
        _timers = []


def _save():
    tmp = TIMERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_timers, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TIMERS_PATH)


# ── what the model asks for ──────────────────────────────────────────────────

def _parse_at(at):
    """'2026-10-04 18:00' (local time) → epoch, or None."""
    try:
        dt = datetime.strptime(at.strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:                                   # just "18:00": today (or tomorrow)
            hm = datetime.strptime(at.strip()[:5], "%H:%M")
            now = datetime.now(_TZ) if _TZ else datetime.now()
            dt = now.replace(hour=hm.hour, minute=hm.minute, second=0,
                             microsecond=0, tzinfo=None)
        except ValueError:
            return None
    if _TZ:
        dt = dt.replace(tzinfo=_TZ)
    due = dt.timestamp()
    if due < time.time() - 60:                 # already past today → tomorrow
        due += 86400
    return due


def apply(actions):
    """Carry out the model's timer actions. Returns a short log string."""
    done = []
    with _lock:
        for a in actions or []:
            kind  = str(a.get("type", "")).lower()
            label = str(a.get("label", "")).strip()
            if kind == "timer":
                secs = int(a.get("seconds") or 0)
                if 0 < secs <= 7 * 86400:
                    _timers.append({"due": time.time() + secs, "label": label,
                                    "kind": "timer", "secs": secs, "set": time.time()})
                    done.append(f"timer {secs}s '{label}'")
            elif kind == "reminder":
                due = _parse_at(str(a.get("at", "")))
                if due:
                    _timers.append({"due": due, "label": label, "kind": "reminder",
                                    "set": time.time()})
                    done.append(f"reminder {time.strftime('%d.%m %H:%M', time.localtime(due))} '{label}'")
            elif kind == "cancel":
                before = len(_timers)
                if label:
                    _timers[:] = [t for t in _timers
                                  if label.lower() not in t["label"].lower()]
                if not label or len(_timers) == before:
                    _timers.clear()            # "wyłącz minutnik" with one set
                done.append(f"cancelled {before - len(_timers)}")
        _timers.sort(key=lambda t: t["due"])
        del _timers[TIMERS_MAX:]
        if done:
            _save()
    if done:
        print("[timers] " + "; ".join(done), flush=True)
    return done


def _left(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


def prompt_block():
    """Active timers for the system prompt (so "ile zostało?" works)."""
    with _lock:
        items = list(_timers)
    if not items:
        return "\nActive timers and reminders: none.\n"
    now = time.time()
    lines = ["\nActive timers and reminders (soonest first):"]
    for t in items:
        at = time.strftime("%H:%M", time.localtime(t["due"]))
        what = t["label"] or ("minutnik" if t["kind"] == "timer" else "przypomnienie")
        lines.append(f"- {t['kind']} \"{what}\": rings at {at}, {_left(t['due'] - now)} left")
    return "\n".join(lines) + "\n"


def countdown_text():
    """What the corner of the screen shows: the nearest timer, or None."""
    with _lock:
        if not _timers:
            return None
        t = _timers[0]
    left = t["due"] - time.time()
    if t["kind"] == "reminder" and left > 3600:
        return time.strftime("%H:%M", time.localtime(t["due"]))
    left = max(0, int(left))
    h, rem = divmod(left, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── ringing ──────────────────────────────────────────────────────────────────

def _minutes_pl(n):
    if n == 1:
        return "minuta"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "minuty"
    return "minut"


def _announcement(t, missed=False):
    label = t["label"]
    if t["kind"] == "timer":
        mins = round(t.get("secs", 0) / 60)
        if label:
            text = f"Minął czas: {label}!"
        elif mins >= 1:
            verb = "Minęła" if mins == 1 else ("Minęły" if _minutes_pl(mins) == "minuty" else "Minęło")
            text = f"Dzyń! {verb} {mins} {_minutes_pl(mins)}."
        else:
            text = "Dzyń! Minutnik!"
    else:
        text = f"Przypominam: {label}!" if label else "Przypominam o czymś!"
    if missed:
        text = "Byłam wyłączona i przegapiłam przypomnienie. " + text
    return text


def _interacted_since(t0):
    with state.lock:
        return state.touch_time > t0 or state.last_activity_time > t0


def _ring(t, missed=False):
    from text_to_speech import speak, play_sound
    from commands import wake_up
    wake_up("timer")
    text = _announcement(t, missed)
    for attempt in range(2):
        with state.lock:
            state.face_override = "surprised"
            state.face_override_until = time.time() + 4.0
            state.gesture_anim = "wave"
            state.gesture_anim_start = time.time()
        play_sound("chime", can_drop=False)
        speak(text if attempt == 0 else "Halo! " + text)
        rang = time.time()
        if attempt == 0:
            # once more in a minute, unless you touched her or talked to her
            while time.time() - rang < TIMER_REPEAT_SECS:
                if _interacted_since(rang):
                    return
                time.sleep(0.5)


def _watch():
    first = True
    while True:
        try:
            now = time.time()
            due = []
            with _lock:
                while _timers and _timers[0]["due"] <= now:
                    due.append(_timers.pop(0))
                if due:
                    _save()
            for t in due:
                missed = first and now - t["due"] > 120
                print(f"[timers] ringing: {t['kind']} '{t['label']}'", flush=True)
                threading.Thread(target=_ring, args=(t, missed), daemon=True).start()
            first = False
            with state.lock:
                state.timer_text = countdown_text()
        except Exception as e:
            print(f"[timers] watch error (recovering): {e}")
        time.sleep(0.5)


def start_timers():
    with _lock:
        _load()
    if _timers:
        print(f"[timers] {len(_timers)} pending from before")
    threading.Thread(target=_watch, daemon=True, name="timers").start()
