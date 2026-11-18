#!/bin/sh
# Checks release/access/raye-screen-reader (Ctrl+Win+Enter): it turns the
# screen reader on or off in kaccessrc and starts the accessibility service,
# which starts or stops it.
#
#   sh release/access/tests/test-screen-reader.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
helper=$here/../raye-screen-reader
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-reader.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0
ok() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

# stand-ins: a kaccessrc of key=value lines, and a service that says it ran
mkdir -p "$work/bin"
cat > "$work/bin/kreadconfig6" <<'X'
#!/bin/sh
sed -n 's/^Enabled=//p' "$RC" | tail -n 1 | grep . || echo false
X
cat > "$work/bin/kwriteconfig6" <<'X'
#!/bin/sh
for v; do :; done
echo "Enabled=$v" >> "$RC"
X
printf '#!/bin/sh\necho started >> "%s/ran"\n' "$work" > "$work/bin/kaccess"
chmod +x "$work/bin/"*
export RC=$work/kaccessrc PATH=$work/bin:$PATH

sh "$helper"
[ "$(tail -n 1 "$RC")" = Enabled=true ] && ok "off -> on" || fail "off -> on"
sh "$helper"
[ "$(tail -n 1 "$RC")" = Enabled=false ] && ok "on -> off" || fail "on -> off"
[ "$(wc -l < "$work/ran")" -eq 2 ] && ok "the service reads it each time" || fail "the service reads it each time"

entry=$here/../org.raye.screen-reader.desktop
grep -qx 'X-KDE-Shortcuts=Ctrl+Meta+Return' "$entry" && ok "Ctrl+Win+Enter, as on Windows" || fail "Ctrl+Win+Enter"
grep -qx 'Exec=/usr/libexec/raye-screen-reader' "$entry" && ok "the entry runs the helper" || fail "the entry runs the helper"
grep -q '^Name\[fr\]=' "$entry" && ok "French name" || fail "French name"

echo
[ "$failures" -eq 0 ] && echo "all checks passed" || { echo "$failures check(s) failed"; exit 1; }
