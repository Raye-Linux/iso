# SPDX-License-Identifier: GPL-3.0-or-later
"""11_raye_safe_graphics: a boot menu entry that starts Raye with nomodeset.

Some graphics cards leave the screen black once their driver takes over
(first report: an AMD RX 550). The install USB has a "Safe graphics" entry
for that; the installed system needs one too, and a menu that shows long
enough to pick it.

The script runs 10_linux again with nomodeset added and keeps its first
entry. Here 10_linux is a stand-in that prints what Ubuntu's prints, in
the same shape (a preamble with a closing brace of its own, the plain
entry, then the advanced ones in a submenu). Checked by hand on
2026-11-15 against the real 10_linux of the resolute build chroot and of
Debian 13: both gave one entry that grub-script-check accepts.
"""
import os
import pathlib
import shutil
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "11_raye_safe_graphics"
CFG = HERE.parent / "50-raye.cfg"
TOP = HERE.parent.parent.parent
PATHS = TOP / "debian" / "raye-release-paths"

UUID = "0b5e5ac3-6a0d-4b8e-9d55-8f1f1c2a7e10"

FAKE_10_LINUX = r'''#!/bin/sh
# what grub-mkconfig would print for one installed kernel
echo "linux: $GRUB_DISABLE_RECOVERY" > "$TRACE"
cat <<CFG
function gfxmode {
	set gfxpayload="\${1}"
}
set linux_gfx_mode=keep
export linux_gfx_mode
menuentry 'Raye Linux' --class raye --class gnu-linux --class gnu --class os \$menuentry_id_option 'gnulinux-simple-@ID@' {
	recordfail
	load_video
	gfxmode \$linux_gfx_mode
	insmod gzio
	if [ "\${initrdfail}" = 2 ]; then echo x; fi
	linux	/boot/vmlinuz-7.0.0-43-generic root=UUID=@ID@ ro $GRUB_CMDLINE_LINUX $GRUB_CMDLINE_LINUX_DEFAULT
	initrd	/boot/initrd.img-7.0.0-43-generic
}
submenu 'Advanced options for Raye Linux' \$menuentry_id_option 'gnulinux-advanced-@ID@' {
	menuentry 'Raye Linux, with Linux 7.0.0-43-generic' --class raye \$menuentry_id_option 'gnulinux-7.0.0-43-generic-advanced-@ID@' {
		linux	/boot/vmlinuz-7.0.0-43-generic root=UUID=@ID@ ro $GRUB_CMDLINE_LINUX_DEFAULT
	}
}
CFG
'''.replace("@ID@", UUID)


def run(tmp_path, cmdline="quiet splash", linux=FAKE_10_LINUX, stop=None):
    fake = tmp_path / "10_linux"
    if linux is not None:
        text = linux
        if stop:
            # 10_linux killed half way: everything from this text on is lost
            text = text[:text.index(stop)] + "\nCFG\n"
        fake.write_text(text)
        fake.chmod(0o755)
    env = dict(os.environ, RAYE_GRUB_LINUX=str(fake),
               GRUB_CMDLINE_LINUX_DEFAULT=cmdline, GRUB_CMDLINE_LINUX="",
               TRACE=str(tmp_path / "trace"))
    r = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def entries(out):
    return [l for l in out.splitlines() if l.lstrip().startswith(("menuentry ", "submenu "))]


def linux_words(out):
    line = next(l for l in out.splitlines() if l.strip().startswith("linux"))
    return line.split()


def test_one_entry_with_its_own_title_and_id(tmp_path):
    out = run(tmp_path)
    assert entries(out) == [
        "menuentry 'Raye Linux (safe graphics)' --class raye --class gnu-linux "
        "--class gnu --class os $menuentry_id_option "
        f"'raye-safe-graphics-{UUID}' {{"]
    # the id of the normal entry stays the normal entry's: the saved
    # default and recordfail hang off it
    assert "gnulinux-simple" not in out
    assert out.rstrip("\n").splitlines()[-1] == "}"


def test_the_kernel_starts_with_nomodeset_and_the_rest_of_the_line(tmp_path):
    words = linux_words(run(tmp_path, "quiet splash loglevel=3"))
    assert words[-3:] == ["splash", "loglevel=3", "nomodeset"]
    assert "quiet" in words and f"root=UUID={UUID}" in words


def test_nomodeset_only_once(tmp_path):
    # a system installed from the safe graphics entry of the USB already
    # has it on every entry (installer: raye-safe-graphics)
    words = linux_words(run(tmp_path, "quiet splash nomodeset"))
    assert words.count("nomodeset") == 1


def test_preamble_and_advanced_entries_are_left_out(tmp_path):
    out = run(tmp_path)
    assert "function gfxmode" not in out
    assert "Advanced options" not in out
    assert "linux_gfx_mode=keep" not in out


def test_no_recovery_entries_asked_for(tmp_path):
    run(tmp_path)
    assert (tmp_path / "trace").read_text().strip() == "linux: true"


def test_a_cut_short_entry_is_not_written(tmp_path):
    # without its closing brace the entry would swallow everything after
    # it in grub.cfg; better no safe entry than no boot menu
    out = run(tmp_path, stop="\tinitrd\t")
    assert out == ""


def test_nothing_when_10_linux_is_turned_off(tmp_path):
    assert run(tmp_path, linux=None) == ""


def test_the_entry_parses(tmp_path):
    check = shutil.which("grub-script-check")
    if not check:
        return  # the build chroot has no grub tools; the shape tests above hold
    path = tmp_path / "safe.cfg"
    path.write_text(run(tmp_path))
    subprocess.run([check, str(path)], check=True)


def test_shipped_and_executable():
    lines = [l.split() for l in PATHS.read_text().splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert ["raye-system", "release/grub/11_raye_safe_graphics",
            "etc/grub.d/11_raye_safe_graphics"] in [l[:3] for l in lines]
    # update-grub skips scripts that are not executable
    assert os.access(SCRIPT, os.X_OK)


def grub_setting(name):
    out = subprocess.run(["sh", "-c", f'. "$1"; printf %s "${name}"', "sh", str(CFG)],
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_the_menu_is_hidden_while_starts_go_well():
    # it shows by itself after a start that did not reach the desktop
    # (test_graphics_ladder), so nobody has to hold a key at the right moment
    assert grub_setting("GRUB_TIMEOUT_STYLE") == "hidden"
    assert grub_setting("GRUB_TIMEOUT") == "0"
    # a start that was cut off (power, crash) shows it too
    assert grub_setting("GRUB_RECORDFAIL_TIMEOUT") == "3"


def test_the_normal_entry_stays_without_nomodeset():
    assert "nomodeset" not in grub_setting("GRUB_CMDLINE_LINUX_DEFAULT").split()
