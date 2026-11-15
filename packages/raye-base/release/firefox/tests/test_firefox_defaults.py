"""What a new Firefox profile gets on Raye.

Settings tells the user "Raye sends no data about you", and Firefox must not
say otherwise on its first page. The file holds defaults, not locks: the user
can turn any of this back on.

No policies.json: any enterprise policy makes Firefox write "Your browser is
being managed by your organization" at the top of its settings, on a home
computer nobody manages. Everything the policies did is a default pref here.
"""

import pathlib
import re
import unittest

FIREFOX = pathlib.Path(__file__).resolve().parent.parent
DEBIAN = FIREFOX.parent.parent / "debian"
PATHS = DEBIAN / "raye-release-paths"
MAINTSCRIPT = DEBIAN / "raye-desktop.maintscript"

LINE = re.compile(r'^pref\("([\w.-]+)", (true|false|-?\d+|"[^"\\]*")\);$')


def read_prefs(text):
    prefs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        m = LINE.match(line)
        if not m:
            raise ValueError("not a plain default pref: " + line)
        name, raw = m.groups()
        if name in prefs:
            raise ValueError("set twice: " + name)
        if raw in ("true", "false"):
            value = raw == "true"
        elif raw.startswith('"'):
            value = raw[1:-1]
        else:
            value = int(raw)
        prefs[name] = value
    return prefs


class Preferences(unittest.TestCase):
    def setUp(self):
        self.text = (FIREFOX / "raye-defaults.js").read_text()
        self.prefs = read_prefs(self.text)

    def expect(self, wanted):
        for name, value in wanted.items():
            self.assertIn(name, self.prefs)
            # assertIs: a "false" string or 0 is not false to Firefox
            if isinstance(value, bool):
                self.assertIs(self.prefs[name], value, name)
            else:
                self.assertEqual(self.prefs[name], value, name)

    def test_only_defaults(self):
        # lockPref takes the choice away, user_pref would only reach one
        # profile, and defaultPref is for autoconfig files, not this folder
        self.assertNotRegex(self.text, r"(?m)^\s*(lockPref|user_pref|defaultPref|sticky_pref)\(")
        self.assertTrue(self.prefs)

    def test_no_data_leaves_for_mozilla(self):
        self.expect({
            "datareporting.healthreport.uploadEnabled": False,
            "datareporting.policy.dataSubmissionEnabled": False,
            "datareporting.usage.uploadEnabled": False,
            "toolkit.telemetry.archive.enabled": False,
            "app.shield.optoutstudies.enabled": False,
            "app.normandy.enabled": False,
        })

    def test_no_bar_about_sending_data(self):
        self.expect({
            "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
            "datareporting.policy.firstRunURL": "",
        })

    def test_no_sponsored_content_and_no_news(self):
        self.expect({
            "browser.newtabpage.activity-stream.showSponsoredTopSites": False,
            "browser.newtabpage.activity-stream.showSponsored": False,
            "browser.newtabpage.activity-stream.feeds.section.topstories": False,
            "browser.newtabpage.activity-stream.feeds.section.highlights": False,
            "browser.newtabpage.activity-stream.showWeather": False,
            "browser.newtabpage.activity-stream.widgets.weather.enabled": False,
            "browser.newtabpage.activity-stream.widgets.enabled": False,
            "browser.urlbar.suggest.quicksuggest.all": False,
            "browser.urlbar.suggest.quicksuggest.sponsored": False,
            "browser.urlbar.quicksuggest.online.enabled": False,
        })

    def test_search_and_shortcuts_stay(self):
        self.expect({
            "browser.newtabpage.activity-stream.showSearch": True,
            "browser.newtabpage.activity-stream.feeds.topsites": True,
        })

    def test_no_questions_on_first_start(self):
        self.expect({
            "browser.shell.checkDefaultBrowser": False,
            "browser.aboutwelcome.enabled": False,
            "startup.homepage_welcome_url": "",
            "startup.homepage_override_url": "",
            "browser.newtabpage.activity-stream.asrouter.userprefs.cfr.addons": False,
            "browser.newtabpage.activity-stream.asrouter.userprefs.cfr.features": False,
            "browser.preferences.moreFromMozilla": False,
        })

    def test_no_terms_of_use_window(self):
        # Firefox 159 shows the window while acceptedVersion is below 4, and
        # re-asks anyone whose acceptedDate is before 2025-12-17 (1765972800000).
        self.expect({"termsofuse.bypassNotification": True})
        self.assertGreaterEqual(self.prefs["termsofuse.acceptedVersion"], 4)
        self.assertGreaterEqual(int(self.prefs["termsofuse.acceptedDate"]), 1765972800000)

    def test_the_first_page_is_rayelinux(self):
        # Firefox opens rayelinux.com when it starts; new tabs stay as they are
        self.expect({
            "browser.startup.homepage": "https://rayelinux.com/",
            "browser.startup.page": 1,
        })

    def test_firefox_speaks_the_language_of_the_session(self):
        self.expect({"intl.locale.requested": ""})

    def test_bookmarks_toolbar_is_shown(self):
        # people expect their bookmarks under the address bar, as in Edge
        self.expect({"browser.toolbars.bookmarks.visibility": "always"})

    def test_file_dialog_goes_through_the_portal(self):
        self.expect({"widget.use-xdg-desktop-portal.file-picker": 1})

    def test_reader_rejects_what_firefox_would_skip(self):
        for bad in ('pref("a.b", False);', 'lockPref("a.b", false);',
                    'pref("a.b", false)', 'pref("a.b", true);\npref("a.b", false);'):
            with self.assertRaises(ValueError, msg=bad):
                read_prefs(bad)


class Shipped(unittest.TestCase):
    def setUp(self):
        self.paths = PATHS.read_text()

    def test_no_enterprise_policy(self):
        self.assertFalse((FIREFOX / "policies.json").exists())
        for line in self.paths.splitlines():
            if line.lstrip().startswith("#"):
                continue
            self.assertNotIn("firefox/policies", line)
            self.assertNotIn("distribution/policies", line)

    def test_prefs_go_where_firefox_reads_them(self):
        # Measured on Firefox 159 (Mozilla's deb): /etc/firefox/defaults/pref
        # is read, /etc/firefox/syspref.js is not.
        self.assertRegex(self.paths, r"(?m)^raye-desktop\s+release/firefox/raye-defaults\.js\s+"
                                     r"etc/firefox/defaults/pref/raye-defaults\.js\s*$")

    def test_an_upgrade_takes_the_old_policy_away(self):
        # /etc files are conffiles: dpkg keeps one the package stops shipping
        text = MAINTSCRIPT.read_text()
        self.assertRegex(text, r"(?m)^rm_conffile /etc/firefox/policies/policies\.json "
                               r"\S+ raye-desktop$")


if __name__ == "__main__":
    unittest.main()
