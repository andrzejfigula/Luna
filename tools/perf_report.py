"""
perf_report.py — how fast she is, day by day, from her log (read-only). For a
before/after, compare the days around a change. Baselines: docs/performance.md.

    ssh raspberry@raspberrypi.local 'cd ~/luna && python3 tools/perf_report.py'
    … python3 tools/perf_report.py --old       # luna.log.1 too (back ~a week)
    … python3 tools/perf_report.py some.log    # another log

A day is the date of the restart its lines follow.
"""
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTART = re.compile(r"^===== restart (\d{4}-\d{2}-\d{2}) ")
LATENCY = re.compile(r"^\[latency\] end of speech → her voice ([0-9.]+)s(?: \((.*)\))?")
HEALTH = re.compile(r"^\[health\] \d+:\d+ CPU (\d+)°C, load (\d+)%, RAM (\d+)%.*?(\d+) failures, audio: "
                    r"(\d+) underruns, (\d+) rebuffers.*?max stall (\d+) ms.*?PipeWire xruns (\d+)"
                    r".*?throttled (0x[0-9a-fA-F]+)")
FACES = re.compile(r"^\[gl\] \d+ faces warmed up in ([0-9.]+) s")
CLOUD = re.compile(r"^\[health\] cloud clients warmed up in ([0-9.]+)s")
STAGES = ("text", "model", "reply", "sentence", "tts", "audio")
# vcgencmd get_throttled: the low bits are now, the same bits << 16 since boot
THROTTLE_BITS = ((0, "under-voltage"), (1, "frequency capped"), (2, "throttled"), (3, "soft temperature limit"))


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct / 100) - 1))]


def new_day():
    return {"latency": [], "stages": {}, "temp": [], "load": [], "stall": [], "failures": 0,
            "underruns": 0, "rebuffers": 0, "xruns": 0, "throttled": None, "faces": [], "cloud": []}


def by_day(lines):
    days, day = {}, None
    for line in lines:
        m = RESTART.match(line)
        if m:
            day = days.setdefault(m.group(1), new_day())
            continue
        if day is None:
            continue
        m = LATENCY.match(line)
        if m:
            day["latency"].append(float(m.group(1)))
            for part in (m.group(2) or "").split(", "):
                if " " in part:
                    name, value = part.split(" ", 1)
                    day["stages"].setdefault(name, []).append(float(value))
            continue
        m = HEALTH.match(line)
        if m:
            temp, load, _, fails, under, rebuf, stall, xruns, throttled = m.groups()
            day["temp"].append(int(temp))
            day["load"].append(int(load))
            day["stall"].append(int(stall))
            day["failures"] += int(fails)
            day["underruns"] += int(under)
            day["rebuffers"] += int(rebuf)
            day["xruns"] = max(day["xruns"], int(xruns))
            day["throttled"] = int(throttled, 16)
            continue
        m = FACES.match(line)
        if m:
            day["faces"].append(float(m.group(1)))
            continue
        m = CLOUD.match(line)
        if m:
            day["cloud"].append(float(m.group(1)))
    return days


def throttle_text(value):
    if value is None:
        return "no health line yet"
    now =[name + " now" for bit, name in THROTTLE_BITS if value >> bit & 1]
    since = [name + " since boot" for bit, name in THROTTLE_BITS if value >> (bit + 16) & 1]
    return ", ".join(now + since) or "never"


def num(values, pct, fmt="{:.2f}"):
    return fmt.format(percentile(values, pct)) if values else "-"


def report(days):
    print("day         answers  p50    p90   temp°C     load%     stall ms  fail under rebuf xruns")
    for name, d in sorted(days.items())[-14:]:
        print(f"{name}  {len(d['latency']):5d}  {num(d['latency'], 50):>5s}  {num(d['latency'], 90):>5s}  "
              f"{num(d['temp'], 50, '{:.0f}'):>3s}/{max(d['temp'], default='-'):<4}  "
              f"{num(d['load'], 50, '{:.0f}'):>3s}/{max(d['load'], default='-'):<4}  "
              f"{max(d['stall'], default='-'):>7}  {d['failures']:4d} {d['underruns']:5d} "
              f"{d['rebuffers']:5d} {d['xruns']:5d}")
    if not days:
        print("(no restart line in this log)")
        return
    # a restart just after midnight opens a day with nothing measured yet
    newest = lambda key: max((n for n in days if days[n][key] not in ([], {}, None)), default=max(days))
    stages, warm, hot = days[newest("stages")], days[newest("faces")], days[newest("throttled")]
    print(f"stages, median from the end of speech, {newest('stages')}: " +
          (", ".join(f"{k} {percentile(stages['stages'][k], 50):.2f}" for k in STAGES if k in stages["stages"]) or "-"))
    print(f"warm-up, median, {newest('faces')}: faces {num(warm['faces'], 50, '{:.1f}')} s, "
          f"cloud {num(warm['cloud'], 50, '{:.1f}')} s")
    print(f"throttling, {newest('throttled')}: {throttle_text(hot['throttled'])}")


def main(argv):
    old ="--old" in argv
    named = [a for a in argv if not a.startswith("--")]
    paths = named or [os.path.join(ROOT, "luna.log.1")] * old + [os.path.join(ROOT, "luna.log")]
    lines = []
    for path in paths:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines += f.read().split("\n")
    report(by_day(lines))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
