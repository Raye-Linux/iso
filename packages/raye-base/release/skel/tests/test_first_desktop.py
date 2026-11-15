"""A new account's first desktop (GP-45).

The account is made the way useradd -m makes it (a copy of release/skel)
in a temporary home, then its first sign-in step runs with the real
xdg-user-dirs tools in English and in French: Windows' six folders in
the account's language, no Templates or Public in the home, the Recycle
Bin on the desktop, and nothing of the step left behind.

    python3 -m pytest release/skel/tests/test_first_desktop.py
"""

import configparser
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

HERE = pathlib.Path(__file__).resolve().parent
SKEL = HERE.parent
DEFAULTS = SKEL.parent / "xdg" / "user-dirs.defaults"
STAGE = ".local/share/raye/first-desktop"
UNITS = ".config/systemd/user"
UNIT = "raye-first-desktop.service"
WANTS = "graphical-session-pre.target.wants"

WINDOWS_EN = ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]
WINDOWS_FR = ["Bureau", "Documents", "Images", "Musique", "Téléchargements", "Vidéos"]

HAVE_XDG = shutil.which("xdg-user-dirs-update") and shutil.which("xdg-user-dir")


def french_missing() -> str:
    """What is missing for the French run, or "" when nothing is.

    🚨 This used to be `french_catalog()`, and it asked half the question.
    The catalogue is what `xdg-user-dirs` installs; translating anything
    also needs the **locale to be compiled**, which is a separate step
    (`locale-gen`) that no package does for you.

    Measured 2026-11-06 on the build machine: installing `xdg-user-dirs` put the
    catalogue there, the gate said yes, and the test FAILED -- with
    `['Desktop', 'Documents', ...] != ['Bureau', 'Documents', ...]`, a
    diff that reads like Raye's first-sign-in step forgetting to localise
    anything, when the real answer was `fr_FR.UTF-8` not being generated.
    `setlocale` fails on a locale that is not compiled and gettext falls
    straight back to C, in silence.

    A gate that checks one of the two things it needs turns a missing
    machine dependency into an accusation against the product.
    """
    if not any(pathlib.Path(base, "fr/LC_MESSAGES/xdg-user-dirs.mo").exists()
               for base in ("/usr/share/locale-langpack", "/usr/share/locale")):
        return "French xdg-user-dirs catalogue missing"
    try:
        have = subprocess.run(["locale", "-a"], capture_output=True,
                              text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return "cannot ask locale -a what is compiled"
    if not any(n.lower().replace("-", "").startswith("fr_fr.utf8")
               for n in have):
        return "fr_FR.UTF-8 is not generated (locale-gen), so gettext falls back to C"
    return ""


class FrenchGate(unittest.TestCase):
    """The gate above, on both halves of the question.

    Worth freezing because the failure it caused was not "a test skipped
    when it should not have": it was a RED that blamed the product for a
    machine's missing locale.
    """

    def test_it_names_the_locale_when_only_the_catalogue_is_there(self):
        with unittest.mock.patch.object(
                subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout="C\nC.utf8\nPOSIX\n")):
            with unittest.mock.patch.object(
                    pathlib.Path, "exists", lambda self: True):
                why = french_missing()
        self.assertIn("locale-gen", why)

    def test_it_names_the_catalogue_when_that_is_what_is_missing(self):
        with unittest.mock.patch.object(
                pathlib.Path, "exists", lambda self: False):
            self.assertIn("catalogue", french_missing())

    def test_nothing_is_missing_when_both_are_there(self):
        with unittest.mock.patch.object(
                subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout="C\nfr_FR.utf8\n")):
            with unittest.mock.patch.object(
                    pathlib.Path, "exists", lambda self: True):
                self.assertEqual(french_missing(), "")


def visible(home: pathlib.Path) -> list[str]:
    return sorted(p.name for p in home.iterdir() if not p.name.startswith("."))


def read_dirs(home: pathlib.Path) -> dict[str, str]:
    values = {}
    for line in (home / ".config/user-dirs.dirs").read_text().splitlines():
        if line.startswith("XDG_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


class Account:
    """A home made from release/skel, with the system's xdg settings."""

    def __init__(self, lang: str, path: str | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.home = root / "home"
        # useradd -m copies the tree as it is, symlinks included
        shutil.copytree(SKEL, self.home, symlinks=True,
                        ignore=shutil.ignore_patterns("tests"))
        self.conf = root / "xdg"
        self.conf.mkdir()
        shutil.copy(DEFAULTS, self.conf / "user-dirs.defaults")
        (self.conf / "user-dirs.conf").write_text("enabled=True\nfilename_encoding=UTF-8\n")
        self.env = {
            "HOME": str(self.home),
            "LANG": lang,
            "LANGUAGE": "",
            "XDG_CONFIG_DIRS": str(self.conf),
            "PATH": path or "/usr/bin:/bin",
        }

    def first_sign_in(self) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/sh", str(self.home / STAGE / "setup")],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def close(self):
        self.tmp.cleanup()


class SkelTree(unittest.TestCase):
    """What useradd copies into every new home."""

    def test_no_desktop_folder_in_skel(self):
        # A Desktop/ folder in the new home makes xdg-user-dirs keep that
        # English name for every language (no "Bureau" in French).
        self.assertFalse((SKEL / "Desktop").exists())
        self.assertEqual(visible(SKEL), ["tests"])

    def test_unit_is_enabled_by_a_relative_link(self):
        link = SKEL / UNITS / WANTS / UNIT
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), f"../{UNIT}")
        self.assertTrue(link.resolve().samefile(SKEL / UNITS / UNIT))

    def test_unit_runs_once_before_the_folders_and_the_shell(self):
        unit = configparser.ConfigParser(strict=False, interpolation=None)
        unit.optionxform = str
        unit.read(SKEL / UNITS / UNIT)
        before = unit["Unit"]["Before"].split()
        self.assertIn("xdg-user-dirs.service", before)
        self.assertIn("graphical-session-pre.target", before)
        self.assertEqual(unit["Unit"]["ConditionPathExists"], f"%h/{STAGE}/setup")
        self.assertEqual(unit["Service"]["Type"], "oneshot")
        self.assertEqual(unit["Service"]["ExecStart"], f"/bin/sh %h/{STAGE}/setup")
        self.assertEqual(unit["Install"]["WantedBy"], "graphical-session-pre.target")

    def test_recycle_bin_link(self):
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read(SKEL / STAGE / "trash.desktop", encoding="utf-8")
        d = entry["Desktop Entry"]
        self.assertEqual(d["Type"], "Link")
        self.assertEqual(d["URL"], "trash:/")
        self.assertEqual(d["Name"], "Recycle Bin")
        self.assertEqual(d["Name[fr]"], "Corbeille")
        self.assertEqual(d["Icon"], "user-trash-full")
        self.assertEqual(d["EmptyIcon"], "user-trash")
        self.assertIn("Comment[fr]", d)

    @unittest.skipUnless(shutil.which("desktop-file-validate"), "desktop-file-validate missing")
    def test_recycle_bin_link_validates(self):
        out = subprocess.run(["desktop-file-validate", str(SKEL / STAGE / "trash.desktop")],
                             capture_output=True, text=True)
        # EmptyIcon is KDE's own key; anything else is a real error
        errors = [l for l in out.stdout.splitlines() if "error" in l and "EmptyIcon" not in l]
        self.assertEqual(errors, [])

    def test_templates_and_public_out_of_sight(self):
        values = read_dirs(SKEL)
        self.assertEqual(values, {
            "XDG_TEMPLATES_DIR": "$HOME/.local/share/templates",
            "XDG_PUBLICSHARE_DIR": "$HOME/.local/share/public",
        })

    def test_system_defaults_are_the_windows_set(self):
        keys = {}
        for line in DEFAULTS.read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                keys[key] = value
        self.assertEqual(keys, {
            "DESKTOP": "Desktop", "DOWNLOAD": "Downloads", "DOCUMENTS": "Documents",
            "PICTURES": "Pictures", "MUSIC": "Music", "VIDEOS": "Videos",
        })

    def test_setup_has_no_rm_r(self):
        # it removes its own files by name, nothing recursive in a home
        text = (SKEL / STAGE / "setup").read_text()
        self.assertNotIn("rm -r", text)
        self.assertNotIn("rm -fr", text)


@unittest.skipUnless(HAVE_XDG, "xdg-user-dirs is not installed")
class FirstSignIn(unittest.TestCase):

    def account(self, lang, **kw):
        acc = Account(lang, **kw)
        self.addCleanup(acc.close)
        return acc

    def assert_cleaned_up(self, home):
        self.assertFalse((home / STAGE).exists())
        self.assertFalse((home / ".local/share/raye").exists())
        self.assertFalse((home / ".config/systemd").exists())

    def assert_bin_on(self, desktop):
        link = desktop / "trash.desktop"
        self.assertTrue(link.is_file())
        self.assertEqual(link.read_bytes(), (SKEL / STAGE / "trash.desktop").read_bytes())
        self.assertEqual([p.name for p in desktop.iterdir()], ["trash.desktop"])

    def test_english_account(self):
        acc = self.account("en_US.UTF-8")
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        home = acc.home
        self.assertEqual(visible(home), WINDOWS_EN)
        self.assert_bin_on(home / "Desktop")
        values = read_dirs(home)
        self.assertEqual(values["XDG_DESKTOP_DIR"], "$HOME/Desktop")
        self.assertEqual(values["XDG_TEMPLATES_DIR"], "$HOME/.local/share/templates")
        self.assertEqual(values["XDG_PUBLICSHARE_DIR"], "$HOME/.local/share/public")
        self.assertTrue((home / ".local/share/templates").is_dir())
        self.assertTrue((home / ".local/share/public").is_dir())
        self.assert_cleaned_up(home)

    @unittest.skipIf(french_missing(), french_missing())
    def test_french_account(self):
        acc = self.account("fr_FR.UTF-8")
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        home = acc.home
        self.assertEqual(visible(home), WINDOWS_FR)
        self.assert_bin_on(home / "Bureau")
        values = read_dirs(home)
        self.assertEqual(values["XDG_DESKTOP_DIR"], "$HOME/Bureau")
        self.assertEqual(values["XDG_DOWNLOAD_DIR"], "$HOME/Téléchargements")
        self.assertEqual(values["XDG_TEMPLATES_DIR"], "$HOME/.local/share/templates")
        self.assertEqual(values["XDG_PUBLICSHARE_DIR"], "$HOME/.local/share/public")
        self.assertFalse((home / ".local/partage").exists())
        self.assert_cleaned_up(home)

    def test_xdg_service_after_it_changes_nothing(self):
        # xdg-user-dirs.service runs right after the step: same folders
        acc = self.account("en_US.UTF-8")
        acc.first_sign_in()
        before = read_dirs(acc.home)
        subprocess.run(["xdg-user-dirs-update"], env=acc.env, check=True)
        self.assertEqual(visible(acc.home), WINDOWS_EN)
        self.assertEqual(read_dirs(acc.home), before)

    def test_own_link_is_kept(self):
        acc = self.account("en_US.UTF-8")
        (acc.home / "Desktop").mkdir()
        (acc.home / "Desktop/trash.desktop").write_text("mine\n")
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((acc.home / "Desktop/trash.desktop").read_text(), "mine\n")
        self.assert_cleaned_up(acc.home)

    def test_desktop_turned_off(self):
        # a desktop folder set to the home itself: no link dropped in the home
        acc = self.account("en_US.UTF-8")
        with open(acc.home / ".config/user-dirs.dirs", "a") as f:
            f.write('XDG_DESKTOP_DIR="$HOME/"\n')
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((acc.home / "trash.desktop").exists())
        self.assertFalse((acc.home / "Desktop").exists())
        self.assert_cleaned_up(acc.home)

    def test_home_with_spaces_and_accents(self):
        acc = self.account("en_US.UTF-8")
        odd = acc.home.parent / "Zoé Dupont"
        acc.home.rename(odd)
        acc.home = odd
        acc.env["HOME"] = str(odd)
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assert_bin_on(odd / "Desktop")
        self.assert_cleaned_up(odd)


class WithoutXdgTools(unittest.TestCase):
    """xdg-user-dirs removed: the bin still lands on ~/Desktop."""

    def test_falls_back_to_desktop(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bin_dir = pathlib.Path(tmp.name) / "bin"
        bin_dir.mkdir()
        for tool in ("sh", "mkdir", "cp", "rm", "rmdir", "cat"):
            found = shutil.which(tool)
            if found:
                (bin_dir / tool).symlink_to(found)
        acc = Account("en_US.UTF-8", path=str(bin_dir))
        self.addCleanup(acc.close)
        res = acc.first_sign_in()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((acc.home / "Desktop/trash.desktop").is_file())
        self.assertFalse((acc.home / STAGE).exists())


if __name__ == "__main__":
    unittest.main()
