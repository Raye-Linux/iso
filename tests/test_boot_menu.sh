#!/bin/bash
#
# Checks the live boot menu and the release name people see:
#  - grub.cfg loads only modules built into the signed CD GRUB (anything
#    else is refused when Secure Boot is on), parses, and carries the
#    entries under names that are ours and not GNU GRUB's; the two "Try"
#    entries start the desktop (raye.try) and keep nothing (nopersistent);
#  - the menu stays PLAIN TEXT: it must NOT set a GRUB theme. The graphical
#    one restarted a Dell Latitude 5420 before the menu even showed, booted
#    from a USB optical drive emulator (iso b691d51, 2026-11-02). Turning it
#    back on is a decision to take on real hardware -- never something a
#    test demands;
#  - the theme left dormant in boot/grub/themes/raye stays usable, so that
#    turning it back on is one line: no font Secure Boot refuses, every
#    picture it names provided, GRUB's own text invisible, an icon for each
#    of the four entries, release.png stamped with VERSION;
#  - VERSION ("0.5 Beta") and its name in release-names ("Alpenglow")
#    are what os-release, lsb-release and issue say; the ISO name and
#    volume label carry VERSION alone, and VERSION_ID is its number.
#
#   tests/test_boot_menu.sh               everything the repository can answer
#   tests/test_boot_menu.sh --root DIR    also question the image tree DIR
#                                         ($RAYE_ROOT is read the same way)
#   tests/test_boot_menu.sh --iso FILE    also the ISO's name and volume label
#   tests/test_boot_menu.sh --efi FILE    signed CD GRUB to read the modules
#                                         from (default: the image's, else
#                                         this machine's)
#   tests/test_boot_menu.sh --self-test   show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# WHICH COPY OF THE SIGNED GRUB IS READ IS NOT A DETAIL, and getting it
# wrong turned this test green over a defect for four builds. build.sh:511
# copies $root/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed -- from the
# IMAGE -- to EFI/BOOT/grubx64.efi, and that is the binary the disc boots.
# This test read the copy installed on the MACHINE RUNNING IT, which is a
# different build of grub-efi-amd64-signed. Measured 2026-11-06 on the beta
# image:
#
#     this machine's gcdx64.efi.signed   97 modules, all_video among them
#     the image's (= the ISO's grubx64)  95 modules, NO all_video
#
# grub.cfg said `insmod all_video`, the machine's copy had it, so the check
# passed -- while on the disc that insmod cannot work at all: the ISO ships
# no .mod file either, so there is nothing to load it from. Same lesson as
# "ask the image which Wine it ships, not the test machine".
#
# So: with an image, the module list is a VERDICT. Without one, this machine's
# copy gives an INDICATION and the differences are printed as notes, never as
# failures -- a false green is what the wrong copy produced, and a false red
# from the same wrong copy would be no better.
#
# THREE assertions were removed on 2026-11-05. They must not come back,
# and here is the measurement for each, so nobody has to redo it:
#
#  1. "grub.cfg must not loadfont from the disc, Secure Boot refuses it" --
#     FALSE. Secure Boot's lockdown in the signed GRUB is on MODULES
#     (insmod), not on data files. GRUB's own /etc/grub.d/00_header, shipped
#     on every Debian and Ubuntu machine, emits `if loadfont <path>`, and
#     that is what runs on Secure Boot machines everywhere.
#  2. "grub.cfg must loadfont unicode, the one built into GRUB" -- FALSE, and
#     it CONTRADICTED 1. The signed gcdx64.efi carries no font: the only
#     string in it is `unicode.pf2`, the default FILENAME its font code looks
#     for under $prefix/fonts. So `loadfont unicode` reads the very same file
#     from the very same disc. No configuration could satisfy both rules.
#  3. "every menuentry must carry --class, so it has a picture" -- it only
#     meant anything for a GRAPHICAL menu. The plain-text menu has no
#     classes, so the check passed vacuously, which is worse than absent.
#     Its real content lives on in check_theme_dormant, which asserts the
#     four icons are still there.
#
# The lesson, which cost a session: a test that forbids the decision it was
# meant to protect is worse than no test. When the menu went back to plain
# text nobody updated this file, and it stayed red for doing its job.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
CFG=$here/boot/grub/grub.cfg
THEME=$here/boot/grub/themes/raye/theme.txt
BUILD=$here/build.sh
REL=$here/packages/raye-base/release

# where the signed CD GRUB is taken from, and who is allowed to fail on it
EFI=
EFI_FROM=
EFI_AUTHORITY=0
MACHINE_EFI=/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed
ROOT=${RAYE_ROOT:-}
ISO=

# the entries of the live menu, and the icon each one would need the day
# the theme is turned back on (the two "Try" entries have none drawn yet)
ENTRIES=$'This USB stick was not written correctly\nInstall Raye Linux\nInstaller Raye Linux\nTry Raye Linux without installing\nEssayer Raye Linux sans l\'installer\nSafe graphics\nCheck the USB stick for errors\nUEFI firmware settings'
ICONS="raye-install raye-french raye-safe raye-firmware"

fail=0
err() { echo "FAIL: $*"; fail=1; }
note() { echo "note: $*"; }

# "0.5 Beta" -> "0.5 Beta Alpenglow", the name taken from release-names
full_release() {
    local release=$1 n
    n=$(awk -v num="${release%% *}" '!/^#/ && $1 == num { print $2; exit }' "$here/release-names")
    printf '%s%s\n' "$release" "${n:+ $n}"
}
ok() { echo "ok: $*"; }

# names of the modules linked into a GRUB EFI image: each one is an ELF
# object with a .modname section
builtin_modules() {
    python3 - "$1" <<'EOF'
import struct, sys
data = open(sys.argv[1], 'rb').read()
names = set()
at = data.find(b'\x7fELF\x02\x01')
while at >= 0:
    try:
        shoff = struct.unpack_from('<Q', data, at + 0x28)[0]
        size, count, strndx = struct.unpack_from('<HHH', data, at + 0x3a)
        sec = lambda k: struct.unpack_from('<IIQQQQIIQQ', data, at + shoff + k * size)
        strtab = sec(strndx)[4]
        for k in range(count):
            s = sec(k)
            if data[at + strtab + s[0]:].split(b'\0', 1)[0] == b'.modname':
                names.add(data[at + s[4]:at + s[4] + s[5]].split(b'\0', 1)[0].decode())
    except (struct.error, UnicodeDecodeError):
        pass
    at = data.find(b'\x7fELF\x02\x01', at + 4)
print('\n'.join(sorted(names)))
EOF
}

# Pick the signed CD GRUB, and remember whether it can carry a verdict.
# Order: --efi, then the image, then this machine. See the at the top.
resolve_efi() {
    local p
    if [ -n "$EFI" ]; then
        EFI_FROM="given with --efi"
        EFI_AUTHORITY=1
        return
    fi
    if [ -n "$ROOT" ]; then
        p=$ROOT/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed
        if [ -f "$p" ]; then
            EFI=$p
            EFI_FROM="the image, which is the copy build.sh:511 puts on the ISO"
            EFI_AUTHORITY=1
            return
        fi
        err "the image has no usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed," \
            "the file build.sh:511 copies to EFI/BOOT/grubx64.efi"
    fi
    if [ -f "$MACHINE_EFI" ]; then
        EFI=$MACHINE_EFI
        EFI_FROM="THIS MACHINE -- another build of grub-efi-amd64-signed, so an indication only"
        EFI_AUTHORITY=0
    fi
}

check_modules() {
    local cfg=$1 mods m miss=0
    if [ ! -f "$EFI" ]; then
        note "no signed CD GRUB here ($MACHINE_EFI), module check skipped" \
             "(grub-efi-amd64-signed, or give --root an image)"
        return
    fi
    note "modules read from: $EFI_FROM"
    mods=$(builtin_modules "$EFI")
    # what grub.cfg actually asks for: anything not built in is refused once
    # Secure Boot is on, and the ISO carries no .mod file to load it from
    for m in $(sed -n 's/^[[:space:]]*insmod[[:space:]]\+\([^[:space:]]*\).*/\1/p' "$cfg"); do
        grep -qx "$m" <<<"$mods" && continue
        if [ "$EFI_AUTHORITY" = 1 ]; then
            err "grub.cfg loads $m, not built into the signed GRUB the ISO boots"
        else
            note "grub.cfg loads $m, which is not in this machine's signed GRUB." \
                 "Only the image can say: give --root or \$RAYE_ROOT"
            miss=1
        fi
    done
    # and what the dormant theme would need the day it is turned back on
    for m in gfxterm gfxmenu png font efi_gop; do
        grep -qx "$m" <<<"$mods" && continue
        if [ "$EFI_AUTHORITY" = 1 ]; then
            err "the signed GRUB has no $m: the dormant theme could not be turned back on"
        else
            note "this machine's signed GRUB has no $m; only the image can say"
            miss=1
        fi
    done
    [ "$miss" = 1 ] && note "the module verdict is MISSING: run with --root <image tree>"
    return 0
}

check_menu() {
    local cfg=$1 entries
    if command -v grub-script-check >/dev/null; then
        grub-script-check "$cfg" || err "grub.cfg does not parse"
    else
        note "grub-script-check missing, syntax not checked"
    fi
    entries=$(sed -n 's/^[[:space:]]*menuentry[[:space:]]\+"\([^"]*\)".*/\1/p' "$cfg")
    [ "$entries" = "$ENTRIES" ] || err "menu entries are: $(tr '\n' '|' <<<"$entries")"
    grep -q 'GNU GRUB' "$cfg" && err "grub.cfg names GNU GRUB"
    check_try_entries "$cfg"
    # the menu stays plain text: the graphical theme restarted a Dell
    # Latitude 5420 before the menu showed. If this fires, someone turned the
    # theme back on -- which is allowed, but only after a real-hardware test,
    # and the checks removed with assertion 3 above come back with it.
    grep -q '^set theme=' <(sed 's/^[[:space:]]*//' "$cfg") &&
        err "grub.cfg sets a GRUB theme: the graphical menu restarted a Dell Latitude 5420 before the menu showed (b691d51). Prove it on real hardware first"
    return 0
}

# The kernel line of each entry, one "<title>|<linux line>" per entry
entry_lines() {
    awk '/^[[:space:]]*menuentry[[:space:]]+"/ { split($0, q, "\""); title = q[2] }
         /^[[:space:]]*linux[[:space:]]/ && title != "" { sub(/^[[:space:]]+/, ""); print title "|" $0; title = "" }' "$1"
}

# "Try" starts the desktop (raye.try, read by casper-bottom/16raye_setup in
# the installer) and keeps nothing (nopersistent: casper makes no writable
# partition on the stick). The install entries must not carry raye.try, or
# the stick would stop opening Setup.
check_try_entries() {
    local cfg=$1 title line tries=0
    while IFS='|' read -r title line; do
        case $title in
            Try*|Essayer*)
                tries=$((tries + 1))
                [[ " $line " == *" raye.try "* ]] || err "\"$title\" does not pass raye.try"
                [[ " $line " == *" nopersistent "* ]] || err "\"$title\" does not pass nopersistent"
                [[ " $line " == *" boot=casper "* ]] || err "\"$title\" does not boot casper"
                ;;
            *)
                [[ " $line " == *" raye.try "* ]] && err "\"$title\" passes raye.try: it would not open Setup"
                ;;
        esac
        case $title in
            Essayer*|Installer*)
                [[ " $line " == *" locale=fr_CA.UTF-8 "* ]] || err "\"$title\" is not in French"
                ;;
        esac
    done < <(entry_lines "$cfg")
    [ "$tries" = 2 ] || err "$tries \"Try\" entries, expected 2 (English and French)"
    return 0
}

check_theme_dormant() {
    local theme=$1 dir font file from_image icon
    dir=$(dirname "$theme")
    grep -q '^title-text: ""' "$theme" || err "the theme shows a title (GNU GRUB)"
    while read -r font; do
        [ "$font" = "GNU Unifont Regular 16" ] || err "theme uses \"$font\", which Secure Boot keeps out"
    done < <(grep -o '\(font\|item_font\|selected_item_font\|terminal-font\)[ :=]*"[^"]*"' "$theme" | sed 's/.*"\(.*\)"/\1/' | sort -u)
    # the entries are pictures: GRUB's own text must stay invisible
    for file in item_color selected_item_color; do
        grep -q "^[[:space:]]*$file = \"#[0-9a-fA-F]\{6\}00\"" "$theme" || err "$file is not transparent"
    done
    # one icon per menu entry -- what assertion 3 really protected
    for icon in $ICONS; do
        [ -f "$dir/icons/$icon.png" ] || err "the dormant theme has lost icons/$icon.png"
    done
    # every picture is in the theme folder or copied by build.sh from grub-theme-raye
    from_image=$(sed -n '/boot\/grub\/themes\/raye" "\$iso/,/done/p' "$BUILD")
    grep -q 'cp -r "$here/boot/grub/themes/raye"' "$BUILD" || err "build.sh does not copy the theme folder"
    for file in $(grep -o '"[^"]*\.png"' "$theme" | tr -d '"'); do
        case $file in
            *\*.png) [ -n "$(find "$dir" -maxdepth 1 -name "${file/\*/c}")" ] ||
                         grep -q "${file/\*/c}" <<<"$from_image" || err "nothing provides ${file/\*/c}" ;;
            *) [ -f "$dir/$file" ] || grep -q "$file" <<<"$from_image" || err "nothing provides $file" ;;
        esac
    done
    [ "$(png_text "$dir/release.png" Raye-Release)" = "$(cat "$here/VERSION")" ] ||
        err "release.png says \"$(png_text "$dir/release.png" Raye-Release)\": run boot/grub/art.py"
}

# a tEXt entry of a PNG, which art.py stamps release.png with
png_text() {
    python3 - "$1" "$2" <<'EOF'
import struct, sys
data = open(sys.argv[1], 'rb').read()
at = 8
while at < len(data):
    size, kind = struct.unpack_from('>I4s', data, at)
    body = data[at + 8:at + 8 + size]
    if kind == b'tEXt':
        key, _, value = body.partition(b'\0')
        if key.decode() == sys.argv[2]:
            print(value.decode('latin-1'))
    at += 12 + size
EOF
}

field() { sed -n "s/^$1=\"\{0,1\}\([^\"]*\)\"\{0,1\}$/\1/p" "$2"; }

# A file of the image, following an absolute symlink INSIDE the image.
# Without this, reading the image is a trap that reports the wrong
# thing: /etc/issue, /etc/issue.net and /etc/lsb-release of a Raye image
# are symlinks to /usr/lib/raye/..., and an absolute target resolves
# against the TEST MACHINE's root, where that file does not exist. `cat`
# then says "No such file", and a check looking for the version would
# call a perfectly good image a wrong version. Measured 2026-11-06.
image_file() {
    local root=$1 p=$root/$2 t n=0
    while [ -L "$p" ] && [ "$n" -lt 16 ]; do
        t=$(readlink "$p")
        case $t in
            /*) p=$root$t ;;
            *) p=$(dirname "$p")/$t ;;
        esac
        n=$((n + 1))
    done
    printf '%s\n' "$p"
}

# The version in the IMAGE, not in the files the repository would package.
# check_release proves the sources are right; this proves the build picked
# them up. The two are not the same question: on 2026-11-05 the repository
# said "0.1 Beta" everywhere and the image's raye.info still said
# "Raye Linux 0.1", because the template was not rebuilt.
check_image_release() {
    local release root=$2 number f shown
    release=$(full_release "$1")
    number=${release%% *}

    f=$(image_file "$root" etc/os-release)
    if [ ! -f "$f" ]; then
        err "the image has no etc/os-release"
        return
    fi
    [ "$(field VERSION_ID "$f")" = "$number" ] ||
        err "the image's os-release VERSION_ID is \"$(field VERSION_ID "$f")\", not $number"
    [ "$(field VERSION "$f")" = "$release" ] ||
        err "the image's os-release VERSION is \"$(field VERSION "$f")\", not \"$release\""
    [ "$(field PRETTY_NAME "$f")" = "Raye Linux $release" ] ||
        err "the image's os-release PRETTY_NAME is \"$(field PRETTY_NAME "$f")\""

    f=$(image_file "$root" etc/lsb-release)
    if [ -f "$f" ]; then
        [ "$(field DISTRIB_RELEASE "$f")" = "$number" ] ||
            err "the image's lsb-release DISTRIB_RELEASE is not $number"
        [ "$(field DISTRIB_DESCRIPTION "$f")" = "Raye Linux $release" ] ||
            err "the image's lsb-release DISTRIB_DESCRIPTION is" \
                "\"$(field DISTRIB_DESCRIPTION "$f")\""
    else
        err "the image has no etc/lsb-release (lsb_release and many scripts read it)"
    fi

    f=$(image_file "$root" etc/issue)
    if [ -f "$f" ]; then
        head -1 "$f" | grep -q "^Raye Linux $release \\\\n \\\\l$" ||
            err "the image's issue says \"$(head -1 "$f")\""
    else
        err "the image has no etc/issue"
    fi
    f=$(image_file "$root" etc/issue.net)
    if [ -f "$f" ]; then
        head -1 "$f" | grep -qx "Raye Linux $release" ||
            err "the image's issue.net says \"$(head -1 "$f")\""
    else
        err "the image has no etc/issue.net"
    fi

    # the sixth place the version shows: the software sources dialog.
    # python-apt reads this template, named after the ID of os-release.
    # test_apt_template.sh checks it against the image's own PRETTY_NAME
    # (self-consistency); here it is checked against VERSION, so that the
    # word cannot be lost from BOTH files at once and still pass.
    f=$(image_file "$root" usr/share/python-apt/templates/raye.info)
    if [ -f "$f" ]; then
        shown=$(awk '/^Suite:/ { n++ } n == 1 && /^Description:/ {
                     sub(/^Description:[[:space:]]*/, ""); print; exit }' "$f")
        [ "$shown" = "Raye Linux $release" ] ||
            err "the image's raye.info calls this system \"$shown\": the software" \
                "sources dialog would say that, and VERSION says \"Raye Linux $release\""
    else
        err "the image has no usr/share/python-apt/templates/raye.info"
    fi
}

# The two things only the finished ISO carries: its file name and the
# volume label the firmware shows. Both are derived from VERSION by
# build.sh, and both are read here from the artefact, not computed twice.
check_iso_name() {
    local release=$1 iso=$2 base label want_name want_volume stamp real
    # Resolve the path first. tools/release.conf names
    # /var/tmp/raye/isos/latest.iso, a SYMLINK to the newest build, and the
    # launcher passes exactly that: basename on the link gives "latest" and
    # the check failed on a perfectly well-named image. The name to judge is
    # the one the file really has. Measured 2026-11-06.
    real=$(readlink -f "$iso" 2>/dev/null) || real=$iso
    [ -n "$real" ] || real=$iso
    [ "$real" = "$iso" ] || note "$iso points at $(basename "$real")"
    iso=$real
    base=$(basename "$iso"); base=${base%.iso}
    stamp=$(sed -n 's/^raye-.*-\([0-9]\{8\}[a-z]*\)-amd64$/\1/p' <<<"$base")
    if [ -z "$stamp" ]; then
        err "the ISO is named \"$base\", which is not raye-<version>-<date>-amd64"
        return
    fi
    eval "$(grep -E '^(name|volume)=' "$BUILD" |
            sed "s/\$stamp/$stamp/; s/\$version/\$release/g")"
    want_name=$name
    want_volume=$volume
    [ "$base" = "$want_name" ] ||
        err "the ISO is named \"$base\"; VERSION and build.sh say \"$want_name\""
    if command -v blkid >/dev/null; then
        label=$(blkid -o value -s LABEL "$iso" 2>/dev/null)
        if [ -z "$label" ]; then
            note "blkid read no volume label from $iso"
        elif [ "$label" = "$want_volume" ]; then
            ok "the ISO volume label is $label, as VERSION says"
        else
            err "the ISO volume label is \"$label\", not \"$want_volume\""
        fi
    else
        note "blkid is not installed, the volume label was not read"
    fi
}

check_release() {
    local version=$1 release rel=$2 number name volume
    release=$(full_release "$version")
    number=${release%% *}
    awk -v num="$number" '!/^#/ && $1 == num { f = 1 } END { exit !f }' "$here/release-names" ||
        err "release-names has no line for $number"
    [[ ${release#"$version"} =~ ^(\ [A-Za-z]+)?$ ]] ||
        err "the release name of $number is not letters only: \"${release#"$version "}\""
    [ "$(field VERSION_ID "$rel/os-release")" = "$number" ] || err "os-release VERSION_ID is not $number"
    [ "$(field VERSION "$rel/os-release")" = "$release" ] || err "os-release VERSION is not \"$release\""
    [ "$(field PRETTY_NAME "$rel/os-release")" = "Raye Linux $release" ] ||
        err "os-release PRETTY_NAME is not \"Raye Linux $release\""
    [ "$(field DISTRIB_RELEASE "$rel/lsb-release")" = "$number" ] || err "lsb-release DISTRIB_RELEASE is not $number"
    [ "$(field DISTRIB_DESCRIPTION "$rel/lsb-release")" = "Raye Linux $release" ] ||
        err "lsb-release DISTRIB_DESCRIPTION is not \"Raye Linux $release\""
    head -1 "$rel/issue" | grep -q "^Raye Linux $release \\\\n \\\\l$" || err "issue does not say Raye Linux $release"
    head -1 "$rel/issue.net" | grep -qx "Raye Linux $release" || err "issue.net does not say Raye Linux $release"

    # the two lines of build.sh that turn VERSION into a file name and a label
    eval "$(grep -E '^(name|volume)=' "$BUILD" | sed 's/\$stamp/20261101/; s/\$version/$version/g')"
    [ "$name" = "raye-$(tr 'A-Z ' 'a-z-' <<<"$version")-20261101-amd64" ] || err "ISO name is $name"
    [[ $name =~ ^[a-z0-9.-]+$ ]] || err "ISO name $name has odd characters"
    [[ $volume =~ ^[A-Z0-9_]{1,32}$ ]] || err "volume label $volume is not a valid ISO 9660 label"
    grep -q 'Preview' "$BUILD" && err "build.sh still says Preview"
    return 0
}

self_test() {
    local t ok=1
    t=$(mktemp -d)
    # a module no signed GRUB carries. The earlier version of this case
    # swapped `insmod png` for `insmod all_video`, and the plain-text cfg has
    # neither: the sed was a no-op, so the case could not go red. Measured
    # 2026-11-05 -- it printed "all_video not caught" against a correct
    # script. A name that cannot exist is the only stable injection.
    sed 's/^[[:space:]]*insmod efi_gop/    insmod raye_pas_un_module/' "$CFG" > "$t/cfg"
    if [ -f "$EFI" ]; then
        # the case asserts a FAILURE, so it needs the copy to carry a verdict:
        # with EFI_AUTHORITY=0 check_modules only takes notes and the case
        # could never go red (and would say the check is broken when it is not)
        local saved_authority=$EFI_AUTHORITY
        EFI_AUTHORITY=1
        grep -q raye_pas_un_module "$t/cfg" ||
            { echo "self-test: injection ratee, aucun insmod efi_gop dans $CFG"; ok=0; }
        (fail=0; check_modules "$t/cfg"; exit $fail) >/dev/null &&
            { echo "self-test: module absent du GRUB signe non attrape"; ok=0; }
        EFI_AUTHORITY=$saved_authority
    else
        echo "self-test: pas de GRUB CD signe ici, le cas des modules n a pas tourne"
    fi
    # the graphical theme turned back on without a hardware test
    sed 's|^set timeout=5|set theme=/boot/grub/themes/raye/theme.txt\nset timeout=5|' "$CFG" > "$t/cfg-theme"
    grep -q '^set theme=' "$t/cfg-theme" || { echo "self-test: injection du theme ratee"; ok=0; }
    (fail=0; check_menu "$t/cfg-theme"; exit $fail) >/dev/null &&
        { echo "self-test: retour du theme graphique non attrape"; ok=0; }
    # a font Secure Boot refuses
    cp -r "$(dirname "$THEME")" "$t/theme"
    sed -i 's/item_font = "GNU Unifont Regular 16"/item_font = "Inter Regular 20"/' "$t/theme/theme.txt"
    (fail=0; check_theme_dormant "$t/theme/theme.txt"; exit $fail) >/dev/null &&
        { echo "self-test: refused font not caught"; ok=0; }
    # an entry without its picture
    cp "$THEME" "$t/theme/theme.txt"
    rm "$t/theme/icons/raye-safe.png"
    (fail=0; check_theme_dormant "$t/theme/theme.txt"; exit $fail) >/dev/null &&
        { echo "self-test: missing picture not caught"; ok=0; }
    # an entry renamed
    sed 's/Safe graphics/safe graphics/' "$CFG" > "$t/cfg2"
    (fail=0; check_menu "$t/cfg2"; exit $fail) >/dev/null && { echo "self-test: wrong entry not caught"; ok=0; }
    # a Try entry that would keep the setup session, or keep changes
    sed '/Try Raye Linux without installing/,/initrd/ s/ raye\.try//' "$CFG" > "$t/cfg-try"
    (fail=0; check_menu "$t/cfg-try"; exit $fail) >/dev/null &&
        { echo "self-test: Try entry without raye.try not caught"; ok=0; }
    sed '/Essayer Raye Linux/,/initrd/ s/ nopersistent//' "$CFG" > "$t/cfg-try2"
    (fail=0; check_menu "$t/cfg-try2"; exit $fail) >/dev/null &&
        { echo "self-test: Try entry without nopersistent not caught"; ok=0; }
    sed '0,/noprompt quiet splash/ s/noprompt quiet splash/noprompt raye.try quiet splash/' "$CFG" > "$t/cfg-try3"
    (fail=0; check_menu "$t/cfg-try3"; exit $fail) >/dev/null &&
        { echo "self-test: Install entry with raye.try not caught"; ok=0; }
    # os-release left behind
    cp -r "$REL" "$t/rel"
    sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="Raye Linux 0.1"/' "$t/rel/os-release"
    (fail=0; check_release "$(cat "$here/VERSION")" "$t/rel"; exit $fail) >/dev/null &&
        { echo "self-test: old PRETTY_NAME not caught"; ok=0; }

    # ---------------------------------------------------- the image side
    # A fake image, laid out like a real one: /etc/lsb-release, /etc/issue
    # and /etc/issue.net are ABSOLUTE symlinks into /usr/lib/raye, exactly
    # as raye-release ships them. That is what makes these cases worth
    # having: read from outside the tree, an absolute target resolves
    # against the TEST MACHINE's root and the file reads as missing.
    fake_image() {
        local d=$1 release=$2
        mkdir -p "$d/etc" "$d/usr/lib/raye" "$d/usr/share/python-apt/templates"
        local number=${release%% *}
        printf 'PRETTY_NAME="Raye Linux %s"\nVERSION_ID="%s"\nVERSION="%s"\nID=raye\n' \
            "$release" "$number" "$release" > "$d/etc/os-release"
        printf 'DISTRIB_ID=Raye\nDISTRIB_RELEASE=%s\nDISTRIB_DESCRIPTION="Raye Linux %s"\n' \
            "$number" "$release" > "$d/usr/lib/raye/lsb-release"
        printf 'Raye Linux %s \\n \\l\n' "$release" > "$d/usr/lib/raye/issue"
        printf 'Raye Linux %s\n' "$release" > "$d/usr/lib/raye/issue.net"
        ln -sf /usr/lib/raye/lsb-release "$d/etc/lsb-release"
        ln -sf /usr/lib/raye/issue "$d/etc/issue"
        ln -sf /usr/lib/raye/issue.net "$d/etc/issue.net"
        printf 'Suite: resolute\nRepositoryType: deb\nDescription: Raye Linux %s\n' \
            "$release" > "$d/usr/share/python-apt/templates/raye.info"
    }
    local rel
    rel=$(full_release "$VERSION_STR")
    fake_image "$t/img" "$rel"
    # it must be green first, or none of the cases below prove anything --
    # and it is the symlinks that decide: image_file has to follow them
    # inside the tree
    (fail=0; check_image_release "$VERSION_STR" "$t/img"; exit $fail) >/dev/null ||
        { echo "self-test: une image correcte est refusee (image_file ne suit pas les liens ?)"; ok=0; }
    # every place the version shows, one at a time
    local f
    for f in etc/os-release usr/lib/raye/lsb-release usr/lib/raye/issue \
             usr/lib/raye/issue.net usr/share/python-apt/templates/raye.info; do
        rm -rf "$t/bad"; fake_image "$t/bad" "$rel"
        # drop the word the other five carry -- the defect of 2026-11-05
        sed -i "s/Raye Linux $rel/Raye Linux ${rel%% *}/" "$t/bad/$f"
        (fail=0; check_image_release "$VERSION_STR" "$t/bad"; exit $fail) >/dev/null &&
            { echo "self-test: \"$f\" sans le mot de VERSION non attrape"; ok=0; }
    done
    # the right number without its name
    rm -rf "$t/bad"; fake_image "$t/bad" "$VERSION_STR"
    (fail=0; check_image_release "$VERSION_STR" "$t/bad"; exit $fail) >/dev/null &&
        { echo "self-test: une image sans le nom de la version non attrapee"; ok=0; }
    # a file gone from the image, not merely wrong
    rm -rf "$t/bad"; fake_image "$t/bad" "$rel"; rm "$t/bad/usr/lib/raye/issue.net"
    (fail=0; check_image_release "$VERSION_STR" "$t/bad"; exit $fail) >/dev/null &&
        { echo "self-test: issue.net absente de l image non attrapee"; ok=0; }
    # an image that is not one at all
    (fail=0; check_image_release "$VERSION_STR" "$t/vide"; exit $fail) >/dev/null &&
        { echo "self-test: un arbre sans os-release non attrape"; ok=0; }
    # the ISO's own name, which build.sh derives from VERSION
    : > "$t/raye-0.2-beta-20261106-amd64.iso"
    (fail=0; check_iso_name "$VERSION_STR" "$t/raye-0.2-beta-20261106-amd64.iso"; exit $fail) >/dev/null &&
        { echo "self-test: un ISO nomme pour une autre version non attrape"; ok=0; }
    : > "$t/raye-sans-date-amd64.iso"
    (fail=0; check_iso_name "$VERSION_STR" "$t/raye-sans-date-amd64.iso"; exit $fail) >/dev/null &&
        { echo "self-test: un ISO sans date dans son nom non attrape"; ok=0; }
    # a well-named ISO reached through latest.iso, which is how the launcher
    # passes it: judging the link's own name failed on a correct image
    : > "$t/raye-$(tr 'A-Z ' 'a-z-' <<<"$VERSION_STR")-20261106-amd64.iso"
    ln -sf "$t/raye-$(tr 'A-Z ' 'a-z-' <<<"$VERSION_STR")-20261106-amd64.iso" "$t/latest.iso"
    (fail=0; check_iso_name "$VERSION_STR" "$t/latest.iso"; exit $fail) >/dev/null ||
        { echo "self-test: un ISO correct atteint par latest.iso est refuse"; ok=0; }
    # and the link must not become a way to smuggle a wrong name past it
    ln -sf "$t/raye-0.2-beta-20261106-amd64.iso" "$t/latest.iso"
    (fail=0; check_iso_name "$VERSION_STR" "$t/latest.iso"; exit $fail) >/dev/null &&
        { echo "self-test: une mauvaise version derriere latest.iso non attrapee"; ok=0; }

    rm -rf "$t"
    [ "$ok" = 1 ] && echo "self-test ok"
    [ "$ok" = 1 ]
}

while [ $# -gt 0 ]; do
    case $1 in
        --efi) EFI=${2:?--efi needs a file}; shift ;;
        --root) ROOT=${2:?--root needs a directory}; shift ;;
        --iso) ISO=${2:?--iso needs a file}; shift ;;
        # resolve_efi FIRST. --self-test exits inside this loop, so
        # without it $EFI is still empty and the whole module case of the
        # self-test is skipped -- while the self-test still prints "ok".
        # Measured 2026-11-06, within the hour of writing resolve_efi.
        --self-test) VERSION_STR=$(cat "$here/VERSION"); resolve_efi; self_test; exit $? ;;
        *) sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    esac
    shift
done

VERSION_STR=$(cat "$here/VERSION")

if [ -n "$ROOT" ] && [ ! -d "$ROOT" ]; then
    err "no such image tree: $ROOT"
    ROOT=
fi
resolve_efi

check_modules "$CFG"
check_menu "$CFG"
check_theme_dormant "$THEME"
check_release "$VERSION_STR" "$REL"

# The image, when there is one. It is never guessed: an image found by
# guessing is an image whose age nobody knows, and a stale one would fail
# this test for a repository that is already right.
if [ -n "$ROOT" ]; then
    echo "image: $ROOT"
    check_image_release "$VERSION_STR" "$ROOT"
else
    note "no image questioned: the version was checked in the files the repository" \
         "packages, not in a built one. Give --root <tree> or \$RAYE_ROOT"
fi
if [ -n "$ISO" ]; then
    if [ -f "$ISO" ]; then
        check_iso_name "$VERSION_STR" "$ISO"
    else
        err "no such ISO: $ISO"
    fi
fi

[ "$fail" = 0 ] && echo "ok: boot menu (plain text), dormant theme and release name"
exit "$fail"
