# SPDX-License-Identifier: GPL-3.0-or-later
"""desktop-sources, on a tiny source package made here."""
import gzip
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True  # no __pycache__ in the repo
HAVE_TOOLS = all(shutil.which(t) for t in ("dpkg-source", "dpkg-deb", "patch"))

CHANGELOG = """demo (1.0-1) resolute; urgency=medium

  * Upstream.

 -- Someone <someone@example.org>  Mon, 02 Nov 2026 10:00:00 +0000
"""
RAYE_ENTRY = """demo (1.0-1+raye2) resolute; urgency=medium

  * Raye series.

 -- Raye Linux <bonjour@rayelinux.com>  Sun, 08 Nov 2026 10:00:00 +0000
"""
CONTROL = """Source: demo
Maintainer: Someone <someone@example.org>

Package: demo
Architecture: all
Description: demo
 demo
"""
PATCH = """Add a file.

--- /dev/null
+++ b/added
@@ -0,0 +1 @@
+raye
"""


@unittest.skipUnless(HAVE_TOOLS, "dpkg-dev and patch are needed")
class DesktopSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def make(self, dangling_link):
        t = self.tmp
        tree = t / "ubuntu" / "demo-1.0"
        tree.mkdir(parents=True)
        (tree / "file").write_text("upstream\n")
        if dangling_link:
            # upstream ships links like this one (plasma-desktop's
            # sddm-theme/components): they point nowhere in the source tree
            (tree / "components").symlink_to("../elsewhere/components")
        subprocess.run(["tar", "-C", str(t / "ubuntu"), "-cJf",
                        str(t / "ubuntu" / "demo_1.0.orig.tar.xz"), "demo-1.0"], check=True)
        (tree / "debian" / "source").mkdir(parents=True)
        (tree / "debian" / "source" / "format").write_text("3.0 (quilt)\n")
        (tree / "debian" / "changelog").write_text(CHANGELOG)
        (tree / "debian" / "control").write_text(CONTROL)
        subprocess.run(["dpkg-source", "-q", "-b", "demo-1.0"], cwd=t / "ubuntu",
                       check=True, stdout=subprocess.DEVNULL)

        desktop = t / "desktop"
        (desktop / "patches" / "demo").mkdir(parents=True)
        (desktop / "patches" / "demo" / "0001-add.patch").write_text(PATCH)
        (desktop / "components").write_text("demo 1.0-1\n")

        # the shipped binary only has to carry its changelog
        debroot = t / "debroot"
        doc = debroot / "usr" / "share" / "doc" / "demo"
        doc.mkdir(parents=True)
        (doc / "changelog.Debian.gz").write_bytes(gzip.compress(RAYE_ENTRY.encode()))
        (debroot / "DEBIAN").mkdir()
        (debroot / "DEBIAN" / "control").write_text(
            "Package: demo\nVersion: 1.0-1+raye2\nArchitecture: all\n"
            "Maintainer: x <x@example.org>\nDescription: demo\n")
        debs = t / "debs"
        debs.mkdir()
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(debroot),
                        str(debs / "demo_1.0-1+raye2_all.deb")], check=True,
                       stdout=subprocess.DEVNULL)

        # the tree the binary was built from: the source with the series on
        built = t / "built"
        subprocess.run(["dpkg-source", "-q", "-x", str(t / "ubuntu" / "demo_1.0-1.dsc"),
                        str(built)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["patch", "-p1", "--silent", "-i",
                        str(desktop / "patches" / "demo" / "0001-add.patch")],
                       cwd=built, check=True)
        log = built / "debian" / "changelog"
        log.write_text(RAYE_ENTRY + "\n" + log.read_text())
        return desktop, debs, built

    def run_tool(self, desktop, debs, built):
        env = dict(os.environ, DESKTOP=str(desktop), DESKTOP_DEBS=str(debs),
                   UBUNTU_SRC=str(self.tmp / "ubuntu"), COMPARE=f"demo={built}")
        return subprocess.run([str(TOOLS / "desktop-sources"), str(self.tmp / "out")],
                              env=env, capture_output=True, text=True)

    def test_writes_the_raye_source_package(self):
        r = self.run_tool(*self.make(dangling_link=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "out" / "demo_1.0-1+raye2.dsc").exists())

    def test_a_dangling_upstream_link_is_compared_as_a_link(self):
        # the link is the same on both sides; following it can only fail
        r = self.run_tool(*self.make(dangling_link=True))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "out" / "demo_1.0-1+raye2.dsc").exists())

    def test_a_different_tree_is_still_refused(self):
        desktop, debs, built = self.make(dangling_link=True)
        (built / "file").write_text("changed\n")
        r = self.run_tool(desktop, debs, built)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not unpack to the tree", r.stderr)
        self.assertFalse((self.tmp / "out" / "demo_1.0-1+raye2.dsc").exists())


if __name__ == "__main__":
    unittest.main()
