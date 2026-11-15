# SPDX-License-Identifier: GPL-3.0-or-later
"""No kernel text on the screen while the computer starts or stops.

A person who restarts to install updates must see the Raye screen from
the moment the desktop goes away to the moment it comes back. "quiet"
alone does not give that: it still lets errors through, and a bad USB
cable then fills the screen with "Cannot enable. Maybe the USB cable is
bad?" during the shutdown. These checks read what the package ships:
the kernel command line of the installed system (etc/default/grub.d)
and the console level that sysctl sets once the system runs.
"""
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
TOP = HERE.parent.parent.parent
CFG = HERE.parent / "50-raye.cfg"
SYSCTL = TOP / "release" / "tuning" / "90-raye.conf"
PATHS = TOP / "debian" / "raye-release-paths"


def cmdline():
    """The words of GRUB_CMDLINE_LINUX_DEFAULT, read the way grub reads it."""
    out = subprocess.run(
        ["sh", "-c", '. "$1"; printf %s "$GRUB_CMDLINE_LINUX_DEFAULT"',
         "sh", str(CFG)], capture_output=True, text=True, check=True)
    return out.stdout.split()


def test_the_file_reaches_the_installed_system():
    lines = [l.split() for l in PATHS.read_text().splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert ["raye-system", "release/grub/50-raye.cfg",
            "etc/default/grub.d/50-raye.cfg"] in [l[:3] for l in lines]


def test_quiet_and_the_raye_screen():
    words = cmdline()
    assert "quiet" in words
    assert "splash" in words


def test_errors_stay_off_the_screen():
    words = cmdline()
    assert "loglevel=3" in words
    assert "rd.udev.log_level=3" in words
    assert "udev.log_level=3" in words
    # "false" also hides "[FAILED] Failed to mount ...", the one line that
    # says why the computer stopped at the emergency screen
    assert "systemd.show_status=error" in words
    assert "systemd.show_status=false" not in words
    assert "vt.global_cursor_default=0" in words


def test_panic_restart_is_kept():
    assert "panic=30" in cmdline()


def test_nothing_turns_the_raye_screen_off():
    # plymouth-poweroff/reboot/halt.service run only with "splash" and
    # without these: one of them and shutdown is plain text again
    for word in cmdline():
        assert word not in ("nosplash", "plymouth.enable=0", "debug")
        assert not word.startswith("loglevel=") or word == "loglevel=3"


def test_each_word_once():
    words = cmdline()
    assert len(words) == len(set(words))


def test_console_level_after_start():
    # sysctl runs after the kernel took loglevel=3; the base system's
    # 55-console-messages.conf puts 4 back, so 90-raye.conf (read later)
    # must set it again. 4 lets errors (level 3) reach the console.
    values = {}
    for line in SYSCTL.read_text().splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        key, value = line.lstrip("-").split("=", 1)
        values[key.strip()] = value.split()
    level = values.get("kernel.printk")
    assert level, "kernel.printk is not set in 90-raye.conf"
    assert len(level) == 4
    assert int(level[0]) <= 3
    assert int(level[3]) <= 3


POSTINST = TOP / "debian" / "raye-system.postinst"


def grub_block(tmp_path):
    """The update-grub part of raye-system.postinst, pointed at tmp_path."""
    lines = POSTINST.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "50-raye.cfg (no text on screen)" in l)
    end = next(i for i in range(start, len(lines)) if lines[i] == "    fi")
    text = "\n".join(lines[start:end + 1])
    for path in ("/boot/grub/grub.cfg", "/usr/sbin/update-grub"):
        text = text.replace(path, str(tmp_path) + path)
    text = text.replace("update-grub;", str(tmp_path) + "/usr/sbin/update-grub;")
    return 'DPKG_ROOT=""\n' + text.replace('"$DPKG_ROOT/', '"' + str(tmp_path) + "/")


def grub_system(tmp_path, cfg):
    (tmp_path / "boot/grub").mkdir(parents=True)
    (tmp_path / "boot/grub/grub.cfg").write_text("menu\n")
    (tmp_path / "usr/sbin").mkdir(parents=True)
    ug = tmp_path / "usr/sbin/update-grub"
    ug.write_text(f'#!/bin/sh\necho run >> "{tmp_path}/runs"\n')
    ug.chmod(0o755)
    (tmp_path / "etc/default/grub.d").mkdir(parents=True)
    (tmp_path / "etc/default/grub.d/50-raye.cfg").write_text(cfg)


def runs(tmp_path):
    p = tmp_path / "runs"
    return len(p.read_text().splitlines()) if p.exists() else 0


def test_new_command_line_reaches_the_menu(tmp_path):
    grub_system(tmp_path, CFG.read_text())
    block = grub_block(tmp_path)
    subprocess.run(["sh", "-e", "-c", block], check=True)
    assert runs(tmp_path) == 1
    # same file at the next upgrade: the menu is left alone
    subprocess.run(["sh", "-e", "-c", block], check=True)
    assert runs(tmp_path) == 1
    (tmp_path / "etc/default/grub.d/50-raye.cfg").write_text(CFG.read_text() + "# changed\n")
    subprocess.run(["sh", "-e", "-c", block], check=True)
    assert runs(tmp_path) == 2
    # a new boot picture script too
    (tmp_path / "etc/grub.d").mkdir()
    (tmp_path / "etc/grub.d/05_raye_boot_picture").write_text("#!/bin/sh\n")
    subprocess.run(["sh", "-e", "-c", block], check=True)
    assert runs(tmp_path) == 3


def test_failed_update_grub_tries_again_next_time(tmp_path):
    grub_system(tmp_path, CFG.read_text())
    (tmp_path / "usr/sbin/update-grub").write_text(
        f'#!/bin/sh\necho run >> "{tmp_path}/runs"\nexit 1\n')
    block = grub_block(tmp_path)
    subprocess.run(["sh", "-e", "-c", block], check=True)
    subprocess.run(["sh", "-e", "-c", block], check=True)
    assert runs(tmp_path) == 2


def test_image_build_without_a_menu(tmp_path):
    grub_system(tmp_path, CFG.read_text())
    (tmp_path / "boot/grub/grub.cfg").unlink()
    subprocess.run(["sh", "-e", "-c", grub_block(tmp_path)], check=True)
    assert runs(tmp_path) == 0
