#!/usr/bin/env python3
"""Every raye: key raye-base sends to plymouth is one the boot theme draws.

    python3 -B -m unittest discover -s tools/tests

The Raye theme drops any message that is not one of its own keys, so a
key the theme does not know is a message nobody sees.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RAYE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RELEASE = os.path.join(RAYE, "iso", "packages", "raye-base", "release")
SCRIPT = os.path.join(RAYE, "theme", "plymouth", "raye", "raye.script")

SENT = re.compile(r"display-message\s+--text=[\"']?(raye:[a-z0-9:-]*)")


def sent_keys():
    keys = {}
    for top, dirs, files in os.walk(RELEASE):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
        for name in files:
            path = os.path.join(top, name)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for key in SENT.findall(text):
                keys.setdefault(key, os.path.relpath(path, RAYE))
    return keys


def theme_keys(text):
    body = text.split("fun message(str)", 1)[1].split("\nfun ", 1)[0]
    exact = set(re.findall(r'str == "(raye:[^"]*)"', body))
    prefixes = set(re.findall(r'starts\(str, "(raye:[^"]*)"\)', body))
    return exact, prefixes


class PlymouthKeys(unittest.TestCase):
    def test_theme_draws_every_key_sent(self):
        if not os.path.exists(SCRIPT):
            self.skipTest("the theme is not next to this tree")
        with open(SCRIPT, encoding="utf-8") as f:
            exact, prefixes = theme_keys(f.read())
        keys = sent_keys()
        self.assertIn("raye:go-back", keys)
        unknown = sorted("%s (%s)" % (key, where) for key, where in keys.items()
                         if key not in exact and not any(key.startswith(p) for p in prefixes))
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
