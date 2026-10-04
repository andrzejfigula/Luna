"""
display.py — the touchscreen's backlight.

run.sh sets the panel to LUNA_BRIGHTNESS at start; this module lets Luna
change it while running (sleep mode, night mode). The backlight file is
writable by the "video" group, so no sudo is needed.
"""

import glob
import os
import threading

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
