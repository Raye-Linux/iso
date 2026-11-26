# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-crash-notice, on recorded pstore folders, with fake
notify-send, xdg-open and busctl.

    python3 -I -m unittest discover -s release/crash/tests
"""
import configparser
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
CRASH = HERE.parent
SCRIPT = CRASH / "raye-crash-notice"
UNIT = CRASH / "raye-crash-notice.service"
DROPIN = CRASH / "raye-pstore.conf"
LOCALE = CRASH / "locale"
FIXTURES = HERE / "fixtures" / "pstore"

SYSRQ = "1793461320/001"
OOPS = "7147483648123456"
RESTART = "1793470000/001"

sys.dont_write_bytecode = True


def load():
    loader = importlib.machinery.SourceFileLoader("raye_crash_notice", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


notice = load()


def write(path, text, mode=0o755):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


class Sandbox(unittest.TestCase):
    """A copy of the recorded pstore folder, a home, and fake commands."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="raye-crash-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pstore = self.tmp / "pstore"
        shutil.copytree(FIXTURES, self.pstore)
        self.summaries = self.tmp / "summaries"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.log = self.tmp / "calls.log"
        # what the fake notify-send answers: the action key, or nothing
        self.answer = self.tmp / "answer"
        self.answer.write_text("")
        self.fake("notify-send", 'cat "$ANSWER"')
        self.fake("xdg-open", "")
        self.fake("busctl", 'echo "b true"')
        self.boot = 1793461000
        self.archived(SYSRQ, 1793461400)
        self.archived(OOPS, 1793461400)
        self.archived(RESTART, 1793461400)

    def fake(self, name, body):
        write(self.bin / name,
              '#!/bin/sh\n'
              'printf "%s" "' + name + '" >> "$CALLS"\n'
              'for a in "$@"; do printf "\\t%s" "$a" >> "$CALLS"; done\n'
              'printf "\\n" >> "$CALLS"\n' + body + "\n")

    def archived(self, key, when):
        """Set when systemd-pstore archived a record (its files' mtime)."""
        folder = self.pstore / key
        for f in folder.iterdir():
            os.utime(f, (when, when))
        os.utime(folder, (when, when))

    def drop(self, *keys):
        for key in keys:
            shutil.rmtree(self.pstore / key.split("/")[0])

    def run_notice(self, lang="en_US.UTF-8", extra_env=None, *args):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "LANG": lang,
            "CALLS": str(self.log),
            "ANSWER": str(self.answer),
        }
        env.update(extra_env or {})
        cmd = [sys.executable, "-I", "-B", str(SCRIPT), "--pstore", str(self.pstore),
               "--summaries", str(self.summaries), "--boot-time", str(self.boot),
               "--wait-seconds", "1", *args]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)

    def collect(self):
        return notice.collect(self.pstore, self.summaries)

    def calls(self, name):
        if not self.log.exists():
            return []
        return [line.split("\t")[1:] for line in self.log.read_text().splitlines()
                if line.split("\t")[0] == name]

    def reports(self):
        folder = self.home / ".local/share/raye/crash-reports"
        return sorted(folder.glob("*.txt")) if folder.exists() else []


class ParseTest(unittest.TestCase):
    def text(self, key):
        return (FIXTURES / key / "dmesg.txt").read_text()

    def test_panic_from_sysrq(self):
        s = notice.parse_dmesg(self.text(SYSRQ))
        self.assertEqual(s["reason"], "Panic")
        self.assertEqual(s["stop_code"], "sysrq triggered crash")
        self.assertEqual(s["process"], "bash")
        self.assertEqual(s["kernel"], "7.0.0-42-generic")
        self.assertEqual(s["computer"], "QEMU Standard PC (Q35 + ICH9, 2009), BIOS 0.0.0 02/06/2015")
        self.assertIsNone(s["module"])
        self.assertEqual(s["trace"][:4], ["dump_stack_lvl", "panic", "sysrq_handle_crash",
                                          "__handle_sysrq"])
        # "? " lines are guesses of the unwinder: left out
        self.assertNotIn("__pfx_sysrq_handle_crash", s["trace"])
        self.assertEqual(s["trace"][-1], "entry_SYSCALL_64_after_hwframe")

    def test_oops_names_the_module(self):
        s = notice.parse_dmesg(self.text(OOPS))
        self.assertEqual(s["reason"], "Oops")
        self.assertEqual(s["stop_code"], "kernel NULL pointer dereference")
        self.assertEqual(s["process"], "kwin_wayland")
        self.assertEqual(s["kernel"], "7.0.0-42-generic")
        self.assertEqual(s["module"], "amdgpu")
        self.assertEqual(s["trace"][0], "dm_update_crtc_state")
        self.assertNotIn("page_fault_oops", s["trace"])

    def test_no_address_or_register_ever(self):
        for key in (SYSRQ, OOPS):
            s = notice.parse_dmesg(self.text(key))
            flat = json.dumps(s)
            self.assertNotRegex(flat, r"0x[0-9a-f]+")
            self.assertNotRegex(flat, r"[0-9a-f]{12,}")
            self.assertNotIn("RSP", flat)

    def test_addresses_go_dates_stay(self):
        s = notice.parse_dmesg(
            "Oops#1 Part1\n"
            "BUG: unable to handle page fault for address: ffffb3a1c3b7f9d8\n"
            "Hardware name: Example Board, BIOS 1.2 20250314\n")
        self.assertEqual(s["stop_code"], "unable to handle page fault")
        self.assertEqual(s["computer"], "Example Board, BIOS 1.2 20250314")

    def test_clean_restart_record(self):
        s = notice.parse_dmesg(self.text(RESTART))
        self.assertEqual(s["reason"], "Restart")
        self.assertIsNone(s["stop_code"])
        self.assertFalse(notice.is_problem(s))
        self.assertTrue(notice.is_problem(notice.parse_dmesg(self.text(SYSRQ))))
        self.assertTrue(notice.is_problem(notice.parse_dmesg(self.text(OOPS))))

    def test_garbage_and_empty(self):
        s = notice.parse_dmesg("")
        self.assertIsNone(s["reason"])
        self.assertEqual(s["trace"], [])
        # an unknown reason is still a problem: better one notice too many
        self.assertTrue(notice.is_problem(s))
        s = notice.parse_dmesg("\x00\xff random bytes\nKernel panic - not syncing: " + "x" * 5000)
        self.assertLessEqual(len(s["stop_code"]), 200)

    def test_long_traces_are_cut(self):
        lines = ["Panic#1 Part1", "Call Trace:", " <TASK>"]
        lines += [f" func_{i}+0x10/0x20" for i in range(100)]
        s = notice.parse_dmesg("\n".join(lines))
        self.assertEqual(len(s["trace"]), notice.MAX_TRACE)


class RecordsTest(Sandbox):
    def test_finds_every_record_and_nothing_else(self):
        found = {r.key: r for r in notice.find_records(self.pstore)}
        self.assertEqual(set(found), {SYSRQ, OOPS, RESTART})
        self.assertEqual(found[SYSRQ].crash_time, 1793461320)
        self.assertIsNone(found[OOPS].crash_time)
        self.assertEqual(found[SYSRQ].archived, 1793461400)

    def test_missing_folder(self):
        self.assertEqual(list(notice.find_records(self.tmp / "nope")), [])

    def test_symlinked_records_are_ignored(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        write(outside / "dmesg.txt", "Panic#1 Part1\n", 0o644)
        (self.pstore / "1793469999").symlink_to(outside)
        self.assertNotIn("1793469999", {r.key for r in notice.find_records(self.pstore)})

    def test_crash_time_must_be_believable(self):
        (self.pstore / "12").mkdir()
        write(self.pstore / "12/001/dmesg.txt", "Panic#1 Part1\n", 0o644)
        found = {r.key: r for r in notice.find_records(self.pstore)}
        self.assertIsNone(found["12/001"].crash_time)


class CollectTest(Sandbox):
    def test_writes_one_readable_summary_per_record(self):
        self.collect()
        files = sorted(p.name for p in self.summaries.iterdir())
        self.assertEqual(files, ["1793461320-001.json", "1793470000-001.json",
                                 "7147483648123456.json"])
        for p in self.summaries.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)
        s = json.loads((self.summaries / "1793461320-001.json").read_text())
        self.assertEqual(s["stop_code"], "sysrq triggered crash")
        self.assertEqual(s["record"], SYSRQ)

    def test_again_changes_nothing_and_old_ones_go(self):
        self.collect()
        before = (self.summaries / "7147483648123456.json").stat().st_mtime_ns
        self.drop(SYSRQ)
        self.collect()
        self.assertFalse((self.summaries / "1793461320-001.json").exists())
        self.assertEqual((self.summaries / "7147483648123456.json").stat().st_mtime_ns, before)

    def test_never_follows_a_planted_link(self):
        self.summaries.mkdir()
        victim = self.tmp / "victim"
        victim.write_text("keep me")
        (self.summaries / "1793461320-001.json").symlink_to(victim)
        self.collect()
        self.assertEqual(victim.read_text(), "keep me")
        self.assertFalse((self.summaries / "1793461320-001.json").is_symlink())

    def test_record_without_text(self):
        (self.pstore / OOPS / "dmesg.txt").unlink()
        self.collect()
        s = json.loads((self.summaries / "7147483648123456.json").read_text())
        self.assertEqual(s["stop_code"], "kernel NULL pointer dereference")

    def test_collect_command_line(self):
        out = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "collect", "--pstore",
                              str(self.pstore), "--summaries", str(self.summaries)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(list(self.summaries.glob("*.json"))), 3)


class NoticeTest(Sandbox):
    def setUp(self):
        super().setUp()
        self.drop(OOPS)          # one crash, one clean restart
        self.collect()

    def test_shows_once(self):
        out = self.run_notice()
        self.assertEqual(out.returncode, 0, out.stderr)
        shown = self.calls("notify-send")
        self.assertEqual(len(shown), 1)
        args = shown[0]
        self.assertIn("Raye restarted after a problem", args)
        self.assertIn("Your files are safe.", args)
        self.assertIn("--action=details=Details", args)
        self.assertIn("--app-name=Raye", args)
        self.assertIn("--icon=raye-eye", args)
        self.assertIn("--wait", args)
        self.assertEqual(self.calls("xdg-open"), [])
        # the report exists even when Details is not clicked
        self.assertEqual(len(self.reports()), 1)

        out = self.run_notice()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.calls("notify-send")), 1)
        self.assertEqual(len(self.reports()), 1)

    def test_details_opens_the_report(self):
        self.answer.write_text("details\n")
        self.run_notice()
        opened = self.calls("xdg-open")
        self.assertEqual(len(opened), 1)
        report = pathlib.Path(opened[0][0])
        self.assertEqual(report, self.reports()[0])
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(report.parent.stat().st_mode), 0o700)
        text = report.read_text()
        self.assertIn("Raye restarted after a problem", text)
        self.assertIn("Stop code:", text)
        self.assertIn("sysrq triggered crash", text)
        self.assertIn("bash", text)
        self.assertIn("sysrq_handle_crash", text)
        self.assertIn("github.com/Raye-Linux/handbook", text)
        self.assertIn(str(self.pstore / SYSRQ), text)
        # the test's own folder has a random name that can read like 0xd01
        self.assertNotRegex(text.replace(str(self.tmp), "<tmp>"), r"0x[0-9a-f]+")

    def test_french(self):
        self.answer.write_text("details")
        self.run_notice("fr_FR.UTF-8")
        args = self.calls("notify-send")[0]
        self.assertIn("Raye a redémarré après un problème", args)
        self.assertIn("Vos fichiers sont en sécurité.", args)
        self.assertIn("--action=details=Détails", args)
        text = self.reports()[0].read_text()
        self.assertIn("Code d'arrêt", text)
        self.assertIn("Vos fichiers sont en sécurité.", text)

    def test_language_list_wins(self):
        self.run_notice("en_US.UTF-8", {"LANGUAGE": "fr_CA:en"})
        self.assertIn("Raye a redémarré après un problème", self.calls("notify-send")[0])

    def test_old_crash_is_not_news(self):
        # the crash was archived a day before this boot, before this
        # account first ran the notice
        self.boot = 1793461400 + 86400
        self.run_notice()
        self.assertEqual(self.calls("notify-send"), [])
        # and stays quiet on the next boot too
        self.boot = 1793990000
        self.run_notice()
        self.assertEqual(self.calls("notify-send"), [])

    def test_clock_set_back_after_the_notice_ran(self):
        # a clock that jumps back (hardware clock in local time) must not
        # hide a crash: what was not there at the last run is new
        self.drop(SYSRQ)
        self.run_notice()
        self.assertEqual(self.calls("notify-send"), [])
        shutil.copytree(FIXTURES / "1793461320", self.pstore / "1793461320")
        self.archived(SYSRQ, 1700000000)
        self.boot = 1700000000 - 30
        self.collect()
        self.run_notice()
        self.assertEqual(len(self.calls("notify-send")), 1)

    def test_crash_after_the_last_notice(self):
        self.run_notice()
        self.assertEqual(len(self.calls("notify-send")), 1)
        shutil.copytree(FIXTURES / "1793461320", self.pstore / "1793500000")
        now = int(time.time()) + 5
        self.archived("1793500000/001", now)
        self.collect()
        self.run_notice()
        self.assertEqual(len(self.calls("notify-send")), 2)
        self.assertEqual(len(self.reports()), 2)

    def test_clean_restart_alone_says_nothing(self):
        self.drop(SYSRQ)
        self.run_notice()
        self.assertEqual(self.calls("notify-send"), [])
        state = json.loads((self.home / ".local/state/raye/crash-notice.json").read_text())
        self.assertIn(RESTART, state["seen"])

    def test_two_crashes_one_notice(self):
        shutil.copytree(FIXTURES / OOPS, self.pstore / OOPS)
        self.archived(OOPS, 1793461500)
        self.collect()
        self.run_notice()
        self.assertEqual(len(self.calls("notify-send")), 1)
        text = self.reports()[0].read_text()
        self.assertIn("amdgpu", text)
        self.assertIn("sysrq triggered crash", text)
        # newest first
        self.assertLess(text.index("amdgpu"), text.index("sysrq triggered crash"))

    def test_without_summary_says_where_details_are(self):
        shutil.rmtree(self.summaries)
        (self.pstore / SYSRQ / "dmesg.txt").unlink()
        self.answer.write_text("details")
        self.run_notice()
        self.assertEqual(len(self.calls("notify-send")), 1)
        text = self.reports()[0].read_text()
        self.assertIn("only root can read them", text)
        self.assertNotIn("administrator", text)
        self.assertIn(str(self.pstore / SYSRQ), text)

    def test_broken_state_is_read_as_none(self):
        state = self.home / ".local/state/raye/crash-notice.json"
        write(state, "{not json", 0o600)
        out = self.run_notice()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.calls("notify-send")), 1)
        json.loads(state.read_text())

    def test_no_notification_server(self):
        self.fake("busctl", 'echo "b false"')
        out = self.run_notice()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls("notify-send"), [])
        # remembered all the same: never shown twice, never shown late
        self.run_notice()
        self.assertEqual(self.calls("notify-send"), [])

    def test_notify_send_missing(self):
        (self.bin / "notify-send").unlink()
        out = self.run_notice(extra_env={"PATH": str(self.bin)})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.reports()), 1)

    def test_report_names_cannot_escape(self):
        evil = self.pstore / "..evil"
        evil.mkdir()
        write(evil / "dmesg.txt", "Panic#1 Part1\n", 0o644)
        self.archived("..evil", 1793461450)
        self.run_notice()
        for p in self.reports():
            self.assertEqual(p.parent, self.home / ".local/share/raye/crash-reports")


class LanguageTest(unittest.TestCase):
    def pick(self, **env):
        return notice.language(env)

    def test_choice(self):
        self.assertEqual(self.pick(LANG="fr_FR.UTF-8"), "fr")
        self.assertEqual(self.pick(LANG="fr_CA.UTF-8"), "fr")
        self.assertEqual(self.pick(LANG="nl_NL.UTF-8"), "en")
        self.assertEqual(self.pick(LANG="de_DE.UTF-8"), "de")
        self.assertEqual(self.pick(LANG="es_MX.UTF-8"), "es")
        self.assertEqual(self.pick(LANG="pt_BR.UTF-8"), "pt")
        self.assertEqual(self.pick(LANG="it_IT.UTF-8"), "it")
        self.assertEqual(self.pick(LANG="en_GB.UTF-8", LC_MESSAGES="fr_BE.UTF-8"), "fr")
        self.assertEqual(self.pick(LANG="fr_FR.UTF-8", LC_ALL="en_US.UTF-8"), "en")
        self.assertEqual(self.pick(LANG="en_US.UTF-8", LANGUAGE="nl:fr:en"), "fr")
        self.assertEqual(self.pick(LANG="C", LANGUAGE="fr"), "en")
        self.assertEqual(self.pick(), "en")


class FilesTest(unittest.TestCase):
    def strings(self, lang):
        return json.loads((LOCALE / f"{lang}.json").read_text())

    def test_same_keys_in_both_languages(self):
        en, fr = self.strings("en"), self.strings("fr")
        self.assertEqual(set(en), set(fr))
        self.assertEqual(len(en["months"]), 12)
        self.assertEqual(len(fr["months"]), 12)
        for key, value in en.items():
            if isinstance(value, str):
                self.assertEqual(re.findall(r"\{\w+\}", value), re.findall(r"\{\w+\}", fr[key]),
                                 key)

    def test_spanish_german_portuguese_italian(self):
        en = self.strings("en")
        for lang in ("es", "de", "pt", "it"):
            t = self.strings(lang)
            self.assertEqual(list(t), list(en), lang)
            self.assertEqual(len(t["months"]), 12, lang)
            for key, value in en.items():
                if isinstance(value, str):
                    self.assertTrue(t[key], (lang, key))
                    self.assertEqual(sorted(re.findall(r"\{\w+\}", value)),
                                     sorted(re.findall(r"\{\w+\}", t[key])), (lang, key))
                    if len(re.findall(r"[A-Za-z]{2,}", re.sub(r"\{\w+\}", "", value))) >= 3:
                        self.assertNotEqual(t[key], value, (lang, key))

    def test_built_in_english_matches_the_file(self):
        self.assertEqual(notice.ENGLISH, self.strings("en"))

    def test_no_forbidden_words(self):
        words = re.compile(r"ubuntu|debian|kubuntu|\barch\b|fedora|\bmint\b|\bwine\b|\bAI\b|assistant",
                           re.I)
        for path in [SCRIPT, UNIT, DROPIN, *LOCALE.iterdir()]:
            self.assertIsNone(words.search(path.read_text()), path)

    def test_user_unit(self):
        unit = configparser.ConfigParser(strict=False, interpolation=None)
        unit.optionxform = str
        unit.read(UNIT)
        self.assertEqual(unit["Service"]["ExecStart"], "/usr/libexec/raye-crash-notice")
        self.assertEqual(unit["Install"]["WantedBy"], "graphical-session.target")
        self.assertEqual(unit["Unit"]["ConditionDirectoryNotEmpty"], "/var/lib/systemd/pstore")
        self.assertIn("graphical-session.target", unit["Unit"]["After"])

    def test_pstore_drop_in(self):
        unit = configparser.ConfigParser(strict=False, interpolation=None)
        unit.optionxform = str
        unit.read(DROPIN)
        self.assertEqual(unit["Service"]["ExecStartPost"],
                         "-/usr/libexec/raye-crash-notice collect")
        self.assertEqual(unit["Service"]["StateDirectory"], "raye/crash")

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
