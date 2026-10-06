"""
log_report.py — a day of luna.log in one screen: what to look at first.

    cd ~/luna && python3 tools/log_report.py            # the whole log
    cd ~/luna && python3 tools/log_report.py 2026-10-06 # lines after that day's first start

Reading the log after real use found most of the bugs worth fixing (actions
the model claimed but couldn't do, memory wearing away, audio clock drift,
answers to people talking to each other). This counts the signals and lists
the exchanges, so a day can be reviewed in a minute.
"""

import collections
import re
import sys

PATTERNS = [
    ("answers (model)", r"^\[brain\] OpenAI \("),
    ("quiet: not said to her", r"not said to me — staying quiet"),
    ("English side talk ignored", r"English side talk — ignored"),
    ("local commands", r"^\[cmd\]|\[brain\] command "),
    ("model commands", r"\[brain\] command '"),
    ("fast commands (no cloud)", r"sure of \".*\" — no cloud"),
    ("cut-off sentences held", r"cut off mid-sentence"),
    ("cloud heard nothing", r"cloud heard no speech|cloud heard nothing"),
    ("self-echo ignored", r"Ignoring self-echo"),
    ("stranger greetings", r"greeting: .*(imię|nie znam|Nie kojarzę)"),
    ("welcome backs", r"\[idle\] welcome back"),
    ("wave-backs", r"\[behavior\] waving back"),
    ("near-miss faces", r"not sure who this is"),
    ("memory saved", r"\[memory\] saved"),
    ("memory: old facts kept back", r"kept \d+ old fact"),
    ("memory tidies", r"\[memory\] saved .*tidied"),
    ("TTS errors", r"\[TTS\] streaming error"),
    ("audio underruns (speech)", r"underrun during speech"),
    ("errors / tracebacks", r"Traceback|Error:|\bERROR\b"),
    ("restarts", r"^\[Luna\] Running on"),
]


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else None
    lines = open("luna.log", encoding="utf-8", errors="replace").read().splitlines()
    if since:
        # keep from the first start on that date onward (the log has no dates,
        # but backups and restarts do: find "started HH:MM" after a date marker)
        idx = next((i for i, l in enumerate(lines) if since in l), 0)
        lines = lines[idx:]
    counts = collections.Counter()
    for l in lines:
        for name, rx in PATTERNS:
            if re.search(rx, l):
                counts[name] += 1
    print("── signals ──")
    for name, _ in PATTERNS:
        print(f"  {counts[name]:5d}  {name}")
    xr = [l for l in lines if "PipeWire xruns" in l]
    if xr:
        last = xr[-1]
        m = re.search(r"PipeWire xruns (\d+)", last)
        n = re.search(r"clock nudges (\d+)", last)
        print(f"  xruns (since the last start): {m.group(1) if m else '?'}, "
              f"clock nudges: {n.group(1) if n else '?'}")
    print("\n── exchanges (what was asked → what she said) ──")
    asked = None
    for l in lines:
        m = re.match(r"^\[brain\] Processing: (.*)", l)
        if m:
            asked = m.group(1)
            continue
        m = re.match(r"^\[brain\] OpenAI \([^)]*\): (.*)", l)
        if m and asked:
            print(f"  « {asked[:70]}\n    → {m.group(1)[:110]}")
            asked = None
        elif "staying quiet" in l and asked:
            print(f"  « {asked[:70]}\n    → (quiet: not for her)")
            asked = None


if __name__ == "__main__":
    main()
