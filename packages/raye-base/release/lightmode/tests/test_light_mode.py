# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-light-mode with made-up memory sizes and stand-in KDE tools."""
import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "raye-light-mode"
SERVICE = HERE.parent / "raye-light-mode.service"

loader = importlib.machinery.SourceFileLoader("raye_light_mode", str(SCRIPT))
spec = importlib.util.spec_from_loader("raye_light_mode", loader)
lm = importlib.util.module_from_spec(spec)
loader.exec_module(lm)

GIB_KIB = 1024 * 1024

# a config store the stand-in kreadconfig6/kwriteconfig6 share: one
# "file|group|key=value" line per key, and every other tool logs its call
STUBS = {
    "kreadconfig6": r"""
        f=; g=; k=
        while [ $# -gt 0 ]; do case $1 in --file) f=$2; shift ;; --group) g=$2; shift ;; --key) k=$2; shift ;; esac; shift; done
        grep -F "$f|$g|$k=" "$STORE" 2>/dev/null | tail -n 1 | sed 's/^[^=]*=//'
    """,
    "kwriteconfig6": r"""
        f=; g=; k=; del=; v=
        while [ $# -gt 0 ]; do case $1 in --file) f=$2; shift ;; --group) g=$2; shift ;; --key) k=$2; shift ;;
            --delete) del=1 ;; --notify) ;; *) v=$1 ;; esac; shift; done
        touch "$STORE"; grep -vF "$f|$g|$k=" "$STORE" > "$STORE.new"; mv "$STORE.new" "$STORE"
        [ -n "$del" ] || echo "$f|$g|$k=$v" >> "$STORE"
    """,
}
LOGGED = ("notify-send", "systemd-run", "dbus-send", "balooctl6", "raye-settings")


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.bin = t / "bin"
        self.bin.mkdir()
        self.store = t / "store"
        self.log = t / "log"
        for name, body in STUBS.items():
            self._stub(name, textwrap.dedent(body))
        for name in LOGGED:
            self._stub(name, 'echo "%s $*" >> "$LOG"\n' % name)
        self.env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "STORE": str(self.store), "LOG": str(self.log),
                    "HOME": str(t / "home"), "XDG_STATE_HOME": str(t / "state"), "LANG": "en_US.UTF-8"}
        self._old_env = dict(os.environ)
        os.environ.update(self.env)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        self.tmp.cleanup()

    def _stub(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(0o755)

    def keys(self):
        if not self.store.exists():
            return {}
        return dict(line.split("=", 1) for line in self.store.read_text().splitlines())

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_a_2_gb_pc_gets_light_mode_once(self):
        self.assertEqual(lm.session(self.env, int(1.9 * GIB_KIB)), "light effects indexing")
        k = self.keys()
        self.assertEqual(k["kdeglobals|KDE|AnimationDurationFactor"], "0")
        self.assertEqual(k["kwinrc|Plugins|blurEnabled"], "false")
        self.assertEqual(k["kdeglobals|Raye|TransparencyEffects"], "false")
        self.assertEqual(k["rayerc|Common|ShadowSize"], "ShadowNone")
        # Settings then reads "Let Raye choose", the choice of a slow PC
        self.assertEqual(k["kdeglobals|Raye|VisualEffectsMode"], "auto")
        self.assertEqual(k["baloofilerc|Basic Settings|Indexing-Enabled"], "false")
        self.assertIn("balooctl6 disable", self.calls())
        self.assertIn("notify-send", self.calls())
        self.assertIn("2 GB of memory", self.calls())
        self.assertIn("raye-settings --page system/performance", self.calls())
        # the second sign-in changes nothing, even if the person turned things back on
        self.store.unlink()
        self.log.unlink()
        self.assertEqual(lm.session(self.env, int(1.9 * GIB_KIB)), "already")
        self.assertEqual(self.keys(), {})
        self.assertEqual(self.calls(), "")

    def test_a_4_gb_pc_counts_as_little_memory(self):
        # what a "4 GB" PC reports once the firmware and the GPU took their share
        self.assertTrue(lm.is_low(3_900_000))
        self.assertTrue(lm.session(self.env, 3_900_000).startswith("light"))

    def test_8_gb_and_more_is_never_touched(self):
        self.assertFalse(lm.is_low(8 * GIB_KIB))
        self.assertEqual(lm.session(self.env, 8 * GIB_KIB), "normal")
        self.assertEqual(self.keys(), {})
        self.assertEqual(self.calls(), "")

    def test_a_choice_the_person_made_stays(self):
        self.store.write_text("kdeglobals|Raye|VisualEffectsMode=appearance\n"
                              "baloofilerc|Basic Settings|Indexing-Enabled=true\n")
        self.assertEqual(lm.session(self.env, 2 * GIB_KIB), "light none")
        self.assertEqual(self.keys()["kdeglobals|Raye|VisualEffectsMode"], "appearance")
        self.assertNotIn("kwinrc|Plugins|blurEnabled", self.keys())
        # nothing changed: nothing to say
        self.assertNotIn("notify-send", self.calls())

    def test_unreadable_memory_decides_nothing(self):
        self.assertEqual(lm.session(self.env, 0), "unknown")
        self.assertFalse(lm.state_file(self.env).exists())

    def test_the_notice_speaks_french(self):
        env = dict(self.env, LANG="fr_CA.UTF-8")
        lm.session(env, 2 * GIB_KIB)
        self.assertIn("Mode léger activé", self.calls())
        self.assertIn("2 Go de mémoire", self.calls())


class Generator(unittest.TestCase):
    def test_a_slow_pc_defers_the_store_at_boot(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(lm.generate("system", d, 2 * GIB_KIB), ["raye-store-catalog.timer"])
            text = pathlib.Path(d, "raye-store-catalog.timer.d", lm.DROPIN).read_text()
            # the stock 2 min is reset, not added to
            self.assertIn("OnBootSec=\nOnBootSec=20min", text)

    def test_a_slow_pc_defers_the_windows_space_after_sign_in(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(sorted(lm.generate("user", d, 2 * GIB_KIB)),
                             ["raye-store-autoupdate.timer", "raye-windows-prepare.timer"])
            text = pathlib.Path(d, "raye-windows-prepare.timer.d", lm.DROPIN).read_text()
            self.assertIn("OnStartupSec=\nOnStartupSec=20min", text)
            # the Store's app updates are a user timer (store CMakeLists: store_user_units)
            upd = pathlib.Path(d, "raye-store-autoupdate.timer.d", lm.DROPIN).read_text()
            self.assertIn("Persistent=false", upd)

    def test_a_normal_pc_gets_no_drop_in(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(lm.generate("system", d, 16 * GIB_KIB), [])
            self.assertEqual(os.listdir(d), [])

    def test_started_as_a_generator_it_writes_and_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            gen = pathlib.Path(d, "system-generators")
            gen.mkdir()
            (gen / "raye-light-mode").symlink_to(SCRIPT)
            mem = pathlib.Path(d, "meminfo")
            mem.write_text("MemTotal:        2000000 kB\nMemFree: 1 kB\n")
            out = pathlib.Path(d, "out")
            out.mkdir()
            r = subprocess.run([sys.executable, str(gen / "raye-light-mode"), str(out), str(out), str(out)],
                               env={"RAYE_MEMINFO": str(mem), "PATH": "/usr/bin:/bin"},
                               capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
            self.assertTrue((out / "raye-store-catalog.timer.d" / lm.DROPIN).exists())

    def test_check_says_low_or_normal(self):
        with tempfile.TemporaryDirectory() as d:
            mem = pathlib.Path(d, "meminfo")
            for kib, word, rc in ((2000000, "low", 0), (16000000, "normal", 1)):
                mem.write_text("MemTotal:  %d kB\n" % kib)
                r = subprocess.run([sys.executable, str(SCRIPT), "check"], env={"RAYE_MEMINFO": str(mem)},
                                   capture_output=True, text=True)
                self.assertEqual((r.returncode, r.stdout.split()[0]), (rc, word))


class Unit(unittest.TestCase):
    def test_the_user_unit_runs_once_per_account_in_the_session(self):
        text = SERVICE.read_text()
        self.assertIn("ExecStart=/usr/libexec/raye-light-mode session", text)
        self.assertIn("ConditionPathExists=!%S/raye/light-mode", text)
        self.assertIn("WantedBy=graphical-session.target", text)

    def test_the_same_line_as_settings_draws(self):
        # Settings > Performance options: PerformanceSettings::lowMemoryKiB
        self.assertEqual(lm.LOW_MEMORY_KIB, 4000 * 1024)



class Packaging(unittest.TestCase):
    ROOT = HERE.parents[2]

    def test_shipped_as_a_program_a_user_unit_and_two_generators(self):
        paths = (self.ROOT / "debian/raye-release-paths").read_text()
        self.assertRegex(paths, r"raye-desktop\s+release/lightmode/raye-light-mode\s+usr/libexec/raye-light-mode\n")
        self.assertRegex(paths, r"raye-desktop\s+release/lightmode/raye-light-mode.service\s+"
                                r"usr/lib/systemd/user/raye-light-mode.service\n")
        links = (self.ROOT / "debian/raye-desktop.links").read_text().split("\n")
        for kind in ("system", "user"):
            self.assertIn("usr/libexec/raye-light-mode usr/lib/systemd/%s-generators/raye-light-mode" % kind, links)

    def test_the_build_runs_these_tests(self):
        self.assertIn("unittest discover -s release/lightmode/tests", (self.ROOT / "debian/rules").read_text())


if __name__ == "__main__":
    unittest.main()
