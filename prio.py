"""
prio.py — which of Luna's threads may be pushed aside.

PipeWire has no realtime scheduling on this Pi (no rtkit), so the audio
players compete for the CPU like everything else. The whole process used to
run under `nice -n 10` — and every pw-play it started inherited that, so her
own voice stream lost to her own face renderer: PipeWire counted thousands
of xruns on it and you heard the words clipped.

Now only the heavy, delay-tolerant threads are niced (face renderer, camera,
vision); the players and the voice thread keep normal priority. On Linux the
nice value is per thread, and a child process inherits the value of the
thread that started it.
"""

import os
import threading

BACKGROUND_NICE = 10


def background(name=""):
    """Lower the calling thread's priority (no-op where unsupported)."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), BACKGROUND_NICE)
    except (AttributeError, OSError) as e:
        print(f"[prio] {name}: {e}")
