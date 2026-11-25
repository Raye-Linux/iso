"""A fallback level of the graphics ladder is not kept for good: once per
new kernel the shutdown arms a trial of the better level, the next start
uses it, a graphical session keeps it, and no session (or a forced restart)
puts the PC back on the level that worked. The case: an RX 550 that a black
start or two left on nomodeset (800x600, no acceleration: low resolution and
a few frames per second) or amdgpu.dc=0 never went back to its full driver."""
import configparser
import os
import subprocess
from pathlib import Path

from test_graphics_ladder import ladder_code, run_grub, start_raye

GRUB = Path(__file__).resolve().parents[1]
OK = GRUB / "raye-graphics-ok"
UNIT = GRUB / "raye-graphics-trial.service"
PATHS = GRUB.parent.parent / "debian" / "raye-release-paths"

# ------------------------------------------------------------- boot menu


def test_an_armed_trial_starts_level_0_and_is_marked_running(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_level": "2", "raye_gfx_try": "0"}
    start_raye(code, env)
    assert env["raye_gfx"] == "raye.gfx_try=0"
    assert env["raye_gfx_trying"] == "1" and "raye_gfx_trying" in env["saved_vars"]


def test_a_trial_that_never_reached_the_desktop_goes_back(tmp_path):
    # forced restart in the trial start: the menu drops the trial, nomodeset
    # again, and the failed start does not step the ladder down
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_level": "2", "raye_gfx_try": "0"}
    start_raye(code, env)
    start_raye(code, env)
    assert env["raye_gfx"] == "nomodeset"
    assert env["raye_gfx_try"] == "" and env["raye_gfx_trying"] == "failed"
    assert env["raye_gfx_level"] == "2"
    # the menu shows, so safe graphics can be picked by hand
    assert env.get("timeout_style") == "menu"
    # and it stays there, no new trial without a new arm
    env["raye_gfx_fails"] = "0"
    start_raye(code, env)
    assert env["raye_gfx"] == "nomodeset" and env["raye_gfx_level"] == "2"


def test_a_level_1_trial_on_an_older_amd_card_keeps_its_driver(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_level": "2", "raye_gfx_try": "1", "raye_gfx_amd_dce": "1"}
    start_raye(code, env)
    assert env["raye_gfx"] == "amdgpu.dc=0 plymouth.enable=0 raye.gfx_try=1"


def test_picking_windows_leaves_the_trial_armed(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_level": "2", "raye_gfx_try": "0"}
    run_grub(code, env)
    assert env.get("raye_gfx_trying", "") == "" and env["raye_gfx_try"] == "0"


def test_no_trial_no_change(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_level": "2"}
    start_raye(code, env)
    assert env["raye_gfx"] == "nomodeset" and "raye_gfx_trying" not in env

# ------------------------------------------------------ raye-graphics-ok

FAKE_EDITENV = r'''#!/usr/bin/env python3
import sys
path, cmd, *args = sys.argv[1:]
lines = [l for l in open(path).read().splitlines() if l and not l.startswith("#")]
env = dict(l.split("=", 1) for l in lines)
if cmd == "list":
    print("\n".join(f"{k}={v}" for k, v in env.items()))
    sys.exit(0)
if cmd == "set":
    for a in args:
        k, v = a.split("=", 1)
        env[k] = v
elif cmd == "unset":
    for a in args:
        env.pop(a, None)
with open(path, "w") as f:
    f.write("# GRUB Environment Block\n" + "".join(f"{k}={v}\n" for k, v in env.items()))
'''


def box(tmp_path, grubenv, sessions=None, cmdline="quiet splash", fs="ext4", dce=False, kernels=("7.0.0-44-generic",)):
    """A PC: its grubenv, logind sessions, kernel line and /boot."""
    (tmp_path / "grub-editenv").write_text(FAKE_EDITENV)
    sessions = sessions or {}
    lc = tmp_path / "loginctl"
    lc.write_text("#!/bin/sh\nif [ \"$1\" = list-sessions ]; then\n"
                  + "".join(f'echo "{i} 1000 anna seat0"\n' for i in sessions)
                  + "exit 0\nfi\ncase $2 in\n"
                  + "".join(f'  {i}) printf "%s\\n" "{v}" ;;\n' for i, v in sessions.items())
                  + "esac\n")
    (tmp_path / "grub-probe").write_text(f"#!/bin/sh\necho {fs}\n")
    (tmp_path / "reboot").write_text(f"#!/bin/sh\necho rebooted > {tmp_path}/rebooted\n")
    (tmp_path / "dce").write_text(f"#!/bin/sh\n[ \"$1\" = --sync ] && exit 0\nexit {0 if dce else 1}\n")
    for f in ("grub-editenv", "loginctl", "grub-probe", "reboot", "dce"):
        (tmp_path / f).chmod(0o755)
    boot = tmp_path / "boot"
    boot.mkdir(exist_ok=True)
    for k in kernels:
        (boot / f"vmlinuz-{k}").write_text("")
    (tmp_path / "grubenv").write_text("# GRUB Environment Block\n" + "".join(f"{k}={v}\n" for k, v in grubenv.items()))
    (tmp_path / "cmdline").write_text(cmdline + "\n")
    (tmp_path / "default").mkdir(exist_ok=True)
    (tmp_path / "default" / "grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
    return {"PATH": f"{tmp_path}:/usr/bin:/bin", "LOGINCTL": str(lc),
            "RAYE_GRUBENV": str(tmp_path / "grubenv"), "RAYE_CMDLINE": str(tmp_path / "cmdline"),
            "RAYE_GFX_SEEN": str(tmp_path / "seen"), "RAYE_BOOT_DIR": str(boot),
            "RAYE_GRUB_DEFAULTS": str(tmp_path / "default"), "RAYE_AMD_DCE": str(tmp_path / "dce"),
            "RAYE_SYSTEM_UPDATE": str(tmp_path / "system-update"), "grub_probe": str(tmp_path / "grub-probe"),
            "RAYE_REBOOT": str(tmp_path / "reboot"), "RAYE_GFX_TRIES": "2", "RAYE_GFX_TRIAL_TRIES": "2",
            "RAYE_GFX_WAIT": "0"}


def grubenv(tmp_path):
    lines = (tmp_path / "grubenv").read_text().splitlines()
    return dict(l.split("=", 1) for l in lines if l and not l.startswith("#"))


def ok(env, *args):
    return subprocess.run(["sh", str(OK), *args], env=env, capture_output=True, text=True, timeout=30)


DESKTOP = {"3": "Class=user\nType=wayland\nState=active"}


def test_a_fallback_start_that_drew_arms_a_trial_at_shutdown(tmp_path):
    env = box(tmp_path, {"raye_gfx_level": "2", "raye_gfx_fails": "1"}, DESKTOP)
    ok(env)
    assert (tmp_path / "seen").exists() and grubenv(tmp_path)["raye_gfx_fails"] == "0"
    ok(env, "--arm")
    g = grubenv(tmp_path)
    assert g["raye_gfx_try"] == "0" and g["raye_gfx_tried"] == "7.0.0-44-generic"


def test_the_trial_start_keeps_the_level_that_drew(tmp_path):
    env = box(tmp_path, {"raye_gfx_level": "2", "raye_gfx_try": "0", "raye_gfx_trying": "1",
                         "raye_gfx_fails": "1", "raye_gfx_try_fails": "1"},
              DESKTOP, cmdline="quiet splash raye.gfx_try=0")
    ok(env)
    g = grubenv(tmp_path)
    assert g["raye_gfx_level"] == "0" and g["raye_gfx_fails"] == "0"
    assert g["raye_gfx_try"] == "" and g["raye_gfx_trying"] == "" and g["raye_gfx_try_fails"] == "0"
    assert not (tmp_path / "rebooted").exists()


def test_a_trial_start_that_never_draws_restarts_on_the_old_level(tmp_path):
    env = box(tmp_path, {"raye_gfx_level": "2", "raye_gfx_try": "0", "raye_gfx_trying": "1",
                         "raye_gfx_fails": "1"},
              {"4": "Class=user\nType=tty\nState=active"}, cmdline="quiet splash raye.gfx_try=0")
    ok(env)
    g = grubenv(tmp_path)
    assert g["raye_gfx_level"] == "2" and g["raye_gfx_fails"] == "0"
    assert g["raye_gfx_try"] == "" and g["raye_gfx_trying"] == "" and g["raye_gfx_try_fails"] == "1"
    assert (tmp_path / "rebooted").exists()


def test_safe_graphics_picked_by_hand_is_not_a_trial(tmp_path):
    env = box(tmp_path, {"raye_gfx_level": "2", "raye_gfx_try": "0", "raye_gfx_trying": "1", "raye_gfx_fails": "1"},
              DESKTOP, cmdline="quiet splash raye.gfx_try=0 nomodeset")
    ok(env)
    g = grubenv(tmp_path)
    assert g["raye_gfx_level"] == "2" and g["raye_gfx_try"] == "0" and g["raye_gfx_trying"] == ""


def test_a_trial_cut_short_is_counted(tmp_path):
    env = box(tmp_path, {"raye_gfx_level": "2", "raye_gfx_trying": "failed", "raye_gfx_try_fails": "1"}, DESKTOP)
    ok(env)
    g = grubenv(tmp_path)
    assert g["raye_gfx_try_fails"] == "2" and g["raye_gfx_trying"] == ""


def armed(tmp_path, grub, **kw):
    env = box(tmp_path, grub, **kw)
    (tmp_path / "seen").write_text("")
    ok(env, "--arm")
    return grubenv(tmp_path)


def test_one_trial_per_kernel(tmp_path):
    g = armed(tmp_path, {"raye_gfx_level": "1", "raye_gfx_fails": "0", "raye_gfx_tried": "7.0.0-44-generic"})
    assert "raye_gfx_try" not in g
    # a newer kernel came in: worth one more trial
    g = armed(tmp_path, {"raye_gfx_level": "1", "raye_gfx_fails": "0", "raye_gfx_tried": "7.0.0-44-generic"},
              kernels=("7.0.0-44-generic", "7.0.0-47-generic"))
    assert g["raye_gfx_try"] == "0" and g["raye_gfx_tried"] == "7.0.0-47-generic"


def test_nomodeset_on_an_older_amd_card_then_tries_amdgpu_dc_0(tmp_path):
    g = armed(tmp_path, {"raye_gfx_level": "2", "raye_gfx_fails": "0", "raye_gfx_tried": "7.0.0-44-generic"}, dce=True)
    assert g["raye_gfx_try"] == "1" and g["raye_gfx_tried1"] == "7.0.0-44-generic"
    g = armed(tmp_path, {"raye_gfx_level": "2", "raye_gfx_fails": "0", "raye_gfx_tried": "7.0.0-44-generic"}, dce=False)
    assert "raye_gfx_try" not in g


def test_never_armed_when_it_must_not_be(tmp_path):
    base = {"raye_gfx_level": "2", "raye_gfx_fails": "0"}
    cases = [
        ({"raye_gfx_level": "0", "raye_gfx_fails": "0"}, {}),      # the normal level already
        ({**base, "raye_gfx_fails": "1"}, {}),                       # this start never drew
        ({**base, "raye_gfx_try_fails": "2"}, {}),                   # two trials failed
        ({**base, "raye_gfx_try": "0"}, {}),                         # one armed already
        (base, {"fs": "btrfs"}),                                     # GRUB cannot write /boot
    ]
    for grub, kw in cases:
        assert "raye_gfx_try" not in armed(tmp_path, grub, **kw) or grub.get("raye_gfx_try"), (grub, kw)
    # an offline update comes next
    env = box(tmp_path, base)
    (tmp_path / "seen").write_text("")
    (tmp_path / "system-update").write_text("")
    ok(env, "--arm")
    assert "raye_gfx_try" not in grubenv(tmp_path)
    (tmp_path / "system-update").unlink()
    # the person wrote nomodeset in /etc/default/grub
    env = box(tmp_path, base)
    (tmp_path / "seen").write_text("")
    (tmp_path / "default" / "grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet nomodeset"\n')
    ok(env, "--arm")
    assert "raye_gfx_try" not in grubenv(tmp_path)
    # no start that drew in this boot
    env = box(tmp_path, base)
    (tmp_path / "seen").unlink()
    ok(env, "--arm")
    assert "raye_gfx_try" not in grubenv(tmp_path)


def test_the_unit_arms_at_shutdown_and_is_shipped():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read_string(UNIT.read_text())
    assert cp["Service"]["ExecStop"] == "/usr/libexec/raye-graphics-ok --arm"
    assert cp["Service"]["RemainAfterExit"] == "yes"
    assert "/boot" in cp["Unit"]["RequiresMountsFor"].split()
    assert cp["Install"]["WantedBy"] == "graphical.target"
    lines = [l.split() for l in PATHS.read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert ["raye-system", "release/grub/raye-graphics-trial.service",
            "usr/lib/systemd/system/raye-graphics-trial.service"] in lines
