# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-windows-needs: what a program asks for that a space does
not have yet, read from the program itself. The programs here are small
PE files made by pe() below, with the imports and the .NET header a real
compiler would write.

    python3 -I -m unittest discover -s release/windows/tests
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
NEEDS = HERE.parent / "raye-windows-needs"


def load():
    loader = importlib.machinery.SourceFileLoader("raye_windows_needs", str(NEEDS))
    spec = importlib.util.spec_from_loader("raye_windows_needs", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def pe(imports=(), delayed=(), bits=32, clr=False):
    """A PE file with one section holding its import names, the way a
    linker lays them out: descriptors, then the DLL names."""
    sect_rva, sect_off, align = 0x1000, 0x200, 0x200
    body = bytearray()
    names = {}
    for dll in list(imports) + list(delayed):
        names[dll] = len(body)
        body += dll.encode() + b"\0"
    while len(body) % 4:
        body += b"\0"
    imp_at = len(body)
    for dll in imports:
        # OriginalFirstThunk, TimeDateStamp, ForwarderChain, Name, FirstThunk
        body += struct.pack("<5I", 0, 0, 0, sect_rva + names[dll], 0)
    body += b"\0" * 20
    delay_at = len(body)
    for dll in delayed:
        body += struct.pack("<8I", 1, sect_rva + names[dll], 0, 0, 0, 0, 0, 0)
    body += b"\0" * 32
    clr_at = len(body)
    if clr:
        body += struct.pack("<IHH", 72, 2, 5) + b"\0" * 64
    while len(body) % align:
        body += b"\0"

    dirs = [(0, 0)] * 16
    if imports:
        dirs[1] = (sect_rva + imp_at, 20 * (len(imports) + 1))
    if delayed:
        dirs[13] = (sect_rva + delay_at, 32 * (len(delayed) + 1))
    if clr:
        dirs[14] = (sect_rva + clr_at, 72)
    if bits == 64:
        opt = struct.pack("<HBBIIIII", 0x20b, 14, 0, len(body), 0, 0, 0x1000, 0x1000)
        opt += struct.pack("<QIIHHHHHHIIIIHHQQQQII", 0x140000000, 0x1000, align, 6, 0, 0, 0,
                           6, 0, 0, sect_rva + len(body), align, 0, 3, 0x8160,
                           0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    else:
        opt = struct.pack("<HBBIIIIII", 0x10b, 14, 0, len(body), 0, 0, 0x1000, 0x1000, 0)
        opt += struct.pack("<IIIHHHHHHIIIIHHIIIIII", 0x400000, 0x1000, align, 6, 0, 0, 0,
                           6, 0, 0, sect_rva + len(body), align, 0, 2, 0x8140,
                           0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    opt += b"".join(struct.pack("<II", *d) for d in dirs)
    machine = 0x8664 if bits == 64 else 0x14c
    head = struct.pack("<4sHHIIIHH", b"PE\0\0", machine, 1, 0, 0, 0, len(opt), 0x0102)
    section = struct.pack("<8sIIIIIIHHI", b".rdata", len(body), sect_rva, len(body), sect_off,
                          0, 0, 0, 0, 0x40000040)
    dos = bytearray(b"MZ" + b"\0" * 0x3e)
    dos[0x3c:0x40] = struct.pack("<I", 0x40)
    headers = bytes(dos) + head + opt + section
    return headers + b"\0" * (sect_off - len(headers)) + bytes(body)


class Reading(unittest.TestCase):
    """The PE reader on its own."""

    def setUp(self):
        self.mod = load()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="needs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = self.tmp / name
        path.write_bytes(data)
        return path

    def test_imports_of_a_32_bit_program(self):
        path = self.write("a.exe", pe(["KERNEL32.dll", "MSVBVM60.DLL"]))
        self.assertEqual(self.mod.read_pe(path).imports, {"kernel32.dll", "msvbvm60.dll"})

    def test_imports_of_a_64_bit_program(self):
        path = self.write("a.exe", pe(["mfc42u.dll", "user32.dll"], bits=64))
        info = self.mod.read_pe(path)
        self.assertEqual(info.imports, {"mfc42u.dll", "user32.dll"})
        self.assertEqual(info.bits, 64)

    def test_delay_loaded_dlls_count_too(self):
        path = self.write("a.exe", pe(["kernel32.dll"], delayed=["OpenAL32.dll"]))
        self.assertIn("openal32.dll", self.mod.read_pe(path).imports)

    def test_dotnet_header_is_seen(self):
        self.assertTrue(self.mod.read_pe(self.write("a.exe", pe(["mscoree.dll"], clr=True))).dotnet)
        self.assertFalse(self.mod.read_pe(self.write("b.exe", pe(["mscoree.dll"]))).dotnet)

    def test_not_a_program(self):
        self.assertIsNone(self.mod.read_pe(self.write("a.exe", b"hello")))
        self.assertIsNone(self.mod.read_pe(self.write("b.exe", b"MZ" + b"\xff" * 200)))
        self.assertIsNone(self.mod.read_pe(self.tmp / "missing.exe"))

    def test_broken_import_table_is_not_followed(self):
        data = bytearray(pe(["msvbvm60.dll"]))
        # point the import directory far past the end of the file
        at = 0x40 + 24 + 96 + 8
        data[at:at + 4] = struct.pack("<I", 0x7fff0000)
        self.assertEqual(self.mod.read_pe(self.write("a.exe", bytes(data))).imports, set())


class Needs(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="needs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = self.tmp / "Program Files" / "Tool"
        self.app.mkdir(parents=True)
        self.space = self.tmp / "space"
        self.space.mkdir()

    def needs(self, exe, space=True):
        return self.mod.needs(exe, self.space if space else None)

    def exe(self, *imports, name="Tool.exe", **kw):
        path = self.app / name
        path.write_bytes(pe(imports, **kw))
        return path

    def test_visual_basic_6_program(self):
        self.assertEqual(self.needs(self.exe("msvbvm60.dll", "kernel32.dll")), ["vb6run"])

    def test_visual_basic_5_program(self):
        self.assertEqual(self.needs(self.exe("MSVBVM50.DLL")), ["vb5run"])

    def test_mfc_6_program(self):
        self.assertEqual(self.needs(self.exe("MFC42.DLL")), ["mfc42"])
        self.assertEqual(self.needs(self.exe("mfc42u.dll", name="U.exe")), ["mfc42"])

    def test_openal_game_that_ships_its_own_is_left_alone(self):
        exe = self.exe("OpenAL32.dll")
        self.assertEqual(self.needs(exe), ["openal"])
        (self.app / "openal32.DLL").write_bytes(b"MZ")
        self.assertEqual(self.needs(exe), [])

    def test_physx_loader(self):
        self.assertEqual(self.needs(self.exe("PhysXLoader.dll")), ["physx"])

    def test_a_dll_next_to_the_program_can_ask_too(self):
        exe = self.exe("kernel32.dll")
        (self.app / "audio.dll").write_bytes(pe(["openal32.dll"]))
        self.assertEqual(self.needs(exe), ["openal"])

    def test_what_the_layer_has_is_never_asked_for(self):
        exe = self.exe("d3dx9_43.dll", "xinput1_3.dll", "xaudio2_7.dll", "msvcp140.dll",
                       "msxml4.dll", "d3dcompiler_47.dll", "gdiplus.dll")
        self.assertEqual(self.needs(exe), [])

    def runtimeconfig(self, frameworks, name="Tool"):
        options = {"tfm": "net8.0-windows"}
        if len(frameworks) == 1:
            options["framework"] = frameworks[0]
        else:
            options["frameworks"] = frameworks
        (self.app / ("%s.runtimeconfig.json" % name)).write_text(json.dumps({"runtimeOptions": options}))

    def test_dotnet_desktop_program(self):
        exe = self.exe("kernel32.dll", bits=64)
        self.runtimeconfig([{"name": "Microsoft.NETCore.App", "version": "8.0.0"},
                            {"name": "Microsoft.WindowsDesktop.App", "version": "8.0.0"}])
        self.assertEqual(self.needs(exe), ["dotnetdesktop8"])

    def test_dotnet_console_program(self):
        exe = self.exe("kernel32.dll", bits=64)
        self.runtimeconfig([{"name": "Microsoft.NETCore.App", "version": "6.0.0"}])
        self.assertEqual(self.needs(exe), ["dotnet6"])

    def test_older_and_newer_dotnet(self):
        exe = self.exe("kernel32.dll", bits=64)
        self.runtimeconfig([{"name": "Microsoft.WindowsDesktop.App", "version": "3.1.0"}])
        self.assertEqual(self.needs(exe), ["dotnetcoredesktop3"])
        self.runtimeconfig([{"name": "Microsoft.WindowsDesktop.App", "version": "42.0.0"}])
        self.assertEqual(self.needs(exe), [])

    def test_self_contained_dotnet_needs_nothing(self):
        exe = self.exe("kernel32.dll", bits=64)
        (self.app / "Tool.runtimeconfig.json").write_text(json.dumps(
            {"runtimeOptions": {"includedFrameworks": [
                {"name": "Microsoft.WindowsDesktop.App", "version": "8.0.11"}]}}))
        self.assertEqual(self.needs(exe), [])

    def test_broken_runtimeconfig_is_ignored(self):
        exe = self.exe("kernel32.dll", bits=64)
        (self.app / "Tool.runtimeconfig.json").write_text("{not json")
        self.assertEqual(self.needs(exe), [])

    def test_what_the_space_has_is_not_asked_again(self):
        exe = self.exe("msvbvm60.dll", "mfc42.dll")
        (self.space / ".raye-components").write_text("vcrun2022 vb6run\n")
        self.assertEqual(self.needs(exe), ["mfc42"])
        (self.space / "winetricks.log").write_text("mfc42\n")
        self.assertEqual(self.needs(exe), [])

    def test_a_crowded_folder_is_read_up_to_a_limit(self):
        exe = self.exe("kernel32.dll")
        for i in range(self.mod.MAX_DLLS + 20):
            (self.app / ("p%03d.dll" % i)).write_bytes(b"MZ")
        self.assertEqual(self.needs(exe), [])

    def test_command_line(self):
        exe = self.exe("msvbvm60.dll", "openal32.dll")
        r = subprocess.run([sys.executable, "-I", str(NEEDS), str(exe), str(self.space)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, "openal vb6run\n"))
        r = subprocess.run([sys.executable, "-I", str(NEEDS), str(self.tmp / "nope.exe")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
