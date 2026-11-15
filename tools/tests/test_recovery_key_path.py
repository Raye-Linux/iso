#!/usr/bin/env python3
"""Everything that names the recovery key file must name the one the
installer writes.

    python3 -B -m unittest discover -s tools/tests

🚨 Measured 2026-11-06, and it had been wrong since the path changed.
Settings' Security page carries a card -- "Recovery key", with an "Action
needed" badge -- whose visibility is `page.encrypted &&
system.recoveryKeyFile`, and SystemInfo::recoveryKeyFile() tested
`~/Raye recovery key.txt`. The installer writes
`~/.local/share/raye/recovery-key`, and installer/tests/test_encryption.py
ASSERTS the .txt is not created. So the predicate was always false: the
card never appeared on any machine, the "action needed" entry never
appeared in the list of things to do, and its own text told the reader to
go and delete a file that does not exist.

The design note said which side was wrong, in so many words: "recovery key file kept
where the first-run app reads it (~/.local/share/raye/recovery-key, 0600)
instead of the home folder text file. Settings ... reads the recovery key
file: it must read this path." An earlier line of the SAME file still
described the text file, and Settings had followed that stale half.

⚠️ This check derives the path from the installer and never writes it. A
test holding the string itself would freeze today's answer and go green
the day the installer moves the file again -- which is exactly how this
defect was born.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RAYE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

ENCRYPTION = os.path.join(RAYE, "installer", "usr", "lib", "calamares",
                          "modules", "rayeencryption", "main.py")
SYSTEMINFO = os.path.join(RAYE, "settings", "src", "systeminfo.cpp")
STALE = "Raye recovery key.txt"

# Where the stale name may still legitimately appear, and why. Both are in
# the installer tree, which is why the sweep below does not scan it:
#   app/firstrun/main.cpp  suggestedName() -- the file name the "Save a
#                          copy..." dialog offers, into Documents. A name
#                          a person chooses, not a path anyone reads back.
#   rayeencryption/main.py Name= of a .desktop entry: a display string.
SWEPT = ("settings", "handbook", os.path.join("iso", "docs"))


def key_path():
    """`.local/share/raye/recovery-key`, read from the installer."""
    with open(ENCRYPTION, encoding="utf-8") as f:
        m = re.search(r"^KEY_FILE\s*=\s*\(([^)]*)\)", f.read(), re.M)
    assert m, "rayeencryption/main.py no longer declares KEY_FILE"
    parts = re.findall(r'"([^"]+)"', m.group(1))
    assert parts, "KEY_FILE declares no path segments"
    return "/".join(parts)


def swept_files():
    out = []
    for top in SWEPT:
        for base, dirs, names in os.walk(os.path.join(RAYE, top)):
            dirs[:] = [d for d in dirs if d not in (".git", "build", "node_modules")]
            for n in names:
                if n.endswith((".png", ".svg", ".jpg", ".oga", ".pf2", ".deb", ".ico")):
                    continue
                out.append(os.path.join(base, n))
    return out


class RecoveryKeyPathTests(unittest.TestCase):
    def test_the_installer_still_declares_where_it_puts_the_key(self):
        self.assertEqual(key_path(), ".local/share/raye/recovery-key",
                         "the installer moved the key file: follow it in Settings, "
                         "the handbook and iso/docs, then update this expectation")

    def test_settings_reads_the_path_the_installer_writes(self):
        with open(SYSTEMINFO, encoding="utf-8") as f:
            text = f.read()
        want = key_path()
        self.assertIn(want, text,
                      "settings/src/systeminfo.cpp never names %r, so "
                      "recoveryKeyFile() cannot be true and the Security page's "
                      "Recovery key card is invisible on every machine" % want)

    def test_the_sweep_really_reaches_the_files(self):
        """🚨 Without this, the check below passes on an empty list.

        A renamed repository or a changed layout would make a test named
        after the recovery key go green having read nothing -- the defect
        family this tree has paid for a dozen times.
        """
        files = swept_files()
        self.assertGreater(len(files), 200,
                           "the sweep found only %d file(s) under %s: the layout "
                           "moved, and this check was about to prove nothing"
                           % (len(files), ", ".join(SWEPT)))

    def test_nothing_outside_the_installer_still_names_the_old_file(self):
        bad = []
        for path in swept_files():
            try:
                with open(path, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if STALE in line and "until" not in line:
                            bad.append("%s:%d" % (os.path.relpath(path, RAYE), i))
            except (UnicodeDecodeError, OSError):
                continue
        self.assertFalse(bad, "these still name %r, which the installer never "
                              "creates: %s" % (STALE, ", ".join(bad)))


if __name__ == "__main__":
    unittest.main()
