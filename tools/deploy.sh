#!/usr/bin/env bash
# deploy.sh — copy to the Pi every tracked file that differs from it, then
# (with --restart) restart her the safe way (restart.sh: waits for idle,
# keeps the running Luna if the smoke or dialog test fails).
#
#     tools/deploy.sh              # show and copy what differs
#     tools/deploy.sh --dry-run    # only show it
#     tools/deploy.sh --restart    # copy, then ./restart.sh
#
# Copying files by hand once left touch_module.py two days behind (hold to
# interrupt, #57, never reached the Pi). Compared by content (line endings
# ignored); never touches data/, .env or anything untracked.
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
cd "$(dirname "$0")/.."

# a patch written through a shell heredoc turns "\b" into a backspace byte —
# a regex then silently never matches (7 Oct: three times in one evening)
bad=$(git ls-files -- '*.py' | xargs grep -lP '[\x00-\x08\x0b\x0c\x0e-\x1f]' 2>/dev/null || true)
if [ -n "$bad" ]; then
    echo "[deploy] REFUSED — control characters (a mangled \\b?) in:"; sed 's/^/  /' <<<"$bad"
    exit 1
fi

new=$(git ls-files --others --exclude-standard -- '*.py' '*.sh' '*.txt')
if [ -n "$new" ]; then
    echo "[deploy] not in git yet, so NOT copied (git add them first):"; sed 's/^/  /' <<<"$new"
fi
files=$(git ls-files | grep -v -E '\.md$|^\.git|^\.env')
local_sums=$(for f in $files; do printf '%s %s\n' "$(tr -d '\r' < "$f" | md5sum | cut -c1-32)" "$f"; done)
remote_sums=$(printf '%s\n' $files | ssh "$PI" 'cd ~/luna && while read f; do
    if [ -f "$f" ]; then printf "%s %s\n" "$(tr -d "\r" < "$f" | md5sum | cut -c1-32)" "$f";
    else printf "missing %s\n" "$f"; fi; done')
changed=$(join -1 2 -2 2 <(sort -k2 <<<"$local_sums") <(sort -k2 <<<"$remote_sums") \
          | awk '$2 != $3 {print $1}')

if [ -z "$changed" ]; then
    echo "[deploy] the Pi already has every tracked file"
else
    echo "[deploy] differs on the Pi:"; sed 's/^/  /' <<<"$changed"
    if [ "${1:-}" != "--dry-run" ]; then
        for f in $changed; do
            ssh "$PI" "mkdir -p ~/luna/$(dirname "$f")"
            scp -q "$f" "$PI:luna/$f"
        done
        echo "[deploy] copied $(wc -l <<<"$changed") file(s)"
    fi
fi
if [ "${1:-}" = "--restart" ]; then
    ssh "$PI" 'cd ~/luna && ./restart.sh'
fi
