#!/bin/sh
# Checks release/tuning/raye-vm-cursor: in a virtual machine the desktop
# draws the pointer itself, because a virtual GPU's cursor plane is not
# shown in the console or over SPICE and the pointer is simply invisible.
# On real hardware it must change nothing: a pointer drawn by the desktop
# lags behind the hand and costs a redraw of the screen at every move.
#
#   sh release/tuning/tests/test-raye-vm-cursor.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
gen=$here/../raye-vm-cursor
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-cursor.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0
mkdir -p "$work/bin"

# Without this, "nothing is set" passes while the generator is missing:
# an absent file prints nothing too.
[ -f "$gen" ] || { echo "FAIL $gen is missing"; exit 1; }

# stand-in for systemd-detect-virt: says what we tell it to say
fake() { # what it prints, what it exits with
    printf '#!/bin/sh\nprintf "%%s\\n" "%s"\nexit %s\n' "$1" "$2" > "$work/bin/systemd-detect-virt"
    chmod +x "$work/bin/systemd-detect-virt"
}

# PATH is the stand-in folder ALONE, never the system one: the machine
# that runs this test is itself a virtual machine, so falling through to
# the real systemd-detect-virt would answer "kvm" and prove nothing.
check() { # name, expected output (empty for none)
    rc=0
    got=$(PATH=$work/bin /bin/sh "$gen" 2>"$work/err") || rc=$?
    if [ "$got" = "$2" ] && [ "$rc" = 0 ]; then
        echo "ok   $1"
    else
        echo "FAIL $1 (said '$got', exit $rc)"; sed 's/^/     /' "$work/err"
        failures=$((failures + 1))
    fi
}

fake kvm 0
check "a virtual machine: the desktop draws the pointer" "KWIN_FORCE_SW_CURSOR=1"
fake qemu 0
check "plain qemu: same" "KWIN_FORCE_SW_CURSOR=1"
fake microsoft 0
check "another hypervisor: same" "KWIN_FORCE_SW_CURSOR=1"
fake none 1
check "real hardware: nothing is set" ""

# systemd-detect-virt exits 1 when it finds nothing, which is not a
# failure; and it may be missing entirely in a container image.
rm -f "$work/bin/systemd-detect-virt"
check "no systemd-detect-virt at all: nothing is set, no error" ""

fake "" 0
check "an empty answer counts as real hardware" ""

echo
if [ "$failures" = 0 ]; then echo "all good"; else echo "$failures failed"; exit 1; fi
