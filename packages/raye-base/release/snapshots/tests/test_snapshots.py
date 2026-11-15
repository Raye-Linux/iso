"""raye-snapshots-setup and raye-snapshots-daily, with a fake snapper."""

import os
import pathlib
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
SETUP = HERE / "raye-snapshots-setup"
DAILY = HERE / "raye-snapshots-daily"

FAKE_SNAPPER = """#!/bin/sh
echo "$*" >> "$SNAPPER_LOG"
case "$*" in
*--csvout\\ list*) printf 'number,date\\n0,\\n' ; cat "$SNAPPER_LIST" 2>/dev/null ;;
esac
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "root"
        bin_dir = pathlib.Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "snapper"
        fake.write_text(FAKE_SNAPPER)
        fake.chmod(0o755)
        self.log = pathlib.Path(self.tmp.name) / "snapper.log"
        self.list = pathlib.Path(self.tmp.name) / "list.csv"
        (self.root / "etc/snapper/configs").mkdir(parents=True)
        (self.root / "etc/snapper/configs/root").write_text("")
        (self.root / "etc/default").mkdir(parents=True)
        (self.root / "etc/default/snapper").write_text(
            'SNAPPER_CONFIGS="root"\nDISABLE_APT_SNAPSHOT="no"\n')
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "RAYE_SNAPSHOTS_ROOT": str(self.root),
                    "SNAPPER_LOG": str(self.log), "SNAPPER_LIST": str(self.list)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script):
        subprocess.run(["sh", str(script)], env=self.env, check=True)
        return self.log.read_text().splitlines() if self.log.exists() else []


class Setup(Base):
    def test_no_hourly_and_space_limits(self):
        calls = self.run_script(SETUP)
        config = next(c for c in calls if "set-config" in c)
        for word in ("TIMELINE_CREATE=no", "TIMELINE_LIMIT_HOURLY=0", "FREE_LIMIT=0.2",
                     "NUMBER_LIMIT=2-6", "NUMBER_LIMIT_IMPORTANT=2-4",
                     "TIMELINE_LIMIT_DAILY=2", "EMPTY_PRE_POST_CLEANUP=yes"):
            self.assertIn(word, config.split())
        self.assertFalse(any("create-config" in c for c in calls))
        # without quota groups snapper skips it: it would only mislead
        self.assertFalse([w for w in config.split() if w.startswith("SPACE_LIMIT=")])
        self.assertTrue((self.root / "var/lib/raye/snapshots-v3").exists())

    def test_creates_the_config_when_missing(self):
        (self.root / "etc/snapper/configs/root").unlink()
        calls = self.run_script(SETUP)
        self.assertIn("--no-dbus -c root create-config /", calls)

    def test_apt_pair_can_be_turned_off(self):
        self.run_script(SETUP)
        text = (self.root / "etc/default/snapper").read_text()
        self.assertIn('DISABLE_APT_SNAPSHOT="${DISABLE_APT_SNAPSHOT:-no}"', text)
        out = subprocess.run(["sh", "-c", f'. "{self.root}/etc/default/snapper"; echo $DISABLE_APT_SNAPSHOT'],
                             env={**os.environ, "DISABLE_APT_SNAPSHOT": "yes"},
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "yes")


class Daily(Base):
    def last_point(self, seconds_ago):
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - seconds_ago))
        self.list.write_text(f"7,{when}\n")

    def test_nothing_changed_no_point(self):
        (self.root / "etc/hostname").write_text("raye\n")
        old = time.time() - 7200
        os.utime(self.root / "etc/hostname", (old, old))
        for p in (self.root / "etc").rglob("*"):
            os.utime(p, (old, old))
        os.utime(self.root / "etc", (old, old))
        self.last_point(3600)
        calls = self.run_script(DAILY)
        self.assertFalse(any(" create " in f" {c} " for c in calls))
        self.assertTrue(any("cleanup timeline" in c for c in calls))

    def test_changed_settings_make_a_point(self):
        self.last_point(3600)
        (self.root / "etc/hostname").write_text("raye\n")
        calls = self.run_script(DAILY)
        made = [c for c in calls if " create " in f" {c} "]
        self.assertEqual(len(made), 1)
        self.assertIn("raye=daily", made[0])
        self.assertIn("-c timeline", made[0])

    def test_change_in_the_same_second_is_already_in_it(self):
        (self.root / "etc/hostname").write_text("raye\n")
        now = int(time.time()) - 60
        for path in [self.root / "etc", *(self.root / "etc").rglob("*")]:
            os.utime(path, (now + 0.5, now + 0.5))
        self.list.write_text(time.strftime("7,%Y-%m-%d %H:%M:%S\n", time.localtime(now)))
        calls = self.run_script(DAILY)
        self.assertFalse(any(" create " in f" {c} " for c in calls))

    def test_manual_points_are_sorted_before_cleanup(self):
        sort = pathlib.Path(self.tmp.name) / "sort"
        sort.write_text(f'#!/bin/sh\necho sort >> "{self.log}"\n')
        sort.chmod(0o755)
        self.env["RAYE_SNAPSHOTS_SORT"] = str(sort)
        calls = self.run_script(DAILY)
        self.assertLess(calls.index("sort"),
                        next(i for i, c in enumerate(calls) if "cleanup number" in c))

    def test_first_point_is_made(self):
        calls = self.run_script(DAILY)
        self.assertTrue(any(" create " in f" {c} " for c in calls))


if __name__ == "__main__":
    unittest.main()
