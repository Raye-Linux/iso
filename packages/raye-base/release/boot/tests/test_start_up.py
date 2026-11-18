# SPDX-License-Identifier: GPL-3.0-or-later
"""What runs at every start: network waits, binfmt, initramfs, update screen."""
import configparser
import os
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
BOOT = HERE.parent
RELEASE = BOOT.parent
BOOT_TARGETS = {"sysinit.target", "basic.target", "multi-user.target", "graphical.target"}


def unit(path):
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read_string(path.read_text())
    return cp


def words(cp, section, key):
    return cp.get(section, key, fallback="").split() if cp.has_section(section) else []


def test_no_boot_unit_waits_for_the_network():
    slow = []
    for path in RELEASE.rglob("*.service"):
        if "tests" in path.parts:
            continue
        cp = unit(path)
        if not BOOT_TARGETS & set(words(cp, "Install", "WantedBy") + words(cp, "Install", "RequiredBy")):
            continue
        for key in ("Wants", "Requires", "After"):
            if "network-online.target" in words(cp, "Unit", key):
                slow.append(f"{path.relative_to(RELEASE)} {key}")
    assert slow == []


def test_drivers_still_wait_for_a_network_when_they_run():
    cp = unit(RELEASE / "drivers" / "raye-drivers.service")
    pre = cp.get("Service", "ExecStartPre")
    assert pre.startswith("-") and "nm-online" in pre
    assert "NetworkManager.service" in words(cp, "Unit", "After")


def binfmt_needed(tmp_path, files):
    for name in files:
        p = tmp_path / name.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(":x:M::ab::/bin/true:\n")
    env = dict(os.environ, RAYE_BINFMT_ROOT=str(tmp_path))
    return subprocess.run(["sh", str(BOOT / "raye-binfmt-needed")], env=env).returncode


def test_binfmt_skipped_with_python_alone(tmp_path):
    assert binfmt_needed(tmp_path, ["/usr/lib/binfmt.d/python3.14.conf"]) == 1


def test_binfmt_skipped_with_nothing(tmp_path):
    assert binfmt_needed(tmp_path, []) == 1


def test_binfmt_runs_for_other_formats(tmp_path):
    assert binfmt_needed(tmp_path, ["/usr/lib/binfmt.d/python3.14.conf",
                                    "/usr/lib/binfmt.d/qemu-aarch64.conf"]) == 0
    assert binfmt_needed(tmp_path / "b", ["/etc/binfmt.d/my-format.conf"]) == 0


def test_binfmt_dropin_calls_the_check():
    cp = unit(BOOT / "systemd-binfmt.service.d" / "raye.conf")
    assert cp.get("Service", "ExecCondition") == "/usr/libexec/raye-binfmt-needed"


def update_screen(tmp_path, target, ping=0):
    rootmnt = tmp_path / "root"
    rootmnt.mkdir()
    if target:
        (rootmnt / "system-update").symlink_to(target)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "log"
    (bin_ / "plymouth").write_text(
        f'#!/bin/sh\n[ "$1" = --ping ] && exit {ping}\necho "$*" >> "{log}"\n')
    (bin_ / "plymouth").chmod(0o755)
    env = dict(os.environ, rootmnt=str(rootmnt), PATH=f"{bin_}:{os.environ['PATH']}")
    r = subprocess.run(["sh", str(BOOT / "raye-update-screen")], env=env)
    assert r.returncode == 0
    return log.read_text().splitlines() if log.exists() else []


def test_update_screen_for_raye_updates(tmp_path):
    assert update_screen(tmp_path, "/var/lib/raye-update/offline") == [
        "display-message --text=raye:mode:updates", "system-update --progress=0"]


def test_update_screen_leaves_other_tools_alone(tmp_path):
    assert update_screen(tmp_path, "/var/lib/PackageKit/prepared-update") == []


def test_update_screen_on_a_normal_start(tmp_path):
    assert update_screen(tmp_path, None) == []


def test_update_screen_without_plymouth_running(tmp_path):
    assert update_screen(tmp_path, "/var/lib/raye-update/offline", ping=1) == []


def test_update_screen_is_in_init_bottom():
    paths = (RELEASE.parent / "debian" / "raye-release-paths").read_text()
    assert ("release/boot/raye-update-screen        "
            "usr/share/initramfs-tools/scripts/init-bottom/raye-update-screen") in paths


def test_gpu_manager_runs_only_where_a_driver_needs_it():
    # it holds the sign-in screen at every start; it only matters with
    # NVIDIA's driver or its graphics switching (PRIME) installed
    cp = unit(BOOT / "gpu-manager.service.d" / "raye.conf")
    raw = (BOOT / "gpu-manager.service.d" / "raye.conf").read_text()
    conds = [l.split("=", 1)[1] for l in raw.splitlines() if l.startswith("ConditionPathExists=")]
    assert sorted(conds) == ["|/usr/bin/nvidia-smi", "|/usr/bin/prime-select"]
    assert cp.has_section("Unit")
    paths = (RELEASE.parent / "debian" / "raye-release-paths").read_text()
    assert "release/boot/*.d/*.conf               usr/lib/systemd/system" in paths
