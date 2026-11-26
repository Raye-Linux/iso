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


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class PromotionTests(unittest.TestCase):
    """A build goes to Dev first, then the very same files move up one channel
    at a time: Dev -> Beta -> Public Beta -> Stable."""

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

    def index(self, out, suite):
        return (out / f"dists/{suite}/main/binary-amd64/Packages").read_text()

    def test_promote_copies_the_exact_set_of_the_channel_below(self):
        out = self.tmp / "promo" / "apt"
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        make_deb(d, "raye-demo", "1.0~rc3", payload="rc3")
        pr.build(sorted(d.glob("*.deb")), out, pr.with_suite(self.conf, "resolute-dev"), keyring=self.keyring)
        s = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        make_deb(s, "raye-demo", "0.9", payload="stable")
        pr.build(sorted(s.glob("*.deb")), out, pr.with_suite(self.conf, "resolute"), keyring=self.keyring)
        stable_before = (out / "dists/resolute/InRelease").read_bytes()
        pr.promote(out, self.conf, "resolute-dev", "resolute-beta", keyring=self.keyring)
        self.assertIn("Version: 1.0~rc3", self.index(out, "resolute-beta"))
        # the same file, not a copy built again
        filename = next(l.split(": ", 1)[1] for l in self.index(out, "resolute-beta").splitlines()
                        if l.startswith("Filename:"))
        self.assertIn(f"Filename: {filename}", self.index(out, "resolute-dev"))
        self.assertTrue((out / filename).is_file())
        # the other channels are as they were
        self.assertEqual((out / "dists/resolute/InRelease").read_bytes(), stable_before)
        self.assertIn("Version: 1.0~rc3", self.index(out, "resolute-dev"))
        self.assertEqual(rp.audit_tree(out, "resolute-beta", self.keyring), [])

    def test_promote_only_goes_one_channel_up(self):
        out = self.tmp / "order" / "apt"
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        make_deb(d, "raye-demo", "1.0", payload="x")
        pr.build(sorted(d.glob("*.deb")), out, pr.with_suite(self.conf, "resolute-dev"), keyring=self.keyring)
        for src, dst in (("resolute-dev", "resolute"), ("resolute-beta", "resolute-dev"),
                         ("resolute-dev", "resolute-public-beta")):
            with self.subTest(src=src, dst=dst), self.assertRaises(rp.PublishError):
                pr.promote(out, self.conf, src, dst, keyring=self.keyring)

    def test_promote_refuses_an_empty_channel(self):
        out = self.tmp / "empty" / "apt"
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        make_deb(d, "raye-demo", "1.0", payload="x")
        pr.build(sorted(d.glob("*.deb")), out, pr.with_suite(self.conf, "resolute"), keyring=self.keyring)
        with self.assertRaises(rp.PublishError):
            pr.promote(out, self.conf, "resolute-beta", "resolute-public-beta", keyring=self.keyring)
