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
                    WAVE_HEAD_EXCLUDE, WAVE_FACE_GRACE_SECS, WAVE_MIN_PRESENCE,
                    WAVE_MIN_MEAN_SPEED, WAVE_SWING_REGULARITY,
                    WAVE_MAX_BELOW_FACE, WAVE_MIN_SKIN, WAVE_SKIN_SIGMA,
                    WAVE_MIN_AREA_FACE, GESTURE_DEBUG)
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


_last_debug = 0.0
last_features = ""     # features of the most recent evaluation (for the log)


def _wave_in(track):
    """track: deque of (t, x, y). True when the blob oscillates SIDEWAYS
    like a wave: enough left/right direction changes, each after a real
    swing, and horizontal travel dominating vertical travel."""
    global _last_debug, last_features
    now = time.time()
    win = [r[1:] for r in track if now - r[0] <= WAVE_WINDOW_SECS]
    pts = [r for r in win if r[0] is not None]
    if len(pts) < 6:
        return False
    presence = len(pts) / max(1, len(win))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    area = sum(p[2] for p in pts) / len(pts)          # mean blob area (px²)
    dxf  = sum(p[3] for p in pts) / len(pts)          # mean offset from the face,
    dyf  = sum(p[4] for p in pts) / len(pts)          # in half-face units (signed y)
    skin = sum(p[5] for p in pts) / len(pts)          # mean skin fraction of the blob
    farea = sum(p[6] for p in pts) / len(pts)         # mean face box area
    area_ratio = area / max(1.0, farea)
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    mean_speed = sum(abs(b - a) for a, b in zip(xs, xs[1:])) / (len(xs) - 1)
    reversals, swings = _count_swings(xs)
    regularity = (min(swings) / max(swings)) if swings else 0.0

    ok = (presence >= WAVE_MIN_PRESENCE and span_x >= WAVE_MIN_AMPLITUDE
          and span_y <= span_x * WAVE_MAX_VERTICAL
          and dyf <= WAVE_MAX_BELOW_FACE
          and skin >= WAVE_MIN_SKIN
          and area_ratio >= WAVE_MIN_AREA_FACE
          and mean_speed >= WAVE_MIN_MEAN_SPEED
          and reversals >= WAVE_MIN_REVERSALS
          and regularity >= WAVE_SWING_REGULARITY)
    last_features = (f"presence={presence:.2f} span_x={span_x:.0f} "
                     f"span_y={span_y:.0f} speed={mean_speed:.1f} rev={reversals} "
                     f"area={area:.0f} ({area_ratio:.2f} face) dxf={dxf:.1f} "
                     f"dyf={dyf:+.1f} skin={skin:.2f}")
    if GESTURE_DEBUG and reversals >= 3 and now - _last_debug > 0.5:
        _last_debug = now
        print(f"[gesture] {'WAVE' if ok else 'cand'} {last_features} "
              f"swings={[round(s) for s in swings]}", flush=True)
    return ok


def _count_swings(xs):
    """Direction changes that follow a real swing (≥ WAVE_MIN_SWING px) and
    the length of each completed swing."""
    # count direction changes, but only after the hand has travelled at
    # least WAVE_MIN_SWING px since the last turn (ignores jitter)
    reversals = 0
    swings    = []             # length of each completed swing
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
            swings.append(abs(extreme - anchor))
            last_dir  = -last_dir
            anchor, extreme = extreme, x
    return reversals, swings


# ── skin model from the face ──────────────────────────────────────────────────
_skin = None   # (meanCr, stdCr, meanCb, stdCb)


def _update_skin_model(ycrcb, cx, cy, fw, fh):
    """Sample the central part of the face box for the person's skin tone."""
    global _skin
    x0, x1 = max(0, cx - fw // 2), min(W, cx + fw // 2)
    y0, y1 = max(0, cy - fh // 2), min(H, cy + fh // 2)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    patch = ycrcb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    cr, cb = patch[:, 1], patch[:, 2]
    _skin = (float(cr.mean()), max(4.0, float(cr.std())),
             float(cb.mean()), max(4.0, float(cb.std())))


def _skin_fraction(ycrcb, x, y, w, h):
    """Fraction of pixels in the box that match the face's skin tone."""
    if _skin is None:
        return 1.0                       # no reference yet — don't block
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    box = ycrcb[y0:y1, x0:x1].astype(np.float32)
    mcr, scr, mcb, scb = _skin
    m = ((np.abs(box[:, :, 1] - mcr) < WAVE_SKIN_SIGMA * scr) &
         (np.abs(box[:, :, 2] - mcb) < WAVE_SKIN_SIGMA * scb))
    return float(m.mean())


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
                last_face     = state.last_face_time
                fx, fy        = state.face_x, state.face_y     # last known
                fwf           = state.face_w
                speaking      = state.speaking
            # a face seen a moment ago still counts — the detector drops
            # frames while the hand moves next to the head
            face_detected = face_detected or (time.time() - last_face
                                              < WAVE_FACE_GRACE_SECS)

            if frame is None:
                time.sleep(0.2)
                continue
            if WAVE_REQUIRE_FACE and not face_detected:
                prev = None            # don't let stale diffs pile up
                track.clear()
                time.sleep(period)
                continue

            small = cv2.resize(frame, (W, H))
            ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
            grey  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            grey  = cv2.GaussianBlur(grey, (5, 5), 0)
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
                if state.face_detected:              # fresh face → refresh skin tone
                    _update_skin_model(ycrcb, cx, cy, fw, fh)
                ex, ey = int(fw * WAVE_HEAD_EXCLUDE), int(fh * WAVE_HEAD_EXCLUDE)
                x0, y0 = max(0, cx - ex), max(0, cy - ey)
                x1, y1 = min(W, cx + ex), min(H, cy + ey)
                mask[y0:y1, x0:x1] = 0

            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                    np.ones((3, 3), np.uint8))
            n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
            x = y = None
            area = 0; dx = dy = 0.0; skin = 0.0
            farea = 1.0
            if face_detected:
                _cx, _cy, _fw, _fh = _face_box(fx, fy, fwf)
                farea = float(4 * _fw * _fh)
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
                        dy = (by - cy) / max(1, fh)         # signed: + = below face
                        near_ok = (WAVE_MIN_FACE_DIST <= dx <= WAVE_MAX_FACE_DIST
                                   and abs(dy) <= WAVE_MAX_FACE_VDIST)
                    if near_ok:
                        x, y = float(bx), float(by)
                        skin = _skin_fraction(ycrcb, int(stats[i, cv2.CC_STAT_LEFT]),
                                              int(stats[i, cv2.CC_STAT_TOP]),
                                              int(stats[i, cv2.CC_STAT_WIDTH]),
                                              int(stats[i, cv2.CC_STAT_HEIGHT]))
            track.append((time.time(), x, y, area, dx, dy, skin, farea))

            if (x is not None and not speaking
                    and time.time() - last_fire > WAVE_WINDOW_SECS
                    and _wave_in(track)):
                last_fire = time.time()
                track.clear()
                print(f"[gesture] WAVE detected  {last_features}", flush=True)
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
