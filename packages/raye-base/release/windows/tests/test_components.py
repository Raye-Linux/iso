# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-windows-components, with fake system commands and a
local web server standing in for Microsoft's.

    python3 -I -m unittest discover -s release/windows/tests
"""
import base64
import contextlib
import functools
import hashlib
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import stat
import struct
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
WINDOWS = HERE.parent
SCRIPT = WINDOWS / "raye-windows-components"
SIGNERS = WINDOWS / "redist-signers.txt"
POLICY = WINDOWS / "org.raye.windows.components.policy"

sys.dont_write_bytecode = True


def load():
    loader = importlib.machinery.SourceFileLoader("raye_windows_components", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def make_pe(product=(14, 51, 36247, 0), marker=b"", pe32=False):
    """A small PE file holding only a version resource, then a marker the
    fake osslsigncode reads to know how to answer."""
    ms = product[0] << 16 | product[1]
    ls = product[2] << 16 | product[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, ms, ls, ms, ls,
                        0x3F, 0, 4, 1, 0, 0, 0)
    key = "VS_VERSION_INFO\0".encode("utf-16-le")
    head = struct.pack("<HHH", 0, len(fixed), 0) + key
    head += b"\0" * (-len(head) % 4)
    blob = head + fixed
    blob = struct.pack("<H", len(blob)) + blob[2:]

    def directory(entry_id, target):
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1) + struct.pack("<II", entry_id, target)

    rva = 0x1000
    root = directory(16, 0x80000000 | 24)
    name = directory(1, 0x80000000 | 48)
    lang = directory(0x409, 72)
    data_off = 72 + 16
    entry = struct.pack("<IIII", rva + data_off, len(blob), 0, 0)
    rsrc = root + name + lang + entry + blob
    rsrc += b"\0" * (-len(rsrc) % 0x200)

    dos = b"MZ" + b"\0" * 58 + struct.pack("<I", 0x40)
    opt_size = 224 if pe32 else 240
    coff = struct.pack("<HHIIIHH", 0x14C if pe32 else 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x10B if pe32 else 0x20B)
    dirs = 96 if pe32 else 112
    struct.pack_into("<II", opt, dirs + 2 * 8, rva, len(rsrc))
    section = struct.pack("<8sIIIIIIHHI", b".rsrc", len(rsrc), rva, len(rsrc),
                          0x200, 0, 0, 0, 0, 0x40000040)
    headers = dos + b"PE\0\0" + coff + bytes(opt) + section
    headers += b"\0" * (0x200 - len(headers))
    return headers + rsrc + marker


FAKE_OSSLSIGNCODE = r'''#!/usr/bin/python3 -I
import base64, os, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "osslsigncode.log", "a") as log:
    log.write(" ".join(args) + "\n")
def opt(name):
    return args[args.index(name) + 1] if name in args else None
def der(pem_path):
    text = pathlib.Path(pem_path).read_text()
    blocks = text.split("-----BEGIN CERTIFICATE-----")[1:]
    return [base64.b64decode(b.split("-----END CERTIFICATE-----")[0]) for b in blocks]
data = pathlib.Path(opt("-in")).read_bytes()
mark = data.rsplit(b"MARK:", 1)[-1].decode() if b"MARK:" in data else ""
org = "Microsoft Corporation"
code_ok = der(opt("-CAfile")) == [(here / "code-root.der").read_bytes()]
time_ok = der(opt("-TSA-CAfile")) == [(here / "time-root.der").read_bytes()]
if mark == "tampered" or not (code_ok and time_ok):
    print("Calculated message digest : 00")
    print("Signature verification: failed")
    print("Failed")
    sys.exit(1)
cn = "Microsoft Corporation"
arch = "x86" if opt("-in").endswith("x86.exe") else "x64"
if mark.startswith("good-"):
    arch = mark[5:]
elif mark == "othersigner":
    cn = "Totally Microsoft"
elif mark == "otherorg":
    cn, org = "Microsoft Corporation", "Contoso"
desc = "Microsoft Visual C++ v14 Redistributable (%s) - 14.51.36247" % arch
if mark == "nodesc":
    desc = None
print("Signer's certificate:")
print("\tSigner #0:")
print("\t\tSubject: CN=%s,O=%s,L=Redmond,ST=Washington,C=US" % (cn, org))
print("\t\tIssuer : CN=Microsoft Code Signing PCA 2024,O=Microsoft Corporation,C=US")
print("Authenticated attributes:")
if desc:
    print("\tText description: " + desc)
print("Signature verification: ok")
print("Succeeded")
'''

FAKE_CABEXTRACT = r"""#!/usr/bin/python3 -I
import json, os, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "cabextract.log", "a") as log:
    log.write(" ".join(args) + "\n")
    log.write("env " + " ".join(sorted(os.environ)) + "\n")
out = pathlib.Path(args[args.index("-d") + 1])
try:
    files = json.loads(pathlib.Path(args[-1]).read_text())
except ValueError:
    print("not a cabinet")
    sys.exit(1)
for name, text in files.items():
    (out / name.lower()).write_text(text)
"""

FAKE_FC_CACHE = r"""#!/bin/sh
echo "$*" >> "$(dirname "$0")/fc-cache.log"
"""


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def sha_file(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Server:
    """Serves files from a folder; a missing file is a 404."""

    def __init__(self, folder):
        handler = functools.partial(Quiet, directory=str(folder))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d/" % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="raye-components-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.www = self.tmp / "www"
        self.state = self.bin / "state"
        for d in (self.bin, self.www, self.state):
            d.mkdir()
        for name, text in (("osslsigncode", FAKE_OSSLSIGNCODE),
                           ("cabextract", FAKE_CABEXTRACT),
                           ("fc-cache", FAKE_FC_CACHE)):
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        self.code_root = os.urandom(900)
        self.time_root = os.urandom(800)
        (self.bin / "code-root.der").write_bytes(self.code_root)
        (self.bin / "time-root.der").write_bytes(self.time_root)
        (self.www / "code.crt").write_bytes(self.code_root)
        (self.www / "time.crt").write_bytes(self.time_root)
        self.server = Server(self.www)
        self.addCleanup(self.server.close)
        base = self.server.base
        signers = self.tmp / "signers.txt"
        signers.write_text(
            "# test pins\n\n"
            "code %s %smissing.crt\n" % (hashlib.sha256(self.code_root).hexdigest(), base) +
            "code %s %scode.crt\n" % (hashlib.sha256(self.code_root).hexdigest(), base) +
            "time %s %stime.crt\n" % (hashlib.sha256(self.time_root).hexdigest().upper(), base))
        self.redist = self.tmp / "var" / "redist"
        m = self.mod
        m.STATE_DIR = str(self.redist)
        m.SIGNERS = str(signers)
        m.SYSTEM_PATH = "%s:/usr/bin:/bin" % self.bin
        self.fonts = self.tmp / "fonts" / "msttcorefonts"
        m.FONT_DIR = str(self.fonts)
        m.FONT_URLS = (base + "fonts1/%s", base + "%s")
        cabs = {"arial32.exe": {"Arial.TTF": "arial regular", "ArialBD.ttf": "arial bold",
                                "licen.txt": "licence"},
                "verdan32.exe": {"verdana.ttf": "verdana regular"}}
        for cab, files in cabs.items():
            (self.www / cab).write_text(json.dumps(files))
        m.FONT_CABS = tuple((cab, sha_file(self.www / cab)) for cab in cabs)
        m.FONTS = (("Arial.ttf", "arial32.exe", "arial.ttf", sha_text("arial regular")),
                   ("Arial_Bold.ttf", "arial32.exe", "arialbd.ttf", sha_text("arial bold")),
                   ("Verdana.ttf", "verdan32.exe", "verdana.ttf", sha_text("verdana regular")))
        m.REDIST = {
            "x64": (base + "first/x64.exe", base + "x64.exe"),
            "x86": (base + "x86.exe",),
        }
        self.older = {"2010-x86": b"old runtime 2010 x86", "2013-x64": b"old runtime 2013 x64"}
        for key, data in self.older.items():
            (self.www / ("old-" + key)).write_bytes(data)
        m.OLDER = tuple((key, base + "old-" + key, hashlib.sha256(data).hexdigest())
                        for key, data in self.older.items())
        m.is_root = lambda: True

    def serve_redist(self, x64=b"good-x64", x86=b"good-x86"):
        if x64 is not None:
            (self.www / "x64.exe").write_bytes(make_pe(marker=b"MARK:" + x64))
        if x86 is not None:
            (self.www / "x86.exe").write_bytes(make_pe(marker=b"MARK:" + x86, pe32=True))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.mod.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def status(self):
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        return json.loads(out)

    def leftovers(self):
        if not self.redist.exists():
            return []
        return sorted(p.name for p in self.redist.iterdir()
                      if p.name.startswith(".") and p.name != ".lock")

    def log(self, name):
        path = self.bin / name
        return path.read_text() if path.exists() else ""


class PeVersion(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="raye-pe-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def version(self, data):
        path = self.tmp / "f.exe"
        path.write_bytes(data)
        return self.mod.pe_version(str(path))

    def test_pe32_plus(self):
        self.assertEqual(self.version(make_pe((14, 51, 36247, 0))), "14.51.36247.0")

    def test_pe32(self):
        self.assertEqual(self.version(make_pe((14, 44, 35211, 3), pe32=True)), "14.44.35211.3")

    def test_not_a_program(self):
        self.assertIsNone(self.version(b"<html>not found</html>"))
        self.assertIsNone(self.version(b""))

    def test_cut_short(self):
        data = make_pe()
        for size in (2, 0x40, 0x100, 0x200, 0x230, 0x260):
            self.assertIsNone(self.version(data[:size]), size)

    def test_no_version_resource(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x200 + 16, 3)  # resource type 3: icons
        self.assertIsNone(self.version(bytes(data)))

    def test_directory_loop_ends(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x200 + 20, 0x80000000)  # points at itself
        self.assertIsNone(self.version(bytes(data)))


class Signers(Base):
    def test_repo_file(self):
        pins = self.mod.read_signers(str(SIGNERS))
        self.assertEqual(set(pins), {"code", "time"})
        for kind, roots in pins.items():
            for sha, urls in roots.items():
                self.assertRegex(sha, r"^[0-9a-f]{64}$")
                self.assertTrue(urls)
                for url in urls:
                    self.assertRegex(url, r"^https?://www\.microsoft\.com/")
        # Microsoft Root Certificate Authority 2011 signs the code signing
        # CAs, the 2010 root the time-stamping one
        self.assertIn("847df6a78497943f27fc72eb93f9a637320a02b561d0a91b09e87a7807ed7c61",
                      pins["code"])
        self.assertIn("df545bf919a2439c36983b54cdfc903dfa4f37d3996d8d84b4c31eec6f3c163e",
                      pins["time"])

    def test_bad_lines(self):
        path = self.tmp / "bad.txt"
        for line in ("code abc https://x/", "other %s https://x/" % ("a" * 64),
                     "code %s" % ("a" * 64), "code %s file:///etc/x" % ("a" * 64)):
            path.write_text(line + "\n")
            with self.assertRaises(ValueError, msg=line):
                self.mod.read_signers(str(path))

    def test_needs_both_kinds(self):
        path = self.tmp / "half.txt"
        path.write_text("code %s https://www.microsoft.com/a.crt\n" % ("a" * 64))
        with self.assertRaises(ValueError):
            self.mod.read_signers(str(path))


class Status(Base):
    def test_nothing_yet(self):
        self.assertEqual(self.status(), {"fonts": False, "vcredist": None, "older": [],
                                         "missing": ["fonts", "vcredist"]})
        self.assertFalse(self.redist.exists())

    def test_works_without_root(self):
        self.mod.is_root = lambda: False
        self.assertEqual(self.status()["missing"], ["fonts", "vcredist"])

    def test_fonts_need_every_file(self):
        self.fonts.mkdir(parents=True)
        for name in ("Arial.ttf", "Arial_Bold.ttf"):
            (self.fonts / name).write_text("x")
        self.assertFalse(self.status()["fonts"])
        (self.fonts / "Verdana.ttf").symlink_to("Arial.ttf")
        self.assertFalse(self.status()["fonts"])
        (self.fonts / "Verdana.ttf").unlink()
        (self.fonts / "Verdana.ttf").write_text("x")
        self.assertTrue(self.status()["fonts"])


class Fonts(Base):
    def test_install(self):
        code, out, err = self.run_cli("install", "fonts")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["fonts"])
        self.assertEqual(sorted(p.name for p in self.fonts.iterdir()),
                         ["Arial.ttf", "Arial_Bold.ttf", "Verdana.ttf",
                          "arial.ttf", "arialbd.ttf", "verdana.ttf"])
        self.assertEqual((self.fonts / "Arial_Bold.ttf").read_text(), "arial bold")
        self.assertEqual(os.readlink(self.fonts / "arialbd.ttf"), "Arial_Bold.ttf")
        self.assertEqual(stat.S_IMODE((self.fonts / "Arial.ttf").stat().st_mode), 0o644)
        self.assertIn(str(self.fonts), self.log("fc-cache.log"))
        self.assertTrue(self.status()["fonts"])
        self.assertEqual(self.leftovers(), [])
        # the cabinet the first address did not have came from the second
        self.assertEqual(self.log("cabextract.log").count("-d "), 2)

    def test_offline(self):
        self.server.close()
        code, out, _ = self.run_cli("install", "fonts")
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["fonts"])
        self.assertFalse(self.fonts.exists())
        code, out, _ = self.run_cli("install", "--quiet", "fonts")
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(self.leftovers(), [])

    def test_changed_cabinet(self):
        (self.www / "verdan32.exe").write_text(json.dumps({"verdana.ttf": "evil"}))
        code, _, _ = self.run_cli("install", "fonts")
        self.assertEqual(code, 1)
        # nothing at all, not even the fonts of the good cabinet
        self.assertFalse(self.fonts.exists())
        self.assertEqual(self.log("cabextract.log").count("-d "), 1)

    def test_changed_font(self):
        m = self.mod
        m.FONTS = m.FONTS[:2] + (("Verdana.ttf", "verdan32.exe", "verdana.ttf", sha_text("other")),)
        code, _, err = self.run_cli("install", "fonts")
        self.assertEqual(code, 1)
        self.assertIn("verdana.ttf", err)
        self.assertFalse(self.fonts.exists())

    def test_not_a_cabinet(self):
        (self.www / "verdan32.exe").write_text("<html>")
        self.mod.FONT_CABS = (self.mod.FONT_CABS[0], ("verdan32.exe", sha_file(self.www / "verdan32.exe")))
        code, _, _ = self.run_cli("install", "fonts")
        self.assertEqual(code, 1)
        self.assertFalse(self.fonts.exists())
        self.assertEqual(self.leftovers(), [])

    def test_already_there(self):
        self.run_cli("install", "fonts")
        os.unlink(self.bin / "cabextract.log")
        code, _, _ = self.run_cli("install", "fonts")
        self.assertEqual(code, 0)
        self.assertEqual(self.log("cabextract.log"), "")

    def test_one_font_lost(self):
        self.run_cli("install", "fonts")
        (self.fonts / "Verdana.ttf").unlink()
        self.assertFalse(self.status()["fonts"])
        code, _, _ = self.run_cli("install", "fonts")
        self.assertEqual(code, 0)
        self.assertTrue(self.status()["fonts"])

    def test_remove(self):
        self.run_cli("install", "fonts")
        code, out, err = self.run_cli("remove", "fonts")
        self.assertEqual(code, 0, err)
        self.assertFalse(json.loads(out)["fonts"])
        self.assertFalse(self.fonts.exists())

    def test_remove_keeps_what_is_not_ours(self):
        self.run_cli("install", "fonts")
        (self.fonts / "mine.ttf").write_text("someone else's")
        (self.fonts / "verdana.ttf").unlink()
        (self.fonts / "verdana.ttf").symlink_to("mine.ttf")
        self.run_cli("remove", "fonts")
        self.assertEqual(sorted(p.name for p in self.fonts.iterdir()),
                         ["mine.ttf", "verdana.ttf"])


class Redist(Base):
    def test_good(self):
        self.serve_redist()
        code, out, err = self.run_cli("install", "vcredist")
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["vcredist"], "14.51.36247.0")
        self.assertEqual(result["missing"], ["fonts"])
        for arch in ("x64", "x86"):
            path = self.redist / ("vc_redist.%s.exe" % arch)
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.redist.stat().st_mode), 0o755)
        saved = json.loads((self.redist / "components.json").read_text())
        self.assertEqual(saved["vcredist"], "14.51.36247.0")
        self.assertEqual(saved["files"]["x64"]["sha256"],
                         hashlib.sha256((self.www / "x64.exe").read_bytes()).hexdigest())
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.status()["vcredist"], "14.51.36247.0")
        # both checks ran with the pinned roots, through the fallback URL
        calls = self.log("osslsigncode.log").splitlines()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.startswith("verify ") for c in calls))

    def test_tampered(self):
        self.serve_redist(x64=b"tampered")
        code, out, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 1)
        self.assertIsNone(json.loads(out)["vcredist"])
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertEqual(self.leftovers(), [])

    def test_wrong_signer(self):
        self.serve_redist(x86=b"othersigner")
        code, out, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 1)
        self.assertFalse((self.redist / "vc_redist.x86.exe").exists())
        self.assertIsNone(json.loads(out)["vcredist"])

    def test_other_organisation(self):
        self.serve_redist(x64=b"otherorg")
        self.run_cli("install", "vcredist")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertTrue((self.redist / "vc_redist.x86.exe").exists())

    def test_wrong_architecture(self):
        self.serve_redist(x64=b"good-x86")
        self.run_cli("install", "vcredist")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())

    def test_no_description(self):
        self.serve_redist(x64=b"nodesc")
        self.run_cli("install", "vcredist")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())

    def test_not_a_program(self):
        (self.www / "x64.exe").write_bytes(b"<html>gone</html>MARK:good-x64")
        self.serve_redist(x64=None)
        self.run_cli("install", "vcredist")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertTrue((self.redist / "vc_redist.x86.exe").exists())

    def test_wrong_root_served(self):
        (self.www / "time.crt").write_bytes(os.urandom(800))
        self.serve_redist()
        code, _, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 1)
        self.assertEqual(self.log("osslsigncode.log"), "")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertEqual(self.leftovers(), [])

    def test_offline(self):
        self.serve_redist()
        self.server.close()
        code, out, _ = self.run_cli("install", "--quiet")
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(self.status()["missing"], ["fonts", "vcredist"])
        self.assertEqual(self.leftovers(), [])

    def test_too_big(self):
        self.serve_redist()
        self.mod.MAX_DOWNLOAD = 1000
        self.run_cli("install", "vcredist")
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertEqual(self.leftovers(), [])

    def test_changed_file_is_not_trusted(self):
        self.serve_redist()
        self.run_cli("install", "vcredist")
        with open(self.redist / "vc_redist.x86.exe", "ab") as f:
            f.write(b"!")
        self.assertIsNone(self.status()["vcredist"])
        # the next install fetches it again
        code, _, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 0)
        self.assertEqual(self.status()["vcredist"], "14.51.36247.0")

    def test_kept_when_there(self):
        self.serve_redist()
        self.run_cli("install", "vcredist")
        self.run_cli("install", "vcredist")
        self.assertEqual(len(self.log("osslsigncode.log").splitlines()), 2)

    def test_half_then_whole(self):
        self.serve_redist(x86=None)
        code, out, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 1)
        self.assertIsNone(json.loads(out)["vcredist"])
        self.assertTrue((self.redist / "vc_redist.x64.exe").exists())
        self.serve_redist()
        code, out, _ = self.run_cli("install", "vcredist")
        self.assertEqual(code, 0)
        # one check per run: the x64 file already there is not fetched again
        calls = self.log("osslsigncode.log").splitlines()
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].endswith("vc_redist.x86.exe"))

    def test_remove(self):
        self.serve_redist()
        self.run_cli("install", "vcredist")
        code, out, err = self.run_cli("remove", "vcredist")
        self.assertEqual(code, 0, err)
        self.assertIsNone(json.loads(out)["vcredist"])
        self.assertFalse((self.redist / "vc_redist.x64.exe").exists())
        self.assertFalse((self.redist / "vc_redist.x86.exe").exists())

    def test_state_dir_symlink_refused(self):
        self.redist.parent.mkdir(parents=True)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.redist.symlink_to(elsewhere)
        self.serve_redist()
        code, _, err = self.run_cli("install", "vcredist")
        self.assertNotEqual(code, 0)
        self.assertEqual(list(elsewhere.iterdir()), [])


class Older(Base):
    def test_pinned_files_are_kept(self):
        self.serve_redist()
        code, _, _ = self.run_cli("install", "--quiet", "vcredist")
        self.assertEqual(code, 0)
        for key, data in self.older.items():
            self.assertEqual((self.redist / ("vcredist-%s.exe" % key)).read_bytes(), data)
        state = self.status()
        self.assertEqual(state["older"], sorted(self.older))
        self.assertEqual(state["vcredist"], "14.51.36247.0")

    def test_changed_file_is_refused(self):
        self.serve_redist()
        (self.www / "old-2013-x64").write_bytes(b"something else")
        code, _, err = self.run_cli("install", "vcredist")
        self.assertEqual(code, 1)
        self.assertIn("not the file Raye knows", err)
        self.assertFalse((self.redist / "vcredist-2013-x64.exe").exists())
        state = self.status()
        self.assertEqual(state["older"], ["2010-x86"])
        self.assertIsNone(state["vcredist"])
        self.assertIn("vcredist", state["missing"])
        self.assertEqual(self.leftovers(), [])

    def test_file_changed_on_disk_is_not_trusted(self):
        self.serve_redist()
        self.run_cli("install", "--quiet", "vcredist")
        (self.redist / "vcredist-2010-x86.exe").write_bytes(b"swapped")
        self.assertEqual(self.status()["older"], ["2013-x64"])

    def test_remove_takes_them_too(self):
        self.serve_redist()
        self.run_cli("install", "--quiet", "vcredist")
        self.run_cli("remove", "--quiet", "vcredist")
        self.assertEqual(sorted(p.name for p in self.redist.glob("vcredist-*")), [])
        self.assertEqual(self.status()["older"], [])


    def test_same_files_leave_the_state_file_alone(self):
        self.serve_redist()
        self.run_cli("install", "--quiet")
        state = self.redist / "components.json"
        before = state.stat()
        self.run_cli("install", "--quiet")
        after = state.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_new_file_rewrites_the_state_file(self):
        self.serve_redist()
        self.run_cli("install", "--quiet", "fonts")
        state = self.redist / "components.json"
        before = state.read_text()
        self.run_cli("install", "--quiet", "vcredist")
        self.assertNotEqual(state.read_text(), before)
        self.assertEqual(self.status()["older"], ["2010-x86", "2013-x64"])


class Timer(unittest.TestCase):
    def test_tries_again_within_the_hour(self):
        # a first boot without network must not wait hours for its runtimes
        text = (WINDOWS / "raye-windows-components.timer").read_text()
        every = re.search(r"^OnUnitActiveSec=(\d+)(min|h)$", text, re.M)
        self.assertIsNotNone(every)
        minutes = int(every.group(1)) * (60 if every.group(2) == "h" else 1)
        self.assertLessEqual(minutes, 60)


class Everything(Base):
    def test_install_all(self):
        self.serve_redist()
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out),
                         {"fonts": True, "vcredist": "14.51.36247.0",
                          "older": ["2010-x86", "2013-x64"], "missing": []})

    def test_quiet_success_prints_nothing(self):
        self.serve_redist()
        self.assertEqual(self.run_cli("install", "--quiet"), (0, "", ""))

    def test_needs_root(self):
        self.mod.is_root = lambda: False
        for args in (("install",), ("remove", "fonts")):
            code, _, err = self.run_cli(*args)
            self.assertEqual(code, 4)
            self.assertTrue(err)
        self.assertEqual(self.log("cabextract.log"), "")
        self.assertFalse(self.redist.exists())

    def test_usage(self):
        for args in ((), ("fly",), ("install", "games"), ("status", "--quiet", "x"),
                     ("remove",)):
            code, _, _ = self.run_cli(*args)
            self.assertEqual(code, 2, args)

    def test_strict_umask(self):
        # pkexec or the installer may run it with umask 077: what it adds
        # must still be readable by every account
        old = os.umask(0o077)
        self.addCleanup(os.umask, old)
        self.serve_redist()
        code, _, err = self.run_cli("install")
        self.assertEqual(code, 0, err)
        for d in (self.fonts, self.fonts.parent, self.redist, self.redist.parent):
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o755, d)
        for f in (self.redist / "components.json", self.redist / "vc_redist.x64.exe",
                  self.fonts / "Arial.ttf"):
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o644, f)

    def test_disk_error(self):
        def full(*args):
            raise OSError(28, "No space left on device")
        self.mod.place = full
        self.serve_redist()
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertIn("No space left", err)
        self.assertNotIn("Traceback", err)
        # the other component still went in, and the state says so
        self.assertEqual(json.loads(out)["missing"], ["fonts"])
        self.assertEqual(self.status()["vcredist"], "14.51.36247.0")
        self.assertEqual(self.leftovers(), [])
        code, out, _ = self.run_cli("install", "--quiet", "fonts")
        self.assertEqual((code, out), (0, ""))

    def test_state_dir_error_quiet(self):
        self.redist.parent.mkdir(parents=True)
        self.redist.write_text("not a folder")
        self.assertEqual(self.run_cli("install", "fonts")[0], 1)
        code, out, err = self.run_cli("install", "--quiet", "fonts")
        self.assertEqual((code, out), (0, ""))
        self.assertTrue(err)

    def test_child_environment(self):
        os.environ["RAYE_LEAK"] = "1"
        self.addCleanup(os.environ.pop, "RAYE_LEAK", None)
        self.run_cli("install", "fonts")
        env = [l for l in self.log("cabextract.log").splitlines() if l.startswith("env ")]
        self.assertTrue(env)
        self.assertNotIn("RAYE_LEAK", env[0])
        self.assertNotIn("HOME", env[0].split())


class Files(unittest.TestCase):
    def test_policy(self):
        root = ET.parse(POLICY).getroot()
        action = root.find("action")
        self.assertEqual(action.get("id"), "org.raye.windows.components")
        langs = {d.get("{http://www.w3.org/XML/1998/namespace}lang")
                 for d in action.findall("description")}
        # English, French, and the four languages of the V1
        self.assertEqual(langs, {None, "fr", "es", "de", "pt_BR", "it"})
        annotate = {a.get("key"): a.text for a in action.findall("annotate")}
        self.assertEqual(annotate["org.freedesktop.policykit.exec.path"],
                         "/usr/libexec/raye-windows-components")
        defaults = action.find("defaults")
        self.assertEqual(defaults.find("allow_any").text, "auth_admin")
        self.assertTrue(defaults.find("allow_active").text.startswith("auth_admin"))

    def test_plain_words(self):
        for path in (SCRIPT, SIGNERS, POLICY):
            text = path.read_text().lower()
            self.assertNotIn("wine", text, path)

    def test_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertTrue(SCRIPT.read_text().startswith("#!/usr/bin/python3 -I\n"))


if __name__ == "__main__":
    unittest.main()
