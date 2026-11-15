#!/bin/sh
# Gets the sched_ext schedulers' source and every Rust crate they need,
# so raye-scx builds with no network at all.
#
# scx.sha256 is the list: the upstream release tarball, and the tarball
# of vendored crates made from it. Nothing is used unless it matches.
# For the crates tarball the SHA-256 is of the tar inside the .xz, so a
# different xz still gives the same answer.
#
#   fetch-scx.sh [--cache DIR] [--no-orig]
#       put both files in upstream/ (downloading the release and running
#       cargo vendor for what is missing), then write
#       ../raye-scx_<version>.orig.tar.xz
#   fetch-scx.sh --check          check upstream/, offline
#   fetch-scx.sh --unpack DEST    check, then unpack the source into DEST,
#                                 apply patches/, put the crates in
#                                 DEST/vendor (debian/rules)
#   fetch-scx.sh --version        the upstream version
#   fetch-scx.sh --list           every file and where it comes from
#
# RAYE_SCX_MIRROR=https://host/path takes both files from that one place
# instead (same names); the hashes still decide.

set -eu

here=$(cd "$(dirname "$0")" && pwd)
sums=$here/scx.sha256
patches=$here/patches
changelog=$here/debian/changelog
up=$here/upstream
pkg=raye-scx

die() { echo "fetch-scx: $*" >&2; exit 1; }

usage() {
    echo "Usage: fetch-scx.sh [--cache DIR] [--no-orig] | --check | --unpack DEST | --version | --list" >&2
    exit 2
}

# the comment at the top of this file
help() {
    sed -n '2,/^$/s/^# \{0,1\}//p' "$0"
    exit 0
}

# a half-written file or folder never stays behind
part= work=
cleanup() {
    [ -z "$part" ] || rm -f "$part"
    [ -z "$work" ] || rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

umask 022

# ------------------------------------------------------------ the list

# reads scx.sha256: sets version, src and vendor (file names) and their hashes
read_sums() {
    [ -f "$sums" ] || die "scx.sha256 is missing"
    src= vendor= src_hash= vendor_hash= n=0
    while read -r hash name rest || [ -n "${hash:-}" ]; do
        n=$((n + 1))
        case $hash in ''|'#'*) continue ;; esac
        [ -z "$rest" ] && [ ${#hash} -eq 64 ] && [ -n "$name" ] ||
            die "scx.sha256: line $n is not '<sha256>  <file>'"
        case $hash in *[!0-9a-f]*) die "scx.sha256: line $n: bad SHA-256" ;; esac
        case $name in
            scx-vendor-*.tar.xz)
                [ -z "$vendor" ] || die "scx.sha256: two crates tarballs"
                vendor=$name vendor_hash=$hash
                v=${name#scx-vendor-} v=${v%.tar.xz} ;;
            scx-*.tar.gz)
                [ -z "$src" ] || die "scx.sha256: two release tarballs"
                src=$name src_hash=$hash
                v=${name#scx-} v=${v%.tar.gz} ;;
            *) die "scx.sha256: line $n: do not know what $name is" ;;
        esac
        case $v in
            [0-9]*) ;;
            *) die "scx.sha256: no version in $name" ;;
        esac
        case $v in
            *[!0-9a-z.]*) die "scx.sha256: odd version in $name" ;;
        esac
    done <"$sums"
    [ -n "$src" ] || die "scx.sha256: no release tarball (scx-<version>.tar.gz)"
    [ -n "$vendor" ] || die "scx.sha256: no crates tarball (scx-vendor-<version>.tar.xz)"
    version=${src#scx-} version=${version%.tar.gz}
    [ "$vendor" = "scx-vendor-$version.tar.xz" ] ||
        die "scx.sha256: the release is $version but the crates tarball is $vendor"
    top=scx-$version
}

url_of() {
    if [ -n "${RAYE_SCX_MIRROR:-}" ]; then
        echo "${RAYE_SCX_MIRROR%/}/$1"
        return
    fi
    case $1 in
        "$src") echo "https://github.com/sched-ext/scx/archive/refs/tags/v$version.tar.gz" ;;
        "$vendor") echo "made here by cargo vendor from $src" ;;
    esac
}

# SHA-256 of a file; for the crates tarball, of the tar inside it
hash_file() {
    case $2 in
        "$vendor") xz -dc <"$1" 2>/dev/null | sha256sum | cut -d' ' -f1 ;;
        *) sha256sum <"$1" | cut -d' ' -f1 ;;
    esac
}

want_of() {
    case $1 in
        "$src") echo "$src_hash" ;;
        "$vendor") echo "$vendor_hash" ;;
    esac
}

# true when the file exists and has the SHA-256 of the list
good() {
    [ -f "$1" ] || return 1
    [ "$(hash_file "$1" "$2")" = "$(want_of "$2")" ]
}

# the changelog names the same upstream version as the list
check_changelog() {
    [ -f "$changelog" ] || die "debian/changelog is missing"
    full=$(sed -n '1s/^[^ ]* (\([^)]*\)).*/\1/p' "$changelog")
    full=${full#*:}
    [ "${full%-*}" = "$version" ] ||
        die "debian/changelog says ${full%-*}, scx.sha256 has $version"
}

# ------------------------------------------------------------ archives

# prints the first member of archive $1 that is not inside folder $2
check_members() {
    tar -tf "$1" | while IFS= read -r m; do
        case $m in
            "$2"|"$2/"|"$2/"*) ;;
            *) echo "$m"; break ;;
        esac
        case /$m/ in
            */../*) echo "$m"; break ;;
        esac
    done
}

# true when a link at path $1 pointing to $2 stays inside the top folder
inside() {
    case $2 in /*) return 1 ;; esac
    case $1 in */*) d=${1%/*} ;; *) d= ;; esac
    path=$d/$2 depth=0
    old_ifs=$IFS
    set -f
    IFS=/
    for c in $path; do
        case $c in
            ''|.) ;;
            ..) depth=$((depth - 1))
                if [ "$depth" -lt 1 ]; then IFS=$old_ifs; set +f; return 1; fi ;;
            *) depth=$((depth + 1)) ;;
        esac
    done
    IFS=$old_ifs
    set +f
    [ "$depth" -ge 1 ]
}

# prints the first link of archive $1 that points out of folder $2
check_links() {
    tar -tvf "$1" | while IFS= read -r line; do
        case $line in
            l*' -> '*)
                name=${line% -> *} name=${name#* [0-9][0-9]:[0-9][0-9] }
                target=${line##* -> }
                inside "$name" "$target" || { echo "$target"; break; } ;;
            h*' link to '*)
                target=${line##* link to }
                case $target in
                    "$2/"*) ;;
                    *) echo "$target"; break ;;
                esac
                case /$target/ in
                    */../*) echo "$target"; break ;;
                esac ;;
        esac
    done
}

safe_archive() {
    bad=$(check_members "$1" "$2")
    [ -z "$bad" ] || die "$(basename "$1"): $bad is outside $2/; not unpacked"
    bad=$(check_links "$1" "$2")
    [ -z "$bad" ] || die "$(basename "$1"): a link points to $bad; not unpacked"
}

# unpack the release into $1 (no top folder) and apply patches/
unpack_source() {
    safe_archive "$up/$src" "$top"
    mkdir -p "$1"
    tar -xzf "$up/$src" --no-same-owner --no-same-permissions \
        --strip-components=1 -C "$1"
    for p in "$patches"/*.patch; do
        [ -f "$p" ] || continue
        patch -s -p1 -N --no-backup-if-mismatch -d "$1" <"$p" ||
            die "patches/$(basename "$p") does not apply to $src"
    done
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
        got=$(hash_file "$part" "$1")
        rm -f "$part"; part=
        die "$1: SHA-256 does not match (got $got, want $(want_of "$1")); not used"
    fi
    mv "$part" "$up/$1"
    part=
}

# the crates tarball: cargo vendor on the patched release, packed the
# same way every time so its SHA-256 can be pinned
make_vendor() {
    command -v cargo >/dev/null || die "cargo is needed to make $vendor"
    echo "running cargo vendor for $src"
    work=$(mktemp -d "$up/.vendor.XXXXXX")
    unpack_source "$work/src"
    mkdir "$work/cargo-home"
    (cd "$work/src" && CARGO_HOME=$work/cargo-home \
        cargo vendor --locked --quiet vendor >/dev/null) ||
        die "cargo vendor failed"
    part=$up/.$vendor.part
    tar --sort=name --format=gnu --owner=0 --group=0 --numeric-owner \
        --mode='u+rw,go+r,go-w' --mtime=@0 -cf - -C "$work/src" vendor |
        xz -T1 -6 >"$part"
    rm -rf "$work"; work=
    if ! good "$part" "$vendor"; then
        got=$(hash_file "$part" "$vendor")
        rm -f "$part"; part=
        die "$vendor: SHA-256 does not match (got $got, want $vendor_hash); a crate changed or patches/ moved on, not used"
    fi
    mv "$part" "$up/$vendor"
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
    for name in "$src" "$vendor"; do
        if good "$up/$name" "$name"; then
            :
        elif [ -n "$cache" ] && good "$cache/$name" "$name"; then
            echo "from the cache: $name"
            put "$cache/$name" "$up/$name"
        elif [ "$name" = "$vendor" ] && [ -z "${RAYE_SCX_MIRROR:-}" ]; then
            rm -f "$up/$name"
            make_vendor
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
    for name in "$src" "$vendor"; do
        [ -f "$up/$name" ] || die "upstream/$name is missing (run fetch-scx.sh)"
        good "$up/$name" "$name" || die "upstream/$name: SHA-256 does not match"
    done
}

# the source tarball: this folder without debian/, the archives in upstream/
write_orig() {
    parent=$(dirname "$here")
    otop=$pkg-$version
    orig=$parent/${pkg}_$version.orig.tar.xz
    when=${SOURCE_DATE_EPOCH:-$(date -d "$(sed -n 's/^ -- .*>  //p' "$changelog" | head -n1)" +%s)}
    work=$(mktemp -d "$parent/.$pkg-orig.XXXXXX")
    mkdir "$work/$otop" "$work/$otop/upstream"
    for entry in "$here"/* "$here"/.[!.]*; do
        [ -e "$entry" ] || continue
        case ${entry##*/} in
            debian|upstream|build|.git|.pytest_cache|__pycache__) continue ;;
        esac
        cp -a "$entry" "$work/$otop/"
    done
    find "$work/$otop" \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
    for name in "$src" "$vendor"; do
        ln "$up/$name" "$work/$otop/upstream/$name" 2>/dev/null ||
            cp "$up/$name" "$work/$otop/upstream/$name"
    done
    part=$orig.part
    tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$when" \
        -cf - -C "$work" "$otop" | xz -T0 -3 >"$part"
    mv "$part" "$orig"
    part=
    rm -rf "$work"; work=
    echo "wrote $orig"
}

# ------------------------------------------------------------ unpacking

unpack() {
    [ ! -e "$dest" ] || [ -z "$(ls -A "$dest")" ] ||
        die "$dest is not empty; not unpacked"
    unpack_source "$dest"
    safe_archive "$up/$vendor" vendor
    [ ! -e "$dest/vendor" ] || die "$src already has a vendor/ folder"
    xz -dc "$up/$vendor" | tar -xf - --no-same-owner --no-same-permissions -C "$dest"
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
    list) for name in "$src" "$vendor"; do echo "$name $(url_of "$name")"; done; exit 0 ;;
esac

check_changelog
case $mode in
    fetch)
        fetch
        [ "$orig" = no ] || write_orig ;;
    check) check ;;
    unpack)
        check
        unpack ;;
esac
