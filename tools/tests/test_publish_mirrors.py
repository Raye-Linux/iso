# SPDX-License-Identifier: GPL-3.0-or-later
"""publish-mirrors: one gesture sends the local tree to R2 and GitHub.

Both mirrors are tried, a failure of either one fails the sync and is
tried again, a refused tree goes nowhere. Nothing is sent: the tools are
replaced by a fake runner. Needs dpkg-deb, apt-ftparchive, gpg and gpgv.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import raye_publish as rp  # noqa: E402
from testkey import make_test_key  # noqa: E402
from test_publish_guard import fake_iso, load  # noqa: E402
from test_publish_repo import make_deb, missing  # noqa: E402

pr = load("publish_repo_m", "publish-repo")
pm = load("publish_mirrors_m", "publish-mirrors")


class Runner:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def __call__(self, cmd):
        self.calls.append(pathlib.Path(cmd[0]).name)
        code = 1 if pathlib.Path(cmd[0]).name in self.fail else 0
        return subprocess.CompletedProcess(cmd, code)


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class MirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.home, cls.keyring, sub = make_test_key(cls.tmp)
        cls.conf = dict(rp.settings(), GNUPGHOME=str(cls.home), SIGNING_KEY=sub)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                       env=dict(os.environ, GNUPGHOME=str(cls.home)))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.stage = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        self.debs = self.stage / "debs"
        self.debs.mkdir()
        make_deb(self.debs, "raye-demo", "1.0")
        pr.build(sorted(self.debs.glob("*.deb")), self.stage / "apt", self.conf, keyring=self.keyring)

    def sync(self, runner, **kw):
        return pm.sync(self.conf, self.stage, runner=runner, keyring=self.keyring, **kw)

    def test_both_mirrors_in_order_then_nothing_to_do(self):
        r = Runner()
        self.assertEqual(self.sync(r), [])
        self.assertEqual(r.calls, ["publish-r2", "publish-github"])
        again = Runner()
        self.assertEqual(self.sync(again, if_changed=True), [])
        self.assertEqual(again.calls, [])

    def test_one_failure_fails_the_sync_and_the_other_still_goes(self):
        r = Runner(fail={"publish-r2"})
        self.assertEqual(self.sync(r), ["r2"])
        self.assertEqual(r.calls, ["publish-r2", "publish-github"])
        # the next timer run tries again
        retry = Runner()
        self.assertEqual(self.sync(retry, if_changed=True), [])
        self.assertEqual(retry.calls, ["publish-r2", "publish-github"])

    def test_a_new_tree_is_sent_again(self):
        self.sync(Runner())
        make_deb(self.debs, "raye-demo", "1.1")
        pr.build(sorted(self.debs.glob("*_1.1_*.deb")), self.stage / "apt", self.conf,
                 keyring=self.keyring)
        r = Runner()
        self.sync(r, if_changed=True)
        self.assertEqual(r.calls, ["publish-r2", "publish-github"])

    def test_a_refused_tree_goes_nowhere(self):
        fake_iso(self.stage / "apt/pool/main/r/raye-demo/index.html")
        r = Runner()
        with self.assertRaisesRegex(rp.PublishError, "must not be published"):
            self.sync(r)
        self.assertEqual(r.calls, [])

    def test_the_main_fails_loudly(self):
        r = Runner(fail={"publish-github"})
        failed = self.sync(r)
        self.assertEqual(failed, ["github"])
        state = pm.read_state(self.stage / "mirrors.state")
        self.assertEqual(state["github"]["exit"], 1)
        self.assertIsNone(state["github"]["stamp"])


class UnitFileTests(unittest.TestCase):
    UNITS = TOOLS / "systemd"

    def test_path_unit_watches_the_stage_and_a_timer_catches_up(self):
        # publish-repo swaps the whole apt/ folder (rename): a watch on a file
        # inside it dies with the old folder, so the stage folder is watched
        path = (self.UNITS / "raye-publish-mirrors.path").read_text()
        self.assertIn("PathChanged=/srv/publish\n", path)
        self.assertNotIn("PathChanged=/srv/publish/apt", path)
        timer = (self.UNITS / "raye-publish-mirrors.timer").read_text()
        self.assertIn("OnUnitInactiveSec=", timer)
        service = (self.UNITS / "raye-publish-mirrors.service").read_text()
        self.assertIn("publish-mirrors --if-changed", service)
        self.assertNotIn(" all", service)


if __name__ == "__main__":
    unittest.main()
