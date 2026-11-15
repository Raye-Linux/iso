#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Memory in use after login, the way people read it: total minus available.

One value per boot, taken 5 minutes after login with nothing open.
"""

import json
import pathlib
import re
import sys

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = "memory"
PER_BOOT = True


def parse_meminfo(text):
    v = {k: int(n) for k, n in re.findall(r"^(\w+):\s+(\d+) kB", text or "", re.M)}
    if "MemTotal" not in v:
        return {"used_mib": None, "total_mib": None, "swap_used_mib": None}
    return {
        "used_mib": (v["MemTotal"] - v.get("MemAvailable", v.get("MemFree", 0))) // 1024,
        "total_mib": v["MemTotal"] // 1024,
        "swap_used_mib": (v.get("SwapTotal", 0) - v.get("SwapFree", 0)) // 1024,
    }


def measure(opts=None):
    with open("/proc/meminfo") as f:
        out = parse_meminfo(f.read())
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    out["_detail"] = {"uptime_s": round(uptime)}
    if uptime < 300:
        out["_detail"]["note"] = "measured less than 5 minutes after boot"
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
