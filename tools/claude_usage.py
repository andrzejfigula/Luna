"""
claude_usage.py — what Claude Code sessions on this repo cost, from their
transcripts on the PC (~/.claude/projects/D--Code-luna/*.jsonl).

    python -X utf8 tools/claude_usage.py        # the last 15 sessions
    python -X utf8 tools/claude_usage.py 40
    python -X utf8 tools/claude_usage.py --tools   # which tool results filled the context

Every call re-reads the whole conversation, so the cost is calls x context:
`first` is the fixed part (system prompt, tool schemas, CLAUDE.md), `avg` and
`max` show how long the session ran before compacting (.claude/settings.json).
"""
import collections
import glob
import json
import os
import re
import sys

_BASH_KIND = re.compile(r"(tools/[\w.]+|tests/[\w.]+|git \w+|\bgrep\b|\bsed\b|\bcat\b|\bhead\b|\bssh\b|\bscp\b|\bls\b)")


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


def tool_kind(name, tool_input):
    """A tool call's group: 'Bash sed', 'Read gl_face.py', 'Grep'."""
    if name == "Bash":
        m = _BASH_KIND.search(tool_input.get("command", ""))
        return "Bash " + (m.group(1) if m else "other")
    if name == "Read":
        return "Read " + os.path.basename(tool_input.get("file_path", ""))
    return name


def tool_results(lines):
    """(kind, characters) of every tool result in a transcript's lines."""
    uses = {}
    for line in lines:
        try:
            content = (json.loads(line).get("message") or {}).get("content")
        except (ValueError, AttributeError):
            continue
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses[block.get("id")] = tool_kind(block.get("name"), block.get("input") or {})
            elif block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                yield uses.get(block.get("tool_use_id"), "?"), len(body or "")


def report_tools(paths, top=20):
    chars, calls = collections.Counter(), collections.Counter()
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for kind, n in tool_results(f):
                chars[kind] += n
                calls[kind] += 1
    print(f"tool results: {sum(chars.values()) // 3000}k tokens (about 3 characters each)")
    for kind, n in chars.most_common(top):
        print(f"{n // 3000:6d}k {calls[kind]:5d}x  avg {n // calls[kind] // 3:6d}  {kind}")


def main():
    args = [a for a in sys.argv[1:] if a != "--tools"]
    n = int(args[0]) if args else 15
    if "--tools" in sys.argv:
        report_tools(sessions(n))
        return
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
