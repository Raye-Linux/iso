#!/bin/bash
#
# Checks the guard that keeps an image from shipping without the Raye
# desktop packages:
#  - build.sh says what DESKTOP_DEBS is for;
#  - desktop_debs_needed() answers from the theme tree, so the two stay in
#    step by themselves;
#  - add_desktop_debs() copies the +raye packages in, skips the debug ones,
#    and refuses to go on when they are missing and needed;
#  - the theme as it stands today needs them, which is what makes the guard
#    live rather than decorative.
#
#   tests/test_desktop_debs.sh              everything
#   tests/test_desktop_debs.sh --self-test  show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh
fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok: $*"; }

# the two functions, lifted out of build.sh so they can be exercised
functions_of() {
    sed -n '/^desktop_debs_needed()/,/^}/p;/^add_desktop_debs()/,/^}/p' "$1"
}

# a sandbox with a fake theme tree and a fake folder of built packages
# $1: "with-layout" or "no-layout"   $2..: package file names to create
sandbox() {
    local layout=$1; shift
    local box
    box=$(mktemp -d "${TMPDIR:-/tmp}/raye-desktop-debs-XXXXXX")
    mkdir -p "$box/src/theme/lookandfeel/org.raye.night.desktop/contents" "$box/debs" "$box/out"
    [ "$layout" = with-layout ] &&
        mkdir -p "$box/src/theme/lookandfeel/org.raye.night.desktop/contents/layouts"
    local f
    for f in "$@"; do
        : > "$box/out/$f"
    done
    echo "$box"
}

# runs the guard in the sandbox; prints the outcome, then how many packages
# were taken. The outcome comes from the exit status, not from what die
# prints: a check that reads a message is a check that a redirection can
# silence, which is how the first version of this test passed a guard that
# had refused nothing.
try() {
    local box=$1 src_file=$2 debs_dir=$3 pkgs=$4
    (
        set -uo pipefail
        src=$box/src
        DESKTOP_DEBS=$pkgs
        say() { :; }
        die() { exit 1; }
        eval "$(functions_of "$src_file")"
        # a nested subshell: die exits, and that must end the call rather
        # than this whole shell, which would print nothing at all
        if ( add_desktop_debs "$debs_dir" ) > /dev/null 2>&1; then
            echo "WENT ON"
        else
            echo "REFUSED"
        fi
        ls -1 "$debs_dir" | wc -l
    )
}

check() {
    local build=$1 label=$2 box out

    grep -q 'DESKTOP_DEBS=<folder>' "$build" ||
        err "$label: build.sh does not say what DESKTOP_DEBS is for"
    grep -q 'desktop_debs_needed' "$build" ||
        err "$label: no guard in build.sh"

    # 1. needed, and nothing to install: it must refuse
    box=$(sandbox no-layout)
    [ "$(try "$box" "$build" "$box/debs" "" | head -1)" = REFUSED ] ||
        err "$label: builds an image with no desktop packages and no layout"
    cleanup "$box"

    # 2. needed, and the packages are there: it must go on and take them
    box=$(sandbox no-layout \
        plasma-desktop_6.6.6-0ubuntu0.1+raye1_amd64.deb \
        plasma-desktop-data_6.6.6-0ubuntu0.1+raye1_all.deb)
    out=$(try "$box" "$build" "$box/debs" "$box/out")
    [ "$(head -1 <<<"$out")" = "WENT ON" ] ||
        err "$label: refuses although the desktop packages are there"
    [ "$(tail -1 <<<"$out")" = 2 ] ||
        err "$label: took $(tail -1 <<<"$out") package(s) instead of 2"
    cleanup "$box"

    # 3. the debug packages are not image material
    box=$(sandbox no-layout \
        plasma-desktop_6.6.6-0ubuntu0.1+raye1_amd64.deb \
        plasma-desktop-dbgsym_6.6.6-0ubuntu0.1+raye1_amd64.ddeb)
    [ "$(try "$box" "$build" "$box/debs" "$box/out" | tail -1)" = 1 ] ||
        err "$label: the debug package went into the image"
    cleanup "$box"

    # 4. a theme that still carries a layout does not need them
    box=$(sandbox with-layout)
    [ "$(try "$box" "$build" "$box/debs" "" | head -1)" = "WENT ON" ] ||
        err "$label: refuses although the look-and-feel still has a layout"
    cleanup "$box"
}

# only ever a folder this script made with mktemp -d
cleanup() {
    case "$1" in
        */raye-desktop-debs-*) rm -rf -- "$1" ;;
        *) echo "cleanup: refusing $1" >&2 ;;
    esac
}

if [ "${1:-}" = --self-test ]; then
    echo "== self-test: the checks must fail on a build.sh without the guard"
    broken=$(mktemp "${TMPDIR:-/tmp}/raye-build-XXXXXX.sh")
    # a build.sh that takes the packages when they are there but never refuses
    {
        sed -n '1,/^add_desktop_debs()/p' "$BUILD" | sed '$d'
        cat <<'BROKEN'
add_desktop_debs() {
    local debs=$1 deb found=0
    if [ -n "$DESKTOP_DEBS" ]; then
        for deb in "$DESKTOP_DEBS"/*+raye*.deb; do
            [ -e "$deb" ] || continue
            cp "$deb" "$debs/"
            found=$((found + 1))
        done
    fi
}
BROKEN
    } > "$broken"
    fail=0
    check "$broken" "no-guard"
    rm -f -- "$broken"
    if [ "$fail" -eq 1 ]; then
        echo "self-test: the checks do fail on bad input"
        exit 0
    fi
    echo "SELF-TEST FAILED: the checks passed a build.sh with no guard"
    exit 1
fi

check "$BUILD" "build.sh"
[ "$fail" -eq 0 ] && ok "the desktop packages cannot be left out of an image that needs them"

# the guard is only worth anything if it is live today
if ls -d "$here/../theme/lookandfeel/"*/contents/layouts > /dev/null 2>&1; then
    echo "note: the theme still ships a look-and-feel layout, so the guard is dormant"
else
    ok "the theme ships no look-and-feel layout, so the guard is live"
fi

exit "$fail"
