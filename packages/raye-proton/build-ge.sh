#!/bin/sh
# Builds Raye Proton: GE-Proton from its sources, with GE-Proton's own
# build system (patches/protonprep-valve-staging.sh, configure.sh, make
# redist) in the Proton SDK container, under the name raye-proton.
# Nothing in GE-Proton is changed; the name Steam shows ("Raye Proton")
# is set when the package is made (debian/rules, raye-proton-name).
#
#   build-ge.sh build WORKDIR    clone the pinned tag, patch, build; leaves
#                                WORKDIR/build/raye-proton.tar.gz and
#                                raye-proton-licenses.tar.gz (the licence
#                                files of GE-Proton and of every component)
#   build-ge.sh licenses WORKDIR only the second archive
#   build-ge.sh check DIR        DIR holds the two archives upstream.sha512 names
#
# WORKDIR needs about 60 GB, podman and access to github.com and
# registry.gitlab.steamos.cloud. Podman's storage is kept in WORKDIR.
# JOBS (default 6) caps the parallel jobs; DOCKER_OPTS adds podman options
# (Raye's build machine: --cgroup-parent=raye-builds.slice).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tag=$(sed -n 's/^tag=//p' "$here/ge-version.txt")
commit=$(sed -n 's/^commit=//p' "$here/ge-version.txt")

# every licence or notice file at the top of GE-Proton and of each of its
# components (its folders and git submodules), kept under the component's path
licenses() {
    src=$1/src/proton-ge out=$1/licenses/raye-proton-licenses
    rm -rf "$1/licenses"; mkdir -p "$out"
    { echo .; (cd "$src" && for d in */; do echo "${d%/}"; done)
      git -C "$src" submodule foreach --quiet --recursive 'echo "$displaypath"'; } | sort -u |
    while read -r d; do
        for f in "$src/$d"/LICENSE* "$src/$d"/LICENCE* "$src/$d"/COPYING* "$src/$d"/COPYRIGHT* \
                 "$src/$d"/Copyright* "$src/$d"/License* "$src/$d"/license* "$src/$d"/NOTICE* \
                 "$src/$d"/AUTHORS "$src/$d"/PATENTS* "$src/$d"/*/COPYING*; do
            [ -f "$f" ] || continue
            rel=${f#"$src/"}; mkdir -p "$out/${rel%/*}"; cp "$f" "$out/$rel"
        done
    done
    tar -C "$1/licenses" --sort=name --owner=0 --group=0 --mtime=@0 \
        -czf "$1/build/raye-proton-licenses.tar.gz" raye-proton-licenses
}

case ${1:-} in
check)
    [ $# -eq 2 ] || { echo "usage: build-ge.sh check DIR" >&2; exit 2; }
    [ "$(grep -c '  raye-proton' "$here/upstream.sha512")" -eq 2 ] || {
        echo "build-ge.sh: upstream.sha512 does not name the two archives" >&2; exit 1; }
    (cd "$2" && sha512sum --strict --quiet -c "$here/upstream.sha512") || {
        echo "build-ge.sh: the archives in $2 are not the ones upstream.sha512 names" >&2; exit 1; }
    ;;
licenses)
    [ $# -eq 2 ] || { echo "usage: build-ge.sh licenses WORKDIR" >&2; exit 2; }
    licenses "$2"
    ;;
build)
    [ $# -eq 2 ] || { echo "usage: build-ge.sh build WORKDIR" >&2; exit 2; }
    w=$2
    mkdir -p "$w/podman/root" "$w/podman/runroot" "$w/podman/tmp" "$w/ccache" "$w/cargo" "$w/build"
    printf '[storage]\ndriver = "overlay"\ngraphroot = "%s"\nrunroot = "%s"\n' \
        "$w/podman/root" "$w/podman/runroot" > "$w/podman/storage.conf"
    printf '[engine]\nimage_copy_tmp_dir = "%s"\n' "$w/podman/tmp" > "$w/podman/containers.conf"
    export CONTAINERS_STORAGE_CONF="$w/podman/storage.conf" CONTAINERS_CONF="$w/podman/containers.conf"
    export TMPDIR="$w/podman/tmp" CCACHE_DIR="$w/ccache" CARGO_HOME="$w/cargo"
    if [ ! -d "$w/src/proton-ge" ]; then
        git clone --depth 1 --branch "$tag" https://github.com/gloriouseggroll/proton-ge-custom "$w/src/proton-ge"
        git -C "$w/src/proton-ge" submodule update --init --recursive --depth 1 --jobs 6
        [ "$(git -C "$w/src/proton-ge" rev-parse HEAD)" = "$commit" ] || {
            echo "build-ge.sh: $tag is not commit $commit" >&2; exit 1; }
        (cd "$w/src/proton-ge" && ./patches/protonprep-valve-staging.sh) > "$w/patchlog.txt" 2>&1
        ! grep -q 'FAILED\|\.rej' "$w/patchlog.txt"
    fi
    cd "$w/build"
    ../src/proton-ge/configure.sh --build-name=raye-proton --container-engine=podman
    # the container downloads a few files (Wine Gecko, Mono): it uses the
    # computer's network, and so its name resolver
    make -j"${JOBS:-6}" DOCKER_OPTS="--network=host ${DOCKER_OPTS:-}" redist
    licenses "$w"
    ;;
*)
    echo "usage: build-ge.sh build|licenses WORKDIR | check DIR" >&2; exit 2 ;;
esac
