#!/bin/bash
#
# Checks add_wine_debs() in build.sh: raye-wine ships in parts
# (raye-wine-i386, -mono, -gecko, -gecko-i386, -extras, -compat), and an
# image that takes the core without its parts cannot install it.
#  - every raye-wine* package of WINE_DEBS goes in;
#  - with the parts but no raye-wine itself, the build stops;
#  - with nothing at all, the build stops.
#
#   tests/test_wine_debs.sh              everything
#   tests/test_wine_debs.sh --self-test  show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh
fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok: $*"; }

V=11.21-1~raye4
PARTS="raye-wine_${V}_amd64.deb raye-wine-i386_${V}_amd64.deb
raye-wine-mono_${V}_amd64.deb raye-wine-gecko_${V}_amd64.deb
raye-wine-gecko-i386_${V}_amd64.deb raye-wine-extras_${V}_amd64.deb
raye-wine-compat_${V}_all.deb"

sandbox() {
    local box f
    box=$(mktemp -d "${TMPDIR:-/tmp}/raye-wine-debs-XXXXXX")
    mkdir -p "$box/debs" "$box/out"
    for f in "$@"; do : > "$box/out/$f"; done
    echo "$box"
}

# outcome from the exit status, then how many packages were taken
try() {
    local box=$1 build=$2
    (
        set -uo pipefail
        src=$box/src
        WINE_DEBS=$box/out
        die() { exit 1; }
        eval "$(sed -n '/^add_wine_debs()/,/^}/p' "$build")"
        if ( add_wine_debs "$box/debs" ) > /dev/null 2>&1; then
            echo "WENT ON"
        else
            echo "REFUSED"
        fi
        ls -1 "$box/debs" | wc -l
    )
}

cleanup() {
    case "$1" in
        */raye-wine-debs-*) rm -rf -- "$1" ;;
        *) echo "cleanup: refusing $1" >&2 ;;
    esac
}

check() {
    local build=$1 label=$2 box out
    # shellcheck disable=SC2086
    box=$(sandbox $PARTS)
    out=$(try "$box" "$build")
    [ "$(head -1 <<<"$out")" = "WENT ON" ] || err "$label: refuses a complete set"
    [ "$(tail -1 <<<"$out")" = 7 ] ||
        err "$label: took $(tail -1 <<<"$out") of the 7 raye-wine packages"
    cleanup "$box"

    # shellcheck disable=SC2086
    box=$(sandbox $(grep -v '^raye-wine_' <<<"$PARTS"))
    [ "$(try "$box" "$build" | head -1)" = REFUSED ] ||
        err "$label: goes on with the parts but without raye-wine"
    cleanup "$box"

    box=$(sandbox)
    [ "$(try "$box" "$build" | head -1)" = REFUSED ] ||
        err "$label: goes on with no raye-wine at all"
    cleanup "$box"
}

if [ "${1:-}" = --self-test ]; then
    echo "== self-test: the checks must fail on the build.sh that named two packages"
    broken=$(mktemp "${TMPDIR:-/tmp}/raye-build-XXXXXX.sh")
    sed 's|"\$WINE_DEBS"/raye-wine\*_\*\.deb|"$WINE_DEBS"/raye-wine_*.deb "$WINE_DEBS"/raye-wine-compat_*.deb|' \
        "$BUILD" > "$broken"
    fail=0
    check "$broken" "two-names"
    rm -f -- "$broken"
    if [ "$fail" -eq 1 ]; then
        echo "self-test: the checks do fail on bad input"
        exit 0
    fi
    echo "SELF-TEST FAILED: the checks passed a build.sh that leaves the parts out"
    exit 1
fi

check "$BUILD" "build.sh"
[ "$fail" -eq 0 ] && ok "every raye-wine part goes into the image, and the core is required"
exit "$fail"
