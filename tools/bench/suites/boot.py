#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot: how long this boot took, from systemd's own numbers.

One value per boot: run raye-bench after each of three cold boots and
join the files with --merge.
"""

import json
import pathlib
import re
import sys

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = "boot"
PER_BOOT = True
PARTS = ("firmware", "loader", "kernel", "initrd", "userspace")


def parse_analyze(text):
    """Parts of the boot in seconds from `systemd-analyze`."""
    out = {f"{p}_s": None for p in PARTS}
    line = re.search(r"Startup finished in (.*?)(?: = |$)", text or "", re.M)
    if line:
        for chunk in line.group(1).split(" + "):
            m = re.match(r"\s*(.+?)\s*\((\w+)\)\s*$", chunk)
            if m and m.group(2) in PARTS:
                out[f"{m.group(2)}_s"] = common.parse_duration(m.group(1))
    parts = [v for v in out.values() if v is not None]
    out["total_s"] = round(sum(parts), 3) if parts else None
    g = re.search(r"graphical\.target reached after (.+?) in userspace", text or "")
    graphical = common.parse_duration(g.group(1)) if g else None
    out["graphical_userspace_s"] = graphical
    # The target is "firmware handover to login screen": kernel, initrd
    # and userspace up to graphical.target.
    if graphical is not None and out["kernel_s"] is not None:
        out["handover_to_login_s"] = round(out["kernel_s"] + (out["initrd_s"] or 0) + graphical, 3)
    else:
        out["handover_to_login_s"] = None
    return out


def parse_blame(text, top=15):
    """The slowest units: [[seconds, unit], ...]."""
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(.+?)\s+(\S+\.(?:service|mount|device|socket|target|timer|swap|scope|slice))\s*$", line)
        if not m:
            continue
        sec = common.parse_duration(m.group(1))
        if sec is not None:
            rows.append([sec, m.group(2)])
    rows.sort(key=lambda r: -r[0])
    return rows[:top]


def measure(opts=None):
    res = common.run(["systemd-analyze"], timeout=30)
    text = res.stdout if res and res.returncode == 0 else ""
    out = parse_analyze(text)
    blame = common.run(["systemd-analyze", "blame", "--no-pager"], timeout=30)
    detail = {"blame_top": parse_blame(blame.stdout if blame else "")}
    if not text:
        detail["note"] = (res.stderr.strip() if res else "systemd-analyze is missing") or "no boot time yet"
    out["_detail"] = detail
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
