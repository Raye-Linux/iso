# SPDX-License-Identifier: GPL-3.0-or-later
"""What GameMode changes while a game runs."""
import configparser
import pathlib

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


def test_the_game_scheduler_follows_the_game():
    c = ini()
    assert c["custom"]["start"] == "systemctl --no-ask-password start raye-game-scheduler.service"
    assert c["custom"]["end"] == "systemctl --no-ask-password stop raye-game-scheduler.service"
