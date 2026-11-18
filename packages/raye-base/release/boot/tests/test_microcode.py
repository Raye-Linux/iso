# SPDX-License-Identifier: GPL-3.0-or-later
"""Intel microcode in the initramfs: this PC's processor only, except on
the install USB, which starts on any PC."""
import pathlib
import re
import subprocess

BOOT = pathlib.Path(__file__).resolve().parent.parent
CONF = BOOT / "intel-microcode"
PATHS = BOOT.parent.parent / "debian" / "raye-release-paths"


def hook_settings(root):
    # what the intel_microcode hook has once it read its config: its own
    # defaults for MODULES=most first, then the file
    script = ('IUCODE_TOOL_INITRAMFS=early; IUCODE_TOOL_SCANCPUS=no; . "$1"; '
              'printf "%s %s" "$IUCODE_TOOL_INITRAMFS" "$IUCODE_TOOL_SCANCPUS"')
    out = subprocess.run(["sh", "-c", script, "sh", str(CONF)], capture_output=True, text=True,
                         check=True, env={"PATH": "/usr/bin:/bin", "RAYE_MICROCODE_ROOT": str(root)})
    return out.stdout


def test_installed_system_keeps_its_own_processor_only(tmp_path):
    assert hook_settings(tmp_path) == "auto yes"


def test_install_usb_keeps_every_model(tmp_path):
    (tmp_path / "usr/share/initramfs-tools/scripts").mkdir(parents=True)
    (tmp_path / "usr/share/initramfs-tools/scripts/casper").write_text("")
    assert hook_settings(tmp_path) == "early no"


def test_it_takes_the_place_of_the_stock_file():
    assert re.search(r"^raye-system\s+release/boot/intel-microcode\s+etc/default/intel-microcode\s+divert\s*$",
                     PATHS.read_text(), re.M)
