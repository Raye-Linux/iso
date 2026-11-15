# SPDX-License-Identifier: GPL-3.0-or-later
"""The ctest counter of raye-tests, on the four shapes ctest prints.

    python3 -I -B -m unittest discover -s tools/tests

⚠️ A counter that miscounts is worse than none: it turns a skipped or
failed test into a pass in the one table people read. Two traps live in
ctest's output and both are checked here:

  * "out of N" is what ctest SELECTED, so N already counts the skipped
    ones -- passed is N minus failed minus skipped, not N minus failed.
  * "Tests Skipped: k" is printed ONLY when something skipped. Taking
    its absence for zero happens to be right; reading only the
    percentage line would count a skipped test as a pass.

And "No tests were found!!!" must count as nothing, not as zero passes:
the launcher then enforces its own "at least one test ran", which is the
whole reason CTEST_NO_TESTS_ACTION=error exists in the package builds.
"""
import importlib.machinery
import importlib.util
import pathlib
import unittest

TOOLS = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = TOOLS / "raye-tests"


def launcher():
    loader = importlib.machinery.SourceFileLoader("raye_tests_mod", str(LAUNCHER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


GREEN = "100% tests passed, 0 tests failed out of 4\nTotal Test time (real) = 16.52 sec\n"
FAILED = ("60% tests passed, 2 tests failed out of 5\n"
          "The following tests FAILED:\n\t  3 - pages (Failed)\n")
SKIPPED = ("75% tests passed, 0 tests failed out of 4\n\n"
           "The following tests did not run:\n\t  4 - shoot (Skipped)\n"
           "Tests Skipped: 1\n")
BOTH = "50% tests passed, 1 tests failed out of 4\nTests Skipped: 1\n"
NOTHING = "Test project /x\nNo tests were found!!!\n"


class CountsCtest(unittest.TestCase):
    def setUp(self):
        self.counts = launcher().counts

    def test_all_green(self):
        self.assertEqual(self.counts("ctest", GREEN), (4, 4, 0, 0))

    def test_failures_are_not_passes(self):
        self.assertEqual(self.counts("ctest", FAILED), (5, 3, 2, 0))

    def test_a_skipped_test_is_not_a_pass(self):
        self.assertEqual(self.counts("ctest", SKIPPED), (4, 3, 0, 1))

    def test_failures_and_skips_together(self):
        self.assertEqual(self.counts("ctest", BOTH), (4, 2, 1, 1))

    def test_no_test_found_counts_as_nothing(self):
        # None, not (0, 0, 0, 0): the launcher reads None as "nothing could
        # be counted" and fails the suite on it.
        self.assertIsNone(self.counts("ctest", NOTHING))
