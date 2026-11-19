"""Chromebooks: which machine counts as one, the top-row map written for
keyd, the Pixelbook's Search key in the hwdb, and the sound notice."""

import fnmatch
import importlib.machinery
import importlib.util
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("raye_chromebook", str(HERE / "raye-chromebook"))
    spec = importlib.util.spec_from_loader("raye_chromebook", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cb = load()

PHYSMAP = "sys/bus/platform/devices/i8042/serio0/function_row_physmap"


def machine(root, vendor="Google", family="", name="Morphius", chassis="9", physmap=None):
    dmi = pathlib.Path(root, "sys/class/dmi/id")
    dmi.mkdir(parents=True, exist_ok=True)
    for key, value in (("sys_vendor", vendor), ("product_family", family),
                       ("product_name", name), ("chassis_type", chassis)):
        (dmi / key).write_text(value + "\n")
    if physmap is not None:
        path = pathlib.Path(root, PHYSMAP)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(physmap + "\n")


def sections(text):
    """{section: [(key, value)]} of a keyd file, comments left out."""
    out, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line.strip("[]")
            out.setdefault(current, [])
        elif "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            out[current].append((key, value))
        else:
            out[current].append((line, None))
    return out


class Detection(unittest.TestCase):
    def test_google_vendor_is_a_chromebook(self):
        self.assertTrue(cb.is_chromebook({"sys_vendor": "Google"}))

    def test_old_boards_in_capitals(self):
        self.assertTrue(cb.is_chromebook({"sys_vendor": "GOOGLE"}))

    def test_family_alone_is_enough(self):
        self.assertTrue(cb.is_chromebook({"sys_vendor": "HP", "product_family": "Google_Zork"}))

    def test_other_laptops_are_not(self):
        self.assertFalse(cb.is_chromebook({"sys_vendor": "Dell Inc.", "product_family": "Latitude"}))
        self.assertFalse(cb.is_chromebook({}))

    def test_chromeos_linux_container_is_not(self):
        self.assertFalse(cb.is_chromebook({"sys_vendor": "Google", "product_name": "crosvm"}))

    def test_chromebox_has_no_keyboard_to_map(self):
        self.assertIsNone(cb.keyboard_kind({"sys_vendor": "Google", "product_name": "Puff", "chassis_type": "3"}))

    def test_dell_boards_keep_their_keyboard(self):
        self.assertIsNone(cb.keyboard_kind({"sys_vendor": "Google", "product_name": "Sarien", "chassis_type": "9"}))

    def test_pixelbook(self):
        self.assertEqual(cb.keyboard_kind({"sys_vendor": "Google", "product_name": "Eve"}), "pixel")

    def test_regular_chromebook(self):
        self.assertEqual(cb.keyboard_kind({"sys_vendor": "Google", "product_name": "Morphius", "chassis_type": "31"}), "chromebook")


class TopRow(unittest.TestCase):
    def test_classic_row_sends_f_keys(self):
        row = cb.top_row("chromebook", [])
        self.assertEqual(row[0], ("f1", "back"))
        self.assertEqual(row[2], ("f3", "refresh"))
        self.assertEqual(row[3], ("f4", "f11"))
        self.assertEqual(row[4], ("f5", "M-tab"))
        self.assertEqual(len(row), 10)

    def test_firmware_order_is_followed(self):
        row = cb.top_row("chromebook", ["EA", "E7", "91", "92", "94", "95", "A0", "AE", "B0"])
        self.assertEqual([k for k, _ in row][:4], ["back", "refresh", "zoom", "scale"])
        self.assertEqual(dict(row)["zoom"], "f11")

    def test_unknown_code_keeps_its_place(self):
        row = cb.top_row("chromebook", ["EA", "C3", "E7"])
        self.assertEqual(row[1], (None, None))
        text = cb.keyd_config(row)
        self.assertIn("refresh = f3", text)

    def test_pixel_has_no_forward(self):
        row = cb.top_row("pixel", [])
        self.assertNotIn("forward", [a for _, a in row])
        self.assertEqual(row[1], ("f2", "refresh"))


class Config(unittest.TestCase):
    def config(self, codes):
        return cb.keyd_config(cb.top_row("chromebook", codes))

    def test_ids_come_first_then_the_mark(self):
        lines = self.config([]).splitlines()
        self.assertEqual(lines[:2], ["[ids]", cb.MARK])
        self.assertIn("k:0001:0001", lines)

    def test_search_gives_f_keys_left_to_right(self):
        meta = dict(sections(self.config(["EA", "E9", "E7"]))["meta"])
        self.assertEqual(meta, {"back": "f1", "forward": "f2", "refresh": "f3"})
        meta = dict(sections(self.config([]))["meta"])
        self.assertEqual(meta["f1"], "f1")
        self.assertEqual(meta["f10"], "f10")

    def test_search_alone_is_left_alone(self):
        # the Search key already sends the Start menu key; remapping it
        # would break Search + E and the other shortcuts
        text = self.config([])
        self.assertNotIn("leftmeta", text)
        self.assertNotIn("[global]", text)

    def test_overview_and_fullscreen(self):
        main = dict(sections(self.config(["EA", "E7", "91", "92"]))["main"])
        self.assertEqual(main["zoom"], "f11")
        self.assertEqual(main["scale"], "M-tab")
        self.assertNotIn("back", main)      # already right, nothing to say

    def test_delete_and_ctrl_alt_delete(self):
        parsed = sections(self.config([]))
        self.assertIn(("backspace", "delete"), parsed["alt"])
        self.assertIn(("backspace", "C-A-delete"), parsed["control+alt"])
        self.assertIn(("f1", "C-A-f1"), parsed["control+alt"])

    def test_keyboard_light_on_alt_brightness(self):
        alt = dict(sections(self.config([]))["alt"])
        self.assertEqual((alt["f6"], alt["f7"]), ("kbdillumdown", "kbdillumup"))

    def test_every_name_is_one_keyd_knows(self):
        keyd = shutil.which("keyd.rvaiya") or shutil.which("keyd")
        if not keyd:
            self.skipTest("keyd is not installed here")
        known = set(subprocess.run([keyd, "list-keys"], capture_output=True,
                                   text=True, check=True).stdout.split())
        for codes in ([], list(cb.VIVALDI), None):
            row = cb.top_row("pixel", []) if codes is None else cb.top_row("chromebook", codes)
            for name, entries in sections(cb.keyd_config(row)).items():
                if name == "ids":
                    continue
                for key, value in entries:
                    for word in (key, re.sub(r"^([CMASG]-)+", "", value)):
                        self.assertIn(word, known, f"[{name}] {key} = {value}")


class Plan(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.conf = pathlib.Path(self.root, cb.CONF)

    def test_written_on_a_chromebook(self):
        machine(self.root, physmap="EA E7 91 92 94 95 A0 AE B0")
        self.assertEqual(cb.keys(self.root), 0)
        self.assertTrue(self.conf.read_text().startswith("[ids]\n" + cb.MARK))
        self.assertEqual(stat.S_IMODE(self.conf.stat().st_mode), 0o644)
        self.assertEqual(cb.plan_keys(self.root), ("keep", "up to date"))

    def test_nothing_on_another_laptop(self):
        machine(self.root, vendor="LENOVO", name="21AH")
        self.assertEqual(cb.plan_keys(self.root)[0], "keep")
        cb.keys(self.root)
        self.assertFalse(self.conf.exists())

    def test_taken_back_when_the_disk_moves(self):
        machine(self.root)
        cb.keys(self.root)
        machine(self.root, vendor="LENOVO", name="21AH")
        self.assertEqual(cb.plan_keys(self.root), ("remove", None))
        cb.keys(self.root)
        self.assertFalse(self.conf.exists())

    def test_hand_edited_file_is_kept(self):
        machine(self.root)
        cb.keys(self.root)
        self.conf.write_text("[ids]\nk:0001:0001\n\n[main]\nf1 = f1\n")
        before = self.conf.read_text()
        self.assertEqual(cb.plan_keys(self.root)[0], "keep")
        machine(self.root, vendor="LENOVO", name="21AH")
        cb.keys(self.root)
        self.assertEqual(self.conf.read_text(), before)

    def test_someone_elses_keyd_setup_wins(self):
        machine(self.root)
        other = pathlib.Path(self.root, "etc/keyd/cros.conf")
        other.parent.mkdir(parents=True)
        other.write_text("[ids]\n0001:0001\n")
        action, why = cb.plan_keys(self.root)
        self.assertEqual(action, "keep")
        self.assertIn("cros.conf", why)

    def test_never_restarts_keyd_outside_the_real_root(self):
        machine(self.root)
        with mock.patch.object(cb, "restart_keyd") as restart:
            cb.keys(self.root)
        restart.assert_not_called()


HWDB = HERE / "61-raye-chromebook.hwdb"
EVE = ("evdev:atkbd:dmi:bvncoreboot:bvrMrChromebox-2409.0:bd09/30/2024:br4.22:efr0.0:"
       "svnGoogle:pnEve:pvr1.0:rvnGoogle:rnEve:rvr1.0:cvnGoogle:ct31:cvr:skuskuX:")
OTHER_GOOGLE = EVE.replace("pnEve", "pnMorphius").replace("rnEve", "rnMorphius")
DELL = EVE.replace("svnGoogle:pnEve", "svnDell Inc.:pnLatitude 5400")


def hwdb_rules(text):
    """[(match patterns, properties)] the way systemd-hwdb reads them."""
    rules, matches, props = [], [], []
    for line in text.splitlines() + [""]:
        if line.startswith("#"):
            continue
        if line.startswith(" "):
            props.append(line.strip())
        elif line.strip():
            if props:
                rules.append((matches, props))
                matches, props = [], []
            matches.append(line)
        elif matches:
            rules.append((matches, props))
            matches, props = [], []
    return rules


def hwdb_lookup(text, modalias):
    return [p for pats, props in hwdb_rules(text)
            if any(fnmatch.fnmatchcase(modalias, pat) for pat in pats) for p in props]


class Hwdb(unittest.TestCase):
    def test_parse(self):
        rules = hwdb_rules(HWDB.read_text())
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0][1], ["KEYBOARD_KEY_d8=leftmeta"])

    def test_only_the_pixelbooks(self):
        text = HWDB.read_text()
        self.assertEqual(hwdb_lookup(text, EVE), ["KEYBOARD_KEY_d8=leftmeta"])
        self.assertEqual(hwdb_lookup(text, EVE.replace("Eve", "Atlas")), ["KEYBOARD_KEY_d8=leftmeta"])
        self.assertEqual(hwdb_lookup(text, OTHER_GOOGLE), [])
        self.assertEqual(hwdb_lookup(text, DELL), [])

    def test_real_hwdb_agrees(self):
        tool = shutil.which("systemd-hwdb")
        if not tool:
            self.skipTest("systemd-hwdb is not installed here")
        with tempfile.TemporaryDirectory() as root:
            dest = pathlib.Path(root, "usr/lib/udev/hwdb.d")
            dest.mkdir(parents=True)
            shutil.copy(HWDB, dest)
            subprocess.run([tool, "--root", root, "--strict", "--usr", "update"], check=True)
            for modalias, want in ((EVE, "KEYBOARD_KEY_d8=leftmeta"), (OTHER_GOOGLE, ""), (DELL, "")):
                got = subprocess.run([tool, "--root", root, "query", modalias],
                                     capture_output=True, text=True, check=True).stdout.strip()
                self.assertEqual(got, want, modalias)


class Quirks(unittest.TestCase):
    def test_matches_the_name_keyd_gives_its_keyboard(self):
        text = (HERE / "50-raye-keyd.quirks").read_text()
        self.assertIn("MatchName=keyd virtual keyboard", text)
        self.assertIn("AttrKeyboardIntegration=internal", text)
        keyd = shutil.which("keyd.rvaiya") or shutil.which("keyd")
        if keyd:
            self.assertIn(b"keyd virtual keyboard", pathlib.Path(keyd).read_bytes())


class Units(unittest.TestCase):
    def test_keys_run_before_keyd(self):
        unit = (HERE / "raye-chromebook-keys.service").read_text()
        self.assertIn("Before=keyd.service", unit)
        self.assertIn("ExecStart=/usr/libexec/raye-chromebook keys", unit)

    def test_keyd_waits_for_a_config(self):
        drop = (HERE / "keyd.service.d/raye.conf").read_text()
        self.assertIn("ConditionPathExistsGlob=/etc/keyd/*.conf", drop)
        self.assertIn("After=raye-chromebook-keys.service", drop)
        # the file the script writes is one keyd and this condition both see
        self.assertTrue(fnmatch.fnmatch("/" + cb.CONF, "/etc/keyd/*.conf"))


class SoundTip(unittest.TestCase):
    def test_no_default_sink(self):
        self.assertTrue(cb.no_sound(1, ""))

    def test_dummy_output(self):
        self.assertTrue(cb.no_sound(0, '  * node.name = "auto_null"\n'))

    def test_a_real_card(self):
        self.assertFalse(cb.no_sound(0, '  * node.name = "alsa_output.pci-0000_00_1f.3.analog-stereo"\n'))

    def run_tip(self, sink_rc, sink_out, vendor="Google"):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        machine(root, vendor=vendor)
        bin_ = pathlib.Path(root, "bin")
        bin_.mkdir()
        log = pathlib.Path(root, "log")
        stubs = {
            "wpctl": f'printf %s "{sink_out}"; exit {sink_rc}',
            "notify-send": f'echo "notify $*" >> {log}; echo open',
            "xdg-open": f'echo "open $*" >> {log}',
        }
        for name, body in stubs.items():
            path = bin_ / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        env = {"PATH": str(bin_), "XDG_STATE_HOME": str(pathlib.Path(root, "state")), "LANG": "fr_CA.UTF-8"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(cb.sound_tip(root, wait=0), 0)
            with mock.patch("time.sleep"):
                cb.sound_tip(root, wait=0)     # second login: nothing more
        return log.read_text() if log.exists() else ""

    def test_notice_once_and_opens_the_page(self):
        out = self.run_tip(1, "")
        self.assertEqual(out.count("notify "), 1)
        self.assertIn("Le son ne marche pas encore", out)
        self.assertIn("fr/11-chromebooks.md#sound", out)

    def test_quiet_when_sound_works(self):
        self.assertEqual(self.run_tip(0, 'node.name = \\"alsa_output.x\\"'), "")

    def test_quiet_on_other_computers(self):
        self.assertEqual(self.run_tip(1, "", vendor="LENOVO"), "")


if __name__ == "__main__":
    unittest.main()
