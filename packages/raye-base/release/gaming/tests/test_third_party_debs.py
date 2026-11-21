# SPDX-License-Identifier: GPL-3.0-or-later
"""Raye's packages must not hold a hard dependency on a package that a
common app's own .deb takes the place of. Valve's Steam .deb
(steam-launcher) has Conflicts: steam-devices, steam-installer and
Provides/Replaces them: a plain "Depends: steam-devices" on raye-gaming
made the Steam .deb look like it could not be installed next to Raye."""
import pathlib
import re

CONTROL = pathlib.Path(__file__).resolve().parents[3] / "debian" / "control"

# what the official .debs of common apps conflict with and replace
TAKEN_BY_THIRD_PARTY = {
    "steam-devices": "steam-launcher",
    "steam-installer": "steam-launcher",
    "steam": "steam-launcher",
}


def stanzas():
    text = re.sub(r"^#.*\n", "", CONTROL.read_text(encoding="utf-8"), flags=re.M)
    for block in text.split("\n\n"):
        fields, key = {}, None
        for line in block.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += " " + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        if "Package" in fields:
            yield fields


def depends(fields):
    """Each Depends entry as the list of its alternatives (names only)."""
    out = []
    for entry in fields.get("Depends", "").split(","):
        names = [a.strip().split(" ")[0].split("(")[0] for a in entry.split("|") if a.strip()]
        if names:
            out.append(names)
    return out


def test_control_is_read():
    names = {f["Package"] for f in stanzas()}
    assert {"raye-gaming", "raye-desktop", "raye-system"} <= names


def test_no_hard_dependency_on_what_a_third_party_deb_replaces():
    for fields in stanzas():
        for alternatives in depends(fields):
            for name, replacer in TAKEN_BY_THIRD_PARTY.items():
                if name in alternatives:
                    assert replacer in alternatives, (
                        f"{fields['Package']} depends on {name} without '| {replacer}': "
                        f"{replacer}'s own .deb could not take its place")


def test_gaming_keeps_the_device_rules():
    gaming = next(f for f in stanzas() if f["Package"] == "raye-gaming")
    assert ["steam-devices", "steam-launcher"] in depends(gaming)
