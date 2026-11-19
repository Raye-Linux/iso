# SPDX-License-Identifier: GPL-3.0-or-later
"""vm-images without root: layout, files written into the image, OVF."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True  # no __pycache__ in the repo
sys.path.insert(0, str(TOOLS))
import raye_vmimage as vm  # noqa: E402

FIRST_START = TOOLS / "first-start"
INSTALLER = TOOLS.parents[1] / "installer"
STRINGS = INSTALLER / "etc/calamares/branding/raye/strings.js"
SETTINGS = INSTALLER / "etc/calamares/settings.conf"

NS = {"ovf": vm.OVF_NS, "rasd": vm.RASD_NS, "vssd": vm.VSSD_NS, "vbox": vm.VBOX_NS, "vmw": vm.VMW_NS}
# show module -> step name in strings.js
STEP_OF = {"welcomeq": "language", "localeq": "region", "keyboardq": "keyboard",
           "notesqml@raye_network": "network", "notesqml@raye_disk": "disk",
           "notesqml@raye_device": "device", "notesqml@raye_account": "account",
           "usersq": "user", "notesqml@raye_privacy": "privacy", "summaryq": "ready",
           "finishedq": "done"}


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(TOOLS / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def steps_of(settings_text):
    """The steps strings.js has to list for this settings.conf."""
    shows, exec_seen, out = [], False, []
    for line in settings_text.splitlines():
        if line.startswith("- show:"):
            shows.append([])
        elif line.startswith("- exec:"):
            exec_seen = True
            shows.append(None)
        elif line.startswith("  - ") and shows and shows[-1] is not None:
            shows[-1].append(line.split("-", 1)[1].strip())
    for group in shows:
        out += ["installing"] if group is None else [STEP_OF[m] for m in group]
    assert exec_seen
    return out


class LayoutTests(unittest.TestCase):
    def test_partitions_like_setup(self):
        plan = vm.partition_plan(64 * vm.GIB)
        self.assertEqual([p["name"] for p in plan], ["EFI", "raye_boot", "raye"])
        self.assertEqual(plan[0]["sectors"] * 512, vm.GIB)
        self.assertEqual(plan[1]["sectors"] * 512, 2 * vm.GIB)
        self.assertEqual(plan[0]["type"], vm.ESP_TYPE)

    def test_partitions_aligned_and_inside(self):
        size = 40 * vm.GIB + 12345 * 512
        plan = vm.partition_plan(size)
        for a, b in zip(plan, plan[1:]):
            self.assertEqual(a["start"] + a["sectors"], b["start"])
        for p in plan:
            self.assertEqual(p["start"] % vm.ALIGN, 0)
            self.assertEqual(p["sectors"] % vm.ALIGN, 0)
        last = plan[-1]
        self.assertLessEqual(last["start"] + last["sectors"], size // 512 - vm.GPT_TAIL)

    def test_small_disk_refused(self):
        with self.assertRaises(vm.LayoutError):
            vm.partition_plan(20 * vm.GIB)
        with self.assertRaises(vm.LayoutError):
            vm.partition_plan(64 * vm.GIB + 1)

    def test_sfdisk_script(self):
        text = vm.sfdisk_script(vm.partition_plan(64 * vm.GIB))
        self.assertTrue(text.startswith("label: gpt\n"))
        self.assertIn('start=2048, size=2097152, type=%s, name="EFI"' % vm.ESP_TYPE, text)
        self.assertEqual(text.count("start="), 3)

    def test_parse_size(self):
        self.assertEqual(vm.parse_size("64G"), 64 * vm.GIB)
        self.assertEqual(vm.parse_size("80GiB"), 80 * vm.GIB)
        self.assertEqual(vm.parse_size("1024"), 1024)
        with self.assertRaises(vm.LayoutError):
            vm.parse_size("big")

    def test_mounts_parents_first_esp_last(self):
        m = vm.mounts("/dev/r", "/dev/b", "/dev/e", "/t")
        self.assertEqual([w for _, w, _, _ in m],
                         ["/t", "/t/home", "/t/var/log", "/t/var/cache", "/t/boot", "/t/boot/efi"])
        self.assertIn("subvol=/@home", m[1][3])
        self.assertEqual(m[-1][2], "vfat")

    def test_fstab(self):
        text = vm.fstab("1111-aaaa", "2222-bbbb", "ABCD-1234")
        rows = [l.split() for l in text.splitlines() if not l.startswith("#")]
        self.assertEqual([r[1] for r in rows],
                         ["/", "/boot", "/boot/efi", "/home", "/var/cache", "/var/log"])
        root = rows[0]
        self.assertEqual(root[0], "UUID=1111-aaaa")
        self.assertEqual(root[3], "subvol=/@,defaults,noatime,compress=zstd:1")
        self.assertEqual(root[5], "0")
        self.assertEqual(rows[2][3], "umask=0077")
        with self.assertRaises(vm.LayoutError):
            vm.fstab("x y", "2222", "3333")


class CommandTests(unittest.TestCase):
    def test_grub_never_touches_nvram(self):
        named, removable = vm.grub_install_argv()
        for argv in (named, removable):
            self.assertIn("--no-nvram", argv)
            self.assertIn("--bootloader-id=ubuntu", argv)
        self.assertNotIn("--removable", named)
        self.assertIn("--removable", removable)

    def test_convert(self):
        q = vm.convert_argv("qcow2", "a.raw", "a.qcow2")
        self.assertEqual(q[:2], ["qemu-img", "convert"])
        self.assertIn("-c", q)
        self.assertEqual(q[-2:], ["a.raw", "a.qcow2"])
        v = vm.convert_argv("vmdk", "a.raw", "a.vmdk")
        self.assertIn("subformat=streamOptimized,adapter_type=lsilogic", v)
        with self.assertRaises(ValueError):
            vm.convert_argv("vdi", "a", "b")

    def test_names(self):
        n = vm.names("/x/raye-1.0-beta-amd64.iso")
        self.assertEqual(n["qcow2"], "raye-1.0-beta-amd64.qcow2")
        self.assertEqual(n["virtualbox"], "raye-1.0-beta-amd64-virtualbox.ova")
        self.assertEqual(n["vmware"], "raye-1.0-beta-amd64-vmware.ova")
        self.assertEqual(vm.names("x.iso", "raye-9")["stem"], "raye-9")
        with self.assertRaises(ValueError):
            vm.names("x.iso", "a b")

    def test_title(self):
        self.assertEqual(vm.title_of("Raye Linux 1.0 Beta Brocken - amd64 (20261119)\n"),
                         ("Raye Linux", "1.0 Beta Brocken"))
        self.assertEqual(vm.title_of(""), ("Raye Linux", ""))

    def test_dry_run_writes_nothing(self):
        tool = load("vm-images")
        with tempfile.TemporaryDirectory() as tmp:
            iso = pathlib.Path(tmp, "raye-1.0-beta-amd64.iso")
            iso.write_bytes(b"")
            work, out = pathlib.Path(tmp, "work"), pathlib.Path(tmp, "out")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = tool.main(["--dry-run", "--iso", str(iso), "--work", str(work), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertFalse(work.exists())
            self.assertFalse(out.exists())
            said = buf.getvalue()
            self.assertIn("losetup --find --show --read-only", said)
            self.assertIn("--no-nvram", said)
            self.assertIn("subformat=streamOptimized", said)
            self.assertNotIn("/dev/sd", said)


class OvfTests(unittest.TestCase):
    def make(self, flavour):
        text = vm.ovf(flavour, "raye-1.0-beta-amd64", "Raye Linux", "1.0 Beta", 64 * vm.GIB,
                      "raye-1.0-beta-amd64-disk1.vmdk", 3141592653)
        return text, ET.fromstring(text.encode())

    def items(self, tree):
        out = {}
        for item in tree.iterfind(".//ovf:VirtualHardwareSection/ovf:Item", NS):
            kind = item.findtext("rasd:ResourceType", namespaces=NS)
            out.setdefault(kind, []).append(item)
        return out

    def check_common(self, tree):
        f = tree.find("ovf:References/ovf:File", NS)
        self.assertEqual(f.get("{%s}href" % vm.OVF_NS), "raye-1.0-beta-amd64-disk1.vmdk")
        self.assertEqual(f.get("{%s}size" % vm.OVF_NS), "3141592653")
        disk = tree.find("ovf:DiskSection/ovf:Disk", NS)
        self.assertEqual(disk.get("{%s}capacity" % vm.OVF_NS), str(64 * vm.GIB))
        self.assertTrue(disk.get("{%s}format" % vm.OVF_NS).endswith("#streamOptimized"))
        items = self.items(tree)
        self.assertEqual(items["3"][0].findtext("rasd:VirtualQuantity", namespaces=NS), "2")
        self.assertEqual(items["4"][0].findtext("rasd:VirtualQuantity", namespaces=NS), "4096")
        self.assertEqual(items["17"][0].findtext("rasd:Parent", namespaces=NS),
                         items["20"][0].findtext("rasd:InstanceID", namespaces=NS))
        ids = [i.findtext("rasd:InstanceID", namespaces=NS) for k in items for i in items[k]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(tree.findtext(".//ovf:ProductSection/ovf:Version", namespaces=NS), "1.0 Beta")

    def test_virtualbox(self):
        text, tree = self.make("virtualbox")
        self.check_common(tree)
        self.assertEqual(tree.findtext(".//vssd:VirtualSystemType", namespaces=NS), "virtualbox-2.2")
        machine = tree.find(".//vbox:Machine", NS)
        self.assertEqual(machine.find("ovf:Hardware/ovf:Firmware", NS).get("type"), "EFI")
        self.assertEqual(machine.find("ovf:Hardware/ovf:Memory", NS).get("RAMSize"), "4096")
        self.assertEqual(machine.find("ovf:Hardware/ovf:CPU", NS).get("count"), "2")
        display = machine.find("ovf:Hardware/ovf:Display", NS)
        self.assertEqual(display.get("accelerate3D"), "false")
        # VirtualBox writes its own section unprefixed, so it falls in the OVF namespace
        disk = tree.find("ovf:DiskSection/ovf:Disk", NS)
        image = machine.find(".//ovf:AttachedDevice/ovf:Image", NS)
        self.assertEqual(image.get("uuid"), "{%s}" % disk.get("{%s}uuid" % vm.VBOX_NS))
        self.assertEqual(text, self.make("virtualbox")[0])  # same input, same file

    def test_vmware(self):
        _, tree = self.make("vmware")
        self.check_common(tree)
        self.assertEqual(tree.findtext(".//vssd:VirtualSystemType", namespaces=NS), "vmx-14")
        conf = {c.get("{%s}key" % vm.VMW_NS): c.get("{%s}value" % vm.VMW_NS)
                for c in tree.iterfind(".//vmw:Config", NS)}
        self.assertEqual(conf["firmware"], "efi")
        self.assertEqual(conf["enable3DSupport"], "false")
        self.assertIsNone(tree.find(".//vbox:Machine", NS))

    def test_unknown_flavour(self):
        with self.assertRaises(ValueError):
            vm.ovf("hyperv", "a", "b", "c", 1, "d", 2)

    def test_manifest_and_order(self):
        n = vm.names("raye-1.0-beta-amd64.iso")
        self.assertEqual(vm.ova_members(n)[0], n["ovf"])
        self.assertEqual(vm.manifest({"a.ovf": "ab", "b.vmdk": "cd"}),
                         "SHA256(a.ovf)= ab\nSHA256(b.vmdk)= cd\n")


class FirstStartTests(unittest.TestCase):
    def test_steps_follow_the_show_list(self):
        settings = (FIRST_START / "settings.conf").read_text()
        self.assertEqual(steps_of(settings), vm.FIRST_START_STEPS)

    @unittest.skipUnless(STRINGS.exists(), "no installer checkout next to this one")
    def test_edits_apply_to_setup_branding(self):
        text = vm.apply_edits(STRINGS.read_text(), vm.BRANDING_EDITS)
        steps = text.split("var steps = ", 1)[1].split("]", 1)[0] + "]"
        self.assertEqual(eval(steps.replace("\n", " ")), vm.FIRST_START_STEPS)  # a plain list literal
        self.assertNotIn('"disk"', text.split("var stages", 1)[1].split("]\n", 1)[0])
        self.assertNotIn("USB", text.split("doneText", 1)[1].split("\n", 1)[0])
        self.assertNotIn("clé USB", text.split("doneText", 2)[2].split("\n", 1)[0])

    @unittest.skipUnless(SETTINGS.exists(), "no installer checkout next to this one")
    def test_setup_steps_are_what_the_edits_expect(self):
        steps = steps_of(SETTINGS.read_text())
        old = vm.BRANDING_EDITS[0][0].split("= ", 1)[1]
        self.assertEqual(eval(old.replace("\n", " ")), steps)

    def test_changed_branding_stops_the_build(self):
        with self.assertRaises(vm.BrandingChanged):
            vm.apply_edits("var steps = []", vm.BRANDING_EDITS)
        with self.assertRaises(vm.BrandingChanged):
            vm.apply_edits("aa", [("a", "b")])

    def test_branding_desc(self):
        self.assertEqual(vm.first_start_branding_desc("---\ncomponentName: raye\nx: 1\n"),
                         "---\ncomponentName: raye-first-start\nx: 1\n")
        with self.assertRaises(vm.BrandingChanged):
            vm.first_start_branding_desc("componentName: other\n")

    def test_no_disk_question(self):
        settings = (FIRST_START / "settings.conf").read_text()
        for word in ("raye_disk", "rayedisk", "unpackfs", "bootloader", "summaryq", "partition"):
            self.assertNotIn(word, settings)
        self.assertIn("dont-chroot: true", settings)
        self.assertIn("branding: raye-first-start", settings)
        self.assertNotIn("storage", (FIRST_START / "modules/welcomeq.conf").read_text())

    def script(self, root, *args):
        env = dict(os.environ, RAYE_FIRST_START_ROOT=str(root))
        return subprocess.run(["sh", str(FIRST_START / "raye-first-start"), *args], env=env,
                              capture_output=True, text=True)

    def fake(self, root):
        for rel in ("var/lib/raye-first-start/xdg/x", "etc/sddm.conf.d/zz-raye-first-start.conf",
                    "etc/sudoers.d/raye-first-start", "usr/local/bin/calamares",
                    "etc/systemd/system/raye-first-start.service"):
            p = pathlib.Path(root, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")

    def test_done_then_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            self.fake(root)
            self.assertEqual(self.script(root, "cleanup").returncode, 0)
            self.assertTrue(pathlib.Path(root, "etc/sudoers.d/raye-first-start").exists())
            self.assertEqual(self.script(root, "done").returncode, 0)
            self.assertFalse(pathlib.Path(root, "etc/sddm.conf.d/zz-raye-first-start.conf").exists())
            self.assertTrue(pathlib.Path(root, "var/lib/raye-first-start/done").exists())
            self.assertEqual(self.script(root, "cleanup").returncode, 0)
            for rel in ("var/lib/raye-first-start", "etc/sudoers.d/raye-first-start",
                        "usr/local/bin/calamares", "etc/systemd/system/raye-first-start.service"):
                self.assertFalse(pathlib.Path(root, rel).exists(), rel)
        self.assertEqual(self.script("/nonexistent", "what").returncode, 2)

    def test_service_waits_for_done(self):
        unit = (FIRST_START / "raye-first-start.service").read_text()
        self.assertIn("ConditionPathExists=/var/lib/raye-first-start/done", unit)
        self.assertIn("Before=display-manager.service", unit)

    def test_sudoers_is_narrow(self):
        text = (FIRST_START / "sudoers").read_text()
        rule = [l for l in text.splitlines() if l.startswith("raye-setup ")][0]
        self.assertNotIn(" ALL\n", text + "\n")
        self.assertNotIn(": ALL", rule)
        self.assertIn("/usr/local/bin/calamares", rule)
        if shutil.which("visudo"):
            with tempfile.NamedTemporaryFile("w", suffix=".sudoers") as f:
                f.write(text)
                f.flush()
                r = subprocess.run(["visudo", "-c", "-q", "-f", f.name], capture_output=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_autologin_is_the_setup_session(self):
        text = (FIRST_START / "sddm.conf").read_text()
        self.assertIn("User=%s" % vm.SETUP_USER, text)
        self.assertIn("Session=raye-setup.desktop", text)


class CheckTests(unittest.TestCase):
    def good(self, root):
        files = {
            "boot/grub/grub.cfg": "linux /vmlinuz root=UUID=r-1 ro rootflags=subvol=@ quiet\n",
            "boot/efi/EFI/BOOT/BOOTX64.EFI": "", "boot/efi/EFI/ubuntu/grubx64.efi": "",
            "boot/efi/EFI/ubuntu/grub.cfg": "", "boot/vmlinuz-7": "", "boot/initrd.img-7": "",
            "etc/fstab": "UUID=r-1 / btrfs\nUUID=b-1 /boot ext4\nUUID=e-1 /boot/efi vfat\n",
            "etc/machine-id": "",
            "etc/passwd": "root:x:0:0::/root:/bin/bash\nraye-setup:x:990:990::/h:/bin/bash\n"
                          "nobody:x:65534:65534::/:/usr/sbin/nologin\n",
            "etc/shadow": "root:*:1::::::\nraye-setup:!:1::::::\n",
            "var/lib/raye-first-start/xdg/calamares/settings.conf": "",
            "var/lib/raye-first-start/xdg/calamares/branding/raye-first-start/branding.desc": "",
            "var/lib/raye-first-start/xdg/calamares/branding/raye-first-start/strings.js":
                'var steps = ["language", "device"]\n',
            "var/lib/raye-first-start/modules/rayefirststart/main.py": "",
            "var/lib/raye-first-start/raye-first-start": "",
            "etc/sddm.conf.d/zz-raye-first-start.conf": "", "etc/sudoers.d/raye-first-start": "",
            "usr/local/bin/calamares": "",
            "usr/share/wayland-sessions/raye-setup.desktop": "",
        }
        for rel in vm.GUEST_FILES:
            files[rel] = ""
        for rel, text in files.items():
            p = pathlib.Path(root, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        wants = pathlib.Path(root, "etc/systemd/system/multi-user.target.wants")
        wants.mkdir(parents=True)
        os.symlink("/etc/systemd/system/raye-first-start.service", wants / "raye-first-start.service")

    def test_good_tree(self):
        with tempfile.TemporaryDirectory() as root:
            self.good(root)
            self.assertEqual(vm.check_tree(root, {"root": "r-1", "boot": "b-1", "esp": "e-1"}), [])

    def test_problems_are_named(self):
        with tempfile.TemporaryDirectory() as root:
            self.good(root)
            pathlib.Path(root, "etc/machine-id").write_text("abc\n")
            with open(pathlib.Path(root, "boot/grub/grub.cfg"), "a") as f:
                f.write("menuentry 'Debian' --class debian --class osprober {}\n")
            pathlib.Path(root, "boot/efi/EFI/BOOT/BOOTX64.EFI").unlink()
            with open(pathlib.Path(root, "etc/passwd"), "a") as f:
                f.write("alex:x:1000:1000::/home/alex:/bin/bash\n")
            pathlib.Path(root, "etc/shadow").write_text("root:$6$x:1::::::\nraye-setup:!:1::::::\n")
            pathlib.Path(root, "usr/sbin/policy-rc.d").write_text("")
            problems = "\n".join(vm.check_tree(root, {"root": "r-2"}))
            for word in ("machine that built it", "machine-id", "BOOTX64.EFI", "alex", "root has a password",
                         "policy-rc.d", "UUID=r-2"):
                self.assertIn(word, problems)


if __name__ == "__main__":
    unittest.main()
