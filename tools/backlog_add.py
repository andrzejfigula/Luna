"""
backlog_add.py — add a numbered row to BACKLOG.md without opening it.

    python tools/backlog_add.py "**Title** — what changed" "why (who, when)" [status]

The number is one more than the highest in BACKLOG.md and
docs/backlog-done.md. Status defaults to ✅. Prints the row it added.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [os.path.join(ROOT, "BACKLOG.md"), os.path.join(ROOT, "docs", "backlog-done.md")]


def next_number():
    top = 0
    for path in FILES:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for m in re.finditer(r"^\| *(\d+) *\|", f.read(), re.M):
                    top = max(top, int(m.group(1)))
    return top + 1


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip())
        return 1
    item, why = argv[1], argv[2]
    status = argv[3] if len(argv) > 3 else "✅"
    clean = lambda s: s.replace("|", "/").replace("\n", " ").strip()
    row = f"| {next_number()} | {clean(item)} | {clean(why)} | {clean(status)} |"
    with open(FILES[0], "a", encoding="utf-8", newline="\n") as f:
        f.write(row + "\n")
    print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
