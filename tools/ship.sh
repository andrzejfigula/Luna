#!/usr/bin/env bash
# ship.sh — test, deploy and restart Luna in one go; every step has a time
# limit, and it ends with her new pid or what went wrong.
#
#     tools/ship.sh            # check_pi.sh (all gates) → deploy.sh → restart --now --tested
#     tools/ship.sh --no-check # deploy and restart (restart.sh then runs its own tests)
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

if [ "${1:-}" != "--no-check" ]; then
    step "testing on the Pi"
    timeout 900 bash tools/check_pi.sh
fi
step "copying"
timeout 300 bash tools/deploy.sh
step "restarting"
timeout 420 "${SSH[@]}" 'cd ~/luna && ./restart.sh --now --tested'
step "done"
