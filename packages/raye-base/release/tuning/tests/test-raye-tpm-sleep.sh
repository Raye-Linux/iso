#!/bin/sh
# Checks release/tuning/raye-tpm-sleep (systemd-sleep hook): on a Dell with
# a Nuvoton ("NTC") TPM 2.0 at firmware 7.x it unbinds the TPM before sleep
# and binds it back after; anywhere else it does nothing.
#
#   sh release/tuning/tests/test-raye-tpm-sleep.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
hook=$here/../raye-tpm-sleep
failures=0
ok() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

sh -n "$hook" && ok "sh -n" || fail "sh -n"

# a fake machine: /sys parts, a fake tpm2_getcap, a run folder
setup() { # vendor manufacturer firmware1
    root=$(mktemp -d)
    mkdir -p "$root/dmi" "$root/driver/MSFT0101:00/tpm/tpm0" "$root/run" "$root/bin"
    printf '%s\n' "$1" > "$root/dmi/sys_vendor"
    : > "$root/driver/bind"; : > "$root/driver/unbind"
    cat > "$root/bin/tpm2_getcap" <<EOF
#!/bin/sh
echo "\$*" >> "$root/getcap-args"
cat <<'OUT'
TPM2_PT_MANUFACTURER:
  raw: 0x4E544300
  value: "$2"
TPM2_PT_FIRMWARE_VERSION_1:
  raw: $3
OUT
EOF
    chmod +x "$root/bin/tpm2_getcap"
}
run() { # stage
    RAYE_TPM_DMI=$root/dmi RAYE_TPM_DRIVER=$root/driver RAYE_TPM_RUN=$root/run \
        PATH="$root/bin:$PATH" sh "$hook" "$1" suspend
}

setup "Dell Inc." NTC 0x70002
run pre
[ "$(cat "$root/driver/unbind")" = "MSFT0101:00" ] && ok "Dell + NTC 7.x: unbound before sleep" || fail "Dell + NTC 7.x: unbound before sleep"
grep -q "device:/dev/tpm0" "$root/getcap-args" && ok "asks the right TPM" || fail "asks the right TPM"
rmdir "$root/driver/MSFT0101:00/tpm/tpm0" "$root/driver/MSFT0101:00/tpm" && rmdir "$root/driver/MSFT0101:00"
run post
[ "$(cat "$root/driver/bind")" = "MSFT0101:00" ] && ok "bound again after waking" || fail "bound again after waking"
[ ! -e "$root/run/raye-tpm-sleep" ] && ok "state cleared" || fail "state cleared"
run post
[ "$(cat "$root/driver/bind")" = "MSFT0101:00" ] && ok "a second post does nothing" || fail "a second post does nothing"
rm -rf "$root"

setup "LENOVO" NTC 0x70002
run pre
[ ! -s "$root/driver/unbind" ] && ok "not a Dell: left alone" || fail "not a Dell: left alone"
rm -rf "$root"

setup "Dell Inc." IFX 0x70002
run pre
[ ! -s "$root/driver/unbind" ] && ok "other TPM maker: left alone" || fail "other TPM maker: left alone"
rm -rf "$root"

setup "Dell Inc." NTC 0x10002
run pre
[ ! -s "$root/driver/unbind" ] && ok "other firmware line: left alone" || fail "other firmware line: left alone"
rm -rf "$root"

setup "Dell Inc." NTC 0x70002
rm "$root/bin/tpm2_getcap"
PATH=/usr/bin:/bin RAYE_TPM_DMI=$root/dmi RAYE_TPM_DRIVER=$root/driver RAYE_TPM_RUN=$root/run sh "$hook" pre suspend
[ ! -s "$root/driver/unbind" ] && ok "no tpm2_getcap: left alone" || fail "no tpm2_getcap: left alone"
rm -rf "$root"

[ "$failures" = 0 ] || exit 1
