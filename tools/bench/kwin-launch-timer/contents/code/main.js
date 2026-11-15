// SPDX-License-Identifier: GPL-3.0-or-later
// Logs one line per new window: when KWin mapped it (wall clock, ms) and
// what it is. raye-bench loads this over D-Bus, starts an app, and reads
// the line back from the journal. Written against the KWin 6.6 API.
// No caption: titles can hold private text and raye-bench does not need it.

function report(window) {
    if (!window || !(window.normalWindow || window.dialog)) {
        return;
    }
    print("raye-launch-timer " + JSON.stringify({
        t: Date.now(),
        cls: String(window.resourceClass || ""),
        name: String(window.resourceName || ""),
        pid: window.pid || 0
    }));
}

workspace.windowAdded.connect(report);
