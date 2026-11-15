# SPDX-License-Identifier: GPL-3.0-or-later
"""Ubuntu's mirror lists and the move of older machines onto them."""
import os
import pathlib
import subprocess

TOP = pathlib.Path(__file__).resolve().parents[3]
APT = TOP / "release/apt"
SCRIPT = APT / "raye-ubuntu-mirrors"

STOCK = """\
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: resolute resolute-updates resolute-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: resolute-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

# the source packages
Types: deb-src
URIs: http://archive.ubuntu.com/ubuntu/
Suites: resolute resolute-updates resolute-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
Enabled: no
"""


def mirror_lines(path):
    out = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        uri, _, meta = line.partition("\t")
        out.append((uri, meta.split()))
    return out


def uris(text):
    return [l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("URIs:")]


def run(root):
    env = dict(os.environ, DPKG_ROOT=str(root))
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)


def machine(tmp_path, text=STOCK):
    src = tmp_path / "etc/apt/sources.list.d/ubuntu.sources"
    src.parent.mkdir(parents=True)
    src.write_text(text)
    src.chmod(0o644)
    return src


def test_archive_list_starts_with_archive_ubuntu_com():
    lines = mirror_lines(APT / "ubuntu-mirrors.list")
    assert lines[0][0] == "http://archive.ubuntu.com/ubuntu/"
    assert len(lines) >= 3


def test_security_list_starts_with_security_ubuntu_com():
    lines = mirror_lines(APT / "ubuntu-security-mirrors.list")
    assert lines[0][0] == "http://security.ubuntu.com/ubuntu/"
    assert len(lines) >= 3


def test_lists_are_ordered_and_hosts_differ():
    for name in ("ubuntu-mirrors.list", "ubuntu-security-mirrors.list"):
        lines = mirror_lines(APT / name)
        # without a priority apt picks one at random
        assert [m for _, m in lines] == [["priority:%d" % i] for i in range(1, len(lines) + 1)]
        hosts = [u.split("/")[2] for u, _ in lines]
        assert len(set(hosts)) == len(hosts)
        for u, _ in lines:
            assert u.endswith(".ubuntu.com/ubuntu/")


def test_stock_sources_move_to_the_lists(tmp_path):
    src = machine(tmp_path)
    assert run(tmp_path).returncode == 0
    text = src.read_text()
    assert uris(text) == ["mirror+file:/etc/apt/mirrors/ubuntu.list",
                          "mirror+file:/etc/apt/mirrors/ubuntu-security.list",
                          "mirror+file:/etc/apt/mirrors/ubuntu.list"]
    assert "# the source packages" in text
    assert "Enabled: no" in text
    assert oct(src.stat().st_mode & 0o777) == "0o644"
    keep = tmp_path / "var/lib/raye-system/ubuntu.sources.before-mirrors"
    assert keep.read_text() == STOCK
    assert not list(src.parent.glob("*.dpkg-tmp"))


def test_second_run_changes_nothing(tmp_path):
    src = machine(tmp_path)
    run(tmp_path)
    first = src.read_text()
    keep = tmp_path / "var/lib/raye-system/ubuntu.sources.before-mirrors"
    keep.write_text("left alone\n")
    assert run(tmp_path).returncode == 0
    assert src.read_text() == first
    assert keep.read_text() == "left alone\n"


def test_server_picked_by_the_owner_stays(tmp_path):
    mine = STOCK.replace("http://archive.ubuntu.com/ubuntu/", "http://fr.archive.ubuntu.com/ubuntu/") \
                .replace("URIs: http://archive.ubuntu.com/ubuntu\n", "URIs: http://fr.archive.ubuntu.com/ubuntu\n")
    src = machine(tmp_path, mine)
    assert run(tmp_path).returncode == 0
    assert uris(src.read_text()) == ["http://fr.archive.ubuntu.com/ubuntu",
                                     "mirror+file:/etc/apt/mirrors/ubuntu-security.list",
                                     "http://fr.archive.ubuntu.com/ubuntu/"]


def test_nothing_to_do_leaves_no_backup(tmp_path):
    custom = STOCK.replace("archive.ubuntu.com", "mirror.example.org") \
                  .replace("security.ubuntu.com", "mirror.example.org")
    src = machine(tmp_path, custom)
    assert run(tmp_path).returncode == 0
    assert src.read_text() == custom
    assert not (tmp_path / "var/lib/raye-system").exists()


def test_no_sources_file_is_fine(tmp_path):
    assert run(tmp_path).returncode == 0
    assert not (tmp_path / "etc").exists()


def test_raye_system_ships_lists_and_script():
    paths = (TOP / "debian/raye-release-paths").read_text().split("\n")
    want = {
        "release/apt/ubuntu-mirrors.list": "etc/apt/mirrors/ubuntu.list",
        "release/apt/ubuntu-security-mirrors.list": "etc/apt/mirrors/ubuntu-security.list",
        "release/apt/raye-ubuntu-mirrors": "usr/libexec/raye-ubuntu-mirrors",
    }
    found = {}
    for line in paths:
        f = line.split()
        if len(f) >= 3 and f[1] in want:
            found[f[1]] = (f[0], f[2])
    assert found == {k: ("raye-system", v) for k, v in want.items()}
    postinst = (TOP / "debian/raye-system.postinst").read_text()
    assert '"$DPKG_ROOT/usr/libexec/raye-ubuntu-mirrors"' in postinst
