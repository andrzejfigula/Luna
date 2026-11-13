"""
backup.py — a copy a day of everything Luna has learned.

Every write in data/ is atomic (write, then rename), so a power cut can't
leave half a file — but an SD card can still die or a bad edit can wipe a
list. Once a day (at start and then every few hours, when the date has
changed) every small JSON and text file of data/ goes to
data/backups/YYYY-MM-DD/, with who is in which photo and the voice-message
index. The last BACKUP_DAYS days are kept and the first copy of each of the
last BACKUP_WEEKS weeks; models, sounds and recordings are not copied (they
are big, or can be made again). store.py takes a file back from here by
itself when the one in data/ no longer reads.

Restore: stop Luna, copy the files of a day back into data/, start her.
"""

import datetime
import os
import shutil
import threading
import time

from config import DATA_DIR, PHOTOS_DIR

BACKUP_DAYS = 7
BACKUP_WEEKS = 8           # …and the first copy of each of the last weeks: a list
                           # emptied unnoticed is still there after the seven days
OFFSITE_MAX_DAYS = 2       # a copy off the Pi older than this: one line a day in the log
MAX_BYTES = 5 * 1024 * 1024
DIR = os.path.join(DATA_DIR, "backups")


def _sources():
    """Every small .json / .txt of data/ (a new feature's file needs no line
    here: calendar.json and schedule.json were missing from the old list),
    the voice-message index and who is in which photo."""
    out = []
    try:
        names = sorted(os.listdir(DATA_DIR))
    except OSError:
        names = []
    for f in names:
        if f.endswith((".json", ".txt")):
            out.append(os.path.join(DATA_DIR, f))
    out.append(os.path.join(DATA_DIR, "messages", "index.json"))
    out.append(os.path.join(PHOTOS_DIR, "people.json"))
    return [p for p in out if os.path.isfile(p) and os.path.getsize(p) <= MAX_BYTES]


def _name(src):
    """The copy's name in the day's folder (store.py finds it again by this)."""
    for root, prefix in ((DATA_DIR, ""), (PHOTOS_DIR, "photos-")):
        rel = os.path.relpath(src, root)
        if not rel.startswith(".."):
            return prefix + rel.replace(os.sep, "-")
    return os.path.basename(src)


def _kept(days):
    """Of the day folders: the last BACKUP_DAYS, and each recent week's first."""
    keep, dated, weeks = set(), [], {}
    for d in sorted(days):
        try:
            y, w, _ = datetime.date.fromisoformat(d).isocalendar()
        except ValueError:
            keep.add(d)                        # not ours: left alone
            continue
        dated.append(d)
        weeks.setdefault((y, w), d)
    keep.update(dated[-BACKUP_DAYS:])
    keep.update(sorted(weeks.values())[-BACKUP_WEEKS:])
    return keep


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
    for src in _sources():
        shutil.copy2(src, os.path.join(tmp, _name(src)))
        n += 1
    os.replace(tmp, dest)                      # a day's folder is complete or absent
    days = [d for d in os.listdir(DIR) if not d.endswith(".tmp")]
    for old in sorted(set(days) - _kept(days)):
        shutil.rmtree(os.path.join(DIR, old), ignore_errors=True)
    print(f"[backup] {n} files → {dest}", flush=True)
    return dest


def offsite_days(now=None):
    """Days since tools/pull_backup.sh last copied her data off the Pi (it
    leaves data/.offsite); None: never."""
    try:
        return max(0.0, ((now or time.time()) - os.path.getmtime(os.path.join(DATA_DIR, ".offsite"))) / 86400)
    except OSError:
        return None


def offsite_warning(now=None):
    """A line for the log when the only copies are on this SD card."""
    age = offsite_days(now)
    if age is not None and age <= OFFSITE_MAX_DAYS:
        return ""
    since = "never" if age is None else f"{age:.0f} days ago"
    return (f"[backup] last copy off the Pi: {since} — everything is on one SD card; "
            "run tools/pull_backup.sh on the PC")


def _pictures():
    """The quizzes' flag and animal pictures, fetched once (quiz.py)."""
    try:
        import quiz
        quiz.prefetch_pictures()
    except Exception as e:
        print(f"[quiz] pictures failed: {e}", flush=True)


def _loop():
    # (10 min after a start: not while she is still waking up; once, not at
    # every round of the loop)
    t = threading.Timer(600, _pictures)
    t.daemon = True
    t.start()
    while True:
        try:
            if backup_now() and offsite_warning():        # once a day, with the new copy
                print(offsite_warning(), flush=True)
        except Exception as e:
            print(f"[backup] failed: {e}", flush=True)
        time.sleep(3 * 3600)


def start_backup():
    threading.Thread(target=_loop, daemon=True, name="backup").start()
