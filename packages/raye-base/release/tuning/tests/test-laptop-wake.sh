#!/bin/sh
# Checks release/tuning/60-raye-laptop-wake.rules: valid for udev, and it
# only turns off waking for wired cards on laptop chassis types.
#
#   sh release/tuning/tests/test-laptop-wake.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
rules=$here/../60-raye-laptop-wake.rules
failures=0
ok() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

if command -v udevadm >/dev/null 2>&1 && udevadm verify --help >/dev/null 2>&1; then
    if udevadm verify "$rules" >/dev/null 2>&1; then ok "udevadm verify"; else fail "udevadm verify"; fi
fi

rule=$(grep -v '^#' "$rules" | grep .)
[ "$(printf '%s\n' "$rule" | wc -l)" = 1 ] && ok "one rule" || fail "one rule"
for want in 'ACTION=="add"' 'SUBSYSTEM=="pci"' 'ATTR{class}=="0x020000"' 'ATTR{power/wakeup}="disabled"'; do
    case $rule in *"$want"*) ok "has $want" ;; *) fail "has $want" ;; esac
done

# SMBIOS chassis types: 8 portable, 9 laptop, 10 notebook, 14 sub notebook,
# 30 tablet, 31 convertible, 32 detachable; never a desktop (3) or tower (7)
types=$(printf '%s\n' "$rule" | sed -n 's/.*chassis_type}=="\([0-9|]*\)".*/\1/p')
[ "$types" = "8|9|10|14|30|31|32" ] && ok "laptop chassis types" || fail "laptop chassis types: $types"

[ "$failures" = 0 ] || exit 1
