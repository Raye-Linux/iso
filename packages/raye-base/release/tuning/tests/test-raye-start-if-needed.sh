#!/bin/sh
# Checks release/tuning/raye-start-if-needed: each helper starts at
# sign-in only when the account gives it something to do; an unknown name
# is an error that shows in the log, never a silent skip.
#
#   sh release/tuning/tests/test-raye-start-if-needed.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
helper=$here/../raye-start-if-needed
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-start.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0
check() { # name, expected (started|skipped), helper argument
    rm -f "$work/ran"
    if HOME=$work/home XDG_CONFIG_HOME= RAYE_START_BIN=$work/bin sh "$helper" "$3"; then rc=0; else rc=$?; fi
    if [ -e "$work/ran" ]; then got=started; else got=skipped; fi
    if [ "$got" = "$2" ] && [ "$rc" = 0 ]; then echo "ok   $1"; else echo "FAIL $1 ($got, exit $rc)"; failures=$((failures + 1)); fi
}

# stand-ins for the real programs: they only say they ran
mkdir -p "$work/bin" "$work/home/.config"
for p in kdeconnectd kclockd; do
    printf '#!/bin/sh\ntouch "%s/ran"\n' "$work" > "$work/bin/$p"
    chmod +x "$work/bin/$p"
done
cfg=$work/home/.config

check "phone service: no phone paired" skipped kdeconnect
mkdir -p "$cfg/kdeconnect"
printf '[abc]\nname=Phone\n' > "$cfg/kdeconnect/trusted_devices"
check "phone service: a phone is paired" started kdeconnect

check "alarms: Clock never used" skipped kclockd
printf '[Timers]\ntimers={"list":[]}\n' > "$cfg/kclockdrc"
check "alarms: only timers (they never run at sign-in)" skipped kclockd
printf '[Alarms]\n' >> "$cfg/kclockdrc"
check "alarms: empty alarm list" skipped kclockd
printf '{6f1c}={"name":"Wake up"}\n' >> "$cfg/kclockdrc"
check "alarms: an alarm is set" started kclockd

if HOME=$work/home sh "$helper" no-such-helper 2>/dev/null; then
    echo "FAIL unknown name exits 0"; failures=$((failures + 1))
else
    echo "ok   unknown name is an error, not a silent skip"
fi

echo
[ "$failures" -eq 0 ] && echo "all checks passed" || { echo "$failures check(s) failed"; exit 1; }
