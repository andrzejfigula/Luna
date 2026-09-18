#!/bin/bash
# Launch Luna inside the labwc Wayland session (from a terminal, SSH, or systemd).
cd "$(dirname "$0")"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland}"

# Screen brightness (percent) from .env — LUNA_BRIGHTNESS=100. The DSI panel
# boots at ~30 %; the backlight file is writable by the "video" group.
PCT=$(grep -E '^LUNA_BRIGHTNESS=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' "')
if [[ "$PCT" =~ ^[0-9]+$ ]]; then
    for BL in /sys/class/backlight/*; do
        MAX=$(cat "$BL/max_brightness" 2>/dev/null) || continue
        echo $(( MAX * PCT / 100 )) > "$BL/brightness" 2>/dev/null && \
            echo "[run] backlight $(basename "$BL") set to ${PCT}%"
    done
fi

exec ./venv/bin/python -u main.py
