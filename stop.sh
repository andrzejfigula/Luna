#!/bin/bash
# Stop Luna (and the lwrespawn watchdog that would restart her).
pkill -f "lwrespawn.*luna/run.sh" 2>/dev/null
for p in $(pgrep -x python); do
    grep -q "main.py" /proc/$p/cmdline 2>/dev/null && kill "$p"
done
echo "Luna stopped"
