#!/usr/bin/env bash
# aec.sh — echo cancelling for Luna on/off (run ON THE PI, no sudo needed).
#
#     tools/aec.sh status
#     tools/aec.sh on      # install pi/60-luna-echo-cancel.conf, restart PipeWire,
#                          # point LUNA_MIC / LUNA_SPEAKER in .env at the AEC nodes
#     tools/aec.sh off     # undo all of it
#
# Then restart Luna (./restart.sh --now). With AEC on, bargein.py can be switched
# from "log" to True in config.py. .env is edited in place, never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
CONF="$CONF_DIR/60-luna-echo-cancel.conf"

set_env() {        # set_env KEY VALUE — replace or append one line of .env
    if grep -q "^$1=" .env 2>/dev/null; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        echo "$1=$2" >> .env
    fi
}

save_env() {       # remember the old value once, to restore it on "off"
    local old
    old=$(grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || true)
    grep -q "^#AEC_OLD_$1=" .env 2>/dev/null || echo "#AEC_OLD_$1=$old" >> .env
}

restore_env() {
    local old
    old=$(grep "^#AEC_OLD_$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [ -n "$old" ]; then set_env "$1" "$old"; else sed -i "/^$1=/d" .env; fi
    sed -i "/^#AEC_OLD_$1=/d" .env
}

restart_pw() {
    systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null ||
        systemctl --user restart pipewire wireplumber
    sleep 2
}

case "${1:-status}" in
    on)
        mkdir -p "$CONF_DIR"
        cp pi/60-luna-echo-cancel.conf "$CONF"
        restart_pw
        save_env LUNA_MIC; save_env LUNA_SPEAKER
        set_env LUNA_MIC "pw:luna_aec_source"
        set_env LUNA_SPEAKER "luna_aec_sink"
        echo "[aec] on — now: ./restart.sh --now"
        ;;
    off)
        rm -f "$CONF"
        restart_pw
        restore_env LUNA_MIC; restore_env LUNA_SPEAKER
        echo "[aec] off — now: ./restart.sh --now"
        ;;
    status)
        [ -f "$CONF" ] && echo "[aec] config installed" || echo "[aec] config not installed"
        wpctl status 2>/dev/null | grep -i "luna_aec\|echo" || echo "[aec] no AEC nodes running"
        grep -q "^LUNA_MIC=pw:" .env 2>/dev/null && echo "[aec] Luna set to the AEC mic" ||
            echo "[aec] Luna uses the plain mic"
        ;;
    *)
        echo "usage: $0 on|off|status"; exit 1 ;;
esac
