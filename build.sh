#!/bin/bash
#
# Builds the Raye Linux live ISO.
#
#   sudo ./build.sh                 everything
#   sudo ./build.sh packages        only rebuild and republish the Raye packages
#   sudo ./build.sh iso             only redo the ISO from the existing tree
#   sudo ./build.sh compiled        only build the compiled packages, to test them
#
# Runs on a Debian 13 build machine with mmdebstrap, aptly, xorriso,
# squashfs-tools and mtools. The other Raye repos (theme, installer) are
# expected next to this one. Output goes to $OUT (default ./out).
# KERNEL_DEBS=<folder> puts the Raye kernel built by the kernel repo into
# the image, so Settings can switch to it without a network.
# WINE_DEBS=<folder> brings raye-wine, built by the wine repo (./build.sh
# there, out/, the default). raye-windows-apps depends on it, and a Wine
# build takes far longer than an image, so it is made on its own and the
# image refuses to go on without it.
# DESKTOP_DEBS=<folder> brings the Raye desktop packages built by the
# desktop repo (./build.sh there, out/). The image INSTALLS these, unlike
# the kernel, which it only carries: the shell package holds the default
# layout and the desktop's own bindings, and the look-and-feel package no
# longer does. Without them a new account starts with no taskbar, so the
# build refuses to go on rather than make such an image.
#
# What it does:
#   1. builds the Raye .debs and publishes them in the signed apt repo
#   2. bootstraps resolute with mmdebstrap and installs the desktop
#   3. cleans the tree up, packs it into casper's squashfs
#   4. lays out the ISO with the signed shim and the CD GRUB, and writes
#      a UEFI hybrid image with xorriso

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here")
version=$(cat "$here/VERSION")
stamp=$(date +%Y%m%d)

OUT=${OUT:-$here/out}
WORK=${WORK:-/var/tmp/raye-build}
MIRROR=${MIRROR:-http://archive.ubuntu.com/ubuntu}
PROXY=${PROXY-http://127.0.0.1:3142}       # apt-cacher-ng, empty to skip
LOCAL_REPO=${LOCAL_REPO:-0}                 # 1: no aptly, packages go in straight
DESKTOP_DEBS=${DESKTOP_DEBS:-}              # the Raye desktop packages, see above
WINE_DEBS=${WINE_DEBS:-$src/wine/out}       # raye-wine, see above
# no cache running here: go to the mirror directly
if [ -n "$PROXY" ] && ! curl -fs -o /dev/null --max-time 3 "$PROXY/acng-report.html"; then
    PROXY=""
fi
SUITE=resolute
# named on purpose: mmdebstrap only guesses it when distro-info-data
# happens to be installed on the build machine
UBUNTU_KEYRING=/usr/share/keyrings/ubuntu-archive-keyring.gpg
GPG_KEY=${GPG_KEY:-E00515536D1382C4ABB31485A5B09A59F05E0DA0}  # signing subkey of the archive key
# This was `export GNUPGHOME=...`, and exporting it broke the build.
#
# It is wanted by exactly one step -- signing the ISO's .sha256 -- and the
# default names the owner's key home, which does NOT exist on a build machine.
# Exported, it reached every subprocess of the whole build, and gpg refuses to
# START when GNUPGHOME names a directory that is not there:
#
#     gpg: Fatal: /var/lib/raye-release/gnupg: directory does not exist!   rc=2
#
# That is fatal even for `--show-keys`, which reads nothing but the file it is
# handed. So any gpg ANYWHERE in the build failed -- and on 2026-11-07 that
# was raye-update's own keyring tests, in a package that has nothing to do
# with signing. The image could not be built at all.
#
# It is therefore NOT exported: the two steps that sign set it per command.
GPG_HOME=${GNUPGHOME:-$(sed -n 's/^GNUPGHOME=//p' "$here/tools/release.local.conf" "$here/tools/release.conf" 2>/dev/null | head -n 1)}
unset GNUPGHOME

root=$WORK/chroot
devroot=${DEVROOT:-/srv/resolute-dev}       # resolute tree for compiled packages
iso=$WORK/iso
# VERSION and release-names are the one place the release people read is
# written; tools/release_name.py writes it into os-release, Raye Setup and
# the rest. Refuse to build an image where one of them says something else.
python3 -B "$here/tools/release_name.py" --check ||
    { echo "build.sh: the release is not the same everywhere (tools/release_name.py --write)" >&2; exit 1; }
# VERSION is what people read ("0.5 Beta"); files and labels get it
# squeezed: raye-0.5-beta-<date>-amd64.iso, volume RAYE_0_5_BETA.
# The release name (release-names) is only in os-release and friends.
name=raye-$(tr 'A-Z ' 'a-z-' <<<"$version")-$stamp-amd64
volume=$(tr 'a-z. ' 'A-Z__' <<<"RAYE $version")

say() { printf '\n\033[1;35m==>\033[0m %s\n' "$*"; }
die() { printf 'build.sh: %s\n' "$*" >&2; exit 1; }

# The Raye desktop packages are needed as soon as the look-and-feel package
# has stopped carrying a default layout: from then on the shell package is
# the only place a new account's desktop comes from. Reading the theme tree
# rather than a flag keeps the two in step by itself -- put a layout back
# there and this relaxes on its own.
desktop_debs_needed() {
    ! ls -d "$src"/theme/lookandfeel/*/contents/layouts >/dev/null 2>&1
}

add_desktop_debs() {
    local debs=$1 deb found=0
    if [ -n "$DESKTOP_DEBS" ]; then
        for deb in "$DESKTOP_DEBS"/*+raye*.deb; do
            [ -e "$deb" ] || continue
            case "$deb" in *-dbgsym_*|*.ddeb) continue ;; esac
            cp "$deb" "$debs/"
            found=$((found + 1))
        done
    fi
    if [ "$found" -eq 0 ] && desktop_debs_needed; then
        die "the Raye desktop packages are missing, and this image must not be built without them.
    raye/theme ships no look-and-feel layout any more, so a new account would be
    handed no desktop layout at all and would start with no taskbar. Build them
    and pass the folder:
        (cd $src/desktop && ./build.sh) && DESKTOP_DEBS=$src/desktop/out $0 $*"
    fi
    [ "$found" -eq 0 ] || echo "$found Raye desktop package(s) added"
}

add_wine_debs() {
    local debs=$1 deb found=0
    # raye-wine comes in parts (raye-wine-i386, -mono, ...); take them all
    for deb in "$WINE_DEBS"/raye-wine*_*.deb; do
        [ -e "$deb" ] || continue
        cp "$deb" "$debs/"
        case ${deb##*/} in raye-wine_*) found=$((found + 1)) ;; esac
    done
    [ "$found" -gt 0 ] || die "raye-wine is missing: raye-windows-apps needs it. Build it and pass the folder:
        (cd $src/wine && ./build.sh) && WINE_DEBS=$src/wine/out $0 $*"
    echo "raye-wine added"
}

# The image must hold the very file apt is offered for a version it already
# has. A package whose version did not move (raye-account, raye-archive,
# raye-scx) is built again by every image build, and the new build is never
# the same file: apt then knows two packages under one version, and the
# first check of a fresh install offered them as updates, a restart included
# (1.0 Beta Sundog on VM 130, 2026-11-20: "raye-account 0.5.4~beta1 ->
# 0.5.4~beta1", "raye-scx 1.1.4-1 -> 1.1.4-1"). PUBLISHED_DEBS=<folder> holds
# the .deb files of the published archive: a build of a package, version and
# architecture found there is replaced by the published file. A package
# whose code changed without a new version is publish-repo's to refuse; here
# it is named, so the build log says the image keeps the published one.
PUBLISHED_DEBS=${PUBLISHED_DEBS:-}
prefer_published() {
    local debs=$1 f pub key n=0
    [ -n "$PUBLISHED_DEBS" ] && [ -d "$PUBLISHED_DEBS" ] || return 0
    local -A have=()
    for pub in "$PUBLISHED_DEBS"/*.deb; do
        [ -e "$pub" ] || continue
        key=$(dpkg-deb --showformat='${Package} ${Version} ${Architecture}' -W "$pub") || continue
        have[$key]=$pub
    done
    for f in "$debs"/*.deb; do
        [ -e "$f" ] || continue
        key=$(dpkg-deb --showformat='${Package} ${Version} ${Architecture}' -W "$f") || continue
        pub=${have[$key]:-}
        [ -n "$pub" ] || continue
        cmp -s "$f" "$pub" && continue
        cp "$pub" "$f"
        n=$((n + 1))
        echo "  already published at this version, the published file is used: ${f##*/}"
    done
    echo "$n package(s) taken from the published archive"
}

# ---------------------------------------------------------------- packages

# Packages with compiled code are built against resolute's libraries, in
# a resolute tree of their own; the plain ones are built on the host.
# archive comes before files, which builds against libraye-archive-dev
# account: raye-desktop depends on raye-account (Raye account, since 0.5.4)
# raye-scx (game mode's scheduler) needs packages/raye-scx/upstream, which
# fetch-scx.sh fills once; the build itself does not touch the network.
compiled_sources() { echo "$src/installer $src/settings $src/store $src/theme $src/archive $src/files $src/apps $src/account $here/packages/raye-scx"; }

make_devroot() {
    [ -x "$devroot/usr/bin/dpkg-buildpackage" ] && return
    say "Creating the resolute build tree"
    nothing_mounted_under "$devroot"
    rm -rf "${devroot:?}"
    local aptopt=()
    [ -n "$PROXY" ] && aptopt=(--aptopt="Acquire::http::Proxy \"$PROXY\"")
    mmdebstrap --mode=root --variant=buildd --keyring="$UBUNTU_KEYRING" \
        --components="main restricted universe multiverse" \
        --include=ca-certificates,debhelper,fakeroot,dpkg-dev \
        "${aptopt[@]}" $SUITE "$devroot" "$MIRROR" \
        "deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] $MIRROR $SUITE-updates main restricted universe multiverse"
}

build_compiled() {
    local dir=$1 out=$2 name
    name=$(basename "$dir")
    make_devroot
    rm -rf "${devroot:?}/build"
    mkdir -p "$devroot/build"
    cp -a "$dir" "$devroot/build/"
    # what this pass already built is a package source too: files needs
    # libraye-archive-dev, which no Ubuntu mirror has
    mkdir -p "$devroot/build/local"
    cp "$out"/*.deb "$devroot/build/local/" 2>/dev/null || true
    # Files keeps its own copy of the org.raye.ui colour table; its test
    # compares it with the theme's only when it can load the theme's QML.
    cp -a "$src/theme/qml" "$devroot/build/theme-qml"
    # the tree may have been made on another machine: use this one's DNS
    cp -L /etc/resolv.conf "$devroot/etc/resolv.conf"
    mount -t proc proc "$devroot/proc"
    # A package test may need a terminal: raye-settings drives passwd on a
    # pty. mmdebstrap leaves dev/pts empty, so forkpty() failed with "out of
    # pty devices" and three of its tests went red here while they passed in
    # every other build tree (2026-11-08). A new devpts instance of its own,
    # never the host's ptys.
    mount -t devpts -o newinstance,ptmxmode=0666,mode=0620 devpts "$devroot/dev/pts"
    # `env -i` WIPES the environment, so anything the caller set has to be
    # named again here. DEB_BUILD_OPTIONS was missing until 2026-11-05: the
    # job count asked for had no effect at all on the packages that actually
    # have code to compile, and nothing said so -- not a warning, not a line
    # in the log. The build simply ran unbounded.
    # And bounding make is NOT enough. `-flto=auto`, which Ubuntu's default
    # CXXFLAGS carry, makes GCC read nproc and fan out that many ltrans
    # processes PER LINK whenever it cannot find make's jobserver. Measured
    # 2026-11-05 on 28 cores: 51 compilers at once, 32060 MiB used on a
    # 32096 MiB VM with no swap -- the kernel killed lto1 and the build died.
    # An explicit `-flto=N` appended LAST is what stops GCC deciding alone;
    # DEB_LDFLAGS_APPEND is the one that counts, since lto1 runs at link time.
    chroot "$devroot" /usr/bin/env -i HOME=/root LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive \
        DEB_BUILD_OPTIONS="${DEB_BUILD_OPTIONS:-}" \
        DEB_CFLAGS_APPEND="${DEB_CFLAGS_APPEND:-}" \
        DEB_CXXFLAGS_APPEND="${DEB_CXXFLAGS_APPEND:-}" \
        DEB_LDFLAGS_APPEND="${DEB_LDFLAGS_APPEND:-}" \
        RAYE_THEME_QML_DIR=/build/theme-qml \
        PATH=/usr/sbin:/usr/bin:/sbin:/bin sh -ec "
            (cd /build/local && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null)
            echo 'deb [trusted=yes] file:/build/local ./' > /etc/apt/sources.list.d/raye-build-local.list
            apt-get update -q
            cd /build/$name
            apt-get build-dep -y -q --no-install-recommends ./
            rm -f /etc/apt/sources.list.d/raye-build-local.list
            dpkg-buildpackage -b -us -uc
        " || { rm -f "$devroot/etc/apt/sources.list.d/raye-build-local.list"
               umount "$devroot/dev/pts"; umount "$devroot/proc"; return 1; }
    umount "$devroot/dev/pts"
    umount "$devroot/proc"
    mv "$devroot"/build/*.deb "$out/"
}

build_packages() {
    say "Building Raye packages"
    local debs=$WORK/debs pkgsrc=$WORK/pkgsrc
    rm -rf "${debs:?}" "${pkgsrc:?}"
    mkdir -p "$debs" "$pkgsrc"
    # `>/dev/null` here threw away the only diagnosis there was. Measured
    # 2026-11-07: raye-update's test step failed and the build log carried
    # nothing but `make[1]: *** [debian/rules:9: override_dh_auto_test] Error
    # 1` -- pytest reports to STDOUT, so the names of the failing tests went
    # to /dev/null while only make's stderr survived. Three faithful
    # reproductions of the same command then passed, which left no way at all
    # to tell what had failed.
    #
    # The output still must not pour into the build log: these two builds are
    # ~1500 lines of dh chatter that buried the ISO steps. So each goes to its
    # own file, and a FAILURE prints the tail of it -- a build that dies has
    # earned the right to be noisy.
    local name buildlog
    for dir in "$here/packages/raye-base" "$src/update"; do
        cp -a "$dir" "$pkgsrc/"
        name=$(basename "$dir")
        buildlog=$WORK/$name.build.log
        if ! (cd "$pkgsrc/$name" && dpkg-buildpackage -b -us -uc -tc) \
                > "$buildlog" 2>&1; then
            echo "build_packages: $name failed. Last 60 lines of $buildlog:" >&2
            tail -60 "$buildlog" >&2
            return 1
        fi
    done
    mv "$pkgsrc"/*.deb "$debs/"
    local dir
    for dir in $(compiled_sources); do
        [ -d "$dir/debian" ] && build_compiled "$dir" "$debs"
    done
    add_desktop_debs "$debs"
    add_wine_debs "$debs"
    prefer_published "$debs"
    ls -1 "$debs"

    if [ "$LOCAL_REPO" = 1 ]; then
        # built somewhere without the archive key: the image installs the
        # packages from a plain folder instead
        (cd "$debs" && dpkg-scanpackages --multiversion . /dev/null > Packages)
        echo "local repo ready in $debs"
        return
    fi

    say "Publishing the Raye repo"
    local snap
    snap=raye-$SUITE-$(date +%Y%m%d%H%M%S)
    aptly repo show "raye-$SUITE" >/dev/null 2>&1 ||
        aptly repo create -distribution=$SUITE -component=main "raye-$SUITE"
    aptly repo add -force-replace "raye-$SUITE" "$debs" >/dev/null
    aptly snapshot create "$snap" from repo "raye-$SUITE" >/dev/null
    if aptly publish list -raw | grep -q "^raye $SUITE\$"; then
        GNUPGHOME=$GPG_HOME aptly publish switch -force-overwrite \
            -gpg-key="$GPG_KEY" $SUITE raye "$snap" >/dev/null
    else
        GNUPGHOME=$GPG_HOME aptly publish snapshot -force-overwrite \
            -gpg-key="$GPG_KEY" -distribution=$SUITE "$snap" raye >/dev/null
    fi
    echo "published $snap"
}

# ------------------------------------------------------------------ chroot

mounted=()
mount_chroot() {
    local m
    for m in proc sys dev dev/pts run; do
        mkdir -p "$root/$m"
    done
    mount -t proc proc "$root/proc"; mounted+=("$root/proc")
    mount -t sysfs sys "$root/sys"; mounted+=("$root/sys")
    mount --bind /dev "$root/dev"; mounted+=("$root/dev")
    mount --bind /dev/pts "$root/dev/pts"; mounted+=("$root/dev/pts")
    mount -t tmpfs tmpfs "$root/run"; mounted+=("$root/run")
}

umount_chroot() {
    local i
    for (( i=${#mounted[@]}-1; i>=0; i-- )); do
        umount -l "${mounted[$i]}" 2>/dev/null || true
    done
    mounted=()
}
trap umount_chroot EXIT

# never delete a tree that still has /dev or /proc bound inside it
nothing_mounted_under() {
    if [ -d "$1" ] && grep -q " ${1%/}/" /proc/mounts; then
        echo "refusing to clean $1: something is still mounted under it" >&2
        exit 1
    fi
}

in_root() {
    chroot "$root" /usr/bin/env -i HOME=/root TERM=dumb LANG=C.UTF-8 \
        DEBIAN_FRONTEND=noninteractive PATH=/usr/sbin:/usr/bin:/sbin:/bin "$@"
}

bootstrap() {
    say "Bootstrapping $SUITE"
    umount_chroot
    nothing_mounted_under "$root"
    rm -rf "${root:?}"
    mkdir -p "$root"
    local aptopt=()
    [ -n "$PROXY" ] && aptopt=(--aptopt="Acquire::http::Proxy \"$PROXY\"")
    mmdebstrap --mode=root --variant=minbase --keyring="$UBUNTU_KEYRING" \
        --components="main restricted universe multiverse" \
        --include=ca-certificates,ubuntu-keyring,systemd-sysv,apt-utils,gnupg \
        "${aptopt[@]}" \
        $SUITE "$root" "$MIRROR"
}

configure_apt() {
    say "Setting up apt in the image"
    rm -f "${root:?}/etc/apt/sources.list" "${root:?}"/etc/apt/sources.list.d/*
    install -m644 "$here/config/ubuntu.sources" "$root/etc/apt/sources.list.d/ubuntu.sources"
    # ubuntu.sources reads its servers from these; raye-system ships the
    # same files later, apt needs them now
    install -D -m644 "$here/packages/raye-base/release/apt/ubuntu-mirrors.list" \
        "$root/etc/apt/mirrors/ubuntu.list"
    install -D -m644 "$here/packages/raye-base/release/apt/ubuntu-security-mirrors.list" \
        "$root/etc/apt/mirrors/ubuntu-security.list"
    # what ubuntu.sources reads; raye-ubuntu-mirrors writes them again with
    # the country mirror first once the machine has a time zone. Until then
    # they are the lists above, in the same order.
    install -m644 "$root/etc/apt/mirrors/ubuntu.list" \
        "$root/etc/apt/mirrors/ubuntu-nearby.list"
    install -m644 "$root/etc/apt/mirrors/ubuntu-security.list" \
        "$root/etc/apt/mirrors/ubuntu-security-nearby.list"
    # the keyring and release packages bring their own sources and pins,
    # but they come from the Raye repo, so bootstrap that one by hand
    install -m644 "$here/packages/raye-base/keyring/raye-archive-keyring.gpg" \
        "$root/usr/share/keyrings/raye-archive-keyring.gpg"
    if [ "$LOCAL_REPO" = 1 ]; then
        mkdir -p "$root/var/cache/raye-local"
        cp "$WORK"/debs/*.deb "$WORK/debs/Packages" "$root/var/cache/raye-local/"
        echo "deb [trusted=yes] file:/var/cache/raye-local ./" \
            > "$root/etc/apt/sources.list.d/raye-local.list"
        # raye-archive-keyring brings the online Raye source; during the
        # build the packages come from the folder above only (the online
        # repo may not exist yet, or hold other builds of the same versions)
        mkdir -p "$root/etc/dpkg/dpkg.cfg.d"
        echo 'path-exclude=/etc/apt/sources.list.d/raye.sources' \
            > "$root/etc/dpkg/dpkg.cfg.d/99raye-build"
    else
        install -m644 "$here/packages/raye-base/release/apt/raye.sources" \
            "$root/etc/apt/sources.list.d/raye.sources"
    fi
    mkdir -p "$root/etc/apt/apt.conf.d"
    {
        echo 'APT::Install-Recommends "false";'
        echo 'Acquire::Languages "none";'
        if [ -n "$PROXY" ]; then
            echo "Acquire::http::Proxy \"$PROXY\";"
            # a host the cache must not stand in front of (PROXY_DIRECT=host)
            if [ -n "${PROXY_DIRECT:-}" ]; then
                echo "Acquire::http::Proxy::$PROXY_DIRECT \"DIRECT\";"
            fi
            # the cache only speaks http, https sources go straight out
            echo 'Acquire::https::Proxy "DIRECT";'
        fi
    } > "$root/etc/apt/apt.conf.d/99raye-build"
    in_root apt-get update -q
}

# Ubuntu can publish a kernel META-package before the kernel itself.
#
# Measured 2026-11-06, and it cost a 47-minute image build: resolute-updates
# offered linux-generic-hwe-26.04 = 7.0.0-43.43, whose
# linux-image-generic-hwe-26.04 requires linux-modules-7.0.0-43-generic -- a
# package absent from the WHOLE archive, while the complete 42.42 set sat in
# resolute-updates AND resolute-security. linux-meta is built and published
# separately from linux, so the two can be out of step for hours.
#
# apt 3.x does not fall back to the older meta. It picks the newest, finds
# the dependency unsatisfiable, and prints "Reached two conflicting assignments"
# followed by forty lines of unrelated `Depends: ... but it is not going to be
# installed` -- so the real cause, one missing package, is the last thing you
# find. That is why this says it in one line instead.
#
# The version is NOT written out here, and that is the whole point. The
# meta's NAME is read from what raye-system depends on, and the VERSION is the
# newest one apt can actually simulate installing. The day Ubuntu finishes
# publishing, the newest simulates clean, no pin is written, and this function
# does nothing -- the only acceptable shape for a workaround to someone else's
# archive, because a pinned version left behind would freeze every future image
# on an old kernel in silence.
KERNEL_PIN=etc/apt/preferences.d/99raye-build-kernel
pin_installable_kernel() {
    local meta versions v newest chosen=""
    meta=$(in_root apt-cache depends raye-system 2>/dev/null |
           awk '/Depends: linux-/ {print $2; exit}')
    if [ -z "$meta" ]; then
        echo "note: raye-system depends on no linux-* meta-package, nothing to pin"
        return 0
    fi
    versions=$(in_root apt-cache madison "$meta" 2>/dev/null | awk '{print $3}' | uniq)
    [ -n "$versions" ] || { echo "!! no version of $meta in the archive" >&2; return 1; }
    newest=$(printf '%s\n' "$versions" | head -1)
    # \u26a0\ufe0f Each version is PINNED and then simulated, never just named on the
    # command line. Measured: `apt-get install --simulate $meta=7.0.0-42.42`
    # fails even though that version is complete, because its dependency
    # linux-image-generic-hwe-26.04 (= 42.42) would be a DOWNGRADE from that
    # package's own candidate (43.43), and apt will not pick a non-candidate
    # version for a dependency on its own. With the pin in place first, the
    # same simulation passes. Probing without the pin reports every version as
    # broken and makes a working archive look unusable.
    for v in $versions; do
        write_kernel_pin "$meta" "$v"
        if in_root apt-get install -q --simulate "$meta" > /dev/null 2>&1; then
            chosen=$v; break
        fi
    done
    if [ -z "$chosen" ]; then
        rm -f "$root/$KERNEL_PIN"
        echo "!! no version of $meta can be installed at all: the archive is broken for this kernel, not Raye" >&2
        return 1
    fi
    if [ "$chosen" = "$newest" ]; then
        # the newest works: leave NOTHING behind
        rm -f "$root/$KERNEL_PIN"
        echo "ok: $meta $chosen is the newest and installs cleanly"
        return 0
    fi
    echo "!! $meta $newest is published but its kernel packages are NOT in the archive"
    echo "   pinning $chosen for this build only (removed from the image by clean_image)"
    write_kernel_pin "$meta" "$chosen"
}

# Pin-Priority 1001 on purpose: above 1000 is what allows a DOWNGRADE, which is
# exactly what choosing an older meta than the candidate is.
write_kernel_pin() {
    local meta=$1 version=$2
    mkdir -p "$root/etc/apt/preferences.d"
    cat > "$root/$KERNEL_PIN" <<EOF
# Build-time only: clean_image removes this file. $meta was published in a
# newer version than $version without the kernel binary packages it needs, and
# apt 3.x reports a conflict instead of falling back. See
# pin_installable_kernel in iso/build.sh.
Package: $meta ${meta/linux-generic/linux-image-generic} ${meta/linux-generic/linux-headers-generic}
Pin: version $version
Pin-Priority: 1001
EOF
}

# Raye rebuilds a few Ubuntu packages (plasma-workspace, plasma-desktop...) with
# its own patches, versioned "+raye". Two things break the image when Ubuntu
# publishes a newer point release of them, measured on 2026-11-18 (Plasma 6.6.7):
#  - the local build folder has no Release file, so the "o=Raye" pins of
#    raye-pins.pref cannot reach it, and Ubuntu's 6.6.7 beats Raye's 6.6.6;
#  - the other 6.6.7 packages (powerdevil...) need the 6.6.7 libraries, which
#    Raye's 6.6.6 does not provide.
# Same shape as the kernel pin: simulate first, pin only if it fails, and the
# file never ships (clean_image removes it). The real fix is to rebase the Raye
# patches on the new point release; this keeps the image consistent until then.
HOLD_PIN=etc/apt/preferences.d/99raye-build-hold
pin_raye_rebuilds() {
    local dump raye p v hold
    rm -f "$root/$HOLD_PIN"
    if in_root apt-get install -q --simulate "$@" > /dev/null 2>&1; then
        echo "ok: the package list installs without any build pin"
        return 0
    fi
    # every version of every package (apt-cache dumpavail shows the candidate
    # only, which hides the very Raye rebuilds this is about); the local
    # folder is read in place by apt, it is not copied to the lists
    dump=$(cat "$root"/var/lib/apt/lists/*_Packages "$root"/var/cache/raye-local/Packages 2>/dev/null || true)
    raye=$(awk '/^Package:/{p=$2} /^Version:/{if ($2 ~ /\+raye/) print p}' <<<"$dump" | sort -u)
    if [ -z "$raye" ]; then
        echo "!! the package list does not install, and no Raye rebuild is involved" >&2
        in_root apt-get install -q --simulate "$@" 2>&1 | tail -15 >&2
        return 1
    fi
    # Raye's version of each rebuilt package
    declare -A rv=()
    while read -r p v; do rv[$p]=$v; done < <(
        awk '/^Package:/{p=$2} /^Version:/{if ($2 ~ /\+raye/) print p, $2}' <<<"$dump" | sort -V)
    # Ubuntu versions of other packages that need a NEWER build of a rebuilt
    # package than Raye has (powerdevil 6.6.7 needs libkworkspace6-6 >= 6.6.7):
    # those are held, apt falls back to the version that fits. Holding the
    # whole point release is NOT possible: the archive keeps only the newest
    # update, and Raye's own packages were built against parts of it.
    hold=$(awk '/^Package:/{p=$2} /^Source:/{src=$2} /^Version:/{v=$2} /^(Pre-)?Depends:/{d=d","substr($0,index($0,":")+1)}
                /^$/{ if (v !~ /\+raye/) { n=split(d,a,/[,|]/); for(i=1;i<=n;i++) { x=a[i]; if (x !~ /\(>= /) continue
                    nm=x; sub(/^ +/,"",nm); sub(/[ (:].*/,"",nm); mv=x; sub(/.*\(>= */,"",mv); sub(/\).*/,"",mv); print (src ? src : p), v, nm, mv } } p=v=d=src="" }' <<<"$dump" |
        while read -r p v dep min; do
            [ -n "${rv[$dep]:-}" ] || continue
            if dpkg --compare-versions "$min" gt "${rv[$dep]}"; then echo "$p $v"; fi
        done | sort -u) || true
    # a held binary drags its whole source package at that version: powerdevil
    # 6.6.4 needs powerdevil-data (= 6.6.4), so 6.6.7 of the data must go too
    hold=$(awk 'NR==FNR {h[$1" "$2]=1; next}
                /^Package:/{p=$2} /^Source:/{src=$2} /^Version:/{v=$2}
                /^$/{ if (((src ? src : p)" "v) in h) print p, v; p=v=src="" }' \
               <(printf '%s\n' "$hold") - <<<"$dump" | sort -u) || true
    {
        echo "# Build-time only: clean_image removes this file. See pin_raye_rebuilds in iso/build.sh."
        echo "Package: ${!rv[*]}"
        echo "Pin: version /raye/"
        echo "Pin-Priority: 1001"
        while read -r p v; do
            [ -n "$p" ] || continue
            printf '\nPackage: %s\nPin: version %s\nPin-Priority: -1\n' "$p" "$v"
            echo "!! holding $p $v back for this build: it needs a newer Raye rebuild than the one built" >&2
        done <<<"$hold"
    } > "$root/$HOLD_PIN"
    if ! in_root apt-get install -q --simulate "$@" > /dev/null 2>&1; then
        echo "!! still not installable with the build pin:" >&2
        in_root apt-get install -q --simulate "$@" 2>&1 | tail -15 >&2
        return 1
    fi
    echo "ok: installable with the build pin ($HOLD_PIN, removed from the image)"
}

install_system() {
    say "Installing Raye"
    mount_chroot
    # no services starting inside the build
    printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
    chmod +x "$root/usr/sbin/policy-rc.d"

    # raye-release first: it brings the pins that keep snapd and friends out
    in_root apt-get install -y -q raye-release
    in_root apt-get update -q
    # before anything pulls the kernel in by dependency
    pin_installable_kernel
    local pkgs
    mapfile -t pkgs < <(grep -v '^\s*#' "$here/config/live.list" | grep -v '^\s*$')
    pin_raye_rebuilds "${pkgs[@]}"
    in_root apt-get install -y -q "${pkgs[@]}"
    in_root apt-get -y -q full-upgrade

    # the Raye kernel the installed system switches to: its packages travel
    # with the image (NVIDIA's modules for it too) so switching works
    # offline. The live session and the installer keep Ubuntu's signed
    # kernel, which starts with Secure Boot on without any key to enroll.
    if [ -n "${KERNEL_DEBS:-}" ]; then
        local deb
        install -d "$root/usr/share/raye/kernel/debs"
        for deb in "$KERNEL_DEBS"/linux-image-*-raye_*.deb "$KERNEL_DEBS"/linux-headers-*-raye_*.deb \
            "$KERNEL_DEBS"/linux-modules-nvidia-*-raye_*.deb; do
            case "$deb" in *-dbg_*|*\**) continue ;; esac
            install -m644 "$deb" "$root/usr/share/raye/kernel/debs/"
        done
    fi

    install -m644 "$here/config/casper.conf" "$root/etc/casper.conf"
    in_root locale-gen en_US.UTF-8 fr_CA.UTF-8 fr_FR.UTF-8 >/dev/null
    printf 'LANG=en_US.UTF-8\n' > "$root/etc/default/locale"
    echo raye > "$root/etc/hostname"

    in_root update-initramfs -u -k all
    umount_chroot
}

check_image() {
    say "Checking the image"
    local bad=0 p
    for p in snapd apport whoopsie ubuntu-pro-client popularity-contest plasma-discover; do
        if in_root dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'ok installed'; then
            echo "!! $p is installed"; bad=1
        fi
    done
    grep -q '^ID=raye$' "$root/usr/lib/os-release" || { echo "!! os-release is not Raye's"; bad=1; }
    in_root dpkg-query -W -f='${Version}\n' firefox | grep -qv snap ||
        { echo "!! firefox is the snap wrapper"; bad=1; }
    for p in rsync netplan.io; do
        in_root dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'ok installed' ||
            { echo "!! $p is missing"; bad=1; }
    done
    [ -f "$root/etc/netplan/01-network-manager-all.yaml" ] ||
        { echo "!! no netplan config, wired networks would stay unmanaged"; bad=1; }

    # The first login. desktop_debs_needed() asks the SOURCE tree whether the
    # Raye desktop packages are needed; nothing until now asked the IMAGE whether
    # they actually arrived, and the two are not the same question.
    #
    # Measured on 2026-11-05: the image was built from plasma-desktop packages
    # dated 00:27, while the patch adding `Provides: raye-desktop-layout` was
    # committed at 21:12 -- and plasma-workspace, which carries the whole
    # layout-lookup fix, had never been built at all. The image came out looking
    # perfectly normal. An image whose packages came from the archive instead is
    # indistinguishable from a correct one until a new account signs in and finds
    # the upstream taskbar, or no taskbar at all.
    #
    # So each check reads the INSTALLED package and the INSTALLED file, never
    # the source tree or the .deb folder: those can be right while the image is
    # wrong, which is exactly what happened.
    local pkg version
    for pkg in plasma-workspace plasma-desktop-data; do
        version=$(in_root dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null)
        case "$version" in
            *+raye*) ;;
            "") echo "!! $pkg is not installed in the image"; bad=1 ;;
            *) echo "!! $pkg in the image is $version, not a +raye build: this is the archive's package, so the Raye desktop patches are ABSENT from this image"; bad=1 ;;
        esac
    done
    # where libplasma reads a layout that belongs to the desktop itself
    [ -f "$root/usr/share/plasma/shells/org.kde.plasma.desktop/contents/layout.js" ] ||
        { echo "!! no layout.js in the shell package: a new account would start with no taskbar at all"; bad=1; }
    # and the look-and-feel must NOT carry one, or the shape of the bar travels
    # with the colour scheme again -- the defect the whole series undoes
    if ls -d "$root"/usr/share/plasma/look-and-feel/org.raye.*/contents/layouts >/dev/null 2>&1; then
        echo "!! a Raye look-and-feel ships layouts/ again: libplasma reads it FIRST, so switching look would hand the account somebody else's desktop"; bad=1
    fi

    # a French session: a package left out fails nothing, the words stay English
    bash "$here/tests/test_french_session.sh" --root "$root" || bad=1

    [ "$bad" = 0 ] && echo "ok: no snap, no reporters, Raye os-release, Firefox as a deb, Raye desktop packages installed with their layout"
    return "$bad"
}

clean_image() {
    say "Cleaning up"
    nothing_mounted_under "$root"
    # 99mmdebstrap holds the build proxy too, it must not ship
    rm -f "${root:?}/usr/sbin/policy-rc.d" "${root:?}/etc/apt/apt.conf.d/99raye-build" \
          "${root:?}/etc/apt/apt.conf.d/99mmdebstrap" "${root:?}/etc/apt/sources.list.d/raye-local.list"
    rm -rf "${root:?}/var/cache/raye-local"
    rm -f "${root:?}/etc/dpkg/dpkg.cfg.d/99raye-build"
    rm -f "${root:?}/$HOLD_PIN"
    # the build-time kernel pin must never ship: it would freeze the image on an
    # old kernel for ever, and nothing in the image would say why
    rm -f "${root:?}/$KERNEL_PIN"
    install -m644 "$here/packages/raye-base/release/apt/raye.sources" \
        "$root/etc/apt/sources.list.d/raye.sources"
    in_root apt-get clean
    rm -rf "${root:?}"/var/lib/apt/lists/* "${root:?}"/tmp/* "${root:?}"/var/tmp/* \
           "${root:?}"/var/cache/apt/*.bin "${root:?}"/root/.bash_history
    find "${root:?}/var/log" -type f -name '*.log' -delete
    if grep -rqi 'proxy' "$root/etc/apt/apt.conf.d/"; then
        echo "!! an apt proxy is left in the image:" >&2
        grep -rli 'proxy' "$root/etc/apt/apt.conf.d/" >&2
        exit 1
    fi
    : > "$root/etc/machine-id"
    rm -f "${root:?}/var/lib/dbus/machine-id"
    ln -sf ../run/systemd/resolve/stub-resolv.conf "$root/etc/resolv.conf"
}

# Hyprland, the other desktop Setup offers: not in the live system, a flat apt
# folder on the stick that the installer's rayedesktop job installs from, so
# picking it needs no network. Only what the live system lacks is fetched,
# which is what the installed system lacks too. About 5 MB.
gather_desktop_pool() {
    say "Gathering the Hyprland desktop for Setup"
    local pool=$WORK/desktops cache=/var/cache/raye-desktops
    rm -rf "$pool" "${root:?}$cache"
    mkdir -p "$pool" "$root$cache/partial"
    # /etc/resolv.conf of the image is resolved's stub link by now, and the
    # chroot's /run is an empty tmpfs: give it this machine's resolver there.
    # It goes away with the mounts and never reaches the image.
    mkdir -p "$root/run/systemd/resolve"
    cp -L /etc/resolv.conf "$root/run/systemd/resolve/stub-resolv.conf"
    in_root apt-get install -q -y --no-install-recommends --download-only \
        -o Dir::Cache::archives="$cache" raye-hyprland
    mv "$root$cache"/*.deb "$pool/"
    rm -rf "${root:?}$cache"
    # Raye's own packages come from a file: source when LOCAL_REPO=1, and apt
    # uses such a package where it lies, never copying it to the cache
    if ! ls "$pool"/raye-hyprland_*.deb >/dev/null 2>&1; then
        cp "$WORK"/debs/raye-hyprland_*.deb "$pool/"
    fi
    (cd "$pool" && dpkg-scanpackages --multiversion . /dev/null > Packages 2>/dev/null)
    grep -qx 'Package: raye-hyprland' "$pool/Packages" ||
        die "raye-hyprland is not in the desktop pool: Setup would offer a Hyprland it cannot install offline"
    echo "ok: desktop pool, $(grep -c '^Package:' "$pool/Packages") packages, $(du -sh "$pool" | cut -f1)"
}

# --------------------------------------------------------------------- ISO

make_iso() {
    say "Laying out the ISO"
    umount_chroot
    rm -rf "${iso:?}"
    mkdir -p "$iso"/{casper,.disk,boot/grub/fonts,boot/grub/themes,EFI/BOOT}

    local kver
    kver=$(find "$root/boot" -maxdepth 1 -name 'vmlinuz-*' -printf '%f\n' | sed 's/^vmlinuz-//' | sort -V | tail -1)
    cp "$root/boot/vmlinuz-$kver" "$iso/casper/vmlinuz"
    cp "$root/boot/initrd.img-$kver" "$iso/casper/initrd"

    in_root dpkg-query -W --showformat='${Package} ${Version}\n' > "$iso/casper/filesystem.manifest"
    grep -E '^(casper|calamares|calamares-settings-raye|libcalamares[^ ]*|calamares-data) ' \
        "$iso/casper/filesystem.manifest" | cut -d' ' -f1 > "$iso/casper/filesystem.manifest-remove"
    du -sx --block-size=1 "$root" | cut -f1 > "$iso/casper/filesystem.size"

    if [ -f "$WORK/desktops/Packages" ]; then
        mkdir -p "$iso/raye"
        cp -r "$WORK/desktops" "$iso/raye/desktops"
    fi

    say "Packing the squashfs (this is the slow part)"
    mksquashfs "$root" "$iso/casper/filesystem.squashfs" \
        -comp zstd -Xcompression-level 15 -b 1M -noappend -quiet -mem 1G -processors 3

    echo "Raye Linux $version - amd64 ($stamp)" > "$iso/.disk/info"
    touch "$iso/.disk/base_installable"
    echo "full_cd/single" > "$iso/.disk/cd_type"

    # Secure Boot chain: Microsoft-signed shim, then the signed CD GRUB
    if [ -f "$root/usr/lib/shim/shimx64.efi.signed.latest" ]; then
        cp "$root/usr/lib/shim/shimx64.efi.signed.latest" "$iso/EFI/BOOT/BOOTX64.EFI"
    else
        cp "$root/usr/lib/shim/shimx64.efi.signed" "$iso/EFI/BOOT/BOOTX64.EFI"
    fi
    cp "$root/usr/lib/shim/mmx64.efi" "$iso/EFI/BOOT/mmx64.efi"
    cp "$root/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed" "$iso/EFI/BOOT/grubx64.efi"
    cp "$here/boot/grub/grub.cfg" "$iso/boot/grub/grub.cfg"
    if [ -f "$root/usr/share/grub/unicode.pf2" ]; then
        cp "$root/usr/share/grub/unicode.pf2" "$iso/boot/grub/fonts/"
    fi
    # the menu's look: theme and its text pictures from here, background,
    # eye and highlight from grub-theme-raye so it matches the installed one
    local theme=$iso/boot/grub/themes/raye f
    cp -r "$here/boot/grub/themes/raye" "$iso/boot/grub/themes/"
    for f in background.png logo.png select_c.png select_e.png select_w.png; do
        cp "$root/usr/share/grub/themes/raye/$f" "$theme/"
    done

    # BIOS boot for old PCs, laid out like Ubuntu's own image: GRUB's El
    # Torito image, its modules (grub.cfg loads vbe there), and the hybrid
    # MBR so a USB stick starts in BIOS mode too. grub-pc-bin comes with
    # raye-system; without it the image would quietly be UEFI-only.
    local bios=$root/usr/lib/grub/i386-pc
    [ -f "$bios/boot_hybrid.img" ] || die "grub-pc-bin is missing from the image: no BIOS boot"
    mkdir -p "$iso/boot/grub/i386-pc"
    cp "$bios"/*.mod "$bios"/*.lst "$iso/boot/grub/i386-pc/"
    chroot "$root" grub-mkimage -O i386-pc-eltorito -d /usr/lib/grub/i386-pc -p /boot/grub \
        -o /tmp/raye-eltorito.img biosdisk iso9660 part_msdos part_gpt search \
        normal configfile linux echo test font gfxterm vbe all_video sleep reboot
    mv "$root/tmp/raye-eltorito.img" "$iso/boot/grub/i386-pc/eltorito.img"

    # A stick written with a tool that changed it fails this check, from
    # the "Check the USB stick for errors" entry (casper integrity-check)
    (cd "$iso" && find . -type f ! -name md5sum.txt -print0 | sort -z | xargs -0 md5sum > md5sum.txt)

    # FAT image with the same EFI files, used as the El Torito EFI boot
    # image and as the ESP when the ISO is written to a USB stick
    local efi=$WORK/efi.img
    rm -f "${efi:?}"
    mkfs.vfat -C -n RAYE_EFI "$efi" 8192 >/dev/null
    mmd -i "$efi" ::/EFI ::/EFI/BOOT ::/boot ::/boot/grub ::/.disk
    mcopy -i "$efi" "$iso"/EFI/BOOT/* ::/EFI/BOOT/
    mcopy -i "$efi" "$iso/boot/grub/grub.cfg" ::/boot/grub/
    mcopy -i "$efi" "$iso/.disk/info" ::/.disk/info

    say "Writing $name.iso"
    mkdir -p "$OUT"
    xorriso -as mkisofs -r -J -joliet-long -iso-level 3 \
        -V "$volume" -o "$OUT/$name.iso" \
        --grub2-mbr "$bios/boot_hybrid.img" -partition_offset 16 --mbr-force-bootable \
        -append_partition 2 0xef "$efi" -appended_part_as_gpt \
        -iso_mbr_part_type a2a0d0eb-e5b9-3344-87c0-68b6b72699c7 \
        -c /boot.catalog \
        -b /boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
        -eltorito-alt-boot \
        -e --interval:appended_partition_2:all:: -no-emul-boot \
        "$iso"

    (cd "$OUT" && sha256sum "$name.iso" > "$name.iso.sha256")
    # [ -d ] first: gpg would create an empty keyring where there is none
    if [ -d "$GPG_HOME" ] &&
            GNUPGHOME=$GPG_HOME gpg --batch --list-secret-keys "$GPG_KEY" >/dev/null 2>&1; then
        GNUPGHOME=$GPG_HOME gpg --batch --yes --local-user "$GPG_KEY!" \
            --armor --detach-sign "$OUT/$name.iso.sha256"
    else
        echo "no archive key here: $name.iso.sha256 is not signed (tools/release-files signs the release)"
    fi
    ls -lh "$OUT/$name.iso"
}

# -------------------------------------------------------------------- main

[ "$(id -u)" = 0 ] || { echo "run me as root" >&2; exit 1; }
mkdir -p "$WORK"

case "${1:-all}" in
    packages) build_packages ;;
    all)
        build_packages
        bootstrap
        configure_apt
        install_system
        mount_chroot; check_image; gather_desktop_pool; umount_chroot
        clean_image
        make_iso
        ;;
    iso) make_iso ;;
    compiled)
        # only build the compiled packages, to try them out; nothing is published
        mkdir -p "$WORK/debs-compiled"
        for dir in $(compiled_sources); do
            build_compiled "$dir" "$WORK/debs-compiled"
        done
        ls -1 "$WORK/debs-compiled"
        ;;
    *) echo "usage: $0 [all|packages|iso|compiled]" >&2; exit 2 ;;
esac
