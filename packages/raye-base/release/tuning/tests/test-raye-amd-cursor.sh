#!/bin/sh
# Checks release/tuning/raye-amd-cursor against made-up /sys trees.
#
# On an AMD card driven by amdgpu, a kernel without the RGBA8888 fix
# refuses KWin's commits ("Unsupported screen format RA24") and the screen
# stays black; the desktop and the sign-in screen draw the pointer
# themselves there. Nowhere else: a pointer drawn by the desktop lags one
# frame behind the hand.
#
#   sh release/tuning/tests/test-raye-amd-cursor.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
tool=$here/../raye-amd-cursor
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-amd-cursor.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0

[ -f "$tool" ] || { echo "FAIL $tool is missing"; exit 1; }

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

# A fresh machine: a kernel release, a package version for it (empty: not
# installed), and stand-ins for uname, dpkg-query, dpkg and modprobe.
machine() { # kernel release, package version
    rm -r -f -- "$work/sys" "$work/bin"
    mkdir -p "$work/sys/class/drm" "$work/sys/bus/pci/drivers" \
             "$work/sys/devices" "$work/sys/module" "$work/bin"
    printf '#!/bin/sh\necho %s\n' "$1" > "$work/bin/uname"
    if [ -n "$2" ]; then
        printf '#!/bin/sh\nprintf %%s %s\n' "$2" > "$work/bin/dpkg-query"
    else
        printf '#!/bin/sh\nexit 1\n' > "$work/bin/dpkg-query"
    fi
    # the real comparison, the only one that matters
    printf '#!/bin/sh\nexec /usr/bin/dpkg "$@"\n' > "$work/bin/dpkg"
    printf '#!/bin/sh\nexit 0\n' > "$work/bin/modprobe"
    chmod +x "$work/bin/"*
}

# gpu NAME VENDOR DRIVER [CONNECTORS...]: a display PCI device as card NAME
gpu() {
    name=$1 vendor=$2 driver=$3
    shift 3
    dev=$work/sys/devices/pci0000:00/0000:0$name:00.0
    mkdir -p "$dev"
    echo "$vendor" > "$dev/vendor"
    echo 0x030000 > "$dev/class"
    echo "pci:v0000${vendor#0x}d000067FFsv00001DA2sd0000E366bc03sc00i00" > "$dev/modalias"
    if [ "$driver" != - ]; then
        mkdir -p "$work/sys/bus/pci/drivers/$driver"
        ln -s "../../../bus/pci/drivers/$driver" "$dev/driver"
        mkdir -p "$work/sys/class/drm/card$name"
        ln -s "../../../devices/pci0000:00/0000:0$name:00.0" "$work/sys/class/drm/card$name/device"
        for c in "$@"; do mkdir -p "$work/sys/class/drm/card$name-$c"; done
    fi
    mkdir -p "$work/sys/bus/pci/devices"
    ln -s "../../../devices/pci0000:00/0000:0$name:00.0" "$work/sys/bus/pci/devices/0000:0$name:00.0"
}

dc_param() { mkdir -p "$work/sys/module/amdgpu/parameters"; echo "$1" > "$work/sys/module/amdgpu/parameters/dc"; }
aliases() { printf '#!/bin/sh\nprintf "%%s\\n" %s\n' "$*" > "$work/bin/modprobe"; chmod +x "$work/bin/modprobe"; }

run() { # args...; output in $got, exit status in $rc
    rc=0
    got=$(env -i PATH="$work/bin" RAYE_SYS="$work/sys" ${KWIN_FORCE_SW_CURSOR+KWIN_FORCE_SW_CURSOR="$KWIN_FORCE_SW_CURSOR"} \
          /bin/sh "$tool" "$@" 2>"$work/err") || rc=$?
}
says() { # name, expected generator output
    run
    if [ "$got" = "$2" ] && [ "$rc" = 0 ]; then ok "$1"
    else bad "$1 (said '$got', exit $rc)"; sed 's/^/     /' "$work/err"; fi
}
covered() { # name, expected exit status of --covered
    run --covered
    if [ "$rc" = "$2" ]; then ok "$1"; else bad "$1 (exit $rc, wanted $2)"; sed 's/^/     /' "$work/err"; fi
}

ON=KWIN_FORCE_SW_CURSOR=1

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1 HDMI-A-1
says "AMD card on Ubuntu's kernel: the desktop draws the pointer" "$ON"
covered "AMD card driven by amdgpu is covered" 0

machine 7.0.14-raye 7.0.0-43.43+raye2
gpu 1 0x1002 amdgpu DP-1
says "Raye kernel without the fix: same" "$ON"

machine 7.0.14-raye 7.0.0-43.43+raye3
gpu 1 0x1002 amdgpu DP-1
says "Raye kernel with the fix: nothing is set" ""
covered "the GPU is still covered (for the boot menu reset)" 0

machine 7.0.14-raye 7.0.0-44.44+raye1
gpu 1 0x1002 amdgpu DP-1
says "a later Raye kernel keeps the fix" ""

machine 7.0.14-raye ""
gpu 1 0x1002 amdgpu DP-1
says "a Raye kernel dpkg does not know: treated as unfixed" "$ON"

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x8086 i915 eDP-1
says "Intel graphics: nothing is set" ""
covered "Intel graphics is not covered" 1

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x8086 i915 eDP-1
gpu 2 0x1002 amdgpu
says "AMD card with no outputs behind Intel: nothing is set" ""

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x8086 i915 eDP-1
gpu 2 0x1002 amdgpu HDMI-A-1
says "AMD card with its own outputs next to Intel: set" "$ON"

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 radeon DVI-I-1
says "older AMD card on radeon: nothing is set" ""
covered "older AMD card on radeon is not covered" 1

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1
dc_param 0
says "amdgpu.dc=0 (the older display path): nothing is set" ""
covered "amdgpu.dc=0: still covered, the boot menu may try the normal path" 0

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1
dc_param -1
says "amdgpu.dc left at its default: set" "$ON"

# nomodeset: amdgpu does not load, the card has no driver at all
machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 -
aliases amdgpu
covered "nomodeset, a card amdgpu takes: covered" 0
says "nomodeset: no DRM card, nothing is set" ""
aliases radeon amdgpu
covered "nomodeset, a card radeon also claims: not covered" 1
aliases amdgpu radeon
covered "nomodeset, radeon listed after amdgpu: not covered" 1
aliases
covered "nomodeset, a card no module knows: not covered" 1

machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1
KWIN_FORCE_SW_CURSOR=0
says "the user said 0 (environment.d): left alone" ""
KWIN_FORCE_SW_CURSOR=1
says "the user said 1: left alone, not said twice" ""
unset KWIN_FORCE_SW_CURSOR

machine 7.0.0-43-generic 7.0.0-43.43
says "no graphics card at all: nothing is set, no error" ""
covered "no graphics card: not covered" 1
rm -r -f -- "$work/sys"
says "no /sys at all: nothing is set, no error" ""

# wrapper mode, for the sign-in screen's KWin
printf '#!/bin/sh\necho "args=$*"\necho "cursor=${KWIN_FORCE_SW_CURSOR-unset}"\n' > "$work/show"
chmod +x "$work/show"
machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1
run "$work/show" --drm --locale1
want=$(printf 'args=--drm --locale1\ncursor=1')
if [ "$got" = "$want" ] && [ "$rc" = 0 ]; then ok "wrapper: AMD, the compositor gets the variable and its arguments"
else bad "wrapper on AMD (said '$got', exit $rc)"; fi
machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x8086 i915 eDP-1
run "$work/show" --drm
want=$(printf 'args=--drm\ncursor=unset')
if [ "$got" = "$want" ] && [ "$rc" = 0 ]; then ok "wrapper: Intel, the compositor runs untouched"
else bad "wrapper on Intel (said '$got', exit $rc)"; fi
machine 7.0.0-43-generic 7.0.0-43.43
gpu 1 0x1002 amdgpu DP-1
KWIN_FORCE_SW_CURSOR=0
run "$work/show"
unset KWIN_FORCE_SW_CURSOR
want=$(printf 'args=\ncursor=0')
if [ "$got" = "$want" ]; then ok "wrapper: a value already set wins"
else bad "wrapper with a value set (said '$got')"; fi

# The sign-in screen: its KWin goes through the wrapper, with the same
# command as the theme's sddm-raye.conf, from a file SDDM reads later.
conf=$here/../sddm-wayland-raye.conf
cmd=$(sed -n 's/^CompositorCommand=//p' "$conf")
case $cmd in
"/usr/libexec/raye-amd-cursor-guard kwin_wayland "*) ok "sign-in KWin goes through the wrapper (by its guard)" ;;
*) bad "sign-in KWin command: '$cmd'" ;;
esac
paths=$here/../../../debian/raye-release-paths
dest=$(awk '$2 == "release/tuning/sddm-wayland-raye.conf" { print $3 }' "$paths")
name=${dest##*/}
if [ "${dest%/*}" = etc/sddm.conf.d ] && [ "$name" \> sddm-raye.conf ] && [ "$name" \> sddm-theme-raye.conf ]; then
    ok "read after the theme's files ($name)"
else
    bad "sddm file lands at '$dest'"
fi
grep -q '^usr/libexec/raye-amd-cursor-guard usr/lib/systemd/user-environment-generators/' \
    "$here/../../../debian/raye-desktop.links" &&
    ok "the session gets it as a user-environment generator" ||
    bad "no generator link in raye-desktop.links"
# Where the theme sits next to this repository, the rest of the command
# must be its own; elsewhere (a source package) there is nothing to read.
theme=$here/../../../../../../theme/config/sddm-raye.conf
if [ -r "$theme" ]; then
    want=$(sed -n 's/^CompositorCommand=//p' "$theme")
    if [ "${cmd#/usr/libexec/raye-amd-cursor-guard }" = "$want" ]; then ok "same command as the theme's sddm-raye.conf"
    else bad "the theme says '$want', here '${cmd#* }'"; fi
fi

echo
if [ "$failures" = 0 ]; then echo "all good"; else echo "$failures failed"; exit 1; fi
