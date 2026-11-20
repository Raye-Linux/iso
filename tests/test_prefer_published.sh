#!/bin/bash
#
# Checks that build.sh puts the published file of a package in the image
# when the build made the same package at the same version.
#
#   tests/test_prefer_published.sh               everything
#   tests/test_prefer_published.sh --self-test   show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why, seen on 2026-11-20 (1.0 Beta Sundog, VM 130): every image build makes
# raye-account, raye-archive and raye-scx again, at a version that did not
# move, and the new build is never the same file as the published one. apt
# then knows two packages under one version: the first "Check for updates"
# of a fresh install offered "raye-account 0.5.4~beta1 -> 0.5.4~beta1" and
# "raye-scx 1.1.4-1 -> 1.1.4-1", with a restart. publish-repo refuses to
# publish the image's builds (same version, other contents), so the image
# must take the published files.

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

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# deb <dir> <name> <version> <words>: a small package, its file content set by <words>
deb() {
    local dir=$1 name=$2 version=$3 words=$4 t
    t=$(mktemp -d "$work/pkg.XXXX")
    mkdir -p "$t/DEBIAN" "$t/usr/share/$name"
    printf 'Package: %s\nVersion: %s\nArchitecture: all\nMaintainer: t <t@t>\nDescription: t\n' \
        "$name" "$version" > "$t/DEBIAN/control"
    echo "$words" > "$t/usr/share/$name/what"
    dpkg-deb --root-owner-group -Zgzip --build "$t" "$dir/${name}_${version}_all.deb" > /dev/null
}

check() {
    local script=$1 corps call scan
    corps=$(corps_de "$script" prefer_published)
    if [ -z "$corps" ]; then
        err "no prefer_published() in $(basename "$script"): this test no longer checks anything"
        return
    fi
    call=$(corps_de "$script" build_packages | grep -n 'prefer_published "\$debs"' | head -1 | cut -d: -f1)
    scan=$(corps_de "$script" build_packages | grep -n 'dpkg-scanpackages' | head -1 | cut -d: -f1)
    [ -n "$call" ] || err "build_packages() never calls prefer_published: the image keeps its own builds"
    [ -n "$call" ] && [ -n "$scan" ] && [ "$call" -gt "$scan" ] &&
        err "prefer_published runs after the image's package list is written"

    rm -rf "$work/built" "$work/pub"; mkdir -p "$work/built" "$work/pub"
    deb "$work/built" raye-account 0.5.4~beta1 "image build"
    deb "$work/pub"   raye-account 0.5.4~beta1 "published build"
    deb "$work/built" raye-store 1.0~beta2 "new"
    deb "$work/pub"   raye-store 1.0~beta1 "old"
    deb "$work/built" raye-scx 1.1.4-1 "same"
    cp "$work/built/raye-scx_1.1.4-1_all.deb" "$work/pub/"
    local fn
    fn=$(printf 'prefer_published() {\n%s\n}\n' "$corps")
    (
        eval "$fn"
        PUBLISHED_DEBS=$work/pub
        prefer_published "$work/built" > "$work/out.log"
    ) || err "prefer_published failed"
    cmp -s "$work/built/raye-account_0.5.4~beta1_all.deb" "$work/pub/raye-account_0.5.4~beta1_all.deb" ||
        err "a package published at the same version keeps the image's build"
    dpkg-deb --fsys-tarfile "$work/built/raye-store_1.0~beta2_all.deb" | tar -xO ./usr/share/raye-store/what |
        grep -qx new || err "a newer build was replaced by an older published file"
    grep -q 'raye-account' "$work/out.log" || err "the build log does not name the package taken from the archive"
    grep -q 'raye-scx' "$work/out.log" && err "an identical file is reported as replaced"

    rm -rf "$work/built"; mkdir -p "$work/built"
    deb "$work/built" raye-account 0.5.4~beta1 "image build"
    (
        eval "$fn"
        PUBLISHED_DEBS=
        prefer_published "$work/built" > /dev/null
    ) || err "prefer_published fails when no archive is given"
    dpkg-deb --fsys-tarfile "$work/built/raye-account_0.5.4~beta1_all.deb" | tar -xO ./usr/share/raye-account/what |
        grep -qx "image build" || err "without PUBLISHED_DEBS the build's own file must stay"
}

if [ "${1:-}" = --self-test ]; then
    bad=$work/build-bad.sh
    # the step left out of build_packages, and a function that does nothing
    sed -e '/^    prefer_published "\$debs"$/d' \
        -e '/^prefer_published() {$/,/^}$/c\prefer_published() {\n    return 0\n}' "$BUILD" > "$bad"
    out=$(fail=0; check "$bad"; echo "rc=$fail")
    n=$(grep -c '^FAIL' <<<"$out")
    if grep -q 'rc=1' <<<"$out" && [ "$n" -ge 3 ]; then
        echo "self-test ok: $n failures on the broken build.sh"
        exit 0
    fi
    echo "self-test FAILED: the broken build.sh was not caught"; echo "$out"
    exit 1
fi

check "$BUILD"
[ "$fail" = 0 ] && echo "ok: prefer_published" 
exit "$fail"
