"""
test_scenes.py — play every scene in the catalogue through the real renderer
and report any that raise.

Run it on the Pi after touching idle_scenes.py or robot_face.py:

    ./stop.sh && ./venv/bin/python test_scenes.py ; ./run.sh &

It exists because a refactor once moved five scenes' drawing code inside
another method: they raised NameError the moment they were picked, the
renderer died, and the watchdog restarted Luna — with no traceback anywhere,
because the shutdown path called os._exit() first. Exceptions are printed
now, and this catches the same class of bug before you ship it.
"""

import time, traceback
from shared_state import state
import idle_scenes
from robot_face import RobotFace

face = RobotFace()
bad = []
for name in sorted(idle_scenes.SCENES):
    sc = idle_scenes.SCENES[name]
    with state.lock:
        state.idle_action = name
        state.idle_action_start = time.time()
        state.face_detected = True
        state.last_face_time = time.time()
        if sc.mood:
            state.face_override = sc.mood
            state.face_override_until = time.time() + sc.duration
    t0 = time.time()
    err = None
    # run the whole scene, sped up: step the start time backwards so the
    # full 0..1 progress is covered in ~1.5 s of real time
    steps = 90
    for i in range(steps):
        with state.lock:
            state.idle_action_start = time.time() - (i / steps) * sc.duration
        try:
            face.draw()
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
            break
    if err:
        bad.append((name, err))
        print("FAIL %-14s %s" % (name, err), flush=True)
    with state.lock:
        state.idle_action = None
        state.face_override = None
print("=== scenes tested:", len(idle_scenes.SCENES), "failures:", len(bad), flush=True)
for n, e in bad:
    print("   ", n, "->", e, flush=True)
print("DONE", flush=True)
