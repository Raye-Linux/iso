#!/bin/sh
# Checks release/tuning/70-raye-serial.rules: valid for udev, it gives the
# person at the computer USB serial adapters, boards and real COM ports
# (Windows programs see them as COM ports), never the empty 8250 nodes, and
# it runs before 73-seat-late, which turns the uaccess tag into an ACL.
#
#   sh release/tuning/tests/test-serial-access.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
rules=$here/../70-raye-serial.rules
paths=$here/../../../debian/raye-release-paths
failures=0
ok() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

[ -f "$rules" ] || { echo "FAIL 70-raye-serial.rules is missing"; exit 1; }
if command -v udevadm >/dev/null 2>&1 && udevadm verify --help >/dev/null 2>&1; then
    if udevadm verify "$rules" >/dev/null 2>&1; then ok "udevadm verify"; else fail "udevadm verify"; fi
fi

body=$(grep -v '^#' "$rules" | grep .)
case $body in *'KERNEL=="ttyUSB[0-9]*|ttyACM[0-9]*", TAG+="uaccess"'*) ok "USB adapters and boards" ;;
    *) fail "USB adapters and boards" ;; esac
case $body in *'KERNEL=="ttyS[0-9]*", ATTR{type}!="0", TAG+="uaccess"'*) ok "only real COM ports" ;;
    *) fail "only real COM ports" ;; esac
printf '%s\n' "$body" | grep -v 'SUBSYSTEM=="tty"' | grep -q . && fail "a rule outside tty" || ok "tty only"
printf '%s\n' "$body" | grep -qE 'MODE|GROUP|OWNER|RUN|ENV' && fail "more than the uaccess tag" || ok "only tags"
n=$(basename "$rules" | cut -d- -f1)
[ "$n" -lt 73 ] && ok "before 73-seat-late" || fail "numbered $n, after 73-seat-late"
grep -qE "release/tuning/70-raye-serial.rules[[:space:]]+usr/lib/udev/rules.d/70-raye-serial.rules" "$paths" \
    && ok "shipped in udev/rules.d" || fail "not in debian/raye-release-paths"

[ "$failures" = 0 ] || exit 1
