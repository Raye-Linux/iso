# Benchmarks

Raye says it is fast; these tools are how it says so honestly. They
measure the same things the same way every time, on Raye and on Windows,
on the same computer, and keep every number with the hardware and
software it was taken on.

| Suite | What it measures | Needs (bench time only) |
|---|---|---|
| `boot` | firmware, loader, kernel, initrd, userspace; handover to login screen; slowest units | systemd |
| `memory` | memory in use after login (total minus available) | - |
| `disk` | disk used by `/` | - |
| `launch` | Files, Firefox, Settings, Konsole, Store: start to window mapped | a Plasma session |
| `latency` | wakeup latency (cyclictest), idle and with every CPU busy | `rt-tests stress-ng` |
| `throughput` | a fixed compile (hyperfine), stress-ng cpu and matrix | `hyperfine stress-ng build-essential` |
| `io` | fio: 4k random read and write, 1M sequential read and write | `fio` |
| `underload` | the app launches while a compile runs, then while a big copy runs | `build-essential` |
| `games` | MangoHud frame-time logs: average FPS, 1 % and 0.1 % lows | logs you record |

These tools are installed only on the computer being measured, never in
the Raye image:

```
sudo apt install rt-tests stress-ng fio hyperfine build-essential mangohud
```

## Method

- Same computer, same firmware settings, mains power, nothing else open,
  5 minutes after login.
- Three runs; the report keeps every value, the median and the min–max.
- Publish the median and the range with the fingerprint: CPU, RAM, disk
  model, kernel, kernel command line, versions of systemd, Plasma, KWin
  and Mesa, CPU governor, power source.
- A virtual machine is for checking that nothing got slower between two
  builds. Its disk, timer and graphics are virtual: never publish its
  numbers. The report says so when it runs in one.
- Each optimisation gets one row in `iso/docs/bench/`: before, after,
  verdict (kept, dropped, no effect).

## On Raye

```
./raye-bench                                  # boot, memory, disk, app launch
./raye-bench --suites all --runs 3 --out after.json --text
sudo ./raye-bench --suites latency --out latency.json   # real-time priority
./raye-bench --compare before.json after.json
./raye-bench --list
```

Boot, memory and disk give one value per boot. Restart (a full power off
and on), log in, wait 5 minutes, run `raye-bench --out boot1.json`, three
times, then join them:

```
./raye-bench --merge boot1.json boot2.json boot3.json --out boots.json --text
```

Close the apps of the launch suite before measuring: one that is already
open is skipped and named in the report. App launch times come from
`kwin-launch-timer/`, a small KWin script that raye-bench loads over
D-Bus (`org.kde.KWin /Scripting`) for the time of the measure and unloads
after. It writes a line to the journal each time a window appears; open
the journal with `journalctl --user -f | grep raye-launch-timer` to watch
it. `--kwin-log FILE` reads those lines from a file instead (a nested KWin
writing to its log).

The I/O and copy tests write their files in `~/.cache/raye-bench`
(`--io-dir` to choose; 1 GiB for fio, 4 GiB for the copy, all deleted
after). `--quick` makes every suite short, to check that the tools work.

Games: play the same fixed run three times with MangoHud logging on
(Shift+F2), then give each log:

```
./raye-bench --suites games --mangohud-log run1.csv --mangohud-log run2.csv --mangohud-log run3.csv
```

1 % low is the frame rate that 99 % of frames reach or beat (1000 divided
by the 99th percentile frame time); 0.1 % low the same at 99.9 %.

Each suite in `suites/` also runs on its own and prints one run:
`python3 suites/latency.py`.

## On Windows

```
powershell -ExecutionPolicy Bypass -File raye-bench.ps1 -Out windows.json
```

As admin, after three restarts (it reads the last three boots from the
boot performance log, event 100). It opens Explorer, Edge, Settings,
Terminal and the Store three times each, the counterparts of Files,
Firefox, Settings, Konsole and the Store, and writes the same JSON shape,
so `./raye-bench --compare windows.json raye.json` works. It records
whether Fast Startup is on: report both numbers honestly. Turn off Edge's
startup boost, or Edge is already running when it is "opened".

## Report

```
{"format": 2, "tool": "raye-bench", "os": "raye", "taken": "...", "runs": 3,
 "fingerprint": {...},
 "results": {"launch": {"files_s": {"median": 0.42, "min": 0.39, "max": 0.51,
                                    "values": [0.42, 0.39, 0.51]}}, ...},
 "details": {...}, "errors": {"io": "fio is missing: sudo apt install fio"}}
```

The end of a name gives its unit: `_s`, `_ms`, `_us`, `_mib`, `_gib`
(lower is better), `_mibs`, `_iops`, `_fps`, `_ops_s` (higher is better).
`--compare` says "same" when the two ranges overlap or the medians are
within 2 %.

## Tests

```
python3 test_raye_bench.py
```

The parsers are fed recorded outputs in `fixtures/` (systemd-analyze,
cyclictest, fio, hyperfine, stress-ng, MangoHud, the launch timer, a
Windows report).
