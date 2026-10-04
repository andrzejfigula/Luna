"""
vision_module.py — face detection for eye-tracking + the addressed-speech gate.

Haar-cascade face detection only (OpenCV, cheap on a Pi 4). It drives:
  • state.face_x / face_y      — the eyes follow the person in front of Luna
  • state.face_detected        — sleep/wake, curiosity idle drift
  • state.last_face_time       — "is someone actually talking TO me" gate

Luna's own emotion is chosen by the LLM (see brain.py), so the old camera-side
emotion classifiers (PyTorch MobileNet + DeepFace/TensorFlow) are gone —
state.emotion stays "Neutral" from this thread and the LLM writes the face
state through state.face_override.
"""

import os
import cv2
import threading
import time

from config import (VISION_FPS, FACE_MIN_NEIGHBORS, FACE_SCALE_FACTOR,
                    FACE_MIN_SIZE, FACE_EQUALIZE, FACE_HOLD_SECS, VISION_DEBUG,
                    VISION_IDLE_FPS, VISION_IDLE_AFTER, VISION_FULL_EVERY)

_last_dbg = 0.0
_clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
from shared_state import state


def _cascade_path(name):
    """pip's opencv-python exposes cv2.data.haarcascades; Debian's
    python3-opencv doesn't, so also look in the distro's share dir."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "data", name)]   # bundled copy
    if hasattr(cv2, "data"):
        candidates.append(os.path.join(cv2.data.haarcascades, name))
    candidates += [
        f"/usr/share/opencv4/haarcascades/{name}",
        f"/usr/share/opencv/haarcascades/{name}",
        f"/usr/local/share/opencv4/haarcascades/{name}",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"{name} not found (expected in data/ or opencv-data)")


face_cascade = cv2.CascadeClassifier(
    _cascade_path("haarcascade_frontalface_default.xml")
)


def vision_loop():
    import prio
    prio.background("vision")
    while True:
        try:
            _vision_iteration_loop()
        except Exception as e:
            # never let a bad frame kill the vision thread
            print(f"[vision] loop error (recovering): {e}")
            time.sleep(1.0)


def _detect(gray, min_size, max_size=None):
    kw = dict(scaleFactor=FACE_SCALE_FACTOR, minNeighbors=FACE_MIN_NEIGHBORS,
              minSize=(min_size, min_size), flags=cv2.CASCADE_SCALE_IMAGE)
    if max_size:
        kw["maxSize"] = (max_size, max_size)
    return face_cascade.detectMultiScale(gray, **kw)


def _search_near(gray, box):
    """Look for the face only around where it just was, at about its size —
    a few scales of a small crop instead of every scale of the frame."""
    x, y, w, h = box
    H, W = gray.shape[:2]
    x0, y0 = max(0, x - w), max(0, y - h)
    x1, y1 = min(W, x + 2 * w), min(H, y + 2 * h)
    crop = gray[y0:y1, x0:x1]
    if crop.shape[0] < FACE_MIN_SIZE or crop.shape[1] < FACE_MIN_SIZE:
        return []
    faces = _detect(crop, max(FACE_MIN_SIZE, int(w * 0.6)), int(w * 1.6) + 1)
    return [(fx + x0, fy + y0, fw, fh) for fx, fy, fw, fh in faces]


def _vision_iteration_loop():
    last_box = None          # where the face was last time (small-frame coords)
    n = 0

    while True:
        t0 = time.monotonic()
        n += 1
        with state.lock:
            unseen = time.time() - state.last_face_time
            asleep = state.sleep_mode            # "dobranoc": no need to watch closely
        slow = unseen > VISION_IDLE_AFTER or asleep
        sleep_time = 1.0 / (VISION_IDLE_FPS if slow else VISION_FPS)

        with state.lock:
            frame = state.frame

        if frame is None:
            time.sleep(0.1)
            continue

        # detect on a half-size copy — Haar cost scales with pixel count and
        # the camera now runs at 640x480 so the LLM gets a usable picture
        small = cv2.resize(frame, (frame.shape[1] // 2, frame.shape[0] // 2))
        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if FACE_EQUALIZE:
            # local contrast equalisation: a face in shadow against a bright
            # window keeps its detail instead of being crushed to black
            gray = _clahe.apply(gray)
        faces = []
        if last_box is not None and n % VISION_FULL_EVERY:
            faces = _search_near(gray, last_box)
        if len(faces) == 0:
            faces = _detect(gray, FACE_MIN_SIZE)              # the whole frame

        if len(faces) > 0:
            # the biggest face is the person in front of Luna
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            last_box = (int(x), int(y), int(w), int(h))
            global _last_dbg
            if VISION_DEBUG and time.time() - _last_dbg > 2.0:
                _last_dbg = time.time()
                print(f"[vision] faces={len(faces)} picked x={x} y={y} w={w} h={h} "
                      f"of {small.shape[1]}x{small.shape[0]}  all={[tuple(int(v) for v in f) for f in faces]}",
                      flush=True)
            # Mirror x: the webcam faces the person, so someone on THEIR left
            # appears on the RIGHT of the image. Luna's eyes must move toward
            # the person, i.e. toward the viewer's left on the screen.
            face_cx = 1.0 - (x + w / 2) / small.shape[1]
            face_cy = (y + h / 2) / small.shape[0]

            with state.lock:
                state.face_detected  = True
                state.face_x         = face_cx
                state.face_y         = face_cy
                state.face_w         = w / small.shape[1]
                state.last_face_time = time.time()   # addressed-speech gate
        else:
            last_box = None
            with state.lock:
                # hold the last face briefly — Haar drops single frames
                if time.time() - state.last_face_time > FACE_HOLD_SECS:
                    state.face_detected = False

        elapsed   = time.monotonic() - t0
        remaining = sleep_time - elapsed
        if remaining > 0:
            time.sleep(remaining)


def start_vision():
    t = threading.Thread(target=vision_loop, daemon=True)
    t.name = "vision"
    t.start()
