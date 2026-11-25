"""raye-hw-drivers: a device the Raye kernel has no driver for in its tree
(a Broadcom BCM4360 Wi-Fi card, say) gets Raye's signed out-of-tree module
by itself, from the index kernel/oot builds. Never DKMS, never on Ubuntu's
kernel (the modules are built for the Raye kernel). Outside commands are
stubs on PATH that log what they were asked."""
import subprocess
from pathlib import Path

DRIVERS = Path(__file__).resolve().parents[1]
SCRIPT = DRIVERS / "raye-hw-drivers"
INDEX = DRIVERS / "raye-modules.index"
RAYE = "7.0.14-44r4-raye"
BCM4360 = "pci:v000014E4d000043A0sv0000106Bsd00000117bc02sc80i00"
INTEL_NIC = "pci:v00008086d00001533sv00008086sd00000001bc02sc00i00"


class PC:
    def __init__(self, tmp, devices=(BCM4360, INTEL_NIC), installed=""):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "log"
        self.log.write_text("")
        self.state = tmp / "state"
        self.sys = tmp / "sys"
        for i, alias in enumerate(devices):
            bus = alias.split(":", 1)[0]
            d = self.sys / "bus" / bus / "devices" / f"0000:0{i + 1}:00.0"
            d.mkdir(parents=True)
            (d / "modalias").write_text(alias + "\n")
        self.installed = tmp / "installed"
        self.installed.write_text(installed)
        log = f'echo "$(basename "$0") $*" >> {self.log}\n'
        for name in ("getent", "apt-get", "modprobe"):
            self.stub(name, "#!/bin/sh\n" + log + "exit 0\n")
        # dpkg-query -W -f=FORMAT PACKAGE: "ii" when PACKAGE is in "installed"
        self.stub("dpkg-query", "#!/bin/sh\n" + log +
                  f'for p; do :; done; grep -qx "$p" {self.installed} && echo "ii " || exit 1\n')

    def stub(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self, *args, release=RAYE, index=INDEX):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_DRIVERS_STATE": str(self.state),
               "RAYE_SYS": str(self.sys), "RAYE_UNAME_R": release, "RAYE_HW_INDEX": str(index)}
        return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def calls(self, name):
        return [l for l in self.log.read_text().splitlines() if l.split(" ", 1)[0] == name]

    def apt_installs(self):
        return [l for l in self.calls("apt-get") if " install " in l]


def test_script_is_valid_sh():
    assert subprocess.run(["sh", "-n", str(SCRIPT)]).returncode == 0


def test_the_index_ships_the_broadcom_cards_the_tree_cannot_drive():
    rows = [l.split("\t") for l in INDEX.read_text().splitlines() if l and not l.startswith("#")]
    assert ["pci:v000014E4d000043A0sv*sd*bc*sc*i*", "linux-modules-broadcom-sta-raye", "wl"] in rows
    for pattern, pkg, module in rows:
        assert pkg.startswith("linux-modules-") and pkg.endswith("-raye") and "dkms" not in pkg


def test_a_broadcom_card_gets_raye_s_signed_module_and_it_loads(tmp_path):
    pc = PC(tmp_path)
    assert pc.run("--needed").returncode == 0
    r = pc.run()
    assert r.returncode == 0, r.stderr
    [install] = pc.apt_installs()
    assert install.endswith("install -y -q --no-install-recommends linux-modules-broadcom-sta-raye")
    assert pc.calls("modprobe") == ["modprobe wl"]


def test_nothing_to_do_without_such_a_device_and_no_network_asked(tmp_path):
    pc = PC(tmp_path, devices=(INTEL_NIC,))
    assert pc.run("--needed").returncode == 1
    assert pc.run().returncode == 0
    assert pc.calls("apt-get") == [] and pc.calls("getent") == []


def test_already_installed_is_left_alone(tmp_path):
    pc = PC(tmp_path, installed="linux-modules-broadcom-sta-raye\n")
    assert pc.run("--needed").returncode == 1
    pc.run()
    assert pc.apt_installs() == []


def test_never_on_ubuntu_s_kernel(tmp_path):
    pc = PC(tmp_path)
    assert pc.run("--needed", release="7.0.0-44-generic").returncode == 1
    pc.run(release="7.0.0-44-generic")
    assert pc.apt_installs() == []


def test_never_a_dkms_package_even_if_an_index_names_one(tmp_path):
    bad = tmp_path / "bad.index"
    bad.write_text("pci:v000014E4d000043A0sv*sd*bc*sc*i*\tbroadcom-sta-dkms\twl\n"
                   "pci:v000014E4d000043A0sv*sd*bc*sc*i*\tlinux-modules-foo-dkms-raye\tfoo\n")
    pc = PC(tmp_path)
    assert pc.run("--needed", index=bad).returncode == 1
    pc.run(index=bad)
    assert pc.apt_installs() == []


def test_no_network_means_later(tmp_path):
    pc = PC(tmp_path)
    pc.stub("getent", "#!/bin/sh\nexit 2\n")
    assert pc.run().returncode == 75
    assert pc.apt_installs() == []


def test_a_failed_install_is_not_retried_at_every_start_but_settings_retries(tmp_path):
    pc = PC(tmp_path)
    pc.stub("apt-get", f'#!/bin/sh\necho "apt-get $*" >> {pc.log}\ncase "$*" in *install*) exit 100 ;; esac\n')
    assert pc.run().returncode == 1
    assert pc.run("--needed").returncode == 1
    pc.log.write_text("")
    pc.run("--again")
    assert len(pc.apt_installs()) == 1


def test_list_names_the_device_for_settings(tmp_path):
    pc = PC(tmp_path)
    r = pc.run("--list")
    assert r.stdout == "linux-modules-broadcom-sta-raye\twl\t0000:01:00.0\n"


def test_plugged_in_devices_and_the_settings_check_run_it():
    rule = (DRIVERS / "70-raye-hw-drivers.rules").read_text()
    assert 'ENV{SYSTEMD_WANTS}+="raye-hw-drivers.service"' in rule
    unit = (DRIVERS / "raye-hw-drivers.service").read_text()
    assert "ExecCondition=/usr/libexec/raye-hw-drivers --needed" in unit
    check = (DRIVERS / "raye-drivers-check.service").read_text()
    assert "ExecStart=-/usr/libexec/raye-hw-drivers --again" in check


def test_the_unit_is_never_started_by_the_package():
    # started from dpkg it would wait on apt's own lock
    paths = (DRIVERS.parents[1] / "debian" / "raye-release-paths").read_text()
    line = [l for l in paths.splitlines() if "raye-hw-drivers.service" in l][0]
    assert line.split()[-1] == "no-start"
