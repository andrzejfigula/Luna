"""
mouth.py — is the person in front of her talking? Seen, not heard.

The microphone can't tell your "stop!" from her own voice (bargein.py) or
your "Luna" from the radio; the camera can: a talking mouth moves. The
vision loop's face detector (YuNet) gives five points per face — eyes, nose
tip, mouth corners — a few times a second; this thread looks at every camera
frame (15 a second) and measures how much the picture of the mouth changed
since the last frame, minus how much the picture around the nose changed
(the head moving, the light changing, the box jumping when the points are
updated). That difference, averaged over WINDOW seconds, is the activity:
~0 for a still face, higher while talking.

    activity()       — now: (value, frames, face seen) for the biggest face
    during(secs)     — the last `secs`: share of frames with a face, median
                       and the highest WINDOW-average — for the log lines
                       ("[STT] heard=… mouth=…", "[mouth] while she spoke…")

MOUTH_STOP = "log" (config): while she speaks, activity ≥ MOUTH_TALK_ON for
MOUTH_TALK_SECS would stop her and listen — only logged until the numbers
from the room say where the line is (17 Oct, Andrzej: "detect when I speak
from the camera").
"""

import collections
import os
import threading
import time

import numpy as np

from shared_state import state

RATE = 15               # looks a second (the camera's own rate)
WINDOW = 0.6            # s averaged into one activity value
MARKS_FRESH = 0.6       # face points older than this: nobody to watch
KEEP = 30.0             # s of history for during()

_lock = threading.Lock()
_marks = [None]         # (14 numbers: box + 5 points on the FULL frame, time)
_hist = collections.deque()     # (time, score or None = no face)


def set_marks(row_small, scale, t=None):
    """The vision loop's biggest face (YuNet row, found on a frame `scale`
    times smaller) — or None when there is no face."""
    with _lock:
        if row_small is None:
            _marks[0] = None
        else:
            _marks[0] = (np.asarray(row_small[:14], np.float32) * scale,
                         time.time() if t is None else t)


def _patch(frame, cx, cy, w, h, size):
    """The grey, contrast-normalised picture of a box (None: off the frame,
    or flat — nothing to compare)."""
    import cv2
    H, W = frame.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    x1, y1 = int(round(cx + w / 2)), int(round(cy + h / 2))
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x1 - x0 < 8 or y1 - y0 < 6:
        return None
    crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    p = cv2.resize(crop, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    p -= p.mean()
    s = p.std()
    return p / s if s > 3.0 else None


def boxes(marks):
    """(mouth box, nose box) as (cx, cy, w, h) from the five face points."""
    reye, leye, nose = marks[4:6], marks[6:8], marks[8:10]
    rm, lm = marks[10:12], marks[12:14]
    eyes = float(np.hypot(*(leye - reye))) or 1.0
    mw = max(float(np.hypot(*(lm - rm))), 0.5 * eyes)
    mc = (rm + lm) / 2
    mouth = (mc[0], mc[1] + 0.15 * mw, 1.5 * mw, 1.1 * mw)
    ref = (nose[0], nose[1] - 0.25 * eyes, 0.6 * eyes, 0.45 * eyes)
    return mouth, ref


def score(prev, cur):
    """How much more the mouth changed than the nose: one frame's evidence."""
    dm = float(np.mean(np.abs(cur[0] - prev[0])))
    dr = float(np.mean(np.abs(cur[1] - prev[1])))
    return max(0.0, dm - dr)


def _window(now):
    vals = [s for t, s in _hist if now - t <= WINDOW and s is not None]
    return (sum(vals) / len(vals) if vals else 0.0), len(vals)


def activity():
    """(activity, frames it is made of, a face seen now)."""
    now = time.time()
    with _lock:
        a, n = _window(now)
        face = bool(_hist) and _hist[-1][1] is not None and now - _hist[-1][0] < 0.5
    return a, n, face


def during(secs, now=None):
    """(share of frames with a face, median activity, highest WINDOW-average)
    over the last `secs` seconds; None when the camera gave nothing."""
    now = time.time() if now is None else now
    with _lock:
        rows = [(t, s) for t, s in _hist if now - secs <= t <= now]
    if not rows:
        return None
    seen = [(t, s) for t, s in rows if s is not None]
    if not seen:
        return 0.0, 0.0, 0.0
    vals = sorted(s for _, s in seen)
    best = 0.0
    for t, _ in seen:                       # the busiest WINDOW inside it
        w = [s for t2, s in seen if t - WINDOW < t2 <= t]
        if len(w) >= 4:
            best = max(best, sum(w) / len(w))
    return len(seen) / len(rows), vals[len(vals) // 2], best


def describe(secs, now=None):
    """For the log: "mouth 0.12/0.40 (face 90%)" or "mouth: no face"."""
    d = during(secs, now)
    if d is None:
        return "mouth: no camera"
    share, med, best = d
    if share < 0.3:
        return f"mouth: no face ({share:.0%})"
    return f"mouth {med:.2f}/{best:.2f} (face {share:.0%})"


DUMP_REQUEST = "/tmp/mouth_dump.request"   # (SIGUSR2 is the watchdog's)
RAW_SECS = 600          # the last 10 min of patches, for tuning (dump())
_raw = collections.deque(maxlen=int(RAW_SECS * RATE))


def dump(path="/tmp/mouth_dump.npz"):
    """touch /tmp/mouth_dump.request: the last RAW_SECS of tiny grey patches (mouth 24×16,
    above the nose 12×10 — no faces), with the time, whether she was
    speaking and the microphone's level, to tune the score offline. Stays on
    the Pi."""
    rows = list(_raw)
    if not rows:
        print("[mouth] nothing to dump", flush=True)
        return
    np.savez_compressed(
        path,
        t=np.array([r[0] for r in rows]),
        mouth=np.stack([r[1] for r in rows]).astype(np.float16),
        ref=np.stack([r[2] for r in rows]).astype(np.float16),
        moved=np.array([r[3] for r in rows]),
        speaking=np.array([r[4] for r in rows]),
        mic=np.array([r[5] for r in rows], np.float32),
        face_w=np.array([r[6] for r in rows], np.float32))
    print(f"[mouth] dumped {len(rows)} frames to {path}", flush=True)


def _loop():
    import prio
    prio.background("mouth")
    last, prev, prev_mt = None, None, None
    while True:
        time.sleep(1.0 / RATE)
        with state.lock:
            frame = state.frame
            speaking, mic = state.speaking, state.mic_level
        if frame is None or frame is last:
            continue
        last = frame
        now = time.time()
        with _lock:
            m = _marks[0]
        cur, moved = None, False
        if m is not None and now - m[1] <= MARKS_FRESH:
            mouth, ref = boxes(m[0])
            pm = _patch(frame, *mouth, (24, 16))
            pr = _patch(frame, *ref, (12, 10))
            if pm is not None and pr is not None:
                cur = (pm, pr)
                # new face points: the boxes jumped — this frame's change is
                # the jump, not the mouth (it drowned the talking, 17 Oct)
                moved = prev_mt is not None and m[1] != prev_mt
                prev_mt = m[1]
                _raw.append((now, pm.astype(np.float16), pr.astype(np.float16), moved, speaking, mic, float(m[0][2])))
        if cur is None:
            s, prev, prev_mt = None, None, None
        else:
            s = score(prev, cur) if (prev is not None and not moved) else None
            prev = cur
        with _lock:
            # a face counts as seen even on a frame with no score (first, jump)
            _hist.append((now, s if s is not None else (0.0 if cur is not None else None)))
            while _hist and now - _hist[0][0] > KEEP:
                _hist.popleft()
        _watch(now)
        if int(now) != int(now - 1.0 / RATE) and os.path.exists(DUMP_REQUEST):
            try:
                os.remove(DUMP_REQUEST)
                dump()
            except OSError as e:
                print(f"[mouth] dump failed: {e}", flush=True)


_reply = {"on": False, "since": None, "logged": False, "t0": 0.0}


def _watch(now):
    """While she speaks: would the camera have stopped her? (logged)"""
    from config import MOUTH_STOP, MOUTH_TALK_ON, MOUTH_TALK_SECS
    with state.lock:
        speaking = state.speaking
    r = _reply
    if speaking and not r["on"]:
        r.update(on=True, since=None, logged=False, t0=now)
    elif not speaking and r["on"]:
        r["on"] = False
        if now - r["t0"] < 1.5:              # a "hmm", a click: nothing to say
            return
        print(f"[mouth] while she spoke {now - r['t0']:.1f}s: {describe(now - r['t0'], now)}",
              flush=True)
        return
    if not speaking or not MOUTH_STOP:
        return
    a, n, face = activity()
    if face and n >= 4 and a >= MOUTH_TALK_ON:
        if r["since"] is None:
            r["since"] = now
        elif now - r["since"] >= MOUTH_TALK_SECS and not r["logged"]:
            r["logged"] = True
            if MOUTH_STOP == "log":
                print(f"[mouth] (log only) would stop her — activity {a:.2f} "
                      f"for {now - r['since']:.1f}s", flush=True)
            else:
                _stop(a)
    else:
        r["since"] = None


def _stop(a):
    import text_to_speech
    text_to_speech.stop_speaking(who=f"mouth (activity {a:.2f})")
    with state.lock:                         # listen at once, no "Luna" needed
        state.conversation_active = True
        state.last_activity_time = time.time()
        state.mic_unblock_time = time.time()


def start():
    threading.Thread(target=_loop, daemon=True, name="mouth").start()
