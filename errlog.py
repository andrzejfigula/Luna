"""
errlog.py — an error that is passed over on purpose still leaves one line.

`except Exception: pass` kept her running and hid what broke (a window that
closed early, a part that never started). once() in the except block prints
the error the first time that place meets it; guard() starts a part of her
and, if it can't start, says so and lets the rest come up.
"""

import sys
import traceback

_seen = {}             # (file, line, error type) → how many times


def once(tag):
    """In an except block: log this error the first time this line sees it."""
    kind, err, tb = sys.exc_info()
    if kind is None:
        return
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = (tb.tb_frame.f_code.co_filename, tb.tb_lineno) if tb else ("?", 0)
    key = (*where, kind.__name__)
    _seen[key] = _seen.get(key, 0) + 1
    if _seen[key] == 1:
        name = where[0].replace("\\", "/").rsplit("/", 1)[-1]
        print(f"[{tag}] passed over: {kind.__name__}: {err} ({name}:{where[1]})", flush=True)


def counts():
    """{(file, line, error): times} — what has been passed over since the start."""
    return dict(_seen)


died = []              # names of threads that ended on an exception
# the loops she can't do without; each is started under this name
ESSENTIAL = ("timers", "mic", "health", "backup", "weather", "memory", "holds",
             "commands", "watchdog")


def _thread_died(args):
    """threading.excepthook: the traceback already went to the log; this adds
    one line to search for and remembers the name for the hourly health line."""
    name = getattr(args.thread, "name", "?")
    if args.exc_type is SystemExit:
        return
    died.append(name)
    print(f"[Luna] thread '{name}' DIED: {args.exc_type.__name__}: {args.exc_value}", flush=True)
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    sys.stderr.flush()


def watch_threads():
    import threading
    threading.excepthook = _thread_died


def threads_line():
    """"" while all is well; else what died and which essential loop is gone."""
    import threading
    alive = {t.name for t in threading.enumerate()}
    gone = [n for n in ESSENTIAL if n not in alive]
    parts = ([f"died: {', '.join(sorted(set(died)))}"] if died else []) \
        + ([f"not running: {', '.join(gone)}"] if gone else [])
    return "; ".join(parts)


def guard(what, fn, *args):
    """Start a part of her; one that fails is logged and left out — she still
    comes up (an exception here used to end the whole start)."""
    try:
        return fn(*args)
    except Exception:
        print(f"[Luna] {what} did not start — going on without it:", flush=True)
        traceback.print_exc()
        sys.stderr.flush()
        return None
