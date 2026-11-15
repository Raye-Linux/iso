# SPDX-License-Identifier: GPL-3.0-or-later
"""Every folder of the apt tree has an index.html, and only that.

dl.rayelinux.com and the GitHub Pages mirror show a folder browser. The
pages must never turn into a way around the audit: an index.html that is
not a page these tools write, or that carries a key, is refused like any
other file; nothing else but index.html is allowed next to the packages.
Needs dpkg-deb, apt-ftparchive, gpg and gpgv.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import raye_pages  # noqa: E402
import raye_publish as rp  # noqa: E402
from testkey import make_test_key  # noqa: E402
from test_publish_guard import fake_iso, load  # noqa: E402
from test_publish_repo import make_deb, missing  # noqa: E402

pr = load("publish_repo_p", "publish-repo")
r2 = load("publish_r2_p", "publish-r2")


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class FolderPageTests(unittest.TestCase):
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

    # ---- what the build writes
    def test_every_folder_has_a_page_and_the_tree_may_go_out(self):
        folders = [self.out, *(p for p in self.out.rglob("*") if p.is_dir())]
        self.assertGreater(len(folders), 6)
        for f in folders:
            self.assertTrue(raye_pages.is_folder_page(f / "index.html"), f)
        self.assertEqual(self.problems(), [])

    def test_apt_never_reads_the_pages(self):
        for name in ("Release", "InRelease"):
            self.assertNotIn("index.html", (self.suite / name).read_text())
        packages = (self.suite / "main/binary-amd64/Packages").read_text()
        self.assertNotIn("index.html", packages)
        # the signature still covers exactly the Release that is there
        self.assertEqual(self.problems(), [])

    def test_pages_are_written_after_signing(self):
        page = (self.suite / "index.html").read_text()
        for name in ("InRelease", "Release.gpg", "Release"):
            self.assertIn(f'<a href="{name}">{name}</a>', page)

    def test_a_page_lists_its_folder_and_links_up(self):
        folder = self.out / "pool/main/r/raye-demo"
        page = (folder / "index.html").read_text()
        self.assertIn('<a href="raye-demo_1.0_all.deb">raye-demo_1.0_all.deb</a>', page)
        self.assertIn('<a href="../">../</a>', page)
        self.assertNotIn(">index.html<", page)
        top = (self.out / "index.html").read_text()
        for d in ("dists/", "pool/"):
            self.assertIn(f'<a href="{d}">{d}</a>', top)

    def test_no_script_and_nothing_from_outside(self):
        for page in self.out.rglob("index.html"):
            text = page.read_text()
            self.assertNotIn("<script", text.lower())
            self.assertNotIn('src="http', text)
            self.assertNotIn('href="http://', text)

    def test_odd_names_are_escaped(self):
        d = self.work / "odd"
        (d / "a b").mkdir(parents=True)
        (d / "<x>&.deb").write_bytes(b"x")
        page = raye_pages.folder_page(d, d, eye="")
        self.assertIn('href="a%20b/"', page)
        self.assertIn("&lt;x&gt;&amp;.deb", page)
        self.assertNotIn("<x>", page)

    def test_the_top_page_of_the_bucket(self):
        page = raye_pages.root_page()
        self.assertTrue(page.startswith(raye_pages.DOCTYPE))
        self.assertIn('<a href="apt/">apt/</a>', page)
        self.assertIn("image will be published here", page)
        self.assertNotIn(".iso", page)

    # ---- the audit does not loosen
    def test_an_iso_named_index_html(self):
        fake_iso(self.out / "pool/main/r/raye-demo/index.html")
        self.assertRefused("not a folder page")
        self.assertRefused("ISO 9660 image")

    def test_a_secret_key_inside_a_page(self):
        page = self.out / "dists/index.html"
        page.write_text(page.read_text() + "-----BEGIN PGP PRIVATE KEY BLOCK-----\n")
        self.assertRefused("secret key material")

    def test_another_html_file_in_the_pool(self):
        (self.out / "pool/main/r/raye-demo/notes.html").write_text(raye_pages.DOCTYPE + "\n")
        self.assertRefused("not a package file")

    def test_a_page_with_another_case(self):
        (self.out / "pool/main/r/raye-demo/Index.html").write_text(raye_pages.DOCTYPE + "\n")
        self.assertRefused("not a folder page")

    def test_a_page_too_big(self):
        (self.out / "pool/index.html").write_text(raye_pages.DOCTYPE + "x" * raye_pages.PAGE_LIMIT)
        self.assertRefused("not a folder page")

    def test_an_iso_at_the_top_still_refused(self):
        fake_iso(self.out / "latest.iso")
        self.assertRefused("not part of an apt tree")


class R2PageTests(unittest.TestCase):
    def test_pages_are_never_cached_forever(self):
        steps = dict(r2.apt_steps(pathlib.Path("/t/apt"), "b"))
        pool = steps["packages and old indexes"]
        self.assertLess(pool.index("- index.html"), pool.index("+ /pool/**"))
        self.assertIn("- index.html", steps["indexes"])
        pages = steps["folder pages"]
        self.assertIn("+ index.html", pages)
        self.assertEqual(pages[-1], r2.SHORT)

    def test_top_page_goes_to_the_top_of_the_bucket(self):
        with tempfile.TemporaryDirectory() as stage:
            page = r2.write_root_page(stage)
            self.assertEqual(page, pathlib.Path(stage) / "www/index.html")
            before = page.stat().st_mtime_ns
            time.sleep(0.01)
            r2.write_root_page(stage)   # unchanged text: the file is left alone
            self.assertEqual(page.stat().st_mtime_ns, before)
            (what, cmd), = r2.root_steps(page, "raye-dl")
            self.assertEqual(cmd[:3], ["copyto", str(page), "r2:raye-dl/index.html"])
            self.assertEqual(cmd[-1], r2.SHORT)


if __name__ == "__main__":
    unittest.main()
