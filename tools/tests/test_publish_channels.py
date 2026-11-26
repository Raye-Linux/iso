# SPDX-License-Identifier: GPL-3.0-or-later
"""publish-repo and the Raye Insider channels: one tree, one suite per
channel (resolute, resolute-public-beta, resolute-beta, resolute-dev), and
publishing one suite never drops another one.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from test_publish_repo import NEEDED, make_deb, missing, pr, rp  # noqa: F401
from testkey import make_test_key


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class ChannelSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        home, cls.keyring, sub = make_test_key(cls.tmp)
        cls.conf = dict(rp.settings(), GNUPGHOME=str(home), SIGNING_KEY=sub)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                       env=dict(os.environ, GNUPGHOME=cls.conf["GNUPGHOME"]))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def debs(self, name, *pairs):
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp, prefix=name))
        for pkg, ver in pairs:
            make_deb(d, pkg, ver, payload=f"{pkg} {ver}")
        return d

    def publish(self, out, suite, debs):
        conf = pr.with_suite(self.conf, suite)
        pr.build(sorted(debs.glob("*.deb")), out, conf, keyring=self.keyring)

    def test_the_channel_suites_are_named_after_the_stable_one(self):
        self.assertEqual(pr.channel_suites(self.conf),
                         ["resolute", "resolute-public-beta", "resolute-beta", "resolute-dev"])
        self.assertEqual(pr.with_suite(self.conf, "resolute-dev")["SUITE"], "resolute-dev")
        with self.assertRaises(rp.PublishError):
            pr.with_suite(self.conf, "experimental")

    def test_publishing_stable_keeps_the_beta_suite_and_its_files(self):
        out = self.tmp / "keep" / "apt"
        self.publish(out, "resolute-beta", self.debs("b", ("raye-demo", "2.0~beta1")))
        beta_release = (out / "dists/resolute-beta/InRelease").read_bytes()
        self.publish(out, "resolute", self.debs("s", ("raye-demo", "1.0")))
        # the stable publish did not take the beta suite away
        self.assertEqual((out / "dists/resolute-beta/InRelease").read_bytes(), beta_release)
        idx = (out / "dists/resolute-beta/main/binary-amd64/Packages").read_text()
        filename = next(l.split(": ", 1)[1] for l in idx.splitlines() if l.startswith("Filename:"))
        self.assertTrue((out / filename).is_file(), filename)
        self.assertIn("1.0", (out / "dists/resolute/main/binary-amd64/Packages").read_text())
        self.assertNotIn("2.0~beta1",
                         (out / "dists/resolute/main/binary-amd64/Packages").read_text())

    def test_apt_on_the_beta_channel_sees_the_newer_version(self):
        out = self.tmp / "apt-view" / "apt"
        self.publish(out, "resolute", self.debs("s2", ("raye-demo", "1.0")))
        self.publish(out, "resolute-beta", self.debs("b2", ("raye-demo", "2.0~beta1")))
        self.assertTrue(rp.verify(self.keyring, out / "dists/resolute-beta/InRelease"))
        self.assertTrue(rp.verify(self.keyring, out / "dists/resolute/InRelease"))
        stable = (out / "dists/resolute/main/binary-amd64/Packages").read_text()
        self.assertIn("Version: 1.0", stable)
        self.assertNotIn("2.0~beta1", stable)
