#!/bin/bash
# Restart Luna safely: wait until nobody has talked to her for IDLE_SECS
# (main.py stamps /tmp/luna_last_activity), then stop and start her again
# with the log APPENDED, so earlier conversations stay readable.
#   ./restart.sh          wait for 3 quiet minutes (up to 30 min)
#   ./restart.sh --now    don't wait
#   ./restart.sh --force  skip the smoke test (tests/smoke_pi.py) — only if
#                         it's the test itself that is broken
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
# the new code must pass the smoke test (real modules, silent) — a broken
# version is never started; the running Luna stays as she is
if [ "$1" != "--force" ] && [ -f tests/smoke_pi.py ]; then
    if ! timeout 180 ./venv/bin/python tests/smoke_pi.py > /tmp/luna_smoke.out 2>&1; then
        echo "restart: SMOKE TEST FAILED — not restarting:"
        grep -E "FAIL|^  -" /tmp/luna_smoke.out
        echo "restart: smoke test failed, kept the running Luna" >> luna.log
        exit 1
    fi
    # …and the everyday sentences must still get the right answers
    if [ -f tests/dialog_pi.py ] && \
       ! timeout 120 ./venv/bin/python -X utf8 tests/dialog_pi.py > /tmp/luna_dialog.out 2>&1; then
        echo "restart: DIALOG TEST FAILED — not restarting:"
        grep -E "FAIL" /tmp/luna_dialog.out
        echo "restart: dialog test failed, kept the running Luna" >> luna.log
        exit 1
    fi
fi
./stop.sh >/dev/null 2>&1
# a Luna that doesn't go within 5 s is killed — two of them fight over the mic
for _ in 1 2 3 4 5; do
    pgrep -f "^\./venv/bin/python -u main.py" >/dev/null || break
    sleep 1
done
for pid in $(pgrep -f "^\./venv/bin/python -u main.py"); do
    [ "$(readlink -f /proc/$pid/cwd)" = "$PWD" ] && kill -9 "$pid" 2>/dev/null \
        && echo "restart: killed a stuck Luna ($pid)" >> luna.log
done
sleep 1
echo "===== restart $(date '+%F %T') =====" >> luna.log
(setsid nohup /usr/bin/lwrespawn "$PWD/run.sh" >> "$PWD/luna.log" 2>&1 < /dev/null &)
sleep 15
grep -E "Running on|Traceback" luna.log | tail -2
