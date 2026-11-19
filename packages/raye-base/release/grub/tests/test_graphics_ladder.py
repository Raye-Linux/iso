"""The graphics ladder: the boot menu steps down after two starts that never
reach the desktop, and a session of a person (not the sign-in screen) clears
the try. GRUB itself is replayed by a tiny model of its script below."""
import os
import re
import stat
import subprocess
from pathlib import Path

GRUB = Path(__file__).resolve().parents[1]
LADDER, OK, CFG = GRUB / "09_raye_graphics", GRUB / "raye-graphics-ok", GRUB / "50-raye.cfg"


def ladder_code(tmp_path, fs="ext4"):
    probe = tmp_path / "probe"
    probe.write_text(f"#!/bin/sh\necho {fs}\n")
    probe.chmod(0o755)
    return subprocess.run(["sh", str(LADDER)], env={"PATH": "/usr/bin:/bin", "grub_probe": str(probe)},
                          capture_output=True, text=True, check=True).stdout


def run_grub(code, env):
    """Runs the generated GRUB code: if/elif/else/fi, set, save_env, with ${var},
    and function definitions called by name."""
    lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    funcs = {}
    body = None
    top = []
    for line in lines:
        m = re.fullmatch(r"function (\w+) \{", line)
        if m:
            body = funcs.setdefault(m.group(1), [])
        elif body is not None and line == "}":
            body = None
        elif body is not None:
            body.append(line)
        else:
            top.append(line)
    stack = []          # (taken_any, active)

    def active():
        return all(a for _, a in stack)

    def test(expr):
        m = re.fullmatch(r'\[ -([nz]) "\$\{(\w+)\}" \]', expr)
        if m:
            return bool(env.get(m.group(2), "")) == (m.group(1) == "n")
        m = re.fullmatch(r'\[ "\$\{(\w+)\}" (=|!=) (\S+) \]', expr)
        val = env.get(m.group(1), "")
        return (val == m.group(3)) if m.group(2) == "=" else (val != m.group(3))

    def do(stmt):
        if not active():
            return
        if stmt.startswith("set "):
            k, v = stmt[4:].split("=", 1)
            env[k] = v.strip('"')
        elif stmt.startswith("save_env"):
            env["saved"] = "yes"
            env.setdefault("saved_vars", set()).update(stmt.split()[1:])
        elif stmt in funcs:
            run(funcs[stmt])

    def part_of(part):
        if part.startswith("if "):
            ok = active() and test(part[3:].replace(" then", "").strip())
            stack.append([ok, ok])
        elif part.startswith("elif "):
            taken = stack[-1][0]
            ok = not taken and all(a for _, a in stack[:-1]) and test(part[5:].replace(" then", "").strip())
            stack[-1] = [taken or ok, ok]
        elif part.startswith("else"):
            taken = stack[-1][0]
            stack[-1] = [True, not taken and all(a for _, a in stack[:-1])]
            if part[4:].strip():
                part_of(part[4:].strip())
        elif part == "fi":
            stack.pop()
        elif part.startswith("then"):
            if part[4:].strip():
                part_of(part[4:].strip())
        else:
            do(part)

    def run(block):
        for line in block:
            for part in [p.strip() for p in re.split(r";\s*(?=then|else|fi|set|if|save_env)", line) if p.strip()]:
                part_of(part)
    run(top)
    return env


def start_raye(code, env):
    """GRUB reads its menu, then the Raye entry runs; every Linux entry of
    10_linux starts with recordfail."""
    return run_grub(code + "\nrecordfail\n", env)


def test_the_kernel_line_carries_the_ladder():
    assert re.search(r'GRUB_CMDLINE_LINUX_DEFAULT="[^"]*\\\$raye_gfx"', CFG.read_text())


def test_nothing_is_written_where_grub_cannot_save(tmp_path):
    assert ladder_code(tmp_path, "btrfs") == ""
    assert "save_env" in ladder_code(tmp_path, "ext4")


def test_two_failed_starts_step_down_and_a_good_one_stays(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true"}
    levels = []
    for reached_desktop in [False, False, False, False, True, True]:
        start_raye(code, env)
        levels.append(env["raye_gfx"])
        if reached_desktop:
            env["raye_gfx_fails"] = "0"         # what raye-graphics-ok writes
    # two black starts at the normal level, two at amdgpu.dc=0, then nomodeset
    # works and stays
    assert levels == ["", "", "amdgpu.dc=0 plymouth.enable=0", "amdgpu.dc=0 plymouth.enable=0", "nomodeset", "nomodeset"]


def test_a_working_desktop_never_steps_down(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true"}
    for _ in range(10):
        start_raye(code, env)
        assert env["raye_gfx"] == ""
        env["raye_gfx_fails"] = "0"


def fake_loginctl(tmp_path, sessions):
    """sessions: {id: 'Class=..\\nType=..\\nState=..'}"""
    lc = tmp_path / "loginctl"
    body = "\n".join(f'  {i}) printf "%s\\n" "{v}" ;;' for i, v in sessions.items())
    lc.write_text("#!/bin/sh\nif [ \"$1\" = list-sessions ]; then\n"
                  + "".join(f'echo "{i} 1000 anna seat0"\n' for i in sessions)
                  + 'exit 0\nfi\ncase $2 in\n' + body + "\nesac\n")
    lc.chmod(0o755)
    edit = tmp_path / "grub-editenv"
    edit.write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/written\n')
    edit.chmod(0o755)
    env_file = tmp_path / "grubenv"
    env_file.write_text("# GRUB Environment Block\n")
    return {"PATH": f"{tmp_path}:/usr/bin:/bin", "LOGINCTL": str(lc), "RAYE_GRUBENV": str(env_file),
            "RAYE_GFX_TRIES": "2", "RAYE_GFX_WAIT": "0"}


def test_a_desktop_session_clears_the_try(tmp_path):
    env = fake_loginctl(tmp_path, {"3": "Class=user\nType=wayland\nState=active"})
    subprocess.run(["sh", str(OK)], env=env, check=True)
    assert (tmp_path / "written").read_text().split() == [str(tmp_path / "grubenv"), "set", "raye_gfx_fails=0"]


def test_the_sign_in_screen_alone_does_not(tmp_path):
    env = fake_loginctl(tmp_path, {"c1": "Class=greeter\nType=wayland\nState=active",
                                   "4": "Class=user\nType=tty\nState=active"})
    subprocess.run(["sh", str(OK)], env=env, check=True)
    assert not (tmp_path / "written").exists()


def test_the_menu_shows_after_a_start_that_never_reached_the_desktop(tmp_path):
    code = ladder_code(tmp_path)
    # what 00_header leaves for a hidden menu
    env = {"have_grubenv": "true", "timeout_style": "hidden", "timeout": "0"}
    start_raye(code, env)
    assert (env["timeout_style"], env["timeout"]) == ("hidden", "0")
    # nobody reached the desktop: the next start shows the menu
    start_raye(code, env)
    assert (env["timeout_style"], env["timeout"]) == ("menu", "3")
    # still nothing: the ladder steps down and the menu shows again
    env["timeout_style"], env["timeout"] = "hidden", "0"
    start_raye(code, env)
    assert (env["timeout_style"], env["timeout"]) == ("menu", "3")
    assert env["raye_gfx"].startswith("amdgpu.dc=0")
    # someone signed in: hidden again
    env["raye_gfx_fails"] = "0"
    env["timeout_style"], env["timeout"] = "hidden", "0"
    start_raye(code, env)
    assert (env["timeout_style"], env["timeout"]) == ("hidden", "0")


def test_a_longer_menu_wait_is_kept(tmp_path):
    # recordfail already asked for its own wait
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true", "raye_gfx_fails": "1", "timeout": "5"}
    start_raye(code, env)
    assert (env["timeout_style"], env["timeout"]) == ("menu", "5")


WAIT = GRUB / "31_raye_menu_wait"


def menu_wait_code(timeout="0"):
    env = {"PATH": "/usr/bin:/bin", "GRUB_TIMEOUT": timeout}
    return subprocess.run(["sh", str(WAIT)], env=env, capture_output=True, text=True,
                          check=True).stdout


def test_another_system_on_the_disk_gets_three_seconds():
    # 30_os-prober opens the menu for 10 seconds when it finds Windows
    env = {"timeout_style": "menu", "timeout": "10"}
    run_grub(menu_wait_code(), env)
    assert env["timeout"] == "3"
    # no other system: the hidden menu is left alone
    env = {"timeout_style": "hidden", "timeout": "0"}
    run_grub(menu_wait_code(), env)
    assert (env["timeout_style"], env["timeout"]) == ("hidden", "0")


def test_a_menu_wait_set_by_hand_is_left_alone():
    assert menu_wait_code("10") == ""
    assert os.access(WAIT, os.X_OK)
    paths = (GRUB.parent.parent / "debian" / "raye-release-paths").read_text()
    assert re.search(r"^raye-system\s+release/grub/31_raye_menu_wait\s+etc/grub.d/31_raye_menu_wait\s*$",
                     paths, re.M)


def test_picking_another_system_counts_no_try(tmp_path):
    # Windows, twice: Raye never started, so its graphics never failed
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true"}
    for _ in range(4):
        run_grub(code, env)
    assert env.get("raye_gfx_fails", "") == ""
    assert env["raye_gfx"] == ""
    start_raye(code, env)
    assert env["raye_gfx_fails"] == "1" and env["raye_gfx"] == ""


def test_the_raye_entry_still_records_its_start(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true"}
    start_raye(code, env)
    assert env["recordfail"] == "1"
    assert {"recordfail", "raye_gfx_fails"} <= env["saved_vars"]
    # grub-reboot: the one-time start does not mark the saved default as failed
    env = {"have_grubenv": "true", "boot_once": "true"}
    start_raye(code, env)
    assert "recordfail" not in env["saved_vars"]
    assert "raye_gfx_fails" in env["saved_vars"]


def test_recordfail_keeps_the_stock_body():
    header = Path("/etc/grub.d/00_header")
    if not header.exists():
        import pytest
        pytest.skip("no /etc/grub.d/00_header here")
    stock = header.read_text().replace("\\$", "$")
    m = re.search(r"function recordfail \{\n(.*?)\n(?:EOF|\})", stock, re.S)
    assert m
    ours = (GRUB / "09_raye_graphics").read_text()
    for line in m.group(1).splitlines():
        if line.strip():
            assert line in ours, line
