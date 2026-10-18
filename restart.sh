#!/bin/bash
# Restart Luna safely: wait until nobody has talked to her for IDLE_SECS
# (main.py stamps /tmp/luna_last_activity), then stop and start her again
# with the log APPENDED, so earlier conversations stay readable.
#   ./restart.sh            wait for 3 quiet minutes (up to 30 min)
#   ./restart.sh --now      don't wait — and take over from a restart that is
#                           still waiting (Andrzej, 17 Oct: "never wait")
#   ./restart.sh --tested   skip the tests when this exact code just passed
#                           tools/check_pi.sh (it leaves /tmp/luna_checked.sums)
#   ./restart.sh --force    skip the tests — only if it's a test that is broken
# Ends when she is up: "restart: OK — pid N" (exit 0), or what went wrong (exit 1).
cd "$(dirname "$0")"
NOW=0; FORCE=0; TESTED=0
for a in "$@"; do
    case "$a" in
        --now) NOW=1 ;;
        --force) FORCE=1 ;;
        --tested) TESTED=1 ;;
    esac
done

# one restart at a time: two waiting for the same quiet minute both started a
# Luna (11 Oct 17:35 — the second had no camera or mic). --now takes over from
# the one waiting (it used to say "another restart is waiting" and leave the
# new code waiting with it — 17 Oct, "waiting for restart for 3 min").
exec 9>/tmp/luna_restart.lock
if ! flock -n 9; then
    old=$(cat /tmp/luna_restart.pid 2>/dev/null)
    if [ "$NOW" = 1 ] && [ -n "$old" ] && grep -aq restart.sh "/proc/$old/cmdline" 2>/dev/null; then
        pkill -P "$old" 2>/dev/null; kill "$old" 2>/dev/null
        echo "restart: took over from the restart that was waiting ($old)"
    fi
    if ! flock -w 15 9; then
        echo "restart: another restart is running — it will start the new code"
        exit 0
    fi
fi
echo $$ > /tmp/luna_restart.pid

IDLE_SECS=180
wait_idle() {
    [ "$NOW" = 1 ] && return
    for _ in $(seq 1 180); do
        last=$(cat /tmp/luna_last_activity 2>/dev/null || echo 0)
        now=$(date +%s)
        busy=$(cut -d" " -f1 /tmp/luna_busy 2>/dev/null || echo 0)
        # idle, and not in the middle of a game, a reading, cooking or the radio
        if [ $(( now - ${last%.*} )) -ge $IDLE_SECS ] && [ "$now" -ge "${busy:-0}" ]; then return; fi
        sleep 10
    done
}
wait_idle

# the new code must pass the tests (real modules, silent) — a broken version is
# never started; the running Luna stays as she is. Code that just passed
# tools/check_pi.sh byte for byte needn't run them twice (a minute or two).
if [ "$TESTED" = 1 ] && [ -f /tmp/luna_checked.sums ] \
        && md5sum -c --quiet /tmp/luna_checked.sums >/dev/null 2>&1; then
    echo "restart: this code passed tools/check_pi.sh — no second test run"
    FORCE=1
elif [ "$TESTED" = 1 ]; then
    echo "restart: the code differs from what tools/check_pi.sh passed — testing it"
fi
if [ "$FORCE" != 1 ] && [ -f tests/smoke_pi.py ]; then
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
    # …and every sentence still reaches the right handler (7 Oct: two
    # regressions only this test caught — "na razie nie" dimmed the screen)
    if [ -f tests/test_routing.py ] && \
       ! timeout 120 ./venv/bin/python -X utf8 tests/test_routing.py > /tmp/luna_routing.out 2>&1; then
        echo "restart: ROUTING TEST FAILED — not restarting:"
        grep -E "^FAIL|^ERROR|AssertionError" /tmp/luna_routing.out | head -20
        echo "restart: routing test failed, kept the running Luna" >> luna.log
        exit 1
    fi
fi
# the tests take a minute or two — someone may have started talking to her
# meanwhile (11 Oct 16:31: stopped while answering "włącz radio z jazzem")
wait_idle
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
mark="===== restart $(date '+%F %T') ====="
echo "$mark" >> luna.log
(setsid nohup /usr/bin/lwrespawn "$PWD/run.sh" >> "$PWD/luna.log" 2>&1 < /dev/null 9>&- &)

# wait for her microphone (≤ 60 s), then say how it went
since() { awk -v m="$mark" '$0 == m {f=1} f' luna.log; }
for _ in $(seq 1 30); do
    since | grep -aq "Microphone stream running\|Traceback" && break
    sleep 2
done
pid=$(pgrep -f "^\./venv/bin/python -u main.py" | head -1)
if since | grep -aq Traceback; then
    echo "restart: FAILED — a traceback at start:"
    since | grep -a -A8 Traceback | head -20
    exit 1
elif ! since | grep -aq "Microphone stream running"; then
    echo "restart: she started (pid ${pid:-none}) but no microphone after 60 s"
    since | tail -5
    exit 1
fi
echo "restart: OK — pid $pid"
