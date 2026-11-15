# SPDX-License-Identifier: GPL-3.0-or-later
"""05_raye_boot_picture: the night background from the moment GRUB starts."""
import os
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "05_raye_boot_picture"
PATHS = HERE.parent.parent.parent / "debian" / "raye-release-paths"


def run(tmp_path, picture=True):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "grub-mkconfig_lib").write_text(
        'prepare_grub_to_access_device() { echo "search --set=root $1"; }\n'
        'make_system_path_relative_to_its_root() { echo "/grub/${1##*/}"; }\n')
    probe = tmp_path / "grub-probe"
    probe.write_text("#!/bin/sh\necho /dev/vda2\n")
    probe.chmod(0o755)
    src = tmp_path / "background.png"
    if picture:
        src.write_bytes(b"\x89PNG night")
    dest = tmp_path / "boot" / "raye-boot.png"
    dest.parent.mkdir()
    env = dict(os.environ, pkgdatadir=str(lib), grub_probe=str(probe),
               RAYE_BOOT_PICTURE=str(src), RAYE_BOOT_PICTURE_DEST=str(dest))
    r = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    return r, dest


def test_picture_drawn_before_anything_else(tmp_path):
    r, dest = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert dest.read_bytes() == b"\x89PNG night"
    lines = r.stdout.splitlines()
    assert lines[0] == "search --set=root /dev/vda2"
    # without "clear" GRUB keeps its black screen until it prints something
    assert lines[1:] == ['if background_image -m stretch "/grub/raye-boot.png"; then',
                         "  clear", "fi"]


def test_no_boot_screen_installed(tmp_path):
    r, dest = run(tmp_path, picture=False)
    assert r.returncode == 0
    assert r.stdout == ""
    assert not dest.exists()


def test_executable_and_shipped():
    assert os.access(SCRIPT, os.X_OK)
    lines = [l.split() for l in PATHS.read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    assert ["raye-system", "release/grub/05_raye_boot_picture",
            "etc/grub.d/05_raye_boot_picture"] in [l[:3] for l in lines]
