# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows command names in a terminal (raye-windows-command), the profile
a space runs with (raye-windows-profile), and the packaging that keeps the
layer's own commands off the PATH.

    python3 -I -m unittest discover -s release/windows/tests
"""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
WINDOWS = HERE.parent
RAYE_BASE = WINDOWS.parent.parent
COMMAND = WINDOWS / "raye-windows-command"
PROFILE = WINDOWS / "raye-windows-profile"
RUN_PARSER = pathlib.Path(os.environ.get(
    "RAYE_RUN_PARSER", "/srv/raye/theme/shell/run/src/runparser.cpp"))

# what the layer installs in its own bin folder; none of these may be a
# command anyone meets
LAYER = ("wine", "wine64", "wineserver", "winecfg", "winetricks", "wineboot", "winedbg",
         "wineconsole", "winefile", "winemine", "winepath", "regsvr32", "msidb", "widl")


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def links():
    out = []
    for line in (RAYE_BASE / "debian" / "raye-windows-apps.links").read_text().splitlines():
        src, dest = line.split()
        out.append((src, dest))
    return out


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="commands-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.apps = self.tmp / "share" / "applications"
        self.apps.mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "started"
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp / "home"), "LANG": "C.UTF-8",
                    "XDG_DATA_HOME": str(self.tmp / "nothing"),
                    "XDG_DATA_DIRS": str(self.tmp / "share"),
                    "RAYE_RUN_WINDOWS": str(self.fake("raye-run-windows"))}

    def fake(self, name):
        path = self.bin / name
        path.write_text('#!/bin/sh\necho fixme:noise; echo err:noise >&2\nprintf "%%s\\n" "%s" "$@" > "%s.tmp"; mv "%s.tmp" "%s"\n'
                        % (name, self.log, self.log, self.log))
        path.chmod(0o755)
        return path

    def app(self, app_id, exec_line):
        (self.apps / (app_id + ".desktop")).write_text(
            "[Desktop Entry]\nType=Application\nName=X\nExec=%s\n\n[Desktop Action new]\nExec=wrong\n"
            % exec_line)

    def run_as(self, name, *args, rc=0, cwd=None):
        link = self.tmp / "commands" / name
        link.parent.mkdir(exist_ok=True)
        if not link.exists():
            link.symlink_to(COMMAND)
        r = subprocess.run([str(link)] + list(args), env=self.env, capture_output=True,
                           text=True, timeout=30, cwd=cwd or self.tmp)
        self.assertEqual(r.returncode, rc, r.stderr)
        return r

    def started(self):
        for _ in range(100):
            if self.log.exists():
                return self.log.read_text().splitlines()
            time.sleep(0.05)
        return None

    def test_notepad_opens_the_editor(self):
        self.app("org.kde.kwrite", "%s %%U" % self.fake("kwrite"))
        r = self.run_as("notepad")
        self.assertEqual(self.started(), ["kwrite"])
        self.assertEqual(r.stdout + r.stderr, "")

    def test_notepad_takes_files_from_here(self):
        self.app("org.kde.kwrite", "%s %%U" % self.fake("kwrite"))
        (self.tmp / "notes.txt").write_text("x")
        self.run_as("notepad", "notes.txt", "new.txt")
        self.assertEqual(self.started(), ["kwrite", str(self.tmp / "notes.txt"), str(self.tmp / "new.txt")])

    def test_the_first_app_installed_wins(self):
        self.app("org.kde.kwrite", "%s %%U" % self.fake("kwrite"))
        self.app("org.kde.kate", "%s %%U" % self.fake("kate"))
        self.run_as("wordpad")
        self.assertEqual(self.started(), ["kwrite"])

    def test_regedit_and_taskmgr(self):
        self.app("org.raye.regedit", str(self.fake("raye-regedit")))
        self.run_as("regedit")
        self.assertEqual(self.started(), ["raye-regedit"])
        self.log.unlink()
        self.app("org.raye.taskmanager", str(self.fake("raye-taskmanager")))
        self.run_as("taskmgr")
        self.assertEqual(self.started(), ["raye-taskmanager"])

    def test_control_panel_and_its_applets(self):
        self.app("org.raye.controlpanel", str(self.fake("raye-controlpanel")))
        self.app("org.raye.settings", "%s %%u" % self.fake("raye-settings"))
        self.run_as("control")
        self.assertEqual(self.started(), ["raye-controlpanel"])
        self.log.unlink()
        self.run_as("control", "mmsys.cpl")
        self.assertEqual(self.started(), ["raye-settings", "settings:system/sound"])
        self.log.unlink()
        self.run_as("control", "printers")
        self.assertEqual(self.started(), ["raye-settings", "settings:devices/printers"])
        self.log.unlink()
        self.run_as("control", "nothing.cpl")
        self.assertEqual(self.started(), ["raye-controlpanel"])
        self.log.unlink()
        self.run_as("winver")
        self.assertEqual(self.started(), ["raye-settings", "settings:system/about"])

    def test_windows_switches_are_refused(self):
        self.app("org.kde.konsole", str(self.fake("konsole")))
        r = self.run_as("cmd", "/c", "dir", rc=2)
        self.assertIn("Windows options", r.stderr)
        self.assertIsNone(self.started())

    def test_msiexec_installs_like_a_double_click(self):
        (self.tmp / "setup.msi").write_bytes(b"x")
        self.run_as("msiexec", "/i", "setup.msi")
        self.assertEqual(self.started(), ["raye-run-windows", str(self.tmp / "setup.msi")])
        r = self.run_as("msiexec", rc=2)
        self.assertIn("msiexec", r.stderr)

    def test_missing_app_is_said_in_french_too(self):
        self.env["LANG"] = "fr_FR.UTF-8"
        r = self.run_as("charmap", rc=127)
        self.assertIn("n'est pas installée", r.stderr)
        self.assertNotIn("Wine", r.stderr)


class Packaging(unittest.TestCase):
    def setUp(self):
        self.c = load(COMMAND, "raye_windows_command")

    def names(self):
        return sorted((set(self.c.APPS) | {k for k in self.c.PAGES if ":" not in k} | {"msiexec"})
                      - self.c.NO_LINK)

    def test_one_link_per_name(self):
        dests = [d for _, d in links()]
        self.assertEqual(sorted(os.path.basename(d) for d in dests), self.names())
        for src, dest in links():
            self.assertEqual(src, "usr/lib/raye/windows/raye-windows-command")
            self.assertEqual(os.path.dirname(dest), "usr/lib/raye/windows/commands")

    def test_none_is_a_command_of_the_layer(self):
        self.assertFalse(set(self.names()) & set(LAYER))

    def test_commands_come_last_on_the_path(self):
        text = (WINDOWS / "raye-windows-commands.sh").read_text()
        self.assertIn('PATH="${PATH:+$PATH:}/usr/lib/raye/windows/commands"', text)
        out = subprocess.run(["sh", "-c", '. "$1"; . "$1"; echo "$PATH"', "sh",
                              str(WINDOWS / "raye-windows-commands.sh")],
                             env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True).stdout
        self.assertEqual(out, "/usr/bin:/bin:/usr/lib/raye/windows/commands\n")

    def test_winetricks_is_taken_off_the_path(self):
        pre = (RAYE_BASE / "debian" / "raye-windows-apps.preinst").read_text()
        post = (RAYE_BASE / "debian" / "raye-windows-apps.postrm").read_text()
        divert = "--divert /usr/lib/raye/windows/bin/winetricks /usr/bin/winetricks"
        self.assertIn("--add --rename \\\n        " + divert, pre)
        self.assertIn("--remove --rename \\\n        " + divert, post)
        run = (WINDOWS / "raye-run-windows").read_text()
        self.assertIn("PATH=$PATH:${RAYE_WINDOWS_BIN:-/usr/lib/raye/windows/bin}", run)

    def test_installed_where_the_scripts_look(self):
        paths = (RAYE_BASE / "debian" / "raye-release-paths").read_text()
        for src, dest in (("raye-windows-command", "usr/lib/raye/windows/raye-windows-command"),
                          ("raye-windows-commands.sh", "etc/profile.d/raye-windows-commands.sh"),
                          ("raye-windows-profile", "usr/libexec/raye-windows-profile"),
                          ("default.profile", "usr/share/raye/windows/default.profile")):
            self.assertRegex(paths, r"\nraye-windows-apps\s+release/windows/%s\s+%s\n"
                             % (re.escape(src), re.escape(dest)))
        for script in (COMMAND, PROFILE):
            self.assertTrue(os.access(script, os.X_OK), script)

    def test_same_names_as_the_run_box(self):
        if not RUN_PARSER.is_file():
            self.skipTest("theme is not beside this tree: %s" % RUN_PARSER)
        text = RUN_PARSER.read_text()
        aliases = re.search(r"s_aliases\[\] = \{(.*?)\n\};", text, re.S).group(1)
        for names, ids in re.findall(r'\{"([^"]+)", "([^"]+)"\}', aliases):
            for n in names.split():
                if n in ("terminal", "write") or n.startswith("ms-settings:"):
                    continue
                self.assertEqual(self.c.APPS.get(n), ids, n)
        pages = re.search(r"s_pages\[\] = \{(.*?)\n\};", text, re.S).group(1)
        for names, page in re.findall(r'\{"([^"]+)", "([^"]+)"\}', pages):
            for n in names.split():
                if not n.startswith("ms-settings:"):
                    self.assertEqual(self.c.PAGES.get(n), page, n)


class ProfileState(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="profile-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.spaces = self.tmp / "spaces"
        self.profiles = self.tmp / "profiles"
        self.profiles.mkdir()
        titles = self.tmp / "titles"
        titles.write_text('#!/bin/sh\ncase "$2" in winrar) echo works ;; *) echo untested ;; esac\n')
        titles.chmod(0o755)
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp),
                    "RAYE_WINDOWS_SPACES": str(self.spaces),
                    "RAYE_WINDOWS_PROFILES_PATH": str(self.profiles),
                    "RAYE_WINDOWS_TITLES": str(titles)}
        (self.profiles / "winrar.profile").write_text(
            'name="WinRAR"\nmatch="winrar*.exe"\ntitle="winrar"\n')
        (self.profiles / "fl-studio.profile").write_text(
            'name="FL Studio"\nmatch="*flstudio*"\ntitle="fl-studio"\n')
        (self.profiles / "7-zip.profile").write_text('name="7-Zip"\nmatch="7z*.exe"\n')

    def space(self, name, marker=None):
        (self.spaces / name / "drive_c").mkdir(parents=True)
        if marker:
            (self.spaces / name / ".raye-profile").write_text(marker + "\n")

    def run_it(self, *args):
        r = subprocess.run([str(PROFILE)] + list(args), env=self.env, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_checked_title_is_optimized(self):
        self.space("winrar", "winrar")
        self.assertEqual(self.run_it(), {"winrar": {"profile": "winrar", "name": "WinRAR",
                                                    "optimized": True, "game": None}})

    def test_profile_nobody_played_through_is_not(self):
        self.space("fl-studio", "fl-studio")
        self.space("7-zip")
        got = self.run_it()
        self.assertEqual(got["fl-studio"]["profile"], "fl-studio")
        self.assertFalse(got["fl-studio"]["optimized"])
        self.assertEqual(got["7-zip"], {"profile": "7-zip", "name": "7-Zip", "optimized": False, "game": None})

    def test_unknown_program_runs_on_the_default(self):
        self.space("some-tool")
        self.space("default")
        got = self.run_it()
        self.assertEqual(got["some-tool"], {"profile": None, "name": None, "optimized": False, "game": None})
        self.assertEqual(got["default"]["profile"], None)

    def test_space_from_before_the_marker(self):
        self.space("winrar-x64-723")
        self.assertTrue(self.run_it("winrar-x64-723")["winrar-x64-723"]["optimized"])

    def test_ready_space_and_odd_names_are_left_out(self):
        (self.spaces / ".template" / "drive_c").mkdir(parents=True)
        self.space("x")
        (self.spaces / "x" / ".raye-profile").write_text("../winrar\n")
        got = self.run_it()
        self.assertEqual(list(got), ["x"])
        self.assertFalse(got["x"]["optimized"])

    def test_a_launcher_profile_says_so(self):
        # the real Battle.net profile: Game Mode for its games, from the start
        shutil.copy(HERE.parent / "profiles" / "battle-net.profile", self.profiles)
        self.space("battle-net", "battle-net")
        self.assertEqual(self.run_it()["battle-net"]["game"], "launcher")

    def test_no_spaces_at_all(self):
        self.assertEqual(self.run_it(), {})


if __name__ == "__main__":
    unittest.main()
