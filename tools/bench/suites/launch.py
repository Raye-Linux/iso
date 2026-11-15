#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-3.0-or-later
"""App launch: seconds from starting an app to KWin mapping its window.

The window time comes from kwin-launch-timer, a KWin script loaded over
D-Bus that logs every new window. Apps that are already open are skipped:
close them first, or the number would only measure a new window.
"""

import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep the tool folder clean
sys.path.insert(0, str(HERE))
import common  # noqa: E402

NAME = "launch"
PER_BOOT = False
SCRIPT = HERE.parent / "kwin-launch-timer" / "contents" / "code" / "main.js"
PLUGIN = "raye-launch-timer"
MARK = "raye-launch-timer "

# key: (command, window class parts, process names that mean "already open")
APPS = {
    "files": (["dolphin"], ("dolphin",), ("dolphin",)),
    "browser": (["firefox", "--new-window", "about:blank"], ("firefox",), ("firefox", "firefox-bin")),
    "settings": (["raye-settings"], ("org.raye.settings", "raye-settings"), ("raye-settings",)),
    "terminal": (["konsole"], ("konsole",), ("konsole",)),
    "store": (["raye-store"], ("org.raye.store", "raye-store"), ("raye-store",)),
}


def parse_event(line):
    """One kwin-launch-timer line from the journal or KWin's log, or None."""
    i = line.find(MARK)
    if i < 0:
        return None
    try:
        ev = json.loads(line[i + len(MARK):].strip())
    except ValueError:
        return None
    if not isinstance(ev, dict) or not isinstance(ev.get("t"), (int, float)):
        return None
    return {"t": ev["t"] / 1000.0, "cls": str(ev.get("cls", "")),
            "name": str(ev.get("name", "")), "pid": ev.get("pid", 0)}


def matches(ev, parts):
    text = (ev["cls"] + " " + ev["name"]).lower()
    return any(p in text for p in parts)


def window_delay(events, t0, parts):
    """Seconds from t0 to the first matching window mapped after it."""
    for ev in events:
        if ev["t"] >= t0 and matches(ev, parts):
            return round(ev["t"] - t0, 3)
    return None


class EventStream:
    """Follows the user journal (or a log file) for timer lines."""

    def __init__(self, log_file=None):
        self.q = queue.Queue()
        self.events = []
        self._stop = threading.Event()
        self._proc = None
        if log_file:
            self._thread = threading.Thread(target=self._follow_file, args=(log_file,), daemon=True)
        else:
            self._proc = subprocess.Popen(
                ["journalctl", "--user", "-f", "-n", "0", "-o", "cat", "--no-pager"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            self._thread = threading.Thread(target=self._follow_pipe, daemon=True)
        self._thread.start()

    def _follow_pipe(self):
        for line in self._proc.stdout:
            self._push(line)

    def _follow_file(self, path):
        with open(path, errors="replace") as f:
            f.seek(0, 2)
            while not self._stop.is_set():
                line = f.readline()
                if line:
                    self._push(line)
                else:
                    time.sleep(0.02)

    def _push(self, line):
        ev = parse_event(line)
        if ev:
            self.q.put(ev)

    def wait(self, t0, parts, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                self.events.append(self.q.get(timeout=0.05))
            except queue.Empty:
                pass
            d = window_delay(self.events, t0, parts)
            if d is not None:
                return d
        return None

    def close(self):
        self._stop.set()
        if self._proc:
            self._proc.terminate()


def _dbus(method, sig="", *args):
    """Call KWin's scripting object on the session bus."""
    if common.have("busctl"):
        cmd = ["busctl", "--user", "call", "org.kde.KWin", "/Scripting",
               "org.kde.kwin.Scripting", method] + ([sig] if sig else []) + [str(a) for a in args]
    else:
        cmd = ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting." + method] + [str(a) for a in args]
    res = common.run(cmd, timeout=10)
    return res is not None and res.returncode == 0


class KWinTimer:
    """Loads kwin-launch-timer for the time of a measure."""

    def __enter__(self):
        _dbus("unloadScript", "s", PLUGIN)  # a copy left by a run that was killed
        if not _dbus("loadScript", "ss", str(SCRIPT), PLUGIN) or not _dbus("start"):
            raise RuntimeError("KWin did not load the launch timer (is this a Plasma session?)")
        return self

    def __exit__(self, *exc):
        _dbus("unloadScript", "s", PLUGIN)


def refuse_root():
    if os.geteuid() == 0:
        raise RuntimeError("app launches run as your user, in your session: run this suite without sudo")


def time_apps(names, stream, timeout=60, settle=3.0):
    """Launch each app once; seconds to its window, None if it never came."""
    out, detail = {}, {}
    for key in names:
        cmd, parts, procs = APPS[key]
        if not common.have(cmd[0]):
            out[f"{key}_s"], detail[key] = None, "not installed"
            continue
        if common.running(procs):
            out[f"{key}_s"], detail[key] = None, "already open"
            continue
        t0 = time.time()
        proc = common.start(cmd)
        try:
            out[f"{key}_s"] = stream.wait(t0, parts, timeout)
            if out[f"{key}_s"] is None:
                detail[key] = "no window within %d s" % timeout
        finally:
            common.stop(proc)
        time.sleep(settle)
    return out, detail


def measure(opts=None):
    refuse_root()
    names = getattr(opts, "apps", None) or list(APPS)
    log_file = getattr(opts, "kwin_log", None)
    stream = EventStream(log_file)
    try:
        with KWinTimer():
            time.sleep(0.5)
            out, detail = time_apps(names, stream)
    finally:
        stream.close()
    out["_detail"] = {"skipped": detail}
    return out


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
