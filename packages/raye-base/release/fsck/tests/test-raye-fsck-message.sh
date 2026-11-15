#!/bin/sh
# Tests of raye-fsck-message and its systemd-fsck@ drop-in: the boot
# screen hears about a drive check only when it takes more than two
# seconds, gets the drive's name, is put back afterwards, and the check's
# own exit status always comes through. plymouth, blkid and findmnt are
# stubs that record their calls; the check is a stub that sleeps.
#
#   sh release/fsck/tests/test-raye-fsck-message.sh
# The checks are strings run by eval, so they expand late on purpose.
# shellcheck disable=SC2016,SC2034
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../raye-fsck-message
dropin=$here/../systemd-fsck@.service.d/raye-message.conf
pass=0
fail=0
current=

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
bin=$work/bin
mkdir -p "$bin"

cat > "$bin/plymouth" <<'STUB'
#!/bin/sh
case "$1" in
--ping) [ -e "$CTL/plymouth-up" ] ;;
*) echo "plymouth $*" >> "$CALLS" ;;
esac
STUB
cat > "$bin/blkid" <<'STUB'
#!/bin/sh
echo "blkid $*" >> "$CTL/blkid-calls"
[ -e "$CTL/label" ] && cat "$CTL/label"
exit 0
STUB
cat > "$bin/check" <<'STUB'
#!/bin/sh
# the drive check: sleeps $CTL/time-<device name> seconds, exits with
# $CTL/status (0 if absent)
echo "check $*" >> "$CALLS"
t=0
[ -e "$CTL/time-${1##*/}" ] && t=$(cat "$CTL/time-${1##*/}")
# stopped like fsck would be: TERM ends it
trap 'kill "$s" 2>/dev/null; exit 143' TERM
sleep "$t" &
s=$!
wait "$s"
[ -e "$CTL/status" ] && exit "$(cat "$CTL/status")"
exit 0
STUB
chmod +x "$bin"/*

# each case gets fresh call logs, state folder and fstab
setup() {
    current=$1
    case_dir=$work/case-$pass-$fail
    rm -rf "$case_dir"
    mkdir -p "$case_dir/ctl"
    CTL=$case_dir/ctl
    CALLS=$case_dir/calls
    : > "$CALLS"
    touch "$CTL/plymouth-up"
    export CTL CALLS
    export RAYE_FSCK_STATE="$case_dir/run"
    export LIBMOUNT_FSTAB="$case_dir/fstab"
    : > "$LIBMOUNT_FSTAB"
}

run() {
    PATH="$bin:/usr/sbin:/usr/bin:/sbin:/bin" sh "$script" "$bin/check" "$@"
}

ok() {
    if eval "$1"; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "FAIL [$current]: $1"
        echo "  calls:"; sed 's/^/    /' "$CALLS"
    fi
}

shows() { grep -qxF "plymouth display-message --text=$1" "$CALLS"; }
nth_line() { sed -n "${1}p" "$CALLS"; }

# -------------------------------------------------- a quick check is silent
setup "quick check"
run /dev/disk/by-uuid/1111-AAAA
status=$?
ok '[ "$status" -eq 0 ]'
ok 'grep -qxF "check /dev/disk/by-uuid/1111-AAAA" "$CALLS"'
ok '! grep -q "^plymouth" "$CALLS"'
ok '[ ! -e "$CTL/blkid-calls" ]'

# ------------------------------------------- its exit status comes through
setup "quick check, errors corrected"
echo 1 > "$CTL/status"
run /dev/sda1
status=$?
ok '[ "$status" -eq 1 ]'
ok '! grep -q "^plymouth" "$CALLS"'

# ------------------------------------- a long check says so, then clears it
setup "long check, label"
echo 3 > "$CTL/time-1111-AAAA"
echo EFI > "$CTL/label"
echo 4 > "$CTL/status"
run /dev/disk/by-uuid/1111-AAAA
status=$?
ok '[ "$status" -eq 4 ]'
ok '[ "$(nth_line 1)" = "check /dev/disk/by-uuid/1111-AAAA" ]'
ok '[ "$(nth_line 2)" = "plymouth display-message --text=raye:fsck:EFI" ]'
ok '[ "$(nth_line 3)" = "plymouth hide-message --text=raye:fsck:EFI" ]'
ok '[ "$(nth_line 4)" = "plymouth display-message --text=raye:clear" ]'
ok '[ "$(nth_line 5)" = "plymouth hide-message --text=raye:clear" ]'
ok '[ "$(wc -l < "$CALLS")" -eq 5 ]'
ok 'grep -qxF "blkid -o value -s LABEL -- /dev/disk/by-uuid/1111-AAAA" "$CTL/blkid-calls"'
ok '[ -z "$(ls "$RAYE_FSCK_STATE" 2>/dev/null | grep -v "^lock$")" ]'

# ------------------------------------- not before two seconds have passed
setup "message waits two seconds"
echo 3 > "$CTL/time-sdb1"
( run /dev/sdb1 ) &
pid=$!
sleep 1
ok '! grep -q "^plymouth" "$CALLS"'
sleep 1.6
ok 'shows raye:fsck:sdb1'
wait "$pid"
ok 'shows raye:clear'

# --------------------- a label the boot screen cannot take: the mount point
setup "unsafe label, mount point"
echo 3 > "$CTL/time-1111-AAAA"
printf '%s\n' '$(reboot)' > "$CTL/label"
printf '%s\n' '/dev/disk/by-uuid/1111-AAAA /boot/efi vfat umask=0077 0 1' > "$LIBMOUNT_FSTAB"
run /dev/disk/by-uuid/1111-AAAA
ok 'shows raye:fsck:/boot/efi'
ok '! grep -q "reboot" "$CALLS"'

setup "label on two lines"
echo 3 > "$CTL/time-sdc2"
printf 'one\ntwo\n' > "$CTL/label"
run /dev/sdc2
ok 'shows raye:fsck:sdc2'

setup "label too long"
echo 3 > "$CTL/time-sdc2"
echo "a-label-that-goes-on-and-on-and-on-forever" > "$CTL/label"
run /dev/sdc2
ok 'shows raye:fsck:sdc2'

# ---------------------------- no label, no fstab line: the device's name
setup "no label, no fstab"
echo 3 > "$CTL/time-nvme0n1p2"
run /dev/nvme0n1p2
ok 'shows raye:fsck:nvme0n1p2'

setup "label with spaces and dots"
echo 3 > "$CTL/time-sdd1"
echo "Raye boot 2.0" > "$CTL/label"
run /dev/sdd1
ok 'shows "raye:fsck:Raye boot 2.0"'

# ------------------------------------------ no boot screen: no messages
setup "plymouth not running"
rm "$CTL/plymouth-up"
echo 3 > "$CTL/time-sde1"
echo 1 > "$CTL/status"
run /dev/sde1
status=$?
ok '[ "$status" -eq 1 ]'
ok '! grep -q "^plymouth" "$CALLS"'
ok '[ -z "$(ls "$RAYE_FSCK_STATE" 2>/dev/null | grep -v "^lock$")" ]'

# ------------- two long checks at once: the other one's message comes back
setup "two drives at once"
echo 3 > "$CTL/time-sda1"
echo 5 > "$CTL/time-sdb1"
( run /dev/sda1 ) &
a=$!
( run /dev/sdb1 ) &
b=$!
wait "$a"
sleep 0.3
ok 'shows raye:fsck:sda1'
ok 'shows raye:fsck:sdb1'
ok 'grep -qxF "plymouth hide-message --text=raye:fsck:sda1" "$CALLS"'
ok '! shows raye:clear'
ok '[ "$(grep -cxF "plymouth display-message --text=raye:fsck:sdb1" "$CALLS")" -eq 2 ]'
wait "$b"
ok '[ "$(tail -n 3 "$CALLS" | head -n 1)" = "plymouth hide-message --text=raye:fsck:sdb1" ]'
ok '[ "$(tail -n 1 "$CALLS")" = "plymouth hide-message --text=raye:clear" ]'

# a state file left by a check that was killed does not come back
setup "stale state file"
mkdir -p "$RAYE_FSCK_STATE"
echo ghost > "$RAYE_FSCK_STATE/999999"
echo 3 > "$CTL/time-sdf1"
run /dev/sdf1
ok '! shows raye:fsck:ghost'
ok 'shows raye:clear'

# --------------------- stopped by systemd: the screen is put back as well
setup "stopped while showing"
echo 30 > "$CTL/time-sdg1"
( run /dev/sdg1; echo $? > "$CTL/exit" ) &
sleep 2.6
ok 'shows raye:fsck:sdg1'
# what systemd does on stop: TERM to every process of the unit
for p in $(pgrep -f -x "/bin/sh $bin/check /dev/sdg1|sh $bin/check /dev/sdg1|$bin/check /dev/sdg1"); do
    kill -TERM "$p" 2>/dev/null
done
wait
ok 'shows raye:clear'
ok '[ "$(cat "$CTL/exit")" -ne 0 ]'

# --------------------------------------- a missing check never stops boot
setup "check missing"
PATH="$bin:/usr/sbin:/usr/bin:/sbin:/bin" sh "$script" "$work/nothing-here" /dev/sdh1 2> "$CTL/err"
status=$?
ok '[ "$status" -eq 0 ]'
ok 'grep -q "not checked" "$CTL/err"'

setup "wrong arguments"
PATH="$bin:/usr/bin:/bin" sh "$script" 2>/dev/null
ok '[ $? -eq 2 ]'

# ------------------------------------------------------------- the drop-in
current="drop-in"
ok '[ -x "$script" ]'
ok '[ "$(grep -c "^ExecStart=" "$dropin")" -eq 2 ]'
ok '[ "$(grep "^ExecStart=" "$dropin" | head -n 1)" = "ExecStart=" ]'
ok '[ "$(grep "^ExecStart=" "$dropin" | tail -n 1)" = "ExecStart=/usr/libexec/raye-fsck-message /usr/lib/systemd/systemd-fsck %f" ]'
ok 'grep -qx "\[Service\]" "$dropin"'
# the stock unit, where this machine has it, still runs the same check
stock=/usr/lib/systemd/system/systemd-fsck@.service
if [ -e "$stock" ]; then
    ok '[ "$(grep "^ExecStart=" "$stock")" = "ExecStart=/usr/lib/systemd/systemd-fsck %f" ]'
fi

echo "raye-fsck-message: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
