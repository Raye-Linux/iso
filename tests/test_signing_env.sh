#!/bin/bash
#
# Checks that the archive key's home stays OUT of the build's environment.
#
#   tests/test_signing_env.sh              everything
#   tests/test_signing_env.sh --self-test  show that the checks fail on bad input
#
# Exit 0 when everything holds, 1 otherwise.
#
# Why this exists. build.sh carried `export GNUPGHOME=${GNUPGHOME:-/root/
# raye-keys/gnupg}` at the top, for one step: signing the ISO's .sha256. The
# default names the OWNER's key home, which does not exist on a build machine
# -- and gpg does not merely ignore a GNUPGHOME that is not there, it refuses
# to start:
#
#     gpg: Fatal: /var/lib/raye-release/gnupg: directory does not exist!    rc=2
#
# even for `--show-keys`, which reads nothing but the file it is handed.
# Exported, that reached every subprocess of the build. Measured 2026-11-07:
# the image could not be built at all, and what failed was raye-update's own
# keyring tests -- a package with nothing to do with signing. The build was
# right to stop; nothing pointed at the cause.
#
# The check reads build.sh with COMMENTS STRIPPED, and that is not
# cosmetic: the explanation above contains the words `export GNUPGHOME`, so a
# pattern over the raw file would match this very paragraph and report a
# defect that is only a description of one. Same family as a guard that goes
# green on a commented-out line, the other way round.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
BUILD=$here/build.sh
fail=0
err() { echo "FAIL: $*"; fail=1; }
ok() { echo "ok: $*"; }

# build.sh without comments: a `#` that starts a line or follows whitespace.
# Strings in this file hold no `#`, which is what makes that safe here.
code_of() { sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*#.*$//' "$1"; }

check_it_is_not_exported() {
    local hits
    hits=$(code_of "$1" | grep -cE '^[[:space:]]*export[[:space:]]+GNUPGHOME' || true)
    [ "$hits" = 0 ] &&
        ok "GNUPGHOME is not exported, so no package build inherits it" ||
        err "build.sh exports GNUPGHOME ($hits line(s)): gpg refuses to start when it names a directory that is not there, and every subprocess of the build would inherit it"
}

check_it_is_not_set_for_the_whole_script() {
    # A per-command PREFIX also starts a line with `GNUPGHOME=`, and that
    # is the correct form -- the first version of this check flagged the four
    # lines of the fix itself. What is wrong is an assignment with nothing
    # after it: that one reaches everything run afterwards.
    local hits
    hits=$(code_of "$1" | grep -cE '^[[:space:]]*GNUPGHOME=[^[:space:]]*[[:space:]]*$' || true)
    [ "$hits" = 0 ] &&
        ok "GNUPGHOME is never assigned on a line of its own" ||
        err "build.sh assigns GNUPGHOME on its own line ($hits): it must be set per command, in front of the one that signs"
}

check_the_signing_step_still_sets_it() {
    # Removing the export must not QUIETLY stop the signing from finding
    # the key. Without this, the fix and a regression look identical: both
    # leave a build.sh with no exported GNUPGHOME.
    local hits
    hits=$(code_of "$1" | grep -cE 'GNUPGHOME=[^ ]+[[:space:]]+(gpg|aptly)' || true)
    [ "${hits:-0}" -ge 1 ] &&
        ok "the steps that sign set it per command ($hits)" ||
        err "nothing in build.sh sets GNUPGHOME in front of gpg or aptly: the release would be left unsigned without saying so"
}

check_the_default_is_still_overridable() {
    local hits
    hits=$(code_of "$1" | grep -cE '\$\{GNUPGHOME:-' || true)
    [ "${hits:-0}" -ge 1 ] &&
        ok "an outside GNUPGHOME still chooses the key home" ||
        err "build.sh no longer reads GNUPGHOME from the environment: a machine that keeps the key elsewhere could not sign"
}

self_test() {
    local t ok_all=1
    t=$(mktemp -d)

    sed 's/^GPG_HOME=/export GNUPGHOME=/' "$BUILD" > "$t/exporte.sh"
    (fail=0; check_it_is_not_exported "$t/exporte.sh"; exit $fail) >/dev/null &&
        { echo "self-test: un export GNUPGHOME non attrape"; ok_all=0; }

    sed 's/^GPG_HOME=/GNUPGHOME=/' "$BUILD" > "$t/pose.sh"
    (fail=0; check_it_is_not_set_for_the_whole_script "$t/pose.sh"; exit $fail) >/dev/null &&
        { echo "self-test: une affectation de ligne non attrapee"; ok_all=0; }

    sed 's/GNUPGHOME=\$GPG_HOME //' "$BUILD" > "$t/sans-signature.sh"
    (fail=0; check_the_signing_step_still_sets_it "$t/sans-signature.sh"; exit $fail) >/dev/null &&
        { echo "self-test: signature silencieusement desarmee non attrapee"; ok_all=0; }

    # the comment-stripping itself: a file whose ONLY mention is in a
    # comment must pass. Without this the guard would fail on its own
    # explanation, which is how it was first written.
    printf '#!/bin/bash\n# export GNUPGHOME=/nope is what this used to do\nGPG_HOME=/x\nGNUPGHOME=$GPG_HOME gpg --version\n' \
        > "$t/commente.sh"
    (fail=0; check_it_is_not_exported "$t/commente.sh"; exit $fail) >/dev/null ||
        { echo "self-test: un simple commentaire est pris pour un export"; ok_all=0; }

    rm -rf "$t"
    [ "$ok_all" = 1 ] && echo "self-test ok"
    [ "$ok_all" = 1 ]
}

case "${1:-}" in
    --self-test) self_test; exit $? ;;
    -h|--help) sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

[ -r "$BUILD" ] || { echo "skipped: no $BUILD" >&2; exit 77; }

echo "== $BUILD"
check_it_is_not_exported "$BUILD"
check_it_is_not_set_for_the_whole_script "$BUILD"
check_the_signing_step_still_sets_it "$BUILD"
check_the_default_is_still_overridable "$BUILD"
echo
[ "$fail" = 0 ] && echo "ok: la cle d'archive ne fuit pas dans l'environnement du build"
exit "$fail"
