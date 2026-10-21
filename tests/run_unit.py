"""
run_unit.py — the unit tests, noting which were skipped (no cv2, pygame,
sounddevice… on the PC), so tools/check_pi.sh runs just those on the Pi.

    python -X utf8 tests/run_unit.py SKIPPED_FILE      # all, skipped ids → file
    python -X utf8 tests/run_unit.py --ids < FILE      # only these ids
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    loader = unittest.defaultTestLoader
    if sys.argv[1:] == ["--ids"]:
        ids = sys.stdin.read().split()
        if not ids:
            print("OK (nothing to run)")
            return 0
        suite = loader.loadTestsFromNames(ids)
    else:
        suite = loader.loadTestsFromName("tests.test_local_logic")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    if sys.argv[1:2] and sys.argv[1] != "--ids":
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.writelines(t.id() + "\n" for t, _ in result.skipped)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
