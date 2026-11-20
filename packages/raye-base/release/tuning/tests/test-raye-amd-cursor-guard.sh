#!/bin/sh
# Checks release/tuning/raye-amd-cursor-guard, the sign-in screen's way
# into raye-amd-cursor.
#
# raye-desktop ships the sign-in screen's settings; raye-amd-cursor comes
# with raye-system. When apt brought the first without the second (Raye
# Update installing in use, 2026-11-19), SDDM was told to start a program
# that was not there: no sign-in screen, then an X11 one where neither the
# mouse nor the keyboard answered. The guard ships with the settings that
# name it, so it is always there, and starts KWin plainly when the helper
# is missing.
#
#   sh release/tuning/tests/test-raye-amd-cursor-guard.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
tool=$here/../raye-amd-cursor-guard
top=$here/../../..
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-amd-cursor-guard.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; failures=$((failures + 1)); }

[ -f "$tool" ] || { echo "FAIL $tool is missing"; exit 1; }
[ -x "$tool" ] || bad "the guard is not executable"

# a command that says what it was given
printf '#!/bin/sh\necho "cmd $*"\n' > "$work/show"
# a stand-in for raye-amd-cursor that says it ran, then runs the command
printf '#!/bin/sh\necho helper\n[ $# -gt 0 ] || { echo KWIN_FORCE_SW_CURSOR=1; exit 0; }\nexec "$@"\n' > "$work/helper"
chmod +x "$work/show" "$work/helper"

# 1. the helper is there: the command goes through it, arguments intact
got=$(RAYE_AMD_CURSOR=$work/helper "$tool" "$work/show" --drm "a b")
want=$(printf 'helper\ncmd --drm a b')
[ "$got" = "$want" ] && ok "with the helper: through it" || bad "with the helper: '$got'"

# 2. the helper is missing: the command starts by itself, nothing else
got=$(RAYE_AMD_CURSOR=$work/nothing-here "$tool" "$work/show" --drm)
[ "$got" = "cmd --drm" ] && ok "without the helper: KWin starts plainly" || bad "without the helper: '$got'"

# 3. there but not runnable (a half-unpacked package): same as missing
: > "$work/notrun"
got=$(RAYE_AMD_CURSOR=$work/notrun "$tool" "$work/show" x)
[ "$got" = "cmd x" ] && ok "a helper that cannot run is skipped" || bad "not runnable: '$got'"

# 4. as a user-environment generator (no arguments)
got=$(RAYE_AMD_CURSOR=$work/helper "$tool")
want=$(printf 'helper\nKWIN_FORCE_SW_CURSOR=1')
[ "$got" = "$want" ] && ok "generator, with the helper: its output" || bad "generator with the helper: '$got'"
if got=$(RAYE_AMD_CURSOR=$work/nothing-here "$tool"); then
    [ -z "$got" ] && ok "generator, without the helper: nothing, exit 0" || bad "generator without the helper said '$got'"
else
    bad "generator without the helper failed"
fi

# 5. the exit status of the command is kept
printf '#!/bin/sh\nexit 7\n' > "$work/seven"; chmod +x "$work/seven"
set +e
RAYE_AMD_CURSOR=$work/nothing-here "$tool" "$work/seven"; rc=$?
set -e
[ "$rc" = 7 ] && ok "the command's exit status is kept" || bad "exit status $rc"

# 6. the settings that name the guard ship in the same package as the guard,
# and the generator link points at the guard, never at another package's file
paths=$top/debian/raye-release-paths
conf_pkg=$(awk '$2 == "release/tuning/sddm-wayland-raye.conf" { print $1 }' "$paths")
guard_pkg=$(awk '$2 == "release/tuning/raye-amd-cursor-guard" { print $1 }' "$paths")
guard_dest=$(awk '$2 == "release/tuning/raye-amd-cursor-guard" { print $3 }' "$paths")
if [ -n "$conf_pkg" ] && [ "$conf_pkg" = "$guard_pkg" ]; then ok "guard and sign-in settings in one package ($conf_pkg)"
else bad "sign-in settings in '$conf_pkg', guard in '$guard_pkg'"; fi
cmd=$(sed -n 's/^CompositorCommand=//p' "$here/../sddm-wayland-raye.conf")
case $cmd in
"/$guard_dest kwin_wayland "*) ok "the sign-in KWin starts through the guard" ;;
*) bad "sign-in KWin command: '$cmd' (guard at '/$guard_dest')" ;;
esac
link=$(grep 'user-environment-generators/' "$top/debian/$conf_pkg.links" || true)
[ "${link%% *}" = "$guard_dest" ] && ok "the generator link points at the guard" || bad "generator link: '$link'"

echo
if [ "$failures" = 0 ]; then echo "all good"; else echo "$failures failed"; exit 1; fi
