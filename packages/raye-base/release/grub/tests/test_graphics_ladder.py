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
    """Runs the generated GRUB code: if/elif/else/fi, set, save_env, with ${var}."""
    lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    stack = []          # (taken_any, active)

    def active():
        return all(a for _, a in stack)

    def test(expr):
        m = re.fullmatch(r'\[ "\$\{(\w+)\}" (=|!=) (\S+) \]', expr)
        val = env.get(m.group(1), "")
        return (val == m.group(3)) if m.group(2) == "=" else (val != m.group(3))

    def do(stmt):
        if not active():
            return
        if stmt.startswith("set "):
            k, v = stmt[4:].split("=", 1)
            env[k] = v
        elif stmt.startswith("save_env"):
            env["saved"] = "yes"
    for line in lines:
        for part in [p.strip() for p in re.split(r";\s*(?=then|else|fi|set|if)", line) if p.strip()]:
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
                rest = part[4:].strip()
                if rest:
                    do(rest)
            elif part == "fi":
                stack.pop()
            elif part.startswith("then"):
                rest = part[4:].strip()
                if rest:
                    do(rest)
            else:
                do(part)
    return env


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
        run_grub(code, env)
        levels.append(env["raye_gfx"])
        if reached_desktop:
            env["raye_gfx_fails"] = "0"         # what raye-graphics-ok writes
    # two black starts at the normal level, two at amdgpu.dc=0, then nomodeset
    # works and stays
    assert levels == ["", "", "amdgpu.dc=0", "amdgpu.dc=0", "nomodeset", "nomodeset"]


def test_a_working_desktop_never_steps_down(tmp_path):
    code = ladder_code(tmp_path)
    env = {"have_grubenv": "true"}
    for _ in range(10):
        run_grub(code, env)
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
