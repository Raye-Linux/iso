#!/bin/sh
# Checks release/grub/raye-update-grub: the real update-grub runs first
# and unchanged, the title pass runs after, and a title pass that fails
# never fails a kernel update.
#
#   sh release/grub/tests/test-raye-update-grub.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
script=$here/../raye-update-grub
[ -f "$script" ] || { echo "FAIL $script is missing"; exit 1; }
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-ug.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0

mkdir -p "$work/usr/sbin" "$work/usr/libexec" "$work/bin"
# The script names absolute paths, so run it against a copy pointed at
# our stand-ins: that is the whole of what we change.
sed -e "s|^real=.*|real=$work/usr/sbin/update-grub.ubuntu|" \
    -e "s|^titles=.*|titles=$work/usr/libexec/raye-grub-titles|" \
    "$script" > "$work/raye-update-grub"

stub() {  # path, exit code, what to write in the trace
    printf '#!/bin/sh\nprintf "%%s %%s\\n" "%s" "$*" >> "%s/trace"\nexit %s\n' \
        "$3" "$work" "$2" > "$1"
    chmod +x "$1"
}

check() { # name, expected exit, expected trace (one entry per line)
    rm -f "$work/trace" "$work/err"
    set +e
    ( cd "$work" && sh "$work/raye-update-grub" "$@" > /dev/null 2> "$work/err" )
    rc=$?
    set -e
    echo "$rc" > "$work/rc"
}

expect() { # name, wanted exit, wanted trace
    got_rc=$(cat "$work/rc")
    got_trace=$(cat "$work/trace" 2>/dev/null || true)
    if [ "$got_rc" = "$2" ] && [ "$got_trace" = "$3" ]; then
        echo "ok   $1"
    else
        echo "FAIL $1"
        echo "     exit $got_rc, wanted $2"
        echo "     trace [$got_trace], wanted [$3]"
        sed 's/^/     err: /' "$work/err"
        failures=$((failures + 1))
    fi
}

# --- both there: the real one, then the titles
stub "$work/usr/sbin/update-grub.ubuntu" 0 real
stub "$work/usr/libexec/raye-grub-titles" 0 titles
check; expect "the real update-grub runs before the title pass" 0 "real 
titles "

# --- arguments are handed on untouched
check -o /boot/grub/grub.cfg
expect "the arguments reach the real one" 0 "real -o /boot/grub/grub.cfg
titles "

# --- the title pass fails: the update must still succeed, and say so
stub "$work/usr/libexec/raye-grub-titles" 1 titles
check
expect "a failed title pass does not fail the update" 0 "real 
titles "
if grep -q "keeps the names grub wrote" "$work/err"; then
    echo "ok   and it says so instead of going quiet"
else
    echo "FAIL it said nothing about the title pass failing"; failures=$((failures + 1))
fi

# --- the real one fails: nothing else runs, and the failure shows
stub "$work/usr/sbin/update-grub.ubuntu" 2 real
stub "$work/usr/libexec/raye-grub-titles" 0 titles
check
expect "a failed update-grub stops there and fails" 2 "real "

# --- the title pass is not installed yet
stub "$work/usr/sbin/update-grub.ubuntu" 0 real
rm -f "$work/usr/libexec/raye-grub-titles"
check
expect "no title pass: the update still works" 0 "real "

echo
if [ "$failures" = 0 ]; then echo "all good"; else echo "$failures failed"; exit 1; fi
