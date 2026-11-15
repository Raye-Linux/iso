#!/bin/bash
# raye-gaming depends on raye-scx, so build.sh has to build it, and the
# game scheduler files have to stay as small as they are meant to be.
#   tests/test_scx_in_image.sh
here=$(cd "$(dirname "$0")/.." && pwd)
bad=0
fail() { echo "FAIL: $*"; bad=1; }

grep -q 'compiled_sources() {.*packages/raye-scx' "$here/build.sh" || fail "build.sh does not build packages/raye-scx"
grep -qE '^ +raye-scx,$' "$here/packages/raye-base/debian/control" || fail "raye-gaming does not depend on raye-scx"

g=$here/packages/raye-base/release/gaming
grep -q '^ExecStart=/usr/bin/scx_lavd$' "$g/raye-game-scheduler.service" || fail "unit does not run scx_lavd"
grep -q '^RuntimeMaxSec=6h$' "$g/raye-game-scheduler.service" || fail "unit has no six hour limit"
grep -q '^Restart=no$' "$g/raye-game-scheduler.service" || fail "unit restarts"
grep -q '^start=systemctl --no-ask-password start raye-game-scheduler.service$' "$g/gamemode.ini" || fail "gamemode start line"
grep -q '^end=systemctl --no-ask-password stop raye-game-scheduler.service$' "$g/gamemode.ini" || fail "gamemode end line"
[ "$(grep -c '^\(start\|end\)=' "$g/gamemode.ini")" = 2 ] || fail "gamemode runs something else"

# the polkit rule, run for real when node is there
rule=$g/50-raye-game-scheduler.rules
if command -v node >/dev/null; then
    node -e '
const fs = require("fs");
let rules = [];
const polkit = { addRule: f => rules.push(f), Result: { YES: "yes", NOT_HANDLED: "no" } };
eval(fs.readFileSync(process.argv[1], "utf8"));
const ask = (id, unit, verb, s) => rules[0]({ id, lookup: k => ({ unit, verb })[k] }, s);
const here = { local: true, active: true }, away = { local: true, active: false }, ssh = { local: false, active: true };
const u = "raye-game-scheduler.service", m = "org.freedesktop.systemd1.manage-units";
const want = [
  [ask(m, u, "start", here), "yes"], [ask(m, u, "stop", here), "yes"],
  [ask(m, u, "restart", here), "no"], [ask(m, u, "enable", here), "no"],
  [ask(m, "ssh.service", "start", here), "no"], [ask(m, "ssh.service", "stop", here), "no"],
  [ask(m, u, "start", away), "no"], [ask(m, u, "start", ssh), "no"],
  [ask("org.freedesktop.systemd1.manage-unit-files", u, "start", here), "no"],
];
const wrong = want.filter(([got, w]) => got !== w);
if (wrong.length || rules.length !== 1) { console.log("rule answers wrong:", JSON.stringify(wrong)); process.exit(1); }
' "$rule" || fail "polkit rule"
else
    echo "note: node missing, polkit rule not run"
fi
[ "$bad" = 0 ] && echo "ok: raye-scx is built, the unit and the polkit rule do only their job"
exit $bad
