"""The line a terminal sign-in shows, instead of the base system's help links."""

import os
import pathlib
import re
import subprocess
import unittest

MOTD = pathlib.Path(__file__).resolve().parent.parent / "motd"
DEBIAN = MOTD.parent.parent.parent / "debian"


class Motd(unittest.TestCase):
    def test_it_replaces_the_help_script_of_the_base_system(self):
        self.assertEqual([p.name for p in MOTD.iterdir()], ["10-help-text"])
        # shipped in /etc it was a conffile over base-files' own: dpkg took
        # the stock one's checksum, found the file moved aside and asked
        # at configure, which stopped the image build. So it ships under
        # usr/lib/raye and a link takes the stock name, like /etc/issue.
        self.assertRegex((DEBIAN / "raye-release-paths").read_text(),
                         r"(?m)^raye-release\s+release/identity/motd/\*\s+usr/lib/raye/motd\s*$")
        self.assertRegex((DEBIAN / "raye-release.links").read_text(),
                         r"(?m)^usr/lib/raye/motd/10-help-text\s+etc/update-motd\.d/10-help-text\s*$")
        for script in ("raye-release.preinst", "raye-release.postinst"):
            fixed = re.search(r'(?m)^FIXED="([^"]*)"', (DEBIAN / script).read_text())
            self.assertIn("/etc/update-motd.d/10-help-text", fixed.group(1).split(), script)

    def test_it_runs_and_says_one_thing(self):
        script = MOTD / "10-help-text"
        # pam_motd runs what is executable and skips the rest without a word
        self.assertTrue(os.access(script, os.X_OK))
        out = subprocess.run([str(script)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("handbook", out)
        for word in ("ubuntu", "canonical", "landscape"):
            self.assertNotIn(word, out.lower())


if __name__ == "__main__":
    unittest.main()
