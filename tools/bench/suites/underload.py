#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Responsiveness under load: the app launches of the launch suite, once
while a compile runs on every CPU and once while a large file is copied.

The compile is the one of the throughput suite, run in a loop; without
make and gcc, stress-ng --cpu takes its place (the report says which).
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402
import launch  # noqa: E402
import throughput  # noqa: E402

NAME = "underload"
PER_BOOT = False


class Loop(threading.Thread):
    """Runs a list of commands over and over until stopped."""

    def __init__(self, commands):
        super().__init__(daemon=True)
        self.commands = commands
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.proc = None

    def run(self):
        while not self.done.is_set():
            for cmd in self.commands:
                with self.lock:
                    if self.done.is_set():
                        return
                    self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL, start_new_session=True)
                self.proc.wait()

    def stop(self):
        with self.lock:
            self.done.set()
            proc = self.proc
        if proc:
            common.stop(proc)
        self.join(timeout=30)


def write_random(path, mib):
    """A file that compression cannot shrink, so the copy really moves data."""
    with open(path, "wb") as f:
        for _ in range(mib):
            f.write(os.urandom(1024 * 1024))


def compile_load(workdir):
    if all(common.have(t) for t in ("make", "gcc")):
        tree = os.path.join(workdir, "compile")
        throughput.write_compile_tree(tree)
        return "compile", Loop([["make", "-s", "-C", tree, "clean"],
                                ["make", "-s", "-C", tree, f"-j{common.cpus()}"]])
    if common.have("stress-ng"):
        return "stress-ng", Loop([["stress-ng", "--cpu", "0", "--timeout", "3600s"]])
    raise RuntimeError("no load to run: sudo apt install build-essential (or stress-ng)")


def measure(opts=None):
    launch.refuse_root()
    names = getattr(opts, "apps", None) or list(launch.APPS)
    quick = getattr(opts, "quick", False)
    folder = getattr(opts, "io_dir", None) or os.path.expanduser("~/.cache/raye-bench")
    copy_mib = 512 if quick else 4096
    os.makedirs(folder, exist_ok=True)
    if shutil.disk_usage(folder).free < copy_mib * 3 * 1024 ** 2:
        raise RuntimeError(f"not enough free space in {folder} for the copy test")
    out, detail, skipped = {}, {}, {}
    stream = launch.EventStream(getattr(opts, "kwin_log", None))
    try:
        with launch.KWinTimer(), tempfile.TemporaryDirectory(prefix="raye-bench-", dir=folder) as d:
            kind, load = compile_load(d)
            detail["cpu_load"] = kind
            load.start()
            time.sleep(5)
            try:
                res, det = launch.time_apps(names, stream)
            finally:
                load.stop()
            out.update({"compile_" + k: v for k, v in res.items()})
            skipped.update({"compile_" + k: v for k, v in det.items()})

            src, dst = os.path.join(d, "copy-source"), os.path.join(d, "copy-target")
            write_random(src, copy_mib)
            load = Loop([["cp", "-f", src, dst], ["sync"]])
            load.start()
            time.sleep(3)
            try:
                res, det = launch.time_apps(names, stream)
            finally:
                load.stop()
            out.update({"copy_" + k: v for k, v in res.items()})
            skipped.update({"copy_" + k: v for k, v in det.items()})
    finally:
        stream.close()
    detail["skipped"] = skipped
    out["_detail"] = detail
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
