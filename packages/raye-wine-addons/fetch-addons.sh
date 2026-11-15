#!/bin/sh
# Gets the free runtime files Windows programs expect, so Raye can ship
# them and nothing is ever downloaded when a program starts:
#
#   Wine Mono     .NET programs           /usr/share/wine/mono
#   Wine Gecko    HTML in programs        /usr/share/wine/gecko
#   DXVK          DirectX 8 to 11         /usr/share/raye/windows/dxvk
#   vkd3d-proton  DirectX 12              /usr/share/raye/windows/vkd3d-proton
#
# addons.sha256 is the list: one file per line with the SHA-256 it must
# have. Nothing is used unless it matches, whether it comes from the
# network, a cache or the upstream/ folder.
#
#   fetch-addons.sh [--cache DIR] [--no-orig]
#       put every file in upstream/ (downloading what is missing), then
#       write ../raye-wine-addons_<version>.orig.tar.xz
#   fetch-addons.sh --check          check upstream/, offline
#   fetch-addons.sh --unpack DEST    check, then unpack into DEST (debian/rules)
#   fetch-addons.sh --version        the upstream version made of the four
#   fetch-addons.sh --list           every file and where it comes from
#
# RAYE_ADDONS_MIRROR=https://host/path takes every file from that one
# place instead (same names); the hashes still decide.

set -eu

here=$(cd "$(dirname "$0")" && pwd)
sums=$here/addons.sha256
table=$here/versions.txt
changelog=$here/debian/changelog
up=$here/upstream
pkg=raye-wine-addons

die() { echo "fetch-addons: $*" >&2; exit 1; }

usage() {
    echo "Usage: fetch-addons.sh [--cache DIR] [--no-orig] | --check | --unpack DEST | --version | --list" >&2
    exit 2
}

# the comment at the top of this file
help() {
    sed -n '2,/^$/s/^# \{0,1\}//p' "$0"
    exit 0
}

# a half-written file never stays behind
part=
cleanup() { [ -z "$part" ] || rm -f "$part"; }
trap cleanup EXIT
trap 'exit 130' INT TERM

# ------------------------------------------------------------ the list

# kind and version of a file, from its name
kind_of() {
    case $1 in
        wine-mono-*-x86.tar.xz)        k=mono    v=${1#wine-mono-} v=${v%-x86.tar.xz} ;;
        wine-gecko-*-x86_64.tar.xz)    k=gecko64 v=${1#wine-gecko-} v=${v%-x86_64.tar.xz} ;;
        wine-gecko-*-x86.tar.xz)       k=gecko32 v=${1#wine-gecko-} v=${v%-x86.tar.xz} ;;
        dxvk-*.tar.gz)                 k=dxvk    v=${1#dxvk-} v=${v%.tar.gz} ;;
        vkd3d-proton-*.tar.zst)        k=vkd3d   v=${1#vkd3d-proton-} v=${v%.tar.zst} ;;
        *) die "addons.sha256: do not know what $1 is" ;;
    esac
    case $v in
        [0-9]*) ;;
        *) die "addons.sha256: no version in $1" ;;
    esac
    case $v in
        *[!0-9A-Za-z.]*) die "addons.sha256: odd version in $1" ;;
    esac
}

# folder at the top of each archive
top_of() {
    kind_of "$1"
    case $k in
        mono) echo "wine-mono-$v" ;;
        gecko32|gecko64) echo "${1%.tar.xz}" ;;
        dxvk) echo "dxvk-$v" ;;
        vkd3d) echo "vkd3d-proton-$v" ;;
    esac
}

url_of() {
    if [ -n "${RAYE_ADDONS_MIRROR:-}" ]; then
        echo "${RAYE_ADDONS_MIRROR%/}/$1"
        return
    fi
    kind_of "$1"
    case $k in
        mono) echo "https://dl.winehq.org/wine/wine-mono/$v/$1" ;;
        gecko32|gecko64) echo "https://dl.winehq.org/wine/wine-gecko/$v/$1" ;;
        dxvk) echo "https://github.com/doitsujin/dxvk/releases/download/v$v/$1" ;;
        vkd3d) echo "https://github.com/HansKristian-Work/vkd3d-proton/releases/download/v$v/$1" ;;
    esac
}

# reads addons.sha256: sets names (space separated) and one version per kind
read_sums() {
    [ -f "$sums" ] || die "addons.sha256 is missing"
    names= mono= gecko32= gecko64= dxvk= vkd3d= n=0
    while read -r hash name rest || [ -n "${hash:-}" ]; do
        n=$((n + 1))
        case $hash in ''|'#'*) continue ;; esac
        [ -z "$rest" ] && [ ${#hash} -eq 64 ] && [ -n "$name" ] ||
            die "addons.sha256: line $n is not '<sha256>  <file>'"
        case $hash in *[!0-9a-f]*) die "addons.sha256: line $n: bad SHA-256" ;; esac
        case $name in
            [A-Za-z0-9]*) ;;
            *) die "addons.sha256: line $n: bad file name $name" ;;
        esac
        case $name in
            *[!A-Za-z0-9._+-]*) die "addons.sha256: line $n: bad file name $name" ;;
        esac
        kind_of "$name"
        eval "seen=\${$k}"
        [ -z "$seen" ] || die "addons.sha256: two files for $k"
        eval "$k=\$v"
        names="$names $name"
    done <"$sums"
    for k in mono gecko32 gecko64 dxvk vkd3d; do
        eval "seen=\${$k}"
        [ -n "$seen" ] || die "addons.sha256: no $k file (Mono, gecko x86 and x86_64, DXVK, vkd3d-proton are all needed)"
    done
    [ "$gecko32" = "$gecko64" ] ||
        die "addons.sha256: gecko x86 is $gecko32 but x86_64 is $gecko64"
    version="$mono+gecko$gecko32+dxvk$dxvk+vkd3d$vkd3d"
}

hash_of() {
    while read -r h_hash h_name h_rest; do
        [ "$h_name" = "$1" ] && { echo "$h_hash"; return; }
    done <"$sums"
}

# true when the file exists and has the SHA-256 of the list
good() {
    [ -f "$1" ] || return 1
    [ "$(sha256sum <"$1" | cut -d' ' -f1)" = "$(hash_of "$2")" ]
}

# the changelog names the same upstream version as the list
check_changelog() {
    [ -f "$changelog" ] || die "debian/changelog is missing"
    full=$(sed -n '1s/^[^ ]* (\([^)]*\)).*/\1/p' "$changelog")
    full=${full#*:}
    [ "${full%-*}" = "$version" ] ||
        die "debian/changelog says ${full%-*}, addons.sha256 makes $version"
}

# the rows of versions.txt marked shipped match what the list ships
check_table() {
    [ -f "$table" ] || die "versions.txt is missing"
    shipped=0 n=0
    while read -r wine wmono wgecko ship rest || [ -n "${wine:-}" ]; do
        n=$((n + 1))
        case $wine in ''|'#'*) continue ;; esac
        [ -n "$ship" ] && [ -z "$rest" ] ||
            die "versions.txt: line $n is not '<wine> <mono> <gecko> <yes|no>'"
        case $ship in
            no) continue ;;
            yes) ;;
            *) die "versions.txt: line $n: last column is yes or no" ;;
        esac
        [ "$wmono" = "$mono" ] && [ "$wgecko" = "$gecko32" ] ||
            die "versions.txt: Wine $wine wants Mono $wmono and Gecko $wgecko, addons.sha256 has Mono $mono and Gecko $gecko32"
        shipped=$((shipped + 1))
    done <"$table"
    [ "$shipped" -gt 0 ] || die "versions.txt: no row is shipped"
}

# ------------------------------------------------------------ fetching

download() {
    command -v curl >/dev/null || die "curl is needed to download $1"
    url=$(url_of "$1")
    echo "downloading $url"
    part=$up/.$1.part
    rm -f "$part"
    if ! curl --proto =https --proto-redir =https -f -sS -L --retry 3 \
            --connect-timeout 30 -o "$part" "$url"; then
        rm -f "$part"; part=
        die "could not download $1 from $url"
    fi
    if ! good "$part" "$1"; then
        got=$(sha256sum <"$part" | cut -d' ' -f1)
        rm -f "$part"; part=
        die "$1: SHA-256 does not match (got $got, want $(hash_of "$1")); not used"
    fi
    mv "$part" "$up/$1"
    part=
}

# copy src to dst through a temporary name in dst's folder
put() {
    part=$(dirname "$2")/.$(basename "$2").part
    cp "$1" "$part"
    mv "$part" "$2"
    part=
}

fetch() {
    mkdir -p "$up"
    [ -z "$cache" ] || mkdir -p "$cache"
    for name in $names; do
        if good "$up/$name" "$name"; then
            :
        elif [ -n "$cache" ] && good "$cache/$name" "$name"; then
            echo "from the cache: $name"
            put "$cache/$name" "$up/$name"
        else
            rm -f "$up/$name"
            download "$name"
        fi
        if [ -n "$cache" ] && ! good "$cache/$name" "$name"; then
            put "$up/$name" "$cache/$name"
        fi
    done
}

check() {
    for name in $names; do
        [ -f "$up/$name" ] || die "upstream/$name is missing (run fetch-addons.sh)"
        good "$up/$name" "$name" || die "upstream/$name: SHA-256 does not match"
    done
}

# the source tarball: this folder without debian/, the archives in upstream/
write_orig() {
    parent=$(dirname "$here")
    top=$pkg-$version
    orig=$parent/${pkg}_$version.orig.tar.xz
    when=${SOURCE_DATE_EPOCH:-$(date -d "$(sed -n 's/^ -- .*>  //p' "$changelog" | head -n1)" +%s)}
    stage=$(mktemp -d "$parent/.$pkg-orig.XXXXXX")
    mkdir "$stage/$top" "$stage/$top/upstream"
    for entry in "$here"/* "$here"/.[!.]*; do
        [ -e "$entry" ] || continue
        case ${entry##*/} in
            debian|upstream|.git|.pytest_cache|__pycache__) continue ;;
        esac
        cp -a "$entry" "$stage/$top/"
    done
    find "$stage/$top" \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
    for name in $names; do
        ln "$up/$name" "$stage/$top/upstream/$name" 2>/dev/null ||
            cp "$up/$name" "$stage/$top/upstream/$name"
    done
    part=$orig.part
    tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$when" \
        -cf - -C "$stage" "$top" | xz -T0 -3 >"$part"
    mv "$part" "$orig"
    part=
    rm -rf "$stage"
    echo "wrote $orig"
}

# ------------------------------------------------------------ unpacking

# every member of the archive is inside its top folder
check_members() {
    t=$(top_of "$1")
    tar -tf "$up/$1" | while IFS= read -r m; do
        case $m in
            "$t"|"$t/"|"$t/"*) ;;
            *) echo "$m"; break ;;
        esac
        case /$m/ in
            */../*) echo "$m"; break ;;
        esac
    done
}

unpack() {
    for name in $names; do
        bad=$(check_members "$name")
        [ -z "$bad" ] || die "$name: $bad is outside $(top_of "$name")/; not unpacked"
    done
    wine=$dest/usr/share/wine
    win=$dest/usr/share/raye/windows
    for name in $names; do
        t=$(top_of "$name")
        kind_of "$name"
        case $k in
            mono)
                mkdir -p "$wine/mono"
                tar -xf "$up/$name" --no-same-owner -C "$wine/mono" ;;
            gecko32|gecko64)
                mkdir -p "$wine/gecko"
                tar -xf "$up/$name" --no-same-owner -C "$wine/gecko" ;;
            dxvk)
                mkdir -p "$win/dxvk"
                tar -xf "$up/$name" --no-same-owner --strip-components=1 \
                    -C "$win/dxvk" "$t/x32" "$t/x64"
                echo "$v" >"$win/dxvk/VERSION" ;;
            vkd3d)
                # only the DLLs: the space is set up by raye-windows-prepare
                mkdir -p "$win/vkd3d-proton"
                tar -xf "$up/$name" --no-same-owner --strip-components=1 \
                    -C "$win/vkd3d-proton" "$t/x86" "$t/x64"
                echo "$v" >"$win/vkd3d-proton/VERSION" ;;
        esac
    done
    chmod -R u+rwX,go+rX,go-w "$wine/mono" "$wine/gecko" "$win/dxvk" "$win/vkd3d-proton"
}

# ------------------------------------------------------------ main

mode=fetch cache= orig=yes dest=
while [ $# -gt 0 ]; do
    case $1 in
        --check) mode=check ;;
        --unpack) [ $# -ge 2 ] || usage; mode=unpack dest=$2; shift ;;
        --version) mode=version ;;
        --list) mode=list ;;
        --cache) [ $# -ge 2 ] || usage; cache=$2; shift ;;
        --no-orig) orig=no ;;
        -h|--help) help ;;
        *) usage ;;
    esac
    shift
done

read_sums
case $mode in
    version) echo "$version"; exit 0 ;;
    list) for name in $names; do echo "$name $(url_of "$name")"; done; exit 0 ;;
esac

check_changelog
check_table
case $mode in
    fetch)
        fetch
        [ "$orig" = no ] || write_orig ;;
    check) check ;;
    unpack)
        check
        unpack ;;
esac
