"""A new Thunderbolt device: let in while unlocked, never while locked."""

import os
import pathlib
import subprocess
import tempfile
import threading
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = HERE / "raye-thunderbolt"

LOGINCTL = r"""#!/bin/sh
case "$1" in
list-sessions) echo "2 1000 me seat0 tty2" ;;
show-session) cat "$FAKE_DIR/session" ;;
esac
"""
BOLTCTL = r"""#!/bin/sh
echo "boltctl $*" >> "$FAKE_DIR/log"
[ -e "$FAKE_DIR/bolt-refuses" ] && exit 1
echo 1 > "$FAKE_SYS/bus/thunderbolt/devices/0-1/authorized"
"""


class Thunderbolt(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.sys = self.dir / "sys"
        self.dev = self.sys / "bus/thunderbolt/devices/0-1"
        self.dev.mkdir(parents=True)
        (self.dev / "authorized").write_text("0\n")
        (self.dev / "unique_id").write_text("d0010000-0082-8718-23d6-8ae1d6d1e621\n")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("loginctl", LOGINCTL), ("boltctl", BOLTCTL)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.session("yes", "no", "no", "user")

    def session(self, active, locked, remote, kind):
        (self.dir / "session").write_text(f"{active}\n{locked}\n{remote}\n{kind}\n")

    def run_script(self, *args, wait=True):
        env = dict(os.environ, FAKE_DIR=str(self.dir), FAKE_SYS=str(self.sys), RAYE_SYSFS=str(self.sys),
                   RAYE_TB_PAUSE="0.1", PATH=f"{self.bin}:{os.environ['PATH']}")
        proc = subprocess.Popen(["/bin/sh", str(SCRIPT), *(args or ("0-1",))], env=env)
        if wait:
            proc.wait(timeout=10)
        return proc

    def log(self):
        path = self.dir / "log"
        return path.read_text() if path.exists() else ""

    def test_unlocked_enrolls_with_bolt(self):
        self.run_script()
        self.assertIn("boltctl enroll --policy auto d0010000-0082-8718-23d6-8ae1d6d1e621", self.log())
        self.assertEqual((self.dev / "authorized").read_text().strip(), "1")

    def test_locked_waits_for_unlock(self):
        self.session("yes", "yes", "no", "user")
        proc = self.run_script(wait=False)
        time.sleep(0.6)
        self.assertEqual(self.log(), "")
        self.assertEqual((self.dev / "authorized").read_text().strip(), "0")
        self.session("yes", "no", "no", "user")
        proc.wait(timeout=10)
        self.assertEqual((self.dev / "authorized").read_text().strip(), "1")

    def test_sign_in_screen_is_not_a_person(self):
        self.session("yes", "no", "no", "greeter")
        proc = self.run_script(wait=False)
        time.sleep(0.5)
        self.assertEqual((self.dev / "authorized").read_text().strip(), "0")
        proc.kill()

    def test_remote_session_does_not_count(self):
        self.session("yes", "no", "yes", "user")
        proc = self.run_script(wait=False)
        time.sleep(0.5)
        self.assertEqual((self.dev / "authorized").read_text().strip(), "0")
        proc.kill()

    def test_unplugged_while_waiting_ends(self):
        self.session("yes", "yes", "no", "user")
        proc = self.run_script(wait=False)
        time.sleep(0.3)
        for f in self.dev.iterdir():
            f.unlink()
        self.dev.rmdir()
        self.assertEqual(proc.wait(timeout=5), 0)

    def test_without_bolt_authorizes_once(self):
        (self.dir / "bolt-refuses").touch()
        self.run_script()
        self.assertEqual((self.dev / "authorized").read_text().strip(), "1")

    def test_already_authorized_does_nothing(self):
        (self.dev / "authorized").write_text("1\n")
        self.run_script()
        self.assertEqual(self.log(), "")

    def test_odd_names_refused(self):
        for name in ("", "../0-1", ".."):
            proc = self.run_script(name)
            self.assertEqual(proc.returncode, 2)

    def test_started_only_for_held_devices(self):
        rule = (HERE / "61-raye-thunderbolt.rules").read_text()
        self.assertIn('ATTR{authorized}=="0"', rule)
        self.assertIn('ACTION=="add"', rule)
        unit = (HERE / "raye-thunderbolt@.service").read_text()
        self.assertIn("ExecStart=/usr/libexec/raye-thunderbolt %i", unit)
        self.assertIn("NoNewPrivileges=yes", unit)


if __name__ == "__main__":
    unittest.main()
