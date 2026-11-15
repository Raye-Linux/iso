#!/bin/bash
#
# Checks that a Raye machine can still add a software source. python-apt
# describes a system from a template named after the ID of os-release;
# without it add-apt-repository, software-properties and Synaptic's
# repository dialog all stop on NoDistroTemplateException.
#
#   tests/test_apt_template.sh               the repo, then an image if one is found
#   tests/test_apt_template.sh --root DIR    question the image tree DIR
#   tests/test_apt_template.sh --iso FILE    question a built ISO (mounted read-only)
#   tests/test_apt_template.sh --no-image    the repo side only
#   tests/test_apt_template.sh --self-test   show that each check fails on bad input
#
# --paths, --rules, --build, --osrelease and --templates replace the
# repo's files (used by the self-test). Exit 0 when everything holds,
# 1 otherwise.
#
# Which image is questioned is said, never guessed: --iso, --root or
# $RAYE_ROOT. With none of them the test rules on the repo alone and
# prints the command to get an image verdict, with the ISO that the ISO=
# line of tools/release.conf names -- the file that already says where
# the publish tools look (a symlink to the newest build on the build machine). No
# path is written in this test: the outer build chroot belongs to the
# launcher outside this repo (/var/tmp/raye/iso-build-start.sh) and a
# path baked in here would be wrong on every other machine. An image
# found by guessing is an image whose age nobody knows, and a stale one
# would fail this test for a repo that is already right.
#
# ---------------------------------------------------------------------
# Measured on 2026-11-05, so nobody walks this road twice.
#
# WHICH ARCHIVE. This VM and the ISO build chroot are Debian 13 trixie
# with python3-apt 3.0.0; the image is ID=raye, VERSION_CODENAME=resolute
# with python3-apt 3.1.0ubuntu1.1. The rule for the template's name is
# therefore read from the IMAGE's own python-apt, and every verdict about
# it is drawn inside the image. Run against a tree that is not Raye's,
# this test says which tree it found and turns its findings into notes:
# another distribution's python-apt has its own rule, and a verdict drawn
# from it would be a guess. Pointing --root at /var/tmp/raye/iso-build
# (the Debian build chroot, which looks plausible and sits one directory
# above the image) is exactly the mistake this guard catches.
#
# THE NAME IS LOWER CASE. On resolute, DistInfo opens
# <base_dir>/<ID>.info with the ID of os-release verbatim, and
# SourceEntryMatcher globs *.info and takes each base name as that
# template's distribution; get_sources then keeps the template whose
# distribution equals Distribution.id, which get_distro() builds from the
# same ID. Measured in the image: raye.info resolves, while a capitalised
# Raye.info reproduces the owner's error word for word --
# "could not find a distribution template for raye/resolute" -- because
# the matcher registers it under 'Raye'. Capitalised names (Ubuntu.info)
# were the rule of the old python-apt; resolute ships ubuntu.info,
# debian.info and kali.info, all lower case.
#
# WHAT THE PACKAGE BUILD ALREADY COVERS. The content of the template --
# tag-file parsing, braced suites, MatchURI, the comment trap -- is
# checked by packages/raye-base/release/apt/tests, which debian/rules
# runs on every image build (build.sh calls dpkg-buildpackage without
# nocheck). That suite needs pytest, which this VM does not have, so it
# never runs in the barrier. This test does not repeat it: it checks that
# the wiring is still in debian/rules, and spends its own effort on the
# one thing no source test can see -- the built image.
#
# STATED LIMIT. The image side needs root, because it runs the image's
# own python3 under chroot. Without root it says so and draws no verdict
# rather than falling back on this machine's python-apt, which is a
# different version of a different distribution.
# ---------------------------------------------------------------------
#
# Note: usage() prints lines 3-16 of this file. Keep that block that
# length, or move the range.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
PKG=$here/packages/raye-base
PATHS=$PKG/debian/raye-release-paths
RULES=$PKG/debian/rules
BUILD=$here/build.sh
OSRELEASE=$PKG/release/os-release
TEMPLATES=$PKG/release/python-apt
VERSIONFILE=$here/VERSION
CONF=$here/tools/release.conf

ROOT=${RAYE_ROOT:-}
ISO=
MODE=check
IMAGE=1

fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok: $*"; }
note() { echo "note: $*"; }

# 1 when the tree we questioned really is a Raye image (set in check_image).
IMAGE_AUTHORITY=0
IMAGE_WEAK=0
MOUNTS=()
TMPS=()
# shellcheck disable=SC2329  # run by the EXIT trap
cleanup() {
    local i d
    for ((i=${#MOUNTS[@]}-1; i>=0; i--)); do umount "${MOUNTS[i]}" 2>/dev/null; done
    for d in "${TMPS[@]}"; do rm -rf -- "$d"; done
}
trap cleanup EXIT

# A finding that rests on an image tree. It is only a failure when that
# tree is Raye's; from anything else it is a note, because another
# distribution's python-apt has its own template rule.
image_err() {
    if [ "$IMAGE_AUTHORITY" = 1 ]; then
        err "$*"
    else
        note "not a Raye image, so not a failure: $*"
    fi
}

usage() { sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT=${2:?--root needs a directory}; shift 2 ;;
        --iso) ISO=${2:?--iso needs a file}; shift 2 ;;
        --paths) PATHS=${2:?--paths needs a file}; shift 2 ;;
        --rules) RULES=${2:?--rules needs a file}; shift 2 ;;
        --build) BUILD=${2:?--build needs a file}; shift 2 ;;
        --osrelease) OSRELEASE=${2:?--osrelease needs a file}; shift 2 ;;
        --templates) TEMPLATES=${2:?--templates needs a directory}; shift 2 ;;
        --version-file) VERSIONFILE=${2:?--version-file needs a file}; shift 2 ;;
        --conf) CONF=${2:?--conf needs a file}; shift 2 ;;
        --no-image) IMAGE=0; shift ;;
        --self-test) MODE=self; shift ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
done

# A field of an os-release file. Read, never sourced: it comes from an
# image tree, so it is data, not code to run here.
os_field() {
    sed -n "s/^$2=[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}\$/\1/p" "$1" 2>/dev/null | head -n1
}

# The suite the image is built from, as build.sh assigns it. Comments are
# stripped first, so a line that only mentions SUITE= in prose is not
# taken for the setting.
target_suite() {
    [ -f "$BUILD" ] || return 0
    sed 's/#.*//' "$BUILD" |
        sed -n 's/^[[:space:]]*SUITE=[\"'"'"']\{0,1\}\([A-Za-z0-9._-]\{1,\}\).*/\1/p' |
        head -n1
}

# "<package> <source> <destination>" of raye-release-paths, with comments
# stripped and the leading "?" of a staged line removed.
paths_lines() {
    sed 's/#.*//' "$1" | awk 'NF >= 3 { sub(/^\?/, "", $2); print $1, $2, $3 }'
}

# A KEY=VALUE line of tools/release.conf. The file is KEY=VALUE and no
# shell, as its own first line says, so it is read and never sourced.
conf_field() {
    sed -n "s/^[[:space:]]*$2=[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}[[:space:]]*\$/\1/p" \
        "$1" 2>/dev/null | head -n1
}

# ------------------------------------------------------------- the repo

check_repo() {
    local id code info mirrors
    [ -f "$OSRELEASE" ] || { err "no $OSRELEASE"; return; }
    id=$(os_field "$OSRELEASE" ID)
    code=$(os_field "$OSRELEASE" VERSION_CODENAME)
    [ -n "$id" ] || { err "$OSRELEASE has no ID"; return; }
    [ -n "$code" ] || { err "$OSRELEASE has no VERSION_CODENAME"; return; }

    info=$TEMPLATES/$id.info
    mirrors=$TEMPLATES/$id.mirrors
    if [ -f "$info" ]; then
        ok "$id.info is there, named after ID=$id of os-release"
    else
        err "$id.info is missing from $TEMPLATES: a Raye machine would answer" \
            "NoDistroTemplateException for $id/$code"
    fi
    [ -f "$mirrors" ] ||
        err "$id.mirrors is missing: the mirror list would never be read"

    # the matcher globs *.info and takes the base name as the
    # distribution, so a differently-cased sibling is a second, wrong one
    local other
    other=$(find "$TEMPLATES" -maxdepth 1 -iname "$id.info" ! -name "$id.info" \
            -printf '%f\n' 2>/dev/null)
    if [ -n "$other" ]; then
        err "$other sits next to $id.info: the matcher would register that one under" \
            "'${other%.info}', which is not ID=$id"
    fi

    # get_sources keeps the FIRST template whose name is the codename
    if [ -f "$info" ]; then
        local first
        first=$(sed -n 's/^Suite:[[:space:]]*\([^[:space:]]*\).*/\1/p' "$info" | head -n1)
        if [ "$first" = "$code" ]; then
            ok "the first suite of the template is $code, the codename of the image"
        else
            err "the first suite of $id.info is '${first:-none}', not the codename" \
                "'$code': get_sources keeps the first match, so it would describe" \
                "the wrong archive"
        fi
    fi

    # What the repository dialog calls this system. It is the sixth place
    # the version shows, and on 2026-11-05 it was the only one of the six
    # that was wrong -- "Raye Linux 0.1", without the word the other five
    # carry. VERSION is the single source (build.sh:33 already reads it);
    # the word never belongs in VERSION_ID, which dpkg and apt compare
    # and which cannot hold a space.
    if [ -f "$info" ] && [ -f "$VERSIONFILE" ]; then
        local release shown
        release=$(head -n1 "$VERSIONFILE")
        # with its name from release-names, beside VERSION: "0.5 Beta Alpenglow"
        local names name
        names=$(dirname "$VERSIONFILE")/release-names
        name=$(awk -v num="${release%% *}" '!/^#/ && $1 == num { print $2; exit }' "$names" 2>/dev/null)
        release="$release${name:+ $name}"
        shown=$(awk '/^Suite:/ { n++ } n == 1 && /^Description:/ { sub(/^Description:[[:space:]]*/, ""); print; exit }' "$info")
        if [ "$shown" = "Raye Linux $release" ]; then
            ok "the repository dialog calls this system \"Raye Linux $release\", as VERSION says"
        else
            err "the template's first Description is \"$shown\"; VERSION says the system is" \
                "\"Raye Linux $release\", and the other files that show the version say so too"
        fi
    fi

    # shipped by a package, which is the whole point: a file dropped by a
    # script is taken away by the next python-apt upgrade
    local want=usr/share/python-apt/templates line shipped_ok=1 f
    for f in "$id.info" "$id.mirrors"; do
        line=$(paths_lines "$PATHS" 2>/dev/null |
               awk -v s="release/python-apt/$f" '$2 == s { print; exit }')
        if [ -z "$line" ]; then
            err "release/python-apt/$f is not in raye-release-paths: it would not be packaged"
            shipped_ok=0
            continue
        fi
        if [ "$line" != "raye-release release/python-apt/$f $want/$f" ]; then
            err "$f is shipped as [$line]; expected package raye-release to $want/$f"
            shipped_ok=0
        fi
    done
    [ "$shipped_ok" = 1 ] && ok "both files are shipped by raye-release to /$want"

    # the build script must not write the template behind the package's back
    if [ -f "$BUILD" ] && sed 's/#.*//' "$BUILD" | grep -q 'python-apt'; then
        err "$(basename "$BUILD") touches python-apt: the template has to come from the" \
            "package, or a python-apt upgrade removes it again"
    else
        ok "the build script does not drop the template behind the package's back"
    fi

    # the deep content checks must stay wired into the package build
    if [ -f "$RULES" ] && sed 's/#.*//' "$RULES" | grep -q 'release/apt/tests'; then
        ok "debian/rules still runs release/apt/tests, which checks the template's content"
    else
        err "debian/rules no longer runs release/apt/tests: the tag-file, braced-suite" \
            "and comment traps would stop being checked anywhere"
    fi
}

# ------------------------------------------------- whose image is this?

# Mount an ISO and the filesystem inside it, read-only, and leave the
# image tree in MOUNTED_TREE.
#
# It must NOT print the path for a caller to capture: a command
# substitution runs in a subshell, so the mount points it appended to
# MOUNTS would never reach this shell and the EXIT trap would unmount
# nothing. Measured on 2026-11-05: the first version of this function
# left both mounts behind after a clean, green run.
MOUNTED_TREE=
mount_iso() {
    local iso=$1 m1 m2 squash
    MOUNTED_TREE=
    [ -f "$iso" ] || { err "no such ISO: $iso"; return 1; }
    [ "$(id -u)" = 0 ] || { note "an ISO can only be opened as root"; return 1; }
    m1=$(mktemp -d); TMPS+=("$m1")
    mount -o loop,ro "$iso" "$m1" 2>/dev/null || { err "cannot mount $iso"; return 1; }
    MOUNTS+=("$m1")
    squash=$(find "$m1" -maxdepth 2 -name 'filesystem.squashfs' -print -quit 2>/dev/null)
    [ -n "$squash" ] || { err "$iso carries no filesystem.squashfs"; return 1; }
    m2=$(mktemp -d); TMPS+=("$m2")
    mount -t squashfs -o loop,ro "$squash" "$m2" 2>/dev/null ||
        { err "cannot mount $squash (no squashfs support?)"; return 1; }
    MOUNTS+=("$m2")
    MOUNTED_TREE=$m2
}

# Is this tree a Raye image? Its ID says so, and its codename is the
# suite build.sh builds from.
tree_is_image() {
    local root=$1 id code suite
    id=$(os_field "$root/etc/os-release" ID)
    code=$(os_field "$root/etc/os-release" VERSION_CODENAME)
    suite=$(target_suite)
    [ "$id" = raye ] || return 1
    [ -z "$suite" ] || [ "$code" = "$suite" ]
}

# The program the IMAGE's own python3 runs, inside the image. It prints
# one "key=value" line per finding and decides nothing; this shell
# decides. It writes nothing anywhere and never touches the network, so
# it also runs on a read-only squashfs mount.
probe_source() {
    cat <<'PROBE'
import inspect
import platform
import sys


def say(k, v):
    print(f"{k}={v}")


try:
    import apt_pkg
    import aptsources.distinfo as distinfo
    import aptsources.distro as distro_mod
    import aptsources.sourceslist as sourceslist
except Exception as e:
    say("python_apt", f"broken {type(e).__name__}: {e}")
    sys.exit(0)

# The folder python-apt really looks in, read from python-apt itself, so
# a version that moves it is noticed instead of assumed.
sig = inspect.signature(distinfo.DistInfo.__init__)
say("templates_dir", sig.parameters["base_dir"].default)

osr = platform.freedesktop_os_release()
say("id", osr.get("ID", ""))
say("codename", osr.get("VERSION_CODENAME", ""))

# The exact call that raised NoDistroTemplateException.
dist = distro_mod.get_distro()
slist = sourceslist.SourcesList(deb822=True)
try:
    dist.get_sources(slist)
except Exception as e:
    say("get_sources", f"{type(e).__name__}: {e}")
    sys.exit(0)
say("get_sources", "ok")
say("template_name", dist.source_template.name)
say("template_distribution", dist.source_template.distribution)
say("template_description", dist.source_template.description)
say("components", ",".join(sorted(c.name for c in dist.source_template.components)))

# The series add-apt-repository builds a PPA source with.
say("ppa_series", dist.codename)

# Every source of the image and the template it was given. A source of
# this distribution described by ANOTHER distribution's template shows
# that distribution's wording in the repository dialog.
code = osr.get("VERSION_CODENAME", "")
for s in slist.exploded_list():
    if s.invalid or s.disabled or not s.uri or not s.dist:
        continue
    t = getattr(s, "template", None)
    if t is None:
        say("third_party", f"{s.type} {s.uri} {s.dist}")
        continue
    mine = t.name == code or t.name.startswith(code + "-")
    say(
        "described",
        f"{t.distribution}|{t.name}|{'suite' if mine else 'other'}|"
        f"{s.type} {s.uri} {s.dist}",
    )

# The dialog that stopped before doing any work.
try:
    from softwareproperties.SoftwareProperties import SoftwareProperties

    SoftwareProperties()
    say("softwareproperties", "ok")
except ImportError:
    say("softwareproperties", "absent")
except Exception as e:
    say("softwareproperties", f"{type(e).__name__}: {e}")

# The file add-apt-repository edits: sourceparts + <id>.sources.
try:
    say(
        "aar_sourceslist",
        apt_pkg.config.find_dir("Dir::Etc::sourceparts") + osr.get("ID", "") + ".sources",
    )
except Exception as e:
    say("aar_sourceslist", f"{type(e).__name__}: {e}")
PROBE
}

# ------------------------------------------------------------ the image

check_image() {
    local root=$1 out id code dir line k v
    local -A got=()

    id=$(os_field "$root/etc/os-release" ID)
    code=$(os_field "$root/etc/os-release" VERSION_CODENAME)
    if tree_is_image "$root"; then
        IMAGE_AUTHORITY=1
        echo "image: $root (ID=$id, $code)"
    else
        IMAGE_AUTHORITY=0
        IMAGE_WEAK=1
        local suite
        suite=$(target_suite)
        note "this tree says ID=${id:-nothing}, codename=${code:-nothing}; a Raye image is" \
             "ID=raye built from ${suite:-the suite named in build.sh}."
        note "  Its python-apt has its own template rule, so what it reports here is a"
        note "  warning, never a failure. For a verdict, give --iso a built ISO or --root"
        note "  a tree whose os-release says ID=raye."
    fi

    if [ ! -x "$root/usr/bin/python3" ]; then
        image_err "$root has no /usr/bin/python3: nothing can be asked of its python-apt"
        return
    fi
    if [ "$(id -u)" != 0 ]; then
        note "not root, so the image's own python-apt was not asked (that needs chroot);" \
             "this machine's python-apt is another version of another distribution and" \
             "would not be evidence about Raye."
        return
    fi

    out=$(probe_source | chroot "$root" /usr/bin/python3 -I - 2>&1)
    while IFS= read -r line; do
        case "$line" in
            *=*) k=${line%%=*}; v=${line#*=} ;;
            *) continue ;;
        esac
        case "$k" in
            described|third_party) got[$k]="${got[$k]-}$v"$'\n' ;;
            *) got[$k]=$v ;;
        esac
    done <<< "$out"

    if [ -z "${got[id]-}" ]; then
        image_err "the image's python-apt could not be questioned:"
        printf '  %s\n' "$out" | head -n 20
        return
    fi

    # the folder python-apt really looks in, as that python-apt states it
    dir=${got[templates_dir]-}
    if [ -z "$dir" ]; then
        image_err "could not read the template folder from the image's python-apt"
    elif [ -f "$root$dir/$id.info" ]; then
        ok "$dir/$id.info is installed in the image (python-apt names that folder itself)"
    else
        image_err "$dir/$id.info is not in the image, and that is the only name" \
                  "python-apt looks for"
    fi

    if [ -n "$dir" ]; then
        local other
        other=$(find "$root$dir" -maxdepth 1 -iname "$id.info" ! -name "$id.info" \
                -printf '%f\n' 2>/dev/null)
        [ -n "$other" ] &&
            image_err "$other is installed beside $id.info: the matcher would register" \
                      "it under '${other%.info}', not '$id'"
    fi

    # in a package, not dropped by a script
    local owner
    owner=$(grep -rlx "$dir/$id.info" "$root"/var/lib/dpkg/info/*.list 2>/dev/null |
            head -n1 | sed 's|.*/||; s|\.list$||')
    if [ -n "$owner" ]; then
        ok "the template belongs to the package $owner, so a python-apt upgrade keeps it"
    else
        image_err "no installed package owns $dir/$id.info: a file dropped by a script is" \
                  "taken away by the next python-apt upgrade"
    fi

    # the call that failed on the owner's machine
    case "${got[get_sources]-}" in
        ok) ok "get_distro().get_sources() works in the image" ;;
        "") image_err "the image's python-apt never reached get_sources" ;;
        *) image_err "get_distro().get_sources() in the image: ${got[get_sources]}" ;;
    esac

    if [ "${got[get_sources]-}" = ok ]; then
        [ "${got[template_distribution]-}" = "$id" ] ||
            image_err "the template it found belongs to" \
                      "'${got[template_distribution]-nothing}', not to '$id'"
        [ "${got[template_name]-}" = "$code" ] ||
            image_err "the template it found is for '${got[template_name]-nothing}', not" \
                      "the codename '$code'"
    fi

    # The repository dialog must call the system what the rest of the
    # image calls it. Checked against the image's OWN os-release, not
    # against the repo: that makes the question "is this image
    # self-consistent", which is answerable from the image alone and does
    # not go red merely because the image is older than a commit.
    local pretty=${got[template_description]-}
    local want_pretty
    want_pretty=$(os_field "$root/etc/os-release" PRETTY_NAME)
    if [ -n "$pretty" ] && [ -n "$want_pretty" ]; then
        if [ "$pretty" = "$want_pretty" ]; then
            ok "the repository dialog says \"$pretty\", as the rest of the image does"
        else
            image_err "the repository dialog would say \"$pretty\" while os-release of the" \
                      "same image says \"$want_pretty\""
        fi
    fi

    # the series a PPA resolves to: no archive publishes a 'raye' series
    local ubu
    ubu=$(os_field "$root/etc/os-release" UBUNTU_CODENAME)
    if [ -z "${got[ppa_series]-}" ]; then
        :
    elif [ "${got[ppa_series]}" = "$id" ]; then
        image_err "a PPA would be asked for a '${got[ppa_series]}' series, which no" \
                  "archive publishes"
    elif [ -n "$ubu" ] && [ "${got[ppa_series]}" != "$ubu" ]; then
        image_err "a PPA would be asked for '${got[ppa_series]}', but the image is built" \
                  "on '$ubu'"
    else
        ok "a PPA resolves to the ${got[ppa_series]} series"
    fi

    # every source of this distribution is described by OUR template
    local bad=0 d tdist rest tname kind
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        tdist=${d%%|*}; rest=${d#*|}
        tname=${rest%%|*}; rest=${rest#*|}
        kind=${rest%%|*}; rest=${rest#*|}
        if [ "$kind" = suite ] && [ "$tdist" != "$id" ]; then
            image_err "the source [$rest] is described by $tdist's template '$tname':" \
                      "$tdist's own wording would show in the repository dialog"
            bad=1
        fi
    done <<< "${got[described]-}"
    if [ -n "${got[described]-}" ] && [ "$bad" = 0 ]; then
        ok "every source of $code is described by $id's own template"
    fi

    case "${got[softwareproperties]-}" in
        ok) ok "softwareproperties builds, so its dialog and Synaptic's open" ;;
        absent) note "software-properties is not installed in this image" ;;
        "") ;;
        *) image_err "softwareproperties: ${got[softwareproperties]}" ;;
    esac

    # Open, and not this test's subject: add-apt-repository writes
    # components and pockets into <ID>.sources, and that name is taken by
    # Raye's own archive. Reported rather than hidden; failing on it
    # would turn the barrier red for a packaging decision that is not
    # ours to take.
    local aar=${got[aar_sourceslist]-}
    if [ -n "$aar" ] && [ -f "$root$aar" ] &&
       grep -qi 'raye' "$root$aar" 2>/dev/null &&
       ! grep -q 'archive\.ubuntu\.com' "$root$aar" 2>/dev/null; then
        note "open, and not this test's subject: add-apt-repository edits $aar, which"
        note "  holds Raye's own archive and not the base one, so 'add-apt-repository -c"
        note "  <component>' and '-p <pocket>' land on the Raye archive (measured"
        note "  2026-11-05). Adding a PPA is unaffected. The remedy is a packaging"
        note "  decision: ship the Raye archive under another name, or the base archive"
        note "  under this one."
    fi
}

# ------------------------------------------------------------ self-test

# A repo side that holds, to measure each break against.
good_repo() {
    local d=$1
    mkdir -p "$d/packages/raye-base/debian" "$d/packages/raye-base/release/python-apt"
    printf 'ID=raye\nVERSION_CODENAME=resolute\nUBUNTU_CODENAME=resolute\n' \
        > "$d/packages/raye-base/release/os-release"
    printf 'Suite: resolute\nRepositoryType: deb\nDescription: Raye Linux 0.1 Beta\n' \
        > "$d/packages/raye-base/release/python-apt/raye.info"
    printf '0.1 Beta\n' > "$d/VERSION"
    mkdir -p "$d/tools"
    printf 'RELEASE_TITLE=Raye Linux 0.1 Beta\n' > "$d/tools/release.conf"
    : > "$d/packages/raye-base/release/python-apt/raye.mirrors"
    printf '%s\n' \
        'raye-release  release/python-apt/raye.info     usr/share/python-apt/templates/raye.info' \
        'raye-release  release/python-apt/raye.mirrors  usr/share/python-apt/templates/raye.mirrors' \
        > "$d/packages/raye-base/debian/raye-release-paths"
    printf 'override_dh_auto_test:\n\tpython3 -m pytest -q release/apt/tests release/grub/tests\n' \
        > "$d/packages/raye-base/debian/rules"
    printf 'SUITE=resolute\n' > "$d/build.sh"
}

run_repo() {
    "$0" --no-image \
        --osrelease "$1/packages/raye-base/release/os-release" \
        --templates "$1/packages/raye-base/release/python-apt" \
        --paths "$1/packages/raye-base/debian/raye-release-paths" \
        --rules "$1/packages/raye-base/debian/rules" \
        --version-file "$1/VERSION" \
        --conf "$1/tools/release.conf" \
        --build "$1/build.sh" 2>&1
}

self_test() {
    local t bad=0 out
    t=$(mktemp -d); TMPS+=("$t")

    # No file of the repo is ever written by the self-test: every case is
    # a sandbox of its own, handed to the test through the --paths,
    # --rules, --build, --osrelease and --templates options. There is
    # therefore nothing to restore and no checksum to compare -- a
    # stronger guarantee than editing the real files and putting them back.
    local box=$t/good
    mkdir -p "$box"; good_repo "$box"
    out=$(run_repo "$box")
    if grep -q '^FAIL:' <<< "$out"; then
        echo "FAIL the known-good repo side is already red:"; printf '  %s\n' "$out"; bad=1
    else
        echo "ok   a repo side that holds passes"
    fi

    # $1 label, $2 a fragment the failure must name, $3.. how to break it
    # (run with the sandbox as $1)
    local n=0
    case_breaks() {
        local label=$1 want=$2; shift 2
        n=$((n + 1))
        local b=$t/bad$n
        mkdir -p "$b"; good_repo "$b"
        "$@" "$b"
        out=$(run_repo "$b")
        if grep -q '^FAIL:' <<< "$out" && grep -qF -- "$want" <<< "$out"; then
            echo "ok   $label"
        else
            echo "FAIL $label did not go red naming [$want]:"
            printf '  %s\n' "$out"; bad=1
        fi
    }

    case_breaks "a missing template is caught" "NoDistroTemplateException" \
        bash -c 'rm -f "$1/packages/raye-base/release/python-apt/raye.info"' --
    case_breaks "a capitalised Raye.info is caught" "would register that one under" \
        bash -c 'mv "$1/packages/raye-base/release/python-apt/raye.info" \
                    "$1/packages/raye-base/release/python-apt/Raye.info"' --
    case_breaks "a missing mirror list is caught" "raye.mirrors is missing" \
        bash -c 'rm -f "$1/packages/raye-base/release/python-apt/raye.mirrors"' --
    case_breaks "a template that is not packaged is caught" "is not in raye-release-paths" \
        bash -c 'grep -v "python-apt/raye.info" \
                   "$1/packages/raye-base/debian/raye-release-paths" > "$1/x" &&
                 mv "$1/x" "$1/packages/raye-base/debian/raye-release-paths"' --
    case_breaks "the wrong install folder is caught" "expected package raye-release" \
        bash -c 'sed -i "s|usr/share/python-apt/templates/raye.info|etc/raye/raye.info|" \
                   "$1/packages/raye-base/debian/raye-release-paths"' --
    case_breaks "the wrong package is caught" "expected package raye-release" \
        bash -c 'sed -i "s|^raye-release  release/python-apt/raye.info|raye-system  release/python-apt/raye.info|" \
                   "$1/packages/raye-base/debian/raye-release-paths"' --
    case_breaks "a first suite that is not the codename is caught" "keeps the first match" \
        bash -c 'printf "Suite: other\nRepositoryType: deb\n\nSuite: resolute\n" \
                   > "$1/packages/raye-base/release/python-apt/raye.info"' --
    # the defect of 2026-11-05: the dialog said "Raye Linux 0.1"
    case_breaks "a Description that drops the word of VERSION is caught" \
        'VERSION says the system is' \
        bash -c 'printf "Suite: resolute\nRepositoryType: deb\nDescription: Raye Linux 0.1\n" \
                   > "$1/packages/raye-base/release/python-apt/raye.info"' --
    case_breaks "a Description naming another version is caught" \
        'VERSION says the system is' \
        bash -c 'printf "0.2\n" > "$1/VERSION"' --
    # the Description of the Raye archive suite is its own, not the system's
    case_breaks "the Description of the FIRST suite is the one read" \
        'VERSION says the system is' \
        bash -c 'printf "%s\n" "Suite: resolute" "RepositoryType: deb" \
                   "Description: wrong" "" "Suite: resolute" "RepositoryType: deb" \
                   "Description: Raye Linux 0.1 Beta" \
                   > "$1/packages/raye-base/release/python-apt/raye.info"' --
    case_breaks "a template dropped by the build script is caught" "touches python-apt" \
        bash -c 'printf "SUITE=resolute\ncp t /usr/share/python-apt/templates/raye.info\n" \
                   > "$1/build.sh"' --
    case_breaks "release/apt/tests dropped from debian/rules is caught" "no longer runs" \
        bash -c 'printf "override_dh_auto_test:\n\tpython3 -m pytest -q release/grub/tests\n" \
                   > "$1/packages/raye-base/debian/rules"' --
    # a commented-out python-apt line in build.sh is prose, not a drop
    local proseboxed=$t/prose
    mkdir -p "$proseboxed"; good_repo "$proseboxed"
    printf 'SUITE=resolute\n# the python-apt template comes from the package\n' \
        > "$proseboxed/build.sh"
    out=$(run_repo "$proseboxed")
    if grep -q '^FAIL:' <<< "$out"; then
        echo "FAIL a commented python-apt line in build.sh was taken for a drop:"
        printf '  %s\n' "$out"; bad=1
    else
        echo "ok   a commented python-apt line in build.sh is prose, not a drop"
    fi

    # the archive rule: the same finding is a note elsewhere, a failure on Raye
    local kept=$IMAGE_AUTHORITY out_w out_f
    IMAGE_AUTHORITY=0
    out_w=$(image_err "the template is missing")
    fail=0; image_err "the template is missing" >/dev/null
    if [ "$fail" = 0 ] && grep -q '^note:' <<< "$out_w"; then
        echo "ok   a finding from another distribution is a note, not a failure"
    else
        echo "FAIL image_err failed off a Raye image: [$out_w] fail=$fail"; bad=1
    fi
    IMAGE_AUTHORITY=1
    out_f=$(image_err "the template is missing")
    fail=0; image_err "the template is missing" >/dev/null
    if [ "$fail" = 1 ] && grep -q '^FAIL:' <<< "$out_f"; then
        echo "ok   the same finding on a Raye image is a failure"
    else
        echo "FAIL image_err did not fail on a Raye image: [$out_f] fail=$fail"; bad=1
    fi
    IMAGE_AUTHORITY=$kept; fail=0

    # tree_is_image tells the image from the Debian build chroot it sits in
    mkdir -p "$t/img/etc" "$t/dbg/etc"
    printf 'ID=raye\nVERSION_CODENAME=resolute\n' > "$t/img/etc/os-release"
    printf 'ID=debian\nVERSION_CODENAME=trixie\n' > "$t/dbg/etc/os-release"
    local kept_build=$BUILD
    printf 'SUITE=resolute\n' > "$t/bsh"
    BUILD=$t/bsh
    if tree_is_image "$t/img" && ! tree_is_image "$t/dbg"; then
        echo "ok   a Raye image is told from the Debian build chroot around it"
    else
        echo "FAIL tree_is_image confuses the image with its build chroot"; bad=1
    fi
    printf 'ID=raye\nVERSION_CODENAME=noble\n' > "$t/img/etc/os-release"
    if ! tree_is_image "$t/img"; then
        echo "ok   an image of a codename build.sh does not build is not trusted"
    else
        echo "FAIL tree_is_image trusts a codename build.sh does not build"; bad=1
    fi

    # target_suite reads build.sh and never a commented SUITE=
    printf '%s\n' '#SUITE=commented-out' '# SUITE=also-prose' 'SUITE=resolute' > "$t/bsh"
    out=$(target_suite)
    BUILD=$kept_build
    if [ "$out" = resolute ]; then
        echo "ok   target_suite reads build.sh, never a commented SUITE="
    else
        echo "FAIL target_suite gave [$out]"; bad=1
    fi

    # paths_lines strips comments and the "?" of a staged line
    printf '%s\n' '# a comment line' 'raye-release  ?release/x  usr/share/x' > "$t/paths"
    out=$(paths_lines "$t/paths")
    if [ "$out" = "raye-release release/x usr/share/x" ]; then
        echo "ok   paths_lines drops comments and the staged '?'"
    else
        echo "FAIL paths_lines gave [$out]"; bad=1
    fi

    # conf_field reads release.conf and never a commented line
    printf '%s\n' '# ISO=/commented/out.iso' 'ISO=/var/tmp/raye/isos/latest.iso' \
        'RELEASE_TITLE=Raye Linux 0.1 Beta' > "$t/conf"
    if [ "$(conf_field "$t/conf" ISO)" = /var/tmp/raye/isos/latest.iso ] &&
       [ "$(conf_field "$t/conf" RELEASE_TITLE)" = "Raye Linux 0.1 Beta" ] &&
       [ -z "$(conf_field "$t/conf" NOSUCHKEY)" ]; then
        echo "ok   conf_field reads release.conf, never a commented line"
    else
        echo "FAIL conf_field gave [$(conf_field "$t/conf" ISO)]"; bad=1
    fi

    # the probe is a program, and it is the image's python that must run it
    if probe_source | grep -q 'get_sources' &&
       probe_source | python3 -c 'import sys; compile(sys.stdin.read(), "probe", "exec")'
    then
        echo "ok   the probe compiles and asks for get_sources"
    else
        echo "FAIL the probe does not compile"; bad=1
    fi

    # The mounts of --iso must be unmountable afterwards, which they are
    # not if a caller captures mount_iso in a command substitution: the
    # subshell keeps the MOUNTS it appended. This happened once; the
    # guard is static because making a fake ISO to prove it would cost
    # more than it is worth, and the real run is in the report.
    #
    # Both needles are assembled from pieces so that this check does not
    # match its own source: a grep for a literal in the file it lives in
    # always finds itself, which is a check that can never go red.
    local src=$0 hands_back wrong
    hands_back='MOUNTED_TREE=''$m2'
    wrong='$''(mount_iso'
    if grep -qF "$hands_back" "$src" && ! grep -qF "$wrong" "$src"; then
        echo "ok   mount_iso hands its tree back in a variable, not through a subshell"
    else
        echo "FAIL mount_iso's mounts would leak out of a command substitution"; bad=1
    fi

    return "$bad"
}

# ----------------------------------------------------------------- main

[ "$MODE" = self ] && { self_test; exit $?; }

check_repo

if [ "$IMAGE" = 1 ]; then
    tree=
    if [ -n "$ISO" ]; then
        mount_iso "$ISO"
        tree=$MOUNTED_TREE
    elif [ -n "$ROOT" ]; then
        if [ -d "$ROOT" ]; then tree=$ROOT; else err "no such tree: $ROOT"; fi
    else
        # No image is picked up by guessing, and that is deliberate: an
        # image found by guessing is an image whose age nobody knows, and
        # a stale one would fail this test for a repo that is already
        # right. The barrier names the artefact it ruled on. What it
        # should pass is printed here, taken from the ISO= line of
        # tools/release.conf -- the file that already names where the
        # publish tools look.
        conf_iso=$(conf_field "$CONF" ISO)
        default=${WORK:-/var/tmp/raye-build}/chroot
        note "no image was questioned, only the repo. For a verdict on an image:"
        if [ -n "$conf_iso" ] && [ -f "$conf_iso" ]; then
            note "    tests/test_apt_template.sh --iso $conf_iso"
            note "  (the ISO= line of $(basename "$CONF"), which is the artefact that ships)"
        elif [ -d "$default" ]; then
            note "    tests/test_apt_template.sh --root $default"
        else
            note "    tests/test_apt_template.sh --iso <a built ISO>"
        fi
    fi
    [ -n "$tree" ] && check_image "$tree"
else
    note "the image side was not run (--no-image)"
fi

if [ "$fail" = 0 ]; then
    if [ "$IMAGE_WEAK" = 1 ]; then
        echo "ok: the template holds (the image side could not speak for Raye, see the notes)"
    elif [ "$IMAGE_AUTHORITY" = 1 ]; then
        echo "ok: a Raye machine can add a software source"
    else
        echo "ok: the repo side holds (no image was questioned)"
    fi
fi
exit "$fail"
