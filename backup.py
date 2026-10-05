"""
backup.py — a copy a day of everything Luna has learned.

Every write in data/ is atomic (write, then rename), so a power cut can't
leave half a file — but an SD card can still die or a bad edit can wipe a
list. Once a day (at start and then every few hours, when the date has
changed) the small JSON files go to data/backups/YYYY-MM-DD/: her memory,
the faces she knows, lists, timers, settings, how she feels about people,
her day, who is in which photo, the voice-message index. The last
BACKUP_DAYS days are kept; models, sounds and recordings are not copied
(they are big, or can be made again).

Restore: stop Luna, copy the files of a day back into data/, start her.
"""

import os
import shutil
import threading
import time

from config import DATA_DIR, PHOTOS_DIR

BACKUP_DAYS = 7
DIR = os.path.join(DATA_DIR, "backups")
FILES = ["memory.json", "people.json", "lists.json", "timers.json", "settings.json",
         "relations.json", "day.json", "diary.json", "errands.json", os.path.join("messages", "index.json")]


def backup_now():
    """Copy today's files (once a day). Returns the folder, or None."""
    day = time.strftime("%Y-%m-%d")
    dest = os.path.join(DIR, day)
    if os.path.isdir(dest):
        return None
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    n = 0
    sources = [(os.path.join(DATA_DIR, f), f) for f in FILES]
    sources.append((os.path.join(PHOTOS_DIR, "people.json"), "photos-people.json"))
    for src, name in sources:
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(tmp, name.replace(os.sep, "-")))
            n += 1
    os.replace(tmp, dest)                      # a day's folder is complete or absent
    for old in sorted(d for d in os.listdir(DIR) if not d.endswith(".tmp"))[:-BACKUP_DAYS]:
        shutil.rmtree(os.path.join(DIR, old), ignore_errors=True)
    print(f"[backup] {n} files → {dest}", flush=True)
    return dest


def _loop():
    while True:
        try:
            backup_now()
        except Exception as e:
            print(f"[backup] failed: {e}", flush=True)
        time.sleep(3 * 3600)


def start_backup():
    threading.Thread(target=_loop, daemon=True, name="backup").start()
