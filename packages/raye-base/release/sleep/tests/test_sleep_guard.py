# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-sleep-guard on fake machine trees: the mark around sleep, the rule
at boot (warning, then off; flat battery not counted; a wake resets), the
known list, "turn sleep back on", and the notice in the session.

    python3 -B -m unittest discover -s release/sleep/tests
"""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE.parent / "raye-sleep-guard"
HOOK = HERE.parent / "raye-sleep-guard.hook"
LIST = HERE.parent / "no-sleep.list"


def load():
    loader = importlib.machinery.SourceFileLoader("raye_sleep_guard", str(TOOL))
    spec = importlib.util.spec_from_loader("raye_sleep_guard", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


g = load()


class Machine:
    """A fake root: DMI, power supplies, boot id, the shipped list."""

    def __init__(self, vendor="LENOVO", product="ThinkPad T480", mains=True, battery=80, lid=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.write("sys/class/dmi/id/sys_vendor", vendor + "\n")
        self.write("sys/class/dmi/id/product_name", product + "\n")
        self.set_power(mains, battery)
        self.new_boot()
        self.write("usr/share/raye/sleep-guard/no-sleep.list", LIST.read_text())
        if lid:
            self.write("proc/acpi/button/lid/LID0/state", "state:      open\n")
        self.logs = []

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def set_power(self, mains, battery):
        if mains is not None:
            self.write("sys/class/power_supply/AC/type", "Mains\n")
            self.write("sys/class/power_supply/AC/online", "1\n" if mains else "0\n")
        if battery is not None:
            self.write("sys/class/power_supply/BAT0/type", "Battery\n")
            self.write("sys/class/power_supply/BAT0/capacity", "%d\n" % battery)
        # a mouse battery never counts
        self.write("sys/class/power_supply/hidpp_battery_0/type", "Battery\n")
        self.write("sys/class/power_supply/hidpp_battery_0/scope", "Device\n")
        self.write("sys/class/power_supply/hidpp_battery_0/capacity", "1\n")

    def new_boot(self):
        self.write("proc/sys/kernel/random/boot_id", os.urandom(8).hex() + "\n")

    # the life of the PC
    def sleep_ok(self, mode="suspend"):
        g.pre(self.root, mode)
        g.post(self.root, mode)

    def sleep_frozen(self, mode="suspend"):
        """pre, then nothing: the power button is held, the PC starts again."""
        g.pre(self.root, mode)
        self.new_boot()
        self.boot()

    def boot(self, now=None):
        g.boot(self.root, now=now, log=self.logs.append)

    def state(self):
        return g.load_state(self.root)

    def dropin(self):
        return (self.root / g.DROPIN).exists()

    def close(self):
        self.tmp.cleanup()


class Rule(unittest.TestCase):
    def setUp(self):
        self.m = Machine()
        self.addCleanup(self.m.close)

    def test_a_pc_that_sleeps_well_keeps_nothing(self):
        self.m.boot()
        self.m.sleep_ok()
        self.m.new_boot()
        self.m.boot()
        self.assertFalse((self.m.root / g.STATE).exists())
        self.assertFalse((self.m.root / g.MARK).exists())
        self.assertFalse(self.m.dropin())

    def test_the_mark_is_on_disk_during_sleep(self):
        g.pre(self.m.root, "suspend")
        mark = json.loads((self.m.root / g.MARK).read_text())
        self.assertEqual(mark["mode"], "suspend")
        self.assertIs(mark["ac"], True)
        self.assertEqual(mark["battery"], 80)
        g.post(self.m.root, "suspend")
        self.assertFalse((self.m.root / g.MARK).exists())

    def test_hibernate_is_not_watched(self):
        g.pre(self.m.root, "hibernate")
        self.assertFalse((self.m.root / g.MARK).exists())

    def test_first_failure_only_warns(self):
        self.m.sleep_frozen()
        s = self.m.state()
        self.assertEqual((s["status"], s["failures"], s["event"]), ("warned", 1, 1))
        self.assertFalse(self.m.dropin(), "one failure must not turn sleep off")
        self.assertFalse((self.m.root / g.MARK).exists())

    def test_second_failure_in_a_row_turns_sleep_off(self):
        self.m.sleep_frozen()
        self.m.sleep_frozen()
        s = self.m.state()
        self.assertEqual((s["status"], s["reason"], s["event"]), ("off", "failed", 2))
        self.assertTrue(self.m.dropin())
        text = (self.m.root / g.DROPIN).read_text()
        for key in ("AllowSuspend=no", "AllowHybridSleep=no", "AllowSuspendThenHibernate=no"):
            self.assertIn(key, text)
        self.assertNotIn("AllowHibernation", text)

    def test_a_wake_between_two_failures_starts_again(self):
        self.m.sleep_frozen()
        self.m.sleep_ok()
        s = self.m.state()
        self.assertEqual((s["status"], s["failures"]), ("ok", 0))
        self.m.sleep_frozen()
        self.assertEqual(self.m.state()["status"], "warned")
        self.assertFalse(self.m.dropin())

    def test_hybrid_and_then_hibernate_count_too(self):
        self.m.sleep_frozen("hybrid-sleep")
        self.m.sleep_frozen("suspend-then-hibernate")
        self.assertEqual(self.m.state()["status"], "off")

    def test_flat_battery_is_not_counted(self):
        self.m.set_power(False, 60)
        g.pre(self.m.root, "suspend")
        self.m.set_power(True, 2)      # plugged in again, battery empty
        self.m.new_boot()
        self.m.boot()
        self.assertFalse((self.m.root / g.STATE).exists())
        self.assertFalse((self.m.root / g.MARK).exists(), "the mark is used once")
        self.assertTrue(any("battery" in line for line in self.m.logs))

    def test_on_battery_with_charge_left_counts(self):
        self.m.set_power(False, 60)
        g.pre(self.m.root, "suspend")
        self.m.set_power(False, 55)
        self.m.new_boot()
        self.m.boot()
        self.assertEqual(self.m.state()["failures"], 1)

    def test_battery_unknown_at_boot_old_sleep_on_battery_is_unclear(self):
        mark = {"boot": "x", "time": 1000, "mode": "suspend", "ac": False, "battery": 40}
        self.assertEqual(g.judge(mark, None, 1000 + 4 * 3600), "unclear")
        self.assertEqual(g.judge(mark, None, 1000 + 600), "failed")
        self.assertEqual(g.judge(dict(mark, ac=True), None, 1000 + 99 * 3600), "failed")
        self.assertEqual(g.judge(dict(mark, ac=None), 3, 1000), "failed")

    def test_a_mark_of_this_same_start_is_left(self):
        g.pre(self.m.root, "suspend")
        self.m.boot()                   # the service restarted, no new start
        self.assertTrue((self.m.root / g.MARK).exists())
        self.assertFalse((self.m.root / g.STATE).exists())

    def test_a_halfwritten_mark_is_dropped_without_counting(self):
        self.m.write(g.MARK, "{\"boot\": ")
        self.m.new_boot()
        self.m.boot()
        self.assertFalse((self.m.root / g.MARK).exists())
        self.assertFalse((self.m.root / g.STATE).exists())

    def test_dropin_follows_the_state_at_every_start(self):
        self.m.sleep_frozen()
        self.m.sleep_frozen()
        (self.m.root / g.DROPIN).unlink()       # /run is empty after a restart
        self.m.new_boot()
        self.m.boot()
        self.assertTrue(self.m.dropin())

    def test_turn_back_on(self):
        self.m.sleep_frozen()
        self.m.sleep_frozen()
        g.enable(self.m.root)
        s = self.m.state()
        self.assertEqual((s["status"], s["failures"], s["user_on"]), ("ok", 0, True))
        self.assertFalse(self.m.dropin())
        self.m.new_boot()
        self.m.boot()
        self.assertFalse(self.m.dropin())
        # two more failures turn it off again
        self.m.sleep_frozen()
        self.assertFalse(self.m.dropin())
        self.m.sleep_frozen()
        self.assertTrue(self.m.dropin())


class KnownList(unittest.TestCase):
    def test_latitude_5490_is_off_from_the_start(self):
        m = Machine("Dell Inc.", "Latitude 5490")
        self.addCleanup(m.close)
        m.boot()
        s = m.state()
        self.assertEqual((s["status"], s["reason"], s["event"]), ("off", "model", 1))
        self.assertTrue(m.dropin())
        m.new_boot()
        m.boot()
        self.assertEqual(m.state()["event"], 1, "said once, not at every start")

    def test_other_dells_are_not(self):
        for product in ("Latitude 5480", "Latitude 5490 2-in-1", "latitude 5490"):
            m = Machine("Dell Inc.", product)
            self.addCleanup(m.close)
            m.boot()
            self.assertFalse(m.dropin(), product)

    def test_the_user_wins_over_the_list(self):
        m = Machine("Dell Inc.", "Latitude 5490")
        self.addCleanup(m.close)
        m.boot()
        g.enable(m.root)
        m.new_boot()
        m.boot()
        self.assertFalse(m.dropin())
        self.assertEqual(m.state()["status"], "ok")

    def test_off_by_the_list_comes_back_when_the_list_drops_it(self):
        m = Machine("Dell Inc.", "Latitude 5490")
        self.addCleanup(m.close)
        m.boot()
        m.write(g.LIST, "# empty\n")
        m.new_boot()
        m.boot()
        self.assertFalse(m.dropin())

    def test_list_parsing(self):
        m = Machine()
        self.addCleanup(m.close)
        m.write(g.LIST, "no bar here\n | x\nA | B # why\n")
        self.assertTrue(g.known_bad(m.root, "A", "B"))
        self.assertFalse(g.known_bad(m.root, "", "x"))


class FakePowerdevilrc:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self, group, key):
        v = self.values.get((group, key))
        return "" if v is None else str(v)

    def write(self, group, key, value):
        if value is None:
            self.values.pop((group, key), None)
        else:
            self.values[(group, key)] = value


class Session(unittest.TestCase):
    def setUp(self):
        self.m = Machine()
        self.addCleanup(self.m.close)
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = {"XDG_STATE_HOME": self.home.name, "LANG": "en_US.UTF-8"}
        self.rc = FakePowerdevilrc()
        self.sent = []
        self.refreshed = 0

    def notice(self):
        def refresh():
            self.refreshed += 1
        g.notice(self.m.root, env=self.env, read=self.rc.read, write=self.rc.write,
                 send=lambda t, b, w: self.sent.append((t, b)), refresh=refresh)

    def turn_off(self):
        self.m.sleep_frozen()
        self.m.sleep_frozen()

    def test_off_says_it_once(self):
        self.turn_off()
        self.notice()
        self.notice()
        self.assertEqual(len(self.sent), 1)
        title, body = self.sent[0]
        self.assertEqual(title, "Sleep is turned off on this PC")
        self.assertIn("Sleep doesn't work on this PC, so Raye turned it off.", body)
        self.assertIn("Closing the lid locks the PC and turns off the screen.", body)
        self.assertIn("Settings > System > Power & battery", body)

    def test_first_failure_warns_then_off_says_again(self):
        self.m.sleep_frozen()
        self.notice()
        self.assertIn("didn't wake up", self.sent[-1][0])
        self.m.sleep_frozen()
        self.notice()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("turned off", self.sent[-1][0])

    def test_french(self):
        self.env["LANG"] = "fr_CA.UTF-8"
        self.turn_off()
        self.notice()
        title, body = self.sent[0]
        self.assertEqual(title, "La mise en veille est désactivée sur ce PC")
        self.assertIn("Paramètres > Système > Alimentation et batterie", body)
        self.assertIn("Fermer le capot", body)

    def test_desktop_without_lid_or_battery(self):
        m = Machine(battery=None, lid=False)
        self.addCleanup(m.close)
        self.m = m
        self.turn_off()
        self.notice()
        body = self.sent[0][1]
        self.assertNotIn("lid", body)
        self.assertIn("Settings > System > Power.", body)

    def test_lid_sleep_becomes_lock_and_screen_off_and_comes_back(self):
        self.rc = FakePowerdevilrc({("AC", "LidAction"): 1, ("Battery", "LidAction"): 1,
                                    ("AC", "PowerButtonAction"): 16, ("AC", "AutoSuspendAction"): 1})
        self.turn_off()
        self.notice()
        self.assertEqual(self.rc.values[("AC", "LidAction")], 64)
        self.assertEqual(self.rc.values[("Battery", "LidAction")], 64)
        self.assertEqual(self.rc.values[("AC", "PowerButtonAction")], 16)
        self.assertEqual(self.rc.values[("AC", "AutoSuspendAction")], 0)
        self.assertEqual(self.refreshed, 1)
        g.enable(self.m.root)
        self.notice()
        self.assertNotIn(("AC", "LidAction"), self.rc.values, "back to the daemon's default")
        self.assertNotIn(("AC", "AutoSuspendAction"), self.rc.values)
        self.assertEqual(self.rc.values[("AC", "PowerButtonAction")], 16, "the user's own choice stays")

    def test_a_choice_made_while_off_is_kept(self):
        self.rc = FakePowerdevilrc({("AC", "LidAction"): 1})
        self.turn_off()
        self.notice()
        self.rc.values[("AC", "LidAction")] = 8      # chose "Shut down" meanwhile
        g.enable(self.m.root)
        self.notice()
        self.assertEqual(self.rc.values[("AC", "LidAction")], 8)

    def test_unset_lid_is_left_to_the_daemon(self):
        self.turn_off()
        self.notice()
        self.assertEqual(self.rc.values, {})
        self.assertEqual(self.refreshed, 0)

    def test_nothing_to_say_on_a_good_pc(self):
        self.notice()
        self.assertEqual(self.sent, [])


class Command(unittest.TestCase):
    def run_tool(self, *args, env=None, root=None):
        e = {"PATH": "/usr/bin:/bin"}
        if root:
            e["RAYE_SLEEP_ROOT"] = str(root)
        e.update(env or {})
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, env=e)

    def test_pkexec_may_only_enable(self):
        m = Machine("Dell Inc.", "Latitude 5490")
        self.addCleanup(m.close)
        res = self.run_tool("boot", env={"PKEXEC_UID": "1000"}, root=m.root)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(m.dropin())

    def test_hook_passes_its_arguments(self):
        text = HOOK.read_text()
        self.assertIn('/usr/libexec/raye-sleep-guard "$@"', text)
        self.assertIn("exit 0", text)

    def test_cli_round(self):
        m = Machine()
        self.addCleanup(m.close)
        self.assertEqual(self.run_tool("pre", "suspend", root=m.root).returncode, 0)
        self.assertTrue((m.root / g.MARK).exists())
        self.assertEqual(self.run_tool("post", "suspend", root=m.root).returncode, 0)
        self.assertFalse((m.root / g.MARK).exists())
        res = self.run_tool("status", root=m.root)
        self.assertEqual(json.loads(res.stdout)["status"], "ok")

    def test_hook_never_fails(self):
        m = Machine()
        self.addCleanup(m.close)
        (m.root / "var").write_text("not a folder")      # nowhere to write
        res = self.run_tool("pre", "suspend", root=m.root)
        self.assertEqual(res.returncode, 0)


class Shipped(unittest.TestCase):
    def test_list_names_the_latitude_5490(self):
        m = Machine()
        self.addCleanup(m.close)
        self.assertTrue(g.known_bad(m.root, "Dell Inc.", "Latitude 5490"))

    def test_units(self):
        boot = (HERE.parent / "raye-sleep-guard.service").read_text()
        self.assertIn("Before=display-manager.service", boot)
        self.assertIn("ExecStart=/usr/libexec/raye-sleep-guard boot", boot)
        user = (HERE.parent / "raye-sleep-notice.service").read_text()
        self.assertIn("ConditionPathExists=/var/lib/raye/sleep-guard/state.json", user)
        self.assertIn("raye-sleep-guard notice", user)
        policy = (HERE.parent / "org.raye.sleep-guard.policy").read_text()
        self.assertIn("/usr/libexec/raye-sleep-guard", policy)

    def test_no_tpm_hook_comes_back(self):
        # 2026-11-19: letting the TPM go did not make the Latitude wake; the
        # cause is the Intel graphics driver. Nothing of it may return.
        tuning = HERE.parent.parent / "tuning"
        self.assertFalse((tuning / "raye-tpm-sleep").exists())


if __name__ == "__main__":
    unittest.main()
