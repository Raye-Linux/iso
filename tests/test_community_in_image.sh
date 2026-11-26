#!/bin/bash
# raye-desktop depends on raye-community, so the image build has to build
# it (the community repo next to this one), or installing the desktop fails.
#   tests/test_community_in_image.sh
here=$(cd "$(dirname "$0")/.." && pwd)
bad=0
fail() { echo "FAIL: $*"; bad=1; }
deps=$(awk '/^Package: raye-desktop/{p=1} p&&/^$/{exit} p' "$here/packages/raye-base/debian/control")
if grep -q 'raye-community' <<<"$deps"; then
    grep -q 'compiled_sources() {.*\$src/community' "$here/build.sh" || fail "raye-desktop needs raye-community, build.sh does not build it"
fi
[ "$bad" = 0 ] && echo "ok: raye-community is built for the image"
exit "$bad"
