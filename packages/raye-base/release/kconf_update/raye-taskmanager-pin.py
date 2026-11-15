# SPDX-License-Identifier: GPL-3.0-or-later
# Once per account: Start and taskbar pins of KDE System Monitor become
# Raye's Task Manager. Package updates never remove System Monitor, so
# an old pin would keep opening it.
import os
import sys

OLD = "org.kde.plasma-systemmonitor.desktop"
NEW = "org.raye.taskmanager.desktop"


def migrate(text):
    group = ""
    out = []
    for line in text.splitlines(keepends=True):
        bare = line.strip()
        if bare.startswith("["):
            group = bare
        key, eq, value = line.partition("=")
        if eq and OLD in value and group in ("[Start]", "[Taskbar]"):
            end = value[len(value.rstrip("\n")):]
            if key.strip() == "Pinned":
                pins = []
                for pin in value.rstrip("\n").split(","):
                    pin = NEW if pin == OLD else pin
                    if pin not in pins:
                        pins.append(pin)
                line = key + "=" + ",".join(pins) + end
            elif key.strip() == "PinnedFolders":
                line = key + "=" + value.replace(OLD, NEW)
        out.append(line)
    return "".join(out)


def main():
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(config, "rayeshellrc")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return 0
    new = migrate(text)
    if new != text:
        tmp = path + ".raye-new"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
