#!/bin/bash
# raye-gaming depends on raye-proton, which is built apart (GE-Proton):
# the image build has to take it in, like raye-wine.
#   tests/test_proton_in_image.sh
here=$(cd "$(dirname "$0")/.." && pwd)
bad=0
fail() { echo "FAIL: $*"; bad=1; }
deps=$(awk '/^Package: raye-gaming/{p=1} p&&/^$/{exit} p' "$here/packages/raye-base/debian/control")
if grep -q 'raye-proton' <<<"$deps"; then
    grep -q '^ *add_proton_debs "\$debs"' "$here/build.sh" || fail "raye-gaming needs raye-proton, build.sh never adds it"
    grep -q 'PROTON_DEBS' "$here/build.sh" || fail "build.sh has no PROTON_DEBS"
fi
[ "$bad" = 0 ] && echo "ok: raye-proton goes into the image"
exit "$bad"
