#!/bin/bash
#
# Checks that build.sh carries the caller's build options INTO the package
# chroot, and that nothing in the tree lets GCC choose its own LTO fan-out.
#
#   tests/test_build_memoire.sh               everything
#   tests/test_build_memoire.sh --self-test   show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why this file exists, measured on 2026-11-05.
#
# `build_compiled` runs dpkg-buildpackage through `chroot ... /usr/bin/env -i`.
# `env -i` WIPES the environment, so DEB_BUILD_OPTIONS never reached it: the
# job count the caller asked for had no effect at all on the six packages that
# actually have code to compile. Nothing said so -- no warning, no line in the
# log -- and builds kept succeeding for weeks because the machine had room.
#
# Then the build machine went to 28 cores (2026-11-03). `-flto=auto`, which Ubuntu's
# default CXXFLAGS carry, makes GCC read nproc and fan out that many ltrans
# processes PER LINK when it finds no jobserver. The next ISO build reached
# 51 compilers at once and 32060 MiB on a 32096 MiB VM with no swap; the
# kernel killed lto1 and the build failed. A build that had taken 44 minutes
# the day before now died, without one line of code changing.
#
# So two properties must hold, and neither is visible by reading a log:
#   1. every `env -i` that builds a package names DEB_BUILD_OPTIONS and the
#      DEB_*_APPEND flags, or the caller's bound is silently dropped;
#   2. nothing in the tree pins `-flto=auto`, which would override the
#      bounded `-flto=N` that dpkg-buildflags appends last.
#
# The lesson in one line: a setting that is passed but never arrives looks
# exactly like a setting that works, until the machine changes under it.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh
# the variables a bounded build needs on the other side of `env -i`
NEEDED="DEB_BUILD_OPTIONS DEB_CFLAGS_APPEND DEB_CXXFLAGS_APPEND DEB_LDFLAGS_APPEND"

fail=0
err() { echo "FAIL: $*"; fail=1; }
note() { echo "note: $*"; }

# Each function of a shell script, as "name<TAB>body-flattened-to-one-line".
# build.sh writes every function as `name() {` with its closing `}` in column 0.
#
# The FUNCTION is the unit, and the first version of this test got that
# wrong: it flattened only the backslash-continued lines of the `env -i`
# command. But build.sh ends that command with `PATH=... sh -ec "` -- no
# trailing backslash -- and dpkg-buildpackage sits INSIDE the quoted string on
# the lines below. So the check never saw it, skipped the command, and the test
# was green without verifying anything. Its own self-test is what caught that.
#
# And this is awk, not `sed -n '/^f() {/,/^}/p'`, because a sed range cannot
# handle a function written on one line: it would run to the next `}` in
# column 0 and swallow the function after it.
fonctions() {
    awk '
        /^[a-z_][a-z_0-9]*\(\) \{/ { nom = $0; sub(/\(\).*/, "", nom); corps = ""; dedans = 1; next }
        dedans && /^\}/ { printf "%s\t%s\n", nom, corps; dedans = 0; next }
        dedans { l = $0; sub(/^[ \t]+/, "", l); corps = corps " " l }
    ' "$1"
}

check_forwarding() {
    local script=$1 nom corps n missing vus=0
    while IFS=$'\t' read -r nom corps; do
        case "$corps" in *"env -i"*) ;; *) continue ;; esac
        case "$corps" in *dpkg-buildpackage*) ;; *) continue ;; esac
        vus=$((vus + 1))
        missing=""
        for n in $NEEDED; do
            grep -q -- "$n=" <<<"$corps" || missing="$missing $n"
        done
        [ -z "$missing" ] ||
            err "$nom() lance dpkg-buildpackage derriere \`env -i\` sans transmettre :$missing -- env -i les EFFACE, le bornage du lanceur est perdu en silence"
    done < <(fonctions "$script")
    [ "$vus" -gt 0 ] ||
        err "aucune fonction de $(basename "$script") ne lance dpkg-buildpackage derriere \`env -i\` : l'analyse de ce test ne mord plus sur rien"
}

check_pas_de_flto_auto() {
    local racine=${1:-$here} hits
    # Comments are stripped FIRST. The first version of this check fired on
    # the comment in build.sh that EXPLAINS why -flto=auto is dangerous: the
    # same trap as a check that cannot tell a comment claiming a feature from
    # one explaining its absence. Only real flag text counts.
    # Known limit, stated rather than hidden: a `#` inside a string is treated
    # as the start of a comment, so a -flto=auto written after one would be
    # missed. Nothing in this tree does that.
    hits=$(grep -rl --include='*.sh' --include='CMakeLists.txt' --include='rules' \
               --include='*.cmake' --include='*.mk' -- '-flto=auto' "$racine" 2>/dev/null |
           grep -v '/tests/' |
           while read -r f; do
               sed 's/#.*//' "$f" | grep -q -- '-flto=auto' && echo "$f"
           done)
    [ -z "$hits" ] ||
        err "-flto=auto est fixe dans le depot ($hits) : il ecraserait le -flto=N borne"
}

self_test() {
    local t ok=1
    t=$(mktemp -d)

    # 1. the defect as it really was: env -i without DEB_BUILD_OPTIONS
    sed '/DEB_BUILD_OPTIONS="\${DEB_BUILD_OPTIONS:-}"/d' "$BUILD" > "$t/sans-options.sh"
    grep -q 'DEB_BUILD_OPTIONS="\${DEB_BUILD_OPTIONS' "$t/sans-options.sh" &&
        { echo "self-test: injection ratee, DEB_BUILD_OPTIONS est encore transmis"; ok=0; }
    (fail=0; check_forwarding "$t/sans-options.sh"; exit $fail) >/dev/null &&
        { echo "self-test: env -i sans DEB_BUILD_OPTIONS non attrape"; ok=0; }

    # 2. the link flags dropped -- the ones that actually bound lto1
    sed '/DEB_LDFLAGS_APPEND="\${DEB_LDFLAGS_APPEND:-}"/d' "$BUILD" > "$t/sans-ldflags.sh"
    (fail=0; check_forwarding "$t/sans-ldflags.sh"; exit $fail) >/dev/null &&
        { echo "self-test: DEB_LDFLAGS_APPEND manquant non attrape"; ok=0; }

    # 3. a second chroot build added later, forwarding nothing
    {
        cat "$BUILD"
        printf '\nbuild_autre() {\n    chroot "$devroot" /usr/bin/env -i HOME=/root \\\n        PATH=/usr/bin sh -ec "dpkg-buildpackage -b -us -uc"\n}\n'
    } > "$t/deuxieme.sh"
    (fail=0; check_forwarding "$t/deuxieme.sh"; exit $fail) >/dev/null &&
        { echo "self-test: second env -i de build non attrape"; ok=0; }

    # 4. -flto=auto pinned in the tree
    mkdir -p "$t/arbre"
    printf 'set(CMAKE_CXX_FLAGS "%s")\n' '-flto=auto' > "$t/arbre/CMakeLists.txt"
    (fail=0; check_pas_de_flto_auto "$t/arbre"; exit $fail) >/dev/null &&
        { echo "self-test: -flto=auto fixe dans l arbre non attrape"; ok=0; }

    # 5. and the analysis must not go blind: a script with no env -i at all
    printf '#!/bin/sh\necho rien\n' > "$t/vide.sh"
    (fail=0; check_forwarding "$t/vide.sh"; exit $fail) >/dev/null &&
        { echo "self-test: script sans env -i non signale"; ok=0; }

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

check_forwarding "$BUILD"
check_pas_de_flto_auto
[ "$fail" = 0 ] && echo "ok: les options de build traversent env -i, et rien ne fixe -flto=auto"
exit "$fail"
