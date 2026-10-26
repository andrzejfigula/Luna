"""
camera_thread.py — supports both ESP32 MJPEG stream and local USB/Pi camera.

USE_ESP32_CAM = True  → reads from ESP32 WiFi stream
USE_ESP32_CAM = False → reads from local camera (USB or Pi cam)
"""

import cv2
import threading

# OpenCV's worker pool busy-waits: on the Pi 4 threads spun at ~20 % each,
# starving the audio. One thread does the same work.
cv2.setNumThreads(1)
import time
import numpy as np
from config import (CAMERA_ID, FRAME_WIDTH, FRAME_HEIGHT,
                    FPS, ESP32_STREAM, USE_ESP32_CAM)
from shared_state import state
import devices
import settings


def _esp32_loop():
    """Read MJPEG stream from ESP32."""
    print(f"[camera] Connecting to ESP32 stream: {ESP32_STREAM}")

    while True:
        cap = cv2.VideoCapture(ESP32_STREAM)

        if not cap.isOpened():
            print("[camera] ESP32 stream not available — retrying in 3s")
            with state.lock:
                state.camera_ok = False
            time.sleep(3)
            continue

        print("[camera] ESP32 stream connected")
        with state.lock:
            state.camera_ok = True

        while True:
            ret, frame = cap.read()

            if not ret:
                print("[camera] ESP32 stream lost — reconnecting")
                break

            # resize to match expected frame size
            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

            with state.lock:
                state.frame = frame

        cap.release()
        time.sleep(2)   # wait before reconnecting


_opened = [None]           # the camera open now (settings page: "teraz: …")
STILL_SIZE = (1280, 960)   # the C270's largest MJPG frame: paper held up to be read
_still = {"want": 0, "frames": [], "done": None}


def grab_stills(n=4, timeout=10.0):
    """n frames at STILL_SIZE (a timetable on paper: 640x480 blurs its small
    print) — the camera thread switches up, grabs them, and back; [] when it
    can't (no camera, an ESP32 stream)."""
    if USE_ESP32_CAM:
        return []
    ev = threading.Event()
    _still.update(want=n, frames=[], done=ev)
    ev.wait(timeout)
    _still["want"] = 0
    return list(_still["frames"])


def _take_stills(cap):
    """In the camera thread: the stills, then back to the usual size. False
    when the camera didn't come back to it (the loop reopens it)."""
    n, out = _still["want"], []
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, STILL_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STILL_SIZE[1])
        t0 = last = time.time()
        while len(out) < n and time.time() - t0 < 6.0:
            ret, f = cap.read()
            if not ret:
                continue
            with state.lock:                 # the face tracking keeps its size
                state.frame = cv2.resize(f, (FRAME_WIDTH, FRAME_HEIGHT))
            # the exposure settles after the switch; a hand shakes: a moment apart
            if time.time() - t0 > 1.2 and time.time() - last > 0.3:
                out.append(f)
                last = time.time()
        print(f"[camera] {len(out)} stills at {out[0].shape[1]}x{out[0].shape[0]}" if out
              else "[camera] no stills", flush=True)
    finally:
        _still.update(want=0, frames=out)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        if _still["done"]:
            _still["done"].set()
    ret, f = cap.read()
    return bool(ret) and f.shape[1] == FRAME_WIDTH


def _open_local_camera():
    """Try the settings page's pick, the configured camera, then indices 0-2."""
    tried = []
    ids = devices.camera_ids()
    for cam_id in ids:
        if cam_id in tried:
            continue
        tried.append(cam_id)
        # V4L2 backend explicitly: OpenCV's GStreamer default takes ~6 s to
        # open a USB webcam on the Pi and spams warnings; V4L2 opens instantly.
        # cam_id may be an index (0) or a device path ("/dev/video2").
        cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS,          FPS)
            cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
            _opened[0] = cam_id
            if cam_id != ids[0]:
                print(f"[camera] Camera {ids[0]} unavailable — using {cam_id}")
            return cap
        cap.release()
    return None


def _measure_light(cap, frame):
    """Room light for auto-brightness: the camera compensates darkness with a
    longer exposure, so brightness / exposure tracks the real light. Kept as
    log10 and smoothed (~20 s) so a hand in front of the lens doesn't flicker
    the screen."""
    try:
        small = cv2.resize(frame, (80, 60))
        mean = float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())
        exposure = float(cap.get(cv2.CAP_PROP_EXPOSURE)) or 156.0
        level = np.log10(max(mean, 1.0) / max(exposure, 1.0))
        with state.lock:
            prev = state.light
            state.light = level if prev is None else prev + (level - prev) * 0.1
    except Exception:
        pass


def _privacy_wait():
    """"Wyłącz kamerę" (commands.py): no frames at all until the time is up —
    True while it waits a second."""
    with state.lock:
        off = time.time() < state.camera_off_until
        if off:
            state.frame = None
            state.camera_ok = False
    if off:
        time.sleep(1.0)
    return off


def _local_loop():
    """Read from local USB or Pi camera. Retries forever if no camera —
    Luna keeps running (voice + face) without vision."""
    import prio
    prio.background("camera")
    print(f"[camera] Starting local camera {CAMERA_ID}")
    help_printed = False

    while True:
        if _privacy_wait():
            continue
        picked = settings.get("camera")
        cap = _open_local_camera()

        if cap is None:
            if not help_printed:
                help_printed = True
                print("[camera] NO CAMERA FOUND — vision disabled, retrying every 5s")
                print("[camera] See README Troubleshooting: 'Camera not found'")
            with state.lock:
                state.camera_ok = False
            time.sleep(5.0)
            continue

        help_printed = False
        with state.lock:
            state.camera_ok = True
        print(f"[camera] Local camera started {FRAME_WIDTH}x{FRAME_HEIGHT} @ {FPS}fps")

        fail_count = 0
        last_light = 0.0
        while True:
            ret, frame = cap.read()

            if not ret:
                fail_count += 1
                if fail_count > 60:   # ~3s of failures → reopen device
                    print("[camera] Camera stopped responding — reopening")
                    break
                time.sleep(0.05)
                continue

            fail_count = 0
            with state.lock:
                state.frame = frame
                off = time.time() < state.camera_off_until
                if off:                      # "wyłącz kamerę": no last frame left behind
                    state.frame = None
                    state.camera_ok = False
            if off:                          # …and the device is let go
                break
            if _still["want"] and not _take_stills(cap):
                print("[camera] not back to its size after the stills — reopening", flush=True)
                break
            if time.time() - last_light > 2.0:
                last_light = time.time()
                _measure_light(cap, frame)
                if settings.get("camera") != picked:      # picked on the settings page
                    print(f"[camera] camera changed to {settings.get('camera') or 'auto'}")
                    break

        cap.release()
        _opened[0] = None
        time.sleep(2.0)


def start_camera():
    if USE_ESP32_CAM:
        t = threading.Thread(target=_esp32_loop, daemon=True)
    else:
        t = threading.Thread(target=_local_loop, daemon=True)

    t.name = "camera"
    t.start()