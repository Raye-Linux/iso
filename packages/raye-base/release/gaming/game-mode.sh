# Shared by raye-game-watch, raye-game-start and raye-game-end: where
# things are, and the person's choices from Settings > Gaming > Game Mode.
#
# ~/.config/raye/game-mode.conf, written by Settings:
#   enabled=true|false     Game Mode itself
#   effects=true|false     blur and see-through backgrounds pause in games
#   scheduler=true|false   the game scheduler while a game runs
#   power=true|false       "Best performance" power mode while plugged in
#   on=KEY ...             Windows programs turned on by hand
#   off=KEY ...            games turned off by hand
# A key is steam:APPID, app:FLATPAK-ID or windows:SPACE. A missing file or
# key means on.

proc=${RAYE_GAME_PROC:-/proc}
sys=${RAYE_GAME_SYS:-/sys}
busctl=${RAYE_GAME_BUSCTL:-busctl}
systemctl=${RAYE_GAME_SYSTEMCTL:-systemctl}
xrt=${RAYE_GAME_XDG_RUNTIME:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}}
runtime=$xrt/raye-game-mode
conf=${RAYE_GAME_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/raye/game-mode.conf}
# the compositor's blur and see-through backgrounds
pausable=${RAYE_GAME_EFFECTS:-blur contrast}
statedir=${RAYE_GAME_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/raye/game-mode}

read_conf() {
    enabled=true effects=true scheduler=true power=true on="" off=""
    [ -r "$conf" ] || return 0
    while IFS='=' read -r key value; do
        case $key in
            enabled) [ "$value" = false ] && enabled=false ;;
            effects) [ "$value" = false ] && effects=false ;;
            scheduler) [ "$value" = false ] && scheduler=false ;;
            power) [ "$value" = false ] && power=false ;;
            on) on=$value ;;
            off) off=$value ;;
        esac
    done < "$conf"
}

# listed "word list" word
listed() {
    case " $1 " in *" $2 "*) return 0 ;; esac
    return 1
}

kwin() { "$busctl" --user --timeout=3 call org.kde.KWin /Effects org.kde.kwin.Effects "$@"; }
