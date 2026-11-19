#!/bin/bash
#
# Checks config/ubuntu.sources, the apt sources every Raye machine gets:
#  - the binary groups and the source groups name the SAME suites,
#    components and servers, so a pocket added to one cannot be forgotten
#    in the other;
#  - the source groups stay off, because a Raye machine would otherwise
#    fetch 18 MiB of source indexes it has no use for;
#  - no binary group is ever disabled;
#  - the suites are the ones build.sh builds from, resolute-updates
#    included -- the desktop build needs that pocket;
#  - and, given an image, the image's own apt is asked what it would
#    really fetch, with the groups off and then on.
#
#   tests/test_apt_sources.sh               the file, then an image if given
#   tests/test_apt_sources.sh --root DIR    ask the apt of the image tree DIR
#   tests/test_apt_sources.sh --sources F   read F instead of the repo's file
#   tests/test_apt_sources.sh --self-test   show that each check fails on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# ---------------------------------------------------------------------
# Measured on 2026-11-05, so nobody walks this road twice.
#
# WHY THE SOURCE GROUPS EXIST. Raye's own packages of the desktop are
# built by running "apt-get source" inside a Raye system, and the version
# the patch series is written against is not in the release pocket.
# Against the archive itself:
#
#     resolute/universe          plasma-workspace  4:6.6.4-0ubuntu2
#     resolute-updates/universe  plasma-workspace  4:6.6.6-0ubuntu0.1
#
# Without deb-src on resolute-updates the build unpacks 6.6.4 and stops.
#
# WHY THEY ARE OFF. The source indexes of the four suites and four
# components come to 18 MiB compressed, 16 of them resolute/universe
# alone (measured with HEAD requests on archive.ubuntu.com). Every Raye
# machine would pay that on every "apt update" for a developer's need.
# Ubuntu's own ubuntu.sources ships deb-src off for the same reason. So
# the groups are written out, correct and complete, and disabled; one
# sed turns them on where a build happens.
#
# WHICH APT. This VM and the ISO build chroot are Debian 13 trixie with
# apt 3.0.x; the image is ID=raye/resolute with apt 3.2.1. Whether
# "Enabled: no" is honoured is a property of a given apt, so the image
# side only rules when the tree really is a Raye image, and says which
# tree it found otherwise.
#
# MEASURED, so the python-apt test next door does not break: python-apt
# reports an "Enabled: no" group as disabled, and
# tests/test_apt_template.sh skips disabled entries. The deb-src groups
# are described by Raye's own template (raye/resolute, raye/resolute-
# updates, ...), not by ubuntu.info's.
# ---------------------------------------------------------------------
#
# Note: usage() prints lines 3-20 of this file. Keep that block that
# length, or move the range.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
SOURCES=$here/config/ubuntu.sources
BUILD=$here/build.sh
ROOT=
MODE=check

fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok: $*"; }
note() { echo "note: $*"; }

IMAGE_AUTHORITY=0
IMAGE_WEAK=0
TMPS=()
# shellcheck disable=SC2329  # run by the EXIT trap
cleanup() { local d; for d in "${TMPS[@]}"; do rm -rf -- "$d"; done; }
trap cleanup EXIT

# A finding that rests on an image's apt. Only Raye's own apt can say
# what Raye's apt does.
image_err() {
    if [ "$IMAGE_AUTHORITY" = 1 ]; then err "$*"; else
        note "not a Raye image, so not a failure: $*"
    fi
}

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT=${2:?--root needs a directory}; shift 2 ;;
        --sources) SOURCES=${2:?--sources needs a file}; shift 2 ;;
        --build) BUILD=${2:?--build needs a file}; shift 2 ;;
        --self-test) MODE=self; shift ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
done

os_field() {
    sed -n "s/^$2=[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}\$/\1/p" "$1" 2>/dev/null | head -n1
}

target_suite() {
    [ -f "$BUILD" ] || return 0
    sed 's/#.*//' "$BUILD" |
        sed -n 's/^[[:space:]]*SUITE=[\"'"'"']\{0,1\}\([A-Za-z0-9._-]\{1,\}\).*/\1/p' |
        head -n1
}

# One line per group of the file: "<types>|<uris>|<suites>|<components>|
# <signed-by>|<enabled>". Comment lines are DELETED first, never blanked:
# apt strips them and keeps the stanza, so blanking one would split a
# group in two here and report both halves as incomplete. The first
# version of this function did exactly that, and its own self-test case
# caught it.
groups() {
    sed '/^[[:space:]]*#/d' "$1" | awk '
        function flush() {
            if (seen)
                printf "%s|%s|%s|%s|%s|%s\n", t, u, s, c, k, (e == "" ? "-" : e)
            t = u = s = c = k = e = ""; seen = 0
        }
        /^[[:space:]]*$/ { flush(); next }
        /^[A-Za-z-]+:/ {
            field = $1; sub(/:$/, "", field)
            value = $0; sub(/^[A-Za-z-]+:[[:space:]]*/, "", value)
            seen = 1
            if (field == "Types") t = value
            else if (field == "URIs") u = value
            else if (field == "Suites") s = value
            else if (field == "Components") c = value
            else if (field == "Signed-By") k = value
            else if (field == "Enabled") e = value
        }
        END { flush() }'
}

field() { cut -d'|' -f"$2" <<< "$1"; }

# ------------------------------------------------------------- the file

check_file() {
    [ -f "$SOURCES" ] || { err "no $SOURCES"; return; }
    local -a all=()
    mapfile -t all < <(groups "$SOURCES")
    [ "${#all[@]}" -gt 0 ] || { err "$SOURCES has no group at all"; return; }

    local g types uris suites comps key enabled
    local -A bin=() src=()
    local complete=1 off=1 on=1

    for g in "${all[@]}"; do
        types=$(field "$g" 1); uris=$(field "$g" 2); suites=$(field "$g" 3)
        comps=$(field "$g" 4); key=$(field "$g" 5); enabled=$(field "$g" 6)
        if [ -z "$types" ] || [ -z "$uris" ] || [ -z "$suites" ] ||
           [ -z "$comps" ] || [ -z "$key" ]; then
            err "a group of $(basename "$SOURCES") is incomplete: [$g]"
            complete=0
            continue
        fi
        case "$types" in
            deb)
                bin["$uris|$suites|$comps"]=$key
                [ "$enabled" = - ] ||
                    { err "the binary group of $uris carries Enabled: $enabled;" \
                          "a machine with no packages is not a machine"; on=0; } ;;
            deb-src)
                src["$uris|$suites|$comps"]=$key
                [ "$enabled" = no ] ||
                    { err "the source group of $uris is Enabled: $enabled; every Raye" \
                          "machine would then fetch 18 MiB of source indexes it has no" \
                          "use for"; off=0; } ;;
            *) err "a group has Types: $types; this file carries deb and deb-src only" ;;
        esac
    done
    [ "$complete" = 1 ] && ok "every group names its types, servers, suites, components and key"
    [ "$on" = 1 ] && ok "no binary group is disabled"
    [ "$off" = 1 ] && [ "${#src[@]}" -gt 0 ] && ok "the source groups are off, so nobody pays for them"

    # the two halves must describe the same archive
    local k paired=1
    for k in "${!bin[@]}"; do
        if [ -z "${src[$k]+x}" ]; then
            err "no deb-src group for [${k//|/ }]: apt-get source would not find it, and" \
                "the two halves of this file have drifted"
            paired=0
        elif [ "${src[$k]}" != "${bin[$k]}" ]; then
            err "[${k//|/ }] is signed by ${bin[$k]} for packages and ${src[$k]} for sources"
            paired=0
        fi
    done
    for k in "${!src[@]}"; do
        [ -n "${bin[$k]+x}" ] ||
            { err "a deb-src group has no deb group: [${k//|/ }]"; paired=0; }
    done
    [ "$paired" = 1 ] && [ "${#bin[@]}" -gt 0 ] &&
        ok "${#bin[@]} binary group(s) and ${#src[@]} source group(s), naming the same archive"

    # every server comes from a mirror list that the image really holds:
    # one dead address must not stop an update (2026-11-09, 91.189.90.12)
    local u lists=1
    for k in "${!bin[@]}"; do
        u=${k%%|*}
        case "$u" in
            mirror+file:/etc/apt/mirrors/ubuntu.list|mirror+file:/etc/apt/mirrors/ubuntu-security.list)
                err "$u is raye-system's conffile: the country mirror is written into" \
                    "the *-nearby list next to it, which is what the sources must read"
                lists=0 ;;
            mirror+file:/etc/apt/mirrors/*.list)
                grep -qF "\$root${u#mirror+file:}\"" "$BUILD" ||
                    { err "$u is not put in the image by $(basename "$BUILD"): apt" \
                          "would find no server at all"; lists=0; } ;;
            *) err "$u is a single server; when it stops answering every update" \
                   "fails, so it goes through mirror+file:/etc/apt/mirrors/"; lists=0 ;;
        esac
    done
    [ "$lists" = 1 ] && [ "${#bin[@]}" -gt 0 ] &&
        ok "every group reads its servers from a mirror list the image holds"

    # the suites are the ones Raye is built from, and the pocket the
    # desktop build needs is among them
    local suite all_suites
    suite=$(target_suite)
    all_suites=$(printf '%s\n' "${!bin[@]}" | cut -d'|' -f2 | tr ' ' '\n' | sort -u | tr '\n' ' ')
    if [ -n "$suite" ]; then
        if grep -qw "$suite" <<< "$all_suites"; then
            ok "the suites are $suite's: $all_suites"
        else
            err "build.sh builds from '$suite' and the sources name [$all_suites]"
        fi
        if grep -qw "$suite-updates" <<< "$all_suites"; then
            ok "$suite-updates is there, which is where the desktop sources live"
        else
            err "$suite-updates is missing: the desktop build would unpack the release" \
                "pocket's older version and refuse to go on"
        fi
    fi
}

# ------------------------------------------------------------ the image

check_image() {
    local root=$1 id code suite box n_off n_on pockets
    id=$(os_field "$root/etc/os-release" ID)
    code=$(os_field "$root/etc/os-release" VERSION_CODENAME)
    suite=$(target_suite)
    if [ "$id" = raye ] && { [ -z "$suite" ] || [ "$code" = "$suite" ]; }; then
        IMAGE_AUTHORITY=1
        echo "image: $root (ID=$id, $code)"
    else
        IMAGE_AUTHORITY=0; IMAGE_WEAK=1
        note "this tree says ID=${id:-nothing}, codename=${code:-nothing}; a Raye image is" \
             "ID=raye built from ${suite:-the suite named in build.sh}. Its apt is another" \
             "apt, so what it reports here is a warning, never a failure."
    fi
    [ -x "$root/usr/bin/apt-get" ] || { image_err "$root has no apt-get"; return; }
    if [ "$(id -u)" != 0 ]; then
        note "not root, so the image's own apt was not asked (that needs chroot); this" \
             "machine's apt is another version and would not be evidence about Raye."
        return
    fi

    # Ask the image's apt what it would fetch, from a folder of our own:
    # the image's real /etc/apt is never touched.
    box=$(mktemp -d "$root/tmp/apt-sources-test.XXXXXX"); TMPS+=("$box")
    cp "$SOURCES" "$box/ubuntu.sources"
    local inner=/tmp/$(basename "$box")
    src_targets() {
        chroot "$root" /usr/bin/apt-get -o "Dir::Etc::sourceparts=$inner" \
            -o Dir::Etc::sourcelist=/dev/null indextargets --no-release-info 2>/dev/null |
            awk '/^URI: .*\/source\/Sources$/{print $2}' |
            sed 's|.*/dists/||; s|/source/Sources$||'
    }

    n_off=$(src_targets | grep -c . )
    if [ "$n_off" = 0 ]; then
        ok "as shipped, the image's apt has no source index to fetch at all"
    else
        image_err "as shipped, the image's apt would fetch $n_off source index(es);" \
                  "every machine would pay for them"
    fi

    sed -i 's/^Enabled: no$/Enabled: yes/' "$box/ubuntu.sources"
    pockets=$(src_targets | sort)
    n_on=$(grep -c . <<< "$pockets")
    if [ "$n_on" -gt 0 ]; then
        ok "turned on, it fetches $n_on source index(es)"
    else
        image_err "turned on, the image's apt still has nothing to fetch: the source" \
                  "groups are written in a way its apt does not read"
    fi
    local want=${suite:-$code}-updates
    if grep -q "^$want/" <<< "$pockets"; then
        ok "among them $(grep -c "^$want/" <<< "$pockets") of $want, where the desktop sources live"
    else
        image_err "turned on, nothing of $want: apt-get source would still unpack the" \
                  "release pocket's older version"
    fi
}

# ------------------------------------------------------------ self-test

good_file() {
    cat > "$1" <<'EOF'
Types: deb
URIs: mirror+file:/etc/apt/mirrors/ubuntu-nearby.list
Suites: resolute resolute-updates resolute-backports
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

# a comment between groups, and one naming Enabled: yes in prose
Types: deb-src
URIs: mirror+file:/etc/apt/mirrors/ubuntu-nearby.list
Suites: resolute resolute-updates resolute-backports
Components: main universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Enabled: no
EOF
}

self_test() {
    local t bad=0 out n=0
    t=$(mktemp -d); TMPS+=("$t")
    printf 'SUITE=resolute\ninstall -D x "$root/etc/apt/mirrors/ubuntu-nearby.list"\n' > "$t/build.sh"

    run() { "$0" --sources "$1" --build "$t/build.sh" 2>&1; }

    good_file "$t/good"
    out=$(run "$t/good")
    if grep -q '^FAIL:' <<< "$out"; then
        echo "FAIL a file that holds is already red:"; printf '  %s\n' "$out"; bad=1
    else
        echo "ok   a file that holds passes"
    fi

    case_breaks() {
        local label=$1 want=$2 edit=$3
        n=$((n + 1))
        good_file "$t/bad$n"
        eval "$edit"
        out=$(run "$t/bad$n")
        if grep -q '^FAIL:' <<< "$out" && grep -qF -- "$want" <<< "$out"; then
            echo "ok   $label"
        else
            echo "FAIL $label did not go red naming [$want]:"; printf '  %s\n' "$out"; bad=1
        fi
    }

    case_breaks "source groups left on are caught" "18 MiB" \
        'sed -i "s/^Enabled: no$/Enabled: yes/" "$t/bad$n"'
    case_breaks "a missing deb-src group is caught" "apt-get source would not find it" \
        'sed -i "/^Types: deb-src$/,\$d" "$t/bad$n"'
    case_breaks "a binary group turned off is caught" "is not a machine" \
        'sed -i "0,/^Signed-By/s/^\(Signed-By.*\)$/\1\nEnabled: no/" "$t/bad$n"'
    case_breaks "a pocket in one half only is caught" "have drifted" \
        'sed -i "0,/^Suites:/s/ resolute-backports$//" "$t/bad$n"'
    case_breaks "resolute-updates missing from both is caught" "refuse to go on" \
        'sed -i "s/ resolute-updates//g" "$t/bad$n"'
    case_breaks "two different keys are caught" "for sources" \
        'awk "/^Signed-By:/ { k++; if (k == 2) { print \"Signed-By: /other.gpg\"; next } } { print }" \
             "$t/bad$n" > "$t/bad$n.x" && mv "$t/bad$n.x" "$t/bad$n"'
    case_breaks "an incomplete group is caught" "is incomplete" \
        'sed -i "/^Components: main universe$/d" "$t/bad$n"'
    case_breaks "a single server is caught" "is a single server" \
        'sed -i "s#mirror+file:/etc/apt/mirrors/ubuntu-nearby.list#http://archive.ubuntu.com/ubuntu#" "$t/bad$n"'
    case_breaks "the conffile list read directly is caught" "the country mirror" \
        'sed -i "s#/ubuntu-nearby.list#/ubuntu.list#" "$t/bad$n"'
    case_breaks "a list the image lacks is caught" "is not put in the image" \
        'sed -i "s#/ubuntu-nearby.list#/other.list#" "$t/bad$n"'
    case_breaks "an unknown Types is caught" "deb and deb-src only" \
        'sed -i "s/^Types: deb\$/Types: deb-foo/" "$t/bad$n"'

    # a comment must not end a group nor be read as a field
    good_file "$t/cmt"
    sed -i '2i # URIs: http://wrong.invalid/x' "$t/cmt"
    out=$(run "$t/cmt")
    if grep -q '^FAIL:' <<< "$out"; then
        echo "FAIL a comment inside a group was read as a field:"; printf '  %s\n' "$out"; bad=1
    else
        echo "ok   a comment inside a group is neither a field nor a group break"
    fi

    # the archive rule
    local kept=$IMAGE_AUTHORITY out_w out_f
    IMAGE_AUTHORITY=0
    out_w=$(image_err "x"); fail=0; image_err "x" >/dev/null
    if [ "$fail" = 0 ] && grep -q '^note:' <<< "$out_w"; then
        echo "ok   a finding from another apt is a note, not a failure"
    else
        echo "FAIL image_err failed off a Raye image"; bad=1
    fi
    IMAGE_AUTHORITY=1
    out_f=$(image_err "x"); fail=0; image_err "x" >/dev/null
    if [ "$fail" = 1 ] && grep -q '^FAIL:' <<< "$out_f"; then
        echo "ok   the same finding on a Raye image is a failure"
    else
        echo "FAIL image_err did not fail on a Raye image"; bad=1
    fi
    IMAGE_AUTHORITY=$kept; fail=0

    # groups() itself
    good_file "$t/g"
    if [ "$(groups "$t/g" | wc -l)" = 2 ] &&
       [ "$(groups "$t/g" | cut -d'|' -f1 | tr '\n' ' ')" = "deb deb-src " ] &&
       [ "$(groups "$t/g" | cut -d'|' -f6 | tr '\n' ' ')" = "- no " ]; then
        echo "ok   groups() reads the types and the Enabled of each group"
    else
        echo "FAIL groups() gave [$(groups "$t/g")]"; bad=1
    fi

    return "$bad"
}

# ----------------------------------------------------------------- main

[ "$MODE" = self ] && { self_test; exit $?; }

check_file
if [ -n "$ROOT" ]; then
    if [ -d "$ROOT" ]; then check_image "$ROOT"; else err "no such tree: $ROOT"; fi
else
    note "no image was questioned, only the file. For a verdict on an image:"
    note "    tests/test_apt_sources.sh --root <an image tree>"
fi

if [ "$fail" = 0 ]; then
    if [ "$IMAGE_WEAK" = 1 ]; then
        echo "ok: the apt sources hold (the image side could not speak for Raye, see the notes)"
    elif [ "$IMAGE_AUTHORITY" = 1 ]; then
        echo "ok: a Raye machine gets its packages, and can be given its sources"
    else
        echo "ok: config/ubuntu.sources holds (no image was questioned)"
    fi
fi
exit "$fail"
