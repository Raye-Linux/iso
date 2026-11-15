# SPDX-License-Identifier: GPL-3.0-or-later
"""The release notes may not say what nothing measured.

    python3 -I -B -m unittest discover -s tools/tests

🚨 Why this file exists, measured on 2026-11-06.

Both notes said "Raye uses about 1.3 GB of memory at idle once you have
signed in". `docs/bench/baseline.md` says, in its own words, that the
measurement after logging in "were not taken here; they go in with the
first real hardware run", and its table row reads `Memory after login |
TODO`. The only memory figure anyone has measured is 680 MiB at the
login screen with nobody signed in. So the most public file of the
release carried a number nobody had ever obtained -- and the same notes
say, four bullets lower, that hardware benchmarks are not done.

Publishing a wrong claim is worse than omitting a true one: a reader can
act on it, and a beta asks people to trust what it says about itself.

What this file holds the notes to:

  * every memory figure is one baseline.md has, and the signed-in one
    comes from its "After signing in" section (measured on 0.3);
  * no "Wine", and no promise of a start without black;
  * no promise of a graphical boot menu while grub.cfg does not set one
    (it restarted a Dell Latitude 5420 before the menu showed, and it is
    deliberately off);
  * English and French say the same FACTS -- every number with a unit,
    every URL and every command in one appears in the other. A fact in
    one language and not the other is a defect whichever side is right;
  * the archive key fingerprint a reader is told to expect is the one the
    image's keyring really has (only with an image: $RAYE_ROOT).

⚠️ What it does NOT do. It does not check prose, promises about features,
or the figures under "Before you start" (4 GB, 32 GB): those are
recommendations deliberately stricter than what the installer enforces
(measured in the image: requiredRam 2.0, requiredStorage 25), and
tightening them is a product decision, not a test's.

⚠️ And it rides the gate of the `iso/tools` suite, which asks for
dpkg-deb, apt-ftparchive, apt-get, gpg and gpgv. That is stricter than a
test about two Markdown files needs; it is accepted because a suite of
its own would make `discover -s tools/tests` run this file twice and
count it twice.
"""
import os
import pathlib
import re
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[2]
DOCS = REPO / "docs"
EN = DOCS / "release-notes-0.5-beta.md"
FR = DOCS / "release-notes-0.5-beta.fr.md"
BASELINE = DOCS / "bench" / "baseline.md"
GRUBCFG = REPO / "boot" / "grub" / "grub.cfg"

# French writes Go/Mo/Mio and a decimal comma; the same fact must compare
# equal across the two files or the parity check is noise.
UNITS = {"go": "gb", "mo": "mb", "mio": "mib", "gio": "gib", "ko": "kb"}
FIGURE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(GiB|MiB|KiB|Gio|Mio|Kio|GB|MB|KB|Go|Mo|Ko)\b")
URL = re.compile(r"https?://[^\s`,)>]+")
# the indented blocks are the commands a reader will paste. The trailing
# `# fingerprint ...` / `# empreinte ...` of the gpg line is a COMMENT, and
# it is translated: comparing the raw lines made the two languages differ on
# a command that is identical. The command is what is compared.
COMMAND = re.compile(r"^(?: {4}|\t)(\S.*)$", re.M)
TRAILING_COMMENT = re.compile(r"\s+#.*$")

# One bullet of a list: it ends at the next bullet, a blank line or a
# heading. Splitting only on the next bullet made the LAST bullet run to
# the end of the file and swallow every figure in the document -- measured
# 2026-11-06, it reported the download table as a memory claim.
BULLET = re.compile(r"^[ \t]*[-*] .*(?:\n(?![ \t]*[-*] |[ \t]*$|#).*)*", re.M)


def figures(text):
    out = set()
    for num, unit in FIGURE.findall(text):
        u = unit.lower()
        out.add((num.replace(",", "."), UNITS.get(u, u)))
    return out


def read(p):
    return p.read_text(encoding="utf-8")


class ReleaseNotesExist(unittest.TestCase):
    def test_both_languages_are_there(self):
        for p in (EN, FR):
            self.assertTrue(p.is_file(), "%s is missing" % p)
        # a guard that read empty files would pass everything below
        for p in (EN, FR):
            self.assertGreater(len(read(p)), 2000, "%s is suspiciously short" % p)


class MemoryFiguresAreMeasured(unittest.TestCase):
    """The defect of 2026-11-06, in both directions."""

    def setUp(self):
        self.assertTrue(BASELINE.is_file(), "%s is missing" % BASELINE)
        self.baseline = read(BASELINE)

    def signed_in(self):
        """The figures of baseline.md's "After signing in" section."""
        m = re.search(r"^## After signing in\n(.*?)(?=^## |\Z)",
                      self.baseline, re.M | re.S)
        self.assertIsNotNone(m, "baseline.md has no 'After signing in' "
                                "section: re-read it before trusting the "
                                "rule below")
        found = figures(m.group(1))
        self.assertTrue(found, "baseline.md's 'After signing in' has no figure")
        return found

    def test_the_signed_in_figure_is_the_measured_one(self):
        """Measured on the 0.3 Beta: 1198 to 1200 MiB, two screens."""
        measured = self.signed_in()
        after = re.compile(
            r"(?:once you have signed in|after signing in|after you sign in|"
            r"une fois la session ouverte|apr[eè]s ouverture de session)",
            re.I)
        for p in (EN, FR):
            text = read(p)
            for para in BULLET.findall(text):
                if not after.search(para):
                    continue
                # the login-screen figure may share the bullet
                claims = {f for f in figures(para) if f[1] in ("mib", "mb")}
                claims -= figures(self.baseline.split("## After signing in")[0])
                self.assertTrue(
                    claims <= measured,
                    "%s states a signed-in memory figure baseline.md does "
                    "not have: %s\n%s" % (p.name, sorted(claims - measured),
                                           para.strip()))

    def test_the_figure_given_is_the_one_that_was_measured(self):
        """680 MiB, the login-screen median of eight boots."""
        measured = figures(self.baseline)
        for p in (EN, FR):
            text = read(p)
            mentioned = {f for f in figures(text)
                         if f[1] in ("mib", "mb") and float(f[0]) > 100}
            for f in mentioned:
                self.assertIn(
                    f, measured,
                    "%s says %s %s of memory, and baseline.md has no such "
                    "figure. Every memory number in the notes must be one "
                    "somebody took." % (p.name, f[0], f[1]))


class WordsTheReaderMustNotSee(unittest.TestCase):
    def test_no_wine(self):
        # the layer that runs Windows programs is Raye's to the reader
        for p in (EN, FR):
            self.assertNotRegex(read(p), r"(?<![-\w])[Ww]ine\b", p.name)

    def test_no_promise_of_a_start_without_black(self):
        # 3 to 5 s of black before the sign-in screen, measured on 0.3
        for p in (EN, FR):
            self.assertNotRegex(read(p), r"(?i)(no black screen|sans [eé]cran noir)",
                                p.name)


class NoGraphicalBootMenuPromised(unittest.TestCase):
    def test_grub_is_still_plain_text(self):
        self.assertTrue(GRUBCFG.is_file(), "%s is missing" % GRUBCFG)
        cfg = read(GRUBCFG)
        theme = re.search(r"^\s*set\s+theme=", cfg, re.M)
        if theme:
            self.skipTest("grub.cfg sets a theme again: the rule below no "
                          "longer applies, and tests/test_boot_menu.sh is the "
                          "place that decides whether it may")
        for p in (EN, FR):
            text = read(p)
            for m in re.finditer(r"(?:boot menu|menu de d[eé]marrage)", text, re.I):
                line = text[max(0, m.start() - 120):m.end() + 120]
                self.assertNotRegex(
                    line, r"(?i)(graphical|graphique|themed|th[eè]me)",
                    "%s describes the boot menu as graphical, and grub.cfg "
                    "keeps it plain text on purpose: the graphical one "
                    "restarted a Dell Latitude 5420 before the menu showed"
                    % p.name)


class TheTwoLanguagesAgreeOnFacts(unittest.TestCase):
    def setUp(self):
        self.en, self.fr = read(EN), read(FR)

    def test_same_figures(self):
        only_en = figures(self.en) - figures(self.fr)
        only_fr = figures(self.fr) - figures(self.en)
        self.assertEqual(
            (sorted(only_en), sorted(only_fr)), ([], []),
            "a number with a unit is in one language and not the other "
            "(Go/Mo/Mio and the decimal comma are already normalised):\n"
            "  only English: %s\n  only French:  %s"
            % (sorted(only_en), sorted(only_fr)))

    def test_same_urls(self):
        # each file links to the other, so those two differ by design
        def links(text, other):
            return {u for u in URL.findall(text) if other not in u}
        only_en = links(self.en, FR.name) - links(self.fr, EN.name)
        only_fr = links(self.fr, EN.name) - links(self.en, FR.name)
        self.assertEqual((sorted(only_en), sorted(only_fr)), ([], []),
                         "a link is in one language and not the other:\n"
                         "  only English: %s\n  only French:  %s"
                         % (sorted(only_en), sorted(only_fr)))

    def test_same_commands(self):
        def cmds(text):
            out = set()
            for c in COMMAND.findall(text):
                c = c.strip()
                if c.startswith("#"):
                    continue
                out.add(TRAILING_COMMENT.sub("", c).strip())
            return out
        only_en, only_fr = cmds(self.en) - cmds(self.fr), cmds(self.fr) - cmds(self.en)
        self.assertEqual((sorted(only_en), sorted(only_fr)), ([], []),
                         "a command a reader is told to paste is in one "
                         "language and not the other:\n  only English: %s\n"
                         "  only French:  %s" % (sorted(only_en), sorted(only_fr)))


class OneAddressForBUGS(unittest.TestCase):
    """🚨 Where a bug report goes must be ONE address.

    Measured 2026-11-06: the image said
    BUG_REPORT_URL="https://github.com/Raye-Linux/iso/issues" and
    /etc/dpkg/origins/raye said the same, while the release notes in both
    languages, both download pages and tools/release.json said
    .../Raye-Linux/releases/issues. Two visible uses against five. A
    report that goes to a repository nobody watches is a bug that never
    gets fixed, so the two were moved onto the five.

    ⚠️ This test asserts they are EQUAL, never which one wins. Changing
    the address is one edit in each of the four places and this test keeps
    them together; hard-coding the value here would make this file the
    fifth place to remember.

    ⚠️ And neither repository exists. Measured the same day: the
    organisation github.com/Raye-Linux answers 200, and Raye-Linux/iso,
    Raye-Linux/releases and Raye-Linux/handbook all answer **404**. So
    which address is right is not a measurable question -- it is the
    owner's, and it is settled by creating the repository. What IS
    measurable, and is a defect either way, is the two of them disagreeing.
    """

    SOURCES = {
        "release/os-release": (
            "packages/raye-base/release/os-release",
            r'^BUG_REPORT_URL="?([^"\n]+)"?$'),
        "release/dpkg/raye": (
            "packages/raye-base/release/dpkg/raye",
            r"^Bugs:\s*(\S+)$"),
    }

    def found(self):
        out = {}
        for name, (rel, pattern) in self.SOURCES.items():
            p = REPO / rel
            self.assertTrue(p.is_file(), "%s is missing" % rel)
            m = re.search(pattern, read(p), re.M)
            self.assertIsNotNone(m, "%s names no bug address" % rel)
            out[name] = m.group(1).strip()
        for p in (EN, FR):
            urls = {u.rstrip(".,") for u in URL.findall(read(p))
                    if "/issues" in u}
            self.assertTrue(urls, "%s tells no one where to report a bug"
                                  % p.name)
            self.assertEqual(len(urls), 1,
                             "%s names %d different issue addresses: %s"
                             % (p.name, len(urls), sorted(urls)))
            out[p.name] = urls.pop()
        return out

    def test_every_place_says_the_same_address(self):
        found = self.found()
        self.assertEqual(
            len(set(found.values())), 1,
            "a bug report would go to different places depending on where "
            "the reader looked:\n" +
            "\n".join("    %-28s %s" % (k, v) for k, v in sorted(found.items())))

    def test_it_is_under_the_raye_organisation(self):
        """The one thing that can be checked without choosing a repository:
        an address outside the organisation is wrong whoever picked it."""
        for where, url in sorted(self.found().items()):
            self.assertRegex(url, r"^https://github\.com/Raye-Linux/[^/]+/issues$",
                             "%s points at %s, which is not an issues page of "
                             "the Raye-Linux organisation" % (where, url))


class TheFingerprintIsTheKeysOwn(unittest.TestCase):
    """Only with an image. A reader types this one in, so it has to be the
    keyring's real fingerprint and not a copied-over one."""

    def setUp(self):
        self.root = os.environ.get("RAYE_ROOT")
        if not self.root:
            self.skipTest("no $RAYE_ROOT: the image's keyring is the only "
                          "thing that can answer, and nothing is guessed")
        self.keyring = pathlib.Path(self.root) / \
            "usr/share/keyrings/raye-archive-keyring.gpg"
        if not self.keyring.is_file():
            self.skipTest("%s is not in the image" % self.keyring)

    def test_the_notes_name_the_images_fingerprint(self):
        p = subprocess.run(
            ["gpg", "--no-default-keyring", "--keyring", str(self.keyring),
             "--list-keys", "--with-colons"],
            capture_output=True, text=True, timeout=120,
            stdin=subprocess.DEVNULL)
        prints = [l.split(":")[9] for l in p.stdout.splitlines()
                  if l.startswith("fpr:")]
        if not prints:
            self.skipTest("gpg read no fingerprint from the image's keyring")
        primary = prints[0]
        for path in (EN, FR):
            text = read(path)
            said = {re.sub(r"\s+", "", m)
                    for m in re.findall(r"(?:[0-9A-F]{4}\s+){9}[0-9A-F]{4}", text)}
            self.assertTrue(said, "%s names no fingerprint at all, while it "
                                  "tells the reader to check one" % path.name)
            self.assertIn(primary, said,
                          "%s tells the reader to expect a fingerprint the "
                          "image's keyring does not have. The keyring says "
                          "%s." % (path.name, primary))


if __name__ == "__main__":
    unittest.main()
