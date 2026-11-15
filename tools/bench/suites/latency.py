#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Wakeup latency: how late a sleeping thread wakes up (cyclictest),
idle and with every CPU busy (stress-ng --cpu).

Needs rt-tests and stress-ng. As root the test threads get real-time
priority, which is how kernels are usually compared; as a user they run
as normal threads, closer to what an app feels. The report says which.
"""

import json
import os
import pathlib
import sys
import tempfile
import time

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = "latency"
PER_BOOT = False
HISTOGRAM_US = 20000


def parse_cyclictest(data):
    """min, mean, p99, p99.9 and max in µs over every thread of a --json file."""
    threads = (data or {}).get("thread", {})
    hist, cycles, total, lo, hi = {}, 0, 0.0, None, None
    for t in threads.values():
        n = int(t.get("cycles", 0))
        cycles += n
        total += float(t.get("avg", 0)) * n
        lo = t["min"] if lo is None else min(lo, t["min"])
        hi = t["max"] if hi is None else max(hi, t["max"])
        for us, count in t.get("histogram", {}).items():
            hist[int(us)] = hist.get(int(us), 0) + int(count)
    if not cycles:
        return {"min_us": None, "avg_us": None, "p99_us": None, "p999_us": None, "max_us": None}

    def pct(p):
        # past the histogram (overflows) there is no exact value: say so
        want, seen = p / 100.0 * cycles, 0
        for us in sorted(hist):
            seen += hist[us]
            if seen >= want:
                return us
        return None

    return {"min_us": lo, "avg_us": round(total / cycles, 2), "p99_us": pct(99),
            "p999_us": pct(99.9), "max_us": hi}


def cyclictest(seconds, workdir):
    path = os.path.join(workdir, "cyclictest.json")
    cmd = ["cyclictest", "-q", "--smp", "-i", "1000", "-h", str(HISTOGRAM_US),
           "-D", f"{int(seconds)}s", f"--json={path}"]
    if os.geteuid() == 0:
        cmd += ["-m", "-p", "90"]
    res = common.run(cmd, timeout=seconds + 60)
    if res is None or res.returncode != 0 or not os.path.exists(path):
        return parse_cyclictest(None)
    with open(path) as f:
        return parse_cyclictest(json.load(f))


def measure(opts=None):
    seconds = 5 if getattr(opts, "quick", False) else 30
    for tool, pkg in (("cyclictest", "rt-tests"), ("stress-ng", "stress-ng")):
        if not common.have(tool):
            raise RuntimeError(f"{tool} is missing: sudo apt install {pkg}")
    out = {}
    with tempfile.TemporaryDirectory(prefix="raye-bench-") as d:
        for k, v in cyclictest(seconds, d).items():
            out["idle_" + k] = v
        load = common.start(["stress-ng", "--cpu", "0", "--timeout", f"{seconds + 30}s"])
        try:
            time.sleep(2)
            for k, v in cyclictest(seconds, d).items():
                out["load_" + k] = v
        finally:
            common.stop(load)
    out["_detail"] = {"rt_priority": os.geteuid() == 0, "seconds": seconds}
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
