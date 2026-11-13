"""
rules.py — which of commands.handle's rules are used, and which never.

    ssh raspberry@raspberrypi.local 'cd ~/luna && python3 tools/rules.py'   # her counts
    python -X utf8 tools/rules.py [--top 30] [--unused] [path/to/rules.json]

handle() has a few hundred rules tried in order; data/rules.json (cmdlog.py)
counts the sentences each one took. A rule that took nothing in weeks of real
use is a candidate to remove or to check that an earlier rule doesn't shadow it.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def report(rules, counts, top=20, unused=False):
    """Lines of text: the most used rules, then how many never fired."""
    names = [name for _, _, name in rules]
    line_of = {name: first for first, _, name in rules}
    used = sorted(((n, c) for n, c in counts.items() if c), key=lambda x: -x[1])
    total = sum(c for _, c in used) or 1
    out = [f"{sum(counts.values())} sentences taken by {len(used)} of {len(names)} rules"]
    for name, c in used[:top]:
        where = f"commands.py:{line_of[name]}" if name in line_of else "(rule gone or renamed)"
        out.append(f"  {c:6d}  {100 * c / total:4.1f}%  {name}  {where}")
    never = [n for n in dict.fromkeys(names) if not counts.get(n)]
    out.append(f"never used: {len(never)}" + ("" if unused else "  (--unused lists them)"))
    if unused:
        out += [f"  commands.py:{line_of[n]:<6d} {n}" for n in never]
    return out


def main(argv):
    import cmdlog
    args = [a for a in argv if not a.startswith("--")]
    top = 20
    if "--top" in argv:
        top = int(argv[argv.index("--top") + 1])
        args = [a for a in args if a != str(top)]
    path = args[0] if args else os.path.join(ROOT, "data", "rules.json")
    try:
        counts = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"rules: no counts at {path} ({e}) — none yet here (they are on the Pi, written every few minutes)")
        return 1
    rules = cmdlog.rules_of(open(os.path.join(ROOT, "commands.py"), encoding="utf-8").read())
    print("\n".join(report(rules, counts, top, "--unused" in argv)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
