#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Disk I/O with fio: 4k random read and write, 1M sequential read and write.

Writes one test file (1 GiB by default) in a new folder inside
~/.cache/raye-bench, or inside the folder given with --io-dir, and deletes
it after. Needs fio.
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = "io"
PER_BOOT = False
JOBS = (  # name, rw, block size, queue depth
    ("randread_4k", "randread", "4k", 32),
    ("randwrite_4k", "randwrite", "4k", 32),
    ("seqread_1m", "read", "1M", 8),
    ("seqwrite_1m", "write", "1M", 8),
)


def parse_fio(data):
    """IOPS, MiB/s and 99th percentile completion latency per job."""
    out = {}
    for job in (data or {}).get("jobs", []):
        name = job.get("jobname", "")
        side = job["read"] if job.get("read", {}).get("io_bytes") else job.get("write", {})
        if not side or not side.get("io_bytes"):
            continue
        pct = side.get("clat_ns", {}).get("percentile", {})
        p99 = pct.get("99.000000")
        out[name] = {
            "iops": round(side.get("iops", 0)),
            "mibs": round(side.get("bw", 0) / 1024, 1),  # fio's bw is KiB/s
            "p99_us": round(p99 / 1000, 1) if p99 is not None else None,
        }
    return out


def fio_command(path, size_mib, seconds, direct):
    cmd = ["fio", "--output-format=json", f"--filename={path}", f"--size={size_mib}M",
           f"--runtime={seconds}", "--time_based", "--ramp_time=2", f"--direct={int(direct)}",
           "--ioengine=libaio", "--numjobs=1", "--randrepeat=0"]
    for name, rw, bs, depth in JOBS:
        cmd += [f"--name={name}", f"--rw={rw}", f"--bs={bs}", f"--iodepth={depth}", "--stonewall"]
    return cmd


def measure(opts=None):
    if not common.have("fio"):
        raise RuntimeError("fio is missing: sudo apt install fio")
    quick = getattr(opts, "quick", False)
    folder = getattr(opts, "io_dir", None) or os.path.expanduser("~/.cache/raye-bench")
    size = getattr(opts, "io_size", None) or (256 if quick else 1024)
    seconds = 5 if quick else 20
    os.makedirs(folder, exist_ok=True)
    if shutil.disk_usage(folder).free < size * 2 * 1024 ** 2:
        raise RuntimeError(f"not enough free space in {folder} for a {size} MiB test file")
    detail = {"folder": folder, "size_mib": size, "direct": True}
    # a private folder of our own: nothing of the user's can be overwritten,
    # even through a link someone left there
    with tempfile.TemporaryDirectory(prefix="raye-bench-", dir=folder) as d:
        path = os.path.join(d, "fio.dat")
        res = common.run(fio_command(path, size, seconds, True), timeout=seconds * 8 + 600)
        if res is not None and res.returncode != 0:
            # tmpfs and some filesystems refuse O_DIRECT; the page cache then
            # flatters the numbers, which the report says
            detail["direct"] = False
            res = common.run(fio_command(path, size, seconds, False), timeout=seconds * 8 + 600)
    if res is not None and res.returncode == 0:
        jobs = parse_fio(json.loads(res.stdout))
    else:
        jobs = {}
        err = (res.stderr.strip().splitlines() or ["no output"])[-1] if res else "fio did not finish"
        detail["note"] = "fio failed: " + err
    out = {}
    for name, rw, _bs, _depth in JOBS:
        j = jobs.get(name, {})
        if rw.startswith("rand"):
            out[f"{name}_iops"] = j.get("iops")
            out[f"{name}_p99_us"] = j.get("p99_us")
        else:
            out[f"{name}_mibs"] = j.get("mibs")
    out["_detail"] = detail
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
