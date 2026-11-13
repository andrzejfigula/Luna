"""
store.py — the JSON files in data/: read safely, written whole.

A file that can't be read is never taken for an empty one and then written
over: load() moves it aside (name.json.corrupt-<time>) and puts the newest
backup's copy back (backup.py). save() writes beside the file, syncs it to
the card, then swaps it in — a power cut leaves the old file or the new one.
"""

import json
import os
import shutil
import threading
import time

_blocked = set()       # load() could neither read nor move these aside: save() refuses


def backup_name(path):
    """The file's name inside a backup's day folder, None if it isn't in data/."""
    import config
    for root, prefix in ((config.DATA_DIR, ""), (config.PHOTOS_DIR, "photos-")):
        try:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
        except ValueError:                       # (Windows: another drive)
            continue
        if not rel.startswith(".."):
            return prefix + rel.replace(os.sep, "-")
    return None


def backups_dir():
    import config
    return os.path.join(config.DATA_DIR, "backups")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fits(data, default):
    """A list where a dict is kept (or the other way) is a broken file too."""
    return not isinstance(default, (dict, list)) or isinstance(data, type(default))


def _from_backup(path, default):
    """(day, file, data) of the newest backup copy that still reads, or None."""
    name = backup_name(path)
    if not name:
        return None
    try:
        days = sorted((d for d in os.listdir(backups_dir()) if not d.endswith(".tmp")),
                      reverse=True)
    except OSError:
        return None
    for day in days:
        src = os.path.join(backups_dir(), day, name)
        try:
            data = _read(src)
        except (OSError, ValueError):
            continue
        if _fits(data, default):
            return day, src, data
    return None


def load(path, default, tag="store"):
    """The file's data; `default` when there is no file. A file that doesn't
    read is kept aside and the last backup's copy comes back in its place."""
    for last in (False, True):
        try:
            data = _read(path)
            if _fits(data, default):
                _blocked.discard(path)
                return data
            why = f"holds a {type(data).__name__}, not a {type(default).__name__}"
        except FileNotFoundError:
            return default
        except (OSError, ValueError) as e:
            why = str(e)
        if not last:
            time.sleep(0.3)            # (a hand edit or scp caught half written)
    aside = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, aside)
        _blocked.discard(path)
    except OSError as e:
        _blocked.add(path)
        print(f"[{tag}] {path} can't be read ({why}) nor moved aside ({e}) — "
              "nothing will be written over it", flush=True)
        return default
    back = _from_backup(path, default)
    if back:
        day, src, data = back
        try:
            shutil.copy2(src, path)
        except OSError as e:
            print(f"[{tag}] the backup copy could not be put back ({e})", flush=True)
        print(f"[{tag}] {path} can't be read ({why}): kept as {os.path.basename(aside)}, "
              f"the backup of {day} is back", flush=True)
        return data
    print(f"[{tag}] {path} can't be read ({why}): kept as {os.path.basename(aside)}, "
          "no backup copy — starting empty", flush=True)
    return default


def save(path, data, indent=None, sync=True):
    """Write the whole file or nothing (OSError when it can't be written).
    sync=False for what is rewritten often and could be lost (a cache)."""
    if path in _blocked:
        raise OSError(f"{path} could not be read: not written over")
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            if sync:
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
