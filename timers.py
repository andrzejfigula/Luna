"""
timers.py — kitchen timers, reminders and wake-up alarms.

  "Luna, minutnik na 10 minut"                    → timer, 600 s
  "przypomnij mi o 18 żeby zadzwonić do mamy"     → reminder at 18:00
  "za pół godziny przypomnij mi o praniu"         → timer with a label
  "wyłącz minutnik" / "ile zostało?"              → the model sees the list
  "obudź mnie o 7"                                → alarm: for SUNRISE_SECS
                                                    before, the screen
                                                    brightens like a dawn
                                                    (display.py), then a
                                                    good-morning with the
                                                    weather

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
from config import (TIMERS_PATH, TIMERS_MAX, TIMER_REPEAT_SECS, LUNA_TIMEZONE,
                    SUNRISE_SECS)

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


_REPEATS = {"none", "daily", "weekdays", "weekends"}


def _matches(dt, repeat):
    wd = dt.weekday()                       # Monday = 0
    return (repeat == "daily" or (repeat == "weekdays" and wd < 5)
            or (repeat == "weekends" and wd >= 5))


def _next_matching(due, repeat, inclusive=False):
    """The next time a repeating reminder rings: same wall-clock time on the
    next matching day (computed on the calendar, so a DST change doesn't
    shift it by an hour)."""
    dt = datetime.fromtimestamp(due, _TZ) if _TZ else datetime.fromtimestamp(due)
    if not inclusive:
        dt += timedelta(days=1)
    for _ in range(8):
        if _matches(dt, repeat):
            break
        dt += timedelta(days=1)
    if _TZ:                                  # re-resolve the offset for that day
        dt = dt.replace(tzinfo=None).replace(tzinfo=_TZ)
    return dt.timestamp()


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
            elif kind in ("reminder", "alarm"):
                due = _parse_at(str(a.get("at", "")))
                repeat = str(a.get("repeat", "none")).lower()
                if repeat not in _REPEATS:
                    repeat = "none"
                if due:
                    if repeat != "none":
                        due = _next_matching(due, repeat, inclusive=True)
                    _timers.append({"due": due, "label": label, "kind": kind,
                                    "repeat": repeat, "set": time.time()})
                    done.append(f"{kind} {time.strftime('%d.%m %H:%M', time.localtime(due))} "
                                f"'{label}'" + (f" ({repeat})" if repeat != "none" else ""))
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
        rep = t.get("repeat", "none")
        lines.append(f"- {t['kind']} \"{what}\": rings at {at}, {_left(t['due'] - now)} left"
                     + (f", repeats {rep}" if rep != "none" else ""))
    return "\n".join(lines) + "\n"


_REPEAT_PL = {"daily": "codziennie", "weekdays": "pn–pt", "weekends": "weekendy"}
_KIND_PL = {"timer": "minutnik", "reminder": "przypomnienie", "alarm": "budzik"}


def screen_lines():
    """What "pokaż przypomnienia" lists on her screen: (time, what) pairs."""
    with _lock:
        items = list(_timers)
    out = []
    now = time.time()
    for t in items:
        if t["kind"] == "timer":
            left = int(t["due"] - now)
            when = f"{left // 60}:{left % 60:02d}" if left < 3600 else                 time.strftime("%H:%M", time.localtime(t["due"]))
        else:
            when = time.strftime("%H:%M", time.localtime(t["due"]))
            if t["due"] - now > 86400 and t.get("repeat", "none") == "none":
                when = time.strftime("%d.%m %H:%M", time.localtime(t["due"]))
        what = t["label"] or _KIND_PL.get(t["kind"], "")
        rep = _REPEAT_PL.get(t.get("repeat", "none"))
        out.append((when, what + (f"  ({rep})" if rep else "")))
    return out


def countdown_text():
    """What the corner of the screen shows: the nearest timer, or None."""
    with _lock:
        if not _timers:
            return None
        t = _timers[0]
    left = t["due"] - time.time()
    if t["kind"] in ("reminder", "alarm") and left > 3600:
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
    if t["kind"] == "alarm":
        try:
            from brain import greeting
            text = greeting(True, waking=True)   # good morning + weather + plans
        except Exception:
            text = None
        return text or "Dzień dobry! Pora wstawać."
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
    import audio_out
    wake_up("timer")
    # a timer you set rings at full volume even in the quiet hours
    audio_out.full_volume_until = time.time() + TIMER_REPEAT_SECS + 60
    text = t.get("say") or _announcement(t, missed)
    if t.get("then"):                                # focus → break
        secs, label, say = t["then"]
        add(secs, label, say)
    for attempt in range(2):
        with state.lock:
            state.face_override = "surprised"
            state.face_override_until = time.time() + 4.0
            state.gesture_anim = "wave"
            state.gesture_anim_start = time.time()
        play_sound("chime", can_drop=False)
        if attempt and t["kind"] == "alarm":
            speak("Halo, śpiochu! Pora wstawać!")
        else:
            speak(text if attempt == 0 else "Halo! " + text)
        rang = time.time()
        if attempt == 0:
            # once more in a minute, unless you touched her or talked to her
            while time.time() - rang < TIMER_REPEAT_SECS:
                if _interacted_since(rang):
                    return
                time.sleep(0.5)


def add(seconds, label, say=None, then=None):
    """A timer set by Luna herself (focus mode): `say` replaces the usual
    announcement; `then` = (seconds, label, say) is set when it rings."""
    with _lock:
        _timers.append({"due": time.time() + seconds, "label": label, "kind": "timer",
                        "secs": seconds, "say": say, "then": then, "set": time.time()})
        _timers.sort(key=lambda t: t["due"])
        _save()


def remove(labels):
    with _lock:
        before = len(_timers)
        _timers[:] = [t for t in _timers if t["label"] not in labels]
        if len(_timers) != before:
            _save()


def _take_due(now):
    """Remove what is due now; a repeating one is put back for its next day."""
    due = []
    with _lock:
        while _timers and _timers[0]["due"] <= now:
            due.append(_timers.pop(0))
        for t in due:
            if t.get("repeat", "none") != "none":
                _timers.append(dict(t, due=_next_matching(t["due"], t["repeat"])))
        if due:
            _timers.sort(key=lambda t: t["due"])
            _save()
    return due


def _watch():
    first = True
    while True:
        try:
            now = time.time()
            due = _take_due(now)
            for t in due:
                if t["kind"] == "alarm":
                    from commands import wake_up     # before the dawn ends
                    wake_up("alarm")
                missed = first and now - t["due"] > 120
                print(f"[timers] ringing: {t['kind']} '{t['label']}'", flush=True)
                threading.Thread(target=_ring, args=(t, missed), daemon=True).start()
            first = False
            # a wake-up alarm close enough: the dawn on the screen
            with _lock:
                alarm = next((t for t in _timers if t["kind"] == "alarm"), None)
            dawn = None
            if alarm and alarm["due"] - now <= SUNRISE_SECS:
                dawn = (alarm["due"] - SUNRISE_SECS, alarm["due"])
            with state.lock:
                state.timer_text = countdown_text()
                state.sunrise = dawn
        except Exception as e:
            print(f"[timers] watch error (recovering): {e}")
        time.sleep(0.5)


def start_timers():
    with _lock:
        _load()
    if _timers:
        print(f"[timers] {len(_timers)} pending from before")
    threading.Thread(target=_watch, daemon=True, name="timers").start()
