#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""Disk used by the system: what `/` holds, like C: on Windows."""

import json
import pathlib
import shutil
import sys

sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402, F401

NAME = "disk"
PER_BOOT = True


def usage_gib(path="/"):
    u = shutil.disk_usage(path)
    return {"used_gib": round(u.used / 1024 ** 3, 2), "size_gib": round(u.total / 1024 ** 3, 1)}


def measure(opts=None):
    return usage_gib("/")


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
