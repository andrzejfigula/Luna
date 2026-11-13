"""
drill.py — break things on purpose and see that she copes. Silent, scratch data.

    ssh raspberry@raspberrypi.local 'cd ~/luna && ./venv/bin/python tools/drill.py'

Each safety net was written after one real failure and never ran again: a
broken data file, a save that can't finish, a microphone that goes silent, a
part that won't start, a thread that dies, a frozen face. This runs each one
for real — in its own process, beside the running Luna, with a stand-in
text_to_speech, a temp LUNA_DATA_DIR and no audio device opened.
"""

import contextlib
import io
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = tempfile.mkdtemp(prefix="luna-drill-")
os.environ["LUNA_DATA_DIR"] = DATA


class _Silent(type(sys)):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


sys.modules["text_to_speech"] = _Silent("text_to_speech")


def _quiet(fn, *args):
    """fn's result and what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        result = fn(*args)
    return result, out.getvalue()


def broken_file():
    """A data file turned to rubbish: the backup's copy comes back, the rubbish is kept."""
    import backup
    import store
    path = os.path.join(DATA, "lists.json")
    store.save(path, {"zakupy": ["mleko", "chleb"]})
    _quiet(backup.backup_now)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"zakupy": ["ml')
    data, said = _quiet(store.load, path, {}, "drill")
    aside = [n for n in os.listdir(DATA) if n.startswith("lists.json.corrupt-")]
    assert data == {"zakupy": ["mleko", "chleb"]}, f"got {data!r}"
    assert aside, "the broken file was not kept"
    assert store.load(path, {}, "drill") == data, "the file on disk was not put back"
    assert "the backup of" in said, said
    return "the list came back from the backup, the broken file kept beside it"


def failed_save():
    """The disk refuses a write half way: the old file is whole, nothing half-written."""
    import store
    path = os.path.join(DATA, "timers.json")
    store.save(path, [{"label": "herbata"}])
    real = os.replace
    os.replace = lambda *a: (_ for _ in ()).throw(OSError(28, "No space left on device"))
    try:
        try:
            store.save(path, [])
            raise AssertionError("the save did not fail")
        except OSError:
            pass
    finally:
        os.replace = real
    assert store.load(path, [], "drill") == [{"label": "herbata"}]
    assert not [n for n in os.listdir(DATA) if n.endswith(".tmp")], "a .tmp was left"
    return "the old file is whole, no .tmp left"


def silent_mic():
    """The stream is open but hands over nothing: noticed and closed, to be opened again."""
    try:
        import speech_to_text as stt
    except ImportError as e:
        return f"SKIPPED: no {e.name} here — run it on the Pi"

    class Stream:
        closed = False

        def stop(self):
            pass

        def close(self):
            self.closed = True

    fake = Stream()
    stt._stream, stt._mic_ok = fake, True
    stt._last_block[0] = time.time() - 1
    assert not stt._stalled(), "a stream that just gave audio counted as silent"
    stt._last_block[0] = time.time() - stt.MIC_SILENT_SECS - 1
    assert stt._stalled(), "the silence was not noticed"
    _, said = _quiet(stt._close_for_new_mic, "drill: no audio")
    assert fake.closed and not stt._mic_ok and stt._stream is None
    assert "reopening" in said, said
    return f"noticed after {stt.MIC_SILENT_SECS} s, closed; the keeper opens a new one within 1–5 s"


def part_not_starting():
    """A part of her raises at start: one line, and the start goes on."""
    import errlog
    result, said = _quiet(errlog.guard, "the drill's part", lambda: 1 / 0)
    assert result is None and "did not start — going on without it" in said, said
    assert errlog.guard("a good part", lambda: 7) == 7
    return "logged, the rest came up"


def dead_thread():
    """A loop dies on an exception: a DIED line, and the hourly line names it."""
    import errlog
    old, before = threading.excepthook, list(errlog.died)
    errlog.watch_threads()
    try:
        t = threading.Thread(target=lambda: [][1], name="timers", daemon=True)
        _, said = _quiet(lambda: (t.start(), t.join(5)))
        line = errlog.threads_line()
    finally:
        threading.excepthook = old
        errlog.died[:] = before
    assert "thread 'timers' DIED: IndexError" in said, said
    assert "died: timers" in line and "not running:" in line, line
    return "the death is one line; the hourly check says: " + line[:60]


def frozen_face():
    """No new frame from the face: the watchdog decides to restart her."""
    import watchdog

    class Stop(Exception):
        pass

    def die(why):
        raise Stop(why)

    keep = (watchdog.GRACE_SECS, watchdog.WATCH_EVERY, watchdog.FREEZE_SECS,
            watchdog._frames, watchdog._die, list(watchdog._quiet))
    watchdog.GRACE_SECS, watchdog.WATCH_EVERY, watchdog.FREEZE_SECS = 0, 0.05, 0.3
    watchdog._frames, watchdog._die = (lambda: 5), die
    watchdog._quiet[0] = 0
    started = time.time()
    try:
        watchdog._loop()
    except Stop as e:
        why = str(e)
    finally:
        (watchdog.GRACE_SECS, watchdog.WATCH_EVERY, watchdog.FREEZE_SECS,
         watchdog._frames, watchdog._die) = keep[:5]
        watchdog._quiet[:] = keep[5]
    assert "no face frame" in why, why
    assert time.time() - started < 5
    return "restart decided: " + why + " (the limits shortened for the drill)"


DRILLS = [broken_file, failed_save, silent_mic, part_not_starting, dead_thread, frozen_face]


def run(drills=DRILLS):
    """[(name, "ok" | "SKIPPED" | "FAILED", what happened)]"""
    import config
    assert os.path.realpath(config.DATA_DIR) == os.path.realpath(DATA), \
        "not the scratch data directory — nothing run"
    rows = []
    for d in drills:
        try:
            said = d()
            if said.startswith("SKIPPED: "):
                rows.append((d.__name__, "SKIPPED", said[9:]))
            else:
                rows.append((d.__name__, "ok", said))
        except Exception as e:
            rows.append((d.__name__, "FAILED", f"{type(e).__name__}: {e}"))
    return rows


def main():
    rows = run()
    for name, how, said in rows:
        print(f"  {how:7s} {name.replace('_', ' ')}: {said}")
    bad = sum(how == "FAILED" for _, how, _ in rows)
    held = sum(how == "ok" for _, how, _ in rows)
    print(f"drill: {held} of {len(rows)} held" + (f", {bad} FAILED" if bad else "")
          + (f", {len(rows) - held - bad} skipped" if held + bad < len(rows) else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)          # threads of the modules it loaded must not keep it alive
