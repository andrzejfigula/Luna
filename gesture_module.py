"""
gesture_module.py — wave detection from camera motion (OpenCV only).

MediaPipe can't run on the Pi 4 with Python 3.13 (its wheels need ARMv8.2
instructions the Cortex-A72 lacks), so gestures are detected from motion:

  frame → 160x120 grey → |diff with previous| → motion mask
        → drop the face region (head movement isn't a gesture)
        → largest hand-sized blob → centroid x over time
        → a WAVE is ≥ WAVE_MIN_REVERSALS left/right direction reversals with
          ≥ WAVE_MIN_AMPLITUDE px of travel inside WAVE_WINDOW_SECS

Cheap (~1 ms/frame) and specific: nodding, walking past or typing don't
oscillate horizontally at hand height. Writes state.gesture = "WAVE" with
state.gesture_time; behavior_engine.py reacts and clears it.
"""

import threading
import time
from collections import deque

import cv2
import numpy as np

from config import (GESTURE_FPS, WAVE_WINDOW_SECS, WAVE_MIN_REVERSALS,
                    WAVE_MIN_AMPLITUDE, WAVE_MIN_SWING, WAVE_MAX_VERTICAL,
                    WAVE_MIN_AREA,
                    WAVE_MAX_AREA, WAVE_DIFF_THRESHOLD, WAVE_REQUIRE_FACE,
                    WAVE_MIN_FACE_DIST, WAVE_MAX_FACE_DIST, WAVE_MAX_FACE_VDIST,
                    WAVE_HEAD_EXCLUDE, GESTURE_DEBUG)
from shared_state import state

W, H = 160, 120           # analysis resolution


def _face_box(face_x, face_y, face_w_frac):
    """Face rectangle in analysis coords (face_x is mirrored; face_w_frac is
    the detected width as a fraction of the frame). Returns centre and
    HALF-sizes."""
    cx = int((1.0 - face_x) * W)
    cy = int(face_y * H)
    fw = max(8, int(face_w_frac * W * 0.5))
    fh = int(fw * 1.25)
    return cx, cy, fw, fh


def _wave_in(track):
    """track: deque of (t, x, y). True when the blob oscillates SIDEWAYS
    like a wave: enough left/right direction changes, each after a real
    swing, and horizontal travel dominating vertical travel."""
    now = time.time()
    pts = [(x, y) for t, x, y in track
           if now - t <= WAVE_WINDOW_SECS and x is not None]
    if len(pts) < 6:
        return False
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x < WAVE_MIN_AMPLITUDE or span_y > span_x * WAVE_MAX_VERTICAL:
        return False
    # count direction changes, but only after the hand has travelled at
    # least WAVE_MIN_SWING px since the last turn (ignores jitter)
    reversals = 0
    last_dir  = 0
    anchor    = xs[0]          # x at the last turning point
    extreme   = xs[0]          # furthest point reached in the current direction
    for x in xs[1:]:
        if last_dir == 0:
            if abs(x - anchor) >= WAVE_MIN_SWING:
                last_dir = 1 if x > anchor else -1
                extreme = x
            continue
        if (x - extreme) * last_dir > 0:
            extreme = x                       # still going the same way
        elif abs(x - extreme) >= WAVE_MIN_SWING:
            reversals += 1                    # turned around by a real swing
            last_dir  = -last_dir
            anchor, extreme = extreme, x
    return reversals >= WAVE_MIN_REVERSALS


def gesture_loop():
    prev  = None
    track = deque(maxlen=int(WAVE_WINDOW_SECS * GESTURE_FPS * 2))
    period = 1.0 / GESTURE_FPS
    last_fire = 0.0

    while True:
        t0 = time.monotonic()
        try:
            with state.lock:
                frame         = state.frame
                face_detected = state.face_detected
                fx, fy        = state.face_x, state.face_y
                fwf           = state.face_w
                speaking      = state.speaking

            if frame is None:
                time.sleep(0.2)
                continue
            if WAVE_REQUIRE_FACE and not face_detected:
                prev = None            # don't let stale diffs pile up
                track.clear()
                time.sleep(period)
                continue

            grey = cv2.cvtColor(cv2.resize(frame, (W, H)), cv2.COLOR_BGR2GRAY)
            grey = cv2.GaussianBlur(grey, (5, 5), 0)
            if prev is None:
                prev = grey
                continue
            diff = cv2.absdiff(grey, prev)
            prev = grey
            mask = (diff > WAVE_DIFF_THRESHOLD).astype(np.uint8) * 255

            # ignore the head and a generous margin around it: turning the
            # head, adjusting glasses, taking headphones off all happen here
            near_ok = True
            if face_detected:
                cx, cy, fw, fh = _face_box(fx, fy, fwf)
                ex, ey = int(fw * WAVE_HEAD_EXCLUDE), int(fh * WAVE_HEAD_EXCLUDE)
                x0, y0 = max(0, cx - ex), max(0, cy - ey)
                x1, y1 = min(W, cx + ex), min(H, cy + ey)
                mask[y0:y1, x0:x1] = 0

            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                    np.ones((3, 3), np.uint8))
            n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
            x = y = None
            if n > 1:
                areas = stats[1:, cv2.CC_STAT_AREA]
                i = int(np.argmax(areas)) + 1
                area = int(stats[i, cv2.CC_STAT_AREA])
                if WAVE_MIN_AREA <= area <= WAVE_MAX_AREA:
                    bx, by = cents[i]
                    if face_detected:
                        # a wave happens clearly beside the head, roughly at
                        # head height — not on it, not across the room
                        cx, cy, fw, fh = _face_box(fx, fy, fwf)
                        dx = abs(bx - cx) / max(1, fw)      # in half-face-widths
                        dy = abs(by - cy) / max(1, fh)
                        near_ok = (WAVE_MIN_FACE_DIST <= dx <= WAVE_MAX_FACE_DIST
                                   and dy <= WAVE_MAX_FACE_VDIST)
                    if near_ok:
                        x, y = float(bx), float(by)
            track.append((time.time(), x, y))

            if (x is not None and not speaking
                    and time.time() - last_fire > WAVE_WINDOW_SECS
                    and _wave_in(track)):
                last_fire = time.time()
                track.clear()
                if GESTURE_DEBUG:
                    print("[gesture] WAVE detected")
                with state.lock:
                    state.gesture      = "WAVE"
                    state.gesture_time = last_fire
        except Exception as e:
            print(f"[gesture] loop error (recovering): {e}")
            time.sleep(1.0)

        remaining = period - (time.monotonic() - t0)
        if remaining > 0:
            time.sleep(remaining)


def start_gesture():
    t = threading.Thread(target=gesture_loop, daemon=True)
    t.name = "gesture"
    t.start()
