#!/bin/bash
# sysupgrade.sh — the Pi's apt upgrade with a way back. Run ON THE PI, by Andrzej:
#
#   bash tools/sysupgrade.sh list              # what would change (no sudo)
#   sudo bash tools/sysupgrade.sh upgrade      # backup, then apt full-upgrade; reboot after
#   sudo bash tools/sysupgrade.sh rollback     # the saved versions back; reboot after
#   sudo bash tools/sysupgrade.sh backup       # only the backup
#
# The backup (~/luna-rollback/sys-DATE/) holds a .deb of every package about to
# change — from apt's cache, or rebuilt from the installed files with dpkg-repack,
# because the repos no longer carry the old Mesa / labwc / kernel — and a copy of
# /boot/firmware. The old kernel's package stays installed (no autoremove here).
set -uo pipefail
ROOT=/home/raspberry/luna-rollback
CACHE=/var/cache/apt/archives
cmd=${1:-}

upgradable() { apt list --upgradable 2>/dev/null | grep 'upgradable from:'; }
latest() { ls -d "$ROOT"/sys-* 2>/dev/null | tail -1; }
need_root() { [ "$(id -u)" = 0 ] || { echo "run it with sudo"; exit 1; }; }
# "pkg/suite new arch [upgradable from: old]" → "pkg arch old"
fields() { sed -n 's|^\([^/]*\)/[^ ]* [^ ]* \([^ ]*\) \[upgradable from: \(.*\)\]$|\1 \2 \3|p'; }

backup() {
    D="$ROOT/sys-$(date +%Y%m%d-%H%M)"
    mkdir -p "$D/debs" || exit 1
    # all of it into a log too: the first run stopped after 8 s and left no trace
    exec 3>&1 4>&2 > >(tee -a "$ROOT/sysupgrade.log") 2>&1
    echo "== backup $(date) in $D"
    dpkg-query -W -f='${binary:Package}=${Version}\n' > "$D/installed.txt"
    apt-mark showmanual > "$D/manual.txt"
    apt-get update || { echo "apt-get update failed"; exit 1; }
    command -v dpkg-repack >/dev/null || apt-get install -y dpkg-repack || exit 1
    upgradable > "$D/upgradable.txt"
    tar -C /boot/firmware -czf "$D/boot-firmware.tgz" . || { echo "no copy of /boot/firmware"; exit 1; }
    cd "$D/debs" || exit 1
    : > "$D/failed.txt"
    n=0
    while read -r pkg arch old; do
        n=$((n + 1))
        f="$CACHE/${pkg}_${old//:/%3a}_${arch}.deb"
        if [ -f "$f" ]; then
            cp "$f" . && continue
        fi
        name=$pkg; [ "$arch" = all ] || name="$pkg:$arch"
        dpkg-repack "$name" >/dev/null 2>>"$D/repack.log" || echo "$name" >> "$D/failed.txt"
    done < <(fields < "$D/upgradable.txt")
    # what the upgrade would remove (pcmanfm, 10 Nov) is saved too
    apt-get -s full-upgrade 2>/dev/null | awk '/^Remv /{print $2}' > "$D/removed.txt"
    while read -r name; do
        n=$((n + 1))
        dpkg-repack "$name" >/dev/null 2>>"$D/repack.log" || echo "$name" >> "$D/failed.txt"
    done < "$D/removed.txt"
    cd / && chown -R raspberry:raspberry "$ROOT"
    echo "backup: $(ls "$D/debs" | wc -l) of $n packages saved in $D ($(du -sh "$D" | cut -f1))"
    if [ -s "$D/failed.txt" ]; then
        echo "backup: NOT saved: $(tr '\n' ' ' < "$D/failed.txt")"
        echo "backup: incomplete — nothing upgraded (see $D/repack.log)"
        exit 1
    fi
}

case "$cmd" in
list)
    upgradable | fields | while read -r pkg arch old; do
        [ -f "$CACHE/${pkg}_${old//:/%3a}_${arch}.deb" ] && echo "cached $pkg $old" || echo "repack $pkg $old"
    done | sort | awk '{c[$1]++; print} END {for (k in c) print "#", k, c[k]}'
    ;;
backup)
    need_root; backup
    ;;
upgrade)
    need_root; backup
    exec 1>&3 2>&4
    echo "upgrade: apt full-upgrade — it asks before it starts"
    apt-get -o Dpkg::Options::=--force-confold full-upgrade || { echo "upgrade: apt failed; rollback: sudo bash tools/sysupgrade.sh rollback"; exit 1; }
    echo "upgrade: done. Now: sudo reboot      (way back: sudo bash tools/sysupgrade.sh rollback)"
    ;;
rollback)
    need_root
    D=${2:-$(latest)}
    [ -d "$D/debs" ] && [ -s "$D/installed.txt" ] || { echo "no backup in '$D'"; exit 1; }
    echo "rollback: from $D ($(ls "$D/debs" | wc -l) packages)"
    apt-get install -y --allow-downgrades -o Dpkg::Options::=--force-confold "$D"/debs/*.deb \
        || { echo "rollback: apt failed — nothing else touched"; exit 1; }
    # kernels the upgrade brought: gone, so the boot hooks don't pick them again
    new=$(dpkg-query -W -f='${binary:Package}\n' 'linux-image-*' 'linux-headers-*' 2>/dev/null \
          | while read -r p; do grep -q "^$p=" "$D/installed.txt" || echo "$p"; done)
    [ -n "$new" ] && apt-get remove -y $new
    tar -C /boot/firmware --no-same-owner --no-same-permissions -xzf "$D/boot-firmware.tgz" \
        || { echo "rollback: /boot/firmware NOT restored"; exit 1; }
    echo "rollback: done. Now: sudo reboot"
    ;;
*)
    sed -n '2,8p' "$0"; exit 1
    ;;
esac
