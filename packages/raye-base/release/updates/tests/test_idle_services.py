# SPDX-License-Identifier: GPL-3.0-or-later
"""The firmware daemon and the guard of background upgrades are not kept in
memory while there is nothing for them to do."""
import configparser
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
UPDATES = HERE.parent
PATHS = UPDATES.parents[1] / "debian" / "raye-release-paths"


def ini(path):
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str
    cfg.read_string(path.read_text())
    return cfg


def shipped(source):
    for line in PATHS.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == source:
            return parts[0], parts[2]
    return None


def test_fwupd_leaves_after_a_slow_start():
    conf = UPDATES / "fwupd.conf"
    cfg = ini(conf)
    # 0 turns the "start took too long, stay for good" rule off; the idle
    # timeout itself stays fwupd's own
    assert cfg["fwupd"]["IdleInhibitStartupThreshold"] == "0"
    assert "IdleTimeout" not in cfg["fwupd"]


def test_fwupd_conf_goes_where_fwupd_reads_its_second_file():
    # /etc/fwupd/fwupd.conf is fwupd's own conffile; /var/etc/fwupd is read after it
    assert shipped("release/updates/fwupd.conf") == ("raye-system", "var/etc/fwupd/fwupd.conf")


def test_upgrade_run_brings_the_shutdown_guard():
    drop = UPDATES / "apt-daily-upgrade.service.d" / "raye-shutdown-guard.conf"
    unit = ini(drop)["Unit"]
    assert unit["Wants"] == "unattended-upgrades.service"
    # the guard holds its shutdown lock before the first package is touched
    assert unit["After"] == "unattended-upgrades.service"
    assert shipped("release/updates/apt-daily-upgrade.service.d/raye-shutdown-guard.conf") == (
        "raye-system", "usr/lib/systemd/system/apt-daily-upgrade.service.d/raye-shutdown-guard.conf")


def test_shutdown_guard_stops_when_the_run_is_over():
    drop = UPDATES / "unattended-upgrades.service.d" / "raye-on-demand.conf"
    unit = ini(drop)["Unit"]
    assert unit["StopWhenUnneeded"] == "yes"
    assert shipped("release/updates/unattended-upgrades.service.d/raye-on-demand.conf") == (
        "raye-system", "usr/lib/systemd/system/unattended-upgrades.service.d/raye-on-demand.conf")
