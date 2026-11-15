# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit drop-ins for start-up and shutdown."""
import os
import pathlib
import shlex
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
BOOT = HERE.parent
PK = BOOT / "packagekit-offline-update.service.d" / "raye-update.conf"


def condition(path, link):
    for line in path.read_text().splitlines():
        if line.startswith("ExecCondition="):
            value = line.split("=", 1)[1].replace("/system-update", str(link))
            return subprocess.run(shlex.split(value), capture_output=True).returncode
    raise AssertionError("no ExecCondition")


def test_packagekit_stays_out_of_raye_offline_updates(tmp_path):
    link = tmp_path / "system-update"
    os.symlink("/var/lib/raye-update/offline", link)
    # skipped, never failed: a failure would run its FailureAction=reboot
    assert 1 <= condition(PK, link) <= 254


def test_packagekit_runs_its_own(tmp_path):
    link = tmp_path / "system-update"
    os.symlink("/var/lib/PackageKit/prepared-update", link)
    assert condition(PK, link) == 0


def test_packagekit_without_any_link(tmp_path):
    assert condition(PK, tmp_path / "system-update") == 0


HOOK = BOOT / "raye-realpath"


def test_realpath_for_the_initramfs(tmp_path):
    dest = tmp_path / "initramfs"
    r = subprocess.run(["sh", str(HOOK)], env=dict(os.environ, DESTDIR=str(dest)),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    shim = dest / "usr/bin/realpath"
    assert os.access(shim, os.X_OK)
    # /sys/block/<disk>/slaves/<part> is a link to the partition's folder
    real = tmp_path / "devices" / "sda3"
    real.mkdir(parents=True)
    slaves = tmp_path / "slaves"
    slaves.mkdir()
    (slaves / "sda3").symlink_to("../devices/sda3")
    for args in (["sh", str(shim), str(slaves / "sda3")],
                 ["sh", str(shim), "-e", "--", str(slaves / "sda3")]):
        out = subprocess.run(args, capture_output=True, text=True)
        assert out.returncode == 0
        assert out.stdout.strip() == str(real)
    gone = subprocess.run(["sh", str(shim), "-e", "--", str(tmp_path / "nothing")],
                          capture_output=True, text=True)
    assert gone.returncode != 0 and gone.stdout == ""


def test_realpath_hook_keeps_a_real_one(tmp_path):
    dest = tmp_path / "initramfs"
    (dest / "usr/bin").mkdir(parents=True)
    (dest / "usr/bin/realpath").write_text("busybox\n")
    subprocess.run(["sh", str(HOOK)], env=dict(os.environ, DESTDIR=str(dest)), check=True)
    assert (dest / "usr/bin/realpath").read_text() == "busybox\n"


GREETER = BOOT / "raye-greeter-back"
DROPIN = BOOT / "user-runtime-dir@.service.d" / "raye-greeter-back.conf"


def greeter_back(tmp_path, sessions, state="running", sddm="active", uid="1001",
                 front="tty2", getty=()):
    """Runs raye-greeter-back with fake loginctl and systemctl. sessions:
    {id: {"Seat":, "Class":, "State":, "Type":}}; front: the VT in front;
    getty: the VTs a getty runs on. Returns the commands that acted."""
    log = tmp_path / "calls"
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    rows = "\n".join(f"{i} 1 u {s['Seat']} 1 {s['Class']} tty1 no -" for i, s in sessions.items())
    show = "\n".join(f'  {i},{k}) echo "{v}" ;;'
                     for i, s in sessions.items() for k, v in s.items())
    (bin_ / "loginctl").write_text(f"""#!/bin/sh
case "$1" in
list-sessions) printf '%s\\n' "{rows}" ;;
show-session)
    while [ $# -gt 0 ]; do case "$1" in -p) p=$2; shift ;; -*|show-session) ;; *) id=$1 ;; esac; shift; done
    case "$id,$p" in
{show}
    esac ;;
*) echo "loginctl $*" >> "{log}" ;;
esac
""")
    (bin_ / "systemctl").write_text(f"""#!/bin/sh
case "$1" in
is-system-running) echo {state} ;;
is-active)
    case "$*" in
    *sddm*) [ "{sddm}" = active ] ;;
    *) for u in "$@"; do case " {' '.join(getty)} " in *" ${{u#*@}} "*) exit 0 ;; esac; done; exit 3 ;;
    esac ;;
*) echo "systemctl $*" >> "{log}" ;;
esac
""")
    (bin_ / "id").write_text('#!/bin/sh\necho 103\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    tty0 = tmp_path / "sys" / "class" / "tty" / "tty0"
    tty0.mkdir(parents=True, exist_ok=True)
    (tty0 / "active").write_text(front + "\n")
    env = dict(os.environ, PATH=f"{bin_}:/usr/bin:/bin", RAYE_GREETER_WAIT="1",
               RAYE_GREETER_SYS=str(tmp_path / "sys"))
    r = subprocess.run(["sh", str(GREETER), uid], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return log.read_text().splitlines() if log.exists() else []


def test_greeter_comes_back_after_terminate_user(tmp_path):
    # sddm took the killed helper for a failed password: seat0 is empty
    assert greeter_back(tmp_path, {}) == ["systemctl restart sddm.service"]


def test_greeter_already_there_is_left_alone(tmp_path):
    s = {"5": {"Seat": "seat0", "Class": "greeter", "State": "online"}}
    assert greeter_back(tmp_path, s) == []


def test_another_active_session_is_left_alone(tmp_path):
    s = {"7": {"Seat": "seat0", "Class": "user", "State": "active"}}
    assert greeter_back(tmp_path, s) == []


def test_other_user_still_signed_in_gets_the_screen(tmp_path):
    # restarting sddm would end that session too
    s = {"7": {"Seat": "seat0", "Class": "user", "State": "online", "Type": "wayland"},
         "8": {"Seat": "", "Class": "manager", "State": "active"}}
    assert greeter_back(tmp_path, s) == ["loginctl activate 7"]


def test_text_console_left_open_does_not_take_the_screen(tmp_path):
    # an admin signed in on tty3 while the desktop was killed
    s = {"5": {"Seat": "seat0", "Class": "user", "State": "online", "Type": "tty"}}
    assert greeter_back(tmp_path, s) == ["systemctl restart sddm.service"]


def test_person_at_a_text_console_keeps_it(tmp_path):
    # signed out of tty3: its getty is in front, the desktop stays behind
    s = {"7": {"Seat": "seat0", "Class": "user", "State": "online", "Type": "wayland"}}
    assert greeter_back(tmp_path, s, front="tty3", getty=("tty3.service",)) == []
    assert greeter_back(tmp_path, s, front="tty3") == ["loginctl activate 7"]


def test_nothing_during_shutdown_or_without_sddm(tmp_path):
    assert greeter_back(tmp_path, {}, state="stopping") == []
    assert greeter_back(tmp_path, {}, sddm="inactive") == []


def test_the_greeter_user_itself_is_ignored(tmp_path):
    # its runtime dir goes away at every sign-in
    assert greeter_back(tmp_path, {}, uid="103") == []


def test_dropin_starts_the_check_without_waiting():
    text = DROPIN.read_text()
    line = next(li for li in text.splitlines() if li.startswith("ExecStopPost="))
    # "-": a failure must never hold the user's teardown; --no-block: the
    # check waits a few seconds and must not delay it either
    assert line.startswith("ExecStopPost=-") and "--no-block" in line
    assert "raye-greeter-back@%i.service" in line
    unit = (BOOT / "raye-greeter-back@.service").read_text()
    assert "Conflicts=shutdown.target" in unit
    assert "ExecStart=/usr/libexec/raye-greeter-back %i" in unit
    assert "[Install]" not in unit
