"""
run_unit.py — the unit tests, noting which were skipped (no cv2, pygame,
sounddevice… on the PC), so tools/check_pi.sh runs just those on the Pi.

    python -X utf8 tests/run_unit.py [SKIPPED_FILE]             # all; skipped ids → file
    python -X utf8 tests/run_unit.py --jobs 8 [SKIPPED_FILE]    # the same, side by side
    python -X utf8 tests/run_unit.py --ids < FILE               # only these ids

With --jobs each worker is a fresh process with its own temp and data, and a
test class stays whole and in order. Not on the Pi: she shares its four cores.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULES = ["tests.test_local_logic", "tests.test_reply_stream", "tests.test_syntax",
           "tests.test_dev_tools"]
WORKER_TIMEOUT = 300


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run(suite, skipped_file=None):
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    if skipped_file:
        with open(skipped_file, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(t.id() + "\n" for t, _ in result.skipped)
    return 0 if result.wasSuccessful() else 1


def shares(ids, jobs):
    """Whole classes to `jobs` workers, the largest class first, to the emptiest."""
    classes = {}
    for test_id in ids:
        classes.setdefault(test_id.rsplit(".", 1)[0], []).append(test_id)
    bins = [[] for _ in range(jobs)]
    for group in sorted(classes.values(), key=len, reverse=True):
        min(bins, key=len).extend(group)
    return [b for b in bins if b]


def worker(ids):
    tmp = tempfile.mkdtemp(prefix="luna-unit-")
    skipped = os.path.join(tmp, "skipped")
    env = dict(os.environ, TMPDIR=tmp, TEMP=tmp, TMP=tmp, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), "--worker", skipped],
                           input="\n".join(ids), env=env, cwd=ROOT, text=True, encoding="utf-8",
                           errors="replace", capture_output=True, timeout=WORKER_TIMEOUT)
        lines = []
        if os.path.exists(skipped):
            with open(skipped, encoding="utf-8") as f:
                lines = f.read().split()
        return p.returncode, p.stdout + p.stderr, lines
    except subprocess.TimeoutExpired:
        return 1, f"ERROR: a worker took over {WORKER_TIMEOUT} s, on: {ids[0]} …", []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_jobs(jobs, skipped_file):
    t0 = time.time()
    tests = flatten(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    ids = [t.id() for t in tests]
    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(worker, shares(ids, jobs)))
    skipped, ran, ok = [], 0, True
    for code, out, skips in results:
        skipped += skips
        ran += sum(int(n) for n in re.findall(r"^Ran (\d+) tests?", out, re.M))
        if code != 0:
            ok = False
            print(out)
    if skipped_file:
        with open(skipped_file, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(i + "\n" for i in skipped)
    print(f"Ran {ran} tests in {time.time() - t0:.1f}s ({len(results)} workers)")
    print(f"OK (skipped={len(skipped)})" if ok else "FAILED")
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if args[:1] == ["--ids"]:
        ids = sys.stdin.read().split()
        if not ids:
            print("OK (nothing to run)")
            return 0
        return run(unittest.defaultTestLoader.loadTestsFromNames(ids))
    if args[:1] == ["--worker"]:
        # through the modules: test_local_logic's load_tests turns a missing cv2 into a skip
        wanted = set(sys.stdin.read().split())
        tests = flatten(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
        return run(unittest.TestSuite(t for t in tests if t.id() in wanted), args[1])
    if args[:1] == ["--jobs"]:
        return run_jobs(int(args[1]), args[2] if len(args) > 2 else None)
    return run(unittest.defaultTestLoader.loadTestsFromNames(MODULES), args[0] if args else None)


if __name__ == "__main__":
    sys.exit(main())
