#!/bin/sh
# Checks Game Mode's scripts in release/gaming: which processes the watcher
# hands to GameMode, what starting and ending game mode changes on the
# desktop, and that ending puts back exactly that.
#
#   sh release/gaming/tests/test-game-mode.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
gaming=$here/..
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-game.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0
ok() { echo "ok   $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }
expect() { # name, command...
    name=$1; shift
    if "$@"; then ok "$name"; else fail "$name"; fi
}
has() { grep -qF -- "$2" "$1" 2>/dev/null; }
hasnt() { ! grep -qF -- "$2" "$1" 2>/dev/null; }

home=$work/home proc=$work/proc sys=$work/sys xrt=$work/run log=$work/log
mkdir -p "$home/.config/raye" "$proc" "$sys/kernel/sched_ext" "$xrt" "$work/bin" "$work/exports"
export HOME=$home XDG_CONFIG_HOME= XDG_STATE_HOME= XDG_RUNTIME_DIR=
export RAYE_GAME_LIB=$gaming/game-mode.sh RAYE_GAME_PROC=$proc RAYE_GAME_SYS=$sys
export RAYE_GAME_XDG_RUNTIME=$xrt RAYE_GAME_BUSCTL=$work/bin/busctl RAYE_GAME_SYSTEMCTL=$work/bin/systemctl
export RAYE_GAME_PPCTL=$work/bin/powerprofilesctl RAYE_GAME_SCX=$work/bin/scx_lavd
export RAYE_GAME_FLATPAK_EXPORTS=$work/exports RAYE_GAME_STEAM_LIBS=$work/steamapps
export RAYE_GAME_STEAM_PIDFILES=$work/steam.pid
conf=$home/.config/raye/game-mode.conf

# stand-ins: each writes what it was asked to the log
cat > "$work/bin/busctl" <<'SH'
#!/bin/sh
echo "busctl $*" >> "$RAYE_TEST_LOG"
case "$*" in
    *isEffectLoaded*) e=$(eval echo \${$#}); if grep -qx "$e" "$RAYE_TEST_KWIN" 2>/dev/null; then echo "b true"; else echo "b false"; fi ;;
    *unloadEffect*) e=$(eval echo \${$#}); grep -vx "$e" "$RAYE_TEST_KWIN" > "$RAYE_TEST_KWIN.new"; mv "$RAYE_TEST_KWIN.new" "$RAYE_TEST_KWIN" ;;
    *" loadEffect"*) e=$(eval echo \${$#}); echo "$e" >> "$RAYE_TEST_KWIN"; echo "b true" ;;
    *RegisterGameByPID*) [ -e "$RAYE_TEST_NOGAMEMODE" ] && exit 1; echo "i 0" ;;
esac
SH
cat > "$work/bin/systemctl" <<'SH'
#!/bin/sh
echo "systemctl $*" >> "$RAYE_TEST_LOG"
case "$*" in *is-active*) [ -e "$RAYE_TEST_ACTIVE" ] ;; esac
SH
cat > "$work/bin/powerprofilesctl" <<'SH'
#!/bin/sh
echo "powerprofilesctl $*" >> "$RAYE_TEST_LOG"
[ "$1" = list ] && cat "$RAYE_TEST_PROFILES"
exit 0
SH
printf '#!/bin/sh\n' > "$work/bin/scx_lavd"
chmod +x "$work/bin/"*
export RAYE_TEST_LOG=$log RAYE_TEST_KWIN=$work/kwin RAYE_TEST_ACTIVE=$work/active
export RAYE_TEST_PROFILES=$work/profiles RAYE_TEST_NOGAMEMODE=$work/no-gamemode

nul() { printf '%s\0' "$@"; }
process() { # pid, then argv...
    pid=$1; shift
    mkdir -p "$proc/$pid"
    nul "$@" > "$proc/$pid/cmdline"
    : > "$proc/$pid/environ"
}
environ() { pid=$1; shift; nul "$@" > "$proc/$pid/environ"; }
gone() { rm -r "$proc/$1"; }
watch() { : > "$log"; sh "$gaming/raye-game-watch" --once; }
registered() { has "$log" "RegisterGameByPID ii $$ $1" || grep -q "RegisterGameByPID ii [0-9]* $1\$" "$log"; }
unregistered() { grep -q "UnregisterGameByPID ii [0-9]* $1\$" "$log"; }
seen() { grep -q "^$1	" "$home/.local/state/raye/game-mode/games" 2>/dev/null; }

# ---------------------------------------------------------------- Steam
mkdir -p "$work/steamapps"
printf '"AppState"\n{\n\t"appid"\t\t"570"\n\t"name"\t\t"Dota 2"\n}\n' > "$work/steamapps/appmanifest_570.acf"
process 100 /app/bin/steam
process 101 /home/u/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=570 -- /x/steam-launch-wrapper -- game
process 102 /x/steam-launch-wrapper -- game
echo 99 > "$work/steam.pid"
watch
expect "steam: nothing is searched while Steam is not running" eval '! registered 101'
echo 100 > "$work/steam.pid"
watch
expect "steam: the game's reaper is handed to GameMode" registered 101
expect "steam: not Steam itself" eval '! registered 100'
expect "steam: not the wrapper under the reaper" eval '! registered 102'
expect "steam: the game is listed with its name" seen steam:570
expect "steam: its name comes from the app manifest" has "$home/.local/state/raye/game-mode/games" "Dota 2"
watch
expect "steam: a game is handed over once" eval '! registered 101'
process 103 /x/reaper SteamLaunch AppId=228980 -- redist
watch
expect "steam: the common redistributables are not a game" eval '! registered 103'
gone 101; gone 103
rm "$work/steam.pid"
process 104 /x/reaper SteamLaunch AppId=570 -- x
watch
expect "steam: Steam from the Store is found through its sandbox" eval '! registered 104'
mkdir -p "$xrt/.flatpak/9" && printf '[Application]\nname=com.valvesoftware.Steam\n' > "$xrt/.flatpak/9/info"
printf '{"child-pid": 100}' > "$xrt/.flatpak/9/bwrapinfo.json"
watch
expect "steam: ... and its games are handed over" registered 104
gone 104
rm -r "$xrt/.flatpak/9"
echo 100 > "$work/steam.pid"

# ------------------------------------------------------- Store (Flatpak)
flatpak() { # instance, app id, pid
    mkdir -p "$xrt/.flatpak/$1"
    printf '[Application]\nname=%s\nruntime=runtime/org.freedesktop.Platform/x86_64/24.08\n\n[Instance]\ninstance-id=%s\n' "$2" "$1" > "$xrt/.flatpak/$1/info"
    printf '{\n    "child-pid": %s\n}\n' "$3" > "$xrt/.flatpak/$1/bwrapinfo.json"
    process "$3" bwrap --args 40 "$2"
}
desktop() { printf '[Desktop Entry]\nName=%s\nCategories=%s\n' "$2" "$3" > "$work/exports/$1.desktop"; }
desktop org.vinegarhq.Sober Sober "Game;"
desktop org.gnome.Calculator Calculator "GTK;Utility;"
desktop com.valvesoftware.Steam Steam "Network;FileTransfer;Game;"
desktop net.supertuxkart.SuperTuxKart SuperTuxKart "Game;ArcadeGame;"
flatpak 1111 org.vinegarhq.Sober 200
flatpak 1112 org.gnome.Calculator 201
flatpak 1113 com.valvesoftware.Steam 202
watch
expect "store: a game from the Store is handed to GameMode" registered 200
expect "store: an app that is not a game is not" eval '! registered 201'
expect "store: Steam is a launcher, not a game" eval '! registered 202'
expect "store: listed with the name of its Start entry" has "$home/.local/state/raye/game-mode/games" "app:org.vinegarhq.Sober	Sober"
mkdir -p "$xrt/.flatpak/1114"
printf '[Application]\nname=net.supertuxkart.SuperTuxKart\n' > "$xrt/.flatpak/1114/info"
watch
expect "store: an instance still starting is looked at again" eval '! registered 203'
printf '{"child-pid": 203}' > "$xrt/.flatpak/1114/bwrapinfo.json"
process 203 bwrap
watch
expect "store: ... and handed over once it runs" registered 203
gone 200; gone 201; gone 202; gone 203
rm -r "$xrt/.flatpak"

# --------------------------------------------------------- Windows layer
winproc() { # pid, argv0, space, kind, ignore
    process "$1" "$2"
    environ "$1" HOME=/home/u "RAYE_GAME_SPACE=$3" "RAYE_GAME_KIND=$4" "RAYE_GAME_NAME=Program $3" "RAYE_GAME_IGNORE=$5"
}
winproc 300 'C:\Games\Witcher\witcher3.exe' witcher3 yes ""
winproc 301 'C:\windows\system32\services.exe' witcher3 yes ""
winproc 302 /opt/raye-wine/bin/wineserver witcher3 yes ""
winproc 310 'C:\Program Files (x86)\Battle.net\Battle.net.exe' battle-net launcher "battle.net.exe;agent.exe"
winproc 311 'C:\Program Files (x86)\Overwatch\_retail_\Overwatch.exe' battle-net launcher "battle.net.exe;agent.exe"
winproc 320 'C:\Program Files\Notepad++\notepad++.exe' notepad-plus-plus "" ""
winproc 330 /usr/bin/sh witchy yes ""
mkdir -p "$xrt/raye-game-mode/windows"
watch
expect "windows: nothing is searched until the runner says a program runs" eval '! registered 300'
: > "$xrt/raye-game-mode/windows/330"
watch
expect "windows: a game's .exe is handed to GameMode" registered 300
expect "windows: the layer's own services are not" eval '! registered 301'
expect "windows: nor the server process" eval '! registered 302'
expect "windows: a launcher is not a game" eval '! registered 310'
expect "windows: a game the launcher started is" registered 311
expect "windows: a program nobody marked as a game is not" eval '! registered 320'
expect "windows: the runner before it becomes the program is not" eval '! registered 330'
process 330 'C:\Games\witchy.exe'
environ 330 "RAYE_GAME_SPACE=witchy" "RAYE_GAME_KIND=yes"
watch
expect "windows: ... and is, once it has become the program" registered 330
gone 330

# --------------------------------------------------------- your choices
printf 'on=windows:notepad-plus-plus\n' > "$conf"
watch
expect "choices: a Windows program turned on in Settings is handed over" registered 320
printf 'off=windows:witcher3 windows:notepad-plus-plus\n' > "$conf"
watch
expect "choices: a game turned off while it runs is taken back" unregistered 300
expect "choices: ... the other one too" unregistered 320
expect "choices: a game left on stays" eval '! unregistered 311'
printf 'enabled=false\n' > "$conf"
watch
expect "choices: Game Mode off gives every game back" unregistered 311
process 340 /x/reaper SteamLaunch AppId=570 -- x
watch
expect "choices: with Game Mode off nothing new is handed over" eval '! registered 340'
rm "$conf"
watch
expect "choices: without a settings file Game Mode is on" registered 340
gone 300; gone 301; gone 302; gone 310; gone 311; gone 320; gone 340

: > "$work/no-gamemode"
process 350 /x/reaper SteamLaunch AppId=570 -- x
watch
rm "$work/no-gamemode"
watch
expect "a game GameMode could not take yet is tried again" registered 350
gone 350

# ------------------------------------------------- start and end of play
run_start() { : > "$log"; sh "$gaming/raye-game-start"; }
run_end() { : > "$log"; sh "$gaming/raye-game-end"; }
printf 'blur\ncontrast\nraye_windows\n' > "$work/kwin"
run_start
expect "start: blur stops while a game runs" eval '! grep -qx blur "$work/kwin"'
expect "start: see-through backgrounds stop too" eval '! grep -qx contrast "$work/kwin"'
expect "start: other effects are left alone" grep -qx raye_windows "$work/kwin"
expect "start: the game scheduler starts" has "$log" "systemctl --no-ask-password start raye-game-scheduler.service"
expect "start: Settings can say Game Mode is on now" test -e "$xrt/raye-game-mode/active"
run_end
expect "end: blur comes back" grep -qx blur "$work/kwin"
expect "end: see-through backgrounds come back" grep -qx contrast "$work/kwin"
expect "end: the game scheduler stops" has "$log" "systemctl --no-ask-password stop raye-game-scheduler.service"
expect "end: nothing is left behind" test ! -e "$xrt/raye-game-mode/effects"
expect "end: Settings no longer says on now" test ! -e "$xrt/raye-game-mode/active"

printf 'raye_windows\n' > "$work/kwin"
run_start; run_end
expect "end: an effect that was off before stays off" eval '! grep -qx blur "$work/kwin"'
printf 'blur\ncontrast\n' > "$work/kwin"
printf 'effects=false\nscheduler=false\n' > "$conf"
run_start
expect "start: effects kept when you said so" grep -qx blur "$work/kwin"
expect "start: no game scheduler when you said so" hasnt "$log" "raye-game-scheduler"
run_end
expect "end: nothing to stop that was not started" hasnt "$log" "stop raye-game-scheduler"
rm "$conf"
rmdir "$sys/kernel/sched_ext"
run_start
expect "start: no game scheduler on a kernel without sched_ext" hasnt "$log" "raye-game-scheduler"
run_end
mkdir "$sys/kernel/sched_ext"
printf 'enabled=false\n' > "$conf"
printf 'blur\n' > "$work/kwin"
run_start
expect "start: Game Mode off leaves the desktop alone (gamemoderun by hand)" grep -qx blur "$work/kwin"
run_end
rm "$conf"

# ----------------------------------------------------------- power mode
hold() { : > "$log"; sh "$gaming/raye-game-hold" --check; }
battery() { # online of the charger, or "none" for a desktop
    rm -rf "$sys/class/power_supply"; mkdir -p "$sys/class/power_supply/BAT0" "$sys/class/power_supply/AC"
    echo Battery > "$sys/class/power_supply/BAT0/type"
    echo Mains > "$sys/class/power_supply/AC/type"
    echo "$1" > "$sys/class/power_supply/AC/online"
}
printf '  performance:\n    CpuDriver:\tamd_pstate\n\n* balanced:\n    CpuDriver:\tamd_pstate\n' > "$work/profiles"
battery 1
hold
expect "power: plugged in, best performance is held" has "$log" "powerprofilesctl launch --profile performance"
battery 0
hold
expect "power: on battery, your power mode stays" hasnt "$log" "launch"
rm -rf "$sys/class/power_supply"
hold
expect "power: a desktop PC counts as plugged in" has "$log" "launch"
printf 'power=false\n' > "$conf"
hold
expect "power: turned off in Settings, nothing held" hasnt "$log" "launch"
printf 'enabled=false\n' > "$conf"
hold
expect "power: Game Mode off, nothing held" hasnt "$log" "launch"
rm "$conf"
printf '* balanced:\n\n  power-saver:\n' > "$work/profiles"
hold
expect "power: no best performance mode on this PC, nothing held" hasnt "$log" "launch"

echo
if [ "$failures" -eq 0 ]; then echo "all passed"; else echo "$failures failed"; exit 1; fi
