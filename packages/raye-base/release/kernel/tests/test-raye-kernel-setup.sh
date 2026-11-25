#!/bin/sh
# Tests of raye-kernel-setup: each step of the switch (enroll, trial
# boot kept or failed, offline, remove, rebind, status) on a fake root,
# with mokutil, clevis, apt, GRUB, nm-online and raye-tpm replaced by
# stubs that record their calls.
#
#   sh release/kernel/tests/test-raye-kernel-setup.sh
# The checks are strings run by eval, so they expand late on purpose.
# shellcheck disable=SC2016,SC2034
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../raye-kernel-setup
pass=0
fail=0
current=

uuid=0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0
raye=7.0.0-42-raye
ubuntu=7.0.0-42-generic

# ------------------------------------------------------------- the stubs
write_stubs() {
    bin=$1
    mkdir -p "$bin"
    cat > "$bin/mokutil" <<'STUB'
#!/bin/sh
echo "mokutil $*" >> "$CALLS"
case "$1" in
--sb-state) [ -e "$CTL/sb" ] && echo "SecureBoot enabled" || echo "SecureBoot disabled" ;;
--test-key) [ -e "$CTL/enrolled" ] && echo "$2 is already enrolled" || echo "$2 is not enrolled" ;;
--generate-hash=*) echo '$6$salt$hash' ;;
--import) [ -e "$CTL/import-fails" ] && exit 1; exit 0 ;;
--list-new) [ -e "$CTL/list-new" ] && cat "$CTL/list-new"; exit 0 ;;
esac
exit 0
STUB
    cat > "$bin/clevis" <<'STUB'
#!/bin/sh
echo "clevis $*" >> "$CALLS"
dev= key=
cmd="$1 $2"; shift 2
while [ $# -gt 0 ]; do
    case "$1" in
    -d) dev=$2; shift ;;
    -s) shift ;;
    -k) key=$2; shift ;;
    esac
    shift
done
n=$(basename "$dev")
case "$cmd" in
"luks list") [ -e "$CTL/slots-$n" ] && cat "$CTL/slots-$n"; exit 0 ;;
"luks pass") [ -e "$CTL/answers-$n" ] || exit 1; printf 'secret-%s' "$n"; exit 0 ;;
"luks bind")
    [ -e "$CTL/bind-fails" ] && exit 1
    cat "$key" > "$CTL/bound-key-$n"; : > "$CTL/answers-$n"; exit 0 ;;
esac
exit 0
STUB
    cat > "$bin/apt-get" <<'STUB'
#!/bin/sh
echo "apt-get $*" >> "$CALLS"
for a in "$@"; do
    if [ "$a" = --print-uris ]; then
        [ -e "$CTL/need-download" ] && echo "'http://archive.example/linux-image-raye.deb' linux-image-raye.deb 1000 SHA256:00"
        exit 0
    fi
done
echo "Setting up linux-image-raye ..."
echo "Warning: os-prober will be executed to detect other bootable partitions." >&2
[ -e "$CTL/apt-fails" ] && exit 100
exit 0
STUB
    cat > "$bin/apt-cache" <<'STUB'
#!/bin/sh
echo "apt-cache $*" >> "$CALLS"
[ -e "$CTL/archive" ] && { echo "Package: linux-image-raye"; exit 0; }
echo "E: No packages found" >&2
exit 100
STUB
    cat > "$bin/update-grub" <<'STUB'
#!/bin/sh
echo "update-grub $*" >> "$CALLS"
echo "Generating grub configuration file ..." >&2
echo "Warning: os-prober will be executed to detect other bootable partitions." >&2
exit 0
STUB
    for g in grub-set-default grub-reboot; do
        cat > "$bin/$g" <<STUB
#!/bin/sh
echo "$g \$*" >> "\$CALLS"
[ -e "\$CTL/$g-fails" ] && exit 1
exit 0
STUB
    done
    cat > "$bin/uname" <<'STUB'
#!/bin/sh
cat "$CTL/uname"
STUB
    cat > "$bin/id" <<'STUB'
#!/bin/sh
if [ "${1:-}" = -u ]; then cat "$CTL/uid"; else /usr/bin/id "$@"; fi
STUB
    cat > "$bin/nm-online" <<'STUB'
#!/bin/sh
echo "nm-online $*" >> "$CALLS"
[ -e "$CTL/online" ]
STUB
    # installed packages: lines "ii  name" in $CTL/dpkg-installed
    cat > "$bin/dpkg-query" <<'STUB'
#!/bin/sh
echo "dpkg-query $*" >> "$CALLS"
[ -e "$CTL/dpkg-installed" ] && cat "$CTL/dpkg-installed"
exit 0
STUB
    chmod 755 "$bin"/*
}

write_tpm_tool() {
    mkdir -p "$R/usr/libexec"
    cat > "$R/usr/libexec/raye-tpm" <<'STUB'
#!/bin/sh
echo "raye-tpm $*" >> "$CALLS"
echo "raye-tpm says: $1"
rc=0
[ -e "$CTL/tpm-rc-$1" ] && rc=$(cat "$CTL/tpm-rc-$1")
exit "$rc"
STUB
    chmod 755 "$R/usr/libexec/raye-tpm"
}

# ------------------------------------------------------------ the world
setup() {
    current=$1
    T=$(mktemp -d)
    R=$T/root
    CTL=$T/ctl
    CALLS=$T/calls
    export RAYE_KERNEL_TEST_ROOT="$R" CTL CALLS
    mkdir -p "$CTL" "$R/boot/grub" "$R/etc/default/grub.d" "$R/usr/share/raye/kernel" \
        "$R/var/lib" "$R/run" "$R/dev/disk/by-uuid" "$R/proc/sys/kernel/random"
    echo 11111111-2222-3333-4444-555555555555 > "$R/proc/sys/kernel/random/boot_id"
    : > "$CALLS"
    write_stubs "$T/bin"
    write_tpm_tool
    PATH=$T/bin:$basepath
    export PATH
    echo 0 > "$CTL/uid"
    echo "$ubuntu" > "$CTL/uname"
    : > "$CTL/sb"
    echo cert > "$R/usr/share/raye/kernel/raye-boot.der"
    : > "$R/boot/vmlinuz-$ubuntu"
    cat > "$R/boot/grub/grub.cfg" <<CFG
menuentry 'Raye' --class ubuntu \$menuentry_id_option 'gnulinux-simple-$uuid' {
}
submenu 'Advanced options for Raye' \$menuentry_id_option 'gnulinux-advanced-$uuid' {
	menuentry 'Raye, with Linux $raye' --class ubuntu \$menuentry_id_option 'gnulinux-$raye-advanced-$uuid' {
	}
	menuentry 'Raye, with Linux $raye (recovery mode)' \$menuentry_id_option 'gnulinux-$raye-recovery-$uuid' {
	}
	menuentry 'Raye, with Linux $ubuntu' --class ubuntu \$menuentry_id_option 'gnulinux-$ubuntu-advanced-$uuid' {
	}
}
CFG
}

# a LUKS disk bound to the TPM; "answers": the TPM opens it on this boot
add_tpm_disk() {
    name=$1 answers=$2
    : > "$R/dev/$name"
    ln -s "../../$name" "$R/dev/disk/by-uuid/uuid-$name"
    echo "luks-$name UUID=uuid-$name none luks,discard" >> "$R/etc/crypttab"
    echo "1: tpm2 '{\"hash\":\"sha256\",\"key\":\"ecc\",\"pcr_bank\":\"sha256\",\"pcr_ids\":\"7\"}'" > "$CTL/slots-$name"
    [ "$answers" = yes ] && : > "$CTL/answers-$name"
    return 0
}

add_local_debs() {
    mkdir -p "$R/usr/share/raye/kernel/debs"
    : > "$R/usr/share/raye/kernel/debs/linux-image-${raye}_7.0.0-42.1_amd64.deb"
    : > "$R/usr/share/raye/kernel/debs/linux-headers-${raye}_7.0.0-42.1_amd64.deb"
}

kernel_installed() { : > "$R/boot/vmlinuz-$raye"; }

state() { echo "$R/var/lib/raye-kernel/$1"; }

run() {
    "$script" "$@" > "$T/out" 2> "$T/err"
    rc=$?
}

run_in() {
    input=$1; shift
    printf '%s' "$input" | "$script" "$@" > "$T/out" 2> "$T/err"
    rc=$?
}

teardown() { rm -rf -- "$T"; }

# ----------------------------------------------------------- assertions
ok() { pass=$((pass + 1)); }
bad() {
    fail=$((fail + 1))
    echo "FAIL [$current] $*"
    echo "  stdout: $(cat "$T/out" 2>/dev/null)"
    echo "  stderr: $(cat "$T/err" 2>/dev/null)"
}
check() { if eval "$1"; then ok; else bad "$2"; fi; }
called() { grep -qF -- "$1" "$CALLS"; }
out_is() { [ "$(cat "$T/out")" = "$1" ]; }
quiet_output() {
    ! grep -qiE "os-prober|Setting up|Generating grub|raye-tpm says" "$T/out" "$T/err"
}
logfile() { echo "$R/var/log/raye/kernel-setup.log"; }

basepath=$PATH

# ================================================================ status
setup "status: nothing set up"
run status
check '[ $rc = 0 ] && out_is not-enrolled' "not-enrolled expected"
check '[ ! -e "$(logfile)" ]' "status writes no log"
teardown

setup "status: no Secure Boot"
rm "$CTL/sb"
run status
check 'out_is no-secure-boot' "no-secure-boot expected"
teardown

setup "status: key queued"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run status
check 'out_is pending' "pending expected"
: > "$CTL/enrolled"
run status
check 'out_is enrolled' "enrolled expected once the key is in"
teardown

setup "status: trial and failed"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
run status
check 'out_is trial' "trial expected"
rm "$(state trial)"; : > "$(state failed)"
run status
check 'out_is failed' "failed expected"
teardown

setup "status: the TPM no longer opens a disk"
mkdir -p "$R/var/lib/raye-tpm"; : > "$R/var/lib/raye-tpm/needs-password"
run status
check 'out_is tpm-needs-password' "tpm-needs-password expected (root, flag)"
echo 1000 > "$CTL/uid"
run status
check 'out_is not-enrolled' "a user cannot see the flag itself, and there is no cache yet"
mkdir -p "$R/run/raye-kernel"; echo stale > "$R/run/raye-kernel/tpm-status"
run status
check 'out_is tpm-needs-password' "tpm-needs-password expected (user, cache)"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
run status
check 'out_is trial' "a trial boot outranks the TPM state"
teardown

setup "status and enroll: NVIDIA driver with prebuilt modules"
# Raye installs NVIDIA's driver with the modules Ubuntu signed for its own
# kernel: on the Raye kernel they would not load, the trial boot would still
# "start" on the fallback driver, and the PC would keep a kernel with no
# NVIDIA driver. Until the Raye kernel has its modules, the switch is refused.
mkdir -p "$R/var/lib/dpkg/info"
: > "$R/var/lib/dpkg/info/linux-modules-nvidia-580-generic-hwe-26.04.list"
run status
check 'out_is nvidia' "nvidia expected while NVIDIA's prebuilt modules are installed"
run enroll
check '[ $rc != 0 ]' "enroll must refuse on an NVIDIA PC"
check '! called "mokutil --import"' "no key queued on an NVIDIA PC"
check '! called "apt-get install"' "no kernel installed on an NVIDIA PC"
check 'grep -q "NVIDIA" "$T/err"' "the refusal names NVIDIA"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
run status
check 'out_is trial' "a switch already under way keeps its own state"
teardown

# ============================================================ tpm-status
setup "tpm-status: no encrypted disk"
run tpm-status
check '[ $rc = 0 ] && out_is none' "none expected"
check '[ "$(cat "$R/run/raye-kernel/tpm-status")" = none ]' "root writes the cache"
check '[ "$(stat -c %a "$R/run/raye-kernel/tpm-status")" = 644 ]' "cache readable by everyone"
teardown

setup "tpm-status: TPM disk opens"
add_tpm_disk vda3 yes
run tpm-status
check 'out_is ok' "ok expected"
teardown

setup "tpm-status: TPM disk does not open"
add_tpm_disk vda3 yes
add_tpm_disk vdb1 no
run tpm-status
check 'out_is stale' "stale expected"
check '[ "$(cat "$R/run/raye-kernel/tpm-status")" = stale ]' "cache says stale"
teardown

setup "tpm-status: disk password only"
: > "$R/dev/vda3"; ln -s ../../vda3 "$R/dev/disk/by-uuid/uuid-vda3"
echo "luks-vda3 UUID=uuid-vda3 none luks" > "$R/etc/crypttab"
run tpm-status
check 'out_is none' "a disk without a TPM binding is none"
teardown

setup "tpm-status: flag left by the boot check"
add_tpm_disk vda3 yes
mkdir -p "$R/var/lib/raye-tpm"; : > "$R/var/lib/raye-tpm/needs-password"
run tpm-status
check 'out_is stale' "the flag means stale"
teardown

setup "tpm-status: as a user"
echo 1000 > "$CTL/uid"
add_tpm_disk vda3 no
run tpm-status
check 'out_is none' "no cache: none"
check '! called "clevis"' "a user never runs clevis"
mkdir -p "$R/run/raye-kernel"; echo ok > "$R/run/raye-kernel/tpm-status"
run tpm-status
check 'out_is ok' "cache value"
echo 'bogus value' > "$R/run/raye-kernel/tpm-status"
run tpm-status
check 'out_is none' "anything else in the cache: none"
teardown

# ================================================================ enroll
setup "enroll: key queued for MokManager"
run enroll
check '[ $rc = 0 ]' "exit 0"
check 'grep -qE "^[0-9]{6}$" "$T/out" && [ "$(wc -l < "$T/out")" -eq 1 ]' "only the six-digit code on stdout"
check '[ -e "$(state pending)" ]' "pending set"
check 'called "mokutil --import"' "key imported"
check '! called "apt-get"' "nothing installed before the key is in"
check '[ -e "$(logfile)" ] && [ "$(stat -c %a "$(logfile)")" = 640 ]' "log file, root and adm only"
teardown

setup "enroll: the firmware refuses the request"
: > "$CTL/import-fails"
run enroll
check '[ $rc = 1 ] && [ ! -e "$(state pending)" ]' "exit 1, nothing pending"
check '[ -z "$(cat "$T/out")" ]' "no code printed"
teardown

setup "enroll: key already in, TPM predicted"
: > "$CTL/enrolled"
add_local_debs
add_tpm_disk vda3 yes
# the kernel package puts the kernel in /boot
cat > "$T/bin/apt-get" <<STUB
#!/bin/sh
echo "apt-get \$*" >> "\$CALLS"
for a in "\$@"; do [ "\$a" = --print-uris ] && exit 0; done
: > "$R/boot/vmlinuz-$raye"
echo "Setting up linux-image-raye ..."
echo "Warning: os-prober will be executed to detect other bootable partitions." >&2
exit 0
STUB
run enroll
check '[ $rc = 0 ]' "exit 0"
check 'quiet_output' "no apt, GRUB or raye-tpm lines on stdout/stderr"
check 'grep -q "os-prober" "$(logfile)" && grep -q "raye-tpm says" "$(logfile)"' "tool output kept in the log"
check 'called "raye-tpm bind-next --kernel raye"' "binding predicted for the Raye kernel"
check '[ ! -d "$(state keys)" ]' "no passphrase copy when the prediction worked"
check 'called "grub-set-default gnulinux-advanced-$uuid>gnulinux-$ubuntu-advanced-$uuid"' "Ubuntu's kernel stays the default"
check 'called "grub-reboot gnulinux-advanced-$uuid>gnulinux-$raye-advanced-$uuid"' "one trial boot of the Raye kernel"
check '[ "$(cat "$(state trial)")" = "$(cat "$R/proc/sys/kernel/random/boot_id")" ]' "trial remembers the boot that set it"
check 'grep -qx "GRUB_DEFAULT=saved" "$R/etc/default/grub.d/60-raye-kernel.cfg"' "GRUB keeps the saved entry"
teardown

setup "enroll: no Secure Boot, nothing to ask"
rm "$CTL/sb"
add_local_debs
kernel_installed
run enroll
check '[ $rc = 0 ] && [ -e "$(state trial)" ]' "installed and tried at once"
check '! called "mokutil --import"' "no key queued"
check 'quiet_output' "quiet"
teardown

# ======================================================= TPM fallbacks
for case in 2 1 4; do
    setup "trial: raye-tpm exits $case, passphrase kept"
    : > "$CTL/enrolled"
    add_local_debs
    kernel_installed
    add_tpm_disk vda3 yes
    echo "$case" > "$CTL/tpm-rc-bind-next"
    run enroll
    check '[ $rc = 0 ] && [ -e "$(state trial)" ]' "the trial still happens"
    check '[ "$(cat "$(state keys)/vda3")" = secret-vda3 ]' "passphrase copied for the old path"
    check '[ "$(stat -c %a "$(state keys)")" = 700 ] && [ "$(stat -c %a "$(state keys)/vda3")" = 600 ]' "root only"
    check '! grep -q secret-vda3 "$(logfile)"' "the passphrase never goes to the log"
    teardown
done

setup "trial: no TPM disk, raye-tpm has nothing to do"
: > "$CTL/enrolled"
add_local_debs
kernel_installed
echo 3 > "$CTL/tpm-rc-bind-next"
run enroll
check '[ -e "$(state trial)" ] && [ ! -d "$(state keys)" ]' "no copy needed"
teardown

setup "trial: raye-tpm missing"
: > "$CTL/enrolled"
add_local_debs
kernel_installed
add_tpm_disk vda3 yes
rm "$R/usr/libexec/raye-tpm"
run enroll
check '[ -e "$(state trial)" ] && [ -f "$(state keys)/vda3" ]' "old path used"
teardown

setup "trial: no Ubuntu kernel entry in GRUB"
: > "$CTL/enrolled"
add_local_debs
kernel_installed
rm "$R/boot/vmlinuz-$ubuntu"
run enroll
check '[ $rc != 0 ] && [ ! -e "$(state trial)" ]' "no trial boot without a way back"
check '! called "grub-reboot"' "GRUB untouched"
teardown

setup "trial: grub-reboot fails"
: > "$CTL/enrolled"
add_local_debs
kernel_installed
: > "$CTL/grub-reboot-fails"
run enroll
check '[ $rc != 0 ] && [ ! -e "$(state trial)" ]' "no trial flag"
teardown

setup "enroll: apt fails"
: > "$CTL/enrolled"
add_local_debs
: > "$CTL/apt-fails"
run enroll
check '[ $rc != 0 ] && [ ! -e "$(state trial)" ]' "nothing tried"
check '[ -n "$(cat "$T/err")" ] && quiet_output' "one Raye line on stderr, no apt line"
teardown

# ================================================================ finish
setup "finish: nothing to do"
run finish
check '[ $rc = 0 ] && [ ! -s "$CALLS" ]' "no tool called"
teardown

setup "finish: the trial boot started the Raye kernel"
kernel_installed
echo "$raye" > "$CTL/uname"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
add_tpm_disk vda3 yes
run finish
check '[ $rc = 0 ] && out_is "Raye kernel kept"' "only Raye's line"
check 'called "grub-set-default 0"' "it becomes the default: the menu's first line, not inside Advanced options"
check 'called "raye-tpm prune"' "old bindings pruned"
check 'called "raye-tpm bind-next --kernel ubuntu"' "Ubuntu's kernel keeps a binding"
check '[ ! -e "$(state trial)" ] && [ ! -e "$(state failed)" ]' "trial done"
teardown

setup "finish: run again before the trial boot (package upgrade)"
kernel_installed
mkdir -p "$R/var/lib/raye-kernel"
cp "$R/proc/sys/kernel/random/boot_id" "$(state trial)"
run finish
check '[ $rc = 0 ] && [ -e "$(state trial)" ] && [ ! -e "$(state failed)" ]' "trial left for the next boot"
check '! called "grub-set-default" && ! called "raye-tpm"' "nothing changed"
echo 99999999-2222-3333-4444-555555555555 > "$R/proc/sys/kernel/random/boot_id"
run finish
check '[ -e "$(state failed)" ] && [ ! -e "$(state trial)" ]' "next boot: the trial is judged"
teardown

setup "finish: kept, old path (passphrase copy)"
kernel_installed
echo "$raye" > "$CTL/uname"
mkdir -p "$(state keys)"; : > "$(state trial)"
add_tpm_disk vda3 no
printf 'secret-vda3' > "$(state keys)/vda3"
mkdir -p "$R/var/lib/raye-tpm"; : > "$R/var/lib/raye-tpm/needs-password"
run finish
check '[ "$(cat "$CTL/bound-key-vda3")" = secret-vda3 ]' "bound again with the kept passphrase"
check '[ ! -e "$R/var/lib/raye-tpm/needs-password" ]' "the trial boot's password flag goes"
check '[ ! -d "$(state keys)" ]' "copy erased"
check 'grep -q "Raye kernel kept" "$T/out"' "kept"
check 'called "raye-tpm record"' "new binding tagged"
teardown

setup "finish: the Raye kernel did not start"
kernel_installed
mkdir -p "$(state keys)"; : > "$(state trial)"
printf 'secret-vda3' > "$(state keys)/vda3"
run finish
check '[ $rc = 0 ] && [ -e "$(state failed)" ]' "failed recorded"
check '[ ! -d "$(state keys)" ]' "copy erased"
check '! called "raye-tpm prune" && ! called "grub-set-default"' "nothing else changed"
teardown

setup "finish: key in, kernel shipped on the disk"
: > "$CTL/enrolled"
add_local_debs
kernel_installed
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check '[ $rc = 0 ] && [ -e "$(state trial)" ] && [ ! -e "$(state pending)" ]' "installed, trial set"
check '! called "nm-online"' "no network wait for a local package"
check 'called "linux-image-${raye}_7.0.0-42.1_amd64.deb"' "local package installed"
check 'quiet_output' "quiet"
teardown

setup "finish: key in, download needed, online"
: > "$CTL/enrolled"
: > "$CTL/archive"; : > "$CTL/need-download"; : > "$CTL/online"
kernel_installed
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check 'called "nm-online -q -t 60"' "waits for the network"
check 'called "install -y -q linux-image-raye"' "installed from the archive"
check '[ -e "$(state trial)" ]' "trial set"
teardown

setup "finish: key in, download needed, offline"
: > "$CTL/enrolled"
: > "$CTL/archive"; : > "$CTL/need-download"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check '[ $rc = 0 ] && [ -e "$(state pending)" ] && [ ! -e "$(state trial)" ]' "tries again next boot"
check '! called "install -y -q linux-image-raye"' "nothing installed"
check 'grep -q "next boot" "$T/out"' "says so"
teardown

setup "finish: offline, but the kernel is also on the disk"
: > "$CTL/enrolled"
: > "$CTL/archive"; : > "$CTL/need-download"
add_local_debs
kernel_installed
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check 'called "linux-image-${raye}_7.0.0-42.1_amd64.deb"' "falls back to the shipped package"
check '[ -e "$(state trial)" ]' "trial set"
teardown

setup "finish: package already downloaded"
: > "$CTL/enrolled"
: > "$CTL/archive"
kernel_installed
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check '! called "nm-online"' "no wait when nothing is downloaded"
check '[ -e "$(state trial)" ]' "trial set"
teardown

setup "finish: no package anywhere"
: > "$CTL/enrolled"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check '[ $rc = 0 ] && [ -e "$(state pending)" ]' "next boot, no failed unit"
teardown

setup "finish: key turned down at the blue screen"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
run finish
check '[ $rc = 0 ] && [ ! -e "$(state pending)" ]' "pending dropped"
teardown

setup "finish: key still waiting for MokManager"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state pending)"
echo "[key 1]" > "$CTL/list-new"
run finish
check '[ -e "$(state pending)" ]' "pending kept"
teardown

# ================================================================ remove
setup "remove: back to Ubuntu's kernel"
mkdir -p "$(state keys)"; : > "$(state pending)"; : > "$(state failed)"
echo GRUB_DEFAULT=saved > "$R/etc/default/grub.d/60-raye-kernel.cfg"
run remove
check '[ $rc = 0 ]' "exit 0"
check 'called "purge -y -q linux-image-*-raye linux-headers-*-raye"' "kernel purged"
check '[ ! -e "$(state pending)" ] && [ ! -e "$(state failed)" ] && [ ! -d "$(state keys)" ]' "state cleared"
check '[ ! -e "$R/etc/default/grub.d/60-raye-kernel.cfg" ]' "GRUB setting removed"
check 'called "update-grub"' "menu rebuilt"
check '! called "raye-tpm bind-next"' "nothing to bind from Ubuntu's kernel"
check 'quiet_output' "quiet"
teardown

setup "remove: while running the Raye kernel"
echo "$raye" > "$CTL/uname"
add_tpm_disk vda3 yes
run remove
check 'called "raye-tpm bind-next --kernel ubuntu"' "Ubuntu's kernel gets a binding before the next boot"
check '[ "$(grep -n "raye-tpm bind-next" "$CALLS" | cut -d: -f1)" -lt "$(grep -n "apt-get purge" "$CALLS" | cut -d: -f1)" ]' "bound before the purge"
teardown

# ================================================================ rebind
setup "rebind: the password lets the TPM open the disk again"
add_tpm_disk vda3 no
mkdir -p "$R/var/lib/raye-tpm"; : > "$R/var/lib/raye-tpm/needs-password"
run_in 'my pass wörd
' rebind
check '[ $rc = 0 ]' "exit 0"
check '[ "$(cat "$CTL/bound-key-vda3")" = "my pass wörd" ]' "key used as typed"
check '[ "$(tail -c 1 "$CTL/bound-key-vda3" | od -An -tx1 | tr -d " ")" != 0a ]' "no trailing newline"
check 'called "raye-tpm record"' "binding tagged"
check '[ ! -e "$R/var/lib/raye-tpm/needs-password" ]' "flag cleared"
check '[ "$(cat "$R/run/raye-kernel/tpm-status")" = ok ]' "cache refreshed"
check '! ls "$R/run" | grep -q raye-rebind' "key file erased"
check '! grep -q "pass wörd" "$(logfile)"' "password never logged"
teardown

setup "rebind: wrong password"
add_tpm_disk vda3 no
: > "$CTL/bind-fails"
mkdir -p "$R/var/lib/raye-tpm"; : > "$R/var/lib/raye-tpm/needs-password"
run_in 'wrong' rebind
check '[ $rc = 1 ]' "exit 1"
check '[ -e "$R/var/lib/raye-tpm/needs-password" ]' "flag kept"
check '[ "$(cat "$R/run/raye-kernel/tpm-status")" = stale ]' "still stale"
check '! ls "$R/run" | grep -q raye-rebind' "key file erased"
teardown

setup "rebind: two disks, the password opens only one"
add_tpm_disk vda3 yes
add_tpm_disk vdb1 no
: > "$CTL/bind-fails"
run_in 'pw' rebind
check '[ $rc = 1 ]' "not done while one disk still asks"
teardown

setup "rebind: no disk bound to the TPM"
run_in 'pw' rebind
check '[ $rc = 1 ]' "nothing to do is not success"
teardown

setup "rebind: the TPM already opens every disk"
add_tpm_disk vda3 yes
run_in 'pw' rebind
check '[ $rc = 0 ] && ! called "luks bind"' "nothing bound"
teardown

# ================================================================ misc
setup "root only"
echo 1000 > "$CTL/uid"
for c in enroll finish rebind remove; do
    run "$c"
    check '[ $rc = 1 ] && [ ! -s "$CALLS" ]' "$c refused for a user"
done
teardown

setup "unknown command"
run frobnicate
check '[ $rc = 2 ]' "exit 2"
teardown

setup "boot unit"
unit=$here/../raye-kernel-finish.service
check '! grep -v "^#" "$unit" | grep -q "network-online"' "no network-online.target in the boot"
check 'grep -q "^ExecStart=/usr/libexec/raye-kernel-setup finish$" "$unit"' "runs finish"
teardown

setup "state at boot"
unit=$here/../raye-tpm-status.service
check 'grep -q "^ExecStart=/usr/libexec/raye-kernel-setup tpm-status$" "$unit"' "writes the TPM state"
check 'grep -q "^WantedBy=multi-user.target$" "$unit"' "at every start"
check 'grep -q "^Type=exec$" "$unit"' "does not hold the start-up"
check 'grep -q "release/kernel/raye-tpm-status.service" "$here/../../../debian/raye-release-paths"' "shipped in raye-kernel"
teardown

setup "polkit"
policy=$here/../org.raye.kernel.policy
check 'grep -A12 "id=\"org.raye.kernel\"" "$policy" | grep -q "<allow_active>auth_admin</allow_active>"' "changing the kernel asks the password"
check 'grep -A14 "id=\"org.raye.kernel.tpm-status\"" "$policy" | grep -q "<allow_active>yes</allow_active>"' "reading the TPM state does not"
check 'grep -A14 "id=\"org.raye.kernel.tpm-status\"" "$policy" | grep -q "exec.argv1\">tpm-status<"' "only for tpm-status"
if command -v xmllint >/dev/null 2>&1; then
    check 'xmllint --noout "$policy" 2>/dev/null' "well-formed XML"
fi
teardown

# ======================================================= V1: Ubuntu's kernel goes
ubuntu_installed() {
    printf 'ii  linux-generic-hwe-26.04\nii  linux-image-%s\nii  linux-modules-%s\nii  linux-headers-generic-hwe-26.04\n' \
        "$ubuntu" "$ubuntu" > "$CTL/dpkg-installed"
}
raye_is_a_package() {
    mkdir -p "$R/var/lib/dpkg/info"; : > "$R/var/lib/dpkg/info/linux-image-$raye.list"
}

setup "finish: kept, Ubuntu's kernel removed"
kernel_installed; raye_is_a_package; ubuntu_installed
echo "$raye" > "$CTL/uname"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
add_tpm_disk vda3 yes
run finish
check '[ $rc = 0 ] && out_is "Raye kernel kept"' "kept, one line"
check 'called "apt-get purge -y -q linux-generic-hwe-26.04 linux-image-$ubuntu linux-modules-$ubuntu linux-headers-generic-hwe-26.04"' "Ubuntu's kernel packages purged"
check '! called "raye-tpm bind-next --kernel ubuntu"' "no binding kept for a kernel that is gone"
check 'called "grub-set-default 0"' "the newest Raye kernel is the default"
check 'quiet_output' "quiet"
teardown

setup "finish: kept, but Ubuntu's kernel cannot be removed"
kernel_installed; raye_is_a_package; ubuntu_installed
echo "$raye" > "$CTL/uname"
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
: > "$CTL/apt-fails"
run finish
check '[ $rc = 0 ] && grep -q "Raye kernel kept" "$T/out"' "still kept"
check 'called "raye-tpm bind-next --kernel ubuntu"' "Ubuntu's kernel stays the fallback, with its binding"
teardown

setup "finish: the trial failed, Ubuntu's kernel stays"
kernel_installed; raye_is_a_package; ubuntu_installed
mkdir -p "$R/var/lib/raye-kernel"; : > "$(state trial)"
run finish
check '[ -e "$(state failed)" ] && ! called "apt-get purge"' "nothing removed when the Raye kernel did not start"
teardown

setup "remove: Ubuntu's kernel was removed, it comes back first"
echo "$raye" > "$CTL/uname"
rm -f "$R/boot/vmlinuz-$ubuntu"; kernel_installed
run remove
check '[ $rc = 0 ]' "exit 0"
check 'called "apt-get install -y -q linux-generic-hwe-26.04"' "Ubuntu's kernel installed again"
check '[ "$(grep -n "install -y -q linux-generic" "$CALLS" | cut -d: -f1)" -lt "$(grep -n "apt-get purge" "$CALLS" | cut -d: -f1)" ]' "before the Raye kernel goes"
teardown

setup "remove: Ubuntu's kernel cannot come back, the Raye kernel stays"
echo "$raye" > "$CTL/uname"
rm -f "$R/boot/vmlinuz-$ubuntu"; kernel_installed
: > "$CTL/apt-fails"
run remove
check '[ $rc != 0 ] && ! called "apt-get purge"' "never the last kernel removed"
teardown

setup "NVIDIA: the Raye kernel has modules for the installed driver"
mkdir -p "$R/var/lib/dpkg/info"
: > "$R/var/lib/dpkg/info/linux-modules-nvidia-580-open-7.0.0-44-generic.list"
: > "$R/var/lib/dpkg/info/linux-modules-nvidia-580-open-generic-hwe-26.04.list"
add_local_debs
: > "$R/usr/share/raye/kernel/debs/linux-modules-nvidia-580-open-${raye}_580.178.04+raye1_amd64.deb"
run status
check 'out_is not-enrolled' "not blocked: the switch can go ahead"
run enroll
check '[ $rc = 0 ] && called "mokutil --import"' "the key is queued"
rm -f "$CTL/sb"
run enroll
check 'called "linux-modules-nvidia-580-open-${raye}_580.178.04+raye1_amd64.deb"' "the Raye NVIDIA modules go in with the kernel"
teardown

setup "NVIDIA: Raye modules only for another driver"
mkdir -p "$R/var/lib/dpkg/info"
: > "$R/var/lib/dpkg/info/linux-modules-nvidia-570-server-7.0.0-44-generic.list"
add_local_debs
: > "$R/usr/share/raye/kernel/debs/linux-modules-nvidia-580-open-${raye}_580.178.04+raye1_amd64.deb"
run status
check 'out_is nvidia' "still blocked for 570-server"
teardown

setup "NVIDIA: only the Raye kernel's own modules are installed"
mkdir -p "$R/var/lib/dpkg/info"
: > "$R/var/lib/dpkg/info/linux-modules-nvidia-580-open-${raye}.list"
run status
check 'out_is not-enrolled' "the Raye modules are not Ubuntu's prebuilt ones"
teardown

# ================================================ EAC v2 boot line, status
eac_cfg=$here/../62-raye-eac.cfg
eac_line() {  # $1: Secure Boot byte or "none", $2: GRUB_CMDLINE_LINUX before
    v=$T/sbvar
    rm -f "$v"
    [ "$1" = none ] || printf '\007\000\000\000\00'"$1" > "$v"
    (GRUB_CMDLINE_LINUX=$2; RAYE_EAC_SB_VAR=$v; . "$eac_cfg"; printf '%s' "$GRUB_CMDLINE_LINUX")
}
setup "EAC: boot line with Secure Boot on"
check '[ "$(eac_line 1 "")" = "lockdown=integrity sysctl.kernel.kexec_load_disabled=1 iommu.passthrough=0" ]' "the three options"
check '[ "$(eac_line 1 "quiet")" = "quiet lockdown=integrity sysctl.kernel.kexec_load_disabled=1 iommu.passthrough=0" ]' "added after what is there"
check '[ "$(eac_line 1 "lockdown=none")" = "lockdown=none" ]' "a lockdown chosen by hand is left alone"
check '[ "$(eac_line 0 "quiet")" = "quiet" ]' "Secure Boot off: nothing"
check '[ "$(eac_line none "quiet")" = "quiet" ]' "no EFI variable: nothing"
# the real variable: SecureBoot in EFI_GLOBAL_VARIABLE (UEFI spec), the one mokutil reads
check 'grep -q "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c" "$eac_cfg"' "the snippet reads the global SecureBoot variable"
check 'grep -q "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c" "$here/../raye-eac-status"' "raye-eac-status reads the same variable"
teardown

setup "EAC: raye-eac-status"
st=$here/../raye-eac-status
E=$T/eac
mkdir -p "$E/sys/firmware/efi/efivars" "$E/sys/class/tpm/tpm0" "$E/sys/kernel/security/tpm0" \
    "$E/sys/kernel/iommu_groups/0" "$E/proc/sys/kernel"
printf '\007\000\000\000\001' > "$E/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
echo 2 > "$E/sys/class/tpm/tpm0/tpm_version_major"
: > "$E/sys/kernel/security/tpm0/binary_bios_measurements"
echo "none [integrity] confidentiality" > "$E/sys/kernel/security/lockdown"
echo "capability,landlock,lockdown,yama,apparmor,bpf,ima,evm" > "$E/sys/kernel/security/lsm"
echo 1 > "$E/proc/sys/kernel/kexec_load_disabled"
echo DMA-FQ > "$E/sys/kernel/iommu_groups/0/type"
echo "BOOT_IMAGE=/vmlinuz quiet lockdown=integrity sysctl.kernel.kexec_load_disabled=1 iommu.passthrough=0" > "$E/proc/cmdline"
echo "$raye" > "$CTL/uname"
RAYE_EAC_TEST_ROOT=$E "$st" > "$T/out" 2> "$T/err"; rc=$?
check '[ $rc = 0 ] && tail -n 1 "$T/out" | grep -qx "eac-v2: ready"' "everything holds: ready"
echo "capability,landlock,lockdown,yama,apparmor" > "$E/sys/kernel/security/lsm"
echo identity > "$E/sys/kernel/iommu_groups/0/type"
echo 0 > "$E/proc/sys/kernel/kexec_load_disabled"
RAYE_EAC_TEST_ROOT=$E "$st" > "$T/out" 2> "$T/err"; rc=$?
check '[ $rc = 1 ] && grep -q "^bpf-lsm  *no" "$T/out" && grep -q "^iommu-no-passthrough  *no" "$T/out" && grep -q "^kexec-disabled  *no" "$T/out"' "each failure named"
check 'tail -n 1 "$T/out" | grep -qx "eac-v2: not ready"' "not ready"
teardown

setup "EAC: shipped"
paths=$here/../../../debian/raye-release-paths
check 'grep -qE "^raye-kernel +release/kernel/62-raye-eac.cfg +etc/default/grub.d/62-raye-eac.cfg$" "$paths"' "boot line snippet installed"
check 'grep -qE "^raye-kernel +release/kernel/raye-eac-status +usr/bin/raye-eac-status$" "$paths"' "status tool installed"
check 'grep -q "^ *linux-generic-hwe-26.04 | raye-kernel-image,$" "$here/../../../debian/control"' "raye-system accepts the Raye kernel in place of Ubuntu's (purging Ubuntu's must not take raye-system with it)"
teardown

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
