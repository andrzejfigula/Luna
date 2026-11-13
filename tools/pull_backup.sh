#!/usr/bin/env bash
# pull_backup.sh — a copy of her data OFF the Pi, onto this PC. Her own daily
# backup (backup.py) sits on the same SD card as the data: a dead card takes
# both, and it never held the drawings, paintings, photos or learned faces.
#
#     tools/pull_backup.sh              # data/ + photos/ → $LUNA_BACKUP_DIR/luna-<day>.tgz
#     tools/pull_backup.sh --if-stale   # only if today's isn't there yet (ship.sh calls this)
#
# Kept: the last 7 archives. Left out: data/tts_cache (made again on demand).
# The folder is outside the repo (default ~/luna-backup): it holds family data.
# After a good copy the Pi gets data/.offsite, so backup.py can say when the
# last one is older than two days.
set -euo pipefail
PI="${LUNA_PI:-raspberry@raspberrypi.local}"
DEST="${LUNA_BACKUP_DIR:-$HOME/luna-backup}"
KEEP=7
day=$(date +%Y-%m-%d)
out="$DEST/luna-$day.tgz"
mkdir -p "$DEST"
if [ "${1:-}" = "--if-stale" ] && [ -s "$out" ]; then
    exit 0
fi
ssh -o ConnectTimeout=10 "$PI" \
    'cd ~/luna && tar -czf - --exclude=data/tts_cache --exclude="*.tmp" data photos' > "$out.part"
n=$(tar -tzf "$out.part" | wc -l)                 # reads to the end: a cut-off copy fails here
if [ "$n" -lt 20 ] || ! tar -tzf "$out.part" | grep -q '^data/memory.json$'; then
    echo "pull_backup: the copy looks wrong ($n files) — kept as $out.part, the old ones untouched"
    exit 1
fi
mv -f "$out.part" "$out"
ls -1t "$DEST"/luna-*.tgz | tail -n +$((KEEP + 1)) | while read -r old; do rm -f "$old"; done
ssh -o ConnectTimeout=10 "$PI" 'date +%s > ~/luna/data/.offsite'
echo "pull_backup: $n files, $(du -h "$out" | cut -f1) → $out"
