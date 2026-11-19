"""Network defaults: kernel settings, private Wi-Fi address, saved networks."""

import os
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
KEEP = HERE / "raye-wifi-keep-address"

FAKE_NMCLI = r"""#!/bin/sh
d=$FAKE_DIR
case "$*" in
"-t -f UUID,TYPE connection show") cat "$d/list" ;;
"-t -f 802-11-wireless.mode,802-11-wireless.cloned-mac-address connection show uuid "*) cat "$d/conn-$7" ;;
"connection modify uuid "*) echo "$*" >> "$d/modified" ;;
*) exit 8 ;;
esac
"""


def settings(name):
    values = {}
    for line in (HERE / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")):
            key, value = (part.strip() for part in line.split("=", 1))
            values[key] = value
    return values


class Kernel(unittest.TestCase):
    def test_no_redirects_or_source_routes(self):
        values = settings("90-raye-network.conf")
        for family in ("ipv4", "ipv6"):
            for scope in ("all", "default"):
                self.assertEqual(values[f"net.{family}.conf.{scope}.accept_redirects"], "0")
                self.assertEqual(values[f"net.{family}.conf.{scope}.accept_source_route"], "0")
        self.assertEqual(values["net.ipv4.conf.all.send_redirects"], "0")
        self.assertEqual(values["net.ipv4.tcp_rfc1337"], "1")

    def test_leaves_reverse_path_to_ubuntu(self):
        # rp_filter=2 comes from Ubuntu; strict (1) would break VPNs and two links
        self.assertFalse(any("rp_filter" in k for k in settings("90-raye-network.conf")))

    def test_no_martian_logging(self):
        self.assertFalse(any("log_martians" in k and v == "1" for k, v in settings("90-raye-network.conf").items()))


class WifiAddress(unittest.TestCase):
    def test_stable_per_network(self):
        text = (HERE / "60-raye-wifi-privacy.conf").read_text()
        self.assertIn("match-device=type:wifi", text)
        self.assertIn("wifi.cloned-mac-address=stable", text)
        self.assertNotIn("ethernet.cloned-mac-address", text)


class KeepAddress(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        nmcli = self.dir / "nmcli"
        nmcli.write_text(FAKE_NMCLI)
        nmcli.chmod(0o755)
        self.lines = []

    def saved(self, uuid, kind, mode="infrastructure", mac=""):
        self.lines.append(f"{uuid}:{kind}")
        (self.dir / f"conn-{uuid}").write_text(
            f"802-11-wireless.mode:{mode}\n802-11-wireless.cloned-mac-address:{mac}\n")

    def run_keep(self):
        (self.dir / "list").write_text("\n".join(self.lines) + "\n")
        env = dict(os.environ, FAKE_DIR=str(self.dir), RAYE_NMCLI=str(self.dir / "nmcli"))
        result = subprocess.run(["sh", str(KEEP)], env=env, capture_output=True, text=True)
        modified = self.dir / "modified"
        return result.returncode, modified.read_text() if modified.exists() else ""

    def test_saved_networks_keep_their_address(self):
        self.saved("home", "802-11-wireless")
        code, modified = self.run_keep()
        self.assertEqual(code, 0)
        self.assertIn("connection modify uuid home 802-11-wireless.cloned-mac-address permanent", modified)

    def test_chosen_address_stays(self):
        self.saved("cafe", "802-11-wireless", mac="random")
        self.saved("work", "802-11-wireless", mac="02:11:22:33:44:55")
        self.assertEqual(self.run_keep()[1], "")

    def test_hotspot_and_cable_left_out(self):
        self.saved("spot", "802-11-wireless", mode="ap")
        self.lines.append("cable:802-3-ethernet")
        self.assertEqual(self.run_keep()[1], "")

    def test_no_networkmanager_is_a_failure(self):
        env = dict(os.environ, RAYE_NMCLI="/nonexistent/nmcli")
        result = subprocess.run(["sh", str(KEEP)], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
