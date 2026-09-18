#!/bin/bash
# Launch Luna inside the labwc Wayland session (from a terminal, SSH, or systemd).
cd "$(dirname "$0")"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland}"
exec ./venv/bin/python -u main.py
