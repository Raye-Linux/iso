# SPDX-License-Identifier: GPL-3.0-or-later
"""No test may re-exec python with -I and without -B.

🚨 Why this file exists, measured on 2026-11-06.

`raye-tests` sets PYTHONDONTWRITEBYTECODE=1 for every suite, and that is
enough for the suites themselves. It is NOT enough for a test that
re-execs python: `-I` is isolated mode, and isolated mode ignores every
PYTHON* variable. The child therefore writes
`tokens/__pycache__/generate.cpython-313.pyc` into the SOURCE tree
whatever the launcher sets -- and the same thing happens under ctest,
where no launcher is involved at all.

Eight call sites did it. One of them wrote into
`usr/lib/calamares/modules/`, a folder the installer PACKAGES: only
`debian/rules` exporting PYTHONDONTWRITEBYTECODE kept those `.pyc` out of
the shipped deb, and that export is exactly what `-I` ignores.

Two guards now exist, and they catch different things:

  * `raye-tests --strict` fails the run on any cache left under a
    repository. It MEASURES (tree before, tree after), so nothing can
    hide from it -- but only for a suite that actually ran. A skipped
    suite leaks nothing today and still carries the defect.
  * this file reads the source, so it sees a skipped suite too.

⚠️ Deliberately NOT flagged: `#!/usr/bin/python3 -I` on the shebang of a
SHIPPED script (the bench suites, `po-rename.py`, `make-apt-rank.py`).
Those run once from `/usr/bin`, four tests assert their first line byte
for byte, and changing them would change packaged file contents for no
measured gain. The tests that EXECUTE them pass `-I -B` themselves,
which is where the leak actually was.

    python3 -I -B -m unittest discover -s tools/tests
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.dirname(os.path.dirname(HERE))          # the iso repository
TREE = os.path.dirname(ISO)                           # /srv/raye, when it exists

# Every repository that holds python tests. A missing one is skipped, not
# invented: a single-repository checkout is a legitimate place to run this.
REPOS = ("iso", "theme", "desktop", "installer", "store", "wine", "kernel",
         "update", "handbook", "settings", "files", "website")

# The argv token, not the prose. A quoted "-I" in a list is a real argument;
# `python3 -I` inside a docstring or a fake script body is not, and this
# pattern cannot confuse the two -- which is the whole reason it matches on
# the quotes.
PY_TOKEN = re.compile(r'(?<!\w)"-I"')
CPP_TOKEN = re.compile(r'QStringLiteral\("-I"\)')
# The next double-quoted argument after the one just matched.
NEXT_ARG = re.compile(r'"([^"\n]*)"')


def _without_comments(text, lang):
    """The file with its comment lines dropped.

    ⚠️ A comment that explains a dangerous flag reads, to a grep, exactly
    like a use of it. `test_build_memoire.sh` already documents paying for
    that once; the docstring above this test mentions `-I` four times, so
    this file would flag ITSELF without this step.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if lang == "py" and stripped.startswith("#"):
            continue
        if lang == "cpp" and stripped.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


SELF = os.path.abspath(__file__)


def _is_test_file(path):
    # This file is excluded from its own scan, and that is not a
    # convenience: PY_TOKEN and CPP_TOKEN are regex literals that CONTAIN
    # the argv token, so the check flagged its own two pattern lines on the
    # first run. A checker whose source is indistinguishable from the thing
    # it forbids has to name the exception rather than weaken the pattern --
    # weakening it is how a check stops biting.
    if os.path.abspath(path) == SELF:
        return False
    base = os.path.basename(path)
    if base.startswith("test_") and base.endswith((".py", ".cpp")):
        return True
    return base == "raye_tests_suites.py"


def _files():
    """Every test file of every repository present, with its language."""
    found = []
    for repo in REPOS:
        root = os.path.join(TREE, repo)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "__pycache__", "build",
                                        "work", "out", "node_modules")]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if _is_test_file(full):
                    found.append((full, "cpp" if name.endswith(".cpp") else "py"))
    return found


class IsolatedPythonNeverWritesBytecode(unittest.TestCase):

    def setUp(self):
        self.files = _files()

    def test_the_scan_actually_has_something_to_read(self):
        """A check that no longer bites is worse than no check.

        If the walk finds no test file at all -- a moved tree, a renamed
        folder -- every other test here passes while verifying nothing.
        """
        self.assertGreater(len(self.files), 50,
                           "only %d test file(s) found under %s: this check has "
                           "stopped scanning anything" % (len(self.files), TREE))
        names = [p for p, _ in self.files]
        self.assertTrue(
            any(p.endswith("raye_tests_suites.py") for p in names),
            "the suite table is not in the scan, and it is the one file that "
            "decides how every suite is launched")

    def test_no_test_re_execs_python_in_isolated_mode_without_B(self):
        offenders = []
        for path, lang in self.files:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = _without_comments(fh.read(), lang)
            except OSError:
                continue
            token = CPP_TOKEN if lang == "cpp" else PY_TOKEN
            for m in token.finditer(text):
                # The NEXT quoted argument must be -B. Looking at "the next
                # 80 characters" instead would pass on a -B that belongs to a
                # different call three lines down.
                nxt = NEXT_ARG.search(text, m.end())
                if nxt is None or nxt.group(1) != "-B":
                    line = text[:m.start()].count("\n") + 1
                    offenders.append("%s:%d" % (os.path.relpath(path, TREE), line))
        self.assertEqual(
            offenders, [],
            "-I without -B, so PYTHONDONTWRITEBYTECODE is ignored and the "
            "child writes .pyc into the source tree: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
