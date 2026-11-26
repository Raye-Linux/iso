# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-run-windows: raye-wine by default, another Wine only when
it is chosen and there is one, the Direct3D and NVAPI choices of
raye-wine-gpu, and the --space forms Start entries and Settings use.

    python3 -I -m unittest discover -s release/windows/tests
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
RUN = HERE.parent / "raye-run-windows"

FAKE_WINE = r"""#!/bin/sh
echo "${FAKE_SETTING-}" > "$FAKE_LOG.extra"
printf '%s|%s|%s|%s|%s\n' "$0" "${WINEDLLOVERRIDES-}" "${DXVK_ENABLE_NVAPI-}" "$*" "${RAYE_WINDOWS_APP_ID-}" >> "$FAKE_LOG"
printf 'WINEDEBUG=%s DXVK_LOG_LEVEL=%s\n' "${WINEDEBUG-}" "${DXVK_LOG_LEVEL-}" > "$FAKE_LOG.env"
pwd > "$FAKE_LOG.pwd"
printf '%s|%s|%s|%s\n' "${RAYE_GAME_SPACE-}" "${RAYE_GAME_KIND-}" "${RAYE_GAME_NAME-}" "${RAYE_GAME_IGNORE-}" > "$FAKE_LOG.game"
case "$1" in
wineboot) mkdir -p "$WINEPREFIX/drive_c" ;;
esac
exit 0
"""
FAKE_SERVER = "#!/bin/sh\nexit 0\n"
FAKE_BOOT = '#!/bin/sh\nexec "$(dirname "$0")/wine" wineboot "$@"\n'


class RunWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="run-windows-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        (self.home / ".config").mkdir(parents=True)
        self.system = self.tmp / "bin"
        self.raye = self.tmp / "raye-wine"
        for d in (self.system, self.raye / "bin", self.raye / "share" / "wine"):
            d.mkdir(parents=True)
        for d in (self.system, self.raye / "bin"):
            self.script(d / "wine", FAKE_WINE)
            self.script(d / "wineserver", FAKE_SERVER)
            self.script(d / "wineboot", FAKE_BOOT)
        (self.raye / "share" / "wine" / "wine.inf").write_text("inf\n")
        self.gpu("RAYE_WINE_OVERRIDES=''")
        self.log = self.tmp / "calls.log"
        self.log.touch()
        self.extra = self.tmp / "calls.log.extra"
        self.exe = self.tmp / "Some Tool.exe"
        self.exe.write_bytes(b"MZ")
        self.env = {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin" % self.system,
                    "LANG": "C.UTF-8", "FAKE_LOG": str(self.log),
                    "RAYE_WINE_PREFIX": str(self.raye),
                    "RAYE_WINDOWS_CONF": str(self.tmp / "etc-windows.conf"),
                    "RAYE_WINDOWS_PROFILES_PATH": str(self.tmp / "profiles"),
                    "RAYE_WINDOWS_DEFAULT_PROFILE": str(HERE.parent / "default.profile"),
                    "RAYE_WINDOWS_BIN": str(self.tmp / "private"),
                    "XDG_RUNTIME_DIR": str(self.tmp / "run")}
        (self.tmp / "profiles").mkdir()

    @staticmethod
    def script(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def gpu(self, output):
        self.script(self.raye / "bin" / "raye-wine-gpu",
                    "#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % output)

    def run_it(self, *args, rc=0, **extra):
        env = dict(self.env, **extra)
        cwd = env.pop("cwd", None)
        r = subprocess.run(["sh", str(RUN)] + list(args or [str(self.exe)]), env=env,
                           capture_output=True, text=True, timeout=60, cwd=cwd)
        self.assertEqual(r.returncode, rc, r.stderr)
        return [l.split("|") for l in self.log.read_text().splitlines()]

    def test_a_program_starts_in_its_own_folder(self):
        sub = self.tmp / "Downloads"
        sub.mkdir()
        exe = sub / "setup.exe"
        exe.write_bytes(b"MZ")
        self.run_it("setup.exe", cwd=str(sub))
        self.assertEqual((self.tmp / "calls.log.pwd").read_text().strip(), str(sub))
        self.assertEqual(self.log.read_text().splitlines()[-1].split("|")[3], str(exe))

    def test_large_address_aware_by_default_and_a_profile_can_say_no(self):
        self.script(self.raye / "bin" / "wine", FAKE_WINE.replace(
            'pwd > "$FAKE_LOG.pwd"', 'pwd > "$FAKE_LOG.pwd"; echo "${WINE_LARGE_ADDRESS_AWARE-}" > "$FAKE_LOG.laa"'))
        self.run_it()
        self.assertEqual((self.tmp / "calls.log.laa").read_text().strip(), "1")
        (self.tmp / "profiles" / "old.profile").write_text(
            'name="Old"\nmatch="old*.exe"\nenv="WINE_LARGE_ADDRESS_AWARE=0"\n')
        old = self.tmp / "old.exe"
        old.write_bytes(b"MZ")
        self.run_it(str(old))
        self.assertEqual((self.tmp / "calls.log.laa").read_text().strip(), "0")

    def test_other_wine_when_chosen(self):
        calls = self.run_it(RAYE_WINDOWS_ENGINE="system")
        self.assertTrue(calls)
        self.assertTrue(all(c[0] == str(self.system / "wine") for c in calls))
        boot, launch = calls[0], calls[-1]
        self.assertIn("mscoree,mshtml=", boot[1])
        self.assertEqual(launch[3], str(self.exe))
        self.assertEqual(launch[1], "winemenubuilder.exe=d")

    def test_choice_of_a_missing_wine_is_ignored(self):
        (self.system / "wine").unlink()
        calls = self.run_it(RAYE_WINDOWS_ENGINE="system", PATH="/usr/bin:/bin")
        self.assertTrue(all(c[0] == str(self.raye / "bin" / "wine") for c in calls))

    def test_raye_wine_by_default(self):
        calls = self.run_it()
        self.assertTrue(all(c[0] == str(self.raye / "bin" / "wine") for c in calls))
        # Mono and Gecko come with it: setting up switches nothing off
        self.assertNotIn("mscoree", calls[0][1])
        self.assertIn("winemenubuilder.exe", calls[0][1])
        self.assertEqual(calls[-1][1], "winemenubuilder.exe=d")
        self.assertEqual(calls[-1][2], "")

    def test_no_vulkan_means_builtin_direct3d(self):
        self.gpu("RAYE_WINE_OVERRIDES='d3d8,d3d9,d3d10core,d3d11,dxgi,d3d12,d3d12core=b'")
        launch = self.run_it(RAYE_WINDOWS_ENGINE="raye")[-1]
        self.assertEqual(launch[1], "winemenubuilder.exe=d;d3d8,d3d9,d3d10core,d3d11,dxgi,d3d12,d3d12core=b")

    def test_nvidia_turns_nvapi_on(self):
        self.gpu("RAYE_WINE_OVERRIDES='nvapi,nvapi64=n'\nDXVK_ENABLE_NVAPI=1")
        launch = self.run_it(RAYE_WINDOWS_ENGINE="raye", WINEDLLOVERRIDES="foo=n")[-1]
        self.assertEqual(launch[1], "winemenubuilder.exe=d;foo=n;nvapi,nvapi64=n")
        self.assertEqual(launch[2], "1")

    def test_switched_on_in_windows_conf(self):
        (self.tmp / "etc-windows.conf").write_text("engine=raye\n")
        calls = self.run_it()
        self.assertEqual(calls[-1][0], str(self.raye / "bin" / "wine"))
        (self.home / ".config" / "raye").mkdir()
        (self.home / ".config" / "raye" / "windows.conf").write_text("engine=system\n")
        self.log.write_text("")
        shutil.rmtree(self.home / ".local")
        self.assertEqual(self.run_it()[-1][0], str(self.system / "wine"))

    def test_the_share_picker_can_name_the_program(self):
        launch = self.run_it(RAYE_WINDOWS_ENGINE="raye")[-1]
        self.assertEqual(launch[4], "org.raye.windows.some_tool")
        desktop = self.home / ".local" / "share" / "applications" / "org.raye.windows.some_tool.desktop"
        text = desktop.read_text()
        self.assertIn("\nName=Some Tool\n", text)
        self.assertIn("\nNoDisplay=true\n", text)
        self.assertIn('\nExec=raye-run-windows "%s"\n' % self.exe, text)

    def test_app_ids_stay_valid(self):
        exe = self.tmp / "3D Viewer.exe"
        exe.write_bytes(b"MZ")
        self.exe = exe
        launch = self.run_it(RAYE_WINDOWS_ENGINE="raye")[-1]
        # a part of an application id cannot start with a digit
        self.assertEqual(launch[4], "org.raye.windows._3d_viewer")

    def test_no_app_id_on_the_system_layer(self):
        launch = self.run_it(RAYE_WINDOWS_ENGINE="system")[-1]
        self.assertEqual(launch[4], "")
        self.assertFalse((self.home / ".local" / "share" / "applications").exists())

    def test_not_installed_falls_back(self):
        (self.raye / "bin" / "wine").unlink()
        calls = self.run_it(RAYE_WINDOWS_ENGINE="raye")
        self.assertTrue(all(c[0] == str(self.system / "wine") for c in calls))

    def test_gpu_output_is_never_run(self):
        self.gpu("RAYE_WINE_OVERRIDES='x'; touch %s/owned\nrm -rf /nonexistent" % self.tmp)
        self.run_it(RAYE_WINDOWS_ENGINE="raye")
        self.assertFalse((self.tmp / "owned").exists())

    def make_space(self, slug):
        prefix = self.home / ".local" / "share" / "raye" / "windows" / slug
        (prefix / "drive_c").mkdir(parents=True)
        return prefix

    def test_start_entry_runs_in_its_space(self):
        self.make_space("7-zip")
        launch = self.run_it("--space", "7-zip", "--run", r"C:\Program Files\7-Zip\7zFM.exe",
                             "--args", "-x  y")[-1]
        self.assertEqual(launch[0], str(self.raye / "bin" / "wine"))
        self.assertEqual(launch[3], r"C:\Program Files\7-Zip\7zFM.exe -x y")
        self.assertEqual(launch[4], "org.raye.windows._7_zip")

    def test_program_inside_a_space_runs_there(self):
        # opened from the Windows programs folder: no new space for it
        prefix = self.make_space("7-zip")
        exe = prefix / "drive_c" / "Program Files" / "7-Zip" / "7zFM.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
        launch = self.run_it(str(exe))[-1]
        self.assertEqual(launch[3], r"C:\Program Files\7-Zip\7zFM.exe")
        self.assertEqual(launch[4], "org.raye.windows._7_zip")
        spaces = sorted(p.name for p in prefix.parent.iterdir() if not p.name.startswith("."))
        self.assertEqual(spaces, ["7-zip"])

    def test_a_setup_inside_a_space_still_gets_a_space_of_its_own_when_hidden(self):
        prefix = self.make_space(".template")
        exe = prefix / "drive_c" / "tool.exe"
        exe.write_bytes(b"MZ")
        launch = self.run_it(str(exe))[-1]
        self.assertNotIn("C:\\", launch[3])

    def test_uninstall_command_with_quotes(self):
        self.make_space("7-zip")
        launch = self.run_it("--space", "7-zip", "--uninstall",
                             r'"C:\Program Files\7-Zip\Uninstall.exe" /S',
                             "--name", "7-Zip", "--icon", "x")[-1]
        self.assertEqual(launch[3], r"C:\Program Files\7-Zip\Uninstall.exe /S")

    def test_uninstall_msi(self):
        self.make_space("tool")
        launch = self.run_it("--space", "tool", "--uninstall", "MsiExec.exe /X{1234}")[-1]
        self.assertEqual(launch[3], "MsiExec.exe /X{1234}")

    def test_uninstall_path_with_spaces_and_no_quotes(self):
        self.make_space("winrar")
        self.script(self.raye / "bin" / "wine",
                    '#!/bin/sh\nprintf "%%s|" "$@" > "%s"\n' % (self.tmp / "argv"))
        self.run_it("--space", "winrar", "--uninstall",
                    r"C:\Program Files\WinRAR\uninstall.exe")
        self.assertEqual((self.tmp / "argv").read_text(),
                         "C:\\Program Files\\WinRAR\\uninstall.exe|")

    def test_space_must_exist(self):
        self.assertEqual(self.run_it("--space", "nope", "--run", r"C:\a.exe", rc=3), [])

    def test_space_names_stay_in_the_folder(self):
        for bad in ("../x", ".template", ""):
            self.assertEqual(self.run_it("--space", bad, "--run", r"C:\a.exe", rc=2), [])

    def test_installer_gets_start_entries(self):
        tool = self.tmp / "tools"
        tool.mkdir()
        self.script(tool / "raye-windows", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "scan"))
        self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system))
        self.assertEqual((self.tmp / "scan").read_text(), "scan some-tool\n")

    def profile(self, slug, text):
        (self.tmp / "profiles" / ("%s.profile" % slug)).write_text(text)

    def titles(self, state, answer):
        tool = self.tmp / "tools"
        tool.mkdir(exist_ok=True)
        self.script(tool / "raye-windows-titles",
                    '#!/bin/sh\ncase "$1" in --state) echo %s ;; --json) cat <<\'EOF\'\n'
                    '{"why_en": "Its publisher keeps it off.", "why_fr": "Son \u00e9diteur le refuse."}\nEOF\n;; esac\n' % state)
        self.script(tool / "kdialog", '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\nexit %d\n'
                    % (self.tmp / "asked", answer))
        return "%s:%s:/usr/bin:/bin" % (tool, self.system)

    def test_blocked_game_is_named_and_not_run(self):
        self.profile("game", 'name="Game"\nmatch="gameplayer*"\ntitle="game"\n')
        self.exe = self.tmp / "GamePlayerInstaller.exe"
        self.exe.write_bytes(b"MZ")
        self.assertEqual(self.run_it(PATH=self.titles("blocked", 0)), [])
        asked = (self.tmp / "asked").read_text()
        self.assertIn("Game can't run on Raye. Its publisher keeps it off.", asked)
        self.assertIn("Open anyway", asked)
        self.assertFalse((self.home / ".local" / "share" / "raye").exists())

    def test_blocked_game_in_french(self):
        self.profile("game", 'name="Game"\nmatch="gameplayer*"\ntitle="game"\n')
        self.exe = self.tmp / "GamePlayerInstaller.exe"
        self.exe.write_bytes(b"MZ")
        self.run_it(PATH=self.titles("blocked", 0), LANG="fr_CA.UTF-8")
        asked = (self.tmp / "asked").read_text()
        self.assertIn("Game ne peut pas fonctionner sur Raye. Son \u00e9diteur le refuse.", asked)
        self.assertIn("Ouvrir quand m\u00eame", asked)

    def test_blocked_game_opens_when_asked(self):
        self.profile("game", 'name="Game"\nmatch="gameplayer*"\ntitle="game"\n')
        self.exe = self.tmp / "GamePlayerInstaller.exe"
        self.exe.write_bytes(b"MZ")
        self.assertEqual(self.run_it(PATH=self.titles("blocked", 1))[-1][3], str(self.exe))

    def test_untested_game_just_runs(self):
        self.profile("game", 'name="Game"\nmatch="gameplayer*"\ntitle="game"\n')
        self.exe = self.tmp / "GamePlayerInstaller.exe"
        self.exe.write_bytes(b"MZ")
        self.assertEqual(self.run_it(PATH=self.titles("untested", 0))[-1][3], str(self.exe))
        self.assertFalse((self.tmp / "asked").exists())

    def test_profile_found_from_the_download_folder(self):
        self.profile("pad", 'name="Pad"\nmatch="pad.*"\nnative="x"\n')
        self.exe = self.tmp / "pad.1.2.Installer.x64.exe"
        self.exe.write_bytes(b"MZ")
        tool = self.tmp / "tools"
        tool.mkdir()
        self.script(tool / "kdialog", "#!/bin/sh\ntouch %s\nexit 1\n" % (self.tmp / "asked"))
        self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system), cwd=str(self.tmp))
        self.assertTrue((self.tmp / "asked").exists())

    def test_start_entry_gets_its_profile_settings(self):
        self.profile("studio", 'name="Studio"\nmatch="studio*"\nenv="FAKE_SETTING=1"\nnative="x"\n')
        self.make_space("studio")
        tool = self.tmp / "tools"
        tool.mkdir()
        self.script(tool / "kdialog", "#!/bin/sh\ntouch %s\nexit 1\n" % (self.tmp / "asked"))
        self.run_it("--space", "studio", "--run", r"C:\a.exe",
                    PATH="%s:%s:/usr/bin:/bin" % (tool, self.system))
        self.assertEqual(self.extra.read_text(), "1\n")
        # the question about another version is for downloads, not Start entries
        self.assertFalse((self.tmp / "asked").exists())

    def game_marks(self):
        return (self.tmp / "calls.log.game").read_text().rstrip("\n").split("|")

    def test_a_game_tells_game_mode_what_it_is(self):
        self.profile("quake", 'name="Quake"\nmatch="quake*"\ngame="yes"\n')
        self.make_space("quake")
        self.run_it("--space", "quake", "--run", r"C:\Games\quake.exe")
        self.assertEqual(self.game_marks(), ["quake", "yes", "Quake", ""])
        # and the watcher is told to look
        self.assertEqual(len(list((self.tmp / "run" / "raye-game-mode" / "windows").iterdir())), 1)

    def test_a_launcher_names_its_own_programs_for_game_mode(self):
        self.profile("hub", 'name="Hub"\nmatch="hub*"\ngame="launcher"\n'
                            'launcher="Hub.exe;Hub Helper.exe"\n')
        self.make_space("hub")
        self.run_it("--space", "hub", "--run", r"C:\Hub\Hub.exe")
        self.assertEqual(self.game_marks(), ["hub", "launcher", "Hub", "hub.exe;hub helper.exe"])

    def test_any_program_can_be_marked_later_in_settings(self):
        # no profile: the space is named, Game Mode decides from Settings
        self.make_space("tool")
        self.run_it("--space", "tool", "--run", r"C:\Tools\Tool.exe")
        self.assertEqual(self.game_marks(), ["tool", "", "Tool", ""])

    def test_only_yes_or_launcher_make_a_game(self):
        self.profile("odd", 'name="Odd"\nmatch="odd*"\ngame="maybe"\n')
        self.make_space("odd")
        self.run_it("--space", "odd", "--run", r"C:\odd.exe")
        self.assertEqual(self.game_marks()[1], "")

    def test_a_windows_installer_package_is_never_a_game(self):
        msi = self.tmp / "tool.msi"
        msi.write_bytes(b"x")
        self.run_it(str(msi))
        self.assertEqual(self.game_marks(), ["", "", "", ""])

    def test_plugin_installer_goes_into_its_hosts_space(self):
        # a VST installer double-clicked on its own would get a space of its
        # own, where FL Studio never sees what it installs
        self.profile("studio", 'name="Studio"\nmatch="studio*"\nenv="FAKE_SETTING=1"\n')
        self.profile("plugins", 'name="Plugins"\nmatch="synth-*"\nspace="studio"\n')
        self.exe = self.tmp / "Synth-1.0-win64-setup.exe"
        self.exe.write_bytes(b"MZ")
        tool = self.tmp / "tools"
        tool.mkdir()
        self.script(tool / "raye-windows", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "scan"))
        launch = self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system))[-1]
        self.assertEqual(launch[3], str(self.exe))
        self.assertEqual(launch[4], "org.raye.windows.studio")
        self.assertEqual((self.tmp / "scan").read_text(), "scan studio\n")
        # it runs with the host's settings, not its own
        self.assertEqual(self.extra.read_text(), "1\n")
        spaces = self.home / ".local" / "share" / "raye" / "windows"
        self.assertEqual(sorted(p.name for p in spaces.iterdir()), ["studio"])

    def test_space_key_must_name_a_profile(self):
        self.profile("plugins", 'name="Plugins"\nmatch="synth-*"\nspace="../x"\n')
        self.exe = self.tmp / "synth-2.exe"
        self.exe.write_bytes(b"MZ")
        self.assertEqual(self.run_it()[-1][4], "org.raye.windows.plugins")

    def test_updater_left_running_does_not_stop_start_entries(self):
        # Edge WebView2's updater (FL Studio, Roblox Studio) never exits, so
        # the space never settles; the entries are made anyway
        tool = self.tmp / "tools"
        tool.mkdir()
        self.script(tool / "raye-windows", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "scan"))
        self.script(self.raye / "bin" / "wineserver",
                    '#!/bin/sh\n[ "$1" = -w ] && [ -e "%s" ] && sleep 100\nexit 0\n' % (self.tmp / "busy"))
        self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system))
        # the space is set up and up to date: nothing of ours is left to wait for
        space = self.home / ".local" / "share" / "raye" / "windows" / "some-tool"
        inf = self.raye / "share" / "wine" / "wine.inf"
        (space / ".update-timestamp").write_text("%d\r\n" % inf.stat().st_mtime)
        (self.tmp / "busy").touch()
        (self.tmp / "scan").unlink()
        calls = self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system),
                            RAYE_WINDOWS_SETTLE="2")
        self.assertEqual(calls[-1][3], str(self.exe))
        self.assertEqual((self.tmp / "scan").read_text(), "scan some-tool\n")

    def test_start_entry_does_not_wait_for_an_updater(self):
        # with the updater still running, a Start entry used to wait for it
        # before starting the program, that is forever
        prefix = self.make_space("app")
        inf = self.raye / "share" / "wine" / "wine.inf"
        (prefix / ".update-timestamp").write_text("%d\r\n" % inf.stat().st_mtime)
        self.script(self.raye / "bin" / "wineserver", '#!/bin/sh\n[ "$1" = -w ] && sleep 100\nexit 0\n')
        launch = self.run_it("--space", "app", "--run", r"C:\a.exe")[-1]
        self.assertEqual(launch[3], r"C:\a.exe")


    # --open: what a profile's opens= / files= hand to the program
    STUDIO = ('name="Studio"\nmatch="studio*"\n'
              'opens="application/x-roblox-place;x-scheme-handler/roblox-studio-auth"\n'
              'files="rbxl rbxlx"\n')

    # what Roblox Studio's installer writes, for the user only (HKCU)
    USER_REG = (
        'WINE REGISTRY Version 2\n\n'
        '[Software\\\\Classes\\\\.rbxl] 1794435216\n@="Roblox.Place"\n\n'
        '[Software\\\\Classes\\\\Roblox.Place\\\\shell\\\\Open\\\\command] 1794435216\n'
        '@="\\"C:\\\\users\\\\me\\\\Studio.exe\\" \\"%1\\""\n\n'
        '[Software\\\\Classes\\\\roblox-studio-auth\\\\shell\\\\open\\\\command] 1794435216\n'
        '@="\\"C:\\\\users\\\\me\\\\Studio.exe\\" %1"\n')

    def opener(self):
        self.profile("studio", self.STUDIO)
        (self.make_space("studio") / "user.reg").write_text(self.USER_REG)
        tool = self.tmp / "tools"
        tool.mkdir(exist_ok=True)
        self.script(tool / "xdg-mime", "#!/bin/sh\necho \"$*\" >> %s\n" % (self.tmp / "mime.log"))
        return "%s:%s:/usr/bin:/bin" % (tool, self.system)

    def test_browser_sign_in_comes_back_to_the_program(self):
        path = self.opener()
        launch = self.run_it("--space", "studio", "--open", "roblox-studio-auth:1+code+x", PATH=path)[-1]
        self.assertEqual(launch[3], r"C:\users\me\Studio.exe roblox-studio-auth:1+code+x")
        desk = (self.home / ".local/share/applications/org.raye.windows.studio.desktop").read_text()
        self.assertIn("Exec=raye-run-windows --space studio --open %u\n", desk)
        self.assertIn("MimeType=application/x-roblox-place;x-scheme-handler/roblox-studio-auth;\n", desk)
        self.assertIn("NoDisplay=true", desk)
        self.assertIn("default org.raye.windows.studio.desktop x-scheme-handler/roblox-studio-auth",
                      (self.tmp / "mime.log").read_text())

    def test_place_from_files_opens_through_windows_association(self):
        path = self.opener()
        place = self.tmp / "My Place.RBXL"
        place.write_text("x")
        launch = self.run_it("--space", "studio", "--open", place.as_uri(), PATH=path)[-1]
        # Wine's own start reads only the machine's classes: the user's
        # association is read here, and the file goes in as a Windows path
        self.assertEqual(launch[3], "%s %s" % (r"C:\users\me\Studio.exe", "Z:" + str(place).replace("/", "\\")))

    def test_nothing_registered_says_so(self):
        path = self.opener()
        (self.home / ".local/share/raye/windows/studio/user.reg").write_text("WINE REGISTRY Version 2\n")
        calls = self.run_it("--space", "studio", "--open", "roblox-studio-auth:x", rc=1, PATH=path)
        self.assertFalse([c for c in calls if "Studio.exe" in c[3]])

    def test_open_refuses_what_the_profile_does_not_name(self):
        path = self.opener()
        for what in (str(self.exe), "https://example.com/"):
            calls = self.run_it("--space", "studio", "--open", what, rc=2, PATH=path)
            self.assertFalse([c for c in calls if "Studio.exe" in c[3]], what)

    def test_no_handler_without_opens(self):
        self.profile("studio", 'name="Studio"\nmatch="studio*"\n')
        self.make_space("studio")
        self.run_it("--space", "studio", "--run", r"C:\a.exe")
        desk = self.home / ".local/share/applications/org.raye.windows.studio.desktop"
        self.assertNotIn("MimeType", desk.read_text())
        self.run_it("--space", "studio", "--open", "roblox-studio-auth:x", rc=2)


    def test_space_gets_the_current_settings_before_it_runs(self):
        # a space copied from an older ready space misses newer .reg lines
        # (WebView2 as Windows 8): the runner asks prepare to bring them
        prefix = self.make_space("7-zip")
        fake = self.tmp / "prepare"
        self.script(fake, "#!/bin/sh\necho \"$*\" >> %s\n" % (self.tmp / "prepare.log"))
        self.run_it("--space", "7-zip", "--run", r"C:\a.exe", RAYE_WINDOWS_PREPARE=str(fake))
        self.assertEqual((self.tmp / "prepare.log").read_text(), "--look %s\n" % prefix)

    def test_shortcut_starts_in_the_programs_folder(self):
        prefix = self.make_space("7-zip")
        (prefix / "drive_c/Program Files/OBS/bin").mkdir(parents=True)
        self.run_it("--space", "7-zip", "--run", r"C:\Program Files\OBS\bin\obs64.exe")
        self.assertEqual((self.tmp / "calls.log.pwd").read_text().strip(),
                         str(prefix / "drive_c/Program Files/OBS/bin"))

    def test_layer_says_nothing_by_default(self):
        self.run_it()
        self.assertEqual((self.tmp / "calls.log.env").read_text(),
                         "WINEDEBUG=-all DXVK_LOG_LEVEL=none\n")

    def test_debug_lets_it_speak(self):
        (self.tmp / "etc-windows.conf").write_text("debug=on\n")
        self.run_it()
        self.assertEqual((self.tmp / "calls.log.env").read_text(),
                         "WINEDEBUG=fixme-all DXVK_LOG_LEVEL=\n")

    def test_profile_settings_come_after_the_default(self):
        self.profile("tool", 'name="Tool"\nmatch="some*"\nenv="DXVK_LOG_LEVEL=warn"\n')
        self.run_it()
        self.assertIn("DXVK_LOG_LEVEL=warn", (self.tmp / "calls.log.env").read_text())

    def test_winetricks_comes_from_the_private_folder(self):
        private = self.tmp / "private"
        private.mkdir()
        self.script(private / "winetricks", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "tricks"))
        self.profile("tool", 'name="Tool"\nmatch="some*"\nverbs="corefonts"\n')
        self.run_it(PATH="%s:/usr/bin:/bin" % self.system)
        self.assertEqual((self.tmp / "tricks").read_text(), "-q corefonts\n")

    def ready_space(self, components):
        template = self.home / ".local/share/raye/windows/.template"
        (template / "drive_c").mkdir(parents=True)
        (template / ".raye-ready").write_text("2 x\n")
        (template / ".raye-components").write_text(components + "\n")

    def test_verbs_the_ready_space_has_are_not_fetched(self):
        private = self.tmp / "private"
        private.mkdir()
        self.script(private / "winetricks", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "tricks"))
        self.ready_space("vcrun2005 vcrun2015 vcrun2022 corefonts")
        self.profile("tool", 'name="Tool"\nmatch="some*"\nverbs="corefonts vcrun2022 gdiplus"\n')
        self.run_it(PATH="%s:/usr/bin:/bin" % self.system)
        self.assertEqual((self.tmp / "tricks").read_text(), "-q gdiplus\n")

    def test_nothing_left_to_fetch(self):
        private = self.tmp / "private"
        private.mkdir()
        self.script(private / "winetricks", '#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "tricks"))
        self.ready_space("vcrun2022 corefonts")
        self.profile("tool", 'name="Tool"\nmatch="some*"\nverbs="corefonts vcrun2022"\n')
        self.run_it(PATH="%s:/usr/bin:/bin" % self.system)
        self.assertFalse((self.tmp / "tricks").exists())

    def needs_tool(self, answer, rc=0):
        """A raye-windows-needs that writes down what it was asked about."""
        tool = self.tmp / "needs"
        self.script(tool, '#!/bin/sh\necho "$1|$2" >> "%s"\n[ -n "%s" ] && echo "%s"\nexit 0\n'
                    % (self.tmp / "needs.log", answer, answer))
        private = self.tmp / "private"
        private.mkdir(exist_ok=True)
        self.script(private / "winetricks",
                    '#!/bin/sh\necho "$*" >> "%s"\nexit %d\n' % (self.tmp / "tricks", rc))
        return {"RAYE_WINDOWS_NEEDS": str(tool), "PATH": "%s:/usr/bin:/bin" % self.system}

    def test_what_a_program_asks_for_is_added_before_it_starts(self):
        env = self.needs_tool("vb6run mfc42")
        self.run_it(**env)
        self.assertEqual((self.tmp / "tricks").read_text(), "-q vb6run mfc42\n")
        asked = (self.tmp / "needs.log").read_text().split("|")
        self.assertEqual(asked[0], str(self.exe.resolve()))
        self.assertTrue(asked[1].strip().endswith("/raye/windows/some-tool"), asked)

    def test_start_entry_program_is_read_inside_its_space(self):
        space = self.make_space("tool")
        game = space / "drive_c/Games/Old Game/game.exe"
        game.parent.mkdir(parents=True)
        game.write_bytes(b"MZ")
        env = self.needs_tool("openal")
        self.run_it("--space", "tool", "--run", r"C:\Games\Old Game\game.exe", **env)
        asked = (self.tmp / "needs.log").read_text().split("|")
        self.assertEqual(asked[0], str(space / "drive_c/Games/Old Game/game.exe"))
        self.assertEqual((self.tmp / "tricks").read_text(), "-q openal\n")

    def test_prepare_fetches_what_the_program_needs_and_does_not_start_it(self):
        # the Store gets an installed program ready while its bar still
        # runs, so the first start has nothing left to fetch
        space = self.make_space("tool")
        game = space / "drive_c/Games/Old Game/game.exe"
        game.parent.mkdir(parents=True)
        game.write_bytes(b"MZ")
        env = self.needs_tool("openal")
        calls = self.run_it("--space", "tool", "--run", r"C:\Games\Old Game\game.exe", "--prepare", **env)
        self.assertEqual((self.tmp / "tricks").read_text(), "-q openal\n")
        self.assertFalse([c for c in calls if "game.exe" in c[3]], calls)

    def test_prepare_says_when_the_fetch_failed(self):
        space = self.make_space("tool")
        game = space / "drive_c/game.exe"
        game.write_bytes(b"MZ")
        env = self.needs_tool("openal", rc=1)
        calls = self.run_it("--space", "tool", "--run", r"C:\game.exe", "--prepare", rc=4, **env)
        self.assertFalse([c for c in calls if "game.exe" in c[3]], calls)
        # a program that needs nothing is ready at once
        env = self.needs_tool("")
        self.run_it("--space", "tool", "--prepare", "--run", r"C:\game.exe", **env)

    def test_prepare_needs_a_program(self):
        self.make_space("tool")
        r = subprocess.run(["sh", str(RUN), "--space", "tool", "--prepare"], env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_a_program_that_needs_nothing_fetches_nothing(self):
        env = self.needs_tool("")
        self.run_it(**env)
        self.assertTrue((self.tmp / "needs.log").exists())
        self.assertFalse((self.tmp / "tricks").exists())

    def test_installer_package_is_not_read(self):
        msi = self.tmp / "setup.msi"
        msi.write_bytes(b"x")
        env = self.needs_tool("vb6run")
        self.run_it(str(msi), **env)
        self.assertFalse((self.tmp / "needs.log").exists())

    def test_offline_fetch_waits_before_trying_again(self):
        env = self.needs_tool("vb6run", rc=1)
        self.run_it(**env)
        self.run_it(**env)
        self.assertEqual((self.tmp / "tricks").read_text(), "-q vb6run\n")
        tried = self.home / ".local/share/raye/windows/some-tool/.raye-needs-tried"
        old = time.time() - 3600
        os.utime(tried, (old, old))
        self.run_it(**env)
        self.assertEqual((self.tmp / "tricks").read_text().count("vb6run"), 2)

    def test_a_good_fetch_clears_the_wait(self):
        env = self.needs_tool("vb6run", rc=1)
        self.run_it(**env)
        tried = self.home / ".local/share/raye/windows/some-tool/.raye-needs-tried"
        self.assertTrue(tried.exists())
        old = time.time() - 3600
        os.utime(tried, (old, old))
        env = self.needs_tool("vb6run", rc=0)
        self.run_it(**env)
        self.assertFalse(tried.exists())


    def test_space_remembers_its_profile(self):
        self.profile("tool", 'name="Tool"\nmatch="some*"\n')
        self.run_it()
        self.assertEqual((self.home / ".local/share/raye/windows/tool/.raye-profile").read_text(),
                         "tool\n")
        shutil.rmtree(self.home / ".local")
        (self.tmp / "profiles" / "tool.profile").unlink()
        self.run_it()
        self.assertFalse((self.home / ".local/share/raye/windows/some-tool/.raye-profile").exists())

    def preparing(self, **extra):
        tool = self.tmp / "tools"
        tool.mkdir(exist_ok=True)
        self.script(tool / "notify-send", '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\n' % (self.tmp / "notice"))
        self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system), **extra)
        for _ in range(50):
            if (self.tmp / "notice").exists():
                break
            time.sleep(0.1)
        return (self.tmp / "notice").read_text() if (self.tmp / "notice").exists() else ""

    def test_a_slow_setup_says_preparing(self):
        notice = self.preparing(DISPLAY=":9")
        self.assertIn("--app-name=Raye\n", notice)
        self.assertTrue(notice.endswith("\nPreparing Some Tool…\n"), notice)
        self.assertNotIn("Wine", notice)

    def test_preparing_in_french(self):
        self.assertIn("Préparation de Some Tool…", self.preparing(DISPLAY=":9", LANG="fr_CA.UTF-8"))

    def test_preparing_stays_until_the_program_starts(self):
        # it vanished after 15 s while a first space took a minute or more
        tool = self.tmp / "tools"
        tool.mkdir(exist_ok=True)
        self.script(tool / "busctl", '#!/bin/sh\necho "$@" >> "%s"\n' % (self.tmp / "closed"))
        self.script(tool / "notify-send", '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\necho 42\n' % (self.tmp / "notice"))
        self.run_it(PATH="%s:%s:/usr/bin:/bin" % (tool, self.system), DISPLAY=":9")
        notice = (self.tmp / "notice").read_text()
        self.assertIn("--expire-time=0\n", notice)
        self.assertIn("--print-id\n", notice)
        closed = (self.tmp / "closed").read_text()
        self.assertIn("CloseNotification u 42", closed)

    def test_a_ready_space_says_nothing(self):
        template = self.home / ".local/share/raye/windows/.template"
        (template / "drive_c").mkdir(parents=True)
        (template / ".raye-ready").touch()
        inf = self.raye / "share" / "wine" / "wine.inf"
        (template / ".update-timestamp").write_text("%d\r\n" % inf.stat().st_mtime)
        self.assertEqual(self.preparing(DISPLAY=":9"), "")

    def test_setup_gets_its_quiet_switches(self):
        launch = self.run_it(str(self.exe), "--args", "/S /NORESTART")[-1]
        self.assertEqual(launch[3], "%s /S /NORESTART" % self.exe)

    def test_msi_gets_its_quiet_switches(self):
        msi = self.tmp / "tool.msi"
        msi.write_bytes(b"x")
        launch = self.run_it(str(msi), "--args", "/qn")[-1]
        self.assertEqual(launch[3], "msiexec /i %s /qn" % msi)

    def test_args_without_a_value_is_refused(self):
        r = subprocess.run(["sh", str(RUN), str(self.exe), "--args"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)

    def server_that_never_settles(self):
        template = self.home / ".local/share/raye/windows/.template"
        (template / "drive_c").mkdir(parents=True)
        (template / ".raye-ready").touch()
        inf = self.raye / "share" / "wine" / "wine.inf"
        (template / ".update-timestamp").write_text("%d\r\n" % inf.stat().st_mtime)
        # "-w" waits for good, like a space that keeps an updater running;
        # "-k" ends it, the way the real one stops every process
        self.script(self.raye / "bin" / "wineserver",
                    '#!/bin/sh\necho "$*" >> "$FAKE_LOG.server"\n'
                    'case "$1" in -w) [ -f "$FAKE_LOG.stopped" ] || sleep 30 ;; '
                    '-k) touch "$FAKE_LOG.stopped" ;; esac\nexit 0\n')

    def test_a_space_that_never_settles_is_stopped_when_asked(self):
        self.server_that_never_settles()
        t = time.monotonic()
        self.run_it(RAYE_WINDOWS_SETTLE="1", RAYE_WINDOWS_SETTLE_END="stop")
        self.assertLess(time.monotonic() - t, 15)
        self.assertEqual((self.tmp / "calls.log.server").read_text().split(), ["-w", "-k", "-w"])

    def test_settling_waits_and_stops_nothing_by_default(self):
        self.server_that_never_settles()
        self.run_it(RAYE_WINDOWS_SETTLE="1")
        self.assertEqual((self.tmp / "calls.log.server").read_text().split(), ["-w"])


if __name__ == "__main__":
    unittest.main()
