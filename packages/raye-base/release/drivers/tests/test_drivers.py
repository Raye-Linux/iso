"""raye-drivers, raye-flatpak-gl and raye-gpu-driver-changed: the graphics
driver comes in by itself (the recommended one, once, and again when the
cards change), Flatpak games get NVIDIA's libraries for the driver that
runs, and a driver change gives the graphics ladder its normal level back.
Every outside command is a stub on PATH that logs what it was asked."""
import os
import subprocess
from pathlib import Path

DRIVERS = Path(__file__).resolve().parents[1]

DEVICES = """== /sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0 ==
modalias : pci:v000010DEd00001C03sv00001462sd00003287bc03sc00i00
vendor   : NVIDIA Corporation
model    : GP106 [GeForce GTX 1060 6GB]
driver   : nvidia-driver-580-server - distro non-free
driver   : nvidia-driver-595 - distro non-free recommended
driver   : nvidia-driver-580 - distro non-free
driver   : xserver-xorg-video-nouveau - distro free builtin
"""
LIST = """nvidia-driver-580-server, (kernel modules provided by linux-modules-nvidia-580-server-generic-hwe-26.04)
nvidia-driver-595, (kernel modules provided by linux-modules-nvidia-595-generic-hwe-26.04)
nvidia-driver-580, (kernel modules provided by linux-modules-nvidia-580-generic-hwe-26.04)
"""


class PC:
    def __init__(self, tmp, cards=(("0x10de", "0x1c03"),), installed=""):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "log"
        self.log.write_text("")
        self.state = tmp / "state"
        self.sys = tmp / "sys"
        self.set_cards(cards)
        self.installed = tmp / "installed"
        self.installed.write_text(installed)
        log = f'echo "$(basename "$0") $*" >> {self.log}\n'
        self.stub("getent", "#!/bin/sh\n" + log + "exit 0\n")
        self.stub("apt-get", "#!/bin/sh\n" + log + "exit 0\n")
        self.stub("ubuntu-drivers", "#!/bin/sh\n" + log +
                  f'case $1 in devices) cat {tmp}/devices ;; list) cat {tmp}/list ;; esac\n')
        (tmp / "devices").write_text(DEVICES)
        (tmp / "list").write_text(LIST)
        # dpkg-query -W -f=FORMAT PATTERN...: answers from the "installed" file
        self.stub("dpkg-query", "#!/bin/sh\n" + log + f'cat {self.installed}\n')

    def set_cards(self, cards):
        pci = self.sys / "bus" / "pci" / "devices"
        if pci.exists():
            for d in pci.iterdir():
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()
        pci.mkdir(parents=True, exist_ok=True)
        for i, (vendor, device) in enumerate(cards):
            d = pci / f"0000:0{i + 1}:00.0"
            d.mkdir()
            (d / "class").write_text("0x030000\n")
            (d / "vendor").write_text(vendor + "\n")
            (d / "device").write_text(device + "\n")
        net = pci / "0000:09:00.0"            # not a graphics card
        net.mkdir()
        (net / "class").write_text("0x020000\n")
        (net / "vendor").write_text("0x8086\n")
        (net / "device").write_text("0x1533\n")

    def stub(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def env(self, **extra):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_DRIVERS_STATE": str(self.state),
               "RAYE_SYS": str(self.sys)}
        env.update(extra)
        return env

    def drivers(self, *args, release="7.0.0-44-generic"):
        return subprocess.run(["sh", str(DRIVERS / "raye-drivers"), *args],
                              env=self.env(RAYE_UNAME_R=release),
                              capture_output=True, text=True)

    def calls(self, name):
        return [line for line in self.log.read_text().splitlines() if line.split(" ", 1)[0] == name]

    def apt_installs(self):
        return [line for line in self.calls("apt-get") if " install " in line]


# ------------------------------------------------------------ raye-drivers

def test_first_start_installs_the_recommended_driver_with_its_signed_modules(tmp_path):
    pc = PC(tmp_path)
    assert pc.drivers().returncode == 0
    [install] = pc.apt_installs()
    assert "nvidia-driver-595 linux-modules-nvidia-595-generic-hwe-26.04 nvidia-settings" in install
    # one driver, never the other branches it lists
    assert "580" not in install
    assert (pc.state / "drivers-done").exists()
    assert (pc.state / "drivers-hardware").read_text() == "0x10de:0x1c03\n"


def test_needed_until_done_then_skipped(tmp_path):
    pc = PC(tmp_path)
    assert pc.drivers("--needed").returncode == 0
    pc.drivers()
    assert pc.drivers("--needed").returncode == 1
    pc.log.write_text("")
    pc.drivers()
    assert pc.apt_installs() == []


def test_needed_asks_nothing_of_the_network_or_apt(tmp_path):
    pc = PC(tmp_path)
    pc.drivers("--needed")
    assert pc.calls("getent") == [] and pc.calls("apt-get") == [] and pc.calls("ubuntu-drivers") == []


def test_a_new_graphics_card_is_looked_at_again(tmp_path):
    pc = PC(tmp_path, cards=(("0x8086", "0x5917"),))
    (tmp_path / "devices").write_text("")
    pc.drivers()
    assert (pc.state / "drivers-done").read_text().strip() == "nothing to install"
    # the NVIDIA card comes in
    pc.set_cards((("0x8086", "0x5917"), ("0x10de", "0x1c03")))
    (tmp_path / "devices").write_text(DEVICES)
    assert pc.drivers("--needed").returncode == 0
    pc.drivers()
    [install] = pc.apt_installs()
    assert "nvidia-driver-595" in install
    assert pc.drivers("--needed").returncode == 1


def test_a_new_card_keeps_the_nvidia_driver_already_installed(tmp_path):
    pc = PC(tmp_path)
    pc.drivers()
    pc.installed.write_text("ii  nvidia-driver-580\n")
    pc.set_cards((("0x10de", "0x2484"),))
    pc.log.write_text("")
    assert pc.drivers().returncode == 0
    assert pc.apt_installs() == []
    assert pc.drivers("--needed").returncode == 1


def test_an_install_from_before_the_cards_were_kept_is_not_redone(tmp_path):
    pc = PC(tmp_path)
    pc.state.mkdir()
    (pc.state / "drivers-done").write_text("installed nvidia-driver-580\n")
    assert pc.drivers("--needed").returncode == 1
    assert (pc.state / "drivers-hardware").read_text() == "0x10de:0x1c03\n"
    assert pc.apt_installs() == []


def test_the_panel_file_still_brings_the_panel_alone(tmp_path):
    pc = PC(tmp_path)
    pc.state.mkdir()
    (pc.state / "drivers-done").write_text("installed\n")
    (pc.state / "drivers-hardware").write_text("0x10de:0x1c03\n")
    (pc.state / "drivers-nvidia-panel").write_text("")
    assert pc.drivers("--needed").returncode == 0
    pc.drivers()
    [install] = pc.apt_installs()
    assert install.endswith("nvidia-settings")


def test_nothing_on_the_raye_kernel_until_back_on_ubuntu_s(tmp_path):
    pc = PC(tmp_path)
    assert pc.drivers("--needed", release="7.0.14-raye").returncode == 1
    assert pc.drivers(release="7.0.14-raye").returncode == 0
    assert pc.apt_installs() == []
    assert not (pc.state / "drivers-done").exists()
    assert pc.drivers("--needed").returncode == 0
    pc.drivers()
    assert len(pc.apt_installs()) == 1


def test_service_runs_the_check_before_waiting_for_the_network():
    unit = (DRIVERS / "raye-drivers.service").read_text()
    assert "ExecCondition=/usr/libexec/raye-drivers --needed" in unit
    assert unit.index("ExecCondition=") < unit.index("ExecStartPre=")
    # the old conditions could never see a new card
    assert "ConditionPathExists" not in unit


# --------------------------------------------------------- raye-flatpak-gl

class Flatpak:
    def __init__(self, tmp, version="595.99.02", apps="com.valvesoftware.Steam\n",
                 runtimes="org.freedesktop.Platform\norg.freedesktop.Platform.GL.default\n"
                          "org.freedesktop.Platform.Compat.i386\norg.freedesktop.Platform.GL32.default\n",
                 online=True):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "log"
        self.log.write_text("")
        self.sys = tmp / "sys"
        if version is not None:
            (self.sys / "module" / "nvidia").mkdir(parents=True)
            (self.sys / "module" / "nvidia" / "version").write_text(version + "\n")
        (tmp / "apps").write_text(apps)
        (tmp / "runtimes").write_text(runtimes)
        log = f'echo "$(basename "$0") $*" >> {self.log}\n'
        self.stub("flatpak", "#!/bin/sh\n" + log +
                  f'case "$*" in *--app*) cat {tmp}/apps ;; *--runtime*) cat {tmp}/runtimes ;; esac\n')
        self.stub("getent", "#!/bin/sh\n" + log + ("exit 0\n" if online else "exit 2\n"))
        self.stub("nm-online", "#!/bin/sh\n" + log + "exit 0\n")

    def stub(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self, *args):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_SYS": str(self.sys)}
        return subprocess.run(["sh", str(DRIVERS / "raye-flatpak-gl"), *args], env=env,
                              capture_output=True, text=True)

    def installs(self):
        return [line for line in self.log.read_text().splitlines() if line.startswith("flatpak install")]


def test_steam_gets_both_halves_of_the_nvidia_libraries(tmp_path):
    f = Flatpak(tmp_path)
    assert f.run("--needed").returncode == 0
    assert f.run().returncode == 0
    assert f.installs() == [
        "flatpak install --system --noninteractive -y flathub "
        "runtime/org.freedesktop.Platform.GL.nvidia-595-99-02/x86_64/1.4",
        "flatpak install --system --noninteractive -y flathub "
        "runtime/org.freedesktop.Platform.GL32.nvidia-595-99-02/x86_64/1.4"]


def test_nothing_when_the_driver_s_extensions_are_in(tmp_path):
    f = Flatpak(tmp_path, runtimes="org.freedesktop.Platform.Compat.i386\n"
                                   "org.freedesktop.Platform.GL.nvidia-595-99-02\n"
                                   "org.freedesktop.Platform.GL32.nvidia-595-99-02\n")
    assert f.run("--needed").returncode == 1
    assert f.run().returncode == 0
    assert f.installs() == []


def test_a_changed_driver_needs_its_own_version(tmp_path):
    # the extension of the old driver does not count
    f = Flatpak(tmp_path, version="580.178.04",
                runtimes="org.freedesktop.Platform.GL.nvidia-595-99-02\n")
    f.run()
    assert f.installs() == ["flatpak install --system --noninteractive -y flathub "
                            "runtime/org.freedesktop.Platform.GL.nvidia-580-178-04/x86_64/1.4"]


def test_no_32_bit_half_without_a_32_bit_side(tmp_path):
    f = Flatpak(tmp_path, apps="org.mozilla.firefox\n", runtimes="org.freedesktop.Platform\n")
    f.run()
    assert len(f.installs()) == 1 and ".GL.nvidia-" in f.installs()[0]


def test_nothing_on_a_pc_without_nvidia_or_without_apps(tmp_path):
    (tmp_path / "a").mkdir()
    no_nvidia = Flatpak(tmp_path / "a", version=None)
    assert no_nvidia.run("--needed").returncode == 1
    assert no_nvidia.run().returncode == 0
    (tmp_path / "b").mkdir()
    no_apps = Flatpak(tmp_path / "b", apps="")
    assert no_apps.run("--needed").returncode == 1
    assert no_apps.run().returncode == 0
    assert no_nvidia.installs() == [] and no_apps.installs() == []


def test_offline_tries_again_later(tmp_path):
    f = Flatpak(tmp_path, online=False)
    assert f.run().returncode == 75
    assert f.installs() == []


def test_a_strange_version_is_never_turned_into_a_name(tmp_path):
    f = Flatpak(tmp_path, version="595.99.02;rm -rf /")
    assert f.run().returncode == 0
    assert f.installs() == []


def test_flatpak_service_never_holds_the_start():
    unit = (DRIVERS / "raye-flatpak-gl.service").read_text()
    assert "Type=exec" in unit
    assert "ExecCondition=/usr/libexec/raye-flatpak-gl --needed" in unit
    assert "SuccessExitStatus=75" in unit


# -------------------------------------------------- raye-gpu-driver-changed

class Apt:
    def __init__(self, tmp, installed=""):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "log"
        self.log.write_text("")
        self.state = tmp / "state" / "gpu-driver.state"
        self.installed = tmp / "installed"
        self.installed.write_text(installed)
        self.stub("dpkg-query", f"#!/bin/sh\ncat {self.installed}\n")
        self.stub("retry", f'#!/bin/sh\necho "retry $*" >> {self.log}\n')

    def stub(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_GPU_DRIVER_STATE": str(self.state),
               "RAYE_GRAPHICS_RETRY": str(self.bin / "retry")}
        return subprocess.run(["sh", str(DRIVERS / "raye-gpu-driver-changed")], env=env,
                              capture_output=True, text=True)

    def retries(self):
        return self.log.read_text().splitlines()


NV595 = "ii  nvidia-driver-595 595.99.02-0ubuntu0.26.04.1\nii  nvidia-utils-595 595.99.02-0ubuntu0.26.04.1\n"
NV580S = "ii  nvidia-driver-580-server 580.126.20-0ubuntu3\nii  nvidia-utils-580-server 580.126.20-0ubuntu3\n"


def test_switching_nvidia_driver_resets_the_ladder(tmp_path):
    a = Apt(tmp_path, NV595)
    a.run()
    a.log.write_text("")
    a.installed.write_text(NV580S)
    assert a.run().returncode == 0
    assert a.retries() == ["retry --driver"]


def test_unrelated_dpkg_runs_change_nothing(tmp_path):
    a = Apt(tmp_path, NV595)
    a.run()
    a.log.write_text("")
    a.run()
    a.run()
    assert a.retries() == []


def test_first_run_with_an_nvidia_driver_resets_once(tmp_path):
    # a 1.0 Beta PC the ladder left at nomodeset while its driver was being sorted out
    a = Apt(tmp_path, NV595)
    a.run()
    assert a.retries() == ["retry --driver"]


def test_first_run_without_nvidia_touches_nothing(tmp_path):
    a = Apt(tmp_path, "")
    a.run()
    assert a.retries() == []
    assert a.state.exists()


def test_removed_or_half_installed_packages_count_as_gone(tmp_path):
    a = Apt(tmp_path, NV595)
    a.run()
    a.log.write_text("")
    a.installed.write_text("rc  nvidia-driver-595 595.99.02-0ubuntu0.26.04.1\n")
    a.run()
    assert a.retries() == ["retry --driver"]


def test_the_hook_never_stops_apt(tmp_path):
    a = Apt(tmp_path, NV595)
    a.stub("retry", "#!/bin/sh\nexit 3\n")
    assert a.run().returncode == 0
    conf = (DRIVERS / "80raye-gpu-driver").read_text()
    assert "DPkg::Post-Invoke" in conf and "|| true" in conf
