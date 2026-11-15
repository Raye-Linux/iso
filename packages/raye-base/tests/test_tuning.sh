#!/bin/sh
# Checks the tuning files of release/tuning/ before they ship:
#   - 90-raye.conf (sysctl): one comment above each setting, no key twice,
#     every key known to the running kernel, the values Raye wants, and
#     nothing Ubuntu already sets;
#   - the udev rules pass "udevadm verify", and spinning disks get bfq;
#   - the tmpfiles line is valid ("systemd-tmpfiles --dry-run" only: run
#     for real as root it would write to /sys);
#   - modules-load files hold module names only;
#   - every file is shipped by a line of debian/raye-release-paths.
#
# Usage: tests/test_tuning.sh   (from anywhere; exit 0 = all good)
# TUNING_DIR and PROC_SYS point the checks somewhere else (to test the test;
# PROC_SYS=/nonexistent skips the check against the running kernel).

set -u

here=$(cd "$(dirname "$0")/.." && pwd)
TUNING_DIR=${TUNING_DIR:-$here/release/tuning}
PROC_SYS=${PROC_SYS:-/proc/sys}
PATHS=$here/debian/raye-release-paths

failed=0
fail() { echo "FAIL: $*"; failed=1; }
pass() { echo "ok:   $*"; }
skip() { echo "skip: $*"; }

# ---------------------------------------------------------------- sysctl
sysctl_file=$TUNING_DIR/90-raye.conf

# key<TAB>value of every setting, the "-" (ignore errors) prefix dropped
settings() {
	sed -n 's/^[[:space:]]*-\{0,1\}\([^#;=[:space:]][^=[:space:]]*\)[[:space:]]*=[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/\1\t\2/p' "$1"
}

value_of() {
	settings "$sysctl_file" | awk -F '\t' -v k="$1" '$1 == k { print $2 }'
}

if [ ! -f "$sysctl_file" ]; then
	fail "90-raye.conf is missing"
else
	# a line is a comment, blank, or "key = value"; nothing else
	bad=$(grep -nvE '^[[:space:]]*([#;].*)?$|^[[:space:]]*-?[A-Za-z0-9_./-]+[[:space:]]*=[[:space:]]*[^[:space:]]' "$sysctl_file")
	[ -z "$bad" ] && pass "90-raye.conf: every line parses" || fail "90-raye.conf: lines that do not parse: $bad"

	dup=$(settings "$sysctl_file" | cut -f1 | sort | uniq -d)
	[ -z "$dup" ] && pass "90-raye.conf: no key set twice" || fail "90-raye.conf: keys set twice: $dup"

	# the line before each setting is a comment
	nocomment=$(awk '
		/^[[:space:]]*-?[A-Za-z0-9_./-]+[[:space:]]*=/ {
			if (prev !~ /^[[:space:]]*[#;]/) print NR ": " $0
		}
		{ prev = $0 }' "$sysctl_file")
	[ -z "$nocomment" ] && pass "90-raye.conf: each setting has its comment" \
		|| fail "90-raye.conf: settings without a comment above: $nocomment"

	# sysctl.d: "/" separates when the key holds one, else "."
	if [ -d "$PROC_SYS/kernel" ]; then
		out=$(settings "$sysctl_file" | cut -f1 | while read -r key; do
			case $key in
				*/*) path=$key ;;
				*) path=$(printf %s "$key" | tr . /) ;;
			esac
			if [ -e "$PROC_SYS/$path" ]; then
				echo "ok:   $key exists under $PROC_SYS"
			else
				echo "FAIL: $key: no $PROC_SYS/$path on this kernel"
			fi
		done)
		echo "$out"
		case $out in *FAIL:*) failed=1 ;; esac
	else
		skip "no $PROC_SYS: keys not checked against a kernel"
	fi

	want() {
		got=$(value_of "$1")
		[ "$got" = "$2" ] && pass "$1 = $2" || fail "$1 is '${got}', want '$2'"
	}
	want vm.swappiness 150
	want vm.page-cluster 0
	want kernel.split_lock_mitigate 0
	want net.core.default_qdisc fq
	want net.ipv4.tcp_congestion_control bbr
	want kernel.printk '3 4 1 3'

	# Ubuntu's procps already sets it (55-map-count.conf): one owner only
	[ -z "$(value_of vm.max_map_count)" ] && pass "vm.max_map_count left to Ubuntu" \
		|| fail "vm.max_map_count is set again (Ubuntu's 55-map-count.conf owns it)"
fi

# ------------------------------------------------------------------ zram
zram=$TUNING_DIR/50-raye.conf
if [ -f "$zram" ] && grep -q '^\[zram0\]' "$zram" \
	&& grep -qE '^zram-size[[:space:]]*=[[:space:]]*min\(ram, 8192\)' "$zram" \
	&& grep -qE '^compression-algorithm[[:space:]]*=[[:space:]]*zstd' "$zram"; then
	pass "50-raye.conf: zram0, up to the size of the RAM and 8 GiB at most, zstd"
else
	# min(ram, 8192), not min(ram / 2, 8192). The half-RAM value was the
	# original one; it was raised deliberately on 2026-11-01 (12e850e,
	# "perf(raye-base): lighter at idle" -- "zram can grow to the size of the
	# RAM, 8G at most"), and this check stayed behind for five days because
	# NOTHING RAN IT. Found on 2026-11-06 by the first run of tools/raye-tests.
	# If this fires, read 50-raye.conf first: the config is the decision, this
	# line only follows it.
	fail "50-raye.conf: zram0 with min(ram, 8192) and zstd expected"
fi

# ------------------------------------------------------------------ udev
if command -v udevadm >/dev/null 2>&1 && udevadm verify --help >/dev/null 2>&1; then
	for r in "$TUNING_DIR"/*.rules; do
		[ -f "$r" ] || continue
		if out=$(udevadm verify --resolve-names=never "$r" 2>&1); then
			pass "udevadm verify $(basename "$r")"
		else
			fail "udevadm verify $(basename "$r"): $out"
		fi
	done
else
	skip "udevadm verify not available: rules not checked by udev"
fi

iosched=$TUNING_DIR/60-raye-iosched.rules
if [ ! -f "$iosched" ]; then
	fail "60-raye-iosched.rules is missing"
else
	# the rule lines, comments and continuations left out
	body=$(grep -vE '^[[:space:]]*(#|$)' "$iosched")
	if printf %s "$body" | grep -q 'ATTR{queue/rotational}=="1"' \
		&& printf %s "$body" | grep -q 'ATTR{queue/scheduler}="bfq"'; then
		pass "spinning disks get bfq"
	else
		fail "60-raye-iosched.rules: rotational==1 -> scheduler bfq expected"
	fi
	# SSDs and NVMe keep the kernel's choice (mq-deadline, none)
	if printf %s "$body" | grep -q 'ATTR{queue/rotational}=="0"'; then
		fail "60-raye-iosched.rules touches non-rotational disks"
	else
		pass "SSDs and NVMe keep the kernel's scheduler"
	fi
	printf %s "$body" | grep -q 'ACTION=="add|change"' \
		&& pass "rule runs on add and change" \
		|| fail "60-raye-iosched.rules: ACTION==\"add|change\" expected"
fi

# -------------------------------------------------------------- tmpfiles
mglru=$TUNING_DIR/raye-mglru.conf
if [ ! -f "$mglru" ]; then
	fail "raye-mglru.conf is missing"
else
	if grep -qE '^w-?[[:space:]]+/sys/kernel/mm/lru_gen/min_ttl_ms[[:space:]]+-[[:space:]]+-[[:space:]]+-[[:space:]]+-[[:space:]]+1000[[:space:]]*$' "$mglru"; then
		pass "MGLRU min_ttl_ms = 1000"
	else
		fail "raye-mglru.conf: 'w /sys/kernel/mm/lru_gen/min_ttl_ms - - - - 1000' expected"
	fi
	# only ever --dry-run: as root the real run would write /sys
	if command -v systemd-tmpfiles >/dev/null 2>&1 \
		&& systemd-tmpfiles --help 2>/dev/null | grep -q -- '--dry-run'; then
		if out=$(systemd-tmpfiles --dry-run --create "$mglru" 2>&1); then
			pass "systemd-tmpfiles --dry-run accepts raye-mglru.conf"
		else
			fail "systemd-tmpfiles --dry-run raye-mglru.conf: $out"
		fi
	else
		skip "systemd-tmpfiles --dry-run not available"
	fi
fi

# ---------------------------------------------------------- modules-load
for m in "$TUNING_DIR"/raye-ntsync.conf "$TUNING_DIR"/raye-net.conf; do
	[ -f "$m" ] || continue
	bad=$(grep -vE '^[[:space:]]*([#;].*)?$|^[a-z0-9_-]+$' "$m")
	[ -z "$bad" ] && pass "$(basename "$m"): module names only" \
		|| fail "$(basename "$m"): not a module name: $bad"
done

# ---------------------------------------------------------------- ntsync
# The Windows layer opens /dev/ntsync when it can: the module is loaded at
# boot and the person at the computer gets it through logind's ACL, the
# way udev's own rules hand out sound and video. The kernel already makes
# the device 0666; the rule must not widen anything further.
nts=$TUNING_DIR/raye-ntsync.conf ntr=$TUNING_DIR/60-raye-ntsync.rules
if grep -qx 'ntsync' "$nts"; then pass "ntsync loaded at boot"
else fail "raye-ntsync.conf does not load ntsync"; fi
if grep -qE '^KERNEL=="ntsync",[[:space:]]*TAG\+="uaccess"$' "$ntr"; then
	pass "ntsync given to the person at the computer"
else
	fail "60-raye-ntsync.rules: no KERNEL==\"ntsync\", TAG+=\"uaccess\" line"
fi
if grep -vE '^[[:space:]]*(#.*)?$' "$ntr" | grep -qE 'MODE|GROUP|OWNER|RUN'; then
	fail "60-raye-ntsync.rules sets more than the uaccess tag"
else
	pass "60-raye-ntsync.rules only tags the device"
fi
grep -qE "release/tuning/raye-ntsync.conf[[:space:]]+usr/lib/modules-load.d/" "$PATHS" \
	&& pass "raye-ntsync.conf goes to modules-load.d" \
	|| fail "raye-ntsync.conf not installed in modules-load.d"
grep -qE "release/tuning/60-raye-ntsync.rules[[:space:]]+usr/lib/udev/rules.d/" "$PATHS" \
	&& pass "60-raye-ntsync.rules goes to udev/rules.d" \
	|| fail "60-raye-ntsync.rules not installed in udev/rules.d"

# --------------------------------------------------------------- shipped
if [ -f "$PATHS" ]; then
	for f in "$TUNING_DIR"/*; do
		[ -f "$f" ] || continue
		name=$(basename "$f")
		if grep -qE "^[a-z0-9-]+[[:space:]]+\??release/tuning/$name[[:space:]]" "$PATHS"; then
			pass "$name is shipped"
		else
			fail "$name has no line in debian/raye-release-paths"
		fi
	done
else
	skip "no debian/raye-release-paths next to the tests"
fi

[ "$failed" -eq 0 ] && echo "all tuning checks passed"
exit "$failed"
