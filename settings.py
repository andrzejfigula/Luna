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


def _load():
    global _data
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            _data = json.load(f)
    except (OSError, ValueError):
        _data = {}


def get(key, default=None):
    with _lock:
        if _data is None:
            _load()
        return _data.get(key, default)


def put(key, value):
    with _lock:
        if _data is None:
            _load()
        _data[key] = value
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, SETTINGS_PATH)
