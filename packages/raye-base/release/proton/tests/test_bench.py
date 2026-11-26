"""raye-proton-bench: the same programs, several compatibility tools, one
computer. Tools here are stubs: a `proton` script that logs its verb and
does what the test asks (finish, fail, hang, write the expected file)."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BENCH = HERE / "raye-proton-bench"
PATHS = HERE.parents[1] / "debian" / "raye-release-paths"


def load():
    loader = importlib.machinery.SourceFileLoader("raye_proton_bench", str(BENCH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def tool(tmp, name, body):
    d = tmp / name
    d.mkdir()
    p = d / "proton"
    p.write_text("#!/bin/sh\n"
                 f'echo "{name} $1 $2 data=$STEAM_COMPAT_DATA_PATH client=$STEAM_COMPAT_CLIENT_INSTALL_PATH" >> "{tmp}/log"\n'
                 + body)
    p.chmod(0o755)
    (d / "version").write_text(f"1 {name}\n")
    return d


def bench(*args, **env):
    e = dict(os.environ, RAYE_BENCH_NO_SCOPE="1")
    e.update(env)
    return subprocess.run([sys.executable, str(BENCH), *args], env=e,
                          capture_output=True, text=True, timeout=120)


def test_frame_stats_from_a_mangohud_log(tmp_path):
    m = load()
    log = tmp_path / "game.csv"
    rows = ["os,cpu,gpu,ram,kernel,driver,cpuscheduler", "Raye,x,y,16,7.0,mesa,bore",
            "fps,frametime,cpu_load,gpu_load,cpu_temp,gpu_temp,elapsed"]
    # 98 frames of 10 ms and 2 of 50 ms: 1000*100/1080 fps on average
    times = [10.0] * 98 + [50.0, 50.0]
    rows += [f"{1000 / t:.1f},{t},10,90,50,60,{i}" for i, t in enumerate(times)]
    log.write_text("\n".join(rows) + "\n")
    got = m.read_mangohud(log)
    assert got == times
    s = m.frame_stats(got)
    assert s["frames"] == 100
    assert s["avg_fps"] == round(100000 / 1080, 2)
    assert s["low1_fps"] == 20.0          # the 99th percentile frame is a 50 ms one
    assert s["stutters"] == 2             # longer than twice the 10 ms median
    assert m.frame_stats([]) is None


def test_dry_run_lists_the_commands_and_the_problems(tmp_path):
    good = tool(tmp_path, "raye", "exit 0\n")
    prog = tmp_path / "hello.exe"
    prog.write_text("MZ")
    r = bench("run", "--tool", f"raye={good}", "--tool", f"ge={tmp_path / 'missing'}",
              "--program", f"hello={prog}", "--out", str(tmp_path / "out"), "--dry-run")
    assert r.returncode == 1
    assert f"raye x hello: 5 runs: {good}/proton waitforexitandrun {prog}" in r.stdout
    assert "problem: ge: no proton in" in r.stdout
    assert not (tmp_path / "out").exists()      # a dry run starts nothing
    assert not (tmp_path / "log").exists()


def test_every_tool_runs_the_same_program_turn_by_turn(tmp_path):
    expect = 'mkdir -p "$STEAM_COMPAT_DATA_PATH/pfx/drive_c"; echo ok > "$STEAM_COMPAT_DATA_PATH/pfx/drive_c/ok.txt"\n'
    a = tool(tmp_path, "raye", expect + "exit 0\n")
    b = tool(tmp_path, "ge", "exit 3\n")                    # starts, does not finish well
    c = tool(tmp_path, "cachy", "exit 0\n")                 # finishes, writes nothing
    prog = tmp_path / "hello.exe"
    prog.write_text("MZ")
    out = tmp_path / "out"
    r = bench("run", "--tool", f"raye={a}", "--tool", f"ge={b}", "--tool", f"cachy={c}",
              "--program", f"hello={prog}::--arg", "--runs", "2", "--expect", "C:\\ok.txt",
              "--out", str(out))
    assert r.returncode == 0, r.stderr
    log = (tmp_path / "log").read_text().splitlines()
    assert [l.split()[0] for l in log] == ["raye", "ge", "cachy", "raye", "ge", "cachy"]
    assert all(l.split()[1:3] == ["waitforexitandrun", str(prog)] for l in log)
    # each tool keeps its own game folder, the same one from run to run
    assert len({l.split()[3] for l in log}) == 3
    res = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    ok = {(x["tool"], x["run"]): x["ok"] for x in res}
    assert ok == {("raye", 1): True, ("raye", 2): True, ("ge", 1): False, ("ge", 2): False,
                  ("cachy", 1): False, ("cachy", 2): False}
    assert [x["first"] for x in res if x["tool"] == "raye"] == [True, False]
    meta = json.loads((out / "machine.json").read_text())
    assert meta["tools"]["ge"]["version"] == "1 ge" and meta["expect"] == "C:\\ok.txt"
    text = (out / "summary.md").read_text()
    assert "| raye | hello | 2 | 2/2 |" in text
    assert "| ge | hello | 2 | 0/2 |" in text
    for word in ("better", "best", "faster", "winner"):
        assert word not in text.lower()


def test_a_program_that_never_ends_is_stopped_and_counted_as_failed(tmp_path):
    a = tool(tmp_path, "raye", "sleep 60\n")
    prog = tmp_path / "hang.exe"
    prog.write_text("MZ")
    out = tmp_path / "out"
    r = bench("run", "--tool", f"raye={a}", "--program", f"hang={prog}", "--runs", "1",
              "--timeout", "1", "--out", str(out))
    assert r.returncode == 0
    res = json.loads((out / "results.jsonl").read_text())
    assert res["timed_out"] and not res["ok"] and res["wall_s"] < 20


def test_mangohud_runs_read_the_frames_logged(tmp_path):
    body = ('d=${MANGOHUD_CONFIG##*output_folder=}; d=${d%%,*}\n'
            'printf "os\\nfps,frametime\\n100,10\\n100,10\\n50,20\\n" > "$d/game_2026.csv"\n'
            '[ "$MANGOHUD" = 1 ] && exit 0\nexit 9\n')
    a = tool(tmp_path, "raye", body)
    prog = tmp_path / "game.exe"
    prog.write_text("MZ")
    out = tmp_path / "out"
    r = bench("run", "--tool", f"raye={a}", "--program", f"game={prog}", "--runs", "1",
              "--mangohud", "5", "--out", str(out))
    assert r.returncode == 0, r.stderr
    res = json.loads((out / "results.jsonl").read_text())
    assert res["ok"] and res["frames"]["frames"] == 3 and res["frames"]["avg_fps"] == 75.0


def test_every_tool_goes_through_the_same_runtime(tmp_path):
    m = load()
    cmd = m.command("/t/ge", "/g/game.exe", ["-x"], "/rt/_v2-entry-point")
    assert cmd == ["/rt/_v2-entry-point", "--verb=waitforexitandrun", "--",
                   "/t/ge/proton", "waitforexitandrun", "/g/game.exe", "-x"]


def test_fetch_refuses_an_archive_whose_sum_is_not_the_pinned_one(tmp_path):
    archive = tmp_path / "src" / "Tool-1.tar.gz"
    archive.parent.mkdir()
    inner = tmp_path / "Tool-1"
    inner.mkdir()
    (inner / "proton").write_text("#!/bin/sh\n")
    subprocess.run(["tar", "-czf", str(archive), "-C", str(tmp_path), "Tool-1"], check=True)
    good = hashlib.sha512(archive.read_bytes()).hexdigest()
    tsv = tmp_path / "tools.tsv"
    tsv.write_text(f"# comment\nTool-1\tfile://{archive}\t{good}\n")
    r = bench("fetch", str(tmp_path / "dest"), RAYE_PROTON_BENCH_TOOLS=str(tsv))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "dest" / "Tool-1" / "proton").exists()
    tsv.write_text(f"Tool-2\tfile://{archive}\t{'0' * 128}\n")
    r = bench("fetch", str(tmp_path / "dest2"), RAYE_PROTON_BENCH_TOOLS=str(tsv))
    assert r.returncode != 0 and "SHA-512" in r.stderr
    assert not (tmp_path / "dest2" / "Tool-2").exists()


def test_the_pinned_tools_are_the_two_named_ones():
    names = [l.split("\t")[0] for l in (HERE / "tools.tsv").read_text().splitlines()
             if l and not l.startswith("#")]
    assert names == ["GE-Proton11-14", "proton-cachyos-11.0-20261015-slr"]
    for l in (HERE / "tools.tsv").read_text().splitlines():
        if l and not l.startswith("#"):
            name, url, want = l.split("\t")
            assert url.startswith("https://github.com/") and len(want) == 128


def test_the_bench_is_installed_with_raye_gaming():
    paths = PATHS.read_text()
    assert "release/proton/raye-proton-bench" in paths and "usr/bin/raye-proton-bench" in paths
    assert "usr/share/raye/proton-bench/tools.tsv" in paths
