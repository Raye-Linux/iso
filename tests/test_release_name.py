# SPDX-License-Identifier: GPL-3.0-or-later
"""The release people read comes from VERSION and release-names only.

On 1.0 Beta 2 every file still said "1.0 Beta Brocken" (os-release, Setup,
About): they were written by hand, one by one. tools/release_name.py now
writes them all from the two files, and this test is what keeps them so.

    python3 -I -B tests/test_release_name.py
"""
import importlib.util
import io
import pathlib
import shutil
import sys
import tempfile
import re
import unittest

ISO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release_name", ISO / "tools" / "release_name.py")
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)


def png_release(png):
    """The Raye-Release text chunk boot/grub/art.py stamps on release.png."""
    data = png.read_bytes()
    pos = 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"tEXt" and body.startswith(b"Raye-Release\x00"):
            return body.split(b"\x00", 1)[1].decode("latin-1")
        pos += 12 + length
    return None


def copy_tree(dest):
    """iso (the files the tool touches) and its siblings, into dest."""
    iso = dest / "iso"
    for rel in ["VERSION", "release-names", "tools/release.conf",
                *[f"packages/raye-base/release/{f}" for f in
                  ("os-release", "lsb-release", "issue", "issue.net", "python-apt/raye.info")]]:
        (iso / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ISO / rel, iso / rel)
    for repo, rels in (("installer", ["VERSION", "etc/calamares/branding/raye/branding.desc"]),
                       ("settings", ["VERSION"]), ("store", ["VERSION"]), ("handbook", ["VERSION"])):
        for rel in rels:
            src = ISO.parent / repo / rel
            if src.is_file():
                (dest / repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dest / repo / rel)
    return iso


class TheTree(unittest.TestCase):
    def test_every_file_says_the_release(self):
        out = io.StringIO()
        drift = rn.run(ISO, stream=out)
        self.assertEqual(drift, [], out.getvalue())

    def test_the_release_is_raye_linux_1_0(self):
        """The stable V1 is "Raye Linux 1.0", without a name: none was
        decided (retours-proprietaire), and a stable release has no beta
        number for a name to replace."""
        version, name, full = rn.release()
        self.assertEqual(version, "1.0")
        self.assertEqual(name, "")
        self.assertEqual(full, "1.0")
        self.assertNotIn("Beta", full)
        self.assertNotIn("Sundog", (ISO / rn.RELEASE_DIR / "os-release").read_text())

    def test_no_name_is_left_to_give(self):
        self.assertNotIn("TODO-NAME", (ISO / "release-names").read_text())

    def test_os_release_is_what_settings_shows(self):
        version, _name, full = rn.release()
        fields = dict(l.split("=", 1) for l in
                      (ISO / rn.RELEASE_DIR / "os-release").read_text().splitlines() if "=" in l)
        self.assertEqual(fields["VERSION"], f'"{full}"')
        self.assertEqual(fields["PRETTY_NAME"], f'"Raye Linux {full}"')
        self.assertEqual(fields["VERSION_ID"], f'"{version.split()[0]}"')


class TheTool(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.iso = copy_tree(self.tmp)
        # the mechanics are checked on a beta, where a name replaces a number
        (self.iso / "VERSION").write_text("1.0 Beta 2\n")
        rn.run(self.iso, write=True, stream=io.StringIO())

    def name(self, line):
        names = self.iso / "release-names"
        text = re.sub(r"^1\.0 Beta 2:.*$", line, names.read_text(), count=1, flags=re.M)
        names.write_text(text)

    def test_a_name_filled_in_reaches_every_file(self):
        self.name("1.0 Beta 2: Matterhorn")
        self.assertEqual(rn.release(self.iso)[2], "1.0 Beta Matterhorn")
        out = io.StringIO()
        self.assertTrue(rn.run(self.iso, stream=out))      # out of step until written
        rn.run(self.iso, write=True, stream=out)
        self.assertEqual(rn.run(self.iso, stream=out), [])
        for rel in ("os-release", "lsb-release", "issue", "issue.net", "python-apt/raye.info"):
            self.assertIn("Raye Linux 1.0 Beta Matterhorn", (self.iso / rn.RELEASE_DIR / rel).read_text(), rel)
        conf = (self.iso / "tools/release.conf").read_text()
        self.assertIn("RELEASE_TITLE=Raye Linux 1.0 Beta Matterhorn\n", conf)
        self.assertIn("RELEASE=1.0-beta\n", conf)
        branding = self.tmp / "installer/etc/calamares/branding/raye/branding.desc"
        if branding.is_file():
            text = branding.read_text()
            self.assertIn("    version:             1.0 Beta Matterhorn\n", text)
            self.assertIn("    versionedName:       Raye Linux 1.0 Beta Matterhorn\n", text)
            self.assertIn("    shortVersion:        1.0 Beta Matterhorn\n", text)
            self.assertIn("    shortVersionedName:  Raye 1.0 Beta Matterhorn\n", text)

    def test_a_hand_edit_is_caught(self):
        osr = self.iso / rn.RELEASE_DIR / "os-release"
        osr.write_text(osr.read_text().replace("1.0 Beta Sundog", "1.0 Beta Brocken"))
        self.assertIn(osr, rn.run(self.iso, stream=io.StringIO()))

    def test_bad_names_are_refused(self):
        for bad in ("1.0 Beta 2: Matter horn", "1.0 Beta 2: Zürich", "1.0 Beta 2 Matterhorn", "1.0 Beta 2: Two2"):
            with self.subTest(bad=bad):
                names = self.iso / "release-names"
                keep = names.read_text()
                self.name(bad)
                with self.assertRaises(rn.ReleaseError):
                    rn.release(self.iso)
                names.write_text(keep)

    def test_a_version_without_a_line_is_refused(self):
        (self.iso / "VERSION").write_text("1.0 Beta 3\n")
        with self.assertRaises(rn.ReleaseError):
            rn.release(self.iso)

    def test_the_shown_release(self):
        self.assertEqual(rn.shown("1.0 Beta 2", "Sundog"), "1.0 Beta Sundog")
        self.assertEqual(rn.shown("1.0 Beta", "Brocken"), "1.0 Beta Brocken")
        self.assertEqual(rn.shown("1.0 Beta 2", ""), "1.0 Beta 2")
        self.assertEqual(rn.shown("1.1", "Crepuscule"), "1.1 Crepuscule")

    def test_an_unnamed_release_keeps_its_number(self):
        self.name("1.0 Beta 2:")
        self.assertEqual(rn.release(self.iso)[2], "1.0 Beta 2")

    def test_the_slug(self):
        self.assertEqual(rn.slug("1.0 Beta 2"), "1.0-beta-2")
        self.assertEqual(rn.slug("0.5 Beta"), "0.5-beta")
        self.assertEqual(rn.series("1.0 Beta 2"), "1.0-beta")
        self.assertEqual(rn.series("1.0 Beta"), "1.0-beta")
        self.assertEqual(rn.series("1.1"), "1.1")


class TheBootMenu(unittest.TestCase):
    def test_grub_shows_the_release(self):
        """GRUB's line under the title is the release people read."""
        self.assertEqual(png_release(ISO / "boot/grub/themes/raye/release.png"), rn.release()[2])


class TheBuild(unittest.TestCase):
    def test_the_image_build_checks_first(self):
        build = (ISO / "build.sh").read_text()
        self.assertRegex(build, r'release_name\.py" --check \|\|')


if __name__ == "__main__":
    unittest.main()
