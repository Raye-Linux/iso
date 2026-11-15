#!/bin/bash
#
# Checks the build-time kernel pin: that it exists, that it cannot write out a
# version, that it pins BEFORE it probes, and that it never ships.
#
#   tests/test_kernel_pin.sh                 the checks on build.sh
#   tests/test_kernel_pin.sh --root DIR      also: the pin is gone from an image
#   tests/test_kernel_pin.sh --self-test     show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why this exists, measured on 2026-11-06 at the cost of a 47-minute build.
#
# Ubuntu publishes linux-meta separately from linux, so the two can be out of
# step. That day resolute-updates offered
#
#     linux-generic-hwe-26.04          7.0.0-43.43
#     linux-image-generic-hwe-26.04    7.0.0-43.43
#
# while linux-modules-7.0.0-43-generic was ABSENT FROM THE WHOLE ARCHIVE and the
# complete 42.42 set sat in resolute-updates AND resolute-security. apt 3.x does
# not fall back to the older meta: it picks the newest, finds the dependency
# unsatisfiable, and prints "Reached two conflicting assignments" followed by
# forty lines of unrelated `Depends: ... but it is not going to be installed`.
# The image build died with the real cause -- one missing package -- buried.
#
# And the first fix did not work, for a reason worth pinning down:
#
#     apt-get install --simulate linux-generic-hwe-26.04=7.0.0-42.42   -> FAILS
#
# even though 42.42 is complete. Naming a version on the command line does not
# make apt choose a NON-CANDIDATE version for that package's DEPENDENCIES:
# linux-image-generic-hwe-26.04 (= 42.42) would be a downgrade from its own
# candidate 43.43, so apt reports it as "not selected for install". With the pin
# written FIRST, the same simulation passes. Probing without pinning reports
# every version as broken and makes a working archive look unusable -- which is
# why the order is a checked property below and not a comment.
#
# And the pin must NEVER reach the image. Left behind, it would freeze every
# future upgrade of that machine on an old kernel, and nothing in the image
# would say why.

set -uo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh
PIN_NAME=99raye-build-kernel

fail=0
err() { echo "FAIL: $*"; fail=1; }
ok()  { echo "ok:   $*"; }

# One function of a shell script as a single line. awk, not
# `sed -n '/^f() {/,/^}/p'`: a sed range cannot handle a function written on one
# line -- it runs to the next `}` in column 0 and swallows the function after it.
# Comment lines are DROPPED, and that is not tidiness. The first version of
# this file failed on a correct build.sh because `${body%%--simulate*}` cut at
# the first `--simulate` in the function -- which is inside the COMMENT that
# explains --simulate, above the code. The same trap is already written down in
# tests/test_build_memoire.sh, about a comment that EXPLAINS why -flto=auto is
# dangerous being read as a use of it. A check that cannot tell code from the
# prose about it will fire on the fix and stay quiet on the defect.
func_of() {
    awk -v want="$2" '
        $0 ~ "^"want"\\(\\) \\{" { dedans = 1; next }
        dedans && /^\}/ { exit }
        dedans {
            l = $0; sub(/^[ \t]+/, "", l)
            if (l ~ /^#/) next
            corps = corps " " l
        }
        END { print corps }
    ' "$1"
}

check_the_pin_is_removed_before_the_image_ships() {
    local body
    body=$(func_of "$1" clean_image)
    [ -n "$body" ] || { err "no clean_image() in $(basename "$1"): this test no longer bites on anything"; return; }
    case "$body" in
        *"rm -f"*KERNEL_PIN*) ok "clean_image removes the build-time kernel pin" ;;
        *"$PIN_NAME"*)        ok "clean_image removes $PIN_NAME" ;;
        *) err "clean_image does not remove the build-time kernel pin. Shipped, it freezes every future kernel upgrade of that machine, and nothing in the image says why" ;;
    esac
}

# The property that cost the build: the pin is written INSIDE the probe loop,
# before the simulation, not after a version has been chosen.
check_it_pins_before_it_probes() {
    local body before_simulate
    body=$(func_of "$1" pin_installable_kernel)
    [ -n "$body" ] || { err "no pin_installable_kernel() in $(basename "$1")"; return; }
    case "$body" in
        *--simulate*) ;;
        *) err "pin_installable_kernel does not simulate anything: it cannot know whether a version is installable"; return ;;
    esac
    before_simulate=${body%%--simulate*}
    case "$before_simulate" in
        *write_kernel_pin*) ok "the pin is written before the simulation" ;;
        *) err "pin_installable_kernel simulates WITHOUT writing the pin first. Measured: apt refuses a complete older version that way, because its dependencies would be downgrades from their own candidate -- every version then looks broken" ;;
    esac
}

check_the_priority_allows_a_downgrade() {
    local prio
    prio=$(sed -n 's/^Pin-Priority: *\([0-9]*\).*/\1/p' "$1" | head -1)
    [ -n "$prio" ] || { err "no Pin-Priority in $(basename "$1")"; return; }
    if [ "$prio" -gt 1000 ]; then
        ok "Pin-Priority $prio is above 1000, so a downgrade is allowed"
    else
        err "Pin-Priority is $prio: at 1000 or below apt will not DOWNGRADE to the pinned version, and choosing an older meta than the candidate is exactly a downgrade"
    fi
}

# A version written out here would outlive the archive problem and freeze
# every later image on an old kernel, in silence. The name of the meta comes from
# what raye-system depends on, the version from what apt can install.
check_no_kernel_version_is_written_out() {
    local hits
    hits=$(sed 's/#.*//' "$1" | grep -nE '[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.[0-9]+' | grep -i 'linux\|kernel\|pin')
    [ -z "$hits" ] && ok "no kernel version is written out in $(basename "$1")" ||
        err "a kernel version is written out in $(basename "$1") ($hits): it would outlive the archive problem and freeze later images on an old kernel"
}

check_an_image_carries_no_pin() {
    local root=$1 f hits
    f=$root/etc/apt/preferences.d/$PIN_NAME
    [ -e "$f" ] &&
        err "$f is in the image: it would freeze every future kernel upgrade of that machine" ||
        ok "no $PIN_NAME in the image"
    # broader: nothing anywhere may pin a linux-* package in a shipped image
    hits=$(grep -rlE '^Package:.*linux-' "$root/etc/apt/preferences.d" "$root/etc/apt/preferences" 2>/dev/null)
    [ -z "$hits" ] && ok "no apt preference in the image pins a linux-* package" ||
        err "an apt preference in the image pins a linux-* package ($hits)"
}

self_test() {
    local t ok_all=1
    t=$(mktemp -d)

    # 1. clean_image stops removing the pin
    awk '/^clean_image\(\) \{/,/^\}$/ { if ($0 ~ /KERNEL_PIN/) next } { print }' "$BUILD" > "$t/sans-rm.sh"
    (fail=0; check_the_pin_is_removed_before_the_image_ships "$t/sans-rm.sh"; exit $fail) >/dev/null &&
        { echo "self-test: pin non retire par clean_image non attrape"; ok_all=0; }

    # 2. the order is reversed: probe first, pin after -- the real mistake
    python3 - "$BUILD" "$t/ordre-inverse.sh" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
i = s.index("pin_installable_kernel() {")
j = s.index("\n}", i)
body = s[i:j]
# drop the write_kernel_pin call that precedes the simulation
body2 = re.sub(r"\n\s*write_kernel_pin \"\$meta\" \"\$v\"\n", "\n", body, count=1)
assert body2 != body, "injection ratee"
open(dst, "w").write(s[:i] + body2 + s[j:])
PY
    (fail=0; check_it_pins_before_it_probes "$t/ordre-inverse.sh"; exit $fail) >/dev/null &&
        { echo "self-test: sondage avant pin non attrape"; ok_all=0; }

    # 3. a priority that cannot downgrade
    sed 's/^Pin-Priority: 1001/Pin-Priority: 990/' "$BUILD" > "$t/prio-basse.sh"
    (fail=0; check_the_priority_allows_a_downgrade "$t/prio-basse.sh"; exit $fail) >/dev/null &&
        { echo "self-test: priorite trop basse non attrapee"; ok_all=0; }

    # 4. a version written out -- as CODE, not in a comment. The first
    #    injection put it in a trailing comment, which the check strips on
    #    purpose, so the self-test failed while the check was right.
    sed 's|^KERNEL_PIN=.*|KERNEL_PIN=etc/apt/preferences.d/99raye-build-kernel\nLINUX_FALLBACK=linux-generic-hwe-26.04=7.0.0-42.42|' \
        "$BUILD" > "$t/version-en-dur.sh"
    (fail=0; check_no_kernel_version_is_written_out "$t/version-en-dur.sh"; exit $fail) >/dev/null &&
        { echo "self-test: version en dur non attrapee"; ok_all=0; }

    # 5. an image that carries the pin
    mkdir -p "$t/image/etc/apt/preferences.d"
    printf 'Package: linux-generic-hwe-26.04\nPin: version 7.0.0-42.42\nPin-Priority: 1001\n' \
        > "$t/image/etc/apt/preferences.d/$PIN_NAME"
    (fail=0; check_an_image_carries_no_pin "$t/image"; exit $fail) >/dev/null &&
        { echo "self-test: pin livre dans l image non attrape"; ok_all=0; }

    rm -rf "$t"
    [ "$ok_all" = 1 ] && echo "self-test ok"
    [ "$ok_all" = 1 ]
}

root=""
while [ $# -gt 0 ]; do
    case $1 in
        --self-test) self_test; exit $? ;;
        --root) root=${2:?"--root needs a directory"}; shift ;;
        -h|--help) sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

check_the_pin_is_removed_before_the_image_ships "$BUILD"
check_it_pins_before_it_probes "$BUILD"
check_the_priority_allows_a_downgrade "$BUILD"
check_no_kernel_version_is_written_out "$BUILD"
if [ -n "$root" ]; then
    [ -d "$root" ] || { echo "no such directory: $root" >&2; exit 2; }
    check_an_image_carries_no_pin "$root"
else
    echo "note: no --root given, so the image itself was NOT checked for a leftover pin"
fi
echo
[ "$fail" = 0 ] && echo "ok: the kernel pin is derived, pins before it probes, and does not ship"
exit "$fail"
