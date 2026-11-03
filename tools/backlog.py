"""
backlog.py — the backlog without reading it. BACKLOG.md holds only what is open
or parked; finished rows live in docs/backlog-done.md (numbers run across both).

    python -X utf8 tools/backlog.py find radio piosenk   # built already? rows, cheat sheet, code
    python -X utf8 tools/backlog.py show 57 738          # those rows in full
    python -X utf8 tools/backlog.py recent [10]          # the latest titles
    python -X utf8 tools/backlog.py open                 # what is open or parked
    python -X utf8 tools/backlog.py add "**Title** — what changed" "why" [status]
                                                         # ✅ (default) → done; ⏳ 🚧 💤 → open
    python -X utf8 tools/backlog.py done 870 ["note"]    # an open row is finished
    python -X utf8 tools/backlog.py check                # numbers unique, nothing finished left open

find matches any of its words anywhere (Polish and English; a stem catches the
inflections: "piosenk"), ignoring case and Polish letters; rows matching the
most words come first.
"""
import glob
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPEN_FILE, DONE_FILE = "BACKLOG.md", os.path.join("docs", "backlog-done.md")
CHEAT_SHEET = "CO_NOWEGO.md"
OPEN_MARKS = "⏳🚧💤"
ROW = re.compile(r"^\| *(\d+) *\|(.*?)\|?\s*$")   # (#266 has no closing bar)
MAX_ROWS = 12
WIDTH = 110


def fold(text):
    """Lower case, no diacritics: 'Piosenkę' and 'piosenke' are one word."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().split("\n")


def write_lines(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


def rows(root):
    """(number, row text, file) of every row, oldest file first."""
    out = []
    for name in (DONE_FILE, OPEN_FILE):
        for line in read_lines(os.path.join(root, name)):
            m = ROW.match(line)
            if m:
                out.append((int(m.group(1)), line, name))
    return out


def title_of(row):
    body = ROW.match(row).group(2)
    m = re.search(r"\*\*(.+?)\*\*", body)
    return (m.group(1) if m else body.split("|")[0].strip())[:WIDTH]


def status_of(row):
    """The status cell's mark; a few old rows carry it in the item instead."""
    cells = ROW.match(row).group(2).split("|")
    for cell in (cells[-1], cells[0]):
        m = re.search("[✅" + OPEN_MARKS + "]", cell)
        if m:
            return m.group(0)
    return "?"


def next_number(root):
    return max((n for n, _, _ in rows(root)), default=0) + 1


def clean(text):
    return text.replace("|", "/").replace("\n", " ").strip()


def append_row(path, row):
    lines = read_lines(path)
    while lines and not lines[-1].strip():
        lines.pop()
    write_lines(path, lines + [row, ""])


def cmd_add(root, args):
    if len(args) < 2:
        print(__doc__.strip())
        return 2
    status = clean(args[2]) if len(args) > 2 else "✅"
    row = f"| {next_number(root)} | {clean(args[0])} | {clean(args[1])} | {status} |"
    append_row(os.path.join(root, OPEN_FILE if status[0] in OPEN_MARKS else DONE_FILE), row)
    print(row)
    return 0


def cmd_done(root, args):
    if not args or not args[0].isdigit():
        print(__doc__.strip())
        return 2
    path = os.path.join(root, OPEN_FILE)
    lines = read_lines(path)
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and int(m.group(1)) == int(args[0]):
            cells = m.group(2).rsplit("|", 1)
            note = f" {clean(args[1])}" if len(args) > 1 else ""
            row = f"| {m.group(1)} |{cells[0]}| ✅{note} |"
            append_row(os.path.join(root, DONE_FILE), row)
            write_lines(path, lines[:i] + lines[i + 1:])
            print(row)
            return 0
    print(f"#{args[0]} is not an open row in {OPEN_FILE}")
    return 1


def cmd_show(root, args):
    wanted = {int(a) for a in args if a.isdigit()}
    found = [r for n, r, _ in rows(root) if n in wanted]
    print("\n".join(found) if found else "no such row")
    return 0 if found else 1


def cmd_recent(root, args):
    n = int(args[0]) if args and args[0].isdigit() else 10
    for num, row, _ in sorted(rows(root))[-n:]:
        print(f"#{num} {status_of(row)} {title_of(row)}")
    return 0


def cmd_open(root, _args):
    print("\n".join(read_lines(os.path.join(root, OPEN_FILE))).strip())
    return 0


def cmd_find(root, args):
    words = [fold(a) for a in args if a.strip()]
    if not words:
        print(__doc__.strip())
        return 2
    scored = []
    for num, row, _ in rows(root):
        text = fold(row)
        hits = sum(w in text for w in words)
        if hits:
            in_title = sum(w in fold(title_of(row)) for w in words)
            scored.append((-hits, -in_title, -num, row))
    scored.sort(key=lambda s: s[:3])
    print(f"backlog: {len(scored)} rows" + (f", the best {MAX_ROWS}:" if len(scored) > MAX_ROWS else ":"))
    for _, _, num, row in scored[:MAX_ROWS]:
        print(f"  #{-num} {status_of(row)} {title_of(row)}")

    sheet = [(i, line.strip()) for i, line in enumerate(read_lines(os.path.join(root, CHEAT_SHEET)), 1)
             if any(w in fold(line) for w in words)]
    print(f"{CHEAT_SHEET}: {len(sheet)} lines" + (":" if sheet else ""))
    for i, line in sheet[:6]:
        print(f"  {i}: {line[:WIDTH]}")

    code = []
    for path in glob.glob(os.path.join(root, "*.py")):
        with open(path, encoding="utf-8") as f:
            n = sum(1 for line in f if any(w in fold(line) for w in words))
        if n:
            code.append((-n, os.path.basename(path)))
    print("code: " + (", ".join(f"{name} {-n}" for n, name in sorted(code)[:8]) or "nothing"))
    return 0


def cmd_check(root, _args):
    seen, problems = {}, []
    for num, _, name in rows(root):
        if num in seen:
            problems.append(f"#{num} twice ({seen[num]}, {name})")
        seen[num] = name
    for num, row, name in rows(root):
        if name == OPEN_FILE and status_of(row) == "✅":
            problems.append(f"#{num} is finished but still in {OPEN_FILE}")
    print("\n".join(problems) if problems else f"backlog OK: {len(seen)} rows, the next is #{next_number(root)}")
    return 1 if problems else 0


COMMANDS = {"add": cmd_add, "done": cmd_done, "show": cmd_show, "recent": cmd_recent,
            "open": cmd_open, "find": cmd_find, "check": cmd_check}


def main(argv, root=ROOT):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.strip())
        return 2
    return COMMANDS[argv[0]](root, argv[1:])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # the Windows console is cp1252 ("✅")
    sys.exit(main(sys.argv[1:]))
