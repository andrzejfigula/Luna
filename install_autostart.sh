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

# PipeWire tuning for the Pi's 3.5 mm output: big quantum (no xruns during
# face rendering), no idle suspend (no wake-up pop), extra ALSA headroom.
SRC="$(cd "$(dirname "$0")" && pwd)/pi"
mkdir -p "$HOME/.config/pipewire/pipewire.conf.d" "$HOME/.config/wireplumber/wireplumber.conf.d"
cp "$SRC/51-luna-quantum.conf"    "$HOME/.config/pipewire/pipewire.conf.d/"
cp "$SRC/51-luna-no-suspend.conf" "$HOME/.config/wireplumber/wireplumber.conf.d/"
systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null && echo "PipeWire audio tuning installed"
