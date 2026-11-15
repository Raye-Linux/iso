#!/bin/bash
#
# Checks config/purge.list, the packages the Raye image never ships:
#  - every line is "<package> <id> <reason>" (or a "#staged" line);
#  - no raye-base package depends on, or recommends, what it removes;
#  - apt can install Raye with all of them held out, with and without
#    Recommends, so purging them never takes anything else along.
#
#   tests/test_purge.sh              the list, raye-base, then apt here
#   tests/test_purge.sh --root DIR   apt inside the image tree DIR, which
#                                    must have raye-desktop available;
#                                    also simulates purging what is installed
#   tests/test_purge.sh --names      print the packages that count, one per line
#   tests/test_purge.sh --no-apt     skip the apt part
#   tests/test_purge.sh --self-test  show that each check fails on bad input
#
# --list FILE and --control FILE replace the repo's files (used by the
# self-test). Exit 0 when everything holds, 1 otherwise.

# Measured on 2026-11-05, so nobody walks this road twice.
#
# This test used to fail with "Raye needs drkonqi". It was reading the
# wrong distribution. The numbers:
#
#  - Raye is built from Ubuntu SUITE=resolute (build.sh). The build machine, where
#    the test is usually run, is Debian 13 trixie, and so is the ISO
#    build chroot: apt-cache policy there shows o=Debian n=trixie and
#    not one Ubuntu source.
#  - trixie's plasma-workspace 4:6.3.6-2 has a hard, versioned, single
#    dependency "drkonqi (>= 6.2.90~)". Holding drkonqi out therefore
#    cannot work *in trixie*, and apt said so:
#      plasma-workspace : Depends: drkonqi (>= 6.2.90~) but it is not
#      going to be installed
#    The blame was right about trixie and says nothing about Raye.
#  - resolute's plasma-workspace 4:6.6.6-0ubuntu0.1 does NOT require
#    drkonqi. In the built image
#    (/var/tmp/raye-build/chroot, ID=raye, VERSION_CODENAME=resolute):
#    plasma-desktop, plasma-workspace and raye-desktop are installed,
#    drkonqi is absent, and of the 1652 installed packages not one
#    names drkonqi in Depends, Pre-Depends, Recommends or Suggests.
#    All 27 names of purge.list are absent. The purge holds.
#
# So drkonqi stays on purge.list, and the apt part of this test now only
# fails when the apt it questioned is Raye's own archive. Elsewhere its
# findings are notes: another distribution's plasma stack has other
# dependencies, and a verdict drawn from it would be a guess.
#
# Two further traps, both fixed here:
#  - the finished image has its apt lists cleaned, so "apt-get -s
#    install" cannot run under --root and answers "E: Unable to locate
#    package raye-desktop". That is a tree with no archive, not a broken
#    purge list; it is told apart and the dpkg checks still run.
#  - the old blame was a grep for "(Depends:? |^ +)<name>" over apt's
#    whole output. On this failure it was right -- it matched the real
#    "Depends: drkonqi" line -- but the "^ +<name>" half also matches
#    the indented package lists apt prints ("The following additional
#    packages will be installed:"), so a purged package that apt merely
#    listed would have been reported as one Raye needs. Only real
#    unmet-dependency lines count now, and the asker is named, which is
#    the one piece of information that was missing.
#
# Note: usage() prints lines 3-19 of this file. Keep that block that
# length, or move the range; this comment sits below it on purpose.

set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
LIST=$here/config/purge.list
CONTROL=$here/packages/raye-base/debian/control
LIVE=$here/config/live.list
PINS=$here/packages/raye-base/release/apt/raye-pins.pref
ROOT=
MODE=check
APT=1

fail=0
err() { echo "FAIL: $*"; fail=1; }
# 1 when the apt we questioned is Raye's own archive (set in check_apt).
APT_AUTHORITY=0
APT_WEAK=0
TMPS=()
# shellcheck disable=SC2329  # run by the EXIT trap
cleanup() { local d; for d in "${TMPS[@]}"; do rm -rf "$d"; done; }
trap cleanup EXIT
note() { echo "note: $*"; }

# A finding that rests on apt's dependency graph. It is only a failure
# when that graph is Raye's; from any other archive it is a warning,
# because another distribution's packages have other dependencies.
apt_err() {
    if [ "$APT_AUTHORITY" = 1 ]; then
        err "$*"
    else
        note "not Raye's archive, so not a failure: $*"
    fi
}

usage() { sed -n '3,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT=${2:?--root needs a directory}; shift 2 ;;
        --list) LIST=${2:?--list needs a file}; shift 2 ;;
        --control) CONTROL=${2:?--control needs a file}; shift 2 ;;
        --names) MODE=names; shift ;;
        --no-apt) APT=0; shift ;;
        --self-test) MODE=self; shift ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
done

# ------------------------------------------------------------- the list

active_names() {
    awk '!/^[[:space:]]*(#|$)/ { print $1 }' "$1"
}

staged_names() {
    awk '/^#staged[[:space:]]/ { print $2 }' "$1"
}

lint_list() {
    awk -v file="$(basename "$1")" '
        function bad(msg) { printf "FAIL: %s:%d: %s\n", file, NR, msg; status = 1 }
        function entry(name, id, nf) {
            if (name !~ /^[a-z0-9][a-z0-9+.-]+$/) bad("\"" name "\" is not a package name")
            else if (name ~ /^raye-/) bad(name " is a Raye package")
            if (nf < 2 || id !~ /^([A-Z][A-Z]-[0-9]+|base)$/)
                bad(name ": the second field must be the id of the decision (XX-0 or base)")
            else if (nf < 3) bad(name ": give the reason after the id")
            if (name in seen) bad(name " is already on line " seen[name])
            else seen[name] = NR
        }
        /^[[:space:]]*$/ { next }
        /^#staged[[:space:]]/ { n = split($0, f); entry(f[2], f[3], n - 1); next }
        /^#[[:space:]]*stag/ { bad("write a waiting line as \"#staged <package> <id> <reason>\""); next }
        /^[[:space:]]*#/ { next }
        { entry($1, $2, NF) }
        END { exit status }
    ' "$1"
}

# --------------------------------------------------------- raye-base

# "binary<TAB>field<TAB>alt1|alt2" for every Depends, Pre-Depends and
# Recommends group of a debian/control. Commented lines (the staged
# blocks) are not part of the field, as for dpkg.
control_groups() {
    awk '
        function flush(   n, i, g, groups) {
            if (field != "") {
                n = split(buf, groups, ",")
                for (i = 1; i <= n; i++) {
                    g = groups[i]
                    gsub(/\([^)]*\)|\[[^]]*\]|<[^>]*>|:any|:native/, "", g)
                    gsub(/[[:space:]]/, "", g)
                    if (g != "" && g !~ /^\$\{/) printf "%s\t%s\t%s\n", pkg, field, g
                }
            }
            field = ""; buf = ""
        }
        /^#/ { next }
        /^[[:space:]]*$/ { flush(); pkg = ""; next }
        /^[[:space:]]/ { if (field != "") buf = buf " " $0; next }
        {
            flush()
            if ($1 == "Package:") pkg = $2
            else if ($1 ~ /^(Depends|Pre-Depends|Recommends):$/) {
                field = substr($1, 1, length($1) - 1)
                buf = substr($0, index($0, ":") + 1)
            }
        }
        END { flush() }
    ' "$1"
}

check_control() {
    local -A purged=() staged=() used_staged=()
    local n bin field group alt left hit
    while read -r n; do purged[$n]=1; done < <(active_names "$LIST")
    while read -r n; do staged[$n]=1; done < <(staged_names "$LIST")

    while IFS=$'\t' read -r bin field group; do
        left=0 hit=
        IFS='|' read -ra alts <<< "$group"
        for alt in "${alts[@]}"; do
            if [ -n "${purged[$alt]:-}" ]; then hit="$hit $alt"; else left=1; fi
            [ -n "${staged[$alt]:-}" ] && used_staged[$alt]=$bin
        done
        if [ -n "$hit" ] && [ "$left" = 0 ]; then
            err "$bin's $field needs \"$group\", which purge.list removes"
        elif [ -n "$hit" ]; then
            note "$bin's $field \"$group\" keeps an alternative to${hit}"
        fi
    done < <(control_groups "$CONTROL")

    for n in "${!staged[@]}"; do
        if [ -n "${used_staged[$n]:-}" ]; then
            note "staged: $n is still in ${used_staged[$n]}'s fields, it waits"
        else
            note "staged: $n has left raye-base's fields, its line can count now"
        fi
    done
}

# --------------------------------------------------------------- apt

# set by check_apt; empty means "whatever apt would read by itself"
APT_BASE=()

aptq() {
    if [ -n "$ROOT" ]; then
        chroot "$ROOT" /usr/bin/env -i LANG=C.UTF-8 PATH=/usr/sbin:/usr/bin:/sbin:/bin "$@"
    else
        LANG=C.UTF-8 "$@"
    fi
}

# names of $@ that apt knows, then "!" and those apt can install: the ones
# with a candidate, and virtual ones that some package provides.
#
# APT_BASE is not optional, and leaving it out cost this test its whole
# install simulation. Measured 2026-11-06 on the beta image: this function
# read the IMAGE's populated dpkg status, where raye-desktop is installed
# and therefore has a candidate -- so the test picked raye-desktop as the
# thing to install. The simulation at the bottom of check_apt installs onto
# an EMPTY status (that is the point: a fresh system), and on an empty base
# raye-desktop has no candidate at all, because the Raye archive is not
# published yet: dl.rayelinux.com does not resolve and
# raye-linux.github.io/packages answers 404. apt said "E: Unable to locate
# package raye-desktop", no_archive() read that as "this tree has no
# archive", and the test reported for days that the image carries no
# archive -- a true-sounding sentence about the wrong thing.
#
# What can be installed and what it is installed ONTO must be the same
# base, by construction.
apt_known() {
    local n
    aptq apt-cache "${aptopt[@]}" "${APT_BASE[@]}" policy "$@" 2>/dev/null | awk '
        /^[^[:space:]].*:$/ { name = substr($0, 1, length($0) - 1); order[++n] = name; table = 0; next }
        /^[[:space:]]+Candidate:/ { if ($2 != "(none)") ok[name] = 1; next }
        /^[[:space:]]+Version table:/ { table = 1; next }
        table { versions[name] = 1 }
        END {
            for (i = 1; i <= n; i++) print order[i]
            print "!"
            for (i = 1; i <= n; i++)
                if (order[i] in ok) print order[i]
                else if (!(order[i] in versions)) print "?" order[i]
        }' | while read -r n; do
            case "$n" in
                \?*) n=${n#?}
                    aptq apt-cache "${aptopt[@]}" showpkg "$n" 2>/dev/null |
                        sed '1,/^Reverse Provides:/d' | grep . >/dev/null && echo "$n" ;;
                *) echo "$n" ;;
            esac
        done
}

# Without the image's apt setup, only the "never" pins of the repo apply
# (Pin: release a=*); a pin that prefers another repo (Pin: origin) names
# packages the image takes from there, so they are left out of the check.
fallback_pins() {
    awk -v RS= -v out="$2" '
        /Pin: release a=\*/ && /Pin-Priority: -/ { print $0 "\n" > out; next }
        /Pin: origin/ && !/Pin-Priority: -/ {
            sub(/^.*Package:[[:space:]]*/, ""); sub(/\n.*/, ""); print
        }' "$1" | tr ' ' '\n' | awk 'NF'
}

# does the apt-get -s output $1 install package $2?
installs() {
    local name=${2//./\\.}
    grep -E "^Inst ${name//+/\\+}(:[a-z0-9]+)? " <<< "$1" >/dev/null
}

# ------------------------------------------------- whose archive is this?

# A field of an os-release file. Read, never sourced: it comes from an
# image tree, so it is data, not code to run here.
os_field() {
    sed -n "s/^$2=[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}\$/\1/p" "$1" 2>/dev/null | head -n1
}

# The suite the image is built from, as build.sh names it. Comments are
# stripped first, so a line that only mentions SUITE= in prose is not
# taken for the setting -- the same care the rest of this file takes with
# the commented #staged blocks.
# Two limits, said rather than hidden:
#  - if build.sh ever computes SUITE instead of assigning it a literal,
#    this finds nothing. That lands on the safe side: the apt check then
#    declares it cannot speak for Raye.
#  - a commented assignment is kept out twice over, by the comment strip
#    and by the ^ anchor. The self-test case below therefore only goes
#    red when both are gone (measured): either one alone still holds.
target_suite() {
    [ -f "$here/build.sh" ] || return 0
    sed 's/#.*//' "$here/build.sh" |
        sed -n 's/^[[:space:]]*SUITE=[\"'"'"']\{0,1\}\([A-Za-z0-9._-]\{1,\}\).*/\1/p' |
        head -n1
}

# The suites apt is actually serving, for the messages: "trixie-updates
# trixie". Taken from the "release" lines of apt-cache policy.
apt_archive_id() {
    aptq apt-cache "${aptopt[@]}" policy 2>/dev/null | tr ',' '\n' |
        awk -F= '
            $1 ~ /(^|[[:space:]])n$/ {
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
                if ($2 != "" && !($2 in seen)) {
                    seen[$2] = 1
                    printf "%s%s", (c++ ? " " : ""), $2
                }
            }
            END { print "" }'
}

# Does apt's package data describe the suite Raye is built from?
apt_speaks_for_raye() {
    local suite=$1
    [ -n "$suite" ] || return 1
    aptq apt-cache "${aptopt[@]}" policy 2>/dev/null | tr ',' '\n' |
        grep -qE "^[[:space:]]*n=$suite[[:space:]]*\$"
}

# Is --root the Raye image itself? Then its package graph IS Raye's.
root_is_image() {
    [ -n "$ROOT" ] || return 1
    local id code suite
    id=$(os_field "$ROOT/etc/os-release" ID)
    code=$(os_field "$ROOT/etc/os-release" VERSION_CODENAME)
    suite=$(target_suite)
    [ "$id" = raye ] && return 0
    [ -n "$code" ] && [ -n "$suite" ] && [ "$code" = "$suite" ]
}

# "Unable to locate package" for something Raye installs means the tree
# has no archive to install from -- the finished image has its apt lists
# cleaned. Nothing to do with the purge list.
no_archive() { grep -q 'E: Unable to locate package' <<< "$1"; }

# "<asker><TAB><needed>" for every real unmet dependency apt reports:
#     " plasma-workspace : Depends: drkonqi (>= 6.2.90~) but it is ..."
# and its indented continuation lines. The --solver trace that follows
# only *mentions* packages ("- drkonqi:amd64 is not selected for
# install"); blaming those framed packages that were merely context, so
# the trace is deliberately left out.
unmet_deps() {
    awk '
        /^[[:space:]]+[^[:space:]]+[[:space:]]+:[[:space:]]/ { asker = $1 }
        asker != "" &&
        match($0, /(Depends|Pre-Depends|Recommends|Suggests):[[:space:]]*[^[:space:],|]+/) {
            need = substr($0, RSTART, RLENGTH)
            sub(/^[^:]*:[[:space:]]*/, "", need)
            sub(/:[a-z0-9]+$/, "", need)
            if (need != "") print asker "\t" need
        }
        /^(E:|W:|The following)/ { asker = "" }
    ' <<< "$1"
}

check_apt() {
    local status_host status_in tmpdir
    local -a elsewhere=()
    aptopt=(-o Debug::NoLocking=1)
    if [ -n "$ROOT" ]; then
        [ -x "$ROOT/usr/bin/apt-get" ] || { err "$ROOT has no apt-get"; return; }
        tmpdir=$(mktemp -d "$ROOT/tmp/purge-test.XXXXXX")
        status_in=/tmp/$(basename "$tmpdir")/status
    else
        tmpdir=$(mktemp -d)
        status_in=$tmpdir/status
        if [ -f "$PINS" ]; then
            mapfile -t elsewhere < <(fallback_pins "$PINS" "$tmpdir/pins")
            touch "$tmpdir/pins"
            aptopt+=(-o "Dir::Etc::Preferences=$tmpdir/pins" -o "Dir::Etc::PreferencesParts=$tmpdir/none")
        fi
    fi
    TMPS+=("$tmpdir")
    status_host=$tmpdir/status
    : > "$status_host"
    # the one dpkg base every apt question in this function is asked about
    APT_BASE=(-o "Dir::State::status=$status_in")

    if ! aptq apt-cache "${aptopt[@]}" show plasma-desktop >/dev/null 2>&1; then
        if [ -n "$ROOT" ]; then err "apt in $ROOT has no package lists"; else
            echo "SKIP apt checks: this apt has no package lists (run apt-get update, or use --root)"
        fi
        return
    fi

    # Whose dependency graph are we about to question? Only Raye's own
    # can say what Raye needs; see the measurements at the top of this
    # file. Everything else is reported, nothing else is failed.
    local suite served
    suite=$(target_suite)
    served=$(apt_archive_id)
    if root_is_image || { [ -z "$ROOT" ] && apt_speaks_for_raye "$suite"; }; then
        APT_AUTHORITY=1
    else
        APT_AUTHORITY=0
        APT_WEAK=1
        note "this apt serves ${served:-an archive it does not name}, not ${suite:-the suite Raye is built from}."
        note "  Its plasma stack has its own dependencies, so what it calls"
        note "  missing is a warning here, never a failure. For a verdict,"
        note "  run with --root on a tree whose os-release says ID=raye."
    fi

    # what Raye installs: raye-desktop and the live list when apt can get
    # them, else the archive part of raye-base's Depends
    local -a live=() targets=() purged=() known=() unchecked=() from_other=()
    local n line bin field group alt
    mapfile -t live < <(sed 's/#.*//' "$LIVE" | awk 'NF { print $1 }')
    mapfile -t purged < <(active_names "$LIST")

    local -A have=()
    if apt_known raye-desktop | sed '0,/^!$/d' | grep -x raye-desktop >/dev/null; then
        targets=(raye-desktop "${live[@]}")
        echo "apt: checking raye-desktop and the live list"
    else
        # Not a failure when Raye's own archive simply is not published.
        # Measured 2026-11-06: dl.rayelinux.com does not resolve and
        # raye-linux.github.io/packages answers 404, so not one raye-*
        # package has a candidate on a fresh base -- including the thirteen
        # raye-desktop depends on. The purge list is still answerable: hold
        # the purged packages out while installing the ARCHIVE part of what
        # Raye needs, which is what the branch below does and what "purging
        # never takes anything else along" actually means.
        #
        # An unavailable raye-desktop for ANY OTHER reason stays a failure:
        # that would be an image whose own packages apt cannot see.
        if [ -n "$ROOT" ]; then
            local -a raye_own=()
            while IFS= read -r n; do
                case "$n" in raye-*|sddm-theme-raye|plymouth-theme-raye) raye_own+=("$n") ;; esac
            done < <(aptq dpkg-query -f '${Package}\n' -W 'raye-*' 2>/dev/null)
            if [ ${#raye_own[@]} -eq 0 ]; then
                err "apt in $ROOT cannot install raye-desktop, and the tree has" \
                    "no raye-* package installed either: this is not a Raye image"
                return
            fi
            local published=0 n
            while read -r n; do
                [ "$n" = "!" ] && continue
                published=1
            done < <(apt_known "${raye_own[@]}" | sed '0,/^!$/d')
            if [ "$published" = 1 ]; then
                err "apt in $ROOT cannot install raye-desktop, although other" \
                    "raye-* packages do have a candidate: something is wrong" \
                    "with raye-desktop itself, not with the archive"
                return
            fi
            note "Raye's own archive is not published yet, so none of the" \
                 "${#raye_own[@]} raye-* packages has a candidate on a fresh base." \
                 "The purged packages are held out of the ARCHIVE part of what"
            note "  Raye needs instead -- which is the part that can take"
            note "  something else along."
        fi
        local -a groups=() names=()
        while IFS=$'\t' read -r bin field group; do
            case "$bin" in raye-system|raye-desktop|raye-gaming) ;; *) continue ;; esac
            [ "$field" = Recommends ] && continue
            groups+=("$group")
        done < <(control_groups "$CONTROL")
        for group in "${groups[@]}"; do IFS='|' read -ra alts <<< "$group"; names+=("${alts[@]}"); done
        while read -r n; do [ "$n" = "!" ] || have[$n]=1; done < <(apt_known "${names[@]}" "${live[@]}" | sed '0,/^!$/d')
        local pat other
        for group in "${groups[@]}"; do
            IFS='|' read -ra alts <<< "$group"
            line='' other=''
            for alt in "${alts[@]}"; do
                for pat in "${elsewhere[@]}"; do
                    # shellcheck disable=SC2053
                    [[ $alt == $pat ]] && other=1
                done
                [ -n "$other" ] && break
                [ -n "${have[$alt]:-}" ] && { line=$alt; break; }
            done
            if [ -n "$other" ]; then from_other+=("$group")
            elif [ -n "$line" ]; then targets+=("$line")
            else unchecked+=("$group"); fi
        done
        for n in "${live[@]}"; do
            if [ -n "${have[$n]:-}" ]; then targets+=("$n"); else unchecked+=("$n"); fi
        done
        echo "apt: no raye-desktop here, checking the archive part of raye-base's Depends (${#targets[@]} packages)"
        [ ${#from_other[@]} -gt 0 ] && note "taken from another repo in the image, not checked: ${from_other[*]}"
        # Shortened on purpose. When apt has no index at all, EVERY name
        # is unavailable and this line was 205 packages long -- a true
        # sentence that drowned the one that matters (the note just below,
        # which says the simulation did not run). The count is the fact; the
        # names only help when a handful are missing.
        if [ ${#unchecked[@]} -gt 12 ]; then
            note "not available here, not checked: ${#unchecked[@]} packages," \
                 "starting with ${unchecked[*]:0:6} ..."
        elif [ ${#unchecked[@]} -gt 0 ]; then
            note "not available here, not checked: ${unchecked[*]}"
        fi
    fi

    # held out: every purged package apt knows ("name-" means never install)
    mapfile -t known < <(apt_known "${purged[@]}" | sed '/^!$/,$d')
    local -a hold=()
    for n in "${known[@]}"; do hold+=("$n-"); done

    # A simulation with nothing to install is not a passing simulation.
    # Measured 2026-11-06, and it was MY OWN first fix that produced it:
    # build.sh:465 empties /var/lib/apt/lists in the finished image, so
    # inside the image nothing has a candidate, targets came out EMPTY, and
    # `apt-get -s install` with no arguments succeeded -- the test printed
    # "ok: Raye installs without them (Recommends false, 0 packages)" twice
    # and went green having proved nothing. That is worse than the note it
    # replaced, which at least said the simulation had not run.
    #
    # The remedy is named, because it is the one thing that makes this
    # verdict reachable: refresh the index inside the tree.
    if [ ${#targets[@]} -eq 0 ]; then
        note "nothing to install: apt inside ${ROOT:-this tree} has no package"
        note "  index (build.sh:465 empties /var/lib/apt/lists in the finished"
        note "  image). The install simulation -- the part that proves purging"
        note "  takes nothing else along -- DID NOT RUN, and no verdict is"
        note "  claimed for it. To reach it:"
        note "    chroot <tree> apt-get update   (then run this again)"
        return
    fi

    local rec out rc came
    for rec in false true; do
        rc=0
        out=$(aptq apt-get -s -q "${aptopt[@]}" -o "Dir::State::status=$status_in" \
              -o "APT::Install-Recommends=$rec" install "${targets[@]}" "${hold[@]}" 2>&1) || rc=$?
        if [ "$rc" != 0 ]; then
            # No archive to install from is not a broken purge list. The
            # finished image has its apt lists cleaned, so say that
            # plainly and let the dpkg checks below do the real work.
            if no_archive "$out"; then
                note "${ROOT:-this apt} has no archive to install from, so the"
                note "  install simulation cannot run (Recommends $rec). The checks"
                note "  on the tree's own dpkg database below still hold."
                continue
            fi
            # Each purged package apt names in a real unmet-dependency
            # line is one Raye would need, and we name who asks for it.
            local culprit='' asker need
            while IFS=$'\t' read -r asker need; do
                for n in "${known[@]}"; do
                    [ "$need" = "$n" ] || continue
                    apt_err "Raye needs $n ($asker requires it), purge.list must not remove it (Recommends $rec)"
                    culprit=1
                done
            done < <(unmet_deps "$out")
            if [ -z "$culprit" ]; then
                apt_err "apt cannot install Raye without the purged packages together (Recommends $rec):"
                printf '%s\n' "$out" | grep -E '^(E:| +[a-z0-9])' | head -n 30 | sed 's/^/    /'
            fi
            continue
        fi
        for n in "${purged[@]}"; do
            if installs "$out" "$n"; then
                apt_err "apt still installs $n (Recommends $rec)"
            fi
        done
        echo "ok: Raye installs without them (Recommends $rec, $(printf '%s\n' "$out" | grep -c '^Inst') packages)"

        # for the record: which of them would have come in
        out=$(aptq apt-get -s -q "${aptopt[@]}" -o "Dir::State::status=$status_in" \
              -o "APT::Install-Recommends=$rec" install "${targets[@]}" 2>/dev/null) || true
        came=
        for n in "${purged[@]}"; do
            installs "$out" "$n" && came="$came $n"
        done
        [ -n "$came" ] && note "held out, would come in (Recommends $rec):$came"
    done

    if [ -n "$ROOT" ]; then
        local -a inst=()
        # shellcheck disable=SC2016  # dpkg-query fields, not shell
        mapfile -t inst < <(aptq dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' "${purged[@]}" 2>/dev/null |
                             awk '$1 ~ /^.i/ { print $2 }')
        if [ ${#inst[@]} -gt 0 ]; then
            local -A listed=()
            for n in "${purged[@]}"; do listed[$n]=1; done
            out=$(aptq apt-get -s -q -o Debug::NoLocking=1 purge "${inst[@]}" 2>&1) ||
                { err "apt cannot purge ${inst[*]}:"; printf '%s\n' "$out" | tail -n 20 | sed 's/^/    /'; return; }
            while read -r n; do
                n=${n%%:*}
                [ -n "${listed[$n]:-}" ] || err "purging ${inst[*]} would also remove $n"
            done < <(printf '%s\n' "$out" | awk '$1 == "Remv" || $1 == "Purg" { print $2 }')
            echo "installed now, to purge: ${inst[*]}"
        fi
    elif [ -f "$PINS" ]; then
        # apt must not bring them back later: each should match a negative pin
        local -a neg=()
        mapfile -t neg < <(awk '
            /^Package:/ { pk = substr($0, 9) }
            /^Pin-Priority:/ { if ($2 < 0) print pk }
            /^[[:space:]]*$/ { pk = "" }' "$PINS" | tr ' ' '\n' | awk 'NF')
        local open='' pat ok
        for n in "${purged[@]}"; do
            ok=0
            for pat in "${neg[@]}"; do
                # shellcheck disable=SC2053
                [[ $n == $pat ]] && { ok=1; break; }
            done
            [ "$ok" = 1 ] || open="$open $n"
        done
        [ -n "$open" ] && note "not pinned out in raye-pins.pref yet:$open"
    fi
    return 0
}

# ------------------------------------------------------------ self-test

self_test() {
    local t bad=0
    t=$(mktemp -d)
    TMPS+=("$t")

    cat > "$t/control" <<'EOF'
Source: raye-base

Package: raye-desktop
Depends: plasma-desktop, polkitd | old-agent,
         kcalc (>= 4),
# staged: comes later
#        khelpcenter,
         ${misc:Depends}
Recommends: spice-vdagent

Package: raye-system
Pre-Depends: base-files
Depends: sudo
EOF
    expect() {  # expect <exit code> <what> <list text>
        local want=$1 what=$2 got=0
        printf '%s\n' "$3" > "$t/list"
        "$0" --no-apt --list "$t/list" --control "$t/control" > "$t/out" 2>&1 || got=$?
        if [ "$got" = "$want" ]; then
            echo "ok   $what"
        else
            echo "FAIL $what (exit $got, wanted $want)"; sed 's/^/     /' "$t/out"; bad=1
        fi
    }

    expect 0 "a good list passes"                  "drkonqi GP-29 crash dialog
#staged kcalc AP-19 replaced"
    expect 0 "a commented Depends line does not count" "khelpcenter GP-44 help center"
    expect 0 "an alternative left is enough"       "old-agent base not wanted"
    expect 1 "a package name with capitals"        "Drkonqi GP-29 crash dialog"
    expect 1 "a line without an id"                "drkonqi crash dialog"
    expect 1 "a line without a reason"             "drkonqi GP-29"
    expect 1 "the same package twice"              "drkonqi GP-29 crash
drkonqi base again"
    expect 1 "a staged line repeats an active one"  "kcalc GP-44 x
#staged kcalc AP-19 y"
    expect 1 "a Raye package"                      "raye-store GP-44 no"
    expect 1 "a mistyped waiting line"             "# staged kcalc AP-19 replaced"
    expect 1 "raye-base depends on it"             "plasma-desktop GP-44 no"
    expect 1 "raye-base depends on it with a version" "kcalc GP-44 no"
    expect 1 "raye-base recommends it"             "spice-vdagent GP-44 no"
    expect 1 "raye-base pre-depends on it"         "base-files GP-44 no"
    expect 1 "every alternative is purged"         "polkitd GP-44 no
old-agent base no"

    # ---- the apt part: who is blamed, and on whose authority

    # A real apt failure, with its --solver trace. "innocent" appears
    # only in the trace: it must not be blamed. This is the regression
    # that made this test demand drkonqi.
    # Only "plasma-workspace : Depends: drkonqi" is a real unmet
    # dependency here. khelpcenter is on purge.list and appears in the
    # indented list of packages apt would have pulled in -- the old
    # blame matched any indented line and would have called it needed.
    local sample got
    sample='The following additional packages will be installed:
  khelpcenter libfoo
The following packages have unmet dependencies:
 plasma-workspace : Depends: drkonqi (>= 6.2.90~) but it is not going to be installed
E: Unable to correct problems, you have held broken packages.
E: The following information from --solver 3.0 may provide additional context:
   1. plasma-workspace:amd64=4:6.3.6-2 is selected for install
   2. plasma-workspace:amd64 Depends drkonqi (>= 6.2.90~)
      but none of the choices are installable:
      - innocent:amd64 is not selected for install'
    got=$(unmet_deps "$sample")
    if [ "$got" = $'plasma-workspace\tdrkonqi' ]; then
        echo "ok   the blame names the asker and comes from the unmet line"
    else
        echo "FAIL unmet_deps gave [$got]"; bad=1
    fi
    if grep -qE 'khelpcenter|libfoo' <<< "$got"; then
        echo "FAIL unmet_deps blames a package apt only listed"; bad=1
    else
        echo "ok   a package apt merely lists is not blamed"
    fi
    if grep -q innocent <<< "$got"; then
        echo "FAIL unmet_deps blames a package the solver only mentions"; bad=1
    else
        echo "ok   a package only mentioned in the solver trace is not blamed"
    fi

    # a tree with no archive must not look like a broken purge list
    if no_archive 'E: Unable to locate package raye-desktop' &&
       ! no_archive "$sample"; then
        echo "ok   no archive is told apart from an unmet dependency"
    else
        echo "FAIL no_archive confuses the two"; bad=1
    fi

    # the target suite comes from build.sh, and a commented SUITE= is prose
    local kept_here=$here
    mkdir -p "$t/repo"
    printf '%s\n' '#SUITE=commented-out' '# SUITE=also-prose' 'SUITE=resolute' > "$t/repo/build.sh"
    here=$t/repo
    got=$(target_suite)
    here=$kept_here
    if [ "$got" = resolute ]; then
        echo "ok   target_suite reads build.sh, never a commented SUITE="
    else
        echo "FAIL target_suite gave [$got]"; bad=1
    fi

    # An archive that is not Raye's must only warn. The wording is read
    # from a subshell; the effect on $fail has to be read in this shell,
    # because an assignment inside $( ) never comes back out.
    local kept=$APT_AUTHORITY out_w out_f
    APT_AUTHORITY=0
    out_w=$(apt_err "needs something")
    fail=0; apt_err "needs something" >/dev/null
    if [ "$fail" = 0 ] && grep -q '^note:' <<< "$out_w"; then
        echo "ok   a finding from another archive is a note, not a failure"
    else
        echo "FAIL apt_err failed on a non-Raye archive: [$out_w] fail=$fail"; bad=1
    fi
    APT_AUTHORITY=1
    out_f=$(apt_err "needs something")
    fail=0; apt_err "needs something" >/dev/null
    if [ "$fail" = 1 ] && grep -q '^FAIL:' <<< "$out_f"; then
        echo "ok   the same finding from Raye's own archive is a failure"
    else
        echo "FAIL apt_err did not fail on Raye's archive: [$out_f] fail=$fail"; bad=1
    fi
    APT_AUTHORITY=$kept; fail=0

    # The regression that cost this test its whole install simulation.
    # apt_known decides WHAT CAN BE INSTALLED; the simulation decides what
    # it is installed ONTO. Measured 2026-11-06: with apt_known reading the
    # image's populated dpkg status and the simulation reading an empty
    # one, raye-desktop looked installable and then could not be located,
    # apt said "Unable to locate package", no_archive() called that "no
    # archive" and the simulation never ran -- on four builds. A source
    # check, because the two questions agreeing is a property of the code,
    # not of any one output.
    if grep -q 'aptq apt-cache "${aptopt\[@\]}" "${APT_BASE\[@\]}" policy' "$0"; then
        echo "ok   apt_known asks about the same dpkg base the simulation uses"
    else
        echo "FAIL apt_known no longer passes APT_BASE: what can be installed and"
        echo "     what it is installed onto are two different bases again, and"
        echo "     the install simulation goes quiet instead of red"; bad=1
    fi
    if grep -q "Raye's own archive is not published yet" "$0"; then
        echo "ok   an unpublished Raye archive is a note, not a failure"
    else
        echo "FAIL the unpublished-archive path is gone: --root on a real image"
        echo "     fails on 'cannot install raye-desktop' instead of checking the"
        echo "     archive part of what Raye needs"; bad=1
    fi

    if grep -q 'if \[ ${#targets\[@\]} -eq 0 \]; then' "$0" &&
       grep -q 'DID NOT RUN, and no verdict is' "$0"; then
        echo "ok   an install simulation with no targets claims no verdict"
    else
        echo "FAIL the empty-targets guard is gone: inside a finished image apt"
        echo "     has no index, targets comes out empty, apt-get -s install with"
        echo "     no arguments succeeds, and the test says 'ok ... 0 packages'"; bad=1
    fi

    printf '%s\n' "a base one" "#staged b AP-1 two" "# c base three" "" "  d GP-2 four  " > "$t/list"
    if [ "$("$0" --names --list "$t/list")" = $'a\nd' ]; then
        echo "ok   --names prints only the lines that count"
    else
        echo "FAIL --names"; bad=1
    fi
    return "$bad"
}

# ----------------------------------------------------------------- main

case "$MODE" in
    names) active_names "$LIST"; exit 0 ;;
    self) self_test; exit $? ;;
esac

[ -f "$LIST" ] || { echo "FAIL: no $LIST"; exit 1; }
lint_list "$LIST" || fail=1

# A name on BOTH lists installs and then removes the same package: the
# build does work it undoes, and -- worse -- whichever list a reader opens
# tells them the opposite of the other. Nothing else would say so; both
# lists would be individually correct. Added 2026-11-06 when
# qemu-guest-agent joined live.list, measured zero overlap at the time, so
# this starts as a guard rather than a repair.
check_both_lists() {
    local both
    [ -f "$LIVE" ] || { err "no $LIVE, so nothing compared the two lists"; return; }
    # The sweep must prove it read something. An empty list on either
    # side makes `comm` return nothing, and a check named after an overlap
    # would pass by having had nothing to compare.
    local n_live n_purge
    n_live=$(active_names "$LIVE" | wc -l)
    n_purge=$(active_names "$LIST" | wc -l)
    [ "$n_live" -gt 0 ] || { err "$LIVE lists no package: the overlap check read nothing"; return; }
    [ "$n_purge" -gt 0 ] || { err "$LIST lists no package: the overlap check read nothing"; return; }
    both=$(comm -12 <(active_names "$LIVE" | sort -u) <(active_names "$LIST" | sort -u))
    if [ -n "$both" ]; then
        err "on BOTH live.list and purge.list, so the image installs then removes it: $(echo $both)"
    else
        echo "ok   no package is on both live.list and purge.list ($n_live live, $n_purge purged)"
    fi
}
check_both_lists
[ -f "$CONTROL" ] && check_control
if [ "$APT" = 1 ] && [ "$fail" = 0 ]; then
    check_apt
fi
if [ "$fail" = 0 ]; then
    if [ "$APT_WEAK" = 1 ]; then
        echo "ok: purge.list holds (the apt part could not speak for Raye here, see the notes)"
    else
        echo "ok: purge.list holds"
    fi
fi
exit "$fail"
