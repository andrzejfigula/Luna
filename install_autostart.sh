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

# Keep the 3.5 mm output from suspending (it pops when it wakes up)
WP="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WP"
cp "$(dirname "$0")/pi/51-luna-no-suspend.conf" "$WP/"
systemctl --user restart wireplumber 2>/dev/null && echo "WirePlumber no-suspend rule installed"
