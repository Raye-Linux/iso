# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers shared by the suites and raye-bench."""

import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import time

# systemd writes "1min 2.345s", "345ms", "12us", "1h 2min 3s"
_UNITS = {"h": 3600.0, "min": 60.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6}
_PART = re.compile(r"([\d.]+)\s*(h|min|ms|us|µs|s)\b")


def parse_duration(text):
    """Seconds in a systemd duration, or None."""
    parts = _PART.findall(text or "")
    if not parts:
        return None
    return round(sum(float(n) * _UNITS[u] for n, u in parts), 6)


def have(tool):
    return shutil.which(tool) is not None


def run(cmd, timeout=None, **kw):
    """Run and capture; None when the program is missing."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None


def start(cmd, **kw):
    """Start in its own process group, so a whole app can be stopped."""
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, start_new_session=True, **kw)


def stop(proc, grace=10):
    """SIGTERM the group, then SIGKILL what is left."""
    if proc is None or proc.poll() is not None and not _group_alive(proc.pid):
        return
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            proc.poll()
            if not _group_alive(proc.pid):
                return
            time.sleep(0.1)


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def running(names):
    """True when a process with one of these names (comm) is running."""
    wanted = {n[:15] for n in names}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() in wanted:
                    return True
        except OSError:
            continue
    return False


def percentile(values, p):
    """Nearest-rank percentile of a list of numbers (p in 0..100)."""
    data = sorted(values)
    if not data:
        return None
    rank = max(1, math.ceil(p / 100.0 * len(data)))
    return data[rank - 1]


def aggregate(values):
    """Median and range of the runs; runs that failed (None) are left out."""
    good = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not good:
        return {"median": None, "min": None, "max": None, "values": list(values)}
    return {
        "median": round(statistics.median(good), 4),
        "min": min(good),
        "max": max(good),
        "values": list(values),
    }


def cpus():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1
