#!/bin/bash
# Stop Luna and the lwrespawn watchdog that would restart her.
#
# Matches on the exact argv of the two processes instead of `pkill -f`, which
# also matches any shell (an SSH session, for instance) whose command line
# merely mentions "luna/run.sh".
HERE="$(cd "$(dirname "$0")" && pwd)"
killed=0

for pid in $(pgrep -x lwrespawn) $(pgrep -x sh) $(pgrep -x python); do
    [ "$pid" = "$$" ] && continue
    mapfile -d '' argv < "/proc/$pid/cmdline" 2>/dev/null || continue
    case "${argv[1]}" in
        /usr/bin/lwrespawn|lwrespawn)          # /bin/sh /usr/bin/lwrespawn <run.sh>
            [[ "${argv[2]}" == "$HERE/run.sh" || "${argv[2]}" == *"/luna/run.sh" ]] || continue ;;
        -u|main.py)                             # ./venv/bin/python -u main.py
            [[ "${argv[*]}" == *"main.py"* ]] || continue
            [[ "$(readlink -f /proc/$pid/cwd)" == "$HERE" ]] || continue ;;
        *) continue ;;
    esac
    kill "$pid" 2>/dev/null && killed=$((killed + 1))
done

echo "Luna stopped ($killed process(es))"
