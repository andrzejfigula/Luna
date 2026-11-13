#!/bin/bash
# lock.sh — the exact versions Luna runs on, written to requirements.lock (on the PC).
#
#   bash tools/lock.sh           # rewrite requirements.lock from the Pi
#   bash tools/lock.sh --check   # only say what differs from the file
#
# requirements.txt says "openai>=3.0": a new SD card a year from now would get
# whatever is newest that day. The lock is what worked; SETUP.md installs from it.
# Run it after `pip install` on the Pi or tools/sysupgrade.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
PI=${LUNA_PI:-raspberry@raspberrypi.local}
new=$(ssh -o ConnectTimeout=8 "$PI" 'cd ~/luna || exit 1
    . /etc/os-release
    echo "# requirements.lock — what the Pi runs (tools/lock.sh writes this; do not edit)."
    echo "# $PRETTY_NAME, kernel $(uname -r), $(python3 -V)"
    echo "# apt (the venv sees them: --system-site-packages):"
    dpkg-query -W -f "#   \${Package}=\${Version}\n" python3-pygame python3-numpy python3-opencv \
        libportaudio2 pipewire wireplumber ffmpeg labwc 2>/dev/null
    echo "# pip, in the venv:"
    ./venv/bin/pip freeze --local 2>/dev/null') || { echo "lock: the Pi did not answer"; exit 1; }
echo "$new" | grep -q '^openai==' || { echo "lock: no package list came back — nothing written"; exit 1; }
if [ "${1:-}" = "--check" ]; then
    if diff <(tr -d '\r' < requirements.lock 2>/dev/null) <(echo "$new") > /dev/null; then
        echo "lock: requirements.lock matches the Pi"
    else
        echo "lock: the Pi differs from requirements.lock (bash tools/lock.sh to update):"
        diff <(tr -d '\r' < requirements.lock 2>/dev/null) <(echo "$new") | grep '^[<>]' | head -20
        exit 1
    fi
else
    printf '%s\n' "$new" > requirements.lock
    echo "lock: requirements.lock written ($(grep -c '==' requirements.lock) pip packages)"
fi
