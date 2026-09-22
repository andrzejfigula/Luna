"""
touch_module.py — the 7" DSI touchscreen as a way to interact with Luna.

SDL/Wayland does not deliver touch events to the pygame window (verified on
this Pi: no FingerDown, no MouseButtonDown), so the panel's evdev node is read
directly. It works regardless of window focus and has no SDL quirks; the user
only needs to be in the "input" group.

Raw events → gestures, published on shared state for robot_face.py (instant
visual reaction) and idle_engine.py (voice reaction):

  tap     — quick touch, barely any movement
  stroke  — finger dragged across the face ("petting")
  multi   — TOUCH_MULTI_COUNT taps inside TOUCH_MULTI_WINDOW ("poking")
"""

import fcntl
import glob
import select
import struct
import threading
import time

from config import (TOUCH_ENABLED, TOUCH_DEVICE, TOUCH_TAP_MAX_SECS,
                    TOUCH_STROKE_MIN, TOUCH_STROKE_REPEAT,
                    TOUCH_MULTI_WINDOW, TOUCH_MULTI_COUNT, TOUCH_POKE_HOLD,
                    TOUCH_FLIP_X, TOUCH_FLIP_Y, TOUCH_DEBUG)
from shared_state import state

# ── evdev constants ───────────────────────────────────────────────────────────
_FMT = "llHHi"                      # struct input_event on 64-bit
_SZ  = struct.calcsize(_FMT)
EV_KEY, EV_ABS = 0x01, 0x03
BTN_TOUCH      = 0x14a
ABS_X, ABS_Y   = 0x00, 0x01
ABS_MT_X, ABS_MT_Y = 0x35, 0x36


def _eviocgabs(axis):
    """_IOR('E', 0x40 + axis, struct input_absinfo) — 6 × s32 = 24 bytes."""
    return (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + axis)


def _abs_range(fd, axis):
    """(min, max) of an absolute axis, or None when the axis doesn't exist."""
    try:
        buf = fcntl.ioctl(fd, _eviocgabs(axis), b"\x00" * 24)
        _value, minimum, maximum, _fuzz, _flat, _res = struct.unpack("6i", buf)
        return (minimum, maximum) if maximum > minimum else None
    except OSError:
        return None


def _find_device():
    """Configured device, else the first evdev node with a touch X axis."""
    if TOUCH_DEVICE:
        return TOUCH_DEVICE
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            with open(path, "rb", buffering=0) as f:
                if _abs_range(f.fileno(), ABS_MT_X) or _abs_range(f.fileno(), ABS_X):
                    return path
        except OSError:
            continue          # no permission / not readable — skip
    return None


# ── gesture recognition ───────────────────────────────────────────────────────

def _publish(kind, nx, ny):
    with state.lock:
        state.touch_kind = kind
        state.touch_x    = nx
        state.touch_y    = ny
        state.touch_time = time.time()
    if TOUCH_DEBUG:
        print(f"[touch] {kind} at ({nx:.2f}, {ny:.2f})", flush=True)


def _reader_loop(path):
    try:
        f = open(path, "rb", buffering=0)
    except OSError as e:
        print(f"[touch] cannot open {path}: {e} — touch disabled "
              f"(is the user in the 'input' group?)")
        return

    rx = _abs_range(f.fileno(), ABS_MT_X) or _abs_range(f.fileno(), ABS_X) or (0, 800)
    ry = _abs_range(f.fileno(), ABS_MT_Y) or _abs_range(f.fileno(), ABS_Y) or (0, 480)
    print(f"[touch] {path} ready (x {rx[0]}-{rx[1]}, y {ry[0]}-{ry[1]})")

    def norm(v, rng, flip):
        n = (v - rng[0]) / max(1, rng[1] - rng[0])
        n = min(1.0, max(0.0, n))
        return 1.0 - n if flip else n

    x = y = None
    down_t = 0.0
    down_pos = (0.0, 0.0)
    moved = 0.0
    stroked = False
    pub_pos = (0.0, 0.0)           # where the last stroke was reported
    pub_t   = 0.0
    taps = []                      # timestamps of recent taps
    poking_until = 0.0             # while poking, further taps stay "multi"

    while True:
        try:
            r, _, _ = select.select([f], [], [], 0.5)
            if not r:
                continue
            data = f.read(_SZ)
            if not data or len(data) < _SZ:
                continue
            _s, _us, etype, code, value = struct.unpack(_FMT, data)

            if etype == EV_ABS:
                if code in (ABS_X, ABS_MT_X):
                    x = norm(value, rx, TOUCH_FLIP_X)
                elif code in (ABS_Y, ABS_MT_Y):
                    y = norm(value, ry, TOUCH_FLIP_Y)
                if down_t and x is not None and y is not None:
                    moved = max(moved, abs(x - down_pos[0]) + abs(y - down_pos[1]))
                    since = abs(x - pub_pos[0]) + abs(y - pub_pos[1])
                    now_t = time.time()
                    if not stroked and moved >= TOUCH_STROKE_MIN:
                        stroked = True
                        pub_pos, pub_t = (x, y), now_t
                        _publish("stroke", x, y)
                    elif (stroked and since >= TOUCH_STROKE_MIN
                            and now_t - pub_t >= TOUCH_STROKE_REPEAT):
                        pub_pos, pub_t = (x, y), now_t
                        _publish("stroke", x, y)   # still being petted

            elif etype == EV_KEY and code == BTN_TOUCH:
                if value == 1 and x is not None and y is not None:
                    down_t   = time.time()
                    down_pos = (x, y)
                    moved    = 0.0
                    stroked  = False
                elif value == 0 and down_t:
                    held = time.time() - down_t
                    if not stroked and held <= TOUCH_TAP_MAX_SECS:
                        now = time.time()
                        if now < poking_until:
                            # still being poked — don't fall back to a
                            # friendly "tap" on the 4th, 5th, ... touch
                            poking_until = now + TOUCH_POKE_HOLD
                            _publish("multi", x, y)
                        else:
                            taps = [t for t in taps if now - t <= TOUCH_MULTI_WINDOW]
                            taps.append(now)
                            if len(taps) >= TOUCH_MULTI_COUNT:
                                taps = []
                                poking_until = now + TOUCH_POKE_HOLD
                                _publish("multi", x, y)
                            else:
                                _publish("tap", x, y)
                    down_t = 0.0
        except Exception as e:
            print(f"[touch] read error (recovering): {e}")
            time.sleep(1.0)


def start_touch():
    if not TOUCH_ENABLED:
        return
    path = _find_device()
    if not path:
        print("[touch] no touchscreen found — touch interaction disabled")
        return
    t = threading.Thread(target=_reader_loop, args=(path,), daemon=True)
    t.name = "touch"
    t.start()
