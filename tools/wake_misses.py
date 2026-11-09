"""
wake_misses.py — how often does "Luna" have to be said twice?
A call she answered, with one or more unanswered sentences in the 20 s
before it, was most likely a repeat: the earlier ones are the misses. Shows
what became of each (never sent to the cloud, the cloud heard nothing, the
cloud heard other words, rejected) and what the wake checks cost. On the Pi:
    python3 tools/wake_misses.py luna.log.1 luna.log         # the counts
    python3 tools/wake_misses.py luna.log -v                 # + each one (words!)
Approximate: a sentence said to someone else just before a call counts as
a miss too — read the -v list before trusting a number.
"""
import re
import sys

HEARD = re.compile(r'^\[STT\] heard="(.*?)" conf=([\d.]+) peak_rms=(\d+) gate=(\d+)')
STAMP = re.compile(r"^\[Luna heard\] (\d+):(\d+):(\d+) (.*)")
CLOUD = re.compile(r'^\[STT\] cloud \([\d.]+s\): "(.*)"')
WAKE = re.compile(r"^\[wake\] (\w+) (\w+) src=([\w-]+).* mode=(\w+) radio=(\d)")
PAUSED = ("[STT] English call/video in the room", "[STT] people talking, not to her")
REPEAT_SECS = 20
KINDS = ("not sent", "cloud: nothing", "cloud: other words", "cloud: her name, refused",
         "noise", "rejected")


def _utt(vosk, conf=None, loud=0.0, window=False):
    return {"vosk": vosk, "conf": conf, "loud": loud, "t": None, "cloud": None,
            "wake": None, "window": window, "noise": False, "radio": False,
            "unbelieved": False}


def utterances(lines):
    """One dict per sentence Vosk heard, with what followed it in the log.
    (A sentence with her name in Vosk's words has no "heard=" line, only
    its "[Luna heard]".)"""
    out, cur, window = [], None, False
    for ln in lines:
        m = HEARD.match(ln)
        if m:
            cur = _utt(m.group(1), float(m.group(2)),
                       int(m.group(3)) / max(1, int(m.group(4))), window)
            out.append(cur)
            continue
        m = STAMP.match(ln)
        if m:
            if cur is None or cur["t"] is not None or cur["vosk"] != m.group(4):
                cur = _utt(m.group(4), window=window)
                out.append(cur)
            cur["t"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            continue
        if ln.startswith("[STT] Wake word"):
            window = True
        elif "Conversation timed out" in ln or "window closed" in ln:
            window = False
        if cur is None:
            continue
        m = CLOUD.match(ln)
        if m and cur["cloud"] is None:
            cur["cloud"] = m.group(1)
            continue
        m = WAKE.match(ln)
        if m and cur["wake"] is None:
            cur["wake"] = m.groups()[:3]
            cur["window"] = m.group(4) == "window"
            cur["radio"] = m.group(5) == "1"
        elif ln.startswith("[STT] Dropped (noise)"):
            cur["noise"] = True
        elif ln.startswith("[STT] cloud wake not believed"):
            cur["unbelieved"] = True
    return out


def kind(u, name_rx):
    if u["wake"] and u["wake"][0] == "REJECT":
        return "rejected"
    if u["unbelieved"] or (u["cloud"] and name_rx.search(u["cloud"])):
        return "cloud: her name, refused"
    if u["noise"]:
        return "noise"
    if u["cloud"] is None:
        return "not sent"
    return "cloud: other words" if u["cloud"] else "cloud: nothing"


def misses(utts, name_rx):
    """(missed utterance, the answered call after it) pairs."""
    for i, u in enumerate(utts):
        if not (u["wake"] and u["wake"][0] == "ACCEPT") or u["window"] or u["t"] is None:
            continue
        for p in reversed(utts[max(0, i - 4):i]):
            if p["t"] is None or p["window"] or (p["wake"] and p["wake"][0] == "ACCEPT"):
                break
            if not 0 <= (u["t"] - p["t"]) % 86400 <= REPEAT_SECS:
                break
            yield p, u


def name_regex():
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import WAKE_WORDS
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in
                                             sorted(WAKE_WORDS, key=len, reverse=True))
                      + r")(?!\w)", re.I)


def report(lines, verbose=False, name_rx=None):
    name_rx = name_rx or name_regex()
    utts = utterances(lines)
    calls = [u for u in utts if u["wake"] and u["wake"][0] == "ACCEPT" and not u["window"]]
    found = list(misses(utts, name_rx))
    repeated = len({id(u) for _, u in found})
    out = [f"{len(calls)} calls answered from idle, {repeated} of them after "
           f"{len(found)} unanswered sentence(s) just before"
           + (f" ({100 * repeated // len(calls)} % said twice)" if calls else "")]
    by_src = {}
    for u in calls:
        by_src[u["wake"][2]] = by_src.get(u["wake"][2], 0) + 1
    out.append("answered by: " + ", ".join(f"{k} {v}" for k, v in
                                           sorted(by_src.items(), key=lambda kv: -kv[1])))
    for k in KINDS:
        rows = [(p, u) for p, u in found if kind(p, name_rx) == k]
        if not rows:
            continue
        radio = sum(1 for _, u in rows if u["radio"])
        out.append(f"  {k}: {len(rows)}" + (f" ({radio} with the radio on)" if radio else ""))
        if verbose:
            for p, u in rows:
                out.append(f"      \"{p['vosk']}\" conf {p['conf'] or 0:.2f} ×{p['loud']:.1f}"
                           + (f" cloud \"{p['cloud']}\"" if p["cloud"] else "")
                           + f"  →  \"{u['cloud'] or u['vosk']}\" ({u['wake'][2]})")
    idle = [u for u in utts if not u["window"]]
    sent = [u for u in idle if u["cloud"] is not None and
            not (u["wake"] and u["wake"][2] in ("vosk", "vosk-name", "vosk-fuzzy"))]
    hit = sum(1 for u in sent if u["wake"] and u["wake"][0] == "ACCEPT")
    out.append(f"wake checks: {len(sent)} of {len(idle)} idle sentences went to the cloud, "
               f"{hit} found her name"
               + (f" ({100 * hit // len(sent)} %)" if sent else "")
               + f"; {sum(1 for u in sent if not u['cloud'])} came back empty; paused "
               f"{sum(1 for ln in lines if ln.startswith(PAUSED))} times")
    return out


def main(argv):
    paths = [a for a in argv if not a.startswith("-")] or ["luna.log"]
    lines = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines += [ln.rstrip("\n") for ln in f]
    print("\n".join(report(lines, "-v" in argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
