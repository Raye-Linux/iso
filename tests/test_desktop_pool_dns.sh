#!/bin/bash
#
# Checks that build.sh gives the image a working resolver before it fetches
# Hyprland for Setup's offline desktop pool.
#
#   tests/test_desktop_pool_dns.sh               everything
#   tests/test_desktop_pool_dns.sh --self-test   show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why, measured on 2026-11-20: the first Beta 2 image build stopped at
# "Gathering the Hyprland desktop for Setup" with "Temporary failure
# resolving 'archive.ubuntu.com'" for every package. mmdebstrap copies the
# host's resolv.conf into the image, but once systemd-resolved is installed
# /etc/resolv.conf is a link to /run/systemd/resolve/stub-resolv.conf, and
# /run is an empty tmpfs in the chroot (no resolved runs there). The packages
# came from the local repo or were already fetched; the pool step is the
# first apt download after that point. Without an apt proxy it can never work.
#
# So gather_desktop_pool must put the build machine's resolver where the
# link points, inside the chroot's /run (a tmpfs: it goes away with the
# mounts and never reaches the image), before it runs apt.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh

fail=0
err() { echo "FAIL: $*"; fail=1; }

corps_de() {
    awk -v f="$2" '
        $0 ~ "^" f "\\(\\) \\{" { dedans = 1; next }
        dedans && /^\}/ { exit }
        dedans { l = $0; sub(/^[ \t]*#.*/, "", l); sub(/[ \t]+#.*$/, "", l); print l }
    ' "$1"
}

check_dns() {
    local script=$1 corps dns apt
    corps=$(corps_de "$script" gather_desktop_pool)
    if [ -z "$corps" ]; then
        err "no gather_desktop_pool() in $(basename "$script"): this test no longer checks anything"
        return
    fi
    dns=$(grep -n 'cp -L /etc/resolv.conf "\$root/run/systemd/resolve/stub-resolv.conf"' <<<"$corps" | head -1 | cut -d: -f1)
    apt=$(grep -n 'in_root apt-get' <<<"$corps" | head -1 | cut -d: -f1)
    [ -n "$apt" ] || { err "gather_desktop_pool() runs no apt-get: the check does not know where to look"; return; }
    [ -n "$dns" ] ||
        err "gather_desktop_pool() gives the chroot no resolver: apt cannot resolve the Ubuntu mirrors there"
    [ -n "$dns" ] && [ "$dns" -lt "$apt" ] ||
        { [ -n "$dns" ] && err "the resolver is put in place after apt-get runs"; }
    grep -q 'mkdir -p "\$root/run/systemd/resolve"' <<<"$corps" ||
        err "gather_desktop_pool() does not make \$root/run/systemd/resolve: the copy has nowhere to go"
    # the call must happen while the chroot's /run is mounted, so the file
    # dies with the tmpfs and never ends up in the image
    grep -Eq 'mount_chroot;.*gather_desktop_pool;.*umount_chroot' "$script" ||
        err "gather_desktop_pool is not called between mount_chroot and umount_chroot"
}

self_test() {
    local t ok=1
    t=$(mktemp -d)
    # 1. the defect as it was
    sed '/cp -L \/etc\/resolv.conf "\$root\/run/d' "$BUILD" > "$t/sans.sh"
    cmp -s "$BUILD" "$t/sans.sh" && { echo "self-test: injection missed"; ok=0; }
    (fail=0; check_dns "$t/sans.sh"; exit $fail) >/dev/null &&
        { echo "self-test: no resolver not caught"; ok=0; }
    # 2. the copy only in a comment
    sed 's/^\( *\)\(cp -L \/etc\/resolv.conf "\$root\/run\)/\1# \2/' "$BUILD" > "$t/comment.sh"
    (fail=0; check_dns "$t/comment.sh"; exit $fail) >/dev/null &&
        { echo "self-test: resolver only in a comment not caught"; ok=0; }
    # 3. called outside the mounts
    sed 's/mount_chroot; check_image; gather_desktop_pool; umount_chroot/mount_chroot; check_image; umount_chroot; gather_desktop_pool/' "$BUILD" > "$t/dehors.sh"
    (fail=0; check_dns "$t/dehors.sh"; exit $fail) >/dev/null &&
        { echo "self-test: call outside the mounts not caught"; ok=0; }
    # 4. no function at all
    printf '#!/bin/sh\necho nothing\n' > "$t/vide.sh"
    (fail=0; check_dns "$t/vide.sh"; exit $fail) >/dev/null &&
        { echo "self-test: script without gather_desktop_pool not flagged"; ok=0; }
    rm -rf "$t"
    [ "$ok" = 1 ] && echo "self-test ok"
    [ "$ok" = 1 ]
}

while [ $# -gt 0 ]; do
    case $1 in
        --self-test) self_test; exit $? ;;
        *) echo "usage: $0 [--self-test]" >&2; exit 2 ;;
    esac
done

check_dns "$BUILD"
[ "$fail" = 0 ] && echo "ok: the desktop pool step has a resolver"
exit "$fail"
