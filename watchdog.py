"""
watchdog.py — Luna must never just freeze.

On 4 Oct a lock taken twice froze every thread at her first word; she sat
there, deaf and still, until someone restarted her by hand. This thread
checks every WATCH_EVERY seconds that

  • state.lock can be taken (a deadlock holds it forever), and
  • the face keeps drawing frames (the main thread is alive),

and when either has been stuck for FREEZE_SECS it writes every thread's
stack to the log (faulthandler — exactly where they are stuck) and ends the
process; lwrespawn starts her again a few seconds later.

`kill -USR2 <pid>` writes the same stacks without stopping her.
"""

import faulthandler
import os
import signal
import sys
import threading
import time

from shared_state import state

WATCH_EVERY = 5
FREEZE_SECS = 30
GRACE_SECS = 60            # start-up: models load, the face isn't up yet


def _frames():
    try:
        import robot_face
        return robot_face.frame_stats["frames"]
    except Exception:
        return None


def _die(why):
    print(f"\n[watchdog] FROZEN: {why} — stacks of all threads follow, then a "
          "restart", flush=True)
    try:
        faulthandler.dump_traceback(file=sys.stdout, all_threads=True)
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(1)                       # lwrespawn brings her back


def _loop():
    time.sleep(GRACE_SECS)
    lock_ok = frames_ok = time.time()
    last_frames = _frames()
    while True:
        time.sleep(WATCH_EVERY)
        now = time.time()
        if state.lock.acquire(timeout=WATCH_EVERY):
            state.lock.release()
            lock_ok = now
        n = _frames()
        if n is None or n != last_frames:
            frames_ok, last_frames = now, n
        if now - lock_ok > FREEZE_SECS:
            _die(f"state.lock held for {now - lock_ok:.0f} s")
        if now - frames_ok > FREEZE_SECS:
            _die(f"no face frame for {now - frames_ok:.0f} s")


def start_watchdog():
    try:
        faulthandler.register(signal.SIGUSR2, file=sys.stdout, all_threads=True)
    except (AttributeError, ValueError):
        pass                          # not on this platform
    threading.Thread(target=_loop, daemon=True, name="watchdog").start()
