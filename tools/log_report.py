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
    ("utterances heard", r"^\[Luna heard\]"),
    ("wake words", r"Wake word"),
    ("answers (model)", r"^\[brain\] OpenAI \("),
    ("quiet: not said to her", r"not said to me — staying quiet"),
    ("English side talk ignored", r"English side talk — ignored"),
    ("model commands", r"\[brain\] command '"),
    ("fast commands (no cloud)", r"sure of \".*\" — no cloud"),
    ("cut-off sentences held", r"cut off mid-sentence"),
    ("false wakes dropped", r"\[STT\] false wake"),
    ("voice stop: would have stopped her", r"\[barge\] \(log only\)"),
    ("voice stop: stopped her", r"interrupted by voice"),
    ("reading aloud sessions", r"\[reading\] listening"),
    ("reminder promised → asked when", r"promised a reminder without one"),
    ("actions held back (offer)", r"action\(s\) held back"),
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
    # 7–8 Oct additions
    ("cloud wake not believed (made up)", r"cloud wake not believed"),
    ("English call: cloud checks paused", r"English call/video in the room"),
    ("game chosen after her offer", r"game chosen after her offer"),
    ("game NOT started (no offer / choosing)", r"not started"),
    ("answered: short command / yes-no", r"a short command, not side talk"),
    ("answered: her name was just said", r"her name was just said"),
    ("answered: a request, nobody else here", r"a request with nobody else here"),
    ("cancel matched nothing → corrected", r"cancel matched nothing"),
    ("command failed (answer kept)", r"\[brain\] command .* failed"),
    ("Vosk's right answer taken (game)", r"is the game's right answer"),
    ("leaving / goodbye", r"goodbye — conversation closed"),
]


def audio_by_hour(lines):
    """The current run's hourly health lines as a trend: xruns added each hour
    and the clock nudges so far. The clock-drift bug (#240) showed up as
    xruns climbing to ~50 000 an hour after ~8 h; with the fix they stay flat
    while the nudges grow slowly."""
    start = max((i for i, l in enumerate(lines) if l.startswith("[Luna] Running on")),
                default=0)
    rows, prev = [], 0
    for l in lines[start:]:
        m = re.match(r"^\[health\] (\d\d:\d\d) .*?PipeWire xruns (\d+)", l)
        if not m:
            continue
        n = re.search(r"clock nudges (\d+)", l)
        x = int(m.group(2))
        rows.append(f"    {m.group(1)}  +{x - prev:<7d} xruns   "
                    f"{n.group(1) if n else '?':>4} nudges so far")
        prev = x
    if rows:
        started = re.search(r"started (\d\d:\d\d)", lines[start])
        rows.insert(0, "  audio by the hour since "
                    + (started.group(1) if started else "the last start") + ":")
    return rows


def latency_summary(lines):
    """End of their speech → her voice, over the answers in these lines: median
    and 90th percentile, and the median of each stage (timing.py)."""
    totals, stages = [], {}
    for l in lines:
        m = re.match(r"^\[latency\] end of speech → her voice ([0-9.]+)s(?: \((.*)\))?", l)
        if not m:
            continue
        totals.append(float(m.group(1)))
        for part in (m.group(2) or "").split(", "):
            if " " in part:
                k, v = part.split(" ", 1)
                stages.setdefault(k, []).append(float(v))
    if not totals:
        return []
    med = lambda v: sorted(v)[len(v) // 2]
    import math
    p90 = sorted(totals)[min(len(totals) - 1, math.ceil(len(totals) * 0.9) - 1)]
    rows = [f"  answer speed: {len(totals)} answers, median {med(totals):.2f}s, 90% within {p90:.2f}s"]
    order = ("text", "model", "sentence", "tts", "audio")
    rows.append("    stages (median, from the end of speech): " +
                ", ".join(f"{k} {med(stages[k]):.2f}" for k in order if k in stages))
    return rows


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
    for row in audio_by_hour(lines):
        print(row)
    for row in latency_summary(lines):
        print(row)
    # replies that say she did something, with no line showing it was done
    # (the commonest real bug: "Włączam radio" — and nothing played)
    claim = re.compile(r"\b(włączam|wyłączam|nastawiam|ustawiam|przypomnę|dodałam|dopisałam|"
                       r"zapisałam|skreśliłam|usunęłam|puszczam|zaczynam)\b", re.I)
    done = re.compile(r"^\[(timers|lists|radio|ambience|fun|cmd|cooking|tictac|memo|quiz)\]|"
                      r"\[brain\] command '.*': done")
    flagged = []
    for i, l in enumerate(lines):
        m = re.match(r"^\[brain\] OpenAI \([^)]*\): (.*)", l)
        if m and claim.search(m.group(1)):
            near = lines[max(0, i - 8):i + 4]
            if not any(done.search(x) for x in near):
                flagged.append(m.group(1))
    print(f"\n── replies claiming an action with nothing done ({len(flagged)}) ──")
    for r in flagged[-15:]:
        print(f"  ! {r[:120]}")

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
