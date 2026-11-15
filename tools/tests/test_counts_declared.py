# SPDX-License-Identifier: GPL-3.0-or-later
"""A suite may pass while counting nothing only if it says so on purpose.

    python3 -I -B -m unittest discover -s tools/tests

🚨 Why this file exists, measured on 2026-11-06.

`files/desktop-file` printed no figure at all in the report -- a blank
where its two sibling suites printed "1 test(s)". The script was not at
fault: it does two real checks and ends with "ok: 2 checks, 0 failed".
Its entry in raye_tests_suites.py simply had no `count=`, and
`counts(how, out)` returns None for `how is None` whatever the output is.
So the suite went green, forever, with nothing counted, and the only
trace was an empty column.

That is indistinguishable, in the report, from a suite that measures
nothing at all. This test makes the difference explicit: a suite with no
`count=` must be named below with the reason, so that the blank column is
a decision somebody wrote down rather than a word somebody forgot.

It cuts both ways, and that is the point:

  * a suite with no `count=` and no entry below -> FAIL. Add the word, or
    add the reason here.
  * an entry below for a suite that now HAS `count=` -> FAIL. The list
    cannot rot into a blanket exemption, which is how an allow-list stops
    protecting anything.

⚠️ What this file does NOT do: demand that `count=` be correct. Whether
"shell" or "pytest" reads a given output is a question only the output
answers, and `raye-tests` already fails a counted suite whose output it
cannot count ("nothing could be counted in the output"). The gap this
file closes is the one that rule cannot see -- an UNcounted suite, which
that rule never looks at.
"""
import importlib.util
import os
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve()
TABLE = HERE.parents[1] / "raye_tests_suites.py"

# Every suite that runs without counting anything, and why. Each reason is
# measured, not assumed: it names what the suite prints and why no counter
# reads it.
UNCOUNTED = {
    "apps/registration":
        'prints "-- registration: 10 test files, all registered". None of '
        "the shell counters match it: RE_SUM wants \"N passed/checks, M "
        'failed", RE_OK wants a line starting with "ok", RE_ALLOK wants '
        '"all checks passed". Giving it count="shell" would fail a green '
        "suite. Its sibling cmake scripts (version, po-check, packaging) "
        'all end with "all checks passed" and are counted',
    "installer/paths-strict":
        "it is a release gate that is MEANT to be red until every '?' in "
        "debian/raye-paths is written, and what matters is the COUNT of "
        "remaining ones in its own output, not a pass/fail tally. Measured "
        "2026-11-06: 12 errors, each naming a missing path",
    "theme/run-shortcut-update":
        'prints "PASS" and nothing else, which no counter matches. '
        'count="shell" would turn a passing suite red. The fix belongs to '
        "the theme repository's script, not to this table",
}


def manifest():
    spec = importlib.util.spec_from_file_location("raye_tests_suites", TABLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MANIFEST


class CountsAreDeclared(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TABLE.is_file(), "%s is missing" % TABLE)
        # The table is data; importing it must not leave bytecode beside it,
        # which is the very thing raye-tests promises not to do.
        self.suites = manifest()
        self.runnable = [s for s in self.suites if "never" not in s]

    def test_the_table_loads_and_has_suites(self):
        """A guard that cannot find the table would pass vacuously."""
        self.assertGreater(len(self.runnable), 40,
                           "only %d runnable suites: the table did not load"
                           % len(self.runnable))

    def test_every_uncounted_suite_is_declared(self):
        undeclared = sorted(s["name"] for s in self.runnable
                            if not s["count"] and s["name"] not in UNCOUNTED)
        self.assertEqual(undeclared, [], "\n".join([
            "these suites run without counting anything, and nothing says why:",
        ] + ["    %s" % n for n in undeclared] + [
            "",
            "Either give the entry count= (\"shell\", \"pytest\", \"unittest\",",
            "\"qmltest\", \"ctest\"), which also makes raye-tests require that at",
            "least one test ran -- or add the name to UNCOUNTED in %s with the"
            % HERE.name,
            "reason, after looking at what the suite actually prints.",
        ]))

    def test_no_stale_exemption(self):
        """An entry here for a suite that is now counted is a dead licence."""
        by_name = {s["name"]: s for s in self.suites}
        stale = []
        for name in sorted(UNCOUNTED):
            s = by_name.get(name)
            if s is None:
                stale.append("%s is not in the table any more" % name)
            elif "never" in s:
                stale.append("%s is a skipped() entry: it never runs, so it "
                             "needs no exemption" % name)
            elif s["count"]:
                stale.append("%s now counts with count=%r: take it out of "
                             "UNCOUNTED" % (name, s["count"]))
        self.assertEqual(stale, [], "\n".join(["stale exemptions:"] +
                                              ["    " + x for x in stale]))

    def test_every_reason_says_something(self):
        """A reason of three words is an exemption nobody can check."""
        thin = sorted(n for n, why in UNCOUNTED.items() if len(why.split()) < 12)
        self.assertEqual(thin, [], "these reasons are too thin to be checked "
                                   "against the suite's output: %s" % thin)


if __name__ == "__main__":
    unittest.main()
