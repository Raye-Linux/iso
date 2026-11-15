# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-windows-prepare, raye-windows-cleanup, their units and
the two colour files, with a fake wine that only writes down what it is
asked to do.

    python3 -I -m unittest discover -s release/windows/tests
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
WINDOWS = HERE.parent
RAYE_BASE = WINDOWS.parent.parent
PREPARE = WINDOWS / "raye-windows-prepare"
CLEANUP = WINDOWS / "raye-windows-cleanup"
NIGHT = WINDOWS / "raye-night.reg"
DAY = WINDOWS / "raye-day.reg"
SERVICE = WINDOWS / "raye-windows-prepare.service"
TIMER = WINDOWS / "raye-windows-prepare.timer"
PATH_UNIT = WINDOWS / "raye-windows-prepare.path"
COMPONENTS = WINDOWS / "raye-windows-components"
VERSIONS_TXT = RAYE_BASE.parent / "raye-wine-addons" / "versions.txt"

# The question is NOT "which Wine is on this machine". A build host or
# the VM that drives the tests is the WRONG machine, and asking it made
# this check skip on every single run -- a skip nobody re-read, inside a
# green suite. The faithful question is which Wine THE IMAGE ships, read
# from its own dpkg status under RAYE_ROOT, exactly as theme/art reads
# Plasma's style names from the image rather than from the dev box.
WINE_PACKAGES = ("wine-stable", "wine-devel", "wine-staging", "wine")


def upstream_version(deb):
    """The upstream part of a dpkg version: no epoch, no revision, no
    distribution suffix. "1:11.0.0.0~resolute-1" -> "11.0.0.0", which
    addons_for() matches against the "11.0" row by prefix."""
    return deb.split(":", 1)[-1].rsplit("-", 1)[0].split("~", 1)[0]


def image_wine(root=None):
    """(package, version) of the Wine installed in the image RAYE_ROOT
    points at, or None when there is no image or it ships no Wine."""
    root = root or os.environ.get("RAYE_ROOT")
    if not root:
        return None
    status = pathlib.Path(root, "var/lib/dpkg/status")
    if not status.is_file():
        return None
    installed = {}
    for block in status.read_text(errors="replace").split("\n\n"):
        # only lines starting at column 0: a Description continuation
        # line can carry ": " too, and would overwrite Package or Version.
        fields = dict(l.split(": ", 1) for l in block.splitlines()
                      if ": " in l and not l[:1].isspace())
        if fields.get("Status", "").endswith("ok installed"):
            installed[fields.get("Package")] = fields.get("Version", "")
    for name in WINE_PACKAGES:
        if name in installed:
            return name, upstream_version(installed[name])
    return None

sys.dont_write_bytecode = True


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# The Raye palette in Windows programs (the 31 system colours). Taken from
# the Raye Night and Raye Day colour schemes of the theme; the check
# against those files runs when the theme is at hand.
PALETTE = {
    "night": {
        "ActiveBorder": "38 37 43", "ActiveTitle": "44 43 49", "AppWorkSpace": "15 14 18",
        "Background": "15 14 18", "ButtonAlternateFace": "44 43 49", "ButtonDkShadow": "10 9 13",
        "ButtonFace": "38 37 43", "ButtonHilight": "74 73 79", "ButtonLight": "54 53 59",
        "ButtonShadow": "24 23 29", "ButtonText": "241 240 244",
        "GradientActiveTitle": "44 43 49", "GradientInactiveTitle": "27 26 31",
        "GrayText": "181 179 188", "Hilight": "123 60 255", "HilightText": "255 255 255",
        "HotTrackingColor": "180 140 255", "InactiveBorder": "27 26 31",
        "InactiveTitle": "27 26 31", "InactiveTitleText": "151 148 159",
        "InfoText": "241 240 244", "InfoWindow": "42 41 47", "Menu": "42 41 47",
        "MenuBar": "20 19 24", "MenuHilight": "123 60 255", "MenuText": "241 240 244",
        "Scrollbar": "33 32 38", "TitleText": "241 240 244", "Window": "27 26 31",
        "WindowFrame": "63 62 68", "WindowText": "241 240 244",
    },
    "day": {
        "ActiveBorder": "245 244 247", "ActiveTitle": "238 237 241", "AppWorkSpace": "238 237 241",
        "Background": "238 237 241", "ButtonAlternateFace": "247 247 249",
        "ButtonDkShadow": "114 111 123", "ButtonFace": "245 244 247",
        "ButtonHilight": "255 255 255", "ButtonLight": "249 249 250",
        "ButtonShadow": "191 189 198", "ButtonText": "23 21 28",
        "GradientActiveTitle": "238 237 241", "GradientInactiveTitle": "245 244 247",
        "GrayText": "84 82 91", "Hilight": "123 60 255", "HilightText": "255 255 255",
        "HotTrackingColor": "106 47 230", "InactiveBorder": "238 237 241",
        "InactiveTitle": "245 244 247", "InactiveTitleText": "108 105 117",
        "InfoText": "23 21 28", "InfoWindow": "255 255 255", "Menu": "255 255 255",
        "MenuBar": "245 244 247", "MenuHilight": "123 60 255", "MenuText": "23 21 28",
        "Scrollbar": "238 237 241", "TitleText": "23 21 28", "Window": "251 251 252",
        "WindowFrame": "199 197 206", "WindowText": "23 21 28",
    },
}
# Windows colour -> (group, key) of the Plasma colour scheme it comes from.
# The others (frame, 3D edges, desktop) are drawn between those values.
FROM_SCHEME = {
    "night": {
        "ButtonFace": ("Colors:Button", "BackgroundNormal"),
        "ButtonAlternateFace": ("Colors:Button", "BackgroundAlternate"),
        "ButtonText": ("Colors:Button", "ForegroundNormal"),
        "Window": ("Colors:View", "BackgroundNormal"),
        "Scrollbar": ("Colors:View", "BackgroundAlternate"),
        "WindowText": ("Colors:View", "ForegroundNormal"),
        "MenuBar": ("Colors:Window", "BackgroundNormal"),
        "GrayText": ("Colors:Window", "ForegroundInactive"),
        "Hilight": ("Colors:Selection", "BackgroundNormal"),
        "HilightText": ("Colors:Selection", "ForegroundNormal"),
        "MenuHilight": ("Colors:Selection", "BackgroundNormal"),
        "HotTrackingColor": ("Colors:Window", "ForegroundLink"),
        "Menu": ("Colors:Tooltip", "BackgroundNormal"),
        "InfoWindow": ("Colors:Tooltip", "BackgroundNormal"),
        "InfoText": ("Colors:Tooltip", "ForegroundNormal"),
        "InactiveTitleText": ("Colors:Header][Inactive", "ForegroundNormal"),
    },
    "day": {
        "ButtonFace": ("Colors:Window", "BackgroundNormal"),
        "ButtonAlternateFace": ("Colors:Button", "BackgroundAlternate"),
        "ButtonText": ("Colors:Button", "ForegroundNormal"),
        "Window": ("Colors:View", "BackgroundNormal"),
        "Scrollbar": ("Colors:Window", "BackgroundAlternate"),
        "WindowText": ("Colors:View", "ForegroundNormal"),
        "MenuBar": ("Colors:Window", "BackgroundNormal"),
        "GrayText": ("Colors:Window", "ForegroundInactive"),
        "Hilight": ("Colors:Selection", "BackgroundNormal"),
        "HilightText": ("Colors:Selection", "ForegroundNormal"),
        "MenuHilight": ("Colors:Selection", "BackgroundNormal"),
        "HotTrackingColor": ("Colors:Window", "ForegroundLink"),
        "Menu": ("Colors:Tooltip", "BackgroundNormal"),
        "InfoWindow": ("Colors:Tooltip", "BackgroundNormal"),
        "InfoText": ("Colors:Tooltip", "ForegroundNormal"),
        "InactiveTitleText": ("Colors:Header][Inactive", "ForegroundNormal"),
    },
}


def parse_reg(text):
    """{section: {name: value}} of a .reg file, comments left out."""
    out, current = {}, None
    for line in text.splitlines():
        if not line.strip() or line.startswith(";"):
            continue
        if line.startswith("["):
            current = out.setdefault(line.strip("[]"), {})
        elif current is not None:
            name, value = line.split("=", 1)
            current[name.strip('"')] = value
    return out


def as_user():
    """The scripts do nothing as root; the tests may run as root."""
    mock.patch.object(os, "geteuid", return_value=1000).start()


def theme_colors_dir():
    for cand in (os.environ.get("RAYE_THEME_COLORS"),
                 str(RAYE_BASE.parents[2] / "theme" / "colors"),
                 "/usr/share/color-schemes"):
        if cand and os.path.isfile(os.path.join(cand, "RayeNight.colors")):
            return cand
    return None


class RegFiles(unittest.TestCase):
    def regs(self):
        return {"night": parse_reg(NIGHT.read_text()), "day": parse_reg(DAY.read_text())}

    def test_header_and_plain_ascii(self):
        for path in (NIGHT, DAY):
            raw = path.read_bytes()
            raw.decode("ascii")
            self.assertTrue(raw.startswith(b"Windows Registry Editor Version 5.00\n"), path)
            self.assertTrue(raw.endswith(b"\n"))

    def test_all_31_colours_from_the_palette(self):
        for name, reg in self.regs().items():
            colours = reg["HKEY_CURRENT_USER\\Control Panel\\Colors"]
            self.assertEqual(len(colours), 31, name)
            self.assertEqual({k: v.strip('"') for k, v in colours.items()}, PALETTE[name], name)
            for value in colours.values():
                parts = value.strip('"').split(" ")
                self.assertEqual(len(parts), 3)
                self.assertTrue(all(0 <= int(p) <= 255 for p in parts))

    def test_text_stays_readable(self):
        def lum(v):
            r, g, b = (int(c) / 255 for c in v.split())
            f = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
            return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]

        def contrast(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)
        for name, p in PALETTE.items():
            for fg, bg in (("WindowText", "Window"), ("ButtonText", "ButtonFace"),
                           ("MenuText", "Menu"), ("InfoText", "InfoWindow"),
                           ("HilightText", "Hilight"), ("TitleText", "ActiveTitle")):
                self.assertGreaterEqual(contrast(p[fg], p[bg]), 4.5, (name, fg, bg))
            self.assertGreaterEqual(contrast(p["GrayText"], p["ButtonFace"]), 3, name)

    def test_same_as_the_theme(self):
        d = theme_colors_dir()
        if not d:
            self.skipTest("Raye colour schemes not at hand")
        for name, file in (("night", "RayeNight.colors"), ("day", "RayeDay.colors")):
            groups = {}
            current = None
            for line in pathlib.Path(d, file).read_text().splitlines():
                if line.startswith("["):
                    current = groups.setdefault(line[1:-1], {})
                elif "=" in line and current is not None:
                    k, v = line.split("=", 1)
                    current[k] = v
            for colour, (group, key) in FROM_SCHEME[name].items():
                self.assertEqual(PALETTE[name][colour], groups[group][key].replace(",", " "),
                                 (name, colour))

    def test_settings_both_files_share(self):
        regs = self.regs()
        for name, reg in regs.items():
            light = "dword:00000001" if name == "day" else "dword:00000000"
            p = reg["HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"]
            self.assertEqual(p, {"AppsUseLightTheme": light, "SystemUsesLightTheme": light})
            self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\ThemeManager"],
                             {"ThemeActive": '"0"'})
            self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Wine\\WineDbg"],
                             {"ShowCrashDialog": "dword:00000000"})
            self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\msedgewebview2.exe"],
                             {"Version": '"win8"'})
            self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides"],
                             {"winemenubuilder.exe": '""'})
            fonts = {"Segoe UI": '"Inter"', "Segoe UI Variable": '"Inter"'}
            self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Wine\\Fonts\\Replacements"], fonts)
            self.assertEqual(reg["HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows NT\\CurrentVersion\\FontSubstitutes"], fonts)
            mask = reg["HKEY_CURRENT_USER\\Control Panel\\Desktop"]["UserPreferencesMask"]
            self.assertTrue(mask.startswith("hex:"))
            self.assertTrue(int(mask[4:].split(",")[2], 16) & 0x02, "flat menus")
            self.assertFalse([k for sec in reg.values() for k in sec if k == "MS Shell Dlg"])
        # apart from the colours and dark/light, the two files say the same
        strip = ("HKEY_CURRENT_USER\\Control Panel\\Colors",
                 "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
        self.assertEqual({k: v for k, v in regs["night"].items() if k not in strip},
                         {k: v for k, v in regs["day"].items() if k not in strip})


class VersionsTable(unittest.TestCase):
    TABLE = "# wine mono gecko shipped\n11.0 10.4.1 2.47.4 yes\n11 10.3.0 2.47.4 no\n10.0 9.4.0 2.47.4 no\n"

    def setUp(self):
        self.p = load(PREPARE, "raye_windows_prepare")

    def test_longest_prefix_on_dots(self):
        f = self.p.addons_for
        self.assertEqual(f("11.0", self.TABLE), ("10.4.1", "2.47.4"))
        self.assertEqual(f("11.0.3", self.TABLE), ("10.4.1", "2.47.4"))
        self.assertEqual(f("11.2", self.TABLE), ("10.3.0", "2.47.4"))
        self.assertEqual(f("10.0", self.TABLE), ("9.4.0", "2.47.4"))
        self.assertIsNone(f("10.01", self.TABLE))
        self.assertIsNone(f("110.0", self.TABLE))
        self.assertIsNone(f("9.0", self.TABLE))
        self.assertIsNone(f("11.0", None))

    def test_the_wine_the_image_ships_is_in_the_table(self):
        if not VERSIONS_TXT.is_file():
            self.skipTest("raye-wine-addons not next to raye-base")
        table = VERSIONS_TXT.read_text()
        shipped = [c for c in (l.split("#", 1)[0].split()
                               for l in table.splitlines())
                   if len(c) == 4 and c[3] == "yes"]
        self.assertTrue(shipped, "versions.txt marks no row as shipped, so"
                                 " raye-wine-addons ships nothing Wine can use")
        found = image_wine()
        if not found:
            self.skipTest("no image to read: point RAYE_ROOT at a mounted Raye"
                          " image (iso/tools/raye-tests --iso ...). The Wine of"
                          " the machine running the tests is the wrong machine")
        package, version = found
        addons = self.p.addons_for(version, table)
        self.assertIsNotNone(
            addons,
            "the image ships %s %s and versions.txt has no row for it, so"
            " nothing says which Mono and Gecko that Wine looks for"
            % (package, version))
        self.assertIn(
            list(addons), [[c[1], c[2]] for c in shipped],
            "the image ships %s %s, which looks for Mono %s and Gecko %s, but"
            " raye-wine-addons ships %s. Wine accepts ONLY the exact versions:"
            " it would ignore them and start without .NET and without HTML,"
            " without a word. Add the versions to raye-wine-addons (and to"
            " addons.sha256, see fetch-addons.sh --check) or pin Wine."
            % (package, version, addons[0], addons[1],
               ", ".join("Mono %s / Gecko %s" % (c[1], c[2]) for c in shipped)))


FAKE_WINE = r"""#!/bin/sh
printf '%s|%s|%s|%s\n' "${DISPLAY-unset}${WAYLAND_DISPLAY-}" "${WINEDLLOVERRIDES-}" "${WINEPREFIX-}" "$*" >> "$FAKE_LOG"
case "$1" in
--version) echo "wine-${FAKE_VERSION:-11.0}"; exit 0 ;;
wineboot)
    [ -n "${FAKE_BOOT_FAIL:-}" ] && { ln -s "$FAKE_SENTINEL" "$WINEPREFIX/link"; exit 1; }
    u="$WINEPREFIX/drive_c/users/$USER"
    mkdir -p "$WINEPREFIX/drive_c/windows/system32" "$WINEPREFIX/drive_c/windows/syswow64" \
             "$WINEPREFIX/dosdevices" "$u/Pictures" "$WINEPREFIX/drive_c/users/Public"
    ln -s / "$WINEPREFIX/dosdevices/z:"
    ln -s "$HOME/Desktop" "$u/Desktop"
    ln -s "$HOME" "$u/Documents"
    echo stuff > "$WINEPREFIX/drive_c/windows/system32/d3d11.dll"
    echo fake > "$WINEPREFIX/system.reg"
    # the layer's own runtime DLLs, marked as such, claiming Microsoft's version
    w="$WINEPREFIX/drive_c/windows"
    sxs="$w/winsxs/amd64_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.6161_none_deadbeef"
    mkdir -p "$sxs"
    for f in "$w/system32/msvcp140.dll" "$w/syswow64/msvcp140.dll" "$w/system32/msvcr120.dll" \
             "$w/system32/msvcr110.dll" "$sxs/msvcr90.dll"; do
        { head -c 64 /dev/zero; printf 'Wine builtin DLL'; } > "$f"
    done
    mkdir -p "$w/winsxs/manifests"
    echo layer > "$w/winsxs/manifests/${sxs##*/}.manifest"
    exit 0 ;;
reg)
    [ -n "${FAKE_REG_FAIL:-}" ] && exit 1
    f=$(printf '%s' "$3" | sed "s#^C:#$WINEPREFIX/drive_c#; s#\\\\#/#g")
    cat "$f" >> "$WINEPREFIX/imported.reg"
    exit 0 ;;
*)
    [ -n "${FAKE_REDIST_FAIL:-}" ] && exit 1
    f=$(printf '%s' "$1" | sed "s#^C:#$WINEPREFIX/drive_c#; s#\\\\#/#g")
    [ -f "$f" ] || exit 3
    # like Windows Installer: a file already there at the same version stays
    w="$WINEPREFIX/drive_c/windows"
    case "${f##*/}" in
    vc_redist.x64.exe) t="$w/system32/msvcp140.dll" ;;
    vc_redist.x86.exe) t="$w/syswow64/msvcp140.dll" ;;
    vcredist-2013-x64.exe) t="$w/system32/msvcr120.dll" ;;
    vcredist-2008-x64.exe) t="$w/winsxs/amd64_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.6161_none_deadbeef/msvcr90.dll" ;;
    *) t="" ;;
    esac
    case "$t" in
    */winsxs/*)
        # a side-by-side assembly already registered is left as it is
        m="$w/winsxs/manifests/$(basename "${t%/*}").manifest"
        [ -e "$m" ] && exit 0
        echo microsoft > "$m" ;;
    esac
    [ -n "$t" ] && [ ! -e "$t" ] && { mkdir -p "${t%/*}"; echo microsoft > "$t"; }
    exit 0 ;;
esac
"""
FAKE_XVFB_RUN = """#!/bin/sh
[ "$1" = -a ] && shift
DISPLAY=:xvfb exec "$@"
"""
FAKE_SERVER = """#!/bin/sh
printf 'server|%s|%s\\n' "${WINEPREFIX-}" "$*" >> "$FAKE_LOG"
"""


class Env(unittest.TestCase):
    """A home, a fake wine on the PATH and the add-ons in a temporary
    folder; the script is loaded as a module with its paths pointed there."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="prepare-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        (self.home / "Desktop").mkdir(parents=True)
        for d in ("Documents", "Images", "Musique", "Vidéos", "Téléchargements"):
            (self.home / d).mkdir()
        (self.home / ".config").mkdir()
        (self.home / ".config" / "user-dirs.dirs").write_text(
            'XDG_DESKTOP_DIR="$HOME/Desktop"\nXDG_DOCUMENTS_DIR="$HOME/Documents"\n'
            'XDG_PICTURES_DIR="$HOME/Images"\nXDG_MUSIC_DIR="$HOME/Musique"\n'
            'XDG_VIDEOS_DIR="$HOME/Vidéos"\nXDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n')
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, text in (("wine", FAKE_WINE), ("wineserver", FAKE_SERVER),
                           ("xvfb-run", FAKE_XVFB_RUN)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        (self.tmp / "share" / "wine").mkdir(parents=True)
        (self.tmp / "share" / "wine" / "wine.inf").write_text("inf\n")
        self.data = self.tmp / "wine-data"
        for d in ("mono/wine-mono-10.4.1", "gecko/wine-gecko-2.47.4-x86",
                  "gecko/wine-gecko-2.47.4-x86_64"):
            (self.data / d).mkdir(parents=True)
        self.addons = self.tmp / "addons"
        for addon, subs in (("dxvk", ("x32", "x64")), ("vkd3d-proton", ("x86", "x64"))):
            for sub in subs:
                (self.addons / addon / sub).mkdir(parents=True)
            (self.addons / addon / "VERSION").write_text("1.0\n")
        for sub in ("x32", "x64"):
            for dll in ("d3d9", "d3d11", "dxgi"):
                (self.addons / "dxvk" / sub / (dll + ".dll")).write_text(sub + dll)
        for sub in ("x86", "x64"):
            (self.addons / "vkd3d-proton" / sub / "d3d12.dll").write_text(sub)
        shutil.copy(NIGHT, self.addons)
        shutil.copy(DAY, self.addons)
        (self.addons / "versions.txt").write_text(VersionsTable.TABLE)
        self.redist = self.tmp / "redist"
        self.redist.mkdir()
        self.server = self.tmp / "srv"
        self.server.mkdir()
        self.sentinel = self.tmp / "sentinel"
        self.sentinel.mkdir()
        (self.sentinel / "keep").write_text("keep")
        self.log = self.tmp / "calls.log"
        self.log.touch()

        env = {"HOME": str(self.home), "USER": "tester", "PATH": "%s:/usr/bin:/bin" % bin_dir,
               "LANG": "C.UTF-8", "DISPLAY": ":99", "WAYLAND_DISPLAY": "wayland-0",
               "FAKE_LOG": str(self.log), "FAKE_SENTINEL": str(self.sentinel)}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        as_user()
        self.addCleanup(mock.patch.stopall)
        self.p = load(PREPARE, "raye_windows_prepare")
        self.p.ADDONS = str(self.addons)
        self.p.VERSIONS = str(self.addons / "versions.txt")
        self.p.REDIST = str(self.redist)
        self.p.WINE_DIRS = ()
        self.p.WINESERVER_GLOBS = ()
        self.p.SERVER_ROOT = str(self.server)
        self.p.WINE_DATA = str(self.data)
        # most tests drive the fake system Wine, whatever this machine has
        self.p.RAYE_WINE = str(self.tmp / "no-raye-wine")
        self.base = self.home / ".local" / "share" / "raye" / "windows"
        self.template = self.base / ".template"

    def calls(self):
        return [l.split("|") for l in self.log.read_text().splitlines()]

    def wine_calls(self):
        return [c for c in self.calls() if c[0] != "server" and c[3] != "--version"]

    def run_prepare(self):
        self.assertEqual(self.p.main([]), 0)

    def kdeglobals(self, text):
        (self.home / ".config" / "kdeglobals").write_text(text)

    def add_redist(self, good=True):
        files = {}
        for arch in ("x86", "x64"):
            name = "vc_redist.%s.exe" % arch
            (self.redist / name).write_bytes(b"MZ" + arch.encode())
            digest = hashlib.sha256(b"MZ" + arch.encode()).hexdigest()
            files[arch] = {"name": name, "sha256": digest if good else "0" * 64,
                           "version": "14.44.35211.0"}
        self.save_components(files=files)

    def save_components(self, **parts):
        path = self.redist / "components.json"
        saved = json.loads(path.read_text()) if path.exists() else {}
        saved.update(parts)
        path.write_text(json.dumps(saved))

    def add_older(self, keys):
        older = {}
        for key in keys:
            name = "vcredist-%s.exe" % key
            (self.redist / name).write_bytes(b"MZ" + key.encode())
            older[key] = {"name": name, "sha256": hashlib.sha256(b"MZ" + key.encode()).hexdigest()}
        self.save_components(older=older)


class Prepare(Env):
    def test_builds_the_ready_space_with_no_display(self):
        self.run_prepare()
        self.assertTrue((self.template / ".raye-ready").is_file())
        self.assertFalse((self.base / ".template.new").exists())
        calls = self.wine_calls()
        self.assertEqual([c[3].split()[0] for c in calls], ["wineboot", "reg"])
        for display, overrides, prefix, _ in calls:
            self.assertEqual(display, "unset")
            self.assertIn("winemenubuilder.exe=d", overrides)
            self.assertIn("winex11.drv,winewayland.drv=d", overrides)
            self.assertNotIn("mscoree", overrides)      # Mono and Gecko are there
            self.assertEqual(prefix, str(self.base / ".template.new"))
        servers = [c for c in self.calls() if c[0] == "server"]
        self.assertTrue(servers and all(c[2] == "-w" for c in servers))

    def test_colours_scale_and_addons_go_in(self):
        self.kdeglobals("[KScreen]\nScaleFactor=1.5\n")
        os.environ["XDG_SESSION_TYPE"] = "x11"
        self.run_prepare()
        reg = parse_reg((self.template / "imported.reg").read_text())
        self.assertEqual({k: v.strip('"') for k, v in
                          reg["HKEY_CURRENT_USER\\Control Panel\\Colors"].items()}, PALETTE["night"])
        self.assertEqual(reg["HKEY_CURRENT_USER\\Control Panel\\Desktop"]["LogPixels"],
                         "dword:00000090")
        self.assertEqual(reg["HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides"],
                         {"winemenubuilder.exe": '""', "d3d11": '"native"', "d3d12": '"native"',
                          "d3d9": '"native"', "dxgi": '"native"'})
        win = self.template / "drive_c" / "windows"
        self.assertEqual((win / "system32" / "d3d11.dll").read_text(), "x64d3d11")
        self.assertEqual((win / "syswow64" / "dxgi.dll").read_text(), "x32dxgi")
        self.assertEqual((win / "system32" / "d3d12.dll").read_text(), "x64")
        self.assertEqual((win / "syswow64" / "d3d12.dll").read_text(), "x86")
        self.assertFalse((win / "temp" / "raye-look.reg").exists())
        look = (self.template / ".raye-look").read_text().strip()
        self.assertEqual(look, "scheme=night reg=%s dpi=144" %
                         hashlib.sha256(NIGHT.read_bytes()).hexdigest())

    def test_folders(self):
        (self.home / "Images" / "photo.png").write_text("x")
        self.run_prepare()
        user = self.template / "drive_c" / "users" / "tester"
        desktop = user / "Desktop"
        self.assertTrue(desktop.is_dir() and not desktop.is_symlink())
        self.assertTrue((desktop / ".raye-keep").is_file())
        self.assertEqual(os.listdir(self.home / "Desktop"), [])
        for name, target in (("Documents", "Documents"), ("Pictures", "Images"),
                             ("Music", "Musique"), ("Videos", "Vidéos"),
                             ("Downloads", "Téléchargements")):
            self.assertEqual(os.readlink(user / name), str(self.home / target), name)
        self.assertTrue((self.home / "Images" / "photo.png").exists())

    def test_a_folder_with_files_is_left_alone(self):
        p = self.tmp / "space"
        user = p / "drive_c" / "users" / "tester"
        (user / "Music").mkdir(parents=True)
        (user / "Music" / "song.mp3").write_text("x")
        self.p.set_folders(str(p))
        self.assertTrue((user / "Music" / "song.mp3").is_file())
        self.assertFalse((user / "Music").is_symlink())

    def test_a_second_run_starts_nothing(self):
        self.run_prepare()
        self.log.write_text("")
        self.run_prepare()
        self.assertEqual(self.wine_calls(), [])

    def test_rebuilt_when_something_it_uses_changes(self):
        self.run_prepare()
        first = (self.template / ".raye-ready").read_text()
        for change in (lambda: (self.addons / "raye-day.reg").write_text(DAY.read_text() + "\n"),
                       lambda: (self.addons / "dxvk" / "VERSION").write_text("2.0\n"),
                       lambda: self.add_redist(),
                       lambda: os.environ.__setitem__("FAKE_VERSION", "11.0.1"),
                       lambda: (self.data / "mono" / "wine-mono-10.5.0").mkdir()):
            change()
            self.log.write_text("")
            self.run_prepare()
            self.assertIn("wineboot --init", [c[3] for c in self.wine_calls()])
            stamp = (self.template / ".raye-ready").read_text()
            self.assertNotEqual(stamp, first)
            first = stamp

    def test_visual_cpp_from_the_checked_files(self):
        self.add_redist()
        self.run_prepare()
        runs = [c[3] for c in self.wine_calls() if c[3].startswith("C:")]
        self.assertEqual(runs, ["C:\\windows\\temp\\vc_redist.x86.exe /install /quiet /norestart",
                                "C:\\windows\\temp\\vc_redist.x64.exe /install /quiet /norestart"])
        self.assertEqual(os.listdir(self.template / "drive_c" / "windows" / "temp"), [])

    def test_every_runtime_on_a_screen_nobody_sees(self):
        self.add_redist()
        self.add_older(["2010-x86", "2005-x64"])
        self.run_prepare()
        runs = [c for c in self.wine_calls() if c[3].startswith("C:")]
        self.assertEqual([c[3] for c in runs], [
            "C:\\windows\\temp\\vcredist-2005-x64.exe /q",
            "C:\\windows\\temp\\vcredist-2010-x86.exe /q",
            "C:\\windows\\temp\\vc_redist.x86.exe /install /quiet /norestart",
            "C:\\windows\\temp\\vc_redist.x64.exe /install /quiet /norestart"])
        for display, overrides, _, _ in runs:
            self.assertEqual(display, ":xvfb")
            self.assertNotIn("winex11", overrides)
        reg = (self.template / "imported.reg").read_text()
        for dll in ("msvcr80", "msvcr100", "msvcp140", "vcruntime140_1"):
            self.assertIn('"%s"="native,builtin"' % dll, reg)
        self.assertNotIn('"msvcr120"', reg)
        self.assertEqual((self.template / ".raye-components").read_text(),
                         "vcrun2005 vcrun2010 vcrun2015 vcrun2017 vcrun2019 vcrun2022\n")

    def test_runtime_replaces_the_layers_own_copies(self):
        self.add_redist()
        self.add_older(["2008-x64", "2013-x64"])
        self.run_prepare()
        w = self.template / "drive_c" / "windows"
        sxs = w / "winsxs" / "amd64_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.6161_none_deadbeef"
        for f in (w / "system32" / "msvcp140.dll", w / "syswow64" / "msvcp140.dll",
                  w / "system32" / "msvcr120.dll", sxs / "msvcr90.dll"):
            self.assertEqual(f.read_text(), "microsoft\n", f)
        self.assertEqual((w / "winsxs" / "manifests" / (sxs.name + ".manifest")).read_text(),
                         "microsoft\n")
        self.assertEqual(list(w.rglob("*.raye-layer")), [])
        # 2012 was not installed: its DLL stays the layer's
        self.assertIn(b"Wine builtin DLL", (w / "system32" / "msvcr110.dll").read_bytes())

    def test_a_failed_runtime_still_has_the_layers_copy(self):
        self.add_older(["2008-x64", "2013-x64"])
        os.environ["FAKE_REDIST_FAIL"] = "1"
        self.run_prepare()
        w = self.template / "drive_c" / "windows"
        sxs = "amd64_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.30729.6161_none_deadbeef"
        self.assertIn(b"Wine builtin DLL", (w / "system32" / "msvcr120.dll").read_bytes())
        self.assertIn(b"Wine builtin DLL", (w / "winsxs" / sxs / "msvcr90.dll").read_bytes())
        self.assertEqual((w / "winsxs" / "manifests" / (sxs + ".manifest")).read_text(), "layer\n")

    def test_core_fonts_count_as_there(self):
        self.save_components(fonts=True)
        self.run_prepare()
        self.assertEqual((self.template / ".raye-components").read_text(), "corefonts\n")

    def test_a_runtime_that_failed_keeps_wines_own(self):
        self.add_older(["2010-x86"])
        os.environ["FAKE_REDIST_FAIL"] = "1"
        self.run_prepare()
        self.assertNotIn("native,builtin", (self.template / "imported.reg").read_text())
        self.assertEqual((self.template / ".raye-components").read_text(), "\n")

    def test_no_hidden_screen_no_installers(self):
        self.p.XVFB_RUN = str(self.tmp / "no-xvfb-run")
        self.add_redist()
        self.run_prepare()
        self.assertFalse([c for c in self.wine_calls() if c[3].startswith("C:")])
        self.assertTrue((self.template / ".raye-ready").is_file())

    def test_visual_cpp_that_changed_is_not_run(self):
        self.add_redist(good=False)
        self.run_prepare()
        self.assertFalse([c for c in self.wine_calls() if c[3].startswith("C:")])
        self.assertTrue((self.template / ".raye-ready").is_file())

    def test_visual_cpp_failing_keeps_the_space(self):
        self.add_redist()
        os.environ["FAKE_REDIST_FAIL"] = "1"
        self.run_prepare()
        self.assertTrue((self.template / ".raye-ready").is_file())

    def test_no_mono_means_no_download_question(self):
        shutil.rmtree(self.data / "mono")
        self.run_prepare()
        boot = self.wine_calls()[0]
        self.assertIn(";mscoree=", boot[1])
        self.assertNotIn("mshtml", boot[1])
        os.unlink(self.addons / "versions.txt")
        self.log.write_text("")
        self.run_prepare()
        self.assertIn(";mscoree,mshtml=", self.wine_calls()[0][1])

    def test_a_failed_set_up_leaves_nothing_behind(self):
        os.environ["FAKE_BOOT_FAIL"] = "1"
        self.run_prepare()
        self.assertFalse(self.template.exists())
        self.assertFalse((self.base / ".template.new").exists())
        self.assertTrue((self.sentinel / "keep").is_file())     # a link inside is not followed
        self.assertIn("-k", [c[2] for c in self.calls() if c[0] == "server"])

    def test_failed_settings_leave_nothing_behind(self):
        os.environ["FAKE_REG_FAIL"] = "1"
        self.run_prepare()
        self.assertFalse(self.template.exists())
        self.assertFalse((self.base / ".template.new").exists())
        self.assertTrue(os.path.isdir("/"))

    def test_a_space_from_before_is_replaced_and_leftovers_go(self):
        (self.template / "drive_c").mkdir(parents=True)
        (self.template / ".raye-ready").write_text("1700000000 corefonts dxvk vkd3d\n")
        os.symlink(self.sentinel, self.template / "z:")
        for leftover in (".template.broken.42", ".template.old.43", ".template.new"):
            (self.base / leftover / "drive_c").mkdir(parents=True)
        self.run_prepare()
        self.assertTrue((self.template / "imported.reg").is_file())
        self.assertEqual(sorted(e for e in os.listdir(self.base) if e.startswith(".template")),
                         [".template"])
        self.assertTrue((self.sentinel / "keep").is_file())

    def test_one_run_at_a_time(self):
        import fcntl
        self.base.mkdir(parents=True)
        with open(self.base / ".prepare.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_prepare()
        self.assertEqual(self.calls(), [])

    def test_not_as_root(self):
        with mock.patch.object(os, "geteuid", return_value=0):
            self.run_prepare()
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.base.exists())

    def test_no_wine_no_work(self):
        os.environ["PATH"] = "/nonexistent"
        self.run_prepare()
        self.assertFalse(self.template.exists())

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.p.main(["--bogus"]), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.p.main(["--help"]), 0)
        self.assertIn("--look SPACE", out.getvalue())


class Look(Env):
    def space(self):
        p = self.tmp / "space"
        (p / "drive_c").mkdir(parents=True)
        return p

    def test_scheme_follows_plasma(self):
        self.assertEqual(self.p.scheme(), "night")
        self.kdeglobals("[General]\nColorScheme=RayeDay\n")
        self.assertEqual(self.p.scheme(), "day")
        self.kdeglobals("[General]\nColorScheme=RayeNight\n[Colors:Window]\nBackgroundNormal=250,250,250\n")
        self.assertEqual(self.p.scheme(), "night")
        self.kdeglobals("[General]\nColorScheme=BreezeLight\n[Colors:Window]\nBackgroundNormal=239,240,241\n")
        self.assertEqual(self.p.scheme(), "day")
        self.kdeglobals("[General]\nColorScheme=BreezeDark\n[Colors:Window]\nBackgroundNormal=32,35,38\n")
        self.assertEqual(self.p.scheme(), "night")
        self.kdeglobals("[Colors:Window]\nBackgroundNormal=nonsense\n")
        self.assertEqual(self.p.scheme(), "night")

    def test_system_kdeglobals_counts_after_the_persons(self):
        sysdir = self.tmp / "xdg"
        sysdir.mkdir()
        (sysdir / "kdeglobals").write_text("[General]\nColorScheme=RayeDay\n")
        os.environ["XDG_CONFIG_DIRS"] = str(sysdir)
        self.assertEqual(self.p.scheme(), "day")
        self.kdeglobals("[General]\nColorScheme=RayeNight\n")
        self.assertEqual(self.p.scheme(), "night")

    def test_log_pixels_from_the_scale(self):
        self.assertEqual(self.p.log_pixels(), 96)
        cfg = self.home / ".config" / "kwinoutputconfig.json"
        cfg.write_text(json.dumps([{"name": "outputs", "data": [{"scale": 1.25}, {"scale": 2}]},
                                   {"name": "setups", "data": [{"scale": 9}]}]))
        self.assertEqual(self.p.log_pixels(), 192)
        self.kdeglobals("[KScreen]\nScaleFactor=1.5\n")
        self.assertEqual(self.p.log_pixels(), 192)          # Wayland: KWin's screens
        os.environ["XDG_SESSION_TYPE"] = "x11"
        self.assertEqual(self.p.log_pixels(), 144)
        self.kdeglobals("[KScreen]\nScaleFactor=0.5\n")
        self.assertEqual(self.p.log_pixels(), 96)
        self.kdeglobals("[KScreen]\nScaleFactor=9\n")
        self.assertEqual(self.p.log_pixels(), 480)
        cfg.write_text("{not json")
        self.kdeglobals("")
        self.assertEqual(self.p.log_pixels(), 96)

    def test_look_only_starts_wine_when_something_changed(self):
        space = self.space()
        self.assertEqual(self.p.main(["--look", str(space)]), 0)
        self.assertEqual([c[3] for c in self.wine_calls()],
                         ["reg import C:\\windows\\temp\\raye-look.reg"])
        self.assertEqual(self.wine_calls()[0][0], "unset")
        self.assertIn("-w", [c[2] for c in self.calls() if c[0] == "server"])
        self.log.write_text("")
        self.assertEqual(self.p.main(["--look", str(space)]), 0)
        self.assertEqual(self.calls(), [])
        self.kdeglobals("[General]\nColorScheme=RayeDay\n")
        self.assertEqual(self.p.main(["--look", str(space)]), 0)
        reg = (space / "imported.reg").read_text()
        self.assertIn('"Window"="251 251 252"', reg)
        self.assertIn('"LogPixels"=dword:00000060', reg)
        self.assertTrue((space / ".raye-look").read_text().startswith("scheme=day reg="))

    def test_look_does_not_wait_for_a_running_program(self):
        space = self.space()
        st = os.stat(space)
        sock = self.server / (".wine-%d" % os.getuid()) / ("server-%x-%x" % (st.st_dev, st.st_ino))
        sock.mkdir(parents=True)
        (sock / "socket").touch()
        self.assertEqual(self.p.main(["--look", str(space)]), 0)
        self.assertNotIn("-w", [c[2] for c in self.calls() if c[0] == "server"])

    def test_look_failing_keeps_the_old_stamp(self):
        space = self.space()
        (space / ".raye-look").write_text("scheme=night reg=old dpi=96\n")
        os.environ["FAKE_REG_FAIL"] = "1"
        self.assertEqual(self.p.main(["--look", str(space)]), 1)
        self.assertEqual((space / ".raye-look").read_text(), "scheme=night reg=old dpi=96\n")

    def test_look_refuses_what_is_not_a_space(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.p.main(["--look", str(self.tmp / "nothing")]), 1)
        self.assertEqual(self.calls(), [])

    def test_ready_space_follows_the_scheme_without_a_rebuild(self):
        self.run_prepare()
        self.kdeglobals("[General]\nColorScheme=RayeDay\n")
        self.log.write_text("")
        self.run_prepare()
        self.assertEqual([c[3].split()[0] for c in self.wine_calls()], ["reg"])
        self.assertTrue((self.template / ".raye-look").read_text().startswith("scheme=day"))


class Engine(Env):
    """raye-wine by default when it is installed; another Wine through the
    environment or windows.conf, and only when there is one."""

    def setUp(self):
        super().setUp()
        self.raye = self.tmp / "raye-wine"
        (self.raye / "bin").mkdir(parents=True)
        self.raye_log = self.tmp / "raye.log"
        self.raye_log.touch()
        wrapper = "#!/bin/sh\nFAKE_VERSION=11.21 FAKE_LOG=%s exec %s \"$@\"\n" % (
            self.raye_log, self.tmp / "bin" / "wine")
        for name, target in (("wine", wrapper), ("wineserver", FAKE_SERVER)):
            (self.raye / "bin" / name).write_text(target)
            (self.raye / "bin" / name).chmod(0o755)
        data = self.raye / "share" / "wine"
        for d in ("mono/wine-mono-11.3.0", "gecko/wine-gecko-2.47.4-x86",
                  "gecko/wine-gecko-2.47.4-x86_64", "raye"):
            (data / d).mkdir(parents=True)
        (data / "wine.inf").write_text("raye inf\n")
        (data / "raye" / "versions").write_text(
            "dxvk 3.1.1\nvkd3d 3.1\nnvapi 0.9.3\nmono 11.3.0\ngecko32 2.47.4\ngecko64 2.47.4\n")
        self.p.RAYE_WINE = str(self.raye)
        self.conf = self.tmp / "etc-windows.conf"
        self.p.ENGINE_CONFS = (str(self.conf),)

    def raye_calls(self):
        return [l.split("|") for l in self.raye_log.read_text().splitlines()
                if l.split("|")[3] != "--version"]

    def test_other_wine_when_chosen(self):
        os.environ["RAYE_WINDOWS_ENGINE"] = "system"
        self.assertEqual(self.p.engine(), "system")
        self.run_prepare()
        self.assertEqual(self.raye_calls(), [])
        self.assertTrue(self.wine_calls())

    def test_choice_of_a_missing_wine_is_ignored(self):
        os.environ["RAYE_WINDOWS_ENGINE"] = "system"
        os.environ["PATH"] = "/nonexistent"
        self.assertEqual(self.p.engine(), "raye")

    def test_raye_wine_by_default(self):
        self.assertEqual(self.p.engine(), "raye")
        self.run_prepare()
        self.assertEqual(self.wine_calls(), [])
        boot = self.raye_calls()[0]
        self.assertEqual(boot[3], "wineboot --init")
        # Mono and Gecko come with raye-wine: nothing is switched off
        self.assertNotIn("mscoree", boot[1])
        self.assertNotIn("mshtml", boot[1])
        # its wine.inf puts Direct3D in: the add-ons are not copied again
        win = self.template / "drive_c" / "windows"
        self.assertEqual((win / "system32" / "d3d11.dll").read_text(), "stuff\n")
        reg = parse_reg((self.template / "imported.reg").read_text())
        self.assertNotIn("d3d11", reg.get("HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides", {}))

    def test_switching_rebuilds_the_ready_space(self):
        os.environ["RAYE_WINDOWS_ENGINE"] = "system"
        self.run_prepare()
        system = (self.template / ".raye-ready").read_text()
        del os.environ["RAYE_WINDOWS_ENGINE"]
        self.run_prepare()
        self.assertNotEqual((self.template / ".raye-ready").read_text(), system)
        self.assertEqual(self.raye_calls()[0][3], "wineboot --init")

    def test_on_from_windows_conf_the_persons_wins(self):
        self.conf.write_text("# Windows programs\nengine=raye\n")
        self.assertEqual(self.p.engine(), "raye")
        mine = self.home / ".config" / "raye"
        mine.mkdir(parents=True)
        (mine / "windows.conf").write_text("engine=system\n")
        self.assertEqual(self.p.engine(), "system")
        os.environ["RAYE_WINDOWS_ENGINE"] = "raye"
        self.assertEqual(self.p.engine(), "raye")

    def test_not_installed_falls_back(self):
        os.environ["RAYE_WINDOWS_ENGINE"] = "raye"
        (self.raye / "bin" / "wine").unlink()
        self.assertEqual(self.p.engine(), "system")
        self.run_prepare()
        self.assertEqual(self.raye_calls(), [])
        self.assertTrue(self.wine_calls())

    def test_odd_values_are_ignored(self):
        os.environ["RAYE_WINDOWS_ENGINE"] = "../../bin/sh"
        self.assertEqual(self.p.engine(), "raye")


class Icons(unittest.TestCase):
    """Start entries made by an older raye-windows get their icons again,
    once: one made before 0.5.5 could carry a 16-colour small icon."""

    def test_spaces_are_scanned_once(self):
        p = load(PREPARE, "raye_windows_prepare")
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            for space in ("fl-studio", "winrar", ".template"):
                (base / space / "drive_c").mkdir(parents=True)
            (base / "empty").mkdir()
            calls = []
            run = lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
            p.rescan_icons(str(base), run=run)
            self.assertEqual(sorted(c[2] for c in calls), ["fl-studio", "winrar"])
            self.assertTrue(all(c[:2] == ["raye-windows", "scan"] for c in calls))
            calls.clear()
            p.rescan_icons(str(base), run=run)
            self.assertEqual(calls, [])


class Cleanup(unittest.TestCase):
    MIMEAPPS = ("[Default Applications]\n"
                "text/plain=wine-extension-txt.desktop;org.kde.kate.desktop;\n"
                "application/pdf=wine-extension-pdf.desktop\n"
                "image/png=org.kde.gwenview.desktop;\n"
                "# wine-extension-keep.desktop in a comment stays\n"
                "\n[Added Associations]\n"
                "application/x-wine-extension-ini=wine-extension-ini.desktop;\n"
                "text/html=firefox.desktop;wine-protocol-ms-settings.desktop;\n")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="cleanup-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        h = self.home
        apps = h / ".local/share/applications"
        (apps / "wine/Programs/Notepad++").mkdir(parents=True)
        (apps / "wine/Programs/Notepad++/Notepad++.desktop").write_text("x")
        for name in ("wine-extension-txt.desktop", "wine-protocol-ms-settings.desktop",
                     "org.raye.mine.desktop", "winedbg-not-ours.desktop"):
            (apps / name).write_text("x")
        menus = h / ".config/menus/applications-merged"
        menus.mkdir(parents=True)
        (menus / "wine-Programs-Notepad++.menu").write_text("x")
        (menus / "kde-other.menu").write_text("x")
        dirs = h / ".local/share/desktop-directories"
        dirs.mkdir(parents=True)
        (dirs / "wine-wine.directory").write_text("x")
        (dirs / "other.directory").write_text("x")
        mime = h / ".local/share/mime/packages"
        mime.mkdir(parents=True)
        (mime / "x-wine-extension-txt.xml").write_text("x")
        (mime / "x-other.xml").write_text("x")
        (h / ".config/mimeapps.list").write_text(self.MIMEAPPS)
        os.chmod(h / ".config/mimeapps.list", 0o600)
        env = {"HOME": str(h), "PATH": "/nonexistent", "LANG": "C.UTF-8"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        as_user()
        self.addCleanup(mock.patch.stopall)
        self.c = load(CLEANUP, "raye_windows_cleanup")

    def test_removes_what_wine_made_and_nothing_else(self):
        h = self.home
        self.assertEqual(self.c.main([]), 0)
        apps = h / ".local/share/applications"
        self.assertEqual(sorted(os.listdir(apps)), ["org.raye.mine.desktop", "winedbg-not-ours.desktop"])
        self.assertEqual(os.listdir(h / ".config/menus/applications-merged"), ["kde-other.menu"])
        self.assertEqual(os.listdir(h / ".local/share/desktop-directories"), ["other.directory"])
        self.assertEqual(os.listdir(h / ".local/share/mime/packages"), ["x-other.xml"])
        self.assertEqual((h / ".config/mimeapps.list").read_text(),
                         "[Default Applications]\n"
                         "text/plain=org.kde.kate.desktop;\n"
                         "image/png=org.kde.gwenview.desktop;\n"
                         "# wine-extension-keep.desktop in a comment stays\n"
                         "\n[Added Associations]\n"
                         "text/html=firefox.desktop;\n")
        self.assertEqual(os.stat(h / ".config/mimeapps.list").st_mode & 0o777, 0o600)
        self.assertEqual((h / ".local/state/raye/windows-cleanup").read_text(), "2\n")

    def test_links_are_not_followed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "precious.desktop").write_text("x")
        apps = self.home / ".local/share/applications"
        shutil.rmtree(apps / "wine")
        os.symlink(outside, apps / "wine")
        os.symlink(outside / "precious.desktop", apps / "wine-extension-doc.desktop")
        target = self.tmp / "real-mimeapps.list"
        target.write_text(self.MIMEAPPS)
        os.unlink(self.home / ".config/mimeapps.list")
        os.symlink(target, self.home / ".config/mimeapps.list")
        self.c.main([])
        self.assertFalse(os.path.lexists(apps / "wine"))
        self.assertFalse(os.path.lexists(apps / "wine-extension-doc.desktop"))
        self.assertTrue((outside / "precious.desktop").is_file())
        self.assertEqual(target.read_text(), self.MIMEAPPS)
        self.assertTrue(os.path.islink(self.home / ".config/mimeapps.list"))

    def test_once_per_account(self):
        self.c.main([])
        apps = self.home / ".local/share/applications"
        (apps / "wine-extension-new.desktop").write_text("x")
        self.c.main([])
        self.assertTrue((apps / "wine-extension-new.desktop").exists())
        self.c.main(["--again"])
        self.assertFalse((apps / "wine-extension-new.desktop").exists())

    def test_empty_home_and_root(self):
        shutil.rmtree(self.home)
        self.home.mkdir()
        self.assertEqual(self.c.main([]), 0)
        with mock.patch.object(os, "geteuid", return_value=0):
            os.unlink(self.home / ".local/state/raye/windows-cleanup")
            self.assertEqual(self.c.main([]), 0)
        self.assertFalse((self.home / ".local/state/raye/windows-cleanup").exists())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.c.main(["--bogus"]), 2)

    def dot_wine(self):
        old = self.home / ".wine"
        prog = old / "drive_c/Program Files/Tool"
        prog.mkdir(parents=True)
        (prog / "tool.exe").write_bytes(b"MZ")
        (old / "system.reg").write_text("WINE REGISTRY Version 2\n")
        os.symlink("../drive_c", old / "c-link")
        self.c.OTHER_WINES = (str(self.tmp / "no-wine"),)
        return old

    def default(self):
        return self.home / ".local/share/raye/windows/default"

    def test_old_dot_wine_becomes_the_default_space(self):
        old = self.dot_wine()
        self.c.main([])
        self.assertFalse(os.path.lexists(old))
        self.assertEqual((self.default() / "drive_c/Program Files/Tool/tool.exe").read_bytes(), b"MZ")
        self.assertEqual(os.readlink(self.default() / "c-link"), "../drive_c")

    def test_dot_wine_moves_even_after_the_first_cleanup(self):
        self.c.main([])
        old = self.dot_wine()
        self.c.main([])
        self.assertFalse(old.exists())
        self.assertTrue(self.default().is_dir())

    def test_its_programs_get_start_entries(self):
        tools = self.tmp / "tools"
        tools.mkdir()
        (tools / "raye-windows").write_text('#!/bin/sh\necho "$*" > "%s"\n' % (self.tmp / "scan"))
        (tools / "raye-windows").chmod(0o755)
        os.environ["PATH"] = str(tools)
        self.dot_wine()
        self.c.main([])
        self.assertEqual((self.tmp / "scan").read_text(), "scan default\n")

    def test_dot_wine_stays_with_another_wine(self):
        old = self.dot_wine()
        other = self.tmp / "wine"
        other.write_text("#!/bin/sh\n")
        other.chmod(0o755)
        self.c.OTHER_WINES = (str(other),)
        self.c.main([])
        self.assertTrue((old / "drive_c/Program Files/Tool/tool.exe").exists())
        self.assertFalse(self.default().exists())

    def test_dot_wine_stays_when_default_is_taken(self):
        old = self.dot_wine()
        (self.default() / "drive_c").mkdir(parents=True)
        self.c.main([])
        self.assertTrue((old / "system.reg").exists())
        self.assertFalse((self.default() / "system.reg").exists())

    def test_dot_wine_stays_while_it_runs(self):
        old = self.dot_wine()
        with mock.patch.object(self.c, "server_running", return_value=True):
            self.c.main([])
        self.assertTrue(old.is_dir())

    def test_a_link_or_a_plain_folder_is_not_a_space(self):
        target = self.tmp / "elsewhere"
        (target / "drive_c").mkdir(parents=True)
        os.symlink(target, self.home / ".wine")
        self.c.OTHER_WINES = ()
        self.c.main([])
        self.assertTrue(os.path.islink(self.home / ".wine"))
        os.unlink(self.home / ".wine")
        (self.home / ".wine" / "notes").mkdir(parents=True)
        self.c.main([])
        self.assertTrue((self.home / ".wine" / "notes").is_dir())


class Units(unittest.TestCase):
    def ini(self, path):
        out = {}
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out.setdefault(k, []).append(v)
        return out

    def test_service(self):
        s = self.ini(SERVICE)
        self.assertEqual(s["Type"], ["oneshot"])
        self.assertEqual(s["ExecStartPre"], ["-/usr/libexec/raye-windows-cleanup"])
        self.assertEqual(s["ExecStart"], ["/usr/libexec/raye-windows-prepare"])
        self.assertNotIn("User", s)
        self.assertIn("TimeoutStartSec", s)

    def test_timer(self):
        t = self.ini(TIMER)
        self.assertEqual(t["WantedBy"], ["timers.target"])
        self.assertIn("OnStartupSec", t)
        self.assertIn("OnUnitActiveSec", t)

    def test_new_runtimes_rebuild_the_space(self):
        # the ready space follows the runtimes as soon as they land, not at the next hourly check
        u = self.ini(PATH_UNIT)
        p = load(PREPARE, "raye_windows_prepare")
        c = load(COMPONENTS, "raye_windows_components")
        self.assertEqual(p.REDIST, c.STATE_DIR)
        self.assertEqual(u["PathChanged"], [p.REDIST + "/components.json"])
        self.assertEqual(u["Unit"], ["raye-windows-prepare.service"])
        self.assertEqual(u["WantedBy"], ["paths.target"])
        debian = RAYE_BASE / "debian"
        for script, verb in (("raye-windows-apps.postinst", "enable"),
                             ("raye-windows-apps.prerm", "disable")):
            self.assertIn("systemctl --global %s raye-windows-prepare.path" % verb,
                          (debian / script).read_text())

    def test_installed_where_the_scripts_look(self):
        paths = (RAYE_BASE / "debian" / "raye-release-paths").read_text()
        p = load(PREPARE, "raye_windows_prepare")
        for src, dest in (("raye-night.reg", p.ADDONS + "/raye-night.reg"),
                          ("raye-day.reg", p.ADDONS + "/raye-day.reg"),
                          ("raye-windows-prepare", "/usr/libexec/raye-windows-prepare"),
                          ("raye-windows-cleanup", "/usr/libexec/raye-windows-cleanup"),
                          ("raye-windows-prepare.service",
                           "/usr/lib/systemd/user/raye-windows-prepare.service"),
                          ("raye-windows-prepare.timer",
                           "/usr/lib/systemd/user/raye-windows-prepare.timer"),
                          ("raye-windows-prepare.path",
                           "/usr/lib/systemd/user/raye-windows-prepare.path")):
            line = [l.split() for l in paths.splitlines()
                    if l.split()[1:2] in (["release/windows/" + src], ["?release/windows/" + src])]
            self.assertEqual(len(line), 1, src)
            self.assertEqual("/" + line[0][2], dest)
        for script in (PREPARE, CLEANUP):
            self.assertTrue(os.access(script, os.X_OK), script)
            self.assertEqual(script.read_text().splitlines()[0], "#!/usr/bin/python3 -I")


if __name__ == "__main__":
    unittest.main()
