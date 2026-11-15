# SPDX-License-Identifier: GPL-3.0-or-later
"""release/grub/raye-grub-titles: the boot menu in plain names.

os-prober writes what it finds with the partition it found it on:
"Windows Boot Manager (on /dev/nvme0n1p1)". That is the name a person
reads when they start the computer, and it is the one place a machine
with two or three systems on it shows its wiring. The pass rewrites the
titles and nothing else -- the lines that boot are untouched, because a
menu that reads well and does not start is worse than a plain one.
"""
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "raye-grub-titles"
FIXTURES = HERE / "fixtures"


assert SCRIPT.is_file(), f"{SCRIPT} is missing"


def run(name, *args):
    """The pass over a copy of a fixture; returns (exit code, text)."""
    src = (FIXTURES / name).read_text()
    work = HERE / f".work-{name}"
    work.write_text(src)
    try:
        p = subprocess.run(["sh", str(SCRIPT), str(work)],
                           capture_output=True, text=True)
        return p.returncode, work.read_text(), p.stderr
    finally:
        work.unlink(missing_ok=True)


def titles(text):
    """Every menuentry/submenu title, in file order."""
    return re.findall(r"^\s*(?:menuentry|submenu) '([^']*)'", text, re.M)


def bootlines(text):
    """The lines that actually boot something."""
    return [l.strip() for l in text.splitlines()
            if re.match(r"\s*(linux|initrd|chainloader|search|insmod)\b", l)]


# --------------------------------------------------------------- the titles


def test_the_partition_leaves_the_title():
    code, out, err = run("grub.cfg.triple")
    assert code == 0, err
    for title in titles(out):
        assert "/dev/" not in title, title
        assert "(on " not in title, title


def test_windows_is_called_windows():
    code, out, _ = run("grub.cfg.triple")
    assert "Windows" in titles(out)
    assert not [t for t in titles(out) if "Boot Manager" in t]


def test_the_other_system_keeps_its_own_name():
    """Their Fedora is theirs: we drop the partition, not the name."""
    code, out, _ = run("grub.cfg.triple")
    assert "Fedora Linux 42 (Workstation Edition)" in titles(out)


def test_advanced_options_follow_their_entry():
    code, out, _ = run("grub.cfg.triple")
    assert "Advanced options for Fedora Linux 42 (Workstation Edition)" in titles(out)
    assert "Advanced options for Raye Linux" in titles(out)


def test_raye_is_left_alone():
    code, out, _ = run("grub.cfg.alone")
    assert code == 0
    assert titles(out) == ["Raye Linux"]


# ------------------------------------------------- two of the same, told apart


def test_two_windows_stay_told_apart():
    """Two disks each with Windows: calling both "Windows" would leave no
    way to pick. The partition comes back, for those two only."""
    code, out, _ = run("grub.cfg.two-windows")
    assert code == 0
    got = titles(out)
    assert len(got) == 2, got
    assert len(set(got)) == 2, f"both entries read the same: {got}"
    for title in got:
        assert title.startswith("Windows"), title
        assert "sda1" in title or "sdb1" in title, title


# ------------------------------------------------------- nothing else moves


def test_what_boots_is_byte_for_byte_the_same():
    for name in ("grub.cfg.triple", "grub.cfg.two-windows", "grub.cfg.alone"):
        before = bootlines((FIXTURES / name).read_text())
        code, out, _ = run(name)
        assert bootlines(out) == before, name


def test_the_menuentry_ids_are_untouched():
    """A changed id loses the saved default and the recordfail state."""
    before = re.findall(r"menuentry_id_option '([^']*)'",
                        (FIXTURES / "grub.cfg.triple").read_text())
    code, out, _ = run("grub.cfg.triple")
    assert re.findall(r"menuentry_id_option '([^']*)'", out) == before


def test_the_classes_are_untouched():
    """The classes carry the icons of the boot theme."""
    before = re.findall(r"--class (\S+)",
                        (FIXTURES / "grub.cfg.triple").read_text())
    code, out, _ = run("grub.cfg.triple")
    assert re.findall(r"--class (\S+)", out) == before


def test_a_hand_written_line_survives():
    code, out, _ = run("grub.cfg.triple")
    assert "a line a person added by hand" in out


def test_the_menu_still_opens_itself_for_the_other_systems():
    """30_os-prober writes timeout_style=menu when it finds another
    system; losing it would boot straight into Raye and hide the rest."""
    code, out, _ = run("grub.cfg.triple")
    assert "set timeout_style=menu" in out


def test_the_line_count_does_not_change():
    for name in ("grub.cfg.triple", "grub.cfg.two-windows", "grub.cfg.alone"):
        before = (FIXTURES / name).read_text().count("\n")
        code, out, _ = run(name)
        assert out.count("\n") == before, name


# ------------------------------------------------------------ it refuses safely


def test_a_missing_file_is_an_error_not_a_silent_pass():
    p = subprocess.run(["sh", str(SCRIPT), "/nonexistent/grub.cfg"],
                       capture_output=True, text=True)
    assert p.returncode != 0
    assert p.stderr.strip(), "it must say what went wrong"


def test_running_it_twice_changes_nothing_more():
    """update-grub runs at every kernel update; the second pass over an
    already-plain menu must be a no-op, or the titles would erode."""
    src = (FIXTURES / "grub.cfg.triple").read_text()
    work = HERE / ".work-twice"
    work.write_text(src)
    try:
        subprocess.run(["sh", str(SCRIPT), str(work)], check=True,
                       capture_output=True)
        once = work.read_text()
        subprocess.run(["sh", str(SCRIPT), str(work)], check=True,
                       capture_output=True)
        assert work.read_text() == once
    finally:
        work.unlink(missing_ok=True)
