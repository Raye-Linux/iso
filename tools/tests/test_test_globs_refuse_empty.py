# SPDX-License-Identifier: GPL-3.0-or-later
"""A file(GLOB) that collects tests must refuse to configure when empty.

    python3 -I -B -m unittest discover -s tools/tests

🚨 Why this file exists, measured on 2026-11-06.

CTEST_NO_TESTS_ACTION=error -- the guard test_ctest_no_tests_guard.py
next to this one enforces -- fires only when ctest selected **zero**
tests. It cannot see a set that was merely CUT SHORT. And cut short is
what a glob does:

    file(GLOB RAYE_TEST_SOURCES CONFIGURE_DEPENDS tests/test_*.cpp)

Rename tests/, and settings' registered tests fall from 43 to 2 -- the
two that do not come from the glob. **Two is not zero**, so the variable
stays quiet, ctest reports "2 tests passed", 41 suites are gone, and the
package builds green. That is a worse silence than an empty tree,
because the figure in the log looks like a number of tests rather than
like nothing.

settings closed it where it belongs, at configure time, with a
FATAL_ERROR when the glob comes back empty: the build stops and says so.
The hole is generic -- six globs in three repositories collect test files
-- so this file derives the list rather than naming it, exactly as the
ctest guard derives its own.

⚠️ What a "guard" means here, and why it is not stricter: the glob's
result must be TESTED before it is used, by a FATAL_ERROR on empty, or by
an `if(<var>)` that makes the registration conditional AND fails or warns
rather than silently registering nothing. A conditional that quietly
skips registration is NOT a guard: it is the defect with an if around it.
Only FATAL_ERROR on the empty case counts.

⚠️ THREE globs are OPEN as of 2026-11-06, and the third is the surprise:
settings guards `tests/test_*.cpp` and does **not** guard
`tests/test_*.sh`, though the same CMakeLists.txt registers three shell
tests from it (line 257). The repository held up as the worked example
closed one of its two test globs. This guard found that by itself, on
its first run, which is the only kind of evidence worth having for a
rule like this one.

They are listed below so the guard is green on what it cannot fix and red
on anything NEW -- a test that goes red for a neighbour's defect blocks
the wrong person. They are defects, not decisions: files/, store/ and
settings/ should each close theirs the way settings closed the first one,
and then this list gets shorter. Every run prints the ones that have been
fixed, so the list shrinks instead of rotting.
"""
import os
import pathlib
import re
import shutil
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve()
RAYE = pathlib.Path(os.environ.get("RAYE_REPOS") or HERE.parents[3])

# A glob is "about tests" when what it matches is test files. Matching on
# the variable name would miss `file(GLOB sources ... tests/test_*.cpp)`;
# matching on the pattern is what the build actually does.
TEST_PATTERN = re.compile(r"(?:test_|tst_)\*|/tests?/[^)\s]*\*")
GLOB = re.compile(r"file\s*\(\s*GLOB(?:_RECURSE)?\s+([A-Za-z_][A-Za-z0-9_]*)"
                  r"([^)]*)\)", re.S)

# Globs that do not refuse an empty result yet, with what was measured.
# SHORTEN this list when one is closed; it must never grow without the
# commit saying which repository added a glob and why it may stay open.
OPEN = {
    "settings/CMakeLists.txt": (
        "RAYE_TEST_SOURCES (tests/test_*.cpp) IS guarded -- that is the "
        "worked example everything below is told to copy. Its sibling "
        "RAYE_TEST_SCRIPTS (tests/test_*.sh) is not, and line 257 "
        "registers three shell tests from it: test_reset_settings.sh, "
        "test_storage_clean.sh, test_version.sh. Rename or move those "
        "three and the .cpp guard stays quiet, because its own glob still "
        "matches"),
    "files/tests/raye/CMakeLists.txt": (
        "two globs, test_*.cpp and test_*.sh, feed ecm_add_test and "
        "add_test with no check that either matched. The whole of files' "
        "ctest run is registered through them: rename tests/raye and the "
        "build is green with nothing run"),
    "store/CMakeLists.txt": (
        "two globs, tests/test_*.cpp and tests/test_*.py, inside an "
        "if(BUILD_TESTING) block with no check that either matched"),
}


def cmake_files():
    """Every CMakeLists.txt of the tree, excluding build folders."""
    out = []
    for p in RAYE.rglob("CMakeLists.txt"):
        rel = p.relative_to(RAYE).as_posix()
        if any(part in rel.split("/") for part in
               ("build", "obj-x86_64-linux-gnu", ".git", "out", "_build")):
            continue
        out.append(p)
    return sorted(out)


def globs_that_collect(path):
    """(variable, pattern) of every glob in `path` that collects tests.

    ⚠️ NOT named test_* on purpose. It used to be `test_globs`, and a
    helper with a test name is collected as one: pytest took it for a
    test, found no fixture called `path`, and ERRORED on every run --
    in the one file whose whole job is to refuse sweeps that collect
    nothing. `unittest discover`, which the launcher uses, ignores a
    module-level function entirely, so the suite stayed green and the
    error was only ever seen by someone running pytest by hand.
    Measured 2026-11-06: pytest said "10 passed, 1 error", unittest
    said "Ran 10 tests ... OK".
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for var, rest in GLOB.findall(text):
        if TEST_PATTERN.search(rest):
            found.append((var, " ".join(rest.split())))
    return found


def guards(path, var):
    """Does `path` refuse to configure when `var` came back empty?

    Only a FATAL_ERROR counts. An `if(var)` that silently registers
    nothing is the defect with an if around it.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    # if(NOT var) ... FATAL_ERROR, in either order, within the same block
    for m in re.finditer(r"if\s*\(\s*NOT\s+%s\s*\)(.{0,600}?)endif" % re.escape(var),
                         text, re.S):
        if "FATAL_ERROR" in m.group(1):
            return True
    # or a bare check: list(LENGTH var n) ... FATAL_ERROR
    for m in re.finditer(r"list\s*\(\s*LENGTH\s+%s\s+(\w+)\s*\)(.{0,600}?)"
                         % re.escape(var), text, re.S):
        if "FATAL_ERROR" in m.group(2):
            return True
    return False


class TheDetectorItselfWorks(unittest.TestCase):
    """🚨 Without this class the whole file is vacuous, and that was
    measured, not foreseen: make `guards()` return True unconditionally and
    every assertion below still passes -- the run only prints three "fixed:"
    lines, which are deliberately NOT failures so that closing a hole is
    never punished. A detector stuck on True is therefore silent, and a
    detector stuck on False would flood. So the detector is tested against
    fixtures, where the answer is known, before it is believed about the
    tree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="raye-globguard.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, body):
        p = pathlib.Path(self.tmp) / "CMakeLists.txt"
        p.write_text(body, encoding="utf-8")
        return p

    def test_it_sees_a_glob_that_collects_tests(self):
        p = self.write("file(GLOB T CONFIGURE_DEPENDS tests/test_*.cpp)\n")
        self.assertEqual(globs_that_collect(p),
                         [("T", "CONFIGURE_DEPENDS tests/test_*.cpp")])

    def test_it_ignores_a_glob_that_collects_sources(self):
        p = self.write("file(GLOB S CONFIGURE_DEPENDS src/*.cpp)\n")
        self.assertEqual(globs_that_collect(p), [],
                         "a glob over src/ is not about tests, and counting "
                         "it would flood this guard with false holes")

    def test_fatal_error_on_empty_counts_as_a_guard(self):
        p = self.write(
            "file(GLOB T CONFIGURE_DEPENDS tests/test_*.cpp)\n"
            "if(NOT T)\n"
            '    message(FATAL_ERROR "tests/test_*.cpp matched nothing")\n'
            "endif()\n")
        self.assertTrue(guards(p, "T"))

    def test_no_check_at_all_is_not_a_guard(self):
        p = self.write("file(GLOB T CONFIGURE_DEPENDS tests/test_*.cpp)\n"
                       "foreach(f IN LISTS T)\nendforeach()\n")
        self.assertFalse(guards(p, "T"))

    def test_a_silent_conditional_is_not_a_guard(self):
        """The defect with an if around it: registration is skipped and the
        build says nothing. This is the case that must NOT read as closed."""
        p = self.write("file(GLOB T CONFIGURE_DEPENDS tests/test_*.cpp)\n"
                       "if(T)\n    foreach(f IN LISTS T)\n    endforeach()\n"
                       "endif()\n")
        self.assertFalse(guards(p, "T"),
                         "an if(T) that quietly registers nothing was read as "
                         "a guard; it is the defect, not the fix")

    def test_a_guard_on_another_variable_does_not_count(self):
        """settings' real shape: one glob guarded, its sibling not."""
        p = self.write(
            "file(GLOB A CONFIGURE_DEPENDS tests/test_*.cpp)\n"
            "file(GLOB B CONFIGURE_DEPENDS tests/test_*.sh)\n"
            'if(NOT A)\n    message(FATAL_ERROR "nothing")\nendif()\n')
        self.assertTrue(guards(p, "A"))
        self.assertFalse(guards(p, "B"),
                         "a FATAL_ERROR about another variable was credited "
                         "to this one -- exactly the case this file found in "
                         "settings")


class TestGlobsRefuseEmpty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = cmake_files()
        cls.globbers = {}
        for p in cls.files:
            found = globs_that_collect(p)
            if found:
                cls.globbers[p.relative_to(RAYE).as_posix()] = (p, found)

    def test_the_tree_was_really_read(self):
        """A guard that found no CMakeLists.txt would pass everything."""
        self.assertGreater(len(self.files), 10,
                           "only %d CMakeLists.txt found under %s: the tree "
                           "was not read" % (len(self.files), RAYE))
        self.assertGreater(len(self.globbers), 0,
                           "no test-collecting glob found anywhere, which "
                           "contradicts the measurement this file records")

    def test_no_new_unguarded_glob(self):
        bad = []
        for rel, (path, found) in sorted(self.globbers.items()):
            if rel in OPEN:
                continue
            for var, pattern in found:
                if not guards(path, var):
                    bad.append("%s: file(GLOB %s %s) is used without "
                               "refusing an empty result" % (rel, var, pattern))
        self.assertEqual(bad, [], "\n".join([
            "a glob collects test files and nothing stops the build when it "
            "matches none:",
        ] + ["    " + b for b in bad] + [
            "",
            "CTEST_NO_TESTS_ACTION cannot catch this: a glob that loses most",
            "of its matches leaves a non-zero count, and only zero makes it",
            "fire. Add, next to the glob:",
            "",
            "    if(NOT <var>)",
            '        message(FATAL_ERROR "tests/test_*.cpp matched nothing")',
            "    endif()",
            "",
            "or, if the glob may legitimately be empty, add the file to OPEN",
            "in %s and say in the commit why." % HERE.name,
        ]))

    def test_the_open_list_is_still_accurate(self):
        """Every entry of OPEN must still exist and still be unguarded.

        An entry for a file that has been FIXED does not fail -- that
        would punish the fix -- but it is printed every run, so the list
        gets shorter instead of rotting.
        """
        gone, closed = [], []
        for rel in sorted(OPEN):
            entry = self.globbers.get(rel)
            if entry is None:
                gone.append(rel)
                continue
            path, found = entry
            if all(guards(path, var) for var, _ in found):
                closed.append(rel)
        for rel in closed:
            print("\nfixed: %s now refuses an empty test glob -- take it out "
                  "of OPEN in %s" % (rel, HERE.name))
        for rel in gone:
            print("\ngone: %s has no test-collecting glob any more -- take it "
                  "out of OPEN in %s" % (rel, HERE.name))
        # a name that no longer matches any file at all is a dead entry and
        # would hide a real hole if the path came back
        unknown = [r for r in gone if not (RAYE / r).exists()]
        self.assertEqual(unknown, [], "OPEN names files that do not exist: "
                                      "%s" % unknown)

    def test_the_worked_example_stays_closed(self):
        """settings' C++ glob is the one guard that exists, and every
        message above tells the others to copy it. If it goes, the rule
        loses the only thing proving it is possible."""
        entry = self.globbers.get("settings/CMakeLists.txt")
        if entry is None:
            self.skipTest("settings/CMakeLists.txt has no test glob any more")
        path, found = entry
        names = [v for v, _ in found]
        self.assertIn("RAYE_TEST_SOURCES", names,
                      "settings no longer globs tests/test_*.cpp into "
                      "RAYE_TEST_SOURCES; re-read its CMakeLists.txt before "
                      "trusting the rule below")
        self.assertTrue(
            guards(path, "RAYE_TEST_SOURCES"),
            "settings stopped refusing an empty tests/test_*.cpp glob. That "
            "FATAL_ERROR is the worked example this whole file points at, and "
            "without it 43 registered tests can fall to 2 with ctest saying "
            '"2 tests passed"')


if __name__ == "__main__":
    unittest.main()
