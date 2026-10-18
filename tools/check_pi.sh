#!/usr/bin/env bash
# check_pi.sh — run the test gates on the Pi against the WORKING TREE, before
# deploying: the tracked files (with local edits) go to a clean /tmp/lunacheck
# and run with ~/luna's venv — unit tests, routing, smoke, dialog (the same
# gates restart.sh uses; it refuses a restart when routing fails, 8 Oct).
# Silent: dialog_pi stands in for text_to_speech. Scratch data only.
# Two lanes side by side (unit + routing | smoke + dialog), each with its own
# scratch data. When all pass, /tmp/luna_checked.sums records the files'
# checksums: restart.sh --tested then skips running the same tests again.
#
#     tools/check_pi.sh            # all four
#     tools/check_pi.sh unit       # just one: unit | routing | smoke | dialog
#     LUNA_CHECK_DIR=/tmp/lunacheck2 tools/check_pi.sh   # beside a sweep running
#                                  # in /tmp/lunacheck (it would be swept away)
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
SSH=(ssh -o HostKeyAlias=raspberrypi.local -o ConnectTimeout=10 -o ServerAliveInterval=10 "$PI")
DIR="${LUNA_CHECK_DIR:-/tmp/lunacheck}"
cd "$(dirname "$0")/.."

files=$(git ls-files | grep -v -E '\.md$|^\.git')
tar -cf - $files | "${SSH[@]}" "rm -rf $DIR && mkdir -p $DIR && tar -xf - -C $DIR"
# (the list restart.sh --tested compares: what deploy.sh copies, so not .env*)
printf '%s\n' $files | grep -v '^\.env' | "${SSH[@]}" "cat > $DIR/.checked_files"
# what isn't in git: the key (.env — linked, never read here), the speech model,
# the face models and sounds; and what scenario-style tests copy
"${SSH[@]}" "cd $DIR" ' && for p in .env vosk-model-small-pl-0.22 data/models data/sounds; do
    [ -e ~/luna/$p ] && [ ! -e $p ] && ln -s ~/luna/$p $p; done
    cp ~/luna/data/people.json ~/luna/data/settings.json data/ 2>/dev/null || true'

which="${1:-all}"
# every temp dir the tests make goes under one TMPDIR per lane, removed at the end
# (14 Oct: 3764 /tmp/luna-photos-* left on the Pi by earlier runs)
"${SSH[@]}" "cd $DIR && rm -f /tmp/luna_checked.sums && PY=~/luna/venv/bin/python W=\$(mktemp -d /tmp/lunacheck-out-XXXXXX)
  want() { [ $which = all ] || [ $which = \$1 ]; }
  lane() {   # name…: runs these gates one after another in fresh scratch dirs
    export TMPDIR=\$(mktemp -d /tmp/lunatest-XXXXXX) LUNA_DATA_DIR=\$(mktemp -d /tmp/lunadata-XXXXXX)
    for g in \"\$@\"; do
      want \$g || continue
      case \$g in
        unit)    timeout 400 \$PY -X utf8 -m unittest -q tests.test_local_logic ;;
        routing) timeout 200 \$PY -X utf8 tests/test_routing.py ;;
        smoke)   timeout 300 \$PY -X utf8 tests/smoke_pi.py ;;
        dialog)  timeout 400 \$PY -X utf8 tests/dialog_pi.py ;;
      esac > \$W/\$g.out 2>&1
    done
    rm -rf \$TMPDIR \$LUNA_DATA_DIR
  }
  lane unit routing & lane smoke dialog & wait
  ok=0
  if want unit; then
    tail -1 \$W/unit.out | sed 's/^/unit:    /'
    grep -A12 '^FAIL:\|^ERROR:' \$W/unit.out | head -30; tail -1 \$W/unit.out | grep -q '^OK' || ok=1
  fi
  if want routing; then
    tail -1 \$W/routing.out | sed 's/^/routing: /'
    grep -E '^FAIL|AssertionError|Error' \$W/routing.out | head -10; tail -1 \$W/routing.out | grep -q '^OK' || ok=1
  fi
  if want smoke; then
    grep -a 'FAIL\|\[smoke\]' \$W/smoke.out | tail -5; grep -q '\[smoke\] OK' \$W/smoke.out || ok=1
  fi
  if want dialog; then
    grep -a 'FAIL\|\[dialog\]' \$W/dialog.out | tail -8; grep -q '\[dialog\] OK' \$W/dialog.out || ok=1
  fi
  rm -rf \$W
  if [ \$ok = 0 ] && [ $which = all ]; then
    xargs -d '\n' md5sum < .checked_files > /tmp/luna_checked.sums
  fi
  [ \$ok = 0 ] && echo 'check: ALL OK' || { echo 'check: FAILED'; exit 1; }"
