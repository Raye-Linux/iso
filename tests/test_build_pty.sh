#!/bin/bash
#
# Checks that build.sh gives the resolute build tree a terminal device of its
# own while a package builds, and takes it away on every way out.
#
#   tests/test_build_pty.sh               everything
#   tests/test_build_pty.sh --self-test   show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why, measured on 2026-11-08. raye-settings tests its password page by
# driving a stand-in for passwd on a pty. build_compiled mounted only proc in
# the tree mmdebstrap made, and that tree's dev/pts is an empty folder: in it
# forkpty() fails with "out of pty devices". Three tests went red in the image
# build while the same commit passed in the agents' chroot, which has /dev/pts,
# and the image could not be made.
#
# So build_compiled must mount a devpts instance on "$devroot/dev/pts" --
# newinstance, never the host's ptys -- and unmount it everywhere it unmounts
# proc. A mount left behind is worse than none: nothing_mounted_under refuses
# to clean the tree after that, and the next build stops there.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh

fail=0
err() { echo "FAIL: $*"; fail=1; }

# The body of one function of a shell script, comments stripped, one line per
# line. build.sh writes every function as `name() {` with `}` in column 0.
# Comments go FIRST: build_compiled explains the pty in a comment, and a
# check that read it would pass on a script whose mount line is gone.
corps_de() {
    awk -v f="$2" '
        $0 ~ "^" f "\\(\\) \\{" { dedans = 1; next }
        dedans && /^\}/ { exit }
        dedans { l = $0; sub(/^[ \t]*#.*/, "", l); sub(/[ \t]+#.*$/, "", l); print l }
    ' "$1"
}

check_pty() {
    local script=$1 corps procs ptys
    corps=$(corps_de "$script" build_compiled)
    if [ -z "$corps" ]; then
        err "pas de build_compiled() dans $(basename "$script") : ce test ne mord plus sur rien"
        return
    fi
    grep -Eq 'mount -t devpts .*newinstance.* "\$devroot/dev/pts"' <<<"$corps" ||
        err "build_compiled() ne monte pas de devpts neuf (newinstance) sur \$devroot/dev/pts : forkpty() echoue dans l arbre de construction"
    procs=$(grep -o 'umount "$devroot/proc"' <<<"$corps" | wc -l)
    ptys=$(grep -o 'umount "$devroot/dev/pts"' <<<"$corps" | wc -l)
    [ "$procs" -gt 0 ] ||
        err "build_compiled() ne demonte plus proc : l analyse de ce test ne sait plus ou chercher"
    [ "$ptys" = "$procs" ] ||
        err "build_compiled() demonte proc $procs fois et dev/pts $ptys fois : une sortie laisse dev/pts monte"
}

self_test() {
    local t ok=1
    t=$(mktemp -d)

    # 1. the defect as it was: no devpts at all
    sed '/mount -t devpts/d' "$BUILD" > "$t/sans-devpts.sh"
    grep -q 'mount -t devpts' "$t/sans-devpts.sh" &&
        { echo "self-test: injection ratee, le montage devpts est encore la"; ok=0; }
    (fail=0; check_pty "$t/sans-devpts.sh"; exit $fail) >/dev/null &&
        { echo "self-test: arbre sans devpts non attrape"; ok=0; }

    # 2. a devpts that is the host's: no newinstance
    sed 's/-o newinstance,/-o /' "$BUILD" > "$t/partage.sh"
    (fail=0; check_pty "$t/partage.sh"; exit $fail) >/dev/null &&
        { echo "self-test: devpts sans newinstance non attrape"; ok=0; }

    # 3. the failure path forgets dev/pts
    sed 's/|| { umount "\$devroot\/dev\/pts"; /|| { /' "$BUILD" > "$t/fuite.sh"
    cmp -s "$BUILD" "$t/fuite.sh" &&
        { echo "self-test: injection ratee, la sortie en erreur demonte encore dev/pts"; ok=0; }
    (fail=0; check_pty "$t/fuite.sh"; exit $fail) >/dev/null &&
        { echo "self-test: dev/pts laisse monte en cas d echec non attrape"; ok=0; }

    # 4. the mount only in a comment
    sed 's/^\( *\)\(mount -t devpts\)/\1# \2/' "$BUILD" > "$t/commente.sh"
    (fail=0; check_pty "$t/commente.sh"; exit $fail) >/dev/null &&
        { echo "self-test: montage seulement en commentaire non attrape"; ok=0; }

    # 5. no build_compiled at all: the check must say it went blind
    printf '#!/bin/sh\necho rien\n' > "$t/vide.sh"
    (fail=0; check_pty "$t/vide.sh"; exit $fail) >/dev/null &&
        { echo "self-test: script sans build_compiled non signale"; ok=0; }

    rm -rf "$t"
    [ "$ok" = 1 ] && echo "self-test ok"
    [ "$ok" = 1 ]
}

while [ $# -gt 0 ]; do
    case $1 in
        --self-test) self_test; exit $? ;;
        *) sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    esac
    shift
done

check_pty "$BUILD"
[ "$fail" = 0 ] && echo "ok: l arbre de construction a son propre devpts, demonte a chaque sortie"
exit "$fail"
