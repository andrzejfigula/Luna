#!/usr/bin/env bash
# preflight.sh — what fails in a second on the PC, before a minute on the Pi:
# control characters in *.py, a syntax error in a changed module; and a warning
# for new files git doesn't know (the Pi never sees them). Called by
# check_pi.sh and deploy.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

# a patch written through a shell heredoc turns "\b" into a backspace byte —
# a regex then silently never matches (7 Oct: three times in one evening)
bad=$(git ls-files -- '*.py' | xargs grep -lP '[\x00-\x08\x0b\x0c\x0e-\x1f]' 2>/dev/null || true)
if [ -n "$bad" ]; then
    echo "[preflight] REFUSED — control characters (a mangled \\b?) in:"; sed 's/^/  /' <<<"$bad"
    exit 1
fi

new=$(git ls-files --others --exclude-standard -- '*.py' '*.sh' '*.txt')
if [ -n "$new" ]; then
    echo "[preflight] not in git yet, so NOT tested or copied (git add them first):"; sed 's/^/  /' <<<"$new"
fi

changed=$(git diff --name-only --diff-filter=d HEAD -- '*.py')
if [ -n "$changed" ]; then
    # shellcheck disable=SC2086
    python -X utf8 -c '
import ast, sys
bad = 0
for path in sys.argv[1:]:
    try:
        ast.parse(open(path, encoding="utf-8").read(), path)
    except SyntaxError as e:
        print(f"[preflight] REFUSED — {path}:{e.lineno}: {e.msg}")
        bad = 1
sys.exit(bad)' $changed
fi
