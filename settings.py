"""
settings.py — preferences changed by voice that must survive a restart
(data/settings.json). Today: how fast she speaks ("mów wolniej").

Volume is not here: PipeWire / WirePlumber already remembers the sink's
volume across restarts.
"""

import json
import os
import threading

from config import SETTINGS_PATH

_lock = threading.Lock()
_data = None
_mtime = [None]        # the file as this process last read or wrote it


def _file_mtime():
    try:
        return os.stat(SETTINGS_PATH).st_mtime_ns
    except OSError:
        return None


def _load():
    """Re-read when the file changed under us (a hand edit, a script), so a
    put() never writes an old copy back over it."""
    global _data
    m = _file_mtime()
    if _data is not None and m == _mtime[0]:
        return
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            _data = json.load(f)
    except (OSError, ValueError):
        if _data is None:
            _data = {}
    _mtime[0] = m


def get(key, default=None):
    with _lock:
        _load()
        return _data.get(key, default)


def put(key, value):
    with _lock:
        _load()
        _data[key] = value
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, SETTINGS_PATH)
        _mtime[0] = _file_mtime()
