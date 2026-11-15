#!/bin/bash
#
# Which applications the Start menu shows under someone else's brand.
#
# Raye ships Plasma, so the image carries KDE's .desktop files. Most are
# daemons or hidden and never appear in the menu; a few do, and a user then
# reads "KDE Connect" in a menu that is otherwise Raye's.
#
#   tests/test_menu_brands.sh                the repository cannot answer this
#                                            on its own; it says so
#   tests/test_menu_brands.sh --root DIR     question the image tree DIR
#                                            ($RAYE_ROOT is read the same way)
#   tests/test_menu_brands.sh --list         print every menu-visible entry
#   tests/test_menu_brands.sh --self-test    show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# This test freezes the PERIMETER:
#
#   * an entry under a foreign brand that is NOT in KNOWN below -> FAIL.
#     A new one appeared, probably with a new package, and nobody chose it.
#   * an entry of KNOWN that is gone -> a note asking to shorten the list.
#     Fixing a leak must never turn this test red.
#
# ---------------------------------------------------------------------
# Measured on 2026-11-06 against the beta image. Both traps below produced a
# wrong count before they were understood, and that is why they are written
# down rather than merely handled:
#
# NotShowIn. kdesystemsettings.desktop ("KDE System Settings") and
# org.kde.kdeconnect.nonplasma.desktop ("KDE Connect Indicator") look like
# leaks and are not: both carry NotShowIn=KDE;, and both Raye sessions
# declare DesktopNames=KDE, so Plasma hides them. A scan that honours only
# NoDisplay/Hidden/OnlyShowIn reports five leaks where there are three.
#
# ABSOLUTE SYMLINKS. /usr/share/applications/wine.desktop is a symlink to
# /opt/wine-stable/share/applications/wine.desktop. Read from outside the
# image that resolves against the TEST MACHINE's root, where it does not
# exist, and the file reads as a broken link. It is not broken, and inside
# the image it says NoDisplay=true, so it is not a leak either.
#
# The session names are read from the image's own session files, never
# assumed: the day Raye stops calling its session KDE, NotShowIn=KDE stops
# hiding anything and those entries appear. That is exactly the kind of
# change this test exists to notice.

set -uo pipefail

ROOT=${RAYE_ROOT:-}
MODE=check

# The entries allowed to show a foreign brand: none since raye-desktop puts
# its own entries in place (release/identity/apps). Each one is a FILE NAME,
# because a Name can be translated and a file name cannot. Never lengthen
# this list without saying, in the commit, which package brought the entry.
KNOWN=""

fail=0
err() { echo "FAIL: $*"; fail=1; }
note() { echo "note: $*"; }
ok() { echo "ok: $*"; }

# Every menu-visible entry of a tree, as "file<TAB>Name", and the brands it
# found. The rules are XDG's -- Type, NoDisplay, Hidden, OnlyShowIn and
# NotShowIn -- judged against the session names the tree itself declares.
scan() {
    python3 -I - "$1" <<'PY'
import os, re, sys

root = sys.argv[1]
apps = os.path.join(root, "usr/share/applications")
brands = re.compile(r'\b(KDE|Kubuntu|Ubuntu|Canonical|Plasma|GNOME|Debian|Wine\w*|KWallet\w*)\b')


def read(path, depth=0):
    """A file of the image, following an absolute symlink inside it."""
    while os.path.islink(path) and depth < 16:
        target = os.readlink(path)
        path = (root + target) if target.startswith("/") \
            else os.path.join(os.path.dirname(path), target)
        depth += 1
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def main_group(text):
    # the group by name: a comment above it is common, and the part before
    # the first group header is then not the entry at all
    found = re.search(r'^\[Desktop Entry\][^\n]*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)
    body = found.group(1) if found else ""

    def field(key):
        m = re.search(r'^%s=(.*)$' % key, body, re.M)
        return m.group(1).strip() if m else None
    return field


sessions = set()
for where in ("usr/share/wayland-sessions", "usr/share/xsessions"):
    full = os.path.join(root, where)
    if not os.path.isdir(full):
        continue
    for name in os.listdir(full):
        if not name.endswith(".desktop"):
            continue
        try:
            field = main_group(read(os.path.join(full, name)))
        except OSError:
            continue
        sessions.update(x for x in (field("DesktopNames") or "").split(";") if x)
print("sessions=%s" % ";".join(sorted(sessions)))

if not os.path.isdir(apps):
    print("error=no usr/share/applications in %s" % root)
    raise SystemExit(0)

for name in sorted(os.listdir(apps)):
    if not name.endswith(".desktop"):
        continue
    try:
        field = main_group(read(os.path.join(apps, name)))
    except OSError as exc:
        print("unreadable=%s\t%s" % (name, exc))
        continue
    if (field("Type") or "Application") != "Application":
        continue
    if (field("NoDisplay") or "").lower() == "true":
        continue
    if (field("Hidden") or "").lower() == "true":
        continue
    only = field("OnlyShowIn")
    if only and not (sessions & {x for x in only.split(";") if x}):
        continue
    nots = field("NotShowIn")
    if nots and (sessions & {x for x in nots.split(";") if x}):
        continue
    shown = field("Name") or name
    print("visible=%s\t%s" % (name, shown))
    if brands.search(shown):
        print("brand=%s\t%s" % (name, shown))
PY
}

check_tree() {
    local root=$1 out file shown found="" seen n=0 sessions
    out=$(scan "$root") || { err "the menu of $root could not be read"; return; }

    if grep -q '^error=' <<<"$out"; then
        err "$(sed -n 's/^error=//p' <<<"$out")"
        return
    fi
    sessions=$(sed -n 's/^sessions=//p' <<<"$out")
    if [ -z "$sessions" ]; then
        note "this tree declares no session name, so NotShowIn hides nothing here;" \
             "an entry that names a session counts as visible"
    else
        note "session names declared by the image: $sessions"
    fi
    n=$(grep -c '^visible=' <<<"$out" || true)
    [ "$n" -gt 0 ] || { err "no menu entry at all in $root: the scan found nothing"; return; }
    note "$n entries would show in the menu"

    while IFS=$'\t' read -r file shown; do
        [ -n "$file" ] || continue
        found="$found$file"$'\n'
        if grep -qxF "$file" <<<"$KNOWN"; then
            note "known: $file shows \"$shown\""
        else
            err "$file shows \"$shown\" in the menu, and it is not one of the known" \
                "ones. A new package brought it, or an entry stopped being hidden." \
                "Hide it or rename it in packages/raye-base/release/identity/apps," \
                "or add the file to KNOWN and say in the commit what brought it"
        fi
    done < <(sed -n 's/^brand=//p' <<<"$out")

    while read -r seen; do
        [ -n "$seen" ] || continue
        grep -qxF "$seen" <<<"$found" ||
            note "gone: $seen no longer shows a foreign brand -- take it out of KNOWN"
    done <<<"$KNOWN"

    while IFS=$'\t' read -r file shown; do
        [ -n "$file" ] && err "$file cannot be read inside the image: $shown"
    done < <(sed -n 's/^unreadable=//p' <<<"$out")

    [ "$fail" = 0 ] && ok "the menu shows no foreign brand beyond the $(grep -c . <<<"$KNOWN") known ones"
}

self_test() {
    local t good=1 out
    # the mechanism is tested on a list of its own, whatever the real one holds
    KNOWN="org.kde.kdeconnect.app.desktop
org.kde.kdeconnect.sms.desktop
org.kde.partitionmanager.desktop"
    t=$(mktemp -d)
    mkdir -p "$t/img/usr/share/applications" "$t/img/usr/share/wayland-sessions" \
             "$t/img/opt/elsewhere" "$t/vide/usr/share/applications"
    printf '[Desktop Entry]\nName=Raye\nDesktopNames=KDE\n' \
        > "$t/img/usr/share/wayland-sessions/plasma.desktop"
    mk() { printf '[Desktop Entry]\nType=Application\nName=%s\n%s\n' "$2" "${3-}" \
           > "$t/img/usr/share/applications/$1"; }
    mk raye-files.desktop "Files"
    mk org.kde.kdeconnect.app.desktop "KDE Connect"
    mk org.kde.kdeconnect.sms.desktop "KDE Connect SMS"
    mk org.kde.partitionmanager.desktop "KDE Partition Manager"
    mk kdesystemsettings.desktop "KDE System Settings" "NotShowIn=KDE;"
    mk org.kde.kdeconnect.nonplasma.desktop "KDE Connect Indicator" "NotShowIn=KDE;"
    printf '[Desktop Entry]\nType=Application\nName=Wine Windows Program Loader\nNoDisplay=true\n' \
        > "$t/img/opt/elsewhere/wine.desktop"
    ln -s /opt/elsewhere/wine.desktop "$t/img/usr/share/applications/wine.desktop"

    # the three known ones and nothing else: green
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null ||
        { echo "self-test: l image de reference est refusee"; good=0; }
    # and green for the RIGHT reason, not by luck: without the NotShowIn
    # rule the two entries above would be reported, and without following the
    # absolute symlink wine.desktop would read as broken
    out=$(fail=0; check_tree "$t/img" 2>&1)
    grep -q 'kdesystemsettings' <<<"$out" &&
        { echo "self-test: NotShowIn=KDE n est pas honore"; good=0; }
    grep -q 'wine.desktop cannot be read' <<<"$out" &&
        { echo "self-test: un lien absolu dans l arbre est lu comme casse"; good=0; }

    # a new leak
    mk org.kde.somethingnew.desktop "KDE Something New"
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null &&
        { echo "self-test: une nouvelle fuite de marque non attrapee"; good=0; }
    rm -f "$t/img/usr/share/applications/org.kde.somethingnew.desktop"

    # an entry that stopped being hidden
    mk kdesystemsettings.desktop "KDE System Settings"
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null &&
        { echo "self-test: une entree qui cesse d etre cachee non attrapee"; good=0; }
    mk kdesystemsettings.desktop "KDE System Settings" "NotShowIn=KDE;"

    # a comment above the group hid NoDisplay and Name from the scan: a real
    # leak read as a nameless entry, and a hidden entry as a visible one
    printf '# made by a tool\n[Desktop Entry]\nType=Application\nName=KDE Hidden One\n' \
        > "$t/img/usr/share/applications/org.kde.commented.desktop"
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null &&
        { echo "self-test: an entry with a comment on top hides its brand"; good=0; }
    printf '# made by a tool\n[Desktop Entry]\nType=Application\nName=KDE Hidden One\nNoDisplay=true\n' \
        > "$t/img/usr/share/applications/org.kde.commented.desktop"
    grep -q 'org.kde.commented' <<<"$(fail=0; scan "$t/img" | grep ^visible=)" &&
        { echo "self-test: NoDisplay under a comment on top is not read"; good=0; }
    rm -f "$t/img/usr/share/applications/org.kde.commented.desktop"

    # the other names of the layer underneath are brands too
    mk winetricks.desktop "Winetricks"
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null &&
        { echo "self-test: Winetricks is not caught"; good=0; }
    rm -f "$t/img/usr/share/applications/winetricks.desktop"

    # a leak removed: a note, never a failure -- a test that goes red when
    # the defect is fixed is a test that argues against its own purpose
    rm -f "$t/img/usr/share/applications/org.kde.kdeconnect.sms.desktop"
    (fail=0; check_tree "$t/img"; exit $fail) >/dev/null ||
        { echo "self-test: retirer une fuite rend le test rouge, ce qui punit le correctif"; good=0; }
    grep -q 'gone: org.kde.kdeconnect.sms.desktop' <<<"$(fail=0; check_tree "$t/img" 2>&1)" ||
        { echo "self-test: une fuite disparue n est pas signalee"; good=0; }

    # an empty tree proves nothing, so it must not pass
    (fail=0; check_tree "$t/vide"; exit $fail) >/dev/null &&
        { echo "self-test: un arbre sans aucune entree passe"; good=0; }

    rm -r -f "$t"
    [ "$good" = 1 ] && echo "self-test ok"
    [ "$good" = 1 ]
}

while [ $# -gt 0 ]; do
    case $1 in
        --root) ROOT=${2:?--root needs a directory}; shift ;;
        --list) MODE=list ;;
        --self-test) self_test; exit $? ;;
        *) sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    esac
    shift
done

if [ -z "$ROOT" ]; then
    # Nothing is guessed. This question has no answer in the repository: the
    # entries come from the desktop's own packages, and only the finished
    # image holds them all.
    # 77, not 0. Exiting 0 here prints a note and NOTHING countable, so
    # tools/raye-tests reports "nothing could be counted in the output: the
    # suite may not have run at all" -- a FAIL on a run that was simply asked
    # for --no-iso. Measured 2026-11-07: `raye-tests --repo iso --no-iso` went
    # red on this suite alone, over a repository with nothing wrong with it.
    #
    # And the other direction is worse: a suite that exits 0 having checked
    # nothing is the shape this tree refuses everywhere else. 77 is the skip
    # code the launcher reads, with the last line as the reason, and four
    # other tests here already use it.
    note "no image given, and the repository cannot answer this on its own:" \
         "the entries come from the desktop's packages. Give --root <image tree>" \
         "or \$RAYE_ROOT (tools/raye-tests does it from the ISO)."
    echo "skipped: no image given, so the Start menu cannot be read" >&2
    exit 77
fi
[ -d "$ROOT" ] || { err "no such image tree: $ROOT"; exit 1; }
echo "image: $ROOT"
if [ "$MODE" = list ]; then
    scan "$ROOT" | sed -n 's/^visible=/  /p' | sort -t"$(printf '\t')" -k2
    exit 0
fi
check_tree "$ROOT"
exit "$fail"
