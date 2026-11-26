# SPDX-License-Identifier: GPL-3.0-or-later
"""Every automated test suite of /srv/raye, and how each one is started.

This is the data half of tools/raye-tests; the runner is the other file.
It is a table on purpose: the knowledge it holds -- that settings' shell
tests want SOURCE_DIR, that tests/test_apt_template.sh only rules on an
image when it is given --iso, that store runs each test file with
python3 -I -B -- used to live only in fourteen READMEs and ctest files,
where nothing could read it all at once.

Every entry says in `doc` WHERE its command comes from: a README line,
the add_test() that registers it, or the docstring of the test itself.
None of it is guessed. When a command here stops matching its repository,
that is a bug in this file, and `doc` says what to go and read.
"""

MANIFEST = []


def suite(name, cwd, argv, doc, needs=(), fuller=(), env=None, count=None,
          timeout=900, gate=None, plus=(), notes_on=()):
    """One invocation.

    name    <repo>/<suite>, the handle --suite takes
    cwd     relative to /srv/raye
    argv    the command, with {work} {image} {iso} {repo} filled in
    doc     where this command comes from. Never guessed: a README line,
            the ctest call, or the docstring of the test itself.
    needs   hard requirements; one missing is a named skip.
            Kinds: cmd:, font:, env:, py:, dir:, file:, iso:, image: and
            ⚠️ ok:<shell command>, run in the repository, exit 0 = met and
            its own last line is the reason when it is not. Use ok: when
            the repository knows something this table would only repeat:
            a path written here goes stale the day the repository moves
            it, and nothing says so.
    fuller  soft ones; one missing still runs, and says what the verdict
            is missing. This is the difference between a test that ran
            and a test that ran against the thing it is about.
    count   how to count what ran: pytest, unittest, qmltest, ctest,
            shell
            or None.
            Anything but None also enforces "at least one test ran".
    gate    "release" for the suites the image build alone turns on
    notes_on (pattern in the suite's own output, what it means). A green
            that says in passing that half of it could not run is a green
            that covers less than it looks like; this lifts the test's
            own sentence into the report instead of leaving it in a log.
    plus    (requirement, args when it is there, args when it is not).
            An image flag must never be built from a missing value:
            "--root None" would be read as a directory name and the
            suite would fail for a reason that is not its own.
    """
    MANIFEST.append(dict(name=name, repo=name.split("/")[0], cwd=cwd, argv=list(argv),
                         doc=doc, needs=list(needs), fuller=list(fuller),
                         env=dict(env or {}), count=count, timeout=timeout,
                         gate=gate, plus=[tuple(x) for x in plus],
                         notes_on=[tuple(x) for x in notes_on]))


def skipped(name, cwd, doc, reason):
    """A suite this launcher deliberately does not run, and why.

    It is in the manifest so that `list` shows the whole tree and the
    report names it. A suite left out of the inventory is a suite nobody
    remembers is not covered.
    """
    MANIFEST.append(dict(name=name, repo=name.split("/")[0], cwd=cwd, argv=[],
                         doc=doc, needs=[], fuller=[], env={}, count=None,
                         timeout=0, gate=None, plus=[], notes_on=[],
                         never=reason))


# The old wording was "needs a compiled build tree; this launcher never
# builds, so an image build keeps the machine". It IMPLIED that the package
# build covers these tests without ever saying so, and a vague promise is
# what let two false skip reasons stand through the night of 2026-11-06.
# ACCOUNT_NO_BUILD below already had the right shape: "say it rather than
# imply the image build does".
#
# And the first rewrite of it cited the WRONG PROOF. It said "the build
# log names 31 tests for files and 12 for apps" -- for every repository,
# settings and store and theme included. A true claim propped up by a
# neighbour's evidence is the same family of defect as the rest of this
# file: the reader checks the figure, finds it is about another repository,
# and learns nothing about this one.
#
# So the policy is one sentence and the PROOF is per repository, each read
# out of that repository's own build log, written
# on 2026-11-06. The figure quoted
# is ctest's own summary line, which is the unit dh_auto_test runs; inner
# QTest cases are many more and are not what is counted here.
#
# THIRD rewrite, 2026-11-06, and this one found the QUOTE ITSELF stale.
# Those logs were written on
# 2026-11-01 at 00:08. Most of the tests these suites are about were
# committed LATER THE SAME DAY, or after. Measured by reading the test
# names ctest printed in each log ("Start N: <name>") against what the
# repository registers today:
#
#   apps/portal-files       1 of 1
#   apps/debian-install     1 of 1
#   apps/qtest              3 of 4   sharepicker absent -- portal/qml/
#                                    CMakeLists.txt adds its tests only
#                                    if(EXISTS qml/CMakeLists.txt), and
#                                    that folder landed after the log
#   apps/taskmanager-qtest  0 of 3   taskmanager/tests/ added 2026-11-06
#   files/qtest             5 of 28  22 test_*.cpp landed 2026-11-01, 1 more 11-02
#   settings/qtest          6 of 40
#   settings/qml            1 of 1
#   store/qtest             3 of 5
#   store/qml               1 of 1
#   theme/qtest             0 of 8   shell/lib/tests/ added 2026-11-01 and
#                                    session/polkit/CMakeLists.txt 2026-11-02;
#                                    not one lib-* name is anywhere in theme2.log
#   theme/qml-ui            2 of 2
#
# So "These tests ARE run, and that run is verified" was true of the
# WIRING and FALSE of the LOG for four of the eleven, and truncated for
# three more. A count quoted with no statement of what it covers is how
# that drifted, and it is the same defect as the one above by another
# road: evidence that reads as a verdict.
#
# The two proofs are SEPARATE now, and each call site carries both:
#
#   site     the registration that a build uses -- <path>:<line>, which
#            can be checked WITHOUT building, and is: see
#            tools/tests/test_no_build_proof.py. This is what says a
#            fresh package build runs the suite.
#   covered  what the quoted log actually ran, as "covers N of M", with
#            the date of that log. This is NOT a promise about today.
_NO_BUILD = ("needs a compiled build tree, and this launcher never builds: "
             "running cmake here would take the machine from an image "
             "build. The package build (dh_auto_test -> ctest) is what "
             "runs them; the registration that does it is ")


def no_build(site, covered):
    """The policy, the WIRING that runs it, then what a log really covered.

    site     "<path>:<line>" of the add_test()/raye_add_qtest() a package
             build reaches. Checkable with no build at all, and checked:
             tools/tests/test_no_build_proof.py resolves every one of
             them and fails when a file moves out from under it.
    covered  the log evidence, and it MUST say "covers N of M". A bare
             "100% tests passed out of 11" is a figure about one build on
             one day; without N of M nobody can tell whether it is about
             this suite at all.
    """
    return _NO_BUILD + site + ". " + covered


# This cited apps.log (2026-11-01), "out of 11" -- a file that no longer
# exists, about a tree five days older than the tests it was evidence for.
# Replaced on 2026-11-07 by the image build itself, whose ctest names every
# test it ran. The eleven became EIGHTEEN, and seven of the new ones are
# tests that had never run anywhere. A chroot preflight with the image
# build's own flags gave the same 18 an hour earlier -- it was worth having
# to know the stage would pass, but it is NOT the evidence kept here: the
# citation names the build the ISO actually came out of, because that is
# the one whose failure would have stopped the release.
# The one log every <REPO>_BUILT below cites: the build that produced
# /var/tmp/raye/isos/raye-0.1-beta-20261107-amd64.iso. It is the first
# build new enough to contain every test the repositories register, and
# it is kept beside the older build logs so the citations stay
# checkable.
LOG = ("iso-build-20261107.log (2026-11-07) -- the build that produced "
       "the image -- ")

APPS_BUILT = (LOG + 'ends "100% tests passed, 0 tests '
              'failed out of 18", and its ctest names them: appstreamtest, '
              'raye-taskmanager/{proctable,endtask,efficiency}, '
              'xdg-desktop-portal-raye/{sharepicker,appidentity,'
              'pickerchoice,sharesessions,sharesessions-bus,files,'
              'sync-upstream}, build/{version,registration,po-check,'
              'app-ledger,control-ships-files,packaging,debian-install}. '
              "⚠️ One of the eighteen is worth knowing: ECM's appstreamtest "
              "validates nothing while install_manifest.txt does not exist "
              "yet, and sharesessions-bus is the sharesessions binary again "
              "under dbus-run-session. ")
FILES_BUILT = (LOG + 'ends "100% tests passed, 0 tests failed out of '
               '34", and its ctest names them: raye_test_ for addressbar, '
               'adminaccess, archive, archivejobs, archivepaths, '
               'archivewizards, archiveworker, askuser, commandbar, '
               'contextmenu, extensions, firstrun, homemodel, locationnames, '
               'navmodel, openwith, options, preview, search, share, smoke, '
               'speedsampler, titlebar, typenames, ui_controls, ui_harness, '
               'ui_tokens, viewdefaults -- the 28 test_*.cpp -- plus catalog, '
               'desktop_file, shell_guards, udev_rules, wiring and i18n. '
               '🚨 The run still starts at "Start 15": debian/rules:67 runs '
               "ctest -L raye, so fourteen UNLABELLED tests before them are "
               "deselected without a word, exactly as the 2026-11-01 log "
               "showed. The selection is what is partial, not the labelled "
               "set. ")
STORE_BUILT = (LOG + 'ends "100% tests passed, 0 tests failed out of '
               '12", and its ctest names them: appstreamtest, background, '
               'jobs, runner_index, store, windows_lib, py-extra, py-feeds, '
               'py-i18n, py-plasma_discover, py-version, qml. ')
# And the arithmetic that used to sit here was wrong, which is worth
# keeping as the worked example. It read: "theme/shell/lib/tests holds six
# tst_*.cpp today -- launcherentry is newer than that build -- so the next
# one will show one more", i.e. 13. That assumed five of the six were
# inside the 12. Measured 2026-11-06: the twelve are inputpanel-*, menus-*,
# run-*, plasmoidcheck, plasmoidload and tree, and `grep shellsettings
# theme2.log` returns ZERO -- so does updatestate, recentlyadded,
# appjumplist and launcherentry. None of the six was ever in that figure.
# theme2.log holds THREE ctest runs (style 4, qml 3, shell 12) and no
# fourth: session/polkit/CMakeLists.txt did not exist yet either.
# A figure arrived at by adding one to somebody else's total is not a
# measurement, and that is exactly what the block above was rewritten
# to stop.
THEME_BUILT = (LOG + "holds FOUR ctest runs -- style \"out of 8\", qml "
               '"out of 3", shell "out of 34", polkit "out of 3" -- all '
               "green. The fourth run is the one theme2.log (2026-11-01) "
               "could not have: session/polkit had no CMakeLists.txt yet, "
               "and the shell run has grown from 12 to 34. ")
# The best evidence of the set, and it is settings': the tests do not
# merely run, their failure STOPS THE BUILD. Measured in settings.log:
# dh_auto_test runs eight ctest entries, "Start 1: appstreamtest" (line
# 1116) through "Start 8: qml" (line 1278); one was red, so the log ends
# "88% tests passed, 1 tests failed out of 8", then "dh_auto_test: error:
# ... returned exit code 2" (line 1448) and dpkg-buildpackage failed. No
# ISO comes out of that. settings2.log is the same build once green.
# Re-measured on the 2026-11-18 build: settings gained sixteen test files and
# moved its add_test lines since the 2026-11-07 figures.
SETTINGS_BUILT = (
    "iso-build-20261118.log (2026-11-18) -- the build that produced the "
    'image -- ends "100% tests passed, 0 tests failed out of 69" (line '
    "10098), and the qml entry is Start 69 of the sixty-nine. Their "
    "failure STOPS the build: in settings.log (2026-11-01) Test #4 search was red (line "
    "1324), the run "
    'ended "88% tests passed, 1 tests failed out of 8" (1439), then '
    '"dh_auto_test: error: ... returned exit code 2" (1448) and '
    "dpkg-buildpackage failed (1450) -- re-read on 2026-11-06, line by "
    "line. So these tests gate the ISO, they do not merely run beside it. ")

# There is deliberately NO bare constant left to reach for. Every one of
# the eleven call sites names its own repository's log, and an unused
# fallback would be an invitation to cite nothing again -- which is the
# defect this whole block exists to undo. A new one needs a new
# <REPO>_BUILT line, read out of that repository's build log.
#
# And a <REPO>_BUILT constant is only half of a call site. The other
# half, "covers N of M", cannot live in a shared constant: it is about ONE
# suite, and sharing it is how apps/taskmanager-qtest came to be defended
# by a figure measured before its tests existed.

# --------------------------------------------------------------- account
# Deliberately NOT gated on cmd:cargo, and the reason matters. A
# `needs` gate would let this run the day someone installs cargo -- and
# `cargo test` COMPILES the server, which is the one thing this launcher
# promises never to do. The permanent reason is that it builds; cargo and
# the throwaway database are extras on top.
skipped("account/cargo", "account",
        "README: RAYE_ACCOUNT_TEST_DB=$(tools/dev-db.sh url) cargo test",
        "cargo test compiles the crate, so it is a build like any other "
        "(and the integration half wants a throwaway PostgreSQL in "
        "RAYE_ACCOUNT_TEST_DB). ⚠️ And no package build covers it: account "
        "has no debian/ and iso/build.sh does not build it")
# NOT no_build(), and the difference is the whole point. That one
# promises the package build covers the tests, and names the log that
# proves it. For account it does not: iso/build.sh builds
# installer, settings, store, theme, files and apps (compiled_sources())
# -- account is not among them, and the repository has no debian/ at all.
# Nothing runs these tests, anywhere. That is a known state, not a gap to
# be covered by a sentence borrowed from the suites it does not apply to.
ACCOUNT_NO_BUILD = (
    "nothing builds this: account has no debian/ and iso/build.sh does not "
    "build it (README: a prototype for after the beta, nothing online). So "
    "no build covers these tests either -- say it rather than imply the "
    "image build does")
skipped("account/qml", "account",
        "README: cmake -S client/qml -B build-qml && ctest --test-dir build-qml",
        ACCOUNT_NO_BUILD)
# The one suite of this repository that DOES run here, and it runs
# because it compiles nothing: stdlib Python over the QML and the JSON of
# the sibling settings checkout. It counts the search rows the Settings
# pages written in account still owe -- the figure ST-27 turns strict --
# and a page copy that has drifted from the one settings ships. With no
# sibling settings checkout it says so per check instead of passing
# quietly, so it is safe to run on a lone clone.
suite("account/search-anchors", "account",
      ["python3", "-I", "-B", "tests/test_search_anchors.py"],
      "tests/test_search_anchors.py docstring: python3 -I -B "
      "tests/test_search_anchors.py",
      count="shell", timeout=120)

# ------------------------------------------------------------------ apps
suite("apps/sync-upstream", "apps",
      ["sh", "portal/tests/test_sync_upstream.sh",
       "{repo}/portal/sync-upstream.sh", "{work}"],
      "portal/tests/CMakeLists.txt: add_test(<pkg>/sync-upstream)",
      count="shell", timeout=300)
# The only check in this table that runs a COMPILER, and it exists
# because nothing else here can. taskmanager/src/processmodel.cpp did not
# compile at all -- on Qt 6.8 or 6.10 -- while six static suites, 18 ctest
# checks and this table's own "11 tests passed" evidence stayed green:
# `QString(QChar(c))` where c is a plain char, under the
# QT_NO_CAST_FROM_ASCII that KDECompilerSettings sets, is a deleted
# overload. No amount of reading source as text can see that.
# It needs no build tree and no KF6: it is syntax-only, on the four
# sources that need Qt alone, and it says which file it set aside and why.
suite("apps/compile-probe", "apps",
      ["sh", "taskmanager/tests/compile_probe.sh"],
      "taskmanager/tests/compile_probe.sh header: sh "
      "taskmanager/tests/compile_probe.sh from the repository root",
      # ECM is a hard requirement, not a soft one: without the real
      # flags the probe is worth nothing, so a machine without
      # extra-cmake-modules must get a NAMED SKIP rather than a pass
      # on guessed flags.
      needs=["cmd:g++", "cmd:pkg-config",
             "file:/usr/share/ECM/kde-modules/KDECompilerSettings.cmake",
             "ok:pkg-config --exists Qt6Core Qt6Gui Qt6Qml"],
      count="shell", timeout=300)
suite("apps/cmake-version", "apps",
      ["cmake", "-DWORK={work}", "-P", "cmake/tests/test_version.cmake"],
      "tests/CMakeLists.txt: add_test(build/version)", count="shell", timeout=300)
suite("apps/cmake-po-check", "apps",
      ["cmake", "-DWORK={work}", "-DSCRIPT={repo}/cmake/RayeCheckPo.cmake",
       "-P", "cmake/tests/test_po_check.cmake"],
      "tests/CMakeLists.txt: add_test(build/po-check)",
      count="shell", timeout=300)
skipped("apps/portal-files", "apps",
        "portal/tests/CMakeLists.txt: add_test(<pkg>/files), fed the build folder",
        no_build("apps/portal/tests/CMakeLists.txt:20",
                 APPS_BUILT + "It covers 1 of 1: the log's "
                 "xdg-desktop-portal-raye/files IS this suite.")
        + " (it is handed ${CMAKE_BINARY_DIR}/portal/data)")
# This was skipped for "it configures and compiles small trees of its
# own" -- an argument of COST, and the cost was never measured. Measured
# 2026-11-06, with the same arguments ctest passes: 8.0 s and 3 MB, exit 0,
# nothing written inside the repository (it builds its fixtures under
# {work}). It needs NO build tree: it makes its own, which is why the skip
# reason was not even about a build tree.
#
# And the skip was hiding RED, not emptiness: the suite was failing with 12
# real failures until apps 536f68f. That makes it the worst of the three
# unjustified skips of that night -- the other two hid nothing.
#
# The Qt gate is an `ok:` probe, not a `cmd:`: what the test needs is the
# Qt6 Core+Test CMake package, and no single binary stands for it (moc is
# not even on this machine while the package is).
#
# And the OBVIOUS probes are wrong. Measured 2026-11-06 on a machine
# where build/packaging passes in 8.0 s: both
# `cmake --find-package -DNAME=Qt6 -DMODE=EXIST` and a real
# `find_package(Qt6 COMPONENTS Core Test)` inside `cmake -P` exit 1 --
# script mode has no project context, so Qt6's config package is not
# found. Either one would skip a suite that runs perfectly, which is the
# same false negative this launcher keeps being bitten by. Asking qmake6
# where Qt's libraries are, and looking for the Qt6Test config package
# there, is the probe that answers: no path is written here, Qt says it.
suite("apps/cmake-packaging", "apps",
      ["cmake", "-DWORK={work}", "-DRAYE_CMAKE_DIR={repo}/cmake",
       "-DGENERATOR=Unix Makefiles", "-DWITH_QT=ON",
       "-P", "cmake/tests/test_packaging.cmake"],
      "tests/CMakeLists.txt: add_test(build/packaging), with -DWITH_QT=ON "
      "and the generator of the parent build",
      needs=["cmd:cmake", "cmd:make", "cmd:g++", "cmd:msgunfmt", "cmd:qmake6",
             "ok:d=$(qmake6 -query QT_INSTALL_LIBS) && [ -d \"$d/cmake/Qt6Test\" ] || "
             "{ echo 'the Qt6 Test CMake package is not installed "
             "(qt6-base-dev), and build/packaging configures with "
             "-DWITH_QT=ON'; exit 1; }"],
      count="shell", timeout=900)
# Not counted, and declared so in tools/tests/test_counts_declared.py:
# it prints "-- registration: 10 test files, all registered", which none of
# the shell counters match. Giving it count="shell" would fail a green
# suite.
suite("apps/registration", "apps",
      ["cmake", "-DSRC={repo}", "-P", "cmake/tests/test_registration.cmake"],
      "tests/CMakeLists.txt: add_test(build/registration) -- only -DSRC",
      needs=["cmd:cmake"], timeout=300)
# This said three, and `grep -rn raye_add_qtest apps/` says FOUR: the
# fourth, sharepicker, is registered a directory away in
# portal/qml/tests/CMakeLists.txt and was simply never looked for. The
# build also runs two add_test() entries that are not qtests at all:
# sharesessions-bus (the same binary under dbus-run-session, only when
# dbus-run-session is found) and appstreamtest.
#
# appstreamtest is named here with what it is worth, because a green
# that measures nothing is worse than an absence. ECM's
# KDECMakeSettings.cmake adds it to EVERY build whenever appstreamcli is
# installed, and appstreamtest.cmake reads
# ${CMAKE_BINARY_DIR}/install_manifest.txt -- a file that `make install`
# writes, so it does not exist while dh_auto_test runs. Measured
# 2026-11-06: it prints "Not installed yet, skipping", validates nothing
# and exits 0. (The one AppStream file in the tree,
# files/src/org.kde.dolphin.appdata.xml, is in another repository and would
# not be reached either, for the same reason.)
skipped("apps/qtest", "apps",
        "portal/tests/CMakeLists.txt: raye_add_qtest(appidentity, pickerchoice, "
        "sharesessions) and portal/qml/tests/CMakeLists.txt: "
        "raye_add_qtest(sharepicker) -- four, plus sharesessions-bus "
        "(dbus-run-session) and ECM's appstreamtest, which validates nothing "
        "during dh_auto_test: install_manifest.txt does not exist yet",
        no_build("apps/portal/tests/CMakeLists.txt:3 and "
                 "apps/portal/qml/tests/CMakeLists.txt:16",
                 APPS_BUILT + "It covers 4 of 4. ⚠️ And the fourth is the "
                 "one worth saying: sharepicker was absent from the "
                 "2026-11-01 log, not because it failed but because it did "
                 "not exist -- apps/portal/CMakeLists.txt:43 sets "
                 "RAYE_PORTAL_PICKER only if(EXISTS .../qml/CMakeLists.txt) "
                 "and :55 adds qml/ behind that flag, and the folder was "
                 "committed after that log. The 2026-11-07 build runs it: "
                 "\"Start 5: xdg-desktop-portal-raye/sharepicker\"."))
# apps builds more than the portal, and apps/qtest above names only the
# portal's. These three are registered by apps/taskmanager/tests/
# CMakeLists.txt:12-21 and belong to another package in the same repository,
# so they get their own entry rather than a longer sentence in that one.
skipped("apps/taskmanager-qtest", "apps",
        "apps/taskmanager/tests/CMakeLists.txt: raye_add_qtest(proctable, "
        "endtask, efficiency)",
        no_build("apps/taskmanager/tests/CMakeLists.txt:12",
                 APPS_BUILT + "It covers 3 of 3, and that is new. 🚨 Until "
                 "2026-11-07 it covered 0 of 3: taskmanager/tests/ was "
                 "committed on 2026-11-06, five days after the log this "
                 "entry used to cite, and proctable, endtask and efficiency "
                 "appeared nowhere in it -- the wiring was sound and no "
                 "build had ever reached it. The build of 2026-11-07 runs "
                 "all three (\"Start 2/3/4: raye-taskmanager/...\"), which "
                 "is the first time these tests have run anywhere."))
skipped("apps/debian-install", "apps",
        "tests/CMakeLists.txt: add_test(build/debian-install), fed ${CMAKE_BINARY_DIR}",
        no_build("apps/tests/CMakeLists.txt:44",
                 APPS_BUILT + "It covers 1 of 1: build/debian-install IS "
                 "in the log. ⚠️ And the two that used to be missing from "
                 "it, build/registration and build/app-ledger, are in the "
                 "2026-11-07 build as Start 13 and Start 15 -- the second "
                 "was simply newer than the log this entry used to cite."))

# --------------------------------------------------------------- desktop
suite("desktop/built-debs", "desktop", ["bash", "tests/test_built_debs.sh"],
      "tests/test_built_debs.sh header: the folder of .deb (default "
      "/var/tmp/raye/desktop-debs); skips with 77 when it is absent",
      needs=["cmd:dpkg-deb"], count="shell", timeout=300)
# Thirty of these tests read the Ubuntu source the patch series is
# applied to. They used to ask for RAYE_DESKTOP_SRC, which nobody set, so
# the thirty skipped on every run; desktop/fetch-sources.sh now gets the
# source without building anything and the tests find it by themselves.
# The requirement asks the REPOSITORY whether it has them -- a path
# written here would go stale the day the repository moves it.
suite("desktop/tests", "desktop", ["python3", "-m", "pytest", "-q",
                                   "-p", "no:cacheprovider", "tests/"],
      "tests/conftest.py: ./fetch-sources.sh && pytest tests/",
      fuller=["ok:./fetch-sources.sh --have"], count="pytest", timeout=900)

# ----------------------------------------------------------------- files
FILES_ENV = {"RAYE_FILES_SOURCE_DIR": "{repo}"}
suite("files/catalog", "files", ["sh", "tests/raye/test_catalog.sh"],
      "tests/raye/CMakeLists.txt: add_test(raye_test_catalog), "
      "RAYE_FILES_SOURCE_DIR from the environment",
      needs=["cmd:msgcmp"], env=FILES_ENV, count="shell", timeout=300)
# count="shell" was MISSING here while both sibling suites had it, so
# the report printed no figure at all for a suite that does two real
# checks and says so ("ok: 2 checks, 0 failed"). counts() returns None
# whatever the output when `how` is None -- the word is the whole fix.
suite("files/desktop-file", "files", ["sh", "tests/raye/test_desktop_file.sh"],
      "tests/raye/CMakeLists.txt: add_test(raye_test_desktop_file)",
      needs=["cmd:desktop-file-validate"], env=FILES_ENV, count="shell",
      timeout=300)
# Both registered by the file(GLOB test_*.sh) loop of
# tests/raye/CMakeLists.txt, as raye_test_shell_guards and raye_test_wiring.
suite("files/shell-guards", "files", ["sh", "tests/raye/test_shell_guards.sh"],
      "tests/raye/CMakeLists.txt: file(GLOB test_*.sh) -> "
      "add_test(raye_test_shell_guards)",
      env=FILES_ENV, count="shell", timeout=300)
suite("files/wiring", "files", ["sh", "tests/raye/test_wiring.sh"],
      "tests/raye/CMakeLists.txt: file(GLOB test_*.sh) -> "
      "add_test(raye_test_wiring)",
      env=FILES_ENV, count="shell", timeout=300)
suite("files/udev-rules", "files", ["sh", "tests/raye/test_udev_rules.sh"],
      "tests/raye/CMakeLists.txt: add_test(raye_test_udev_rules)",
      fuller=["cmd:udevadm"], env=FILES_ENV, count="shell", timeout=300)
skipped("files/qtest", "files",
        "README: ctest --test-dir build -L raye; tests/raye/test_*.cpp (QtTest)",
        no_build("files/tests/raye/CMakeLists.txt:32",
                 FILES_BUILT + "✅ It covers 28 of 28: every "
                 "tests/raye/test_*.cpp is named in that run. The glob at "
                 "line 29 and LABELS raye at line 48 do what they promise. "
                 "⚠️ The figure this entry carried until 2026-11-07 was "
                 "\"5 of 28\", and it was true of the log it cited: that "
                 "build predated twenty-three of the files. A coverage "
                 "citation goes stale by the repository growing, not by the "
                 "wiring breaking -- so it is re-measured against the newest "
                 "build, never carried forward."))

# -------------------------------------------------------------- handbook
suite("handbook/version", "handbook", ["python3", "-I", "-B", "tests/test_version.py"],
      "tests/test_version.py docstring: python3 -I -B tests/test_version.py",
      count="shell", timeout=120)
# handbook declared ONE command, so this file was reached only because
# test_version.py imports its siblings by hand (its SIDECARS tuple). That is
# a workaround, not a registration: a second sidecar nobody adds to that
# tuple would never run, and the report would still look complete. It is a
# suite of its own now, and it runs standalone -- measured 2026-11-06,
# `python3 -I -B tests/test_promises.py` is green on its own.
suite("handbook/promises", "handbook", ["python3", "-I", "-B", "tests/test_promises.py"],
      "tests/test_promises.py docstring, and it runs standalone: "
      "python3 -I -B tests/test_promises.py",
      count="shell", timeout=120)

# ------------------------------------------------------------- installer
suite("installer/python", "installer",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
       "tests", "debian/test_raye_paths.py"],
      "CMakeLists.txt: add_test(python)", count="pytest", timeout=600)
# A RED HERE IS THE POINT, not a defect, and the report has to say so
# or the next reader spends an evening on it. debian/raye-paths marks
# every file whose part is not written yet with a leading "?", and
# RAYE_PATHS_STRICT=1 turns those marks into errors. It is a to-do list
# with teeth: it goes green when the installer is finished, and until
# then the number of lines it prints is a completeness figure, not a
# breakage. 12 of them on 2026-11-06, 11 later that day, 10 on
# 2026-11-07 -- and the eleventh was never owed: see the OWED block of
# installer/debian/test_raye_paths.py.
suite("installer/paths-strict", "installer",
      ["python3", "debian/raye_paths.py", "check"],
      "CMakeLists.txt: add_test(paths-strict), only if(RAYE_RELEASE) -- "
      "it is MEANT to be red until every '?' in debian/raye-paths is "
      "written: read the count, not the colour. 10 of them on 2026-11-07, "
      "down from 11 because one marker was stale. \u26a0\ufe0f And read the "
      "NOT JUDGED HERE lines separately from the errors: a source under "
      "debian/tmp is a BUILD OUTPUT, so outside a package build this gate "
      "cannot see it at all -- until 2026-11-07 it called those missing, "
      "which is an error about its own working conditions dressed up as an "
      "answer about the tree",
      env={"RAYE_PATHS_STRICT": "1"}, gate="release", timeout=300)
# This was a static skip reading "qmltestrunner is not installed, and
# the module has to be laid out by the build first". HALF of that was
# never true: tests/ui/stage-module.sh lays org.raye.setup out exactly as
# the package installs it, with no build at all. The other half stopped
# being true the day qmltestrunner was installed -- and nothing re-read
# the sentence. 22 tests, green in 1.8 s the first time they were run.
suite("installer/ui-qml", "installer", ["sh", "tests/ui/run-tests.sh"],
      "tests/ui/CMakeLists.txt: add_test(qml-setup); "
      "tests/ui/run-tests.sh runs the same thing without a build",
      count="qmltest", timeout=600)

# ------------------------------------------------------------------- iso
suite("iso/apt-sources", "iso", ["bash", "tests/test_apt_sources.sh"],
      "tests/test_apt_sources.sh header: --root DIR asks the apt of the image tree",
      fuller=["image"], plus=[("image", ["--root", "{image}"], [])],
      count="shell", timeout=900)
suite("iso/apt-template", "iso", ["bash", "tests/test_apt_template.sh"],
      "tests/test_apt_template.sh header: --iso FILE questions a built ISO",
      fuller=["iso"],
      plus=[("iso", ["--iso", "{iso}"], ["--no-image"])],
      count="shell", timeout=900)
# This one used to be repository-only, and that cost a false green for
# four builds. It reads the modules of the signed CD GRUB, and it read the
# copy installed on THIS machine -- a different build from the one build.sh
# puts on the ISO. The test now prefers the image's copy ($RAYE_ROOT, which
# this launcher sets), and without an image it says the module verdict is
# missing instead of inventing one. --iso adds the ISO's own name and
# volume label, which only the finished artefact carries.
# The release people read: VERSION and release-names, written everywhere it
# shows by tools/release_name.py (os-release, Raye Setup, the publish
# title). Reads the sibling installer, settings, store and handbook too.
suite("iso/release-name", "iso", ["python3", "-I", "-B", "tests/test_release_name.py"],
      "tests/test_release_name.py docstring: python3 -I -B tests/test_release_name.py",
      count="unittest", timeout=120)
suite("iso/boot-menu", "iso", ["bash", "tests/test_boot_menu.sh"],
      "tests/test_boot_menu.sh header: --root DIR also questions the image, "
      "--iso FILE its name and volume label",
      fuller=["image", "iso"], plus=[("iso", ["--iso", "{iso}"], [])],
      notes_on=[("the module verdict is MISSING",
                 "the modules were read from this machine's signed GRUB, not "
                 "the image's: grub.cfg was checked against the wrong binary "
                 "and no verdict was reached"),
                ("no image questioned",
                 "the version was checked in the files the repository packages, "
                 "not in a built image")],
      count="shell", timeout=300)
# Only the finished image holds every .desktop file of the desktop, so the
# repository cannot answer this at all on its own -- without an image the
# suite says so and rules on nothing.
suite("iso/menu-brands", "iso", ["bash", "tests/test_menu_brands.sh"],
      "tests/test_menu_brands.sh header: --root DIR questions the image tree",
      fuller=["image"],
      notes_on=[("the repository cannot answer this on its own",
                 "no image, so the Start menu was not read: foreign-brand "
                 "entries were neither confirmed nor counted")],
      count="shell", timeout=300)
suite("iso/build-memoire", "iso", ["bash", "tests/test_build_memoire.sh"],
      "tests/test_build_memoire.sh header: everything", count="shell", timeout=300)
suite("iso/build-pty", "iso", ["bash", "tests/test_build_pty.sh"],
      "tests/test_build_pty.sh header: everything", count="shell", timeout=300)
suite("iso/desktop-pool-dns", "iso", ["bash", "tests/test_desktop_pool_dns.sh"],
      "tests/test_desktop_pool_dns.sh header: everything", count="shell", timeout=300)
suite("iso/prefer-published", "iso", ["bash", "tests/test_prefer_published.sh"],
      "tests/test_prefer_published.sh header: everything", count="shell", timeout=300)
suite("iso/desktop-debs", "iso", ["bash", "tests/test_desktop_debs.sh"],
      "tests/test_desktop_debs.sh header: everything", count="shell", timeout=300)
suite("iso/wine-debs", "iso", ["bash", "tests/test_wine_debs.sh"],
      "tests/test_wine_debs.sh header: everything", count="shell", timeout=300)
# Registered the day it was written, because the defect it guards made the
# image UNBUILDABLE and pointed nowhere: build.sh exported GNUPGHOME to the
# owner's key home, which does not exist on a build machine, and gpg refuses
# to start on a GNUPGHOME that is not there -- so every gpg in every package
# build failed, and what went red was raye-update's keyring tests.
suite("iso/signing-env", "iso", ["bash", "tests/test_signing_env.sh"],
      "tests/test_signing_env.sh header: everything", count="shell", timeout=300)
suite("iso/raye-kernel-in-image", "iso", ["bash", "tests/test_raye_kernel_in_image.sh"],
      "tests/test_raye_kernel_in_image.sh header: everything", count="shell", timeout=60)
suite("iso/kernel-pin", "iso", ["bash", "tests/test_kernel_pin.sh"],
      "tests/test_kernel_pin.sh header: --root DIR also checks the image",
      fuller=["image"], plus=[("image", ["--root", "{image}"], [])],
      count="shell", timeout=300)
suite("iso/french-session", "iso", ["bash", "tests/test_french_session.sh"],
      "tests/test_french_session.sh header: --root DIR questions the image tree",
      fuller=["image"], plus=[("image", ["--root", "{image}"], [])],
      count="shell", timeout=120)
suite("iso/purge", "iso", ["bash", "tests/test_purge.sh"],
      "tests/test_purge.sh header: --root DIR runs apt inside the image tree",
      fuller=["image"], plus=[("image", ["--root", "{image}"], [])],
      # The old note said "the image carries no archive", which was the
      # wrong diagnosis: the image carries no apt INDEX (build.sh:465
      # empties /var/lib/apt/lists), and Raye's own archive is not
      # published. Both are now said by the test itself; this lifts the
      # sentence that matters into the report.
      notes_on=[("DID NOT RUN, and no verdict is",
                 "apt inside the image has no package index, so the install "
                 "simulation -- the part that proves purging takes nothing "
                 "else along -- did not run. `chroot <tree> apt-get update` "
                 "first makes it reachable: measured 2026-11-06, it then "
                 "checks 205 packages and passes with Recommends off (1556) "
                 "and on (1968)"),
                ("Raye's own archive is not published yet",
                 "raye-desktop cannot be installed because dl.rayelinux.com "
                 "does not resolve and raye-linux.github.io/packages answers "
                 "404, so the archive part of what Raye needs is checked "
                 "instead")],
      count="shell", timeout=1200)
suite("iso/tools", "iso",
      ["python3", "-B", "-m", "unittest", "discover", "-s", "tools/tests"],
      "tools/tests/test_publish_repo.py docstring: "
      "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests",
      needs=["cmd:dpkg-deb", "cmd:apt-ftparchive", "cmd:apt-get",
             "cmd:gpg", "cmd:gpgv"], count="unittest", timeout=1200)
suite("iso/bench", "iso/tools/bench", ["python3", "-B", "test_raye_bench.py"],
      "tools/bench/test_raye_bench.py docstring: python3 test_raye_bench.py",
      count="unittest", timeout=300)

RB = "iso/packages/raye-base"
suite("iso/raye-base-python", RB,
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider",
       "debian/test_raye_release.py", "release/apt/tests", "release/grub/tests",
       "release/updates/tests", "release/recovery/tests"],
      "debian/rules: override_dh_auto_test", count="pytest", timeout=600)
suite("iso/raye-base-tpm", RB,
      ["python3", "-I", "-B", "-m", "unittest", "discover", "-s", "release/tpm/tests"],
      "debian/rules: python3 -B -m unittest discover -s release/tpm/tests",
      count="unittest", timeout=600)
# "image" is not a nicety here: one check asks which Wine THE IMAGE
# ships and compares it against raye-wine-addons/versions.txt, reading the
# image's own dpkg under RAYE_ROOT. It used to ask the machine running the
# tests -- the wrong machine -- and so skipped on every run, silently,
# inside a green suite. Without an image the run names the partial verdict.
suite("iso/raye-base-windows", RB,
      ["python3", "-I", "-B", "-m", "unittest", "discover",
       "-s", "release/windows/tests"],
      "release/windows/tests/*.py docstring: "
      "python3 -I -m unittest discover -s release/windows/tests",
      fuller=["image"], count="unittest", timeout=900)
suite("iso/raye-base-crash", RB,
      ["python3", "-I", "-B", "-m", "unittest", "discover", "-s", "release/crash/tests"],
      "release/crash/tests/test_crash_notice.py docstring", count="unittest", timeout=600)
suite("iso/raye-base-skel", RB,
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "release/skel/tests"],
      "release/skel/tests/test_first_desktop.py docstring", count="pytest", timeout=600)
suite("iso/raye-base-tuning-files", RB, ["sh", "tests/test_tuning.sh"],
      "tests/test_tuning.sh header: tests/test_tuning.sh (from anywhere)",
      count="shell", timeout=300)
for _n, _p in (("laptop-wake", "release/tuning/tests/test-laptop-wake.sh"),
               ("vm-cursor", "release/tuning/tests/test-raye-vm-cursor.sh"),
               ("start-if-needed", "release/tuning/tests/test-raye-start-if-needed.sh"),
               ("update-grub", "release/grub/tests/test-raye-update-grub.sh"),
               ("fsck-message", "release/fsck/tests/test-raye-fsck-message.sh"),
               ("kernel-setup", "release/kernel/tests/test-raye-kernel-setup.sh")):
    suite("iso/raye-base-" + _n, RB, ["sh", _p],
          "debian/rules, or the script's own header: sh " + _p,
          count="shell", timeout=300)
suite("iso/scx", "iso/packages/raye-scx",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
      "tests/test_fetch_scx.py docstring: run by the package build (pytest)",
      count="pytest", timeout=600)
suite("iso/wine-addons", "iso/packages/raye-wine-addons",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
      "tests/test_fetch_addons.py docstring (pytest)", count="pytest", timeout=600)

# ---------------------------------------------------------------- kernel
suite("kernel/art", "kernel",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "art/"],
      "README: python3 -m pytest art/",
      fuller=["py:PIL", "font:Inter", "dir:../theme"], count="pytest", timeout=600)
# Nine of these read the kernel source -- eleven files, not a tree.
# They asked for RAYE_KERNEL_TREE, nobody set it, and the nine skipped on
# every run; kernel/fetch-sources.sh fetches those eleven files at the
# Ubuntu tag and the tests find them by themselves. The requirement asks
# the REPOSITORY, which is the side that knows where they go.
suite("kernel/tests", "kernel",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/"],
      "README: ./fetch-sources.sh <version> && python3 -m pytest tests/",
      needs=["cmd:patch"], fuller=["ok:./fetch-sources.sh --have"],
      count="pytest", timeout=900)

# -------------------------------------------------------------- settings
SET_ENV = {"SOURCE_DIR": "{repo}", "LANGUAGE": "en"}
for _n in ("version", "storage-clean", "reset-settings"):
    suite("settings/" + _n, "settings",
          ["sh", "tests/test_%s.sh" % _n.replace("-", "_")],
          "CMakeLists.txt: add_test(%s), SOURCE_DIR and BUILD_DIR in the "
          "environment" % _n.replace("-", "_"),
          env=SET_ENV, count="shell", timeout=300)
skipped("settings/qtest", "settings",
        "CMakeLists.txt: the test-<name> QtTest programs",
        no_build("settings/CMakeLists.txt:256",
                 SETTINGS_BUILT + "✅ It covers 56 of 56: Start 2 "
                 "accessibility through Start 57 windowsdebug are exactly "
                 "the fifty-six test_*.cpp of tests/, and Starts 58-68 "
                 "(autologin through version) are the shell entries beside "
                 "them. The FATAL_ERROR at line 241 stops a build whose "
                 "glob goes empty, so the fifty-six cannot quietly become "
                 "fewer."))
skipped("settings/qml", "settings",
        "CMakeLists.txt: add_test(qml) -- raye-settings --check-qml",
        no_build("settings/CMakeLists.txt:271",
                 SETTINGS_BUILT + "It covers 1 of 1: \"Start 69: qml\" "
                 "IS this suite, and it is the best-evidenced entry of the "
                 "whole set."))

# ----------------------------------------------------------------- store
for _n in ("extra", "feeds", "plasma_discover", "version"):
    suite("store/" + _n.replace("_", "-"), "store",
          ["python3", "-I", "-B", "tests/test_%s.py" % _n],
          "CMakeLists.txt: add_test(py-%s) -- python3 -I -B tests/test_%s.py"
          % (_n, _n), count="unittest", timeout=300)
skipped("store/qtest", "store", "CMakeLists.txt: the test_*.cpp programs",
        no_build("store/CMakeLists.txt:236",
                 STORE_BUILT + "✅ It covers 5 of 5: background, jobs, "
                 "runner_index, store and windows_lib are the five "
                 "test_*.cpp, and all five are in that run. ✅ And the five "
                 "test_*.py the same block registers are all there too "
                 "(py-extra, py-feeds, py-i18n, py-plasma_discover, "
                 "py-version) -- the 2026-11-01 log had two of them."))
skipped("store/qml", "store",
        "CMakeLists.txt: add_test(qml) -- raye-store --check-qml",
        no_build("store/CMakeLists.txt:251",
                 STORE_BUILT + "It covers 1 of 1: \"Start 12: qml\" IS "
                 "this suite."))

# ----------------------------------------------------------------- theme
for _n, _path, _doc in (
        ("tokens", "tokens/", "tokens/test_tokens.py docstring: python3 -m pytest tokens/"),
        ("tests", "tests/", "tests/*/*.py docstrings: python3 -m pytest -q tests/..."),
        ("art", "art/", "art/*.py docstrings: python3 -m pytest art/..."),
        ("grub", "grub/tests/", "grub/tests/test_grub_theme.py docstring")):
    # "art" alone asks for the image, and not as a nicety: 18 of its
    # checks compare Raye's Plasma style names against PLASMA'S OWN, which
    # it reads under RAYE_ROOT. On the build machine there is no Plasma, and putting
    # Debian's there would mean 203 packages and system services on the
    # machine that drives the lab -- for the wrong reference anyway, since
    # Debian ships 6.3 and Raye is built on Ubuntu's 6.6. The image carries
    # the right one. Without an image the run says so by name instead of
    # quietly skipping 18 checks inside a green suite.
    suite("theme/" + _n, "theme",
          ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", _path],
          _doc, count="pytest", timeout=1200,
          fuller=["image"] if _n == "art" else [])
suite("theme/taskbarsync-pins", "theme",
      ["python3", "-I", "-B", "shell/taskbarsync/tests/test_pins.py"],
      "shell/taskbarsync/tests/CMakeLists.txt", count="unittest", timeout=300)
suite("theme/style-check-names", "theme",
      ["python3", "-I", "-B", "style/cmake/test_check_names.py"],
      "style/cmake/test_check_names.py: tests of check_names.py",
      count="unittest", timeout=300)
suite("theme/style-import-upstream", "theme",
      ["python3", "-I", "-B", "style/cmake/test_import_upstream.py"],
      "style/cmake/test_import_upstream.py: tests of import_upstream.py",
      count="unittest", timeout=300)
suite("theme/tray-defaults", "theme", ["sh", "session/tests/test_tray_defaults.sh"],
      "session/tests/test_tray_defaults.sh header",
      needs=["cmd:qml6"], count="shell", timeout=300)
suite("theme/fonts", "theme", ["sh", "tests/test_fonts.sh"],
      "tests/test_fonts.sh header: the files of this repo",
      needs=["font:Inter", "font:Inter Display", "font:Cascadia Mono"],
      count="shell", timeout=300)
suite("theme/run-shortcut-update", "theme",
      ["sh", "shell/run/tests/tst_shortcut_update.sh",
       "{repo}/shell/run/data/raye-run-shortcut.sh"],
      "shell/run/tests/CMakeLists.txt: add_test(run-shortcut-update), "
      "SKIP_RETURN_CODE 77",
      needs=["cmd:kreadconfig6", "cmd:kwriteconfig6"], timeout=300)
# This used to be a no-build skip, and that reason was FALSE here: it
# promises the package build covers the tests. theme/debian/rules builds style, qml, shell and
# session/polkit -- tools/gallery is not in RAYE_TREES and is part of no
# package, so NOTHING built it and nothing ran its FOUR ctest tests:
# options, scheme, pages (23 QtTest cases) and shoot, the Xvfb capture of
# every page. Measured 2026-11-06, their first run ever: all four pass.
# The repository now answers whether a tree is built, and names the two
# cmake lines when it is not.
suite("theme/gallery", "theme", ["sh", "tools/gallery/run-tests.sh"],
      "tools/gallery/run-tests.sh: ctest over a tree you built yourself "
      "(options, scheme, pages, shoot)",
      needs=["ok:sh tools/gallery/run-tests.sh --have"],
      count="ctest", timeout=600)
# shell/ and session/polkit/ only. The tst_*.cpp of tools/gallery are
# NOT covered by any build either -- they are the theme/gallery suite
# above, which runs them against a tree you build by hand.
skipped("theme/qtest", "theme",
        "the tst_*.cpp of shell/ and session/polkit/ (QtTest) -- "
        "shell/lib/tests/CMakeLists.txt:23 registers six: shellsettings, "
        "updatestate, recentlyadded, components, appjumplist, launcherentry",
        no_build("theme/shell/lib/tests/CMakeLists.txt:34 and "
                 "theme/session/polkit/CMakeLists.txt:62",
                 THEME_BUILT + "✅ It covers 8 of 8, and they ran for "
                 "the FIRST time in that build: lib-shellsettings, "
                 "lib-updatestate, lib-recentlyadded, lib-components, "
                 "lib-appjumplist and lib-launcherentry are Starts 9-14 of "
                 "the shell run, and polkit's appinfo and request are Starts "
                 "1-2 of the fourth run (with tst_prompt.qml as Start 3). "
                 "🚨 This entry read \"covers 0 of 8\" until 2026-11-07, and "
                 "that was right: shell/lib/tests/ was committed on "
                 "2026-11-01 and session/polkit/CMakeLists.txt on 11-02, "
                 "both AFTER the log then cited. The wiring was sound all "
                 "along (theme/shell/lib/CMakeLists.txt:82 adds tests under "
                 "BUILD_TESTING; debian/rules:35 has shell and "
                 "session/polkit in RAYE_TREES and :43 passes "
                 "-DBUILD_TESTING=ON) -- what was missing was a build new "
                 "enough to prove it."))
# These four were ONE line of this table until 2026-11-06:
#     skipped("theme/qml", ..., "qmltestrunner is not installed")
# a frozen string that no code re-evaluated. Installing qmltestrunner did
# not change it, and nothing else ran them either -- no CMakeLists
# registered lockscreen/, sddm/ or signin/, so the package build never
# touched them. 355 tests, every one green the first time they were run.
# They are suites now: each script finds the runner (Debian keeps it off
# PATH, Ubuntu on it) and exits 77 with its own reason when there is none,
# so the skip is MEASURED at every run instead of written down once.
suite("theme/qml-lockscreen", "theme", ["sh", "lockscreen/tests/run-tests.sh"],
      "lockscreen/tests/run-tests.sh header",
      count="qmltest", timeout=600)
suite("theme/qml-sddm", "theme", ["sh", "sddm/tests/run-tests.sh"],
      "sddm/tests/run-tests.sh header",
      count="qmltest", timeout=600)
suite("theme/qml-signin", "theme", ["sh", "signin/tests/run-tests.sh"],
      "signin/tests/run-tests.sh header",
      count="qmltest", timeout=900)
suite("theme/qml-polkit", "theme", ["sh", "session/polkit/tests/run-tests.sh"],
      "session/polkit/CMakeLists.txt: add_test(prompt)",
      count="qmltest", timeout=600)
suite("theme/find-qmltestrunner", "theme",
      ["sh", "tests/test_find_qmltestrunner.sh"],
      "tests/test_find_qmltestrunner.sh header",
      count="shell", timeout=120)
# raye-ui is NOT in the list above, and that is the honest line: its
# tests load the compiled plugin out of ${CMAKE_BINARY_DIR}/qml, so they
# cannot run without a build. The other four take org.raye.signin straight
# from the repository, which is why they can.
skipped("theme/qml-ui", "theme",
        "qml/CMakeLists.txt: add_test(raye-ui), add_test(raye-ui-source) -- "
        "qmltestrunner on tests/qml/tst_raye_ui.qml",
        no_build("theme/qml/CMakeLists.txt:76",
                 THEME_BUILT + "It covers 2 of 2: the qml run's three are "
                 "appstreamtest, raye-ui and raye-ui-source -- unchanged "
                 "between the 2026-11-01 and 2026-11-07 builds. ⚠️ And it "
                 "cannot silently stop being registered: line 64 finds "
                 "qmltestrunner with REQUIRED, so an absent runner fails "
                 "the configure instead of dropping the tests -- measured "
                 "2026-11-06, exit 1 with REQUIRED against exit 0 and a "
                 "green ctest without it.")
        + " (the plugin comes from ${CMAKE_BINARY_DIR}/qml)")

# ---------------------------------------------------------------- update
suite("update/tests", "update",
      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
      "tests/conftest.py and the test docstrings (pytest)",
      count="pytest", timeout=600)

# --------------------------------------------------------------- website
suite("website/backend", "website/backend",
      ["python3", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
      "README: cd backend && python3 -m unittest discover -s tests -t tests",
      needs=["cmd:openssl"], count="unittest", timeout=900)
# The suite above proves the download page matches tools/release.json.
# It proves NOTHING about release.json matching the image. Both can be
# stale together, and on 2026-11-06 they were: the page carried a
# checksum and a size for an image 49 MB smaller than the one that would
# have been handed out, and the suite was green, because page and cache
# agreed with each other.
#
# A release gate, like installer/paths-strict, and for the same reason:
# a checksum is a publication concern. It would be noise on every
# ordinary run and it is a refusal on the run that matters. RAYE_ISO is
# passed only here, so the test names itself as a skip elsewhere.
suite("website/release-json", "website/backend",
      ["python3", "-B", "-m", "unittest", "tests.test_site",
       "-k", "release_json"],
      "backend/tests/test_site.py: "
      "test_release_json_describes_the_iso_it_will_publish -- it is MEANT "
      "to be red while tools/release.json is older than the image: the "
      "remedy is in the failure, tools/build_pages.py --release",
      env={"RAYE_ISO": "{iso}"}, fuller=["iso"], gate="release",
      count="unittest", timeout=600)

# ------------------------------------------------------------------ wine
suite("wine/tree", "wine",
      ["python3", "-I", "-B", "-m", "unittest", "discover", "-s", "tests"],
      "tests/test_tree.py docstring: python3 -I -m unittest discover -s tests",
      count="unittest", timeout=600)


