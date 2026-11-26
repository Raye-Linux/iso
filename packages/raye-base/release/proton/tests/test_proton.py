"""Raye Proton is its own package now (packages/raye-proton: GE-Proton
built by Raye, with Steam's bridge); raye-gaming brings it and no longer
ships the first Raye Proton, a launcher on raye-wine."""
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parents[3]


def gaming_stanza():
    control = (BASE / "debian/control").read_text()
    return re.search(r"^Package: raye-gaming\n(.*?)(?=^Package: )", control, re.S | re.M).group(1)


def test_raye_gaming_brings_raye_proton():
    depends = re.search(r"^Depends:(.*?)(?=^\S)", gaming_stanza(), re.S | re.M).group(1)
    assert re.search(r"(^|[\s,])raye-proton\s*,", depends)


def test_raye_gaming_no_longer_ships_the_launcher():
    paths = (BASE / "debian/raye-release-paths").read_text()
    lines = [l for l in paths.splitlines() if l.startswith("raye-gaming ")]
    assert not [l for l in lines if "compatibilitytools.d/raye-proton" in l or "raye-proton-setup" in l]
    assert not (BASE / "release/proton/proton").exists()


def test_raye_proton_takes_over_the_launcher_s_files():
    control = (BASE.parent / "raye-proton/debian/control").read_text()
    assert "Replaces: raye-gaming (<<" in control and "Breaks: raye-gaming (<<" in control
