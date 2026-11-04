"""
ideas.py — proposals to sift (docs/ideas.md), by filter, without reading the file.

    python -X utf8 tools/ideas.py area=games size=S     # filters add up; a,b means either
    python -X utf8 tools/ideas.py value=3 needs=- maja  # plain words search the whole row
    python -X utf8 tools/ideas.py mark=keep             # undecided by default; all = every mark
    python -X utf8 tools/ideas.py stats [area=learn]    # counts per group
    python -X utf8 tools/ideas.py show 12 40            # those rows in full
    python -X utf8 tools/ideas.py drop 12 40 area=hw    # numbers and/or a filter; keep, undo, built too
    python -X utf8 tools/ideas.py page                  # docs/ideas.html: all of them, to tick and filter

Filters: mark area for size value kind needs. Rows stay in the file when dropped,
so an idea that was turned down isn't proposed again.
"""
import json
import os
import re
import sys

from backlog import ROOT, fold, read_lines, write_lines

IDEAS_FILE = os.path.join("docs", "ideas.md")
PAGE_FILE = os.path.join("docs", "ideas.html")   # generated, not tracked
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ideas_page.tmpl")
FIELDS = ("mark", "area", "for", "size", "value", "kind", "needs")
MARKS = {"undo": "·", "keep": "✓", "drop": "✗", "built": "✅"}
ROW = re.compile(r"^\| *(\d+) *\|")
WIDTH = 150


def parse(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    row = dict(zip(("num",) + FIELDS + ("idea", "why"), cells))
    row["num"] = int(row["num"])
    return row


def load(root):
    lines = read_lines(os.path.join(root, IDEAS_FILE))
    return lines, [parse(line) for line in lines if ROW.match(line)]


def field_matches(row, field, wanted):
    if field == "mark":
        wanted = wanted.lower()
        return wanted == "all" or any(row["mark"] == MARKS.get(w, w) for w in wanted.split(","))
    have = fold(row[field]).split(",")     # needs can be "hw,sudo"
    return any(w in have for w in fold(wanted).split(","))


def split_args(args):
    """(numbers, {field: wanted}, words); None for the filters if a field is unknown."""
    numbers, filters, words = [], {}, []
    for arg in args:
        if arg.isdigit():
            numbers.append(int(arg))
        elif "=" in arg:
            field, wanted = arg.split("=", 1)
            if field not in FIELDS:
                print(f"no filter '{field}': use {', '.join(FIELDS)}")
                return numbers, None, words
            filters[field] = wanted
        else:
            words.append(fold(arg))
    return numbers, filters, words


def select(rows, filters, words):
    """Undecided rows only, unless the filter says which mark."""
    filters = {"mark": "undo", **filters}
    return [r for r in rows
            if all(field_matches(r, f, w) for f, w in filters.items())
            and all(w in fold(r["idea"] + " " + r["why"] + " " + r["for"]) for w in words)]


def title(row):
    m = re.search(r"\*\*(.+?)\*\*", row["idea"])
    return (m.group(1) if m else row["idea"])[:WIDTH]


def print_rows(found):
    for r in found:
        print(f"{r['num']:>3} {r['mark']} {r['area']:<7} {r['for']:<5} {r['size']} v{r['value']} "
              f"{r['kind']:<6} {r['needs']:<7} {title(r)}")
    print(f"{len(found)} ideas")


def cmd_list(root, args):
    _, filters, words = split_args(args)
    if filters is None:
        return 2
    _, rows = load(root)
    print_rows(sorted(select(rows, filters, words), key=lambda r: (-int(r["value"]), r["num"])))
    return 0


def cmd_show(root, args):
    numbers, _, _ = split_args(args)
    _, rows = load(root)
    found = [r for r in rows if r["num"] in numbers]
    for r in found:
        print(f"#{r['num']} {r['mark']} {r['area']} / {r['for']} / {r['size']} / value {r['value']} "
              f"/ {r['kind']} / needs {r['needs']}\n  {r['idea']}\n  Why: {r['why']}")
    return 0 if found else 1


def cmd_stats(root, args):
    _, filters, words = split_args(args)
    if filters is None:
        return 2
    _, rows = load(root)
    found = select(rows, filters, words)
    print(f"{len(found)} ideas ({sum(r['mark'] == '✓' for r in rows)} kept, "
          f"{sum(r['mark'] == '✗' for r in rows)} dropped, {sum(r['mark'] == '✅' for r in rows)} built)")
    for field in FIELDS[1:]:
        counts = {}
        for r in found:
            for value in r[field].split(","):
                counts[value] = counts.get(value, 0) + 1
        print(f"{field}: " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    return 0


def cmd_mark(root, command, args):
    numbers, filters, words = split_args(args)
    if filters is None:
        return 2
    if not (numbers or filters or words):
        print(__doc__.strip())
        return 2
    lines, rows = load(root)
    wanted = set(numbers)
    if filters or words:     # a filter leaves decided rows alone, except for undo
        if command == "undo":
            filters.setdefault("mark", "all")
        wanted |= {r["num"] for r in select(rows, filters, words)}
    missing = wanted - {r["num"] for r in rows}
    if missing:
        print("no such idea: " + " ".join(map(str, sorted(missing))))
        return 1
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and int(m.group(1)) in wanted:
            cells = line.split("|")
            cells[2] = f" {MARKS[command]} "
            lines[i] = "|".join(cells)
    write_lines(os.path.join(root, IDEAS_FILE), lines)
    print(f"{MARKS[command]} {len(wanted)} ideas: " + " ".join(map(str, sorted(wanted))))
    return 0


def cmd_page(root):
    _, rows = load(root)
    for r in rows:
        m = re.match(r"\*\*(.+?)\*\*(?: — )?(.*)", r["idea"])
        r["title"], r["what"] = m.groups() if m else (r["idea"], "")
        del r["idea"]
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read()
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    path = os.path.join(root, PAGE_FILE)
    write_lines(path, [page.replace("/*DATA*/[]", data)])
    print(path)
    return 0


def main(argv, root=ROOT):
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if argv and argv[0] in MARKS:
        return cmd_mark(root, argv[0], argv[1:])
    if argv and argv[0] == "page":
        return cmd_page(root)
    if argv and argv[0] == "show":
        return cmd_show(root, argv[1:])
    if argv and argv[0] == "stats":
        return cmd_stats(root, argv[1:])
    return cmd_list(root, argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # the Windows console is cp1252 ("✅")
    sys.exit(main(sys.argv[1:]))
