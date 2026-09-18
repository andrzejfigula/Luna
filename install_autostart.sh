#!/bin/bash
# Make Luna start with the labwc desktop session (Raspberry Pi OS Trixie).
# lwrespawn restarts her automatically if she ever crashes.
set -e
LINE="/usr/bin/lwrespawn $HOME/luna/run.sh > $HOME/luna/luna.log 2>&1 &"
FILE="$HOME/.config/labwc/autostart"
mkdir -p "$(dirname "$FILE")"
touch "$FILE"
grep -qF "luna/run.sh" "$FILE" || echo "$LINE" >> "$FILE"
echo "Autostart installed in $FILE:"
grep -F "luna" "$FILE"
