# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-pins.pref keeps Raye's Plasma builds over Ubuntu's updates."""
import pathlib
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
PINS = HERE.parent / "raye-pins.pref"
PUBLISH = HERE.parents[4] / "tools" / "publish-repo"

RAYE = "4:6.6.6-0ubuntu0.1+raye4"
SRU = "4:6.6.6-0ubuntu0.2"
# the binaries of plasma-workspace and plasma-desktop that Raye rebuilds
PLASMA = {"plasma-workspace", "plasma-workspace-data", "plasma-workspace-dev",
          "plasma-session-wayland", "plasma-session-x11", "libbatterycontrol6",
          "libkfontinst6", "libkfontinstui6", "libklipper6", "libklookandfeel6",
          "libkmpris6", "libkworkspace6-6", "libnotificationmanager1",
          "libtaskmanager6", "plasma-desktop", "plasma-desktop-data",
          "plasma-desktop-dev", "sddm-theme-breeze"}


def stanzas():
    out, cur = [], {}
    for line in PINS.read_text().splitlines() + [""]:
        if line.startswith("#"):
            continue
        if not line.strip():
            if cur:
                out.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(":")
        cur[key.strip()] = value.strip()
    return out


def raye_stanza():
    found = [s for s in stanzas() if s.get("Pin") == "release o=Raye"]
    assert len(found) == 1
    return found[0]


def test_every_rebuilt_plasma_package_is_pinned():
    stanza = raye_stanza()
    assert PLASMA <= set(stanza["Package"].split())
    assert "raye-wine" in stanza["Package"].split()
    assert int(stanza["Pin-Priority"]) > 1000


def test_pin_names_the_origin_the_repo_publishes():
    if not PUBLISH.exists():
        pytest.skip("tools/publish-repo is not next to this package")
    assert "Origin: Raye" in PUBLISH.read_text()


def repo(path, origin, suite, packages):
    path.mkdir()
    (path / "Packages").write_text("".join(
        f"Package: {name}\nVersion: {version}\nArchitecture: all\n"
        f"Filename: ./{name}.deb\nSize: 1\nDescription: x\n\n"
        for name, version in packages))
    (path / "Release").write_text(
        f"Origin: {origin}\nLabel: {origin}\nSuite: {suite}\nCodename: resolute\n")


def candidates(tmp_path, installed):
    if not shutil.which("apt-cache"):
        pytest.skip("apt is not installed")
    for d in ("state/lists/partial", "cache/archives/partial", "etc"):
        (tmp_path / d).mkdir(parents=True)
    repo(tmp_path / "raye", "Raye", "resolute",
         [("plasma-workspace", RAYE), ("plasma-desktop", RAYE), ("raye-wine", "11.0+raye1")])
    repo(tmp_path / "ubuntu", "Ubuntu", "resolute-updates",
         [("plasma-workspace", SRU), ("plasma-desktop", SRU), ("kwin-wayland", "4:6.6.7-0ubuntu0.1")])
    (tmp_path / "etc/sources.list").write_text(
        f"deb [trusted=yes] file:{tmp_path}/raye ./\n"
        f"deb [trusted=yes] file:{tmp_path}/ubuntu ./\n")
    (tmp_path / "status").write_text("".join(
        f"Package: {name}\nStatus: install ok installed\nVersion: {version}\n"
        f"Architecture: all\nDescription: x\n\n" for name, version in installed))
    opts = ["-o", f"Dir::State={tmp_path}/state", "-o", f"Dir::State::status={tmp_path}/status",
            "-o", f"Dir::Cache={tmp_path}/cache", "-o", f"Dir::Etc::SourceList={tmp_path}/etc/sources.list",
            "-o", "Dir::Etc::SourceParts=/nonexistent", "-o", f"Dir::Etc::Preferences={PINS}",
            "-o", "Dir::Etc::PreferencesParts=/nonexistent", "-o", "APT::Architecture=amd64",
            "-o", "Debug::NoLocking=1"]
    subprocess.run(["apt-get", "-q", *opts, "update"], check=True, capture_output=True)
    out = subprocess.run(["apt-cache", *opts, "policy", "plasma-workspace", "plasma-desktop", "kwin-wayland"],
                         check=True, capture_output=True, text=True).stdout
    result, name = {}, None
    for line in out.splitlines():
        if not line.startswith(" "):
            name = line.rstrip(":")
        elif line.strip().startswith("Candidate:"):
            result[name] = line.split(":", 1)[1].strip()
    return result


def test_ubuntu_update_does_not_replace_raye_plasma(tmp_path):
    got = candidates(tmp_path, [("plasma-workspace", RAYE), ("plasma-desktop", RAYE),
                                ("kwin-wayland", "4:6.6.6-0ubuntu0.1")])
    assert got["plasma-workspace"] == RAYE
    assert got["plasma-desktop"] == RAYE
    # anything Raye does not rebuild still takes Ubuntu's update
    assert got["kwin-wayland"] == "4:6.6.7-0ubuntu0.1"


def test_a_desktop_already_on_ubuntus_build_comes_back(tmp_path):
    got = candidates(tmp_path, [("plasma-workspace", SRU), ("plasma-desktop", SRU)])
    assert got["plasma-workspace"] == RAYE
