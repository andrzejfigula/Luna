"""
wake_replay.py — what would activation.py have done with the wakes in a log?
Replays every "[STT] Wake word" line of luna.log (from before the firewall,
or after it) through activation.name_role and the radio-face rule, and
counts what would now stay silent. On the Pi:
    python3 tools/wake_replay.py luna.log luna.log.1         # the counts
    python3 tools/wake_replay.py luna.log -v                 # + each one (words!)
Approximate: Vosk's confidence isn't in the old log, so a bare call isn't
judged sure/unsure here — the new "[wake]" lines say that directly.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import activation                         # noqa: E402
from config import WAKE_WORDS             # noqa: E402

CLOUD = re.compile(r'^\[STT\] cloud \([\d.]+s\): "(.*)"')
RX = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in
                                        sorted(WAKE_WORDS, key=len, reverse=True))
                + r")(?!\w)", re.I)


def replay(lines):
    for i, ln in enumerate(lines):
        if not ln.startswith("[STT] Wake word"):
            continue
        back = lines[max(0, i - 6):i]
        cloud = next((CLOUD.match(x).group(1) for x in reversed(back) if CLOUD.match(x)), None)
        radio_face = any("the face in front of her said it" in x for x in back)
        reply = next((x for x in lines[i + 1:i + 14]
                      if x.startswith("[Luna] ") or x.startswith("[brain] Processing")), "")
        if radio_face:
            kind = "radio_face"                    # now: a local command only
        elif cloud and activation.name_role(cloud, RX) == "about":
            kind = "about_her"                     # now: REJECT, silent
        else:
            kind = "kept"
        yield kind, cloud or "", reply


def main(argv):
    verbose = "-v" in argv
    lines = []
    for f in (a for a in argv if not a.startswith("-")):
        lines += open(f, encoding="utf-8", errors="replace").read().splitlines()
    counts = {}
    for kind, cloud, reply in replay(lines):
        counts[kind] = counts.get(kind, 0) + 1
        if verbose and kind != "kept":
            print(f"{kind:10} | {cloud[:70]:70} | {reply[:60]}")
    total = sum(counts.values())
    print(f"wakes: {total}  kept: {counts.get('kept', 0)}  "
          f"about_her (now silent): {counts.get('about_her', 0)}  "
          f"radio_face (now commands only): {counts.get('radio_face', 0)}")
    new = [x for x in lines if x.startswith("[wake] ")]
    if new:
        tally = {}
        for x in new:
            k = " ".join(x.split()[1:3])
            tally[k] = tally.get(k, 0) + 1
        print("firewall lines: " + ", ".join(f"{k} {n}" for k, n in sorted(tally.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
