"""
mouth_stats.py — does mouth.py's "mouth talking N%" tell speech TO her from
the rest? Reads luna.log's "[STT] heard=… mouth talking N%, best ×B (face F%)"
lines (face in view ≥ 80%) and splits them by what followed: said with her
name (certainly to her), answered, ignored / other. On the Pi:
    python3 tools/mouth_stats.py luna.log            # the table
    python3 tools/mouth_stats.py luna.log -v         # + the low readings
    python3 tools/mouth_stats.py luna.log --days     # low share per day
29 Oct: ~50% of every group read ≤2% — no signal (docs/side-talk.md).
"""
import collections
import re
import sys

RX = re.compile(r'^\[STT\] heard="([^"]*)".*mouth talking (\d+)%, best .([\d.]+) \(face (\d+)%\)')
CLOUD = re.compile(r'cloud \([\d.]+s\): "(.*)"')
LOW = 2                 # % of frames "talking": a still face


def rows(lines):
    day = "?"
    for i, ln in enumerate(lines):
        if ln.startswith("===== restart"):
            day = ln.split()[2]
        m = RX.match(ln)
        if not m or int(m.group(4)) < 80:
            continue
        nxt = lines[i + 1:i + 8]
        cloud = next((CLOUD.search(x).group(1) for x in nxt if CLOUD.search(x)), None)
        if any("Wake word" in x for x in nxt) or (cloud and re.match(r"(?i)\W*(luna|luno)\b", cloud)):
            kind = "name"
        elif any("Processing:" in x for x in nxt):
            kind = "answered"
        else:
            kind = "other"
        yield day, kind, int(m.group(2)), float(m.group(3)), cloud or m.group(1)


def main():
    lines = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
    got = list(rows(lines))
    if "--days" in sys.argv:
        per = collections.defaultdict(lambda: [0, 0])
        for day, _, talk, _, _ in got:
            per[day][0] += 1
            per[day][1] += talk <= LOW
        for day, (n, low) in sorted(per.items()):
            print(f"{day}  {n:4}  low {low / n:.0%}")
        return
    by = collections.defaultdict(list)
    for _, kind, talk, best, said in got:
        by[kind].append((talk, best, said))
    for kind in ("name", "answered", "other"):
        r = by[kind]
        low = sum(1 for t, _, _ in r if t <= LOW)
        print(f"{kind:9} n={len(r):5}  talking <={LOW}%: {low:5} ({low / max(len(r), 1):.0%})")
    if "-v" in sys.argv:
        for kind in ("name", "answered"):
            print(f"--- {kind}, talking <={LOW}%:")
            for t, b, said in [x for x in by[kind] if x[0] <= LOW][-30:]:
                print(f"  {t:3}% x{b:.1f}  {said[:90]}")


if __name__ == "__main__":
    main()
