# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-energy-saver on a fake machine and a fake power daemon: on when the
charger comes out, back when it goes in, at a battery level, never against
the person, and the screen a little dimmer only while it is on.

    python3 -B -m unittest discover -s release/power/tests
"""
import importlib.machinery
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE.parent / "raye-energy-saver"
UNIT = HERE.parent / "raye-energy-saver.service"


def load():
    loader = importlib.machinery.SourceFileLoader("raye_energy_saver", str(TOOL))
    spec = importlib.util.spec_from_loader("raye_energy_saver", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


es = load()


KEEP = []


def tearDownModule():
    for tmp in KEEP:
        tmp.cleanup()


class Laptop:
    def __init__(self, on_battery=True, level=80, profile="balanced", turn_on_at=None, dims=None, brightness=(400, 400)):
        self.tmp = tempfile.TemporaryDirectory()
        KEEP.append(self.tmp)
        self.root = pathlib.Path(self.tmp.name)
        self.home = self.root / "config"
        self.home.mkdir()
        es.ROOT = str(self.root)
        self.profile = profile
        self.calls = []
        self.put("sys/class/power_supply/BAT0/type", "Battery")
        self.put("sys/class/power_supply/AC/type", "Mains")
        self.put("sys/class/backlight/intel_backlight/brightness", str(brightness[0]))
        self.put("sys/class/backlight/intel_backlight/max_brightness", str(brightness[1]))
        self.power(on_battery, level)
        self.configure(turn_on_at, dims)
        self.saver = es.Saver(self.run)

    def put(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n")

    def power(self, on_battery, level=None):
        self.put("sys/class/power_supply/AC/online", "0" if on_battery else "1")
        self.put("sys/class/power_supply/BAT0/status", "Discharging" if on_battery else "Charging")
        if level is not None:
            self.put("sys/class/power_supply/BAT0/capacity", str(level))

    def configure(self, turn_on_at=None, dims=None):
        lines = ["[EnergySaver]"]
        if turn_on_at is not None:
            lines.append(f"TurnOnAt={turn_on_at}")
        if dims is not None:
            lines.append(f"LowerBrightness={'true' if dims else 'false'}")
        (self.home / "raye-settingsrc").write_text("\n".join(lines) + "\n")

    def brightness(self):
        return int((self.root / "sys/class/backlight/intel_backlight/brightness").read_text())

    def run(self, command, **kwargs):
        self.calls.append(command)
        if command[:2] == ["powerprofilesctl", "get"]:
            return subprocess.CompletedProcess(command, 0, self.profile + "\n", "")
        if command[:2] == ["powerprofilesctl", "set"]:
            self.profile = command[2]
        if command[0] == "busctl":
            self.put("sys/class/backlight/intel_backlight/brightness", command[-1])
        return subprocess.CompletedProcess(command, 0, "", "")

    def step(self):
        return self.saver.step(str(self.home))


class EnergySaver(unittest.TestCase):
    def test_unplugging_turns_it_on_and_plugging_in_gives_the_mode_back(self):
        pc = Laptop(on_battery=False, profile="balanced")
        self.assertEqual(pc.step(), "charger")
        self.assertEqual(pc.profile, "balanced")
        pc.power(True, 80)
        self.assertEqual(pc.step(), "saver on")
        self.assertEqual(pc.profile, "power-saver")
        pc.step()
        self.assertEqual(pc.profile, "power-saver")
        pc.power(False)
        pc.step()
        self.assertEqual(pc.profile, "balanced")

    def test_the_screen_is_a_little_dimmer_only_while_it_is_on(self):
        pc = Laptop(on_battery=True)
        pc.step()
        self.assertEqual(pc.brightness(), 240)
        pc.power(False)
        pc.step()
        self.assertEqual(pc.brightness(), 400)

    def test_dimming_can_be_switched_off(self):
        pc = Laptop(on_battery=True, dims=False)
        pc.step()
        self.assertEqual(pc.profile, "power-saver")
        self.assertEqual(pc.brightness(), 400)

    def test_a_screen_the_person_changed_is_not_put_back_over_them(self):
        pc = Laptop(on_battery=True)
        pc.step()
        pc.put("sys/class/backlight/intel_backlight/brightness", "100")
        pc.power(False)
        pc.step()
        self.assertEqual(pc.brightness(), 100)

    def test_it_does_not_fight_the_person(self):
        pc = Laptop(on_battery=True)
        pc.step()
        pc.profile = "balanced"  # the person turned Energy saver off
        for _ in range(3):
            pc.step()
        self.assertEqual(pc.profile, "balanced")
        # until the charger has gone in and out again
        pc.power(False)
        pc.step()
        pc.power(True, 70)
        pc.step()
        self.assertEqual(pc.profile, "power-saver")

    def test_best_performance_is_respected_unless_the_battery_is_low(self):
        pc = Laptop(on_battery=True, profile="performance")
        pc.step()
        self.assertEqual(pc.profile, "performance")
        low = Laptop(on_battery=True, profile="performance", turn_on_at=20, level=15)
        low.step()
        self.assertEqual(low.profile, "power-saver")

    def test_a_level_waits_for_the_battery_to_get_there(self):
        pc = Laptop(on_battery=True, turn_on_at=20, level=60)
        pc.step()
        self.assertEqual(pc.profile, "balanced")
        pc.power(True, 19)
        pc.step()
        self.assertEqual(pc.profile, "power-saver")

    def test_never_means_never(self):
        pc = Laptop(on_battery=True, turn_on_at=0, level=3)
        pc.step()
        self.assertEqual(pc.profile, "balanced")

    def test_turning_the_rule_off_gives_the_mode_back(self):
        pc = Laptop(on_battery=True)
        pc.step()
        pc.configure(turn_on_at=0)
        pc.step()
        self.assertEqual(pc.profile, "balanced")

    def test_energy_saver_the_person_turned_on_stays_theirs(self):
        pc = Laptop(on_battery=True, profile="power-saver")
        pc.step()
        pc.power(False)
        pc.step()
        self.assertEqual(pc.profile, "power-saver")

    def test_a_desktop_without_a_power_daemon_or_battery_is_left_alone(self):
        pc = Laptop(on_battery=True)
        for p in (pc.root / "sys/class/power_supply/BAT0/capacity",):
            p.unlink()
        self.assertEqual(pc.step(), "charger")
        self.assertEqual(pc.profile, "balanced")

    def test_the_unit_runs_only_on_a_laptop_and_in_the_session(self):
        text = UNIT.read_text()
        self.assertIn("ConditionPathExistsGlob=/sys/class/power_supply/BAT*", text)
        self.assertIn("WantedBy=graphical-session.target", text)
        self.assertIn("ExecStart=/usr/libexec/raye-energy-saver", text)


if __name__ == "__main__":
    unittest.main()
