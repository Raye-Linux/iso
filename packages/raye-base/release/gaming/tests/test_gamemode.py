# SPDX-License-Identifier: GPL-3.0-or-later
"""What GameMode changes while a game runs."""
import configparser
import pathlib
import shutil
import subprocess

import pytest

GAMING = pathlib.Path(__file__).resolve().parent.parent


def ini():
    c = configparser.ConfigParser(interpolation=None, comment_prefixes=(";", "#"))
    c.read(GAMING / "gamemode.ini")
    return c


def test_processor_runs_at_full_speed_during_a_game():
    # GameMode's own default too: written out so nobody reads the file as
    # leaving the governor alone
    c = ini()
    assert c["general"]["desiredgov"] == "performance"
    # put back what the system had once the game ends
    assert "defaultgov" not in c["general"]


def test_nothing_is_reniced_and_the_screen_stays_on():
    c = ini()
    assert c["general"]["renice"] == "0"
    assert c["general"]["softrealtime"] == "off"
    assert c["general"]["inhibit_screensaver"] == "1"


def test_game_mode_unit_follows_the_game():
    # the unit does the scheduler, the effects and the power mode, and puts
    # them back however it stops; --no-block: GameMode does not wait on it
    c = ini()
    assert c["custom"]["start"] == "systemctl --user --no-block start raye-game-mode.service"
    assert c["custom"]["end"] == "systemctl --user --no-block stop raye-game-mode.service"


def unit(name):
    c = configparser.ConfigParser(interpolation=None, strict=False)
    c.optionxform = str
    c.read(GAMING / name)
    return c


def test_desktop_is_put_back_whatever_ends_game_mode():
    c = unit("raye-game-mode.service")
    assert c["Unit"]["BindsTo"] == "gamemoded.service"
    assert c["Service"]["ExecStartPre"] == "/usr/libexec/raye-game-start"
    assert c["Service"]["ExecStart"] == "/usr/libexec/raye-game-hold"
    # ExecStopPost, not ExecStop: it also runs when the start failed or the
    # main process died
    assert c["Service"]["ExecStopPost"] == "/usr/libexec/raye-game-end"
    assert "ExecStop" not in c["Service"]
    assert "Install" not in c


def test_watcher_runs_in_every_session():
    c = unit("raye-game-watch.service")
    assert c["Service"]["ExecStart"] == "/usr/libexec/raye-game-watch"
    assert c["Install"]["WantedBy"] == "graphical-session.target"
    assert c["Unit"]["PartOf"] == "graphical-session.target"


RULES = (GAMING / "50-raye-game-scheduler.rules").read_text()


def test_player_may_use_gamemodes_own_helpers():
    # Ubuntu's rule wants a "gamemode" group no Raye account is in
    for action in ("com.feralinteractive.GameMode.governor-helper",
                   "com.feralinteractive.GameMode.procsys-helper"):
        assert f'action.id == "{action}"' in RULES
    # never the clock or core helpers: they change the hardware's limits
    assert "gpu-helper" not in RULES
    assert "cpu-helper" not in RULES


def test_rules_are_for_the_player_at_the_machine_only():
    first = RULES.index("polkit.addRule")
    guard = RULES.index("if (!subject.local || !subject.active)")
    assert guard > first
    assert guard < RULES.index("return polkit.Result.YES")


def test_rules_in_a_javascript_engine():
    node = shutil.which("node")
    if not node:
        pytest.skip("no JavaScript engine here")
    script = """
const fs = require("fs");
let rule;
global.polkit = { addRule: f => rule = f, Result: { YES: "yes", NOT_HANDLED: "nh" } };
eval(fs.readFileSync(process.argv[1], "utf8"));
const ask = (id, unit, verb, local, active) =>
    rule({ id, lookup: k => ({ unit, verb })[k] }, { local, active });
const out = [
    ask("org.freedesktop.systemd1.manage-units", "raye-game-scheduler.service", "start", true, true),
    ask("org.freedesktop.systemd1.manage-units", "raye-game-scheduler.service", "restart", true, true),
    ask("org.freedesktop.systemd1.manage-units", "ssh.service", "stop", true, true),
    ask("com.feralinteractive.GameMode.governor-helper", "", "", true, true),
    ask("com.feralinteractive.GameMode.governor-helper", "", "", true, false),
    ask("com.feralinteractive.GameMode.procsys-helper", "", "", false, true),
    ask("com.feralinteractive.GameMode.gpu-helper", "", "", true, true),
];
console.log(out.join(" "));
"""
    out = subprocess.run([node, "-e", script, str(GAMING / "50-raye-game-scheduler.rules")],
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["yes", "nh", "nh", "yes", "nh", "nh", "nh"]
