#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Games: reads MangoHud frame-time logs of a fixed run of a game.

Play the same run three times with MangoHud logging on (Shift+F2 by
default, logs in the folder set by output_folder), then give each CSV
with --mangohud-log. One log is one run. Nothing is played here.

1 % low is the frame rate that 99 % of frames reach or beat
(1000 / the 99th percentile frame time), 0.1 % low the same at 99.9 %.
"""

import csv
import io
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = "games"
PER_BOOT = False
FROM_FILES = True


def parse_mangohud_csv(text):
    lines = (text or "").splitlines()
    start = next((i for i, l in enumerate(lines)
                  if "frametime" in [c.strip() for c in l.split(",")]), None)
    empty = {"avg_fps": None, "low1_fps": None, "low01_fps": None,
             "frametime_p99_ms": None, "frames": 0, "duration_s": None}
    if start is None:
        return empty
    times = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        try:
            ft = float(row["frametime"])
        except (TypeError, ValueError, KeyError):
            continue
        if ft > 0:
            times.append(ft)
    if not times:
        return empty
    total_ms = sum(times)
    p99 = common.percentile(times, 99)
    p999 = common.percentile(times, 99.9)
    return {
        "avg_fps": round(1000.0 * len(times) / total_ms, 2),
        "low1_fps": round(1000.0 / p99, 2),
        "low01_fps": round(1000.0 / p999, 2),
        "frametime_p99_ms": round(p99, 3),
        "frames": len(times),
        "duration_s": round(total_ms / 1000.0, 2),
    }


def newest_csv(path):
    if os.path.isdir(path):
        logs = [os.path.join(path, f) for f in os.listdir(path)
                if f.endswith(".csv") and not f.endswith("_summary.csv")]
        if not logs:
            raise RuntimeError(f"no MangoHud log in {path}")
        return max(logs, key=os.path.getmtime)
    return path


def read_log(path):
    path = newest_csv(path)
    with open(path, errors="replace") as f:
        out = parse_mangohud_csv(f.read())
    out["_detail"] = {"log": os.path.basename(path)}
    return out


def measure(opts=None):
    logs = getattr(opts, "mangohud_log", None) or []
    if not logs:
        raise RuntimeError("give the logs with --mangohud-log FILE (once per run)")
    return read_log(logs[0])


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(read_log(p), indent=2))
