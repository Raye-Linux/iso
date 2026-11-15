# SPDX-License-Identifier: GPL-3.0-or-later
"""The public apt tree carries packages and nothing else.

The owner's rule: the packages may be public, the ISO not. These tests go
red when an image (under any name), secret key material, or an unsigned
or wrongly signed Release would reach the tree that publish-github pushes
to a public repo. Needs dpkg-deb, apt-ftparchive, gpg and gpgv.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
"""
import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import raye_publish as rp  # noqa: E402
from testkey import make_test_key  # noqa: E402
from test_publish_repo import make_deb, missing  # noqa: E402


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(TOOLS / file))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


pr = load("publish_repo_g", "publish-repo")
pg = load("publish_github_g", "publish-github")


def fake_iso(path):
    """A file that is an ISO 9660 image to anyone who reads it."""
    data = bytearray(0x8800)
    data[0x8000:0x8006] = b"\x01CD001"
    path.write_bytes(bytes(data))


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.home, cls.keyring, sub = make_test_key(cls.tmp)
        cls.conf = dict(rp.settings(), GNUPGHOME=str(cls.home), SIGNING_KEY=sub)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                       env=dict(os.environ, GNUPGHOME=str(cls.home)))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        self.debs = self.work / "debs"
        self.debs.mkdir()
        make_deb(self.debs, "raye-demo", "1.0")
        self.out = self.work / "apt"
        pr.build(sorted(self.debs.glob("*.deb")), self.out, self.conf, keyring=self.keyring)
        self.suite = self.out / "dists" / self.conf["SUITE"]

    def problems(self):
        return rp.audit_tree(self.out, self.conf["SUITE"], self.keyring)

    def assertRefused(self, pattern):
        found = self.problems()
        self.assertTrue(any(pattern in p for p in found), f"{pattern!r} not in {found}")
        with self.assertRaises(rp.PublishError):
            pg.check_tree(self.out, self.conf, self.keyring)

    def secret_key(self, armor):
        args = ["gpg", "--batch", "--export-secret-keys"] + (["--armor"] if armor else [])
        return subprocess.run(args, env=dict(os.environ, GNUPGHOME=str(self.home)),
                              capture_output=True, check=True).stdout

    def test_a_good_tree_may_go_out(self):
        self.assertEqual(self.problems(), [])
        pg.check_tree(self.out, self.conf, self.keyring)

    # ---- the ISO, never
    def test_an_iso_by_its_name(self):
        (self.out / "pool/main/r/raye-demo/raye-0.1-beta-amd64.iso").write_bytes(b"x")
        self.assertRefused("image file name")

    def test_the_iso_checksum_file(self):
        (self.out / "dists/latest.iso.sha256").write_text("0" * 64 + "  latest.iso\n")
        self.assertRefused("image file name")

    def test_an_iso_under_another_name(self):
        fake_iso(self.out / "pool/main/r/raye-demo/raye-demo_1.0.orig.tar.xz")
        self.assertRefused("ISO 9660 image")

    def test_an_iso_at_the_top_of_the_tree(self):
        fake_iso(self.out / "latest")
        self.assertRefused("not part of an apt tree")

    def test_build_refuses_an_iso_dressed_as_a_source(self):
        src = self.work / "src"
        src.mkdir()
        fake_iso(src / "demo_1.0.tar.xz")
        digest = rp.sha256(src / "demo_1.0.tar.xz")
        (src / "demo_1.0.dsc").write_text(
            f"Format: 3.0 (native)\nSource: demo\nVersion: 1.0\nBinary: demo\n"
            f"Checksums-Sha256:\n {digest} {(src / 'demo_1.0.tar.xz').stat().st_size}"
            " demo_1.0.tar.xz\nFiles:\n 0 0 demo_1.0.tar.xz\n")
        with self.assertRaisesRegex(rp.PublishError, "ISO 9660"):
            pr.build(sorted(self.debs.glob("*.deb")), self.out, self.conf,
                     keyring=self.keyring, dscs=[src / "demo_1.0.dsc"])
        # the published tree is the previous one, untouched
        self.assertEqual(self.problems(), [])

    # ---- secret keys, never
    def test_an_armored_secret_key(self):
        (self.suite / "archive.asc").write_bytes(self.secret_key(armor=True))
        self.assertRefused("secret key material")

    def test_a_binary_secret_key(self):
        (self.suite / "archive.gpg").write_bytes(self.secret_key(armor=False))
        self.assertRefused("secret key material")

    def test_a_gnupg_home(self):
        d = self.out / "pool/main/r/raye-demo/private-keys-v1.d"
        d.mkdir()
        (d / "ABCD.key").write_text("(private-key)")
        self.assertRefused("key or secret file")

    def test_the_r2_credentials(self):
        (self.out / "dists/r2.env").write_text("R2_SECRET_ACCESS_KEY=x\n")
        self.assertRefused("key or secret file")

    # ---- signed by the shipped key, over the Release that is there
    def test_no_inrelease(self):
        (self.suite / "InRelease").unlink()
        self.assertRefused("not signed")

    def test_no_detached_signature(self):
        (self.suite / "Release.gpg").unlink()
        self.assertRefused("not signed")

    def test_release_changed_after_signing(self):
        with open(self.suite / "Release", "a") as f:
            f.write("Extra: 1\n")
        self.assertRefused("does not sign the Release")

    def test_signed_by_another_key(self):
        other = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        _, other_ring, _ = make_test_key(other)
        found = rp.audit_tree(self.out, self.conf["SUITE"], other_ring)
        self.assertTrue(any("does not verify" in p for p in found), found)

    def test_unsigned_build_is_not_publishable(self):
        out = self.work / "unsigned"
        pr.build(sorted(self.debs.glob("*.deb")), out, self.conf, signed=False,
                 keyring=self.keyring)
        found = rp.audit_tree(out, self.conf["SUITE"], self.keyring)
        self.assertTrue(any("not signed" in p for p in found), found)

    def test_source_packages_are_published_and_indexed(self):
        src = self.work / "src"
        src.mkdir()
        (src / "demo_1.0.tar.xz").write_bytes(b"\xfd7zXZ\x00 not really")
        digest = rp.sha256(src / "demo_1.0.tar.xz")
        size = (src / "demo_1.0.tar.xz").stat().st_size
        (src / "demo_1.0.dsc").write_text(
            f"Format: 3.0 (native)\nSource: demo\nBinary: demo\nArchitecture: any\n"
            f"Version: 1.0\nMaintainer: Raye <bonjour@rayelinux.com>\n"
            f"Checksums-Sha256:\n {digest} {size} demo_1.0.tar.xz\n"
            f"Files:\n 00000000000000000000000000000000 {size} demo_1.0.tar.xz\n")
        pr.build(sorted(self.debs.glob("*.deb")), self.out, self.conf,
                 keyring=self.keyring, dscs=[src / "demo_1.0.dsc"])
        self.assertTrue((self.out / "pool/main/d/demo/demo_1.0.dsc").is_file())
        sources = (self.suite / "main/source/Sources").read_text()
        self.assertIn("Package: demo", sources)
        self.assertIn("main/source/Sources", (self.suite / "Release").read_text())
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
