# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-boot-ok.service: no boot menu after an offline update restart."""
import configparser
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
UNIT = HERE.parent / "raye-boot-ok.service"
PATHS = HERE.parent.parent.parent / "debian" / "raye-release-paths"


def unit():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(UNIT.read_text())
    return cp


def test_runs_in_the_offline_update_start():
    u = unit()
    assert u["Install"]["WantedBy"] == "system-update.target"
    assert "system-update.target" in u["Unit"]["Before"].split()
    assert "raye-update-install.service" in u["Unit"]["Before"].split()
    assert u["Unit"]["ConditionPathIsSymbolicLink"] == "/system-update"


def test_clears_recordfail_once_boot_is_mounted():
    u = unit()
    lines = [l.split("=", 1)[1] for l in UNIT.read_text().splitlines() if l.startswith("ExecStart=")]
    assert "/usr/bin/grub-editenv /boot/grub/grubenv unset recordfail" in lines
    # an update start is not a failed graphics start (09_raye_graphics)
    assert "/usr/bin/grub-editenv /boot/grub/grubenv set raye_gfx_fails=0" in lines
    assert "local-fs.target" in u["Unit"]["After"].split()
    assert u["Unit"]["DefaultDependencies"] == "no"


def test_shipped_enabled_not_started():
    lines = [l.split() for l in PATHS.read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    assert ["raye-system", "release/grub/raye-boot-ok.service",
            "usr/lib/systemd/system/raye-boot-ok.service", "no-start"] in lines
