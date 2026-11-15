# SPDX-License-Identifier: GPL-3.0-or-later
"""Restore points made by hand, and the "earlier states" boot entries."""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

REC = pathlib.Path(__file__).resolve().parent.parent
SORT = REC / "raye-snapshots-sort"
MENU = REC / "raye-earlier-states"
GOBACK = REC / "raye-go-back-at-boot"
PLUGIN = REC / "50-raye"
HOOK = REC / "grub.d" / "42_raye_earlier_states"

FAKE_LIB = """
prepare_grub_to_access_device () {
    echo "insmod part_gpt"
    echo "search --no-floppy --fs-uuid --set=root 1234-ABCD"
}
make_system_path_relative_to_its_root () { echo "${1#/boot}"; }
"""


def snap(number, date, description, cleanup="number", type="single", **userdata):
    return {"number": number, "type": type, "date": date, "cleanup": cleanup,
            "description": description, "userdata": userdata or None}


def fakes(tmp_path, snaps):
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (tmp_path / "list.json").write_text(json.dumps({"root": [snap(0, "", "current", cleanup="")] + snaps}))
    log = tmp_path / "calls"
    for name, body in {
        "snapper": f'echo "snapper $*" >> "{log}"\ncase "$*" in *list*) cat "{tmp_path}/list.json" ;; esac',
        "systemctl": f'echo "systemctl $*" >> "{log}"',
        "plymouth": f'echo "plymouth $*" >> "{log}"',
        "sleep": "true",
    }.items():
        (bin_ / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    (tmp_path / "lib").write_text(FAKE_LIB)
    root = tmp_path / "root"
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "etc/default").mkdir(parents=True, exist_ok=True)
    (root / "proc/cmdline").write_text(
        "BOOT_IMAGE=/vmlinuz-7.0.14-raye root=UUID=aaaa ro rootflags=subvol=@ quiet splash raye.go-back=3\n")
    env = dict(os.environ, PATH=f"{bin_}:/usr/bin:/bin", RAYE_SNAPSHOTS_SNAPPER=str(bin_ / "snapper"),
               RAYE_EARLIER_ROOT=str(root), RAYE_EARLIER_LIB=str(tmp_path / "lib"))
    return env, log, root


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_manual_points_leave_the_number_cleanup(tmp_path):
    env, log, _ = fakes(tmp_path, [
        snap(4, "2026-11-10 10:00:00", "Before tinkering", important="yes", raye="manual"),
        snap(5, "2026-11-10 11:00:00", "Before installing updates", important="yes", raye="update")])
    subprocess.run([str(SORT)], env=env, check=True)
    acted = [c for c in calls(log) if "list" not in c]
    assert acted == ["snapper --no-dbus -c root modify -c  4"]


def test_only_the_newest_three_manual_points_stay(tmp_path):
    env, log, _ = fakes(tmp_path, [
        snap(n, f"2026-11-0{n} 10:00:00", f"Point {n}", cleanup="", raye="manual") for n in range(1, 6)])
    subprocess.run([str(SORT)], env=env, check=True)
    assert [c for c in calls(log) if "delete" in c] == [
        "snapper --no-dbus -c root delete 1", "snapper --no-dbus -c root delete 2"]


def menu(tmp_path, snaps, lang=None, cmdline=None):
    env, _, root = fakes(tmp_path, snaps)
    if lang:
        (root / "etc/default/locale").write_text(f'LANG="{lang}"\n')
    if cmdline:
        (root / "proc/cmdline").write_text(cmdline)
    out = tmp_path / "earlier.cfg"
    subprocess.run([str(MENU), str(out)], env=env, check=True)
    return out.read_text()


POINTS = [snap(7, "2026-11-11 09:30:12", "Before installing updates", raye="update"),
          snap(9, "2026-11-12 14:03:40", "My point's 'name'", raye="manual")]


def test_one_entry_per_point_newest_first(tmp_path):
    text = menu(tmp_path, POINTS)
    assert text.startswith("submenu 'Raye Linux, earlier states' --class raye {")
    entries = [l.strip() for l in text.splitlines() if "menuentry" in l]
    assert entries == [
        "menuentry '2026-11-12 14:03  My point'\\''s '\\''name'\\''' --class raye --id raye-earlier-9 {",
        "menuentry '2026-11-11 09:30  Before installing updates' --class raye --id raye-earlier-7 {"]
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("linux ")]
    assert lines[0] == "linux /vmlinuz root=UUID=aaaa ro rootflags=subvol=@ quiet splash raye.go-back=9"
    assert "search --no-floppy --fs-uuid --set=root 1234-ABCD" in text
    assert "initrd /initrd.img" in text


def test_menu_is_valid_grub(tmp_path):
    if not shutil.which("grub-script-check"):
        pytest.skip("grub-script-check is not installed")
    out = tmp_path / "check.cfg"
    out.write_text(menu(tmp_path, POINTS))
    subprocess.run(["grub-script-check", str(out)], check=True)
    hook = subprocess.run(["sh", str(HOOK)], capture_output=True, text=True, check=True).stdout
    (tmp_path / "hook.cfg").write_text(hook)
    subprocess.run(["grub-script-check", str(tmp_path / "hook.cfg")], check=True)
    assert "raye-earlier-states.cfg" in hook


def entries(text):
    return [l.strip().split(" --class")[0] for l in text.splitlines() if "menuentry" in l]


def test_french_titles_match_settings(tmp_path):
    text = menu(tmp_path, POINTS + [
        snap(10, "2026-11-12 15:00:00", "apt"),
        snap(11, "2026-11-13 08:00:00", "Daily restore point", cleanup="timeline", raye="daily")],
        lang="fr_CA.UTF-8")
    assert text.startswith("submenu 'Raye Linux, états précédents'")
    assert entries(text) == [
        "menuentry '2026-11-13 08:00  Point de restauration quotidien'",
        "menuentry '2026-11-12 15:00  Avant l'\\''installation de mises à jour ou d'\\''applications'",
        "menuentry '2026-11-12 14:03  My point'\\''s '\\''name'\\'''",
        "menuentry '2026-11-11 09:30  Avant l'\\''installation des mises à jour'"]


def test_post_points_left_out(tmp_path):
    text = menu(tmp_path, [
        snap(20, "2026-11-12 10:00:00", "Before installing updates", type="pre", raye="update"),
        snap(21, "2026-11-12 10:04:00", "After installing updates", type="post", raye="update")])
    assert entries(text) == ["menuentry '2026-11-12 10:00  Before installing updates'"]


def test_menu_stops_at_thirty_points(tmp_path):
    text = menu(tmp_path, [snap(n, "2026-11-12 10:00:00", "", raye="daily") for n in range(1, 41)])
    assert len(entries(text)) == 30
    assert "raye-earlier-40 " in text and "raye-earlier-10 " not in text


def test_no_points_no_submenu(tmp_path):
    assert menu(tmp_path, []) == ""


def test_live_session_writes_nothing(tmp_path):
    assert menu(tmp_path, POINTS, cmdline="boot=casper quiet splash\n") == ""


def go_back(tmp_path, cmdline, result="done"):
    env, log, root = fakes(tmp_path, [])
    tool = tmp_path / "snapshot-restore"
    tool.write_text(f'#!/bin/sh\necho "restore $*" >> "{log}"\necho {result}\n')
    tool.chmod(0o755)
    (tmp_path / "cmdline").write_text(cmdline)
    env.update(RAYE_GO_BACK_CMDLINE=str(tmp_path / "cmdline"), RAYE_GO_BACK_TOOL=str(tool))
    subprocess.run(["sh", str(GOBACK)], env=env, check=True)
    return [c for c in calls(log) if not c.startswith("plymouth")]


def test_boot_entry_goes_back_then_restarts(tmp_path):
    assert go_back(tmp_path, "root=UUID=a quiet raye.go-back=12\n") == [
        "restore go-back 12", "systemctl --no-block reboot"]


def test_failed_go_back_starts_as_usual(tmp_path):
    assert go_back(tmp_path, "raye.go-back=12\n", result="error failed") == ["restore go-back 12"]


def plymouth_calls(tmp_path, result):
    tmp_path.mkdir()
    go_back(tmp_path, "raye.go-back=12\n", result=result)
    return [c for c in calls(tmp_path / "calls") if c.startswith("plymouth")]


def test_go_back_uses_the_theme_keys(tmp_path):
    assert plymouth_calls(tmp_path / "ok", "done") == ["plymouth display-message --text=raye:go-back"]
    assert plymouth_calls(tmp_path / "no", "error failed") == [
        "plymouth display-message --text=raye:go-back",
        "plymouth display-message --text=raye:go-back-failed",
        "plymouth display-message --text=raye:clear"]


def test_ordinary_boot_does_nothing(tmp_path):
    assert go_back(tmp_path, "root=UUID=a quiet splash\n") == []
    assert go_back(tmp_path, "raye.go-back=12x\n") == []


def test_plugin_wakes_the_unit_for_root_only(tmp_path):
    env, log, _ = fakes(tmp_path, [])
    env["RAYE_SYSTEMD_RUN"] = str(tmp_path)
    subprocess.run(["sh", str(PLUGIN), "create-snapshot-post", "/", "btrfs", "12"], env=env, check=True)
    subprocess.run(["sh", str(PLUGIN), "delete-snapshot-post", "/home", "btrfs", "3"], env=env, check=True)
    subprocess.run(["sh", str(PLUGIN), "create-snapshot-pre", "/", "btrfs", "13"], env=env, check=True)
    assert calls(log) == ["systemctl --no-block start raye-snapshots-changed.service"]
