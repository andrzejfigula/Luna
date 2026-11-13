#!/usr/bin/env bash
# rollback.sh — put back the code the last deploy replaced, and restart her.
# The Pi copy is not a git checkout: deploy.sh overwrote files in place and a
# bad ship could only be undone by shipping again. Now deploy.sh first packs
# the files it is about to replace into ~/luna-rollback/code/<stamp>.tgz
# (the last 5 are kept).
#
#     tools/rollback.sh            # list what can be put back
#     tools/rollback.sh last       # the newest one, then ./restart.sh --now
#     tools/rollback.sh 20261113-2210
#
# Files a deploy ADDED stay where they are (the older code doesn't import
# them). Never touches data/ or .env. The PC's git is unchanged: revert or
# fix there too, or the next ship brings the same code back.
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
which="${1:-}"
if [ -z "$which" ]; then
    ssh -o ConnectTimeout=10 "$PI" 'cd ~/luna-rollback/code 2>/dev/null && for f in $(ls -1t *.tgz); do
        echo "${f%.tgz}  $(tar -tzf "$f" | wc -l) files: $(tar -tzf "$f" | head -4 | tr "\n" " ")…"; done' \
        || echo "rollback: nothing kept yet"
    exit 0
fi
ssh -o ConnectTimeout=10 "$PI" "cd ~/luna-rollback/code && f=\$( [ '$which' = last ] && ls -1t *.tgz | head -1 || echo '$which.tgz' ) \
    && [ -f \"\$f\" ] && tar -xzf \"\$f\" -C ~/luna && echo \"rollback: put back \$(tar -tzf \"\$f\" | wc -l) files from \$f\" \
    && cd ~/luna && ./restart.sh --now"
