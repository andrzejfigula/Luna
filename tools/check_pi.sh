#!/usr/bin/env bash
# check_pi.sh — run the test gates against the WORKING TREE, before deploying:
# the tracked files (with local edits) go to a fresh /tmp/lunacheck-run-* on
# the Pi and run with ~/luna's venv — routing, smoke, dialog (the gates
# restart.sh uses; it refuses a restart when routing fails, 8 Oct). The unit
# tests run HERE meanwhile: 10 s on the PC against 99 s on the Pi (21 Oct);
# the ones skipped here (no cv2, pygame, sounddevice) then run on the Pi.
# Silent: dialog_pi stands in for text_to_speech. Scratch data only.
# Lanes side by side, each with its own scratch data. When all pass,
# /tmp/luna_checked.sums records the files' checksums: restart.sh --tested
# then skips running the same tests again.
#
#     tools/check_pi.sh            # unit here | routing + smoke, dialog on the Pi
#     tools/check_pi.sh quick      # unit here | smoke on the Pi (ship.sh --quick)
#     tools/check_pi.sh full       # all four on the Pi (its Python 3.13, numpy…)
#     tools/check_pi.sh unit       # just one, on the Pi: unit | routing | smoke | dialog
#
# Each run has its own directory (21 Oct: a second session's check wiped
# /tmp/lunacheck under a running one); LUNA_CHECK_DIR still picks one by hand.
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
SSH=(ssh -o HostKeyAlias=raspberrypi.local -o ConnectTimeout=10 -o ServerAliveInterval=10 "$PI")
cd "$(dirname "$0")/.."

which="${1:-all}"
case "$which" in
    all)   lanes="routing,smoke dialog"; local_unit=1 ;;
    quick) lanes="smoke";                local_unit=1 ;;
    full)  lanes="unit routing,smoke dialog"; local_unit=0 ;;
    unit|routing|smoke|dialog) lanes="$which"; local_unit=0 ;;
    *) echo "check_pi.sh: all | quick | full | unit | routing | smoke | dialog"; exit 2 ;;
esac
gates=" ${lanes//,/ } "
case "$which" in all|quick|full) record=1 ;; *) record=0 ;; esac

if [ -n "${LUNA_CHECK_DIR:-}" ]; then
    DIR="$LUNA_CHECK_DIR"; keep=1
else
    DIR="/tmp/lunacheck-run-$(date +%s)-$$-$RANDOM"; keep=0
fi

cleanup() {
    [ -n "${unit_pid:-}" ] && kill "$unit_pid" 2>/dev/null
    [ -n "${unit_out:-}" ] && rm -f "$unit_out" "$unit_out".*
    [ "$keep" = 0 ] && "${SSH[@]}" "rm -rf $DIR" 2>/dev/null
    return 0
}
trap cleanup EXIT

files=$(git ls-files | grep -v -E '\.md$|^\.git')
# (runs killed half way leave their directories: an hour old ones go)
tar -cf - $files | "${SSH[@]}" "find /tmp -maxdepth 1 -name 'lunacheck-run-*' -mmin +60 -exec rm -rf {} + 2>/dev/null
    rm -rf $DIR && mkdir -p $DIR && tar -xf - -C $DIR"
# (the list restart.sh --tested compares: what deploy.sh copies, so not .env*)
printf '%s\n' $files | grep -v '^\.env' | "${SSH[@]}" "cat > $DIR/.checked_files"
# what isn't in git: the key (.env — linked, never read here), the speech model,
# the face models and sounds; and what scenario-style tests copy
"${SSH[@]}" "cd $DIR" ' && for p in .env vosk-model-small-pl-0.22 data/models data/sounds; do
    [ -e ~/luna/$p ] && [ ! -e $p ] && ln -s ~/luna/$p $p; done
    cp ~/luna/data/people.json ~/luna/data/settings.json data/ 2>/dev/null || true'

# the unit tests here, beside the Pi's lanes; then what was skipped here, there
if [ "$local_unit" = 1 ]; then
    unit_out=$(mktemp)
    {
        python -X utf8 tests/run_unit.py "$unit_out.skipped" > "$unit_out.here" 2>&1 \
            && "${SSH[@]}" "cd $DIR && T=\$(mktemp -d /tmp/lunatest-XXXXXX) D=\$(mktemp -d /tmp/lunadata-XXXXXX)
                TMPDIR=\$T LUNA_DATA_DIR=\$D timeout 400 ~/luna/venv/bin/python -X utf8 tests/run_unit.py --ids
                r=\$?; rm -rf \$T \$D; exit \$r" < "$unit_out.skipped" > "$unit_out.pi" 2>&1
    } &
    unit_pid=$!
fi

# every temp dir the tests make goes under one TMPDIR per lane, removed at the end
# (14 Oct: 3764 /tmp/luna-photos-* left on the Pi by earlier runs)
pi_ok=0
"${SSH[@]}" "cd $DIR && rm -f /tmp/luna_checked.sums && PY=~/luna/venv/bin/python W=\$(mktemp -d /tmp/lunacheck-out-XXXXXX)
  want() { case '$gates' in *\" \$1 \"*) return 0 ;; esac; return 1; }
  lane() {   # gate,gate…: run one after another in fresh scratch dirs
    export TMPDIR=\$(mktemp -d /tmp/lunatest-XXXXXX) LUNA_DATA_DIR=\$(mktemp -d /tmp/lunadata-XXXXXX)
    for g in \$(echo \$1 | tr , ' '); do
      case \$g in
        unit)    timeout 400 \$PY -X utf8 -m unittest -q tests.test_local_logic ;;
        routing) timeout 200 \$PY -X utf8 tests/test_routing.py ;;
        smoke)   timeout 300 \$PY -X utf8 tests/smoke_pi.py ;;
        dialog)  timeout 400 \$PY -X utf8 tests/dialog_pi.py ;;
      esac > \$W/\$g.out 2>&1
    done
    rm -rf \$TMPDIR \$LUNA_DATA_DIR
  }
  for l in $lanes; do lane \$l & done; wait
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
  if [ \$ok = 0 ] && [ $record = 1 ]; then
    xargs -d '\n' md5sum < .checked_files > .checked.sums
  fi
  [ \$ok = 0 ]" || pi_ok=1

unit_ok=0
if [ "$local_unit" = 1 ]; then
    wait "$unit_pid" || true; unit_pid=
    for part in here pi; do
        [ -s "$unit_out.$part" ] || continue
        tail -1 "$unit_out.$part" | sed "s/^/unit:    /; s/\$/ ($part)/"
        grep -A12 '^FAIL:\|^ERROR:' "$unit_out.$part" | head -30 || true
    done
    tail -1 "$unit_out.here" | grep -q '^OK' && tail -1 "$unit_out.pi" 2>/dev/null | grep -q '^OK' \
        || unit_ok=1
fi

if [ "$pi_ok" = 0 ] && [ "$unit_ok" = 0 ]; then
    [ "$record" = 1 ] && "${SSH[@]}" "cp $DIR/.checked.sums /tmp/luna_checked.sums"
    echo 'check: ALL OK'
else
    echo 'check: FAILED'; exit 1
fi
