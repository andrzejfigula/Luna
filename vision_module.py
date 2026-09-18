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

from config import VISION_FPS
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
    while True:
        try:
            _vision_iteration_loop()
        except Exception as e:
            # never let a bad frame kill the vision thread
            print(f"[vision] loop error (recovering): {e}")
            time.sleep(1.0)


def _vision_iteration_loop():
    sleep_time = 1.0 / VISION_FPS

    while True:
        t0 = time.monotonic()

        with state.lock:
            frame = state.frame

        if frame is None:
            time.sleep(0.1)
            continue

        # detect on a half-size copy — Haar cost scales with pixel count and
        # the camera now runs at 640x480 so the LLM gets a usable picture
        small = cv2.resize(frame, (frame.shape[1] // 2, frame.shape[0] // 2))
        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        if len(faces) > 0:
            x, y, w, h = faces[0]
            face_cx = (x + w / 2) / small.shape[1]
            face_cy = (y + h / 2) / small.shape[0]

            with state.lock:
                state.face_detected  = True
                state.face_x         = face_cx
                state.face_y         = face_cy
                state.last_face_time = time.time()   # addressed-speech gate
        else:
            with state.lock:
                state.face_detected = False

        elapsed   = time.monotonic() - t0
        remaining = sleep_time - elapsed
        if remaining > 0:
            time.sleep(remaining)


def start_vision():
    t = threading.Thread(target=vision_loop, daemon=True)
    t.name = "vision"
    t.start()
