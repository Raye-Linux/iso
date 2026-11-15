// Firefox on Raye. Defaults only: the user can change any of these, and
// Firefox does not say the browser is managed, as policies would.

// No data sent to Mozilla, and no bar on the first start asking about it.
pref("datareporting.healthreport.uploadEnabled", false);
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("datareporting.usage.uploadEnabled", false);
pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
pref("datareporting.policy.firstRunURL", "");
pref("toolkit.telemetry.archive.enabled", false);
pref("app.shield.optoutstudies.enabled", false);
pref("app.normandy.enabled", false);

// New tab: search and the user's own shortcuts, nothing else.
pref("browser.newtabpage.activity-stream.showSearch", true);
pref("browser.newtabpage.activity-stream.feeds.topsites", true);
pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
pref("browser.newtabpage.activity-stream.showSponsored", false);
pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
pref("browser.newtabpage.activity-stream.feeds.section.highlights", false);
pref("browser.newtabpage.activity-stream.showWeather", false);
pref("browser.newtabpage.activity-stream.widgets.weather.enabled", false);
pref("browser.newtabpage.activity-stream.widgets.enabled", false);

// No sponsored suggestions in the address bar.
pref("browser.urlbar.suggest.quicksuggest.all", false);
pref("browser.urlbar.suggest.quicksuggest.sponsored", false);
pref("browser.urlbar.quicksuggest.online.enabled", false);

// First start: no welcome tour, no default browser question, no terms of
// use window, no "what's new" page after an update.
pref("browser.shell.checkDefaultBrowser", false);
pref("browser.aboutwelcome.enabled", false);
pref("startup.homepage_welcome_url", "");
pref("startup.homepage_override_url", "");

// Firefox opens rayelinux.com when it starts. New tabs keep their own page.
pref("browser.startup.homepage", "https://rayelinux.com/");
pref("browser.startup.page", 1);
pref("termsofuse.bypassNotification", true);
pref("termsofuse.acceptedVersion", 999);
pref("termsofuse.acceptedDate", "1767225600000");
pref("browser.newtabpage.activity-stream.asrouter.userprefs.cfr.addons", false);
pref("browser.newtabpage.activity-stream.asrouter.userprefs.cfr.features", false);
pref("browser.preferences.moreFromMozilla", false);

// The language of the session.
pref("intl.locale.requested", "");
pref("browser.toolbars.bookmarks.visibility", "always");

// Open and save go through the desktop's file dialog.
pref("widget.use-xdg-desktop-portal.file-picker", 1);
// Rounded window corners like the other windows.
pref("widget.gtk.rounded-bottom-corners.enabled", true);
// No "Import bookmarks..." button on a new profile; File > Import stays.
pref("browser.bookmarks.addedImportButton", true);
