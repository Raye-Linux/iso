#!/usr/bin/env python3
"""The staged Raye apps, and the terminal Plasma is pointed at.

    python3 -B -m unittest discover -s tools/tests

🚨 Measured 2026-11-06. raye-base/debian/control carries a block of
commented Depends with the instruction « replace the "#" of its line by a
space », and that instruction was a TRAP for eleven of its thirteen names:
their stanzas had been removed from apps/debian/control because the
packages shipped empty -- changelog.gz plus copyright, 1792 bytes,
Installed-Size 9, and their full Depends -- so uncommenting one fails the
ISO build on a dependency nothing provides. Both lists were individually
correct; only reading them together says so.

And the same absence had already cost something visible: theme's kdeglobals
set TerminalApplication=raye-terminal, a binary nothing provides any more,
so every "Open Terminal Here" in the desktop did nothing, silently.

⚠️ Everything here is DERIVED at run time from apps/debian/control. A list
written into this file would freeze today's answer and go green the day an
app is written -- which is exactly how both defects were born.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RAYE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

APPS = os.path.join(RAYE, "apps", "debian", "control")
BASE = os.path.join(RAYE, "iso", "packages", "raye-base", "debian", "control")
KDEGLOBALS = os.path.join(RAYE, "theme", "config", "kdeglobals")


def declared():
    """The packages apps/debian/control really declares."""
    with open(APPS, encoding="utf-8") as f:
        return set(re.findall(r"^Package:\s*(\S+)", f.read(), re.M))


def staged():
    """{"ready": [...], "todo": [...]} from raye-base's commented block."""
    with open(BASE, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, group = {"ready": [], "todo": []}, None
    for line in lines:
        if line.startswith("# staged-ready:"):
            group = "ready"
            continue
        if line.startswith("# staged-todo:"):
            group = "todo"
            continue
        m = re.match(r"^#\s+(\S+),\s*$", line)
        if m and group:
            out[group].append(m.group(1))
        elif group and not line.startswith("#"):
            group = None          # the commented block ended
    return out


def installed_by_the_image():
    """Every package raye-base's own Depends really asks for (uncommented)."""
    with open(BASE, encoding="utf-8") as f:
        text = f.read()
    # Dependency fields ONLY. A first version tokenised every
    # uncommented line, so the Description prose put words like "ready",
    # "machine" and "blocked" into the set -- and
    # TerminalApplication=ready would have passed. Measured 2026-11-06.
    FIELDS = ("Depends:", "Recommends:", "Suggests:", "Pre-Depends:")
    names, inside = set(), False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if any(line.startswith(f) for f in FIELDS):
            inside = True
            line = line.split(":", 1)[1]
        elif inside and line[:1] in (" ", "\t"):
            pass                      # a continuation of the field
        else:
            inside = False
            continue
        for tok in re.findall(r"[a-z0-9][a-z0-9.+-]+", line):
            names.add(tok)
    return names


class StagedPackagesTests(unittest.TestCase):
    def test_the_two_files_are_readable_and_say_something(self):
        """🚨 Without this every check below passes on empty sets."""
        self.assertTrue(declared(), "apps/debian/control declares no package at "
                                    "all: the checks below would prove nothing")
        with open(BASE, encoding="utf-8") as f:
            text = f.read()
        # BOTH markers, not "either group is non-empty". Measured
        # 2026-11-06 while proving this file red: renaming staged-ready
        # alone left todo populated, `ready or todo` stayed truthy, and
        # test_every_ready_name_is_one_apps_declares then swept an EMPTY
        # list and passed. One marker gone is half the comparison gone.
        for marker in ("# staged-ready:", "# staged-todo:"):
            self.assertIn(marker, text,
                          "raye-base/debian/control has no %r line any more, so "
                          "half of this comparison reads nothing and passes. The "
                          "trap this file exists for is back." % marker)
        s = staged()
        self.assertTrue(s["ready"], "the staged-ready group is empty")
        self.assertTrue(s["todo"], "the staged-todo group is empty")

    def test_every_ready_name_is_one_apps_declares(self):
        """Uncommenting a ready line must WORK."""
        missing = sorted(n for n in staged()["ready"] if n not in declared())
        self.assertFalse(missing, "listed under staged-ready in raye-base, but "
                                  "apps/debian/control does not declare them, so "
                                  "uncommenting the line fails the ISO build on an "
                                  "unfindable dependency: %s" % ", ".join(missing))

    def test_no_todo_name_is_already_written(self):
        """And the other way: a package that EXISTS must not sit under
        staged-todo, or it never reaches the image and nothing says why."""
        done = sorted(n for n in staged()["todo"] if n in declared())
        self.assertFalse(done, "apps/debian/control declares them, so they are "
                               "written, but raye-base still lists them under "
                               "staged-todo: move the line up to staged-ready: %s"
                               % ", ".join(done))

    def test_ctrl_alt_del_opens_the_raye_task_manager(self):
        """The sign-out screen launches org.raye.taskmanager.desktop first
        and falls back to the stock system monitor, whose first page asks
        for GPU and disk sensors a fresh install does not have: a red "This
        page is missing some sensors" bar, measured 2026-11-08. So the Raye
        one has to be in the image."""
        self.assertIn("raye-taskmanager", declared())
        self.assertIn("raye-taskmanager", installed_by_the_image(),
                      "raye-base does not install raye-taskmanager, so Task "
                      "Manager on Ctrl+Alt+Del opens the stock monitor")

    def test_plasma_is_pointed_at_a_terminal_the_image_installs(self):
        with open(KDEGLOBALS, encoding="utf-8") as f:
            m = re.search(r"^TerminalApplication=(\S+)", f.read(), re.M)
        self.assertTrue(m, "theme/config/kdeglobals no longer sets "
                           "TerminalApplication: Plasma falls back to its own "
                           "default, which may not be in the image either")
        named = m.group(1)
        self.assertIn(named, installed_by_the_image(),
                      "kdeglobals points Plasma at %r, which raye-base does not "
                      "install, so every \"Open Terminal Here\" does nothing and "
                      "says nothing" % named)


    def test_the_terminal_service_id_agrees_with_the_program(self):
        """⚠️ The OTHER half, and the one a first fix forgot.

        kdeglobals carries two keys. TerminalApplication is the program;
        TerminalService is the .desktop id KDE reads. Changing only the
        first left the desktop pointed at org.raye.terminal.desktop, which
        nothing provides either -- caught on 2026-11-06 by theme's own
        test, not by this file, which then only read one key. A guard that
        checks half of a pair is a guard that lets the other half rot.
        """
        with open(KDEGLOBALS, encoding="utf-8") as f:
            text = f.read()
        prog = re.search(r"^TerminalApplication=(\S+)", text, re.M)
        serv = re.search(r"^TerminalService=(\S+)", text, re.M)
        self.assertTrue(prog and serv,
                        "kdeglobals no longer sets both TerminalApplication and "
                        "TerminalService, so this pair is no longer kept in step")
        program, service = prog.group(1), serv.group(1)

        if service.startswith("org.raye."):
            # Pointing at a Raye app is only allowed once apps ships it.
            stem = service[len("org.raye."):].removesuffix(".desktop")
            self.assertIn("raye-" + stem, declared(),
                          "TerminalService names %r, a Raye service, but "
                          "apps/debian/control does not declare raye-%s, so the "
                          "desktop points at a .desktop nothing provides"
                          % (service, stem))
        else:
            # Otherwise the two keys must describe the same program, or one
            # of them is stale and nothing says which.
            self.assertIn(program, service,
                          "TerminalApplication is %r but TerminalService is %r: "
                          "the two keys name different programs, so one of them "
                          "is stale" % (program, service))

if __name__ == "__main__":
    unittest.main()
