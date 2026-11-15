# SPDX-License-Identifier: GPL-3.0-or-later
"""Every debian/rules that runs ctest must refuse an empty ctest run.

    python3 -I -B -m unittest discover -s tools/tests

🚨 `ctest` prints "No tests were found!!!" and exits **0**. Measured in the
resolute chroot on an empty tree: bare `ctest` exits 0, and with
CTEST_NO_TESTS_ACTION=error it exits 8. So a package whose tests stop
being registered -- a renamed tests/ folder, a find_package that quietly
goes missing, BUILD_TESTING flipped by a cmake upgrade -- builds GREEN
with nothing run, and the only trace is one line in an 8 MB build log.

⚠️ And the case that will actually happen is not the empty tree: it is a
LABEL FILTER that catches nothing. Several of these rules run
`ctest -L raye`, so one test registered without its label is enough.
Measured again on 2026-11-06, on a tree holding exactly one UNLABELLED
test: `ctest -L raye` exits **0** with "No tests were found!!!", and
**8** with CTEST_NO_TESTS_ACTION=error. Nobody empties a tests folder;
people forget a label. That is the same silence, reached by the likelier
road, and this guard covers it.

🚨 TWO CASES IT DOES **NOT** COVER, measured 2026-11-06. The real shape
of the defect is not "the tree is empty", it is "what ctest selected is
empty OR CUT SHORT", and the variable only answers the first half.

  1. BUILD_TESTING=OFF. `enable_testing()` is never called, no
     CTestTestfile.cmake is written, and `ctest` exits **0 with the
     variable exactly as without it** -- measured both ways on the same
     tree. The guard is blind here. The case IS caught, but by something
     else entirely: `make test` has no `test` target and exits **2**, and
     `make test` is precisely what dh_auto_test runs (measured: 2 with
     BUILD_TESTING=OFF, 0 with it ON). Worth writing down, because
     someone reading only the paragraph above would lean on a protection
     that does not exist.

  2. A `file(GLOB)` that stops matching. If a tests/ folder is renamed,
     settings' registered tests fall from 43 to 2 -- the two that do not
     come from the glob. CTEST_NO_TESTS_ACTION **cannot fire: two is not
     zero.** The build would announce "2 tests passed" with 41 suites
     gone and not one word. settings closed it in its own CMakeLists.txt
     (a FATAL_ERROR when the glob is empty), and the hole is generic to
     every repository that collects tests by glob --
     test_test_globs_refuse_empty.py next to this file is the derived
     guard for that.

Six packages of Raye run ctest through dh_auto_test, and on 2026-11-06 not
one of them set that guard. This test exists so that removing it again is
a failure instead of a silence.

⚠️ It derives the list: every debian/rules under /srv/raye that mentions
dh_auto_test and whose repository configures with CMake. A list written
here would go stale the first time a repository starts or stops building
with CMake, which is exactly the defect this file is about.
"""
import os
import pathlib
import re
import unittest

GUARD = "CTEST_NO_TESTS_ACTION"
# debian/rules is a makefile: the value must be EXPORTED, or the recipe's
# ctest never sees it. "VAR = error" alone would look right and do nothing.
EXPORTED = re.compile(r"^\s*export\s+" + GUARD + r"\s*[:?+]?=\s*error\s*$", re.M)

RAYE = pathlib.Path(os.environ.get("RAYE_REPOS") or
                    pathlib.Path(__file__).resolve().parents[3])


def rules_that_run_ctest():
    """Every debian/rules that will invoke ctest: it runs dh_auto_test
    (explicitly or through the dh catch-all) and its build system is
    CMake, which is what makes `test` mean ctest."""
    found = {}
    for rules in sorted(RAYE.glob("*/debian/rules")):
        text = rules.read_text(errors="replace")
        cmake = "buildsystem=cmake" in text or (rules.parent.parent / "CMakeLists.txt").is_file()
        if not cmake:
            continue
        # nocheck-only packaging never tests; everything else does, either
        # by an override or by dh's own dh_auto_test step.
        if "dh_auto_test" not in text and not re.search(r"^\t*dh \$@", text, re.M):
            continue
        found[rules.parent.parent.name] = text
    return found


class CtestNoTestsGuard(unittest.TestCase):
    def test_there_is_something_to_check(self):
        # A scan that finds nothing passes for the wrong reason. On
        # 2026-11-06 there were six.
        self.assertGreaterEqual(
            len(rules_that_run_ctest()), 6,
            "found %d debian/rules that run ctest; the scan is looking in the"
            " wrong place (%s)" % (len(rules_that_run_ctest()), RAYE))

    def test_every_one_refuses_an_empty_ctest_run(self):
        without = sorted(name for name, text in rules_that_run_ctest().items()
                         if not EXPORTED.search(text))
        self.assertEqual(
            without, [],
            "%s/debian/rules runs ctest without 'export %s = error'. ctest"
            " exits 0 when it finds no test, so those packages would build"
            " green with nothing run." % (", ".join(without), GUARD))

    def test_the_guard_is_exported_not_merely_set(self):
        # "CTEST_NO_TESTS_ACTION = error" without export is a makefile
        # variable the recipe's ctest never sees: right-looking, inert.
        wrong = []
        for name, text in rules_that_run_ctest().items():
            if GUARD in text and not EXPORTED.search(text):
                wrong.append(name)
        self.assertEqual(wrong, [],
                         "%s sets %s without exporting it, so ctest never"
                         " sees it" % (", ".join(wrong), GUARD))
