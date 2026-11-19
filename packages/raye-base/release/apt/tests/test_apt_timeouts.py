"""apt gives up on a silent server after 15 s and moves to the next mirror.

Measured on 2026-11-19 in the test VM: archive.ubuntu.com stopped answering
in the middle of an update, apt waited out its default timeout three times,
and "Checking for updates" took 6 min 31 s. With 15 s it took 62 s, all the
indexes downloaded again from scratch.
"""
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
CONF = HERE.parent / "raye-timeouts.conf"
PATHS = HERE.parents[2] / "debian" / "raye-release-paths"


def settings():
    out = {}
    for m in re.finditer(r'^\s*(Acquire::[\w:]+)\s+"([^"]*)";', CONF.read_text(), re.M):
        out[m.group(1)] = m.group(2)
    return out


def test_silent_servers_are_left_after_15_seconds():
    s = settings()
    assert s.get("Acquire::http::Timeout") == "15"
    assert s.get("Acquire::https::Timeout") == "15"


def test_the_file_is_installed_where_apt_reads_it():
    lines = [l.split() for l in PATHS.read_text().splitlines() if "raye-timeouts.conf" in l]
    assert lines, "raye-timeouts.conf is not installed by any package"
    assert lines[0][2].startswith("etc/apt/apt.conf.d/")


def test_apt_accepts_the_file():
    try:
        out = subprocess.run(["apt-config", "-c", str(CONF), "dump"], capture_output=True,
                             text=True, timeout=30)
    except FileNotFoundError:
        import pytest
        pytest.skip("apt-config is not installed here")
    assert out.returncode == 0, out.stderr
    assert 'Acquire::http::Timeout "15";' in out.stdout
