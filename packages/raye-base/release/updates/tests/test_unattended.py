# SPDX-License-Identifier: GPL-3.0-or-later
"""unattended-upgrades leaves the packages Raye Update keeps for a restart."""
import ast
import glob
import os
import pathlib
import re
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
CONF = HERE.parent / "52raye-unattended-upgrades"
# raye-update's source, when the whole tree is checked out next to iso
UPDATE = HERE.parents[5] / "update" / "src" / "raye_update.py"
LISTS = os.environ.get("RAYE_APT_LISTS", "/var/lib/apt/lists")

HELD = ["libc6", "libc6-i386", "locales", "libnss-systemd", "libnss-resolve",
        "libkirigami6", "libquickcharts1", "kwallet6", "libkfontinst6", "libc-bin", "systemd", "libsystemd0", "udev",
        "dbus", "libqt6core6t64", "qt6-base-private-dev", "libkf6coreaddons6",
        "plasma-workspace", "plasma-desktop", "libplasma6", "kwin-wayland",
        "sddm", "mesa-libgallium", "libgbm1", "libdrm2", "xwayland",
        "linux-image-7.0.14-raye", "linux-modules-7.0.14-raye", "shim-signed",
        "grub-efi-amd64-signed", "nvidia-driver-580", "raye-theme"]
FREE = ["firefox", "libssl3t64", "openssl", "curl", "sudo", "libnss3",
        "tzdata", "openssh-client", "libsystemd-dev-tools", "raye-theme-extra",
        "linux-tools-common", "breeze-icon-theme"]


def blacklist():
    if not shutil.which("apt-config"):
        pytest.skip("apt-config is not installed")
    out = subprocess.run(
        ["apt-config", "-c", str(CONF), "dump", "--format", "%v%n",
         "Unattended-Upgrade::Package-Blacklist"],
        capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def held(name, patterns):
    # what unattended-upgrade's is_pkgname_in_blacklist does
    return any(re.match(p, name) for p in patterns)


def test_desktop_and_boot_packages_are_left_to_raye_update():
    patterns = blacklist()
    assert [n for n in HELD if not held(n, patterns)] == []


def test_ordinary_security_fixes_still_go_in():
    patterns = blacklist()
    assert [n for n in FREE if held(n, patterns)] == []


def test_security_origin_still_allowed():
    text = CONF.read_text()
    assert '"origin=Ubuntu,archive=resolute-security,label=Ubuntu";' in text
    assert 'Unattended-Upgrade::Automatic-Reboot "false";' in text


def assignment(name):
    for node in ast.parse(UPDATE.read_text()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == name):
            return ast.literal_eval(node.value.args[0])
    raise AssertionError(f"no {name} in raye_update.py")


def offline_alternatives():
    pattern = assignment("OFFLINE_PACKAGES")
    assert pattern.startswith("^(") and pattern.endswith(")")
    body, parts, depth, cur = pattern[2:-1], [], 0, ""
    for ch in body:
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    parts.append(cur)
    return parts


def test_same_names_as_raye_update():
    if not UPDATE.exists():
        pytest.skip("raye-update's source is not next to this tree")
    alternatives = offline_alternatives()
    assert blacklist()[:len(alternatives)] == alternatives


def indexes():
    found = {}
    for path in glob.glob(os.path.join(LISTS, "*_dists_resolute*_binary-*_Packages")):
        name = None
        for line in open(path, encoding="utf-8", errors="replace"):
            if line.startswith("Package: "):
                name = source = line[9:].strip()
            elif line.startswith("Source: ") and name:
                source = line[8:].split()[0]
            elif not line.strip() and name:
                found[name] = source
                name = None
        if name:
            found[name] = source
    return found


def test_every_binary_of_a_held_source_is_held():
    if not UPDATE.exists():
        pytest.skip("raye-update's source is not next to this tree")
    found = indexes()
    if not found:
        pytest.skip(f"no resolute Packages index in {LISTS}")
    sources = re.compile(assignment("OFFLINE_SOURCES"))
    patterns = blacklist()
    missed = sorted(n for n, s in found.items() if sources.match(s) and not held(n, patterns))
    assert missed == [], "run tools/unattended-held"
