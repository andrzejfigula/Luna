#!/bin/bash
# Restart Luna safely: wait until nobody has talked to her for IDLE_SECS
# (main.py stamps /tmp/luna_last_activity), then stop and start her again
# with the log APPENDED, so earlier conversations stay readable.
#   ./restart.sh          wait for 3 quiet minutes (up to 30 min)
#   ./restart.sh --now    don't wait
cd "$(dirname "$0")"
IDLE_SECS=180
if [ "$1" != "--now" ]; then
    for _ in $(seq 1 180); do
        last=$(cat /tmp/luna_last_activity 2>/dev/null || echo 0)
        now=$(date +%s)
        if [ $(( now - ${last%.*} )) -ge $IDLE_SECS ]; then break; fi
        sleep 10
    done
fi
./stop.sh >/dev/null 2>&1
sleep 2
echo "===== restart $(date '+%F %T') =====" >> luna.log
(setsid nohup /usr/bin/lwrespawn "$PWD/run.sh" >> "$PWD/luna.log" 2>&1 < /dev/null &)
sleep 15
grep -E "Running on|Traceback" luna.log | tail -2
