"""
display.py — the touchscreen's backlight.

run.sh sets the panel to LUNA_BRIGHTNESS at start. While Luna runs, one
thread here decides the brightness from her situation and fades to it:

  a wake-up alarm is near            → rises from where it is to full,
                                       like a dawn (timers.py sets it)
  asleep ("dobranoc")                → SLEEP_BRIGHTNESS
  night (quiet hours), you talk      → NIGHT_TALK_BRIGHTNESS
  night, nobody talking              → NIGHT_BRIGHTNESS
  day                                → LUNA_BRIGHTNESS
  …and in any case no brighter than the room's light calls for (camera,
  AMBIENT_*), down to AMBIENT_MIN_BRIGHTNESS in a dark room

Never brighter than LUNA_BRIGHTNESS. The backlight file is writable by the
"video" group, so no sudo is needed.
"""

import glob
import os
import threading
import time

import config  # noqa: F401  (loads .env into the environment)

_lock = threading.Lock()


def _panels():
    return sorted(glob.glob("/sys/class/backlight/*"))


def base_percent():
    """The brightness you chose in .env (LUNA_BRIGHTNESS), default 100."""
    try:
        return max(5, min(100, int(os.environ.get("LUNA_BRIGHTNESS", "100"))))
    except ValueError:
        return 100


def set_percent(pct):
    """Set every backlight to pct % of its maximum. Returns True on success."""
    pct = max(1, min(100, int(pct)))
    ok = False
    with _lock:
        for bl in _panels():
            try:
                with open(os.path.join(bl, "max_brightness")) as f:
                    mx = int(f.read().strip())
                with open(os.path.join(bl, "brightness"), "w") as f:
                    f.write(str(max(1, mx * pct // 100)))
                ok = True
            except (OSError, ValueError) as e:
                print(f"[display] {os.path.basename(bl)}: {e}")
    return ok


def _night():
    from config import PROACTIVE_QUIET_FROM as a, PROACTIVE_QUIET_TO as b
    h = time.localtime().tm_hour
    return a <= h < b if a <= b else (h >= a or h < b)


def target_percent():
    from shared_state import state
    from config import (NIGHT_MODE, NIGHT_BRIGHTNESS, NIGHT_TALK_BRIGHTNESS,
                        SLEEP_BRIGHTNESS)
    base = base_percent()
    with state.lock:
        asleep  = state.sleep_mode
        talking = state.conversation_active or state.speaking
        dawn    = state.sunrise
        lamp    = bool(state.overlay and state.overlay[0] == "lamp"
                       and time.time() < state.overlay[1])
    if lamp:
        from config import LAMP_BRIGHTNESS
        return min(base, LAMP_BRIGHTNESS)
    if dawn:
        start, end = dawn
        k = max(0.0, min(1.0, (time.time() - start) / max(1.0, end - start)))
        low = min(base, SLEEP_BRIGHTNESS if asleep else NIGHT_BRIGHTNESS)
        return round(low + (base - low) * k * k)    # slow at first, like dawn
    if asleep:
        return min(base, SLEEP_BRIGHTNESS)
    if NIGHT_MODE and _night():
        return min(base, NIGHT_TALK_BRIGHTNESS if talking else NIGHT_BRIGHTNESS)
    return min(base, _ambient_cap(base))


def _ambient_cap(base):
    from shared_state import state
    from config import (AMBIENT_AUTO, AMBIENT_LOG_BRIGHT, AMBIENT_LOG_DARK,
                        AMBIENT_MIN_BRIGHTNESS)
    with state.lock:
        light = state.light
    if not AMBIENT_AUTO or light is None:
        return base
    k = (light - AMBIENT_LOG_DARK) / (AMBIENT_LOG_BRIGHT - AMBIENT_LOG_DARK)
    k = max(0.0, min(1.0, k))
    low = min(base, AMBIENT_MIN_BRIGHTNESS)
    return round(low + (base - low) * k)


def _manager():
    current = get_percent() or base_percent()
    while True:
        try:
            want = target_percent()
            if want != current:
                # fade: ~1 s whatever the distance
                step = max(1, abs(want - current) // 12)
                current += step if want > current else -step
                if abs(want - current) < step:
                    current = want
                set_percent(current)
                time.sleep(0.08)
                continue
        except Exception as e:
            print(f"[display] manager error: {e}")
        time.sleep(0.5)


def start_display():
    threading.Thread(target=_manager, daemon=True, name="display").start()


def get_percent():
    for bl in _panels():
        try:
            with open(os.path.join(bl, "max_brightness")) as f:
                mx = int(f.read().strip())
            with open(os.path.join(bl, "brightness")) as f:
                return round(int(f.read().strip()) * 100 / mx)
        except (OSError, ValueError):
            continue
    return None
