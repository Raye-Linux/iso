#!/bin/bash
#
# A session in French has to be French from its first sign-in. Three of the
# pieces that needs are nothing but a package nobody asked for, and a missing
# one changes no build and fails no test: the words just stay English.
#
#   tests/test_french_session.sh              the lists of this repository
#   tests/test_french_session.sh --root DIR   the image tree DIR as well
#   tests/test_french_session.sh --self-test  show the checks fail on bad input
#
# What each piece is for, measured on the 2026-11-07 image:
#
#  - xdg-user-dirs ships no catalogue of its own. Its French is in
#    language-pack-gnome-fr-base, and the image only had the fr and kde packs,
#    so a new French account got Desktop and Downloads. The same pack holds
#    the words of GTK and GLib. 2.0 MB in the image.
#  - Firefox reads the language of the session as it is (distribution.ini sets
#    intl.locale.requested to ""), but it has no French without firefox-l10n-fr:
#    0.5 MB.
#  - no locale, no language: gettext falls back to English without a word.
#
# Exit 0 when everything holds, 1 otherwise.

here=$(cd "$(dirname "$0")/.." && pwd)
fail=0

complain() {
    echo "FAIL: $*"
    fail=1
}

# the Depends of one package of a control file, comment lines left out
depends_of() {
    awk -v pkg="$2" '
        /^Package:/ { inside = ($2 == pkg); next }
        inside && /^#/ { next }
        inside && /^Depends:/ { on = 1; sub(/^Depends:/, ""); print; next }
        inside && on && /^[ \t]/ { print; next }
        { on = 0 }' "$1"
}

check_lists() { # live.list control
    local live=$1 control=$2 p
    for p in language-pack-fr language-pack-kde-fr language-pack-gnome-fr hunspell-fr; do
        grep -qx "$p" "$live" || complain "$p is not in $live"
    done
    depends_of "$control" raye-desktop | grep -Eq '(^|[ ,])firefox-l10n-fr([ ,]|$)' ||
        complain "raye-desktop does not depend on firefox-l10n-fr"
}

check_image() { # root
    local root=$1 mo found=
    for mo in usr/share/locale-langpack/fr/LC_MESSAGES/xdg-user-dirs.mo \
              usr/share/locale/fr/LC_MESSAGES/xdg-user-dirs.mo; do
        [ -f "$root/$mo" ] && found=$mo
    done
    [ -n "$found" ] || complain "no French catalogue for the user folders in $root"
    compgen -G "$root/usr/lib/firefox/distribution/extensions/langpack-fr@*.xpi" >/dev/null ||
        complain "no French language pack for Firefox in $root"
    grep -Eq '^intl\.locale\.requested=""' "$root/usr/lib/firefox/distribution/distribution.ini" 2>/dev/null ||
        complain "Firefox no longer follows the language of the session in $root"
    grep -Eq '^fr_(CA|FR)\.UTF-8' "$root/var/lib/locales/supported.d/fr" "$root/etc/locale.gen" 2>/dev/null ||
        complain "no French locale is set up in $root"
}

self_test() {
    local tmp bad=0 out
    tmp=$(mktemp -d) || return 1
    trap 'rm -rf "$tmp"' RETURN

    printf 'language-pack-fr\nlanguage-pack-kde-fr\nhunspell-fr\n' > "$tmp/live"
    printf 'Package: raye-desktop\nDepends: firefox,\n# firefox-l10n-fr,\n         ark\n\nPackage: other\nDepends: firefox-l10n-fr\n' > "$tmp/control"
    out=$(fail=0; check_lists "$tmp/live" "$tmp/control"; echo "rc=$fail")
    case $out in *"language-pack-gnome-fr is not"*) ;; *) echo "self-test: a missing pack went unseen"; bad=1 ;; esac
    # a commented line and another package's Depends do not count
    case $out in *"does not depend on firefox-l10n-fr"*) ;; *) echo "self-test: a commented dependency counted"; bad=1 ;; esac

    printf 'language-pack-fr\nlanguage-pack-kde-fr\nlanguage-pack-gnome-fr\nhunspell-fr\n' > "$tmp/live"
    printf 'Package: raye-desktop\nDepends: firefox,\n         firefox-l10n-fr,\n         ark\n' > "$tmp/control"
    out=$(fail=0; check_lists "$tmp/live" "$tmp/control"; echo "rc=$fail")
    [ "$out" = "rc=0" ] || { echo "self-test: good lists refused: $out"; bad=1; }

    mkdir -p "$tmp/root/etc"
    out=$(fail=0; check_image "$tmp/root"; echo "rc=$fail")
    case $out in *"rc=1") ;; *) echo "self-test: an empty image passed"; bad=1 ;; esac

    mkdir -p "$tmp/root/usr/share/locale-langpack/fr/LC_MESSAGES" "$tmp/root/usr/lib/firefox/distribution/extensions"
    : > "$tmp/root/usr/share/locale-langpack/fr/LC_MESSAGES/xdg-user-dirs.mo"
    : > "$tmp/root/usr/lib/firefox/distribution/extensions/langpack-fr@firefox.mozilla.org.xpi"
    printf '[Preferences]\nintl.locale.requested=""\n' > "$tmp/root/usr/lib/firefox/distribution/distribution.ini"
    printf 'fr_CA.UTF-8 UTF-8\n' > "$tmp/root/etc/locale.gen"
    out=$(fail=0; check_image "$tmp/root"; echo "rc=$fail")
    [ "$out" = "rc=0" ] || { echo "self-test: a good image refused: $out"; bad=1; }

    [ "$bad" = 0 ] && echo "ok: self-test"
    return "$bad"
}

root=""
while [ $# -gt 0 ]; do
    case $1 in
        --self-test) self_test; exit $? ;;
        --root) root=${2:?"--root needs a directory"}; shift ;;
        -h|--help) sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

check_lists "$here/config/live.list" "$here/packages/raye-base/debian/control"
if [ -n "$root" ]; then
    [ -d "$root" ] || { echo "no such directory: $root" >&2; exit 2; }
    check_image "$root"
else
    echo "note: no --root given, so the image itself was NOT questioned"
fi
echo
[ "$fail" = 0 ] && echo "ok: the French pieces are there"
exit "$fail"
