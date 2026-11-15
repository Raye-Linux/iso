# SPDX-License-Identifier: GPL-3.0-or-later
"""System Monitor pins left by 0.2 become Task Manager pins."""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "raye-taskmanager-pin.py"
UPD = HERE.parent / "raye-taskmanager-pin.upd"

OLD_RC = """[Taskbar]
Alignment=center
Pinned=org.kde.dolphin.desktop,org.kde.plasma-systemmonitor.desktop

[Start]
Layout=default
Pinned=firefox.desktop,org.kde.plasma-systemmonitor.desktop,org.kde.kate.desktop,org.raye.taskmanager.desktop
PinnedFolders=Tools:org.kde.plasma-systemmonitor.desktop;org.kde.kcalc.desktop

[JumpLists]
Recent=org.kde.plasma-systemmonitor.desktop
"""


def run(tmp_path, text):
    config = tmp_path / "config"
    config.mkdir()
    rc = config / "rayeshellrc"
    if text is not None:
        rc.write_text(text)
        rc.chmod(0o600)
    env = dict(os.environ, XDG_CONFIG_HOME=str(config))
    subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)], env=env, check=True)
    return rc


def test_pins_move_to_task_manager(tmp_path):
    rc = run(tmp_path, OLD_RC)
    lines = rc.read_text().splitlines()
    assert "Pinned=org.kde.dolphin.desktop,org.raye.taskmanager.desktop" in lines
    assert ("Pinned=firefox.desktop,org.raye.taskmanager.desktop,org.kde.kate.desktop"
            in lines)
    assert "PinnedFolders=Tools:org.raye.taskmanager.desktop;org.kde.kcalc.desktop" in lines


def test_other_groups_and_keys_stay(tmp_path):
    rc = run(tmp_path, OLD_RC)
    assert "Recent=org.kde.plasma-systemmonitor.desktop" in rc.read_text()
    assert oct(rc.stat().st_mode & 0o777) == "0o600"


def test_untouched_account_keeps_its_file(tmp_path):
    text = "[Start]\nPinned=firefox.desktop\n"
    rc = run(tmp_path, text)
    assert rc.read_text() == text


def test_no_file_no_file(tmp_path):
    assert not run(tmp_path, None).exists()


def test_upd_runs_the_script_with_python():
    text = UPD.read_text()
    assert "Version=6" in text
    assert "Script=raye-taskmanager-pin.py,python3" in text
