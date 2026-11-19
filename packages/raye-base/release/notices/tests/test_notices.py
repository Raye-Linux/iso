"""System notices in Raye's words: when each one shows, and what it says."""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest

NOTICES = pathlib.Path(__file__).resolve().parent.parent
PATHS = NOTICES.parent.parent / "debian" / "raye-release-paths"
sys.dont_write_bytecode = True


def load():
    loader = importlib.machinery.SourceFileLoader("raye_notices", str(NOTICES / "raye-notices"))
    spec = importlib.util.spec_from_loader("raye_notices", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


rn = load()
GIB = 1024 ** 3
MIB = 1024 ** 2


def prop(value, kind="u"):
    return json.dumps({"type": kind, "data": value})


class Words(unittest.TestCase):
    def test_both_languages_have_the_same_words_and_blanks(self):
        self.assertEqual(set(rn.WORDS["en"]), set(rn.WORDS["fr"]))
        blanks = re.compile(r"{(\w+)}")
        for key, text in rn.WORDS["en"].items():
            self.assertEqual(set(blanks.findall(text)), set(blanks.findall(rn.WORDS["fr"][key])), key)

    def test_french_differs_and_no_layer_is_named(self):
        for key, text in rn.WORDS["en"].items():
            self.assertNotRegex(text + rn.WORDS["fr"][key], r"KDE|Plasma|UDisks|UPower|NetworkManager|SMART", key)
        self.assertNotEqual(rn.WORDS["en"]["low_disk_title"], rn.WORDS["fr"]["low_disk_title"])

    def test_language_comes_from_the_session(self):
        self.assertEqual(rn.language({"LANG": "fr_CA.UTF-8"}), "fr")
        self.assertEqual(rn.language({"LANGUAGE": "fr:en", "LANG": "en_US.UTF-8"}), "fr")
        self.assertEqual(rn.language({"LANG": "en_CA.UTF-8"}), "en")
        self.assertEqual(rn.language({"LANG": "de_DE.UTF-8"}), "en")
        self.assertEqual(rn.language({}), "en")


class Disk(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(rn.disk_level(50 * GIB, 100 * GIB), 0)
        self.assertEqual(rn.disk_level(4 * GIB, 100 * GIB), 1)      # under 5 %
        self.assertEqual(rn.disk_level(3 * GIB, 30 * GIB), 0)       # 10 % of a small disk
        self.assertEqual(rn.disk_level(1 * GIB, 16 * GIB), 1)       # under 2 GiB
        self.assertEqual(rn.disk_level(400 * MIB, 100 * GIB), 2)
        self.assertEqual(rn.disk_level(0, 0), 0)                    # a pseudo file system

    def test_notice_offers_to_clean_up(self):
        got = rn.disk_conditions(lambda p: (1 * GIB, 100 * GIB, 7), rn.WORDS["en"], ["/", "/home"])
        self.assertEqual(len(got), 1, "the same file system is one notice")
        self.assertEqual(got[0].level, 1)
        self.assertIn("1.0", got[0].body)
        self.assertEqual(got[0].actions[0][2], rn.OPEN_STORAGE)


class Battery(unittest.TestCase):
    def test_only_on_battery_and_below_warning(self):
        w = rn.WORDS["en"]
        self.assertEqual(rn.battery_conditions(dict(present=False, state=2, warning=4, percent=3), w), [])
        self.assertEqual(rn.battery_conditions(dict(present=True, state=1, warning=4, percent=3), w), [])
        self.assertEqual(rn.battery_conditions(dict(present=True, state=2, warning=1, percent=60), w), [])
        low = rn.battery_conditions(dict(present=True, state=2, warning=3, percent=9), w)
        self.assertEqual(low[0].level, 1)
        self.assertIn("9", low[0].body)
        critical = rn.battery_conditions(dict(present=True, state=2, warning=4, percent=3), w)
        self.assertEqual(critical[0].level, 2)
        self.assertEqual(rn.battery_conditions(dict(present=True, state=2, warning=5, percent=1), w)[0].level, 2)


class Health(unittest.TestCase):
    OBJECTS = {"type": "a{oa{sa{sv}}}", "data": [{
        "/org/freedesktop/UDisks2/drives/good": {
            "org.freedesktop.UDisks2.Drive": {"Model": {"type": "s", "data": "Fine"}, "Vendor": {"type": "s", "data": ""}},
            "org.freedesktop.UDisks2.Drive.Ata": {"SmartFailing": {"type": "b", "data": False}}},
        "/org/freedesktop/UDisks2/drives/bad": {
            "org.freedesktop.UDisks2.Drive": {"Model": {"type": "s", "data": "Dying"}, "Vendor": {"type": "s", "data": "ACME"}},
            "org.freedesktop.UDisks2.Drive.Ata": {"SmartFailing": {"type": "b", "data": True}}},
        "/org/freedesktop/UDisks2/block_devices/vda": {"org.freedesktop.UDisks2.Block": {}},
        "/org/freedesktop/UDisks2/drives/nvme_bad": {
            "org.freedesktop.UDisks2.Drive": {"Model": {"type": "s", "data": "Fast"}, "Vendor": {"type": "s", "data": ""}}},
        "/org/freedesktop/UDisks2/block_devices/nvme0": {
            "org.freedesktop.UDisks2.NVMe.Controller": {
                "SmartCriticalWarning": {"type": "as", "data": ["spare", "temperature"]}},
            "org.freedesktop.UDisks2.Block": {"Drive": {"type": "o", "data": "/org/freedesktop/UDisks2/drives/nvme_bad"}}},
    }]}

    def test_failing_drives_are_named_and_healthy_ones_are_quiet(self):
        got = rn.health_conditions(self.OBJECTS, rn.WORDS["en"])
        self.assertEqual(sorted(n.key for n in got), ["health:bad", "health:nvme_bad"])
        bodies = " ".join(n.body for n in got)
        self.assertIn("ACME Dying", bodies)
        self.assertIn("Fast", bodies)
        self.assertNotIn("Fine", bodies)

    def test_nothing_read_is_not_an_alarm(self):
        self.assertEqual(rn.health_conditions(None, rn.WORDS["en"]), [])
        self.assertEqual(rn.health_conditions({"data": []}, rn.WORDS["en"]), [])


class Portal(unittest.TestCase):
    def test_only_a_portal_asks_to_sign_in(self):
        w = rn.WORDS["en"]
        self.assertEqual(rn.portal_conditions(4, "Cafe", w), [])
        self.assertEqual(rn.portal_conditions(1, "Cafe", w), [])
        self.assertEqual(rn.portal_conditions(None, "", w), [])
        got = rn.portal_conditions(2, "Cafe", w)
        self.assertIn("Cafe", got[0].title)
        self.assertEqual(got[0].actions[0][2], rn.OPEN_PORTAL)


class Monitor(unittest.TestCase):
    def notice(self, level=1):
        return rn.Notice("k", level, "App", "icon", "Title", "Body", [])

    def test_one_notice_until_it_gets_worse_or_clears(self):
        sent = []
        mon = rn.Monitor(sent.append)
        mon.update("disk", [self.notice()])
        mon.update("disk", [self.notice()])
        self.assertEqual(len(sent), 1, "no repeat")
        mon.update("disk", [self.notice(2)])
        self.assertEqual(len(sent), 2, "worse says so")
        mon.update("disk", [self.notice(1)])
        self.assertEqual(len(sent), 2, "better says nothing")
        mon.update("disk", [])
        mon.update("disk", [self.notice()])
        self.assertEqual(len(sent), 3, "back again says so")

    def test_a_group_clears_only_its_own(self):
        sent = []
        mon = rn.Monitor(sent.append)
        mon.update("disk", [rn.Notice("a", 1, "", "", "", "", [])])
        mon.update("battery", [])
        mon.update("disk", [rn.Notice("a", 1, "", "", "", "", [])])
        self.assertEqual(len(sent), 1)


class State(unittest.TestCase):
    """One look a minute from a timer: what was said lives in a file."""

    def look(self, state, notices, session="boot/3", cleared=None):
        sent = []
        new = rn.look(state, session, lambda wanted: notices, sent.append,
                      lambda: cleared.append(1) if cleared is not None else None)
        return new, sent

    def test_nothing_is_said_twice_across_looks(self):
        disk = [rn.Notice("d", 1, "", "", "", "", [])]
        state, sent = self.look(None, {"disk": disk})
        self.assertEqual(len(sent), 1)
        state = json.loads(json.dumps(state))   # through the file
        state, sent = self.look(state, {"disk": disk})
        self.assertEqual(sent, [])
        state, sent = self.look(state, {"disk": [rn.Notice("d", 2, "", "", "", "", [])]})
        self.assertEqual(len(sent), 1, "worse says so")

    def test_a_new_session_starts_fresh_and_clears_the_restart_mark(self):
        disk = [rn.Notice("d", 1, "", "", "", "", [])]
        cleared = []
        state, _ = self.look(None, {"disk": disk}, cleared=cleared)
        self.assertEqual(len(cleared), 1)
        _, sent = self.look(state, {"disk": disk}, cleared=cleared)
        self.assertEqual(len(cleared), 1, "once a session")
        _, sent = self.look(state, {"disk": disk}, session="boot/4", cleared=cleared)
        self.assertEqual(len(sent), 1, "said again at the next sign-in")
        self.assertEqual(len(cleared), 2)

    def test_drives_are_read_every_thirty_looks(self):
        groups = []
        state = None
        for _ in range(61):
            state = rn.look(state, "s", lambda wanted: {}, lambda n: None, lambda: None,
                            groups=groups.append)
        self.assertEqual(groups.count("health"), 3)
        self.assertEqual(groups.count("disk"), 61)

    def test_file_round_trip_and_a_broken_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "x", "state.json")
            self.assertIsNone(rn.read_state(path))
            rn.write_state(path, {"session": "s", "tick": 2, "shown": [["disk", "d", 1]]})
            self.assertEqual(rn.read_state(path)["tick"], 2)
            path.write_text("{not json")
            self.assertIsNone(rn.read_state(path))


class Buttons(unittest.TestCase):
    def test_the_answer_waits_in_its_own_unit(self):
        notice = rn.Notice("disk:1", 1, "Storage", "drive-harddisk", "Low", "Body",
                           [("clean", "Clean up", rn.OPEN_STORAGE)])
        cmd = rn.waiter(notice)
        self.assertEqual(cmd[:2], ["systemd-run", "--user"])
        self.assertIn("--collect", cmd)
        self.assertNotIn("--wait", cmd[:cmd.index("--")])

    def test_the_chosen_button_runs_its_command(self):
        notice = rn.Notice("p", 1, "Network", "net", "Sign in to Café 'A'", "Body",
                           [("signin", "Sign in", ["sh", "-c", 'echo opened >> "$CALLS"'])])
        script = rn.waiter(notice)[-1]
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp, "bin")
            bindir.mkdir()
            log = pathlib.Path(tmp, "calls")
            for answer in ("", "signin"):
                stub = bindir / "notify-send"
                stub.write_text('#!/bin/sh\necho "notify-send $*" >> "$CALLS"\necho %s\n' % answer)
                stub.chmod(0o755)
                subprocess.run(["sh", "-c", script], env=dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin",
                                                              CALLS=str(log)), check=True, timeout=10)
            calls = log.read_text()
            self.assertEqual(calls.count("opened"), 1, calls)
            self.assertIn("--wait", calls)
            self.assertIn("Sign in to Café 'A'", calls)


class RestartMark(unittest.TestCase):
    def run_it(self, marked, this_boot):
        gone = []
        done = rn.clear_restart_mark(lambda: marked, lambda g, k: gone.append((g, k)), this_boot)
        return done, gone

    def test_cleared_after_a_restart(self):
        done, gone = self.run_it("boot-a", "boot-b")
        self.assertTrue(done)
        self.assertIn(("Start", "RestartNeeded"), gone)
        self.assertIn(("Power", "RestartNeededBoot"), gone)

    def test_kept_in_the_same_boot_and_when_nothing_is_known(self):
        for marked, boot in (("boot-a", "boot-a"), ("", "boot-b"), ("boot-a", "")):
            done, gone = self.run_it(marked, boot)
            self.assertFalse(done)
            self.assertEqual(gone, [])


class Live(unittest.TestCase):
    """The command itself, with stand-ins for busctl and notify-send on PATH."""

    def run_once(self, script, *args, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp, "bin")
            bindir.mkdir()
            log = pathlib.Path(tmp, "calls")
            for name, body in {"notify-send": 'echo "notify-send $*" >> "$CALLS"\n',
                               "kwriteconfig6": 'echo "kwriteconfig6 $*" >> "$CALLS"\n',
                               "busctl": 'exit 1\n'}.items():
                path = bindir / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(path.stat().st_mode | stat.S_IEXEC)
            full = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", CALLS=str(log), LANG="fr_CA.UTF-8",
                        LANGUAGE="", LC_ALL="", HOME=tmp, **(env or {}))
            res = subprocess.run([sys.executable, "-I", "-B", str(NOTICES / script), *args], env=full,
                                 capture_output=True, text=True, timeout=30)
            # a notice that is not waited for may still be on its way
            for _ in range(50):
                if log.exists() or res.returncode != 0:
                    break
                subprocess.run(["sleep", "0.1"])
            return res, log.read_text() if log.exists() else ""

    def test_each_look_leaves_its_state(self):
        with tempfile.TemporaryDirectory() as state_dir:
            state = pathlib.Path(state_dir, "notices.json")
            for _ in range(2):
                res, calls = self.run_once("raye-notices", "--state", str(state), "--paths",
                                           env={"XDG_SESSION_ID": "7"})
                self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(state.read_text())
            self.assertEqual(got["tick"], 2)
            self.assertTrue(got["session"].endswith("/7"))

    def test_nothing_answers_and_it_stays_quiet(self):
        # no disk to read and busctl fails: no battery, no drive, no network
        res, calls = self.run_once("raye-notices", "--once", "--paths")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(calls, "")

    def test_restart_notice_in_french_with_the_two_buttons(self):
        res, calls = self.run_once("raye-restart-notice", "--reason", "drivers", "--no-wait")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Redémarrage requis", calls)
        self.assertIn("Redémarrer maintenant", calls)
        self.assertIn("Plus tard", calls)
        # shown for the usual time: an expiry of one millisecond is no notice
        self.assertNotIn("--expire-time", calls)
        # the key Start's power button reads
        self.assertIn("--group Start --key RestartNeeded drivers", calls)
        self.assertIn("--group Power --key RestartNeededBoot", calls)

    def test_restart_notice_names_the_app(self):
        res, calls = self.run_once("raye-restart-notice", "--reason", "app", "--app", "Pilote X", "--no-wait")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Pilote X", calls)

    def answered(self, answer, *args, delay=0):
        """notify-send answers with a button; busctl and systemctl only log."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp, "bin")
            bindir.mkdir()
            log = pathlib.Path(tmp, "calls")
            for name, body in {"notify-send": f'sleep {delay}; echo "notify-send" >> "$CALLS"; echo {answer}\n',
                               "kwriteconfig6": "exit 0\n",
                               "busctl": 'echo "busctl $*" >> "$CALLS"\n',
                               "systemctl": 'echo "systemctl $*" >> "$CALLS"\n'}.items():
                path = bindir / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(path.stat().st_mode | stat.S_IEXEC)
            full = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", CALLS=str(log), LANG="en_US.UTF-8",
                        LANGUAGE="", LC_ALL="", HOME=tmp)
            res = subprocess.run([sys.executable, "-I", "-B", str(NOTICES / "raye-restart-notice"),
                                  "--reason", "drivers", *args], env=full,
                                 capture_output=True, text=True, timeout=3)
            for _ in range(10 * delay + 50):
                if "busctl" in (log.read_text() if log.exists() else "") or \
                        (answer != "now" and log.exists()):
                    break
                subprocess.run(["sleep", "0.1"])
            return res, log.read_text() if log.exists() else ""

    def test_restart_now_restarts_with_and_without_no_wait(self):
        for args in ((), ("--no-wait",)):
            res, calls = self.answered("now", *args)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("logoutAndReboot", calls, args)

    def test_later_does_not_restart(self):
        for args in ((), ("--no-wait",)):
            res, calls = self.answered("later", *args)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("notify-send", calls)
            self.assertNotIn("busctl", calls)
            self.assertNotIn("systemctl", calls)

    def test_a_caller_reading_the_output_is_not_held(self):
        # the user answers after five seconds; a caller that reads the
        # output must be back within three, or the run times out
        for args in ((), ("--no-wait",)):
            res, calls = self.answered("later", *args, delay=5)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("notify-send", calls)

    def test_an_unknown_reason_is_an_error_and_shows_nothing(self):
        res, calls = self.run_once("raye-restart-notice", "--reason", "nonsense", "--no-wait")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(calls, "")


class StockPopups(unittest.TestCase):
    # event names read from the installed 6.6 files
    EXPECTED = {
        "freespacenotifier.notifyrc": {"Event/freespacenotif": ""},
        "powerdevil.notifyrc": {"Event/lowbattery": "Sound", "Event/criticalbattery": "Sound"},
        "org.kde.kded.smart.notifyrc": {"Event/imminentDeviceFailure": ""},
    }

    def test_replaced_popups_are_off_and_sounds_stay(self):
        for name, events in self.EXPECTED.items():
            text = (NOTICES / name).read_text()
            for event, action in events.items():
                self.assertRegex(text, r"(?ms)^\[%s\]\nAction=%s$" % (re.escape(event), action), name)


class Shipped(unittest.TestCase):
    def test_nothing_is_optional_any_more(self):
        paths = PATHS.read_text()
        for line in ("usr/bin/raye-restart-notice", "usr/libexec/raye-notices",
                     "usr/lib/systemd/user/raye-notices.service"):
            self.assertRegex(paths, r"(?m)^raye-desktop\s+release/notices/\S+\s+%s\s*$" % line)
        self.assertRegex(paths, r"(?m)^raye-desktop\s+release/notices/\*\.notifyrc\s+etc/xdg\s*$")

    def test_the_first_look_comes_with_the_session_then_a_timer(self):
        unit = (NOTICES / "raye-notices.service").read_text()
        self.assertIn("WantedBy=graphical-session.target", unit)
        self.assertIn("ExecStart=/usr/libexec/raye-notices", unit)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("Wants=raye-notices.timer", unit)
        timer = (NOTICES / "raye-notices.timer").read_text()
        self.assertIn("OnUnitActiveSec=60", timer)
        self.assertIn("PartOf=graphical-session.target", timer)
        self.assertNotIn("[Install]", timer)
        self.assertRegex(PATHS.read_text(), r"(?m)^raye-desktop\s+release/notices/raye-notices.timer\s+"
                                            r"usr/lib/systemd/user/raye-notices.timer\s*$")


if __name__ == "__main__":
    unittest.main()
