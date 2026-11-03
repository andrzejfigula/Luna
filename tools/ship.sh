#!/usr/bin/env bash
# ship.sh — test, deploy and restart Luna in one go; every step has a time
# limit, and it ends with her new pid or what went wrong.
#
#     tools/ship.sh            # check_pi.sh (all gates) → deploy.sh → restart --now --tested
#     tools/ship.sh --quick    # only unit (here) + smoke (Pi) — for tuning, ~30 s;
#                              # run the full one before calling it done
#     tools/ship.sh --no-check # deploy and restart (restart.sh then runs its own tests)
#     tools/ship.sh --restart  # restart even if she already runs this code
#
# Code that already passed isn't tested again, and she isn't restarted when
# nothing she runs changed (only tools/, tests/, docs/): a restart interrupts
# the family. deploy.sh stamps /tmp/luna_deployed_at when it copies her code.
#
# 17–18 Oct the separate steps kept hanging: a restart waiting for a quiet
# minute held the lock and the new one quietly did nothing; restart.sh re-ran
# the tests just run; and the watching loops matched their own command line.
set -euo pipefail
cd "$(dirname "$0")/.."
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
SSH=(ssh -o HostKeyAlias=raspberrypi.local -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=4 "$PI")
t0=$(date +%s)
step() { echo "ship: $1 ($(( $(date +%s) - t0 )) s)"; }

check=all
force_restart=0
for a in "$@"; do
    case "$a" in
        --quick)    check=quick ;;
        --no-check) check= ;;
        --restart)  force_restart=1 ;;
        *) echo "ship.sh: --quick | --no-check | --restart"; exit 2 ;;
    esac
done
case "$check" in
    quick) step "testing (quick: unit + smoke)"; timeout 600 bash tools/check_pi.sh quick ;;
    all)   step "testing";                       timeout 900 bash tools/check_pi.sh ;;
esac
step "copying"
timeout 300 bash tools/deploy.sh
if [ "$force_restart" = 0 ] && "${SSH[@]}" 'pid=$(pgrep -f "^\./venv/bin/python -u main.py" | head -1)
        [ -n "$pid" ] && [ -f /tmp/luna_deployed_at ] &&
        [ "$(stat -c %Y /tmp/luna_deployed_at)" -lt "$(( $(date +%s) - $(ps -o etimes= -p "$pid") ))" ]'; then
    step "done — she already runs this code, no restart"
    exit 0
fi
step "restarting"
timeout 420 "${SSH[@]}" 'cd ~/luna && ./restart.sh --now --tested'
step "done"
