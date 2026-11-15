# SPDX-License-Identifier: GPL-3.0-or-later
"""The download pages say which Raye they serve.

The version comes from release.conf (RELEASE=0.2-beta reads "0.2 Beta"),
so a new release changes every title without touching the pages.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
"""
import pathlib
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
import raye_pages  # noqa: E402


class PageTitleTests(unittest.TestCase):
    def test_release_reads_as_people_say_it(self):
        self.assertEqual(raye_pages.release_label("0.2-beta"), "0.2 Beta")
        self.assertEqual(raye_pages.release_label("1.0"), "1.0")
        self.assertEqual(raye_pages.release_label("1.1-rc"), "1.1 RC")

    def test_the_label_comes_from_release_conf(self):
        with tempfile.TemporaryDirectory() as d:
            conf = pathlib.Path(d) / "release.conf"
            conf.write_text("RELEASE=0.3-beta\n")
            self.assertEqual(raye_pages.release_label(conf=conf), "0.3 Beta")

    def test_every_page_names_the_release(self):
        label = raye_pages.release_label()
        with tempfile.TemporaryDirectory() as d:
            tree = pathlib.Path(d) / "apt"
            (tree / "dists").mkdir(parents=True)
            for page in (raye_pages.root_page(),
                         raye_pages.folder_page(tree, tree, eye=""),
                         raye_pages.folder_page(tree, tree / "dists", eye="")):
                title = page.split("<title>", 1)[1].split("</title>", 1)[0]
                self.assertIn(f"Raye Linux {label}", title)
                self.assertIn(f"Raye Linux {label}", page.split("<header>", 1)[1].split("</header>", 1)[0])


if __name__ == "__main__":
    unittest.main()
