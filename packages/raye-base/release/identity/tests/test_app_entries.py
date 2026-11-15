"""The Start entries Raye replaces.

A stock app the user must not meet (a wallet manager, a package tool) stays
installed and runnable and leaves Start and its search. A stock app the user
does need keeps its command under a plain name, in English and French.
"""

import configparser
import pathlib
import re
import unittest

IDENTITY = pathlib.Path(__file__).resolve().parent.parent
APPS = IDENTITY / "apps"
PATHS = IDENTITY.parent.parent / "debian" / "raye-release-paths"

HIDDEN = {
    "org.kde.kdeconnect.sms.desktop": "kdeconnect-sms",
    "org.kde.kmenuedit.desktop": "kmenuedit",
    "org.kde.kwalletmanager.desktop": "kwalletmanager5 %F",
    "synaptic.desktop": "synaptic-pkexec",
    "winetricks.desktop": "winetricks --gui",
}
RENAMED = {
    "org.kde.kdeconnect.app.desktop": ("Your Phone", "Votre téléphone", "kdeconnect-app"),
    "org.kde.partitionmanager.desktop": ("Disk Management", "Gestion des disques", "partitionmanager"),
    "btrfs-assistant.desktop": ("Restore Points", "Points de restauration", "btrfs-assistant-launcher"),
}
BRANDS = re.compile(r"kde|plasma|wine|kwallet|synaptic", re.I)
SHOWN_KEYS = re.compile(r"^(name|genericname|comment)(\[.*\])?$")


def entry(name):
    parser = configparser.RawConfigParser(strict=True, interpolation=None)
    parser.optionxform = str
    parser.read(APPS / name, encoding="utf-8")
    return parser["Desktop Entry"]


class Entries(unittest.TestCase):
    def test_nothing_else_is_in_the_folder(self):
        self.assertEqual({p.name for p in APPS.iterdir()}, set(HIDDEN) | set(RENAMED))

    def test_hidden_entries_are_hidden_and_still_run(self):
        for name, command in HIDDEN.items():
            with self.subTest(name):
                self.assertEqual(entry(name)["NoDisplay"], "true")
                self.assertEqual(entry(name)["Exec"], command)

    def test_renamed_entries_show_and_keep_their_command(self):
        for name, (english, french, command) in RENAMED.items():
            with self.subTest(name):
                e = entry(name)
                self.assertEqual(e["Name"], english)
                self.assertEqual(e["Name[fr]"], french)
                self.assertEqual(e["Exec"], command)
                self.assertNotIn("NoDisplay", e)
                self.assertIn("Comment", e)
                self.assertIn("Comment[fr]", e)

    def test_renamed_entries_can_still_be_found_by_their_old_word(self):
        self.assertIn("kdeconnect", entry("org.kde.kdeconnect.app.desktop")["Keywords"])
        self.assertIn("partition", entry("org.kde.partitionmanager.desktop")["Keywords"])

    def test_no_shown_text_names_the_parts_underneath(self):
        for name in RENAMED:
            for key, value in entry(name).items():
                if SHOWN_KEYS.match(key):
                    self.assertIsNone(BRANDS.search(value), f"{name} {key}={value}")

    def test_only_french_and_english(self):
        for path in APPS.iterdir():
            for key in entry(path.name):
                lang = re.search(r"\[(.*)\]", key)
                if lang:
                    self.assertEqual(lang.group(1), "fr", f"{path.name} {key}")


class Shipped(unittest.TestCase):
    def test_every_entry_takes_the_place_of_the_stock_file(self):
        self.assertRegex(
            PATHS.read_text(),
            r"(?m)^raye-desktop\s+release/identity/apps/\*\.desktop\s+usr/share/applications\s+divert\s*$",
        )


if __name__ == "__main__":
    unittest.main()
