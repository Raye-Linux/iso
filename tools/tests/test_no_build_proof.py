# SPDX-License-Identifier: GPL-3.0-or-later
"""A "the package build runs it" skip must name the wiring, and what a log covered.

    python3 -I -B -m unittest discover -s tools/tests

🚨 Why this file exists, measured on 2026-11-06.

Eleven suites of raye_tests_suites.py are skipped with the `no_build`
policy, which says the package build runs them instead. The sentence used
to end "and that run is verified -- apps.log ends 100% tests passed out of
11", and a reader checked the figure, found it, and stopped.

The figure was real. It was also, for four of the eleven, evidence about
OTHER TESTS:

  * apps/taskmanager-qtest -- taskmanager/tests/ was committed on
    2026-11-06, five days AFTER that log. Its three tests appear nowhere
    in it. Defended by 11 passing tests, none of which was one of them.
  * theme/qtest -- the twelve of theme2.log's shell run are inputpanel-*,
    menus-*, run-*, plasmoidcheck, plasmoidload and tree. `grep
    shellsettings theme2.log` returns ZERO, and so do updatestate,
    recentlyadded, appjumplist, launcherentry and polkit's appinfo and
    request. 0 of 8.
  * apps/qtest -- 3 of 4. sharepicker's folder landed after the log, and
    portal/CMakeLists.txt adds it only if(EXISTS qml/CMakeLists.txt): the
    eleven were eleven because the test did not exist.
  * files/qtest -- 5 of 28. settings/qtest -- 6 of 40. store/qtest -- 3 of 5.

So the defect is NOT "ctest found nothing": CTEST_NO_TESTS_ACTION and
test_test_globs_refuse_empty.py next to this file already cover that, and
`make test` covers BUILD_TESTING=OFF. The defect is the PROOF going stale
while reading as a verdict -- a count quoted from a build that predates the
tests it is cited for. A count with no statement of what it covers cannot
be checked by anyone, which is why nobody did for five days.

What this guard demands, and all of it is checkable with NO build:

  1. the reason names the registration -- "<path>:<line>" of the
     add_test()/ecm_add_test()/raye_add_qtest() a package build reaches;
  2. that path exists and that LINE really registers a test. This is the
     half that cannot rot: move the file or the line and the guard says so,
     which a sentence of prose never does;
  3. the reason says "covers N of M". The figure is a measurement about
     ONE suite, and writing it is what makes 0 of 3 impossible to mistake
     for 11 passing tests;
  4. a quoted build log carries its date, "(YYYY-MM-DD)". The log itself is
     NOT required to be present: it lives outside the repository, and a
     checkout elsewhere has no copy. The
     date is the part that lets a reader see it predates the tests.

⚠️ What this guard does NOT do. It cannot tell whether "covers 3 of 5" is
TRUE -- that needs the log, which is not in the repository. It makes the
claim exist, specific and dated, so that it can be checked and so that it
is wrong out loud rather than absent. The same bargain as the count= word
in test_counts_declared.py.

⚠️ And it deliberately refuses the policy to account/*. Nothing builds
account -- no debian/, and iso/build.sh's compiled_sources() names
installer, settings, store, theme, files and apps. Those two suites run
NOWHERE, and borrowing the no_build sentence for them would be the same
defect with a different subject.
"""

import importlib.util
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve()
TABLE = HERE.parents[1] / "raye_tests_suites.py"
RAYE = HERE.parents[3]          # /srv/raye

# The first words of the policy. A skip reason carrying this claims the
# package build runs the suite, and must then prove it.
POLICY = "needs a compiled build tree, and this launcher never builds"

# "<path>:<line>", path relative to /srv/raye, pointing at CMake or at a
# debian/rules. Both kinds rot the same way, so both are resolved.
SITE = re.compile(r"\b([A-Za-z0-9_][A-Za-z0-9_./+-]*"
                  r"(?:CMakeLists\.txt|\.cmake|debian/rules)):(\d+)\b")
COVERS = re.compile(r"\bcovers\s+(\d+)\s+of\s+(\d+)\b")
LOG = re.compile(r"\b([A-Za-z0-9_.+-]+\.log)\b")
DATED_LOG = re.compile(r"\b[A-Za-z0-9_.+-]+\.log\s*\((\d{4}-\d{2}-\d{2})\)")
# A line that REGISTERS a test. At least one cited site must be one of
# these: it is the only kind of line that makes a test exist.
REGISTERS = re.compile(r"\b(?:add_test|ecm_add_test|raye_add_qtest)\s*\(")
# A line that merely REACHES a registration -- the add_subdirectory, the
# if(EXISTS ...) or the -DBUILD_TESTING a build goes through. Citing one is
# legitimate and often the interesting half (apps/qtest's sharepicker is
# absent from a log precisely because of an if(EXISTS)), so these are
# allowed -- but they are resolved exactly like the others, because a
# wiring citation goes stale the same way. What they may NOT do is stand
# alone: a reason naming only wiring has not named the test.
REACHES = re.compile(r"\b(?:add_subdirectory|if\s*\(\s*EXISTS|raye_add_app"
                     r"|BUILD_TESTING|RAYE_TREES|dh_auto_test|dh_auto_configure"
                     r"|set_tests_properties|LABELS|FATAL_ERROR|find_program)\b")

# The suites nothing builds at all. They must NOT use the policy.
NOT_BUILT_ANYWHERE = {
    "account/cargo":
        "cargo test compiles the crate, and no package build covers it: "
        "account has no debian/ and iso/build.sh's compiled_sources() does "
        "not name it",
    "account/qml":
        "account has no debian/ and iso/build.sh's compiled_sources() does "
        "not name it, so these tests run nowhere",
}


def manifest():
    spec = importlib.util.spec_from_file_location("raye_tests_suites", TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MANIFEST


def code_of(line):
    """The CMake code of a line, without its comment.

    🚨 Found by this file's own regression bench on 2026-11-06: commenting
    out `add_test(NAME raye-ui ...)` left every check GREEN, because the
    pattern matched the text inside the `#`. A registration that has been
    commented out is exactly the regression this guard exists to catch, and
    it was the one shape it could not see. CMake comments run to the end of
    the line, so the first `#` ends the code -- a `#` inside a quoted
    string would truncate early, which costs a false alarm, never a miss.
    """
    return line.split("#", 1)[0]


def sites_of(reason):
    return [(p, int(n)) for p, n in SITE.findall(reason)]


def unresolved(reason):
    """Every named site that does not resolve to a real registration."""
    bad = []
    for path, line in sites_of(reason):
        f = RAYE / path
        if not f.is_file():
            bad.append("%s:%d -- no such file under %s" % (path, line, RAYE))
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if line > len(lines):
            bad.append("%s:%d -- the file has only %d lines"
                       % (path, line, len(lines)))
        elif not (REGISTERS.search(code_of(lines[line - 1]))
                  or REACHES.search(code_of(lines[line - 1]))):
            bad.append("%s:%d -- that line is %r, which neither registers a "
                       "test nor reaches one"
                       % (path, line, lines[line - 1].strip()[:70]))
    return bad


def registering_sites(reason):
    """The cited sites whose line really makes a test exist."""
    out = []
    for path, line in sites_of(reason):
        f = RAYE / path
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if line <= len(lines) and REGISTERS.search(code_of(lines[line - 1])):
            out.append("%s:%d" % (path, line))
    return out


class NoBuildProof(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TABLE.is_file(), "%s is missing" % TABLE)
        self.suites = manifest()
        self.claimed = [s for s in self.suites
                        if POLICY in s.get("never", "")]

    def test_the_table_loads_and_the_policy_is_still_worded_this_way(self):
        """A guard that matches nothing passes vacuously, and says nothing."""
        self.assertGreater(len(self.suites), 40,
                           "the table did not load: %d entries" % len(self.suites))
        self.assertGreaterEqual(
            len(self.claimed), 11,
            "only %d suites carry the no_build policy. Either they were "
            "wired up (good -- lower the floor in this test) or the policy "
            "sentence was reworded and POLICY here no longer matches it, "
            "which would make every check below pass on nothing."
            % len(self.claimed))

    def test_every_claim_names_its_registration(self):
        """\"the build runs it\" with no file:line is a claim nobody can check."""
        naked = sorted(s["name"] for s in self.claimed if not sites_of(s["never"]))
        self.assertEqual(naked, [], "\n".join([
            "these suites say the package build runs them and name no "
            "registration site:",
        ] + ["    %s" % n for n in naked] + [
            "",
            "Pass no_build() a \"<path>:<line>\" (relative to /srv/raye) of the",
            "add_test(), ecm_add_test() or raye_add_qtest() that a package build",
            "reaches. Prose cannot be checked; a path and a line can, and this",
            "test does check them.",
        ]))

    def test_wiring_alone_is_not_a_registration(self):
        """add_subdirectory(tests) is where the tests are, not what they are."""
        wiring_only = sorted(s["name"] for s in self.claimed
                             if sites_of(s["never"])
                             and not registering_sites(s["never"]))
        self.assertEqual(wiring_only, [], "\n".join([
            "these suites cite only wiring -- an add_subdirectory, an",
            "if(EXISTS ...), a -DBUILD_TESTING -- and never the line that",
            "registers a test:",
        ] + ["    %s" % n for n in wiring_only] + [
            "",
            "Cite the add_test()/ecm_add_test()/raye_add_qtest() itself too.",
            "Wiring says a folder is reached; only the registration says a",
            "test exists at the end of it.",
        ]))

    def test_every_named_site_really_registers_a_test(self):
        """The half that cannot rot: the file moved, so the proof is gone."""
        bad = []
        for s in sorted(self.claimed, key=lambda x: x["name"]):
            for problem in unresolved(s["never"]):
                bad.append("%s: %s" % (s["name"], problem))
        self.assertEqual(bad, [], "\n".join([
            "these registration sites do not resolve:",
        ] + ["    " + b for b in bad] + [
            "",
            "Re-read the file and put the real line number in the table. A",
            "stale file:line is the same defect as a stale count: it reads as",
            "proof and proves nothing.",
        ]))

    def test_every_claim_says_what_it_covers(self):
        """0 of 3 and 11 passing tests must not look alike."""
        silent = sorted(s["name"] for s in self.claimed
                        if not COVERS.search(s["never"]))
        self.assertEqual(silent, [], "\n".join([
            "these suites quote evidence without saying what it covers:",
        ] + ["    %s" % n for n in silent] + [
            "",
            "Add \"covers N of M\" to the no_build() covered= text, measured by",
            "reading the ctest names the log printed (\"Start N: <name>\")",
            "against what the repository registers today. M = what a fresh",
            "build would run; N = how many of those the quoted log really ran.",
            "apps/taskmanager-qtest was defended for five days by 11 passing",
            "tests, none of which was one of its three.",
        ]))

    def test_coverage_figures_are_possible(self):
        """N of M with N > M, or M = 0, is a typo that would read as proof."""
        wrong = []
        for s in sorted(self.claimed, key=lambda x: x["name"]):
            for n, m in COVERS.findall(s["never"]):
                n, m = int(n), int(m)
                if m == 0:
                    wrong.append("%s: covers %d of 0 -- M is what a fresh "
                                 "build would run, and it is never zero" % (s["name"], n))
                elif n > m:
                    wrong.append("%s: covers %d of %d" % (s["name"], n, m))
        self.assertEqual(wrong, [], "impossible coverage figures:\n    " +
                                    "\n    ".join(wrong))

    def test_a_quoted_log_carries_its_date(self):
        """An undated log is how a count outlives the tests it is cited for."""
        undated = []
        for s in sorted(self.claimed, key=lambda x: x["name"]):
            named = set(LOG.findall(s["never"]))
            if not named:
                continue
            dated = set(re.findall(r"\b([A-Za-z0-9_.+-]+\.log)\s*\(\d{4}-\d{2}-\d{2}\)",
                                   s["never"]))
            for miss in sorted(named - dated):
                undated.append("%s quotes %s with no (YYYY-MM-DD)"
                               % (s["name"], miss))
        self.assertEqual(undated, [], "\n".join([
            "these log citations have no date:",
        ] + ["    " + u for u in undated] + [
            "",
            "Write the log's date next to its name. The file is not in the",
            "repository, so the date is the only thing a reader has to notice",
            "that the build predates the tests being defended with it.",
        ]))

    def test_what_nothing_builds_does_not_borrow_the_policy(self):
        """account/* run NOWHERE. Saying "the build runs them" would be false."""
        by_name = {s["name"]: s for s in self.suites}
        wrong = []
        for name, why in sorted(NOT_BUILT_ANYWHERE.items()):
            s = by_name.get(name)
            if s is None:
                wrong.append("%s is not in the table any more -- if it was "
                             "wired up, take it out of NOT_BUILT_ANYWHERE "
                             "here" % name)
            elif "never" not in s:
                wrong.append("%s runs now: take it out of NOT_BUILT_ANYWHERE"
                             % name)
            elif POLICY in s["never"]:
                wrong.append("%s uses the no_build policy, but %s" % (name, why))
        self.assertEqual(wrong, [], "\n".join(["\n    " + w for w in wrong]))

    def test_the_repository_was_really_read(self):
        """If RAYE pointed at the wrong folder every site would be "missing"."""
        self.assertTrue((RAYE / "iso" / "tools" / "raye-tests").is_file(),
                        "RAYE = %s does not look like /srv/raye" % RAYE)


class TheGuardCanFail(unittest.TestCase):
    """A garde-fou that has never gone red proves nothing. These are the
    four shapes it exists to catch, written out rather than trusted."""

    def test_no_site_is_caught(self):
        self.assertEqual(sites_of(POLICY + ", and it is all fine"), [])

    def test_a_site_in_a_missing_file_is_caught(self):
        bad = unresolved("see theme/no/such/CMakeLists.txt:7 for it")
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("no such file", bad[0])

    def test_a_site_past_the_end_of_the_file_is_caught(self):
        bad = unresolved("see iso/tools/tests/test_no_build_proof.py:999999")
        # not a CMake path: SITE must not even match it
        self.assertEqual(bad, [])
        bad = unresolved("see theme/qml/CMakeLists.txt:999999 for it")
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("only", bad[0])

    def test_a_site_on_a_line_that_does_neither_is_caught(self):
        bad = unresolved("see theme/qml/CMakeLists.txt:1 for it")
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("neither registers", bad[0])

    def test_wiring_resolves_but_does_not_register(self):
        """The distinction the guard turns on, both halves measured."""
        wiring = "theme/shell/lib/CMakeLists.txt:82"      # add_subdirectory(tests)
        self.assertEqual(unresolved(wiring), [])
        self.assertEqual(registering_sites(wiring), [])
        real = "theme/shell/lib/tests/CMakeLists.txt:34"  # add_test(NAME lib-...)
        self.assertEqual(unresolved(real), [])
        self.assertEqual(registering_sites(real), [real])

    def test_a_debian_rules_site_is_resolved_too(self):
        self.assertEqual(unresolved("files/debian/rules:67"), [])
        bad = unresolved("files/debian/rules:1")
        self.assertEqual(len(bad), 1, bad)

    def test_a_real_site_resolves(self):
        self.assertEqual(unresolved("theme/qml/CMakeLists.txt:76"), [])
        self.assertEqual(unresolved("files/tests/raye/CMakeLists.txt:32"), [])
        self.assertEqual(
            unresolved("apps/taskmanager/tests/CMakeLists.txt:12"), [])

    def test_a_bare_count_has_no_coverage(self):
        self.assertIsNone(COVERS.search('ends "0 tests failed out of 11"'))
        self.assertIsNotNone(COVERS.search("it covers 0 of 3"))

    def test_a_commented_out_registration_does_not_count(self):
        """The shape that was green until 2026-11-06."""
        self.assertIsNotNone(REGISTERS.search(code_of("    add_test(NAME x)")))
        self.assertIsNone(REGISTERS.search(code_of("    # add_test(NAME x)")))
        self.assertIsNone(REACHES.search(code_of("    # add_subdirectory(tests)")))

    def test_an_undated_log_is_not_dated(self):
        self.assertIsNone(DATED_LOG.search("apps.log ends well"))
        self.assertIsNotNone(DATED_LOG.search("apps.log (2026-11-01) ends well"))


if __name__ == "__main__":
    unittest.main()
