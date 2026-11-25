# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-power-tune on fake machine trees: what it lets sleep on battery,
what it never touches, what it puts back on the charger, and that it
leaves alone what something else changed in between.

    python3 -B -m unittest discover -s release/power/tests
"""
import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE.parent / "raye-power-tune"
RULES = HERE.parent / "60-raye-power-source.rules"
SERVICE = HERE.parent / "raye-power-tune.service"


def load():
    loader = importlib.machinery.SourceFileLoader("raye_power_tune", str(TOOL))
    spec = importlib.util.spec_from_loader("raye_power_tune", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


tune = load()


KEEP = []


def tearDownModule():
    for tmp in KEEP:
        tmp.cleanup()


class Machine:
    """A fake root with a laptop's power supplies, PCI and USB devices."""

    def __init__(self, chassis="10", on_battery=True, battery=True):
        self.tmp = tempfile.TemporaryDirectory()
        KEEP.append(self.tmp)
        self.root = pathlib.Path(self.tmp.name)
        tune.ROOT = str(self.root)
        self.put("sys/class/dmi/id/chassis_type", chassis)
        if battery:
            self.put("sys/class/power_supply/BAT0/type", "Battery")
            self.put("sys/class/power_supply/BAT0/status", "Discharging" if on_battery else "Charging")
            self.put("sys/class/power_supply/AC/type", "Mains")
            self.put("sys/class/power_supply/AC/online", "0" if on_battery else "1")
        self.pci("0000:00:14.0", "0x020000")  # the network card
        self.pci("0000:00:02.0", "0x030000")  # graphics
        self.pci("0000:00:1f.3", "0x040300")  # audio
        self.pci("0000:00:14.1", "0x0c0330")  # a USB controller
        self.usb("1-5", "fixed", ["0e"])      # the camera, soldered in
        self.usb("1-6", "fixed", ["03"])      # a soldered keyboard
        self.usb("1-7", "removable", ["0e"])  # a camera someone plugged in
        self.usb("1-8", "fixed", ["e0"])      # Bluetooth
        self.put("sys/class/scsi_host/host0/link_power_management_policy", "max_performance")
        self.put("sys/class/net/wlan0/wireless/.keep", "")
        self.wifi = "off"
        self.iw_calls = []

    def put(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + ("\n" if text else ""))

    def get(self, name):
        return (self.root / name).read_text().strip()

    def pci(self, address, pci_class):
        self.put(f"sys/bus/pci/devices/{address}/class", pci_class)
        self.put(f"sys/bus/pci/devices/{address}/power/control", "on")

    def usb(self, name, removable, interface_classes):
        self.put(f"sys/bus/usb/devices/{name}/removable", removable)
        self.put(f"sys/bus/usb/devices/{name}/power/control", "on")
        for i, c in enumerate(interface_classes):
            self.put(f"sys/bus/usb/devices/{name}/{name}:1.{i}/bInterfaceClass", c)

    def plug(self, charger):
        self.put("sys/class/power_supply/AC/online", "1" if charger else "0")
        self.put("sys/class/power_supply/BAT0/status", "Charging" if charger else "Discharging")

    def run(self, command, **kwargs):
        """The iw stand-in."""
        self.iw_calls.append(command)
        if command[:2] == ["iw", "dev"] and command[3] == "get":
            return subprocess.CompletedProcess(command, 0, f"Power save: {self.wifi}\n", "")
        if command[3] == "set":
            self.wifi = command[5]
        return subprocess.CompletedProcess(command, 0, "", "")

    def apply(self):
        # the fake iw is always "installed"
        tune._have = lambda program: True
        return tune.apply(self.run)


class PowerTune(unittest.TestCase):
    def test_battery_rests_what_can_rest_and_only_that(self):
        m = Machine()
        self.assertEqual(m.apply(), "battery")
        self.assertEqual(m.get("sys/bus/pci/devices/0000:00:14.0/power/control"), "auto")
        self.assertEqual(m.get("sys/bus/usb/devices/1-5/power/control"), "auto")
        self.assertEqual(m.get("sys/class/scsi_host/host0/link_power_management_policy"), "med_power_with_dipm")
        self.assertEqual(m.wifi, "on")
        # never: graphics, audio, USB controllers, soldered keyboards,
        # Bluetooth, and whatever is plugged in
        for kept in ("pci/devices/0000:00:02.0", "pci/devices/0000:00:1f.3", "pci/devices/0000:00:14.1",
                     "usb/devices/1-6", "usb/devices/1-7", "usb/devices/1-8"):
            self.assertEqual(m.get(f"sys/bus/{kept}/power/control"), "on", kept)

    def test_charger_puts_back_exactly_what_it_changed(self):
        m = Machine()
        m.apply()
        m.plug(True)
        self.assertEqual(m.apply(), "charger")
        self.assertEqual(m.get("sys/bus/pci/devices/0000:00:14.0/power/control"), "on")
        self.assertEqual(m.get("sys/bus/usb/devices/1-5/power/control"), "on")
        self.assertEqual(m.get("sys/class/scsi_host/host0/link_power_management_policy"), "max_performance")
        self.assertEqual(m.wifi, "off")
        # and a second plug in does nothing more
        m.iw_calls.clear()
        m.apply()
        self.assertEqual([c for c in m.iw_calls if c[3] == "set"], [])

    def test_a_setting_changed_by_someone_else_is_left_alone(self):
        m = Machine()
        m.apply()
        m.put("sys/bus/pci/devices/0000:00:14.0/power/control", "on")  # the owner turned it back on
        m.put("sys/class/scsi_host/host0/link_power_management_policy", "min_power")
        m.plug(True)
        m.apply()
        self.assertEqual(m.get("sys/class/scsi_host/host0/link_power_management_policy"), "min_power")

    def test_wifi_already_saving_power_is_not_touched(self):
        m = Machine()
        m.wifi = "on"
        m.apply()
        m.plug(True)
        m.apply()
        self.assertEqual(m.wifi, "on")
        self.assertEqual([c for c in m.iw_calls if c[3] == "set"], [])

    def test_a_desktop_is_never_touched(self):
        m = Machine(chassis="3")
        self.assertEqual(m.apply(), "charger")
        self.assertEqual(m.get("sys/bus/pci/devices/0000:00:14.0/power/control"), "on")
        self.assertEqual(m.wifi, "off")

    def test_no_battery_means_the_charger(self):
        m = Machine(battery=False)
        self.assertEqual(m.apply(), "charger")
        self.assertEqual(m.get("sys/bus/pci/devices/0000:00:14.0/power/control"), "on")

    def test_the_off_switch_puts_everything_back(self):
        m = Machine()
        m.apply()
        m.put("etc/raye/power-tune.off", "")
        self.assertEqual(m.apply(), "charger")
        self.assertEqual(m.get("sys/bus/usb/devices/1-5/power/control"), "on")

    def test_applying_twice_on_battery_changes_nothing_more(self):
        m = Machine()
        m.apply()
        state = m.get("run/raye-power-tune/state.json")
        m.apply()
        self.assertEqual(m.get("run/raye-power-tune/state.json"), state)

    def test_a_refused_write_is_left_as_it_was(self):
        m = Machine()
        real = tune.write
        tune.write = lambda target, value: False
        try:
            m.apply()
        finally:
            tune.write = real
        self.assertEqual(m.get("sys/bus/pci/devices/0000:00:14.0/power/control"), "on")
        self.assertEqual(tune.load_state()["changed"], [m_ for m_ in tune.load_state()["changed"] if m_["kind"] == "wifi"])


class Files(unittest.TestCase):
    def test_the_rule_wakes_the_unit_on_the_charger_only(self):
        rule = [l for l in RULES.read_text().splitlines() if l and not l.startswith("#")]
        self.assertEqual(len(rule), 1)
        for want in ('SUBSYSTEM=="power_supply"', 'ATTR{type}=="Mains"', 'SYSTEMD_WANTS}+="raye-power-tune.service"'):
            self.assertIn(want, rule[0])
        verify = subprocess.run(["udevadm", "verify", "--help"], capture_output=True)
        if verify.returncode == 0:
            self.assertEqual(subprocess.run(["udevadm", "verify", str(RULES)], capture_output=True).returncode, 0)

    def test_the_unit_runs_only_on_a_laptop(self):
        text = SERVICE.read_text()
        self.assertIn("ConditionPathExistsGlob=/sys/class/power_supply/BAT*", text)
        self.assertIn("ExecStart=/usr/libexec/raye-power-tune apply", text)


if __name__ == "__main__":
    unittest.main()
