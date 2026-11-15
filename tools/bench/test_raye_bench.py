# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for raye-bench and its suites, fed with recorded tool outputs
(fixtures/): systemd-analyze, cyclictest, fio, hyperfine, stress-ng,
MangoHud and the KWin launch timer.

    python3 test_raye_bench.py
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"
sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(HERE / "suites"))


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bench = load(HERE / "raye-bench", "raye_bench")
common = load(HERE / "suites" / "common.py", "t_common")
boot = load(HERE / "suites" / "boot.py", "t_boot")
memory = load(HERE / "suites" / "memory.py", "t_memory")
latency = load(HERE / "suites" / "latency.py", "t_latency")
throughput = load(HERE / "suites" / "throughput.py", "t_throughput")
fio = load(HERE / "suites" / "io.py", "t_io")
games = load(HERE / "suites" / "games.py", "t_games")
launch = load(HERE / "suites" / "launch.py", "t_launch")


def fixture(name):
    return (FIX / name).read_text()


class TestCommon(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(common.parse_duration("2min 1.796s"), 121.796)
        self.assertEqual(common.parse_duration("812ms"), 0.812)
        self.assertEqual(common.parse_duration("450us"), 0.00045)
        self.assertEqual(common.parse_duration("1h 2min 3s"), 3723.0)
        self.assertIsNone(common.parse_duration("soon"))

    def test_aggregate_leaves_out_failed_runs(self):
        a = common.aggregate([3.0, None, 1.0, 2.0])
        self.assertEqual((a["median"], a["min"], a["max"]), (2.0, 1.0, 3.0))
        self.assertEqual(a["values"], [3.0, None, 1.0, 2.0])
        self.assertIsNone(common.aggregate([None, None])["median"])
        self.assertIsNone(common.aggregate([True])["median"])

    def test_percentile_nearest_rank(self):
        self.assertEqual(common.percentile(range(1, 101), 99), 99)
        self.assertEqual(common.percentile([5], 99.9), 5)
        self.assertIsNone(common.percentile([], 50))


class TestBoot(unittest.TestCase):
    def test_parts_total_and_handover(self):
        b = boot.parse_analyze(fixture("systemd-analyze.txt"))
        self.assertEqual(b["firmware_s"], 4.12)
        self.assertEqual(b["initrd_s"], 0.812)
        self.assertEqual(b["total_s"], 10.944)
        self.assertEqual(b["graphical_userspace_s"], 2.904)
        # kernel + initrd + userspace to graphical.target
        self.assertEqual(b["handover_to_login_s"], 4.926)

    def test_vm_without_firmware_times(self):
        b = boot.parse_analyze(fixture("systemd-analyze-vm.txt"))
        self.assertIsNone(b["firmware_s"])
        self.assertEqual(b["kernel_s"], 121.796)
        self.assertEqual(b["handover_to_login_s"], 125.777)

    def test_unknown(self):
        b = boot.parse_analyze("Bootup is not yet finished.")
        self.assertIsNone(b["total_s"])
        self.assertIsNone(b["handover_to_login_s"])

    def test_blame_slowest_first(self):
        rows = boot.parse_blame(fixture("systemd-analyze-blame.txt"), top=3)
        self.assertEqual(rows, [[63.102, "apt-daily-upgrade.timer"],
                                [2.311, "plymouth-quit-wait.service"],
                                [1.042, "NetworkManager-wait-online.service"]])
        units = [u for _s, u in boot.parse_blame(fixture("systemd-analyze-blame.txt"))]
        self.assertIn("systemd-random-seed.service", units)
        self.assertEqual(len(units), 8)   # the line that is not a unit is skipped


class TestMemory(unittest.TestCase):
    def test_used_is_total_minus_available(self):
        m = memory.parse_meminfo("MemTotal:  4096000 kB\nMemFree:  1000 kB\nMemAvailable:  3072000 kB\n"
                                 "SwapTotal: 2048000 kB\nSwapFree: 1024000 kB\n")
        self.assertEqual(m, {"used_mib": 1000, "total_mib": 4000, "swap_used_mib": 1000})

    def test_empty(self):
        self.assertIsNone(memory.parse_meminfo("")["used_mib"])


class TestLatency(unittest.TestCase):
    def test_recorded_run(self):
        data = json.loads(fixture("cyclictest.json"))
        r = latency.parse_cyclictest(data)
        self.assertEqual(r["min_us"], 54)
        self.assertEqual(r["max_us"], 3330)
        self.assertAlmostEqual(r["avg_us"], (70.57 * 1996 + 70.71 * 1991) / 3987, places=2)
        # p99 from the joined histograms, counted by hand
        hist = {}
        for t in data["thread"].values():
            for us, n in t["histogram"].items():
                hist[int(us)] = hist.get(int(us), 0) + n
        seen = 0
        for us in sorted(hist):
            seen += hist[us]
            if seen >= 0.99 * 3987:
                break
        self.assertEqual(r["p99_us"], us)
        # 19 wakeups landed past the histogram: no exact p99.9
        self.assertIsNone(r["p999_us"])

    def test_no_data(self):
        self.assertIsNone(latency.parse_cyclictest(None)["avg_us"])


class TestThroughput(unittest.TestCase):
    def test_hyperfine(self):
        r = throughput.parse_hyperfine(json.loads(fixture("hyperfine.json")))
        self.assertEqual(r["median"], 0.0551)
        self.assertEqual(r["min"], 0.0549)
        self.assertIsNone(throughput.parse_hyperfine({})["median"])

    def test_stressng(self):
        self.assertEqual(throughput.parse_stressng_yaml(fixture("stress-ng.yaml")), {"cpu": 1978.09})

    def test_compile_tree_is_the_same_every_time(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            throughput.write_compile_tree(a, files=3, functions=4)
            throughput.write_compile_tree(b, files=3, functions=4)
            names = sorted(os.listdir(a))
            self.assertEqual(names, ["Makefile", "u0.c", "u1.c", "u2.c"])
            for n in names:
                self.assertEqual(pathlib.Path(a, n).read_text(), pathlib.Path(b, n).read_text())


class TestIO(unittest.TestCase):
    def test_recorded_four_jobs(self):
        r = fio.parse_fio(json.loads(fixture("fio.json")))
        self.assertEqual(sorted(r), ["randread_4k", "randwrite_4k", "seqread_1m", "seqwrite_1m"])
        self.assertEqual(r["randread_4k"]["iops"], 115026)
        self.assertEqual(r["randread_4k"]["p99_us"], 602.1)
        self.assertEqual(r["seqwrite_1m"]["mibs"], 2589.1)

    def test_command(self):
        cmd = fio.fio_command("/tmp/x.dat", 64, 2, True)
        self.assertIn("--direct=1", cmd)
        self.assertEqual(cmd.count("--stonewall"), 4)
        self.assertEqual([c for c in cmd if c.startswith("--name=")],
                         ["--name=randread_4k", "--name=randwrite_4k", "--name=seqread_1m", "--name=seqwrite_1m"])

    def test_works_in_its_own_folder_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "raye-bench-fio.dat").write_text("keep me")
            seen = []

            class O:
                io_dir, io_size, quick = d, 1, True

            def fake_run(cmd, timeout=None):
                path = next(c for c in cmd if c.startswith("--filename=")).split("=", 1)[1]
                seen.append(path)
                pathlib.Path(path).write_text("x")
                return subprocess.CompletedProcess(cmd, 1, "", "fio: something broke\n")
            old_have, old_run = fio.common.have, fio.common.run
            fio.common.have, fio.common.run = (lambda t: True), fake_run
            try:
                r = fio.measure(O())
            finally:
                fio.common.have, fio.common.run = old_have, old_run
            self.assertEqual(os.listdir(d), ["raye-bench-fio.dat"])
            self.assertEqual(pathlib.Path(d, "raye-bench-fio.dat").read_text(), "keep me")
            self.assertNotEqual(os.path.dirname(seen[0]), d)
            self.assertFalse(r["_detail"]["direct"])          # retried without O_DIRECT
            self.assertEqual(r["_detail"]["note"], "fio failed: fio: something broke")
            self.assertIsNone(r["randread_4k_iops"])


class TestGames(unittest.TestCase):
    def test_recorded_log(self):
        r = games.parse_mangohud_csv(fixture("mangohud.csv"))
        self.assertEqual(r["frames"], 1000)
        self.assertEqual(r["avg_fps"], round(1000 * 1000 / (985 * 10 + 13 * 25 + 2 * 50), 2))
        self.assertEqual(r["frametime_p99_ms"], 25.0)
        self.assertEqual(r["low1_fps"], 40.0)
        self.assertEqual(r["low01_fps"], 20.0)
        self.assertEqual(r["duration_s"], 10.28)

    def test_not_a_log(self):
        self.assertEqual(games.parse_mangohud_csv("a,b\n1,2\n")["frames"], 0)

    def test_newest_log_in_a_folder(self):
        with tempfile.TemporaryDirectory() as d:
            for i, n in enumerate(["old.csv", "new.csv", "new_summary.csv"]):
                p = pathlib.Path(d, n)
                p.write_text(fixture("mangohud.csv"))
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual(os.path.basename(games.newest_csv(d)), "new.csv")


class TestLaunch(unittest.TestCase):
    def events(self):
        return [e for e in map(launch.parse_event, fixture("kwin-launch-timer.log").splitlines()) if e]

    def test_parse_timer_lines(self):
        ev = self.events()
        self.assertEqual([e["cls"] for e in ev], ["org.kde.dolphin", "firefox", "org.raye.settings"])
        self.assertEqual(ev[0]["t"], 1793474275.532)

    def test_delay_counts_only_windows_after_the_start(self):
        ev = self.events()
        self.assertEqual(launch.window_delay(ev, 1793474275.0, ("dolphin",)), 0.532)
        self.assertIsNone(launch.window_delay(ev, 1793474276.0, ("dolphin",)))
        self.assertEqual(launch.window_delay(ev, 1793474290.0, launch.APPS["settings"][1]), 0.25)

    def test_every_app_has_a_class(self):
        self.assertEqual(sorted(launch.APPS), ["browser", "files", "settings", "store", "terminal"])

    def test_time_apps_end_to_end_with_a_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            log = pathlib.Path(d, "kwin.log")
            log.write_text("")
            fake = ("python3 -c \"import json,time,sys;time.sleep(0.3);"
                    "open(sys.argv[1],'a').write('js: raye-launch-timer '+json.dumps("
                    "{'t':int(time.time()*1000),'cls':'org.raye.fake'})+'\\n');time.sleep(60)\" " + str(log))
            old = dict(launch.APPS)
            launch.APPS.clear()
            launch.APPS.update({
                "fake": (["sh", "-c", fake], ("org.raye.fake",), ("no-such-proc",)),
                "missing": (["raye-no-such-app"], ("x",), ("x",)),
            })
            stream = launch.EventStream(str(log))
            try:
                t0 = time.monotonic()
                out, detail = launch.time_apps(["fake", "missing"], stream, timeout=10, settle=0)
                self.assertLess(time.monotonic() - t0, 20)   # the sleeping app was stopped
            finally:
                stream.close()
                launch.APPS.clear()
                launch.APPS.update(old)
            self.assertGreaterEqual(out["fake_s"], 0.3)
            self.assertLess(out["fake_s"], 5)
            self.assertIsNone(out["missing_s"])
            self.assertEqual(detail["missing"], "not installed")

    def test_kwin_script_present_and_pinned_to_windowadded(self):
        js = launch.SCRIPT.read_text()
        self.assertIn("workspace.windowAdded.connect", js)
        self.assertIn(launch.MARK.strip(), js)
        meta = json.loads((launch.SCRIPT.parents[2] / "metadata.json").read_text())
        self.assertEqual(meta["KPlugin"]["Id"], launch.PLUGIN)


def report(results, kernel="7.0.0-42-raye", virt=None):
    raw = {s: [dict(r) for r in runs] for s, runs in results.items()}
    fp = {"os": "Raye Linux", "kernel": kernel, "cpu": "CPU", "disk": "Disk (nvme, ssd)",
          "cmdline": "quiet splash", "packages": {}, "virtual": virt, "on_mains": True}
    return bench.build_report(raw, {}, 3, fp)


class TestRunner(unittest.TestCase):
    def test_units_and_direction(self):
        self.assertEqual(bench.unit_of("cpu_ops_s"), ("ops/s", 1))
        self.assertEqual(bench.unit_of("files_s"), ("s", -1))
        self.assertEqual(bench.unit_of("seqread_1m_mibs"), ("MiB/s", 1))
        self.assertEqual(bench.unit_of("used_mib"), ("MiB", -1))
        self.assertEqual(bench.unit_of("frames"), ("", 0))

    def test_report_has_medians_and_ranges(self):
        r = report({"launch": [{"files_s": 0.5}, {"files_s": 0.3}, {"files_s": None, "_detail": {"files": "x"}}]})
        m = r["results"]["launch"]["files_s"]
        self.assertEqual((m["median"], m["min"], m["max"]), (0.4, 0.3, 0.5))
        self.assertEqual(r["format"], 2)
        self.assertEqual(r["details"]["launch"][2], {"files": "x"})

    def test_merge_three_boots(self):
        boots = [report({"boot": [{"total_s": t}]}, kernel=k) for t, k in
                 ((10.0, "7.0.0-42-raye"), (12.0, "7.0.0-42-raye"), (11.0, "7.0.0-43-raye"))]
        m = bench.merge(json.loads(json.dumps(boots)))
        t = m["results"]["boot"]["total_s"]
        self.assertEqual((t["median"], t["min"], t["max"], t["values"]), (11.0, 10.0, 12.0, [10.0, 12.0, 11.0]))
        self.assertEqual(m["fingerprint_differs"], ["kernel"])
        with self.assertRaises(ValueError):
            bench.merge([{"format": 1}])

    def test_compare_verdicts(self):
        a = report({"launch": [{"files_s": 1.0}, {"files_s": 1.1}, {"files_s": 0.9}],
                    "games": [{"avg_fps": 100.0, "frames": 10}]})
        b = report({"launch": [{"files_s": 0.5}, {"files_s": 0.6}, {"files_s": 0.4}],
                    "games": [{"avg_fps": 101.0, "frames": 12}]})
        rows = {r[0]: r for r in bench.compare(a, b)}
        self.assertEqual(rows["launch.files_s"][3:], (-50.0, "better"))
        self.assertEqual(rows["games.avg_fps"][4], "same")    # 1 %
        self.assertEqual(rows["games.frames"][4], "-")
        self.assertEqual(bench.compare(b, a)[0][4], "worse")

    def test_windows_report_compares_with_raye(self):
        win = json.loads(fixture("windows-report.json"))
        raye = report({"launch": [{"files_s": 0.4}, {"files_s": 0.5}, {"files_s": 0.45}],
                       "memory": [{"used_mib": 1500, "total_mib": 16000}]})
        rows = {r[0]: r for r in bench.compare(win, raye)}
        self.assertEqual(rows["launch.files_s"][4], "better")
        self.assertEqual(rows["memory.used_mib"][4], "better")
        self.assertEqual(rows["memory.total_mib"][4], "-")
        self.assertIn("Windows", bench.compare_text(win, raye))

    def test_text_warns_in_a_vm(self):
        txt = bench.text_report(report({"disk": [{"used_gib": 9.5}],
                                        "launch": [{"files_s": None, "_detail": {"skipped": {"files": "already open"}}}]},
                                       virt="kvm"))
        self.assertIn("never publish", txt)
        self.assertIn("launch run 1: files: already open", txt)
        self.assertNotIn("None", txt)
        self.assertIn("disk.used_gib", txt)

    def test_errors_are_reported_not_raised(self):
        class O:
            runs, mangohud_log, quick = 1, [], True
        raw, errors = bench.run_suites(["games"], O(), log=io.StringIO())
        self.assertEqual(raw, {})
        self.assertIn("--mangohud-log", errors["games"])

    def test_games_one_run_per_log(self):
        class O:
            runs, quick = 1, True
            mangohud_log = [str(FIX / "mangohud.csv")] * 3
        raw, errors = bench.run_suites(["games"], O(), log=io.StringIO())
        self.assertEqual(len(raw["games"]), 3)

    def test_fingerprint_parsers(self):
        self.assertEqual(bench.parse_os_release('NAME="Raye"\nPRETTY_NAME="Raye Linux 26.04"\n'), "Raye Linux 26.04")
        self.assertEqual(bench.parse_cpu_model("processor\t: 0\nmodel name\t: AMD EPYC 7551\n"), "AMD EPYC 7551")
        lsblk = 'MODEL="" ROTA="0" TRAN=""\nMODEL="Samsung SSD 980 PRO 1TB" ROTA="0" TRAN="nvme"\n'
        self.assertEqual(bench.parse_lsblk_model(lsblk), "Samsung SSD 980 PRO 1TB (nvme, ssd)")
        self.assertEqual(bench.parse_lsblk_model('MODEL="WDC WD40" ROTA="1" TRAN=""'), "WDC WD40 (hdd)")
        self.assertIsNone(bench.parse_lsblk_model('MODEL="" ROTA="0" TRAN=""'))

    def test_power_state(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(bench.power_state(d))
            for name, kind, online in (("AC", "Mains", "0"), ("BAT0", "Battery", None)):
                os.makedirs(f"{d}/{name}")
                pathlib.Path(d, name, "type").write_text(kind + "\n")
                if online is not None:
                    pathlib.Path(d, name, "online").write_text(online + "\n")
            self.assertFalse(bench.power_state(d))
            pathlib.Path(d, "AC", "online").write_text("1\n")
            self.assertTrue(bench.power_state(d))

    def test_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                bench.parse_args(["--suites", "boot,nope"])
            with self.assertRaises(SystemExit):
                bench.parse_args(["--apps", "files,nope"])
            with self.assertRaises(SystemExit):
                bench.parse_args(["--runs", "0"])
        o = bench.parse_args(["--suites", "all"])
        self.assertNotIn("games", o.names)
        o = bench.parse_args(["--suites", "all", "--mangohud-log", "x.csv"])
        self.assertIn("games", o.names)
        self.assertEqual(bench.parse_args([]).names, list(bench.DEFAULT))

    def test_compare_from_the_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = pathlib.Path(d, "a.json"), pathlib.Path(d, "b.json")
            a.write_text(json.dumps(report({"disk": [{"used_gib": 10.0}]})))
            b.write_text(json.dumps(report({"disk": [{"used_gib": 8.0}]})))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(bench.main(["--compare", str(a), str(b)]), 0)
            self.assertIn("-20.0 %", out.getvalue())
            self.assertIn("better", out.getvalue())

    def test_bad_report_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d, "x.json")
            p.write_text("not json")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(bench.main(["--compare", str(p), str(p)]), 2)
            self.assertIn("raye-bench:", err.getvalue())

    def test_launch_refuses_root(self):
        old = launch.os.geteuid
        launch.os.geteuid = lambda: 0
        try:
            with self.assertRaises(RuntimeError):
                launch.refuse_root()
        finally:
            launch.os.geteuid = old

    def test_list_names_every_suite(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bench.main(["--list"])
        for s in bench.SUITES:
            self.assertIn(s, out.getvalue())

    def test_suites_run_on_their_own(self):
        for name in ("memory", "disk"):
            res = subprocess.run([sys.executable, "-I", "-B", str(HERE / "suites" / f"{name}.py")],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIsInstance(json.loads(res.stdout), dict)

    def test_windows_script_speaks_the_same_json(self):
        ps = (HERE / "raye-bench.ps1").read_text()
        self.assertIn("format = 2", ps)
        for app in launch.APPS:
            self.assertRegex(ps, rf"\n    {app} +=")
        for key in ("total_s", "used_mib", "used_gib", "fingerprint", "results", "errors"):
            self.assertIn(key, ps)
        self.assertNotIn("Stop-Process", ps)   # never kill Explorer, the shell
        win = json.loads(fixture("windows-report.json"))
        self.assertEqual(sorted(win["results"]["launch"]), sorted(f"{a}_s" for a in launch.APPS))

    def test_reads_a_report_with_a_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d, "w.json")
            p.write_bytes(b"\xef\xbb\xbf" + fixture("windows-report.json").encode())
            self.assertEqual(bench.read_json(str(p))["os"], "windows")

    def test_no_launch_tool_from_outside_the_archive(self):
        for p in [HERE / "raye-bench"] + sorted((HERE / "suites").glob("*.py")):
            self.assertNotIn("kdotool", p.read_text(), p.name)


if __name__ == "__main__":
    unittest.main()
