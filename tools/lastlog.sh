#!/usr/bin/env bash
# lastlog.sh — the lines of ~/luna/luna.log worth reading, from the Pi, in one
# screen: what she heard (Vosk and cloud), wake and window decisions, what she
# said, commands, radio, latency, errors. Long lines are cut at 220 chars.
#
#     tools/lastlog.sh              # last 80 such lines since the last restart
#     tools/lastlog.sh 200          # more
#     tools/lastlog.sh 80 all       # across restarts too
#     tools/lastlog.sh 80 all 'mouth|vision'   # plus your own pattern
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
N="${1:-80}"
SCOPE="${2:-since}"
EXTRA="${3:-}"
PAT='^\[STT\] (heard|cloud|Wake|Dropped|Conversation|speculative|false wake)|^\[Luna heard\]|^\[Luna\]|^\[cmd\]|^\[radio\] (playing|stopped)|^\[latency\]|^\[brain\] (command|claimed)|^=====|Traceback|Error|error'
[ -n "$EXTRA" ] && PAT="$PAT|$EXTRA"
ssh -o HostKeyAlias=raspberrypi.local -o ConnectTimeout=10 "$PI" \
    "cd ~/luna && if [ '$SCOPE' = all ]; then cat luna.log; else
       s=\$(grep -an '^===== restart' luna.log | tail -1 | cut -d: -f1); tail -n +\${s:-1} luna.log; fi" \
    | grep -aE "$PAT" | cut -c1-220 | tail -n "$N"
