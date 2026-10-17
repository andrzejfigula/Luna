"""
mouth.py — is the person in front of her talking? Seen, not heard.

The microphone can't tell your "stop!" from her own voice (bargein.py) or
your "Luna" from the radio; the camera can: a talking mouth moves. The
vision loop's face detector (YuNet) gives five points per face — eyes, nose
tip, mouth corners — a few times a second; this thread looks at every camera
frame (15 a second) and measures how much the picture of the mouth changed
since the last frame, and how much the picture just above the nose did (the
head moving, the light changing). Averaged over WINDOW seconds: a still face
changes both alike; a talking mouth changes 2–3× more than the nose
(talking()). The frame where the boxes jump to new face points is skipped.

    activity()       — now: (talking, mouth change, nose change, face seen)
    during(secs)     — the last `secs`: share of frames with a face, share of
                       them that looked like talking, the best ratio — for the
                       log lines ("[STT] heard=… mouth…", "[mouth] while she spoke…")
    dump()           — the last 10 min of tiny patches, to tune it offline

MOUTH_STOP (config): while she speaks, talking seen for MOUTH_TALK_SECS
stops her and she listens at once, as a finger held on the screen does —
17 Oct, Andrzej: "detect when I speak from the camera" (the voice "stop!"
couldn't tell him from her own voice). Tuned on two dumps of him talking
over her: at MOUTH_RATIO 2.0 a second story was stopped 28 s late (talking
in bursts, the head moving a little); at 1.6 every try ~0.5–1 s in, and
still never while he listened, nodded or turned. The microphone's last
1.5 s go to the listener (speech_to_text.open_mic_now) — the words said
before she stopped.
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
_hist = collections.deque()     # (time, (mouth, nose change) | False = a face, no
                                # change to tell | None = no face)


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


def change(prev, cur):
    """(mouth change, change above the nose) from one frame to the next."""
    dm = float(np.mean(np.abs(cur[0] - prev[0])))
    dr = float(np.mean(np.abs(cur[1] - prev[1])))
    return dm, dr


def talking(dm, dr, n):
    """Does WINDOW's average change say "talking"? The mouth changed at
    least MOUTH_RATIO× more than above the nose (a still face: both ~0.02–
    0.07, the same), by at least MOUTH_MIN_CHANGE, and the head was fairly
    still (above the nose ≤ MOUTH_MAX_HEAD — a turning head changes both,
    the nose part often more, and says nothing). Tuned on 17 Oct's dump."""
    from config import MOUTH_RATIO, MOUTH_MIN_CHANGE, MOUTH_MAX_HEAD
    return (n >= 4 and dm >= MOUTH_MIN_CHANGE and dm >= MOUTH_RATIO * dr
            and dr <= MOUTH_MAX_HEAD)


def _window(rows, now):
    """(average mouth change, average nose change, frames) of WINDOW to `now`."""
    ds = [d for t, d in rows if now - WINDOW < t <= now and d]
    if not ds:
        return 0.0, 0.0, 0
    return sum(d[0] for d in ds) / len(ds), sum(d[1] for d in ds) / len(ds), len(ds)


def activity():
    """(talking now, mouth change, nose change, a face seen now)."""
    now = time.time()
    with _lock:
        dm, dr, n = _window(_hist, now)
        face = bool(_hist) and _hist[-1][1] is not None and now - _hist[-1][0] < 0.5
    return talking(dm, dr, n), dm, dr, face


def during(secs, now=None):
    """(share of frames with a face, share of them that looked like talking,
    the highest mouth/nose ratio of a WINDOW) over the last `secs` seconds;
    None when the camera gave nothing."""
    now = time.time() if now is None else now
    with _lock:
        rows = [(t, d) for t, d in _hist if now - secs - WINDOW <= t <= now]
    inside = [(t, d) for t, d in rows if t >= now - secs]
    if not inside:
        return None
    seen = [(t, d) for t, d in inside if d is not None]
    if not seen:
        return 0.0, 0.0, 0.0
    talk, best = 0, 0.0
    for t, _ in seen:
        dm, dr, n = _window(rows, t)
        if n >= 4:
            best = max(best, dm / max(dr, 0.01))
        talk += talking(dm, dr, n)
    return len(seen) / len(inside), talk / len(seen), best


def describe(secs, now=None):
    """For the log: "mouth talking 40%, best ×2.6 (face 90%)" or "mouth: no face"."""
    d = during(secs, now)
    if d is None:
        return "mouth: no camera"
    share, talk, best = d
    if share < 0.3:
        return f"mouth: no face ({share:.0%})"
    return f"mouth talking {talk:.0%}, best ×{best:.1f} (face {share:.0%})"


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
            d, prev, prev_mt = None, None, None
        else:
            # False: a face, but nothing to compare (its first frame, a jump)
            d = change(prev, cur) if (prev is not None and not moved) else False
            prev = cur
        with _lock:
            _hist.append((now, d))
            while _hist and now - _hist[0][0] > KEEP:
                _hist.popleft()
        _watch(now)
        _duck_radio(now)
        if int(now) != int(now - 1.0 / RATE) and os.path.exists(DUMP_REQUEST):
            try:
                os.remove(DUMP_REQUEST)
                dump()
            except OSError as e:
                print(f"[mouth] dump failed: {e}", flush=True)


_reply = {"on": False, "since": None, "logged": False, "t0": 0.0}


def _watch(now):
    """While she speaks: would the camera have stopped her? (logged)"""
    from config import MOUTH_STOP, MOUTH_TALK_SECS
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
    talk, dm, dr, face = activity()
    if face and talk:
        if r["since"] is None:
            r["since"] = now
        elif now - r["since"] >= MOUTH_TALK_SECS and not r["logged"]:
            r["logged"] = True
            what = (f"mouth {dm:.2f} vs nose {dr:.2f} for "
                    f"{now - r['since'] + WINDOW:.1f}s")
            if MOUTH_STOP == "log":
                print(f"[mouth] (log only) would stop her — {what}", flush=True)
            else:
                print(f"[mouth] you're talking — {what}: she stops and listens", flush=True)
                _stop()
    else:
        r["since"] = None


_radio = {"since": None, "logged": 0.0}


def _duck_radio(now):
    """The radio plays and the face in front of her starts talking: it quiets
    at once (radio._ducked, the same 4 s as when her name is in Vosk's words)
    — so the rest of "Luna, jaka jutro pogoda?" is heard over it."""
    from config import MOUTH_TALK_SECS
    with state.lock:
        playing, speaking = state.radio, state.speaking
    if not playing or speaking:
        _radio["since"] = None
        return
    talk, dm, dr, face = activity()
    if not (face and talk):
        _radio["since"] = None
        return
    if _radio["since"] is None:
        _radio["since"] = now
    elif now - _radio["since"] >= MOUTH_TALK_SECS:
        with state.lock:
            state.name_heard_at = now
        if now - _radio["logged"] > 20:
            _radio["logged"] = now
            print(f"[mouth] someone facing her is talking — the radio quiets "
                  f"(mouth {dm:.2f} vs nose {dr:.2f})", flush=True)


def _stop():
    import speech_to_text
    import text_to_speech
    speech_to_text.open_mic_now()            # your first words, said over her
    text_to_speech.stop_speaking(who="the camera (your mouth moving)")
    with state.lock:                         # listen at once, no "Luna" needed
        state.conversation_active = True
        state.last_activity_time = time.time()
        state.mic_unblock_time = time.time()


def start():
    threading.Thread(target=_loop, daemon=True, name="mouth").start()
