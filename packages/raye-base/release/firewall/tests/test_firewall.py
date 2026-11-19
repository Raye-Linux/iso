"""Private and public networks, the dispatcher hook and the firewall setup."""

import os
import pathlib
import stat
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PROFILE = HERE / "raye-network-profile"
SETUP = HERE / "raye-firewall-setup"
HOOK = HERE / "before.init"
DISPATCH = HERE / "50-raye-network-profile"

# What nmcli answers, by its arguments. Each active connection is
# "uuid:type:device" plus its fields and the addresses of its device.
FAKE_NMCLI = r"""#!/bin/sh
d=$FAKE_DIR
echo "$*" >> "$d/nmcli-calls"
case "$*" in
"-t -f UUID,TYPE,DEVICE connection show --active") cat "$d/active" ;;
"-t -f connection.zone,802-11-wireless-security.key-mgmt connection show uuid "*)
    cat "$d/conn-$7" 2>/dev/null ;;
"-t -f IP4.ADDRESS device show "*) cat "$d/ip4-$6" 2>/dev/null ;;
"-t -f IP6.ADDRESS device show "*) cat "$d/ip6-$6" 2>/dev/null ;;
*) echo "nmcli $*" >> "$d/unknown"; exit 8 ;;
esac
"""

FAKE_TABLES = r"""#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_DIR/calls"
case "$(basename "$0")" in
*-restore) cat >> "$FAKE_DIR/restore-$(basename "$0")" ;;
esac
case "$*" in
"-n -L raye-profile-in") [ -e "$FAKE_DIR/running" ] ;;
"-C "*) [ -e "$FAKE_DIR/jumped" ] ;;
"-D "*) exit 1 ;;
esac
"""


class Fake:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.tool("nmcli", FAKE_NMCLI)
        for name in ("iptables", "ip6tables", "iptables-restore", "ip6tables-restore"):
            self.tool(name, FAKE_TABLES)
        (self.dir / "active").write_text("")
        self.nm_running = "1"

    def tool(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def link(self, uuid, kind, device, fields="", ip4="", ip6=""):
        with open(self.dir / "active", "a") as f:
            f.write(f"{uuid}:{kind}:{device}\n")
        (self.dir / f"conn-{uuid}").write_text(fields)
        (self.dir / f"ip4-{device}").write_text(ip4)
        (self.dir / f"ip6-{device}").write_text(ip6)

    def run(self, *args):
        env = dict(os.environ, FAKE_DIR=str(self.dir), PATH=f"{self.bin}:{os.environ['PATH']}",
                   RAYE_NP_STATE=str(self.dir / "state"), RAYE_NM_RUNNING=self.nm_running)
        return subprocess.run(["sh", str(PROFILE), *args], env=env, capture_output=True, text=True)

    def text(self, name):
        path = self.dir / name
        return path.read_text() if path.exists() else ""


def profile(zone, kind, key):
    return subprocess.run(["sh", str(PROFILE), "profile", zone, kind, key],
                          capture_output=True, text=True).stdout.strip()


class Profile(unittest.TestCase):
    def test_home_wifi_is_private(self):
        self.assertEqual(profile("", "802-11-wireless", "wpa-psk"), "private")
        self.assertEqual(profile("", "802-11-wireless", "sae"), "private")

    def test_ethernet_is_private(self):
        self.assertEqual(profile("", "802-3-ethernet", ""), "private")

    def test_open_wifi_is_public(self):
        self.assertEqual(profile("", "802-11-wireless", ""), "public")
        self.assertEqual(profile("", "802-11-wireless", "owe"), "public")

    def test_mobile_data_is_public(self):
        self.assertEqual(profile("", "gsm", ""), "public")

    def test_zone_wins(self):
        self.assertEqual(profile("public", "802-3-ethernet", ""), "public")
        self.assertEqual(profile("home", "802-11-wireless", ""), "private")


class Rules(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()

    def show(self):
        result = self.fake.run("show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.text("unknown"), "")
        return result.stdout

    def test_private_network_reaches_the_pc(self):
        self.fake.link("u1", "802-11-wireless", "wlp2s0", "connection.zone:\n802-11-wireless-security.key-mgmt:wpa-psk\n",
                       "IP4.ADDRESS[1]:192.168.1.23/24\n",
                       "IP6.ADDRESS[1]:2001:db8:1:2::5/64\nIP6.ADDRESS[2]:fe80::1/64\n")
        out = self.show()
        self.assertIn("-A raye-profile-in -i wlp2s0 -s 192.168.1.23/24 -j ACCEPT", out)
        self.assertIn("-A raye-profile-in -i wlp2s0 -s 2001:db8:1:2::5/64 -j ACCEPT", out)
        self.assertIn("-A raye-profile-in -i wlp2s0 -s fe80::1/64 -j ACCEPT", out)
        self.assertNotIn("DROP", out)

    def test_public_network_is_quiet(self):
        self.fake.link("u2", "802-11-wireless", "wlp2s0", "connection.zone:\n",
                       "IP4.ADDRESS[1]:10.20.0.9/16\n")
        out = self.show()
        self.assertIn("-A raye-profile-in -i wlp2s0 -p icmp --icmp-type echo-request -j DROP", out)
        self.assertIn("-A raye-profile-in -i wlp2s0 -p ipv6-icmp --icmpv6-type echo-request -j DROP", out)
        self.assertIn("-A raye-profile-out -o wlp2s0 -p udp -m multiport --dports 137,138,3702,5353,5355 -j DROP", out)
        self.assertNotIn("10.20.0.9", out)
        self.assertNotIn("-i wlp2s0 -s", out)

    def test_marked_public_wins_over_home_wifi(self):
        self.fake.link("u3", "802-11-wireless", "wlan0",
                       "connection.zone:public\n802-11-wireless-security.key-mgmt:wpa-psk\n",
                       "IP4.ADDRESS[1]:192.168.1.23/24\n")
        out = self.show()
        self.assertIn("-i wlan0 -p icmp", out)
        self.assertNotIn("192.168.1.23", out)

    def test_established_traffic_leaves_first(self):
        out = self.show()
        rules = [l for l in out.splitlines() if l.startswith("-A raye-profile-in")]
        self.assertEqual(rules[0], "-A raye-profile-in -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN")

    def test_virtual_machines_keep_their_network(self):
        out = self.show()
        self.assertIn("-A raye-profile-in -i virbr+ -j ACCEPT", out)
        self.assertIn("-A raye-profile-fwd -i virbr+ -j ACCEPT", out)
        self.assertIn("-A raye-profile-fwd -o virbr+ -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT", out)

    def test_vpn_plugin_line_is_left_out(self):
        self.fake.link("u4", "802-11-wireless", "wlp2s0", "", "IP4.ADDRESS[1]:10.20.0.9/16\n")
        with open(self.fake.dir / "active", "a") as f:
            f.write("u5:vpn:wlp2s0\n")
        (self.fake.dir / "conn-u5").write_text("connection.zone:home\n")
        out = self.show()
        self.assertNotIn("10.20.0.9", out)

    def test_odd_device_names_are_skipped(self):
        self.fake.link("u6", "802-3-ethernet", "-j ACCEPT", "", "IP4.ADDRESS[1]:1.2.3.4/8\n")
        self.fake.link("u7", "802-3-ethernet", "eth0;rm", "", "IP4.ADDRESS[1]:1.2.3.4/8\n")
        self.assertNotIn("1.2.3.4", self.show())

    def test_bad_address_is_skipped(self):
        self.fake.link("u8", "802-3-ethernet", "eth0", "", "IP4.ADDRESS[1]:1.2.3.4/8 -j ACCEPT\n")
        self.assertNotIn("1.2.3.4", self.show())

    def test_rules_are_small(self):
        self.fake.link("u1", "802-11-wireless", "wlp2s0", "802-11-wireless-security.key-mgmt:wpa-psk\n",
                       "IP4.ADDRESS[1]:192.168.1.23/24\n", "IP6.ADDRESS[1]:fe80::1/64\n")
        out = self.show()
        self.assertLessEqual(sum(l.startswith("-A") for l in out.splitlines()), 40)
        self.assertNotIn("LOG", out)


class Load(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.fake.link("u1", "802-3-ethernet", "eth0", "", "IP4.ADDRESS[1]:192.168.1.23/24\n")

    def test_apply_does_nothing_while_firewall_is_off(self):
        result = self.fake.run("apply")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.fake.text("restore-iptables-restore"), "")

    def test_apply_loads_when_firewall_runs(self):
        (self.fake.dir / "running").touch()
        self.fake.run("apply")
        loaded = self.fake.text("restore-iptables-restore")
        self.assertIn("-s 192.168.1.23/24", loaded)
        self.assertIn(":raye-profile-in - [0:0]", loaded)
        self.assertIn("COMMIT", self.fake.text("restore-ip6tables-restore"))

    def test_same_network_loads_once(self):
        (self.fake.dir / "running").touch()
        self.fake.run("apply")
        self.fake.run("apply")
        self.assertEqual(self.fake.text("restore-iptables-restore").count("COMMIT"), 1)

    def test_start_puts_chains_first(self):
        self.fake.run("start")
        calls = self.fake.text("calls")
        for chain, builtin in (("raye-profile-in", "INPUT"), ("raye-profile-out", "OUTPUT"),
                               ("raye-profile-fwd", "FORWARD")):
            self.assertIn(f"iptables -I {builtin} 1 -j {chain}", calls)
            self.assertIn(f"ip6tables -I {builtin} 1 -j {chain}", calls)

    def test_start_twice_keeps_one_jump(self):
        (self.fake.dir / "jumped").touch()
        self.fake.run("start")
        self.assertNotIn(" -I ", self.fake.text("calls"))

    def test_start_at_boot_does_not_ask_networkmanager(self):
        self.fake.nm_running = "0"
        (self.fake.bin / "systemctl").write_text("#!/bin/sh\nexit 3\n")
        (self.fake.bin / "systemctl").chmod(0o755)
        self.fake.run("start")
        loaded = self.fake.text("restore-iptables-restore")
        self.assertNotIn("192.168.1.23", loaded)
        self.assertIn("COMMIT", loaded)
        self.assertEqual(self.fake.text("nmcli-calls"), "")

    def test_stop_removes_chains(self):
        self.fake.run("stop")
        calls = self.fake.text("calls")
        self.assertIn("iptables -X raye-profile-in", calls)
        self.assertIn("ip6tables -X raye-profile-fwd", calls)


class Dispatcher(unittest.TestCase):
    def test_runs_on_network_changes_only(self):
        text = DISPATCH.read_text()
        for action in ("up", "down", "reapply", "dhcp4-change", "dhcp6-change"):
            self.assertIn(action, text)
        self.assertNotIn("connectivity-change", text)
        self.assertTrue(os.access(DISPATCH, os.X_OK))

    def test_hook_never_fails_ufw(self):
        result = subprocess.run(["/bin/sh", str(HOOK), "start"], capture_output=True,
                                env=dict(os.environ, PATH="/nonexistent"))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.access(HOOK, os.X_OK))


class Setup(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        for d in ("etc/ufw", "usr/share/ufw", "usr/share/raye/firewall", "var/lib/dpkg/info"):
            (self.root / d).mkdir(parents=True)
        self.conf = self.root / "etc/ufw/ufw.conf"
        self.conf.write_text("# /etc/ufw/ufw.conf\nENABLED=no\nLOGLEVEL=low\n")
        (self.root / "usr/share/ufw/before.init").write_text("#!/bin/sh\n# stock\n")
        (self.root / "etc/ufw/before.init").write_text("#!/bin/sh\n# stock\n")
        (self.root / "usr/share/raye/firewall/before.init").write_text(HOOK.read_text())
        (self.root / "var/lib/dpkg/info/ufw.list").write_text("")

    def run_setup(self, **env):
        return subprocess.run(["sh", str(SETUP)], env=dict(os.environ, RAYE_ROOT=str(self.root), **env),
                              capture_output=True, text=True)

    def age(self, path, seconds):
        t = time.time() - seconds
        os.utime(path, (t, t))

    def test_new_install_turns_it_on(self):
        self.run_setup()
        text = self.conf.read_text()
        self.assertIn("ENABLED=yes", text)
        self.assertIn("LOGLEVEL=off", text)
        self.assertTrue((self.root / "var/lib/raye/firewall-default").exists())

    def test_hook_takes_the_stock_ones_place(self):
        self.run_setup()
        hook = self.root / "etc/ufw/before.init"
        self.assertEqual(hook.read_text(), HOOK.read_text())
        self.assertTrue(hook.stat().st_mode & stat.S_IXUSR)

    def test_hook_written_by_hand_stays(self):
        (self.root / "etc/ufw/before.init").write_text("#!/bin/sh\n# mine\n")
        self.run_setup()
        self.assertIn("mine", (self.root / "etc/ufw/before.init").read_text())

    def test_turned_off_in_settings_stays_off(self):
        (self.root / "var/lib/raye").mkdir(parents=True)
        (self.root / "var/lib/raye/firewall-off").touch()
        self.run_setup()
        self.assertIn("ENABLED=no", self.conf.read_text())

    def test_turned_off_before_the_update_stays_off(self):
        self.age(self.root / "var/lib/dpkg/info/ufw.list", 30 * 86400)
        self.run_setup()
        self.assertIn("ENABLED=no", self.conf.read_text())

    def test_untouched_older_install_turns_on(self):
        self.age(self.root / "var/lib/dpkg/info/ufw.list", 30 * 86400)
        self.age(self.conf, 30 * 86400 - 60)
        self.run_setup()
        self.assertIn("ENABLED=yes", self.conf.read_text())

    def test_only_once(self):
        self.run_setup()
        self.conf.write_text("ENABLED=no\nLOGLEVEL=off\n")
        self.run_setup()
        self.assertIn("ENABLED=no", self.conf.read_text())

    def test_logging_left_alone_when_already_on(self):
        self.conf.write_text("ENABLED=yes\nLOGLEVEL=medium\n")
        self.run_setup()
        self.assertIn("LOGLEVEL=medium", self.conf.read_text())

    def test_running_system_asks_ufw(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        log = self.root / "log"
        (bin_dir / "ufw").write_text(f'#!/bin/sh\necho "ufw $*" >> {log}\n')
        (bin_dir / "ufw").chmod(0o755)
        self.run_setup(RAYE_FIREWALL_LIVE="1", PATH=f"{bin_dir}:{os.environ['PATH']}")
        calls = log.read_text()
        self.assertIn("ufw --force enable", calls)
        self.assertIn("ufw logging off", calls)

    def test_no_ufw_no_work(self):
        self.conf.unlink()
        self.assertEqual(self.run_setup().returncode, 0)
        self.assertFalse((self.root / "var/lib/raye/firewall-default").exists())


if __name__ == "__main__":
    unittest.main()
