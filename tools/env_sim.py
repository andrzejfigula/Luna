"""
env_sim.py — show Luna's world outside (environment.py) in a simulated state
on the Pi's screen, labelled "SYMULACJA: …"; "off" back to the real time and
weather. Read by the running Luna every 2 s (/tmp/luna_env_sim, gone on reboot).

    python tools/env_sim.py night heavy-rain
    python tools/env_sim.py sunset fog winter wind=30
    python tools/env_sim.py cycle=120 snow       # a whole day in 120 s
    python tools/env_sim.py off

Words: environment.SIM_TIME, SIM_WEATHER, SIM_SEASON, "HH:MM", wind=, dir=, cycle=.
"""
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import environment  # noqa: E402

PI = os.environ.get("LUNA_PI", "raspberry@raspberrypi.local")


def main():
    words = sys.argv[1:]
    if not words:
        print(__doc__)
        print("time:", " ".join(environment.SIM_TIME))
        print("weather:", " ".join(environment.SIM_WEATHER))
        print("season:", " ".join(environment.SIM_SEASON))
        return 1
    if words == ["off"]:
        cmd = f"rm -f {environment.SIM_FILE}"
    else:
        known = set(environment.SIM_TIME) | set(environment.SIM_WEATHER) | set(environment.SIM_SEASON)
        odd = [w for w in words if w.lower() not in known and "=" not in w and ":" not in w]
        if odd:
            print(f"unknown: {' '.join(odd)}")
            return 1
        cmd = f"printf %s {shlex.quote(' '.join(words))} > {environment.SIM_FILE}"
    return subprocess.call(["ssh", PI, cmd])


if __name__ == "__main__":
    sys.exit(main())
