"""
claude_usage.py — what Claude Code sessions on this repo cost, from their
transcripts on the PC (~/.claude/projects/D--Code-luna/*.jsonl).

    python -X utf8 tools/claude_usage.py        # the last 15 sessions
    python -X utf8 tools/claude_usage.py 40

Every call re-reads the whole conversation, so the cost is calls x context:
`first` is the fixed part (system prompt, tool schemas, CLAUDE.md), `avg` and
`max` show how long the session ran before compacting (.claude/settings.json).
"""
import glob
import json
import os
import sys


def sessions(n):
    d = os.path.expanduser("~/.claude/projects/D--Code-luna")
    return sorted(glob.glob(os.path.join(d, "*.jsonl")), key=os.path.getmtime)[-n:]


def contexts(path):
    """Context size of each API call (one call is split over several lines)."""
    seen, ctxs, out = set(), [], 0
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        if d.get("type") != "assistant" or m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        u = m.get("usage") or {}
        ctxs.append(sum(u.get(k) or 0 for k in
                        ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")))
        out += u.get("output_tokens") or 0
    return ctxs, out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print("calls   first     avg     max   total  output  session")
    grand = 0
    for f in sessions(n):
        ctxs, out = contexts(f)
        if not ctxs:
            continue
        grand += sum(ctxs)
        print(f"{len(ctxs):5d} {ctxs[0]/1e3:6.0f}k {sum(ctxs)/len(ctxs)/1e3:6.0f}k "
              f"{max(ctxs)/1e3:6.0f}k {sum(ctxs)/1e6:6.1f}M {out/1e3:5.0f}k  {os.path.basename(f)[:8]}")
    print(f"total context read: {grand/1e6:.0f}M tokens")


if __name__ == "__main__":
    main()
