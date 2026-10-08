#!/usr/bin/env bash
# check_pi.sh — run the test gates on the Pi against the WORKING TREE, before
# deploying: the tracked files (with local edits) go to a clean /tmp/lunacheck
# and run with ~/luna's venv — unit tests, routing, smoke, dialog (the same
# gates restart.sh uses; it refuses a restart when routing fails, 8 Oct).
# Silent: dialog_pi stands in for text_to_speech. Scratch data only.
#
#     tools/check_pi.sh            # all four
#     tools/check_pi.sh unit       # just one: unit | routing | smoke | dialog
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
SSH=(ssh -o HostKeyAlias=raspberrypi.local "$PI")
cd "$(dirname "$0")/.."

git ls-files | grep -v -E '\.md$|^\.git' | tar -cf - -T - \
    | "${SSH[@]}" 'rm -rf /tmp/lunacheck && mkdir -p /tmp/lunacheck && tar -xf - -C /tmp/lunacheck'
# what isn't in git: the key (.env — linked, never read here), the speech model,
# the face models and sounds; and what scenario-style tests copy
"${SSH[@]}" 'cd /tmp/lunacheck && for p in .env vosk-model-small-pl-0.22 data/models data/sounds; do
    [ -e ~/luna/$p ] && [ ! -e $p ] && ln -s ~/luna/$p $p; done
    cp ~/luna/data/people.json ~/luna/data/settings.json data/ 2>/dev/null || true'

which="${1:-all}"
"${SSH[@]}" "cd /tmp/lunacheck && export LUNA_DATA_DIR=\$(mktemp -d) && PY=~/luna/venv/bin/python
  ok=0
  if [ $which = all ] || [ $which = unit ]; then
    r=\$(\$PY -X utf8 -m unittest -q tests.test_local_logic 2>&1); echo \"\$r\" | tail -1 | sed 's/^/unit:    /'
    echo \"\$r\" | grep -A12 '^FAIL:\|^ERROR:' | head -30; echo \"\$r\" | tail -1 | grep -q '^OK' || ok=1
  fi
  if [ $which = all ] || [ $which = routing ]; then
    r=\$(timeout 200 \$PY -X utf8 tests/test_routing.py 2>&1); echo \"\$r\" | tail -1 | sed 's/^/routing: /'
    echo \"\$r\" | grep -E '^FAIL|AssertionError|Error' | head -10; echo \"\$r\" | tail -1 | grep -q '^OK' || ok=1
  fi
  if [ $which = all ] || [ $which = smoke ]; then
    r=\$(timeout 300 \$PY -X utf8 tests/smoke_pi.py 2>&1); echo \"\$r\" | grep -a 'FAIL\|\[smoke\]' | tail -5
    echo \"\$r\" | grep -q '\[smoke\] OK' || ok=1
  fi
  if [ $which = all ] || [ $which = dialog ]; then
    r=\$(timeout 400 \$PY -X utf8 tests/dialog_pi.py 2>&1); echo \"\$r\" | grep -a 'FAIL\|\[dialog\]' | tail -8
    echo \"\$r\" | grep -q '\[dialog\] OK' || ok=1
  fi
  rm -rf \$LUNA_DATA_DIR
  [ \$ok = 0 ] && echo 'check: ALL OK' || { echo 'check: FAILED'; exit 1; }"
