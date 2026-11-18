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
    if HOME=$work/home XDG_CONFIG_HOME= RAYE_START_BIN=$work/bin RAYE_START_XDG=$work/xdg RAYE_START_PGREP=$work/pgrep sh "$helper" "$3"; then rc=0; else rc=$?; fi
    if [ -e "$work/ran" ]; then got=started; else got=skipped; fi
    if [ "$got" = "$2" ] && [ "$rc" = 0 ]; then echo "ok   $1"; else echo "FAIL $1 ($got, exit $rc)"; failures=$((failures + 1)); fi
}

# stand-ins for the real programs: they only say they ran
mkdir -p "$work/bin" "$work/home/.config" "$work/xdg"
for p in kdeconnectd kclockd gmenudbusmenuproxy xembedsniproxy kaccess; do
    printf '#!/bin/sh\ntouch "%s/ran"\n' "$work" > "$work/bin/$p"
    chmod +x "$work/bin/$p"
done
cfg=$work/home/.config
# Xwayland runs or not, as pgrep would say
xwayland() {
    if [ "$1" = up ]; then printf '#!/bin/sh\nexit 0\n'; else printf '#!/bin/sh\nexit 1\n'; fi > "$work/pgrep"
    chmod +x "$work/pgrep"
}
xwayland down

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

check "global menu: nothing uses one" skipped gmenudbusmenuproxy
printf '[org.kde.kdecoration2]\nButtonsOnLeft=\nButtonsOnRight=IAX\n' > "$cfg/kwinrc"
printf '[Containments][2][Applets][5]\nplugin=org.raye.clock\n' > "$cfg/plasma-org.kde.plasma.desktop-appletsrc"
check "global menu: Raye title bar and taskbar" skipped gmenudbusmenuproxy
printf '[Containments][2][Applets][9]\nplugin=org.kde.plasma.appmenu\n' >> "$cfg/plasma-org.kde.plasma.desktop-appletsrc"
check "global menu: in use, but no X11 program yet" skipped gmenudbusmenuproxy
xwayland up
check "global menu: the menu widget is on a bar" started gmenudbusmenuproxy
rm "$cfg/plasma-org.kde.plasma.desktop-appletsrc"
printf '[org.kde.kdecoration2]\nButtonsOnLeft=N\nButtonsOnRight=IAX\n' > "$cfg/kwinrc"
check "global menu: the title bar has the menu button" started gmenudbusmenuproxy
rm "$cfg/kwinrc"
printf '[org.kde.kdecoration2]\nButtonsOnLeft=MN\n' > "$work/xdg/kwinrc"
check "global menu: the button comes from the system's defaults" started gmenudbusmenuproxy
printf '[org.kde.kdecoration2]\nButtonsOnRight=IAX\n' > "$cfg/kwinrc"
check "global menu: the account took the button away" skipped gmenudbusmenuproxy
xwayland down

if HOME=$work/home sh "$helper" no-such-helper 2>/dev/null; then
    echo "FAIL unknown name exits 0"; failures=$((failures + 1))
else
    echo "ok   unknown name is an error, not a silent skip"
fi

check "old tray icons: no X11 program yet" skipped xembedsniproxy
xwayland up
check "old tray icons: X11 is running" started xembedsniproxy
xwayland down

check "accessibility: nothing turned on, no X11 program" skipped kaccess
printf '[ScreenReader]\nEnabled=false\n[Keyboard]\nStickyKeys=false\n' > "$cfg/kaccessrc"
check "accessibility: options there but off" skipped kaccess
xwayland up
check "accessibility: X11 programs get the keyboard settings" started kaccess
xwayland down
printf '[ScreenReader]\nEnabled=true\n' > "$cfg/kaccessrc"
check "accessibility: the screen reader starts at sign-in" started kaccess
printf '[Keyboard]\nSlowKeys=true\n' > "$cfg/kaccessrc"
check "accessibility: a keyboard option is on" started kaccess
printf '[Mouse]\nMouseKeys=true\n' > "$cfg/kaccessrc"
check "accessibility: mouse keys are on" started kaccess
printf '[Other]\nStickyKeys=true\n' > "$cfg/kaccessrc"
check "accessibility: a key of another group does not count" skipped kaccess

# the session units go through the check
for name in gmenudbusmenuproxy xembedsniproxy kaccess; do
    dropin=$here/../user/plasma-$name.service.d/raye-idle.conf
    if grep -qx 'ExecStart=' "$dropin" 2>/dev/null &&
            grep -qx "ExecStart=/usr/libexec/raye-start-if-needed $name" "$dropin"; then
        echo "ok   $name unit starts through the check"
    else
        echo "FAIL $name unit starts through the check"; failures=$((failures + 1))
    fi
done
# and X11 starting brings the two X11 helpers
x11=$here/../../xdg/Xwayland-session.d/50-raye-x11-helpers
if [ -x "$x11" ] && grep -q 'systemctl --user --no-block start' "$x11" &&
        grep -q 'plasma-xembedsniproxy.service' "$x11" && grep -q 'plasma-kaccess.service' "$x11" &&
        grep -q 'plasma-gmenudbusmenuproxy.service' "$x11"; then
    echo "ok   X11 starting brings the X11 helpers"
else
    echo "FAIL X11 starting brings the X11 helpers"; failures=$((failures + 1))
fi

echo
[ "$failures" -eq 0 ] && echo "all checks passed" || { echo "$failures check(s) failed"; exit 1; }
