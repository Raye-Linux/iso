# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-windows-programs: the folder in the home where every
installed Windows program can be found, as Program Files is on Windows.

    python3 -I -m unittest discover -s release/windows/tests
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

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE.parent / "raye-windows-programs"
sys.dont_write_bytecode = True


def load():
    loader = importlib.machinery.SourceFileLoader("raye_windows_programs", str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


wp = load()


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="win-programs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.root = self.home / ".local/share/raye/windows"
        self.root.mkdir(parents=True)
        # the ready space has the folders every space starts with
        self.space(".template")

    def space(self, slug, *folders, user_programs=()):
        c = self.root / slug / "drive_c"
        for d in ("Program Files/Common Files", "Program Files/Internet Explorer", "Program Files/Windows NT",
                  "Program Files (x86)/Windows Media Player", "users/me/AppData/Local"):
            (c / d).mkdir(parents=True, exist_ok=True)
        for f in folders:
            (c / f).mkdir(parents=True, exist_ok=True)
        for f in user_programs:
            (c / "users/me/AppData/Local/Programs" / f).mkdir(parents=True, exist_ok=True)
        return c

    def sync(self, lang="C.UTF-8"):
        return wp.sync(str(self.root), str(self.home), lang)

    def links(self, folder):
        return {p.name: os.readlink(p) for p in folder.iterdir() if p.is_symlink()}

    def test_one_link_per_program(self):
        c = self.space("notepad", "Program Files/Notepad++")
        self.space("7zip", "Program Files/7-Zip")
        folder = pathlib.Path(self.sync())
        self.assertEqual(folder, self.home / "Windows programs")
        self.assertEqual(self.links(folder), {"Notepad++": str(c / "Program Files/Notepad++"),
                                              "7-Zip": str(self.root / "7zip/drive_c/Program Files/7-Zip")})
        self.assertIn("Icon=folder-windows", (folder / ".directory").read_text())

    def test_windows_own_folders_are_left_out(self):
        self.space("app", "Program Files/Common Files/Thing", "Program Files (x86)/Microsoft/EdgeWebView",
                   "Program Files (x86)/Tool")
        folder = pathlib.Path(self.sync())
        self.assertEqual(sorted(self.links(folder)), ["Tool"])

    def test_per_user_programs(self):
        self.space("sumatra", user_programs=["SumatraPDF"])
        folder = pathlib.Path(self.sync())
        self.assertEqual(sorted(self.links(folder)), ["SumatraPDF"])

    def test_french_name(self):
        self.space("notepad", "Program Files/Notepad++")
        self.assertEqual(pathlib.Path(self.sync("fr_CA.UTF-8")), self.home / "Programmes Windows")

    def test_existing_folder_keeps_its_name_whatever_the_language(self):
        self.space("notepad", "Program Files/Notepad++")
        self.sync("fr_FR.UTF-8")
        self.assertEqual(pathlib.Path(self.sync("en_US.UTF-8")), self.home / "Programmes Windows")
        self.assertFalse((self.home / "Windows programs").exists())

    def test_nothing_installed_no_folder(self):
        self.assertIsNone(self.sync())
        self.assertFalse((self.home / "Windows programs").exists())

    def test_same_name_in_two_spaces(self):
        self.space("a", "Program Files/Tool")
        self.space("b", "Program Files/Tool")
        folder = pathlib.Path(self.sync())
        self.assertEqual(sorted(self.links(folder)), ["Tool", "Tool (2)"])

    def test_uninstalled_program_goes_away(self):
        c = self.space("notepad", "Program Files/Notepad++")
        self.space("7zip", "Program Files/7-Zip")
        folder = pathlib.Path(self.sync())
        shutil.rmtree(c / "Program Files/Notepad++")
        self.sync()
        self.assertEqual(sorted(self.links(folder)), ["7-Zip"])

    def test_last_one_gone_takes_the_folder(self):
        c = self.space("notepad", "Program Files/Notepad++")
        folder = pathlib.Path(self.sync())
        shutil.rmtree(self.root / "notepad")
        self.assertIsNone(self.sync())
        self.assertFalse(folder.exists())

    def test_the_persons_own_files_are_never_touched(self):
        self.space("notepad", "Program Files/Notepad++")
        folder = pathlib.Path(self.sync())
        (folder / "notes.txt").write_text("mine")
        (folder / "elsewhere").symlink_to("/tmp")
        shutil.rmtree(self.root / "notepad")
        self.sync()
        self.assertEqual((folder / "notes.txt").read_text(), "mine")
        self.assertTrue((folder / "elsewhere").is_symlink())

    def test_hidden_spaces_are_skipped(self):
        self.space(".template", "Program Files/Ready")
        self.space(".building", "Program Files/Half")
        self.assertIsNone(self.sync())

    def test_command_line(self):
        self.space("notepad", "Program Files/Notepad++")
        env = dict(os.environ, HOME=str(self.home), LANG="C.UTF-8")
        env.pop("XDG_DATA_HOME", None)
        env.pop("LANGUAGE", None)
        r = subprocess.run([sys.executable, "-I", str(TOOL)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / "Windows programs" / "Notepad++").is_symlink())


class Runner(unittest.TestCase):
    def test_runner_keeps_the_folder_in_step(self):
        text = (HERE.parent / "raye-run-windows").read_text()
        self.assertIn("raye-windows-programs", text)

    def test_installed(self):
        paths = (HERE.parent.parent.parent / "debian" / "raye-release-paths").read_text()
        self.assertIn("release/windows/raye-windows-programs", paths)


if __name__ == "__main__":
    unittest.main()
