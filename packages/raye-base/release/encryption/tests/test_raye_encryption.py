#!/usr/bin/python3
"""Tests of raye-encryption, on a made-up machine: no disk is touched.

The real cryptsetup steps (online shrink, --init-only with a 32 MiB
shift, online encryption and decryption, keyslots refused while it runs)
were checked on loop images; here the order of the steps, what is
refused and where the secrets go.

Run: python3 -m unittest discover -s release/encryption/tests
"""

import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "raye-encryption")
_loader = importlib.machinery.SourceFileLoader("raye_encryption", TOOL)
_spec = importlib.util.spec_from_loader("raye_encryption", _loader)
re_ = importlib.util.module_from_spec(_spec)
_loader.exec_module(re_)

GIB = 1024 ** 3
PASSWORD = "correct horse battery"
PART = "/dev/vda3"
PARTUUID = "aaaa-bbbb"


class FakeProc:
    def __init__(self, lines, rc, on_signal=None):
        self.stdout = io.BytesIO(b"".join(l.encode() + b"\n" for l in lines))
        self.rc = rc
        self.signals = []

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self):
        return self.rc


class FakeMachine(re_.System):
    def __init__(self, root):
        super().__init__(root)
        self.encrypted = False
        self.fstype = "btrfs"
        self.boot = ("/dev/vda2", "ext4", "boot-uuid")
        self.tpm = True
        self.battery = (False, None)
        self.free = {"/": 40 * GIB, "/boot": GIB}
        self.size = 100 * GIB
        self.fs_size = 100 * GIB
        self.calls = []
        self.fail = set()
        self.proc_lines = ['{"device_bytes":"%d","device_size":"%d"}' % (n * GIB, 10 * GIB)
                           for n in (2, 5, 10)]
        self.proc_rc = 0
        self.procs = []
        self.right_password = PASSWORD
        self.battery_during_run = None
        for d in ("etc", "run", "boot", "dev/mapper", "var/lib"):
            os.makedirs(self.path(d), exist_ok=True)

    def mount(self, target):
        if target == "/":
            if self.encrypted:
                return "/dev/mapper/luks-old", self.fstype, "fs-uuid"
            return PART, self.fstype, "fs-uuid"
        return self.boot if target == "/boot" else None

    def lsblk(self, dev, column):
        if column == "TYPE":
            return "crypt" if dev.startswith("/dev/mapper/") else "part"
        if column == "FSTYPE":
            return "crypto_LUKS" if self.encrypted else "btrfs"
        return {"PARTUUID": PARTUUID, "UUID": "old-luks-uuid"}.get(column, "")

    def parent(self, dev):
        return PART

    def free_bytes(self, target):
        return self.free[target]

    def btrfs_devices(self, target):
        return [("1", str(self.fs_size), PART)]

    def device_size(self, dev):
        return self.size

    def has_tpm(self):
        return self.tpm

    def power(self):
        return self.battery

    def run(self, argv, data=None, check=False):
        self.calls.append((argv, data))
        rc = 1 if argv[0] in self.fail else 0
        out = b""
        if argv[:3] == ["btrfs", "filesystem", "resize"]:
            self.fs_size = int(argv[3].split(":")[1])
        elif argv[:2] == ["clevis", "encrypt"]:
            out = b"JWE(" + data + b")"
        elif argv[:2] == ["clevis", "decrypt"]:
            out = data[4:-1]
        elif argv[:2] == ["cryptsetup", "luksHeaderBackup"]:
            open(argv[-1], "w").close()
        elif "--test-passphrase" in argv:
            rc = 0 if data.decode() == self.right_password else 2
        if check and rc != 0:
            raise RuntimeError("%s failed" % argv[0])
        return rc, out, b""

    def popen(self, argv, data=None):
        self.calls.append((argv, data))
        if self.battery_during_run:
            self.battery = self.battery_during_run
        proc = FakeProc(self.proc_lines, self.proc_rc)
        self.procs.append(proc)
        return proc


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.m = FakeMachine(self.tmp)

    def tool(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        rc = re_.main(list(argv), system=self.m, stdin=io.StringIO(stdin), out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    def state(self):
        with open(self.m.path(re_.STATE_DIR + "/state.json")) as f:
            return json.load(f)

    def commands(self):
        return [argv for argv, _ in self.m.calls]

    def files_with(self, text):
        found = []
        for folder, _, names in os.walk(self.tmp):
            for n in names:
                with open(os.path.join(folder, n), "rb") as f:
                    if text.encode() in f.read():
                        found.append(os.path.relpath(os.path.join(folder, n), self.tmp))
        return found

    def crypttab(self):
        try:
            with open(self.m.path("/etc/crypttab")) as f:
                return f.read()
        except FileNotFoundError:
            return ""


class CheckTest(Base):
    def refused(self, mode="encrypt"):
        rc, _, err = self.tool("check", mode)
        self.assertEqual(rc, re_.EXIT_REFUSED, err)
        return err.split()[0]

    def test_ready(self):
        self.assertEqual(self.tool("check", "encrypt")[0], 0)

    def test_needs_the_security_chip(self):
        self.m.tpm = False
        self.assertEqual(self.refused(), "no-tpm")

    def test_low_battery(self):
        self.m.battery = (True, 35)
        self.assertEqual(self.refused(), "battery")
        self.m.battery = (True, 80)
        self.assertEqual(self.tool("check", "encrypt")[0], 0)
        self.m.battery = (False, 10)  # plugged in
        self.assertEqual(self.tool("check", "encrypt")[0], 0)

    def test_not_enough_space(self):
        self.m.free["/"] = GIB
        self.assertEqual(self.refused(), "space")
        self.m.free["/"] = 40 * GIB
        self.m.free["/boot"] = 50 * 1024 ** 2
        self.assertEqual(self.refused(), "boot-space")

    def test_other_disks(self):
        self.m.fstype = "ext4"
        self.assertEqual(self.refused(), "unsupported-disk")
        self.m.fstype = "btrfs"
        self.m.boot = None
        self.assertEqual(self.refused(), "unsupported-disk")

    def test_already_on_or_off(self):
        self.m.encrypted = True
        self.assertEqual(self.refused("encrypt"), "already-encrypted")
        self.m.encrypted = False
        self.assertEqual(self.refused("decrypt"), "not-encrypted")

    def test_one_at_a_time(self):
        self.assertEqual(self.tool("encrypt", stdin=PASSWORD + "\n")[0], 0)
        self.assertEqual(self.refused(), "busy")

    def test_status_says_why_without_root(self):
        self.m.battery = (True, 20)
        rc, out, _ = self.tool("status", "--json")
        status = json.loads(out)
        self.assertEqual((rc, status["blocked"], status["encrypted"], status["tpm"]),
                         (0, "battery", False, True))


class EncryptTest(Base):
    def encrypt(self):
        rc, out, err = self.tool("encrypt", stdin=PASSWORD + "\n")
        self.assertEqual(rc, 0, err)
        return out

    def test_gets_ready_for_the_next_start(self):
        out = self.encrypt()
        key = re.fullmatch(r"recovery-key ((\d{6}-){7}\d{6})\n", out)
        self.assertTrue(key, out)
        # the file system leaves the last 32 MiB to the header
        self.assertLessEqual(self.m.fs_size, self.m.size - re_.SHIFT)
        self.assertEqual(self.m.fs_size % 4096, 0)
        st = self.state()
        self.assertEqual((st["mode"], st["phase"], st["partuuid"]), ("encrypt", "restart", PARTUUID))
        self.assertEqual(st["name"], "luks-" + st["uuid"])
        with open(self.m.path("/etc/raye-encryption/plan")) as f:
            plan = dict(l.split("=", 1) for l in f.read().split())
        self.assertEqual(plan["MODE"], "encrypt")
        self.assertEqual(plan["UUID"], st["uuid"])
        self.assertTrue(os.path.exists(self.m.path(re_.STATE_DIR + "/active")))
        self.assertIn(["update-initramfs", "-u", "-k", "all"], self.commands())
        # sealed before the initramfs is made, so it carries them
        cmds = self.commands()
        self.assertLess(cmds.index(["clevis", "encrypt", "tpm2", "{}"]),
                        cmds.index(["update-initramfs", "-u", "-k", "all"]))

    def test_secrets_only_sealed(self):
        out = self.encrypt()
        key = out.split()[1]
        sealed = self.files_with(PASSWORD)
        self.assertEqual(sealed, ["etc/raye-encryption/pass.jwe"])
        self.assertEqual(self.files_with(key), ["etc/raye-encryption/recovery.jwe"])
        mode = os.stat(self.m.path("/etc/raye-encryption/pass.jwe")).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertNotIn(PASSWORD, json.dumps(self.state()))
        for argv, _ in self.m.calls:
            self.assertNotIn(PASSWORD, " ".join(argv))

    def test_refused_changes_nothing(self):
        self.m.tpm = False
        rc, _, _ = self.tool("encrypt", stdin=PASSWORD + "\n")
        self.assertEqual(rc, re_.EXIT_REFUSED)
        self.assertEqual(self.m.calls, [])
        self.assertEqual(self.m.fs_size, self.m.size)
        self.assertFalse(os.path.exists(self.m.path("/etc/raye-encryption")))

    def test_empty_password(self):
        self.assertEqual(self.tool("encrypt", stdin="\n")[0], re_.EXIT_REFUSED)
        self.assertEqual(self.m.calls, [])

    def test_initramfs_failure_takes_the_secrets_back(self):
        self.m.fail.add("update-initramfs")
        rc, _, _ = self.tool("encrypt", stdin=PASSWORD + "\n")
        self.assertEqual(rc, re_.EXIT_ERROR)
        self.assertEqual(self.files_with(PASSWORD), [])
        self.assertFalse(os.path.exists(self.m.path(re_.STATE_DIR + "/active")))

    def after_restart(self):
        out = self.encrypt()
        st = self.state()
        # what the initramfs did at the next start
        open(self.m.path("/dev/mapper/" + st["name"]), "w").close()
        os.makedirs(self.m.path("/dev/disk/by-partuuid"))
        open(self.m.path("/dev/disk/by-partuuid/" + PARTUUID), "w").close()
        self.m.calls.clear()
        return out.split()[1], st

    def test_runs_then_adds_the_keys(self):
        key, st = self.after_restart()
        rc, out, err = self.tool("run")
        self.assertEqual(rc, 0, err)
        cmds = self.commands()
        run = next(a for a in cmds if "reencrypt" in a)
        self.assertEqual(run[:4], ["nice", "-n", "10", "ionice"])
        self.assertIn("--resume-only", run)
        self.assertEqual(run[run.index("--active-name") + 1], st["name"])
        add = next(i for i, a in enumerate(cmds) if a[:2] == ["cryptsetup", "luksAddKey"])
        bind = next(i for i, a in enumerate(cmds) if a[:3] == ["clevis", "luks", "bind"])
        initrd = max(i for i, a in enumerate(cmds) if a[0] == "update-initramfs")
        # keyslots only once the disk is encrypted, then the initramfs
        self.assertLess(cmds.index(run), add)
        self.assertLess(add, bind)
        self.assertLess(bind, initrd)
        self.assertIn("UUID=%s none luks,discard" % st["uuid"], self.crypttab())
        self.assertEqual(self.state()["phase"], "done")
        self.assertEqual(self.files_with(PASSWORD), [])
        self.assertEqual(self.files_with(key), [])
        self.assertFalse(os.path.exists(self.m.path(re_.STATE_DIR + "/active")))
        with open(self.m.path("/run/raye-encryption/progress.json")) as f:
            self.assertEqual(json.load(f), {"done": 10 * GIB, "size": 10 * GIB})

    def test_power_cut_keeps_everything_for_the_next_start(self):
        key, st = self.after_restart()
        self.m.proc_rc = 1
        rc, _, _ = self.tool("run")
        self.assertEqual(rc, re_.EXIT_ERROR)
        self.assertEqual(self.state()["phase"], "paused")
        self.assertFalse([a for a in self.commands() if a[:2] == ["cryptsetup", "luksAddKey"]])
        self.assertTrue(os.path.exists(self.m.path("/etc/raye-encryption/pass.jwe")))
        self.assertTrue(os.path.exists(self.m.path(re_.STATE_DIR + "/active")))
        self.assertEqual(self.crypttab(), "")

    def test_low_battery_pauses(self):
        self.after_restart()
        self.m.battery_during_run = (True, 9)
        self.m.proc_rc = 1
        self.tool("run")
        self.assertEqual(self.m.procs[0].signals[0], signal.SIGINT)
        self.assertEqual((self.state()["phase"], self.state()["error"]), ("paused", "battery"))

    def test_status_shows_progress(self):
        self.after_restart()
        st = self.state()
        st["phase"] = "running"
        re_.write_file(self.m.path(re_.STATE_DIR + "/state.json"), json.dumps(st).encode(), 0o644)
        re_.write_file(self.m.path("/run/raye-encryption/progress.json"),
                       b'{"done": 25, "size": 100}', 0o644)
        status = json.loads(self.tool("status", "--json")[1])
        self.assertEqual((status["phase"], status["percent"]), ("running", 25.0))
        self.assertNotIn("blocked", status)


class DecryptTest(Base):
    def setUp(self):
        super().setUp()
        self.m.encrypted = True
        with open(self.m.path("/etc/crypttab"), "w") as f:
            f.write("# Encrypted disks\nluks-old UUID=old-luks-uuid none luks,discard\nswap /dev/x none\n")

    def test_wrong_password(self):
        rc, _, err = self.tool("decrypt", stdin="nope\n")
        self.assertEqual(rc, re_.EXIT_WRONG_PASSWORD)
        self.assertIn("luks-old", self.crypttab())
        self.assertFalse([a for a in self.commands() if a[0] in ("update-initramfs", "systemctl")])

    def test_starts_in_the_background(self):
        rc, _, err = self.tool("decrypt", stdin=PASSWORD + "\n")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("luks-old", self.crypttab())
        self.assertIn("swap /dev/x none", self.crypttab())
        cmds = self.commands()
        backup = next(i for i, a in enumerate(cmds) if a[:2] == ["cryptsetup", "luksHeaderBackup"])
        initrd = cmds.index(["update-initramfs", "-u", "-k", "all"])
        self.assertLess(backup, initrd)
        self.assertEqual(cmds[-1], ["systemctl", "--no-block", "start", "raye-encryption.service"])
        with open(self.m.path("/run/raye-encryption/key")) as f:
            self.assertEqual(f.read(), PASSWORD)
        self.assertEqual(os.stat(self.m.path("/run/raye-encryption/key")).st_mode & 0o777, 0o600)

    def test_off_once_decrypted_before_the_restart(self):
        self.tool("decrypt", stdin=PASSWORD + "\n")
        open(self.m.path("/dev/mapper/luks-old"), "w").close()
        self.assertTrue(json.loads(self.tool("status", "--json")[1])["encrypted"])
        self.tool("run")
        orig = self.m.lsblk
        self.m.lsblk = lambda dev, col: "btrfs" if col == "FSTYPE" else orig(dev, col)
        self.assertFalse(json.loads(self.tool("status", "--json")[1])["encrypted"])

    def test_menu_and_fstab_point_at_the_plain_disk(self):
        os.makedirs(self.m.path("/boot/grub"))
        with open(self.m.path("/boot/grub/grub.cfg"), "w") as f:
            f.write("linux /vmlinuz root=/dev/mapper/luks-old ro rootflags=subvol=@ quiet\n")
        with open(self.m.path("/etc/fstab"), "w") as f:
            f.write("/dev/mapper/luks-old / btrfs subvol=@ 0 0\n"
                    "/dev/mapper/luks-old /home btrfs subvol=@home 0 0\n"
                    "UUID=boot-uuid /boot ext4 defaults 0 2\n")
        self.tool("decrypt", stdin=PASSWORD + "\n")
        open(self.m.path("/dev/mapper/luks-old"), "w").close()
        open(self.m.path("/boot/raye-encryption/header.img"), "w").close()
        self.assertEqual(self.tool("run")[0], 0)
        with open(self.m.path("/boot/grub/grub.cfg")) as f:
            self.assertEqual(f.read(), "linux /vmlinuz root=UUID=fs-uuid ro rootflags=subvol=@ quiet\n")
        with open(self.m.path("/etc/fstab")) as f:
            self.assertEqual(f.read(), "UUID=fs-uuid / btrfs subvol=@ 0 0\n"
                                       "UUID=fs-uuid /home btrfs subvol=@home 0 0\n"
                                       "UUID=boot-uuid /boot ext4 defaults 0 2\n")

    def test_run_then_resume_then_done(self):
        self.tool("decrypt", stdin=PASSWORD + "\n")
        open(self.m.path("/dev/mapper/luks-old"), "w").close()
        self.m.calls.clear()
        self.m.proc_rc = 1
        self.tool("run")
        first = next(a for a in self.commands() if "reencrypt" in a)
        self.assertIn("--decrypt", first)
        self.assertEqual(first[first.index("--header") + 1], self.m.path("/boot/raye-encryption/header.img"))
        # cryptsetup wrote the header to /boot before the cut
        open(self.m.path("/boot/raye-encryption/header.img"), "w").close()
        self.m.calls.clear()
        self.m.proc_rc = 0
        rc, _, err = self.tool("run")
        self.assertEqual(rc, 0, err)
        second = next(a for a in self.commands() if "reencrypt" in a)
        self.assertIn("--resume-only", second)
        self.assertEqual(self.state()["phase"], "done")
        self.assertEqual(os.listdir(self.m.path("/boot/raye-encryption")), [])
        self.assertEqual(self.files_with(PASSWORD), [])

    def test_done_refreshes_the_chip_state(self):
        self.tool("decrypt", stdin=PASSWORD + "\n")
        open(self.m.path("/dev/mapper/luks-old"), "w").close()
        open(self.m.path("/boot/raye-encryption/header.img"), "w").close()
        self.m.calls.clear()
        self.assertEqual(self.tool("run")[0], 0)
        self.assertIn(["/usr/libexec/raye-kernel-setup", "tpm-status"], self.commands())


class InitramfsTest(unittest.TestCase):
    """The local-top script, with its paths moved into a folder and the
    tools replaced by stubs that write down how they were called."""

    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t)
        t = self.t
        with open(os.path.join(HERE, "..", "initramfs-local-top")) as f:
            script = f.read()
        for real, fake in (("/etc/raye-encryption", t + "/etc/raye-encryption"),
                           ("/scripts/functions", t + "/functions"), ("/run/", t + "/run/"),
                           ("/dev/", t + "/dev/"), ("/lib/cryptsetup/askpass", t + "/bin/askpass"),
                           ("/bin/plymouth", t + "/nope/plymouth")):
            script = script.replace(real, fake)
        self.script = os.path.join(t, "local-top")
        with open(self.script, "w") as f:
            f.write(script)
        for d in ("etc/raye-encryption", "bin", "dev/mapper", "dev/disk/by-partuuid", "run"):
            os.makedirs(os.path.join(t, d))
        open(os.path.join(t, "dev/disk/by-partuuid/pp"), "w").close()
        with open(os.path.join(t, "functions"), "w") as f:
            f.write('wait_for_udev() { :; }\nlog_failure_msg() { echo "$*" >&2; }\n')
        self.calls = os.path.join(t, "calls")
        stub = '#!/bin/sh\necho "$(basename $0) $*" >> %s\n' % self.calls
        for name, body in (("cryptsetup", 'case "$1" in isLuks) exit ${LUKS:-1};; esac\n'
                                          'for a; do last2=$last; last=$a; done\n'
                                          'case "$1" in reencrypt|open) : > %s/dev/mapper/$last;; esac\n' % t),
                           ("clevis", 'cat > /dev/null; [ -n "$CLEVIS_FAILS" ] && exit 1; printf "sealed-pass"\n'),
                           ("askpass", 'printf "typed-pass"\n'),
                           ("btrfs", ""), ("modprobe", ""), ("mount", 'exit ${MOUNT_FAILS:-0}\n'),
                           ("umount", "")):
            path = os.path.join(t, "bin", name)
            with open(path, "w") as f:
                f.write(stub + body)
            os.chmod(path, 0o755)

    def plan(self, mode):
        with open(os.path.join(self.t, "etc/raye-encryption/plan"), "w") as f:
            f.write("MODE=%s\nPARTUUID=pp\nUUID=uu\nNAME=luks-uu\nBOOT_UUID=bb\n" % mode)
        open(os.path.join(self.t, "etc/raye-encryption/pass.jwe"), "w").close()

    def run_script(self, **env):
        import subprocess
        full = dict(os.environ, PATH=os.path.join(self.t, "bin") + ":/usr/bin:/bin", **env)
        p = subprocess.run(["sh", self.script], env=full, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        try:
            with open(self.calls) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def key(self):
        path = os.path.join(self.t, "run/raye-encryption/key")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        with open(path) as f:
            return f.read()

    def test_no_plan_no_work(self):
        self.assertEqual(self.run_script(), [])

    def test_first_start_writes_the_header(self):
        self.plan("encrypt")
        calls = self.run_script()
        init = [c for c in calls if c.startswith("cryptsetup reencrypt")]
        self.assertEqual(len(init), 1, calls)
        for word in ("--encrypt", "--init-only", "--reduce-device-size 32M", "--uuid uu",
                     self.t + "/dev/disk/by-partuuid/pp luks-uu"):
            self.assertIn(word, init[0])
        self.assertEqual(self.key(), "sealed-pass")

    def test_later_starts_only_open(self):
        self.plan("encrypt")
        calls = self.run_script(LUKS="0")
        self.assertFalse([c for c in calls if "reencrypt" in c])
        self.assertTrue([c for c in calls if c.startswith("cryptsetup open")])

    def test_already_open(self):
        self.plan("encrypt")
        open(os.path.join(self.t, "dev/mapper/luks-uu"), "w").close()
        self.assertEqual(self.run_script(), [])

    def test_decrypt_uses_the_header_in_boot(self):
        self.plan("decrypt")
        # the stub mount does nothing: the header stands where /boot would be
        os.makedirs(os.path.join(self.t, "run/raye-boot/raye-encryption"))
        open(os.path.join(self.t, "run/raye-boot/raye-encryption/header.img"), "w").close()
        calls = self.run_script()
        opened = [c for c in calls if c.startswith("cryptsetup open")]
        self.assertIn("--header " + self.t + "/run/raye-boot/raye-encryption/header.img", opened[0])

    def test_decrypt_not_started_yet(self):
        self.plan("decrypt")
        calls = self.run_script(LUKS="0")
        opened = [c for c in calls if c.startswith("cryptsetup open")]
        self.assertNotIn("--header", opened[0])

    def test_asks_when_the_chip_says_no(self):
        self.plan("encrypt")
        self.run_script(CLEVIS_FAILS="1")
        self.assertEqual(self.key(), "typed-pass")


class InitramfsHookTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t)
        with open(os.path.join(HERE, "..", "initramfs-hook")) as f:
            script = f.read()
        script = script.replace("/usr/share/initramfs-tools/hook-functions", self.t + "/functions")
        script = script.replace("/etc/raye-encryption", self.t + "/etc/raye-encryption")
        self.script = os.path.join(self.t, "hook")
        with open(self.script, "w") as f:
            f.write(script)
        self.calls = os.path.join(self.t, "calls")
        with open(os.path.join(self.t, "functions"), "w") as f:
            f.write('copy_exec() { echo "copy_exec $#:$*" >> %s; }\n'
                    'manual_add_modules() { echo "modules $*" >> %s; }\n' % (self.calls, self.calls))
        self.dest = os.path.join(self.t, "dest")
        os.makedirs(self.dest)

    def run_hook(self):
        import subprocess
        p = subprocess.run(["sh", self.script], env=dict(os.environ, DESTDIR=self.dest),
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        try:
            with open(self.calls) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def test_nothing_without_a_plan(self):
        self.assertEqual(self.run_hook(), [])

    def test_copies_the_tools_and_the_sealed_password_only(self):
        os.makedirs(os.path.join(self.t, "etc/raye-encryption"))
        for name in ("plan", "pass.jwe", "recovery.jwe"):
            open(os.path.join(self.t, "etc/raye-encryption", name), "w").close()
        calls = self.run_hook()
        # one argument: the tool keeps its own path in the initramfs
        self.assertIn("copy_exec 1:/usr/sbin/cryptsetup", calls)
        self.assertIn("modules dm_crypt", calls)
        # the folder name was moved like the rest: DESTDIR + the moved path
        copied = sorted(os.listdir(os.path.join(self.dest, self.t.lstrip("/"), "etc/raye-encryption")))
        self.assertEqual(copied, ["pass.jwe", "plan"])


class PasswordTest(unittest.TestCase):
    def test_read(self):
        self.assertEqual(re_.Tool.read_password(io.StringIO("a b\n")), "a b")
        for bad in ("", "\n"):
            with self.assertRaises(re_.Refused):
                re_.Tool.read_password(io.StringIO(bad))

    def test_progress_lines(self):
        self.assertEqual(re_.parse_progress('{"device_bytes":"5","device_size":"9"}'), (5, 9))
        self.assertIsNone(re_.parse_progress("Progress: 5%"))


if __name__ == "__main__":
    unittest.main()
