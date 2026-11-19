# SPDX-License-Identifier: GPL-3.0-or-later
"""The Ubuntu mirror of the time zone's country goes first, and only when
it is safe: a mirror of its own, answering, up to date.

Measured on 2026-11-19, so nobody walks this road twice:

- every <cc>.archive.ubuntu.com resolves, even zz: a DNS wildcard sends the
  countries without a mirror to Canonical's servers in London and Boston,
  while archive.ubuntu.com itself now sits behind a CDN. A name that
  resolves proves nothing, and putting us.archive or jp.archive first
  would slow those users down. Only the listed countries go first;
- apt does not leave a failing mirror quickly. With a name that does not
  resolve first in the list, an update of one pocket took 14.5 s instead of
  0.5 s (four tries with growing pauses); with a server that accepts the
  connection and says nothing, minutes (15 s per try, per file). Hence the
  probe before each update, and the day off for a mirror that failed it;
- bg.archive.ubuntu.com answered with a -updates index 10 days old. apt
  takes old indexes without a word, so a stale mirror is caught by its
  date, against the security server's.
"""
import os
import pathlib
import re
import subprocess
import time

import pytest

TOP = pathlib.Path(__file__).resolve().parents[3]
APT = TOP / "release/apt"
SCRIPT = APT / "raye-ubuntu-mirrors"
HOOK = APT / "raye-ubuntu-mirrors.conf"

ZONE_TAB = """\
# a test zone.tab
FR\t+4852+00220\tEurope/Paris
DE\t+5230+01322\tEurope/Berlin
CA\t+4339-07923\tAmerica/Toronto
US\t+404251-0740023\tAmerica/New_York
BG\t+4241+02319\tEurope/Sofia
PT\t+3843-00908\tEurope/Lisbon
"""
ZONE1970_TAB = """\
# a test zone1970.tab
AU,AQ\t-3352+15113\tAustralia/Sydney
"""

NOW = int(time.time())
DAY = 86400


def date_line(epoch):
    return "Date: " + time.strftime("%a, %d %b %Y %H:%M:%S UTC", time.gmtime(epoch))


def lines(path):
    out = []
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            uri, _, meta = line.partition("\t")
            out.append((uri, meta))
    return out


def uris(path):
    return [u for u, _ in lines(path)]


class Machine:
    def __init__(self, root, zone="Europe/Paris"):
        self.root = root
        self.mirrors = root / "etc/apt/mirrors"
        self.mirrors.mkdir(parents=True)
        (self.mirrors / "ubuntu.list").write_text((APT / "ubuntu-mirrors.list").read_text())
        (self.mirrors / "ubuntu-security.list").write_text(
            (APT / "ubuntu-security-mirrors.list").read_text())
        (root / "etc/os-release").write_text('NAME="Raye"\nUBUNTU_CODENAME=resolute\n')
        self.zi = root / "usr/share/zoneinfo"
        for z in ("Europe/Paris", "Europe/Berlin", "America/Toronto", "America/New_York",
                  "Europe/Sofia", "Europe/Lisbon", "Australia/Sydney", "Etc/UTC"):
            f = self.zi / z
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("TZif\n")
        (self.zi / "zone.tab").write_text(ZONE_TAB)
        (self.zi / "zone1970.tab").write_text(ZONE1970_TAB)
        (self.zi / "Old").mkdir()
        (self.zi / "Old/Paris").symlink_to("../Europe/Paris")
        self.lists = root / "var/lib/apt/lists"
        self.lists.mkdir(parents=True)
        self.calls = root / "probe-calls"
        self.answer = root / "probe-answer"
        self.probe = root / "probe"
        self.archive = root / "archive-answer"
        self.archive.write_text("Origin: Ubuntu\n%s\n" % date_line(NOW))
        self.probe.write_text(
            '#!/bin/sh\necho "$1" >> "%s"\n'
            'case "$1" in http://archive.ubuntu.com/*) f="%s" ;; *) f="%s" ;; esac\n'
            '[ -f "$f" ] || exit 7\ncat "$f"\n' % (self.calls, self.archive, self.answer))
        self.probe.chmod(0o755)
        self.set_zone(zone)

    def set_zone(self, zone):
        link = self.root / "etc/localtime"
        if link.is_symlink() or link.exists():
            link.unlink()
        if zone:
            link.symlink_to("/usr/share/zoneinfo/" + zone)

    def mirror_answers(self, epoch=NOW):
        self.answer.write_text("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n"
                               "Origin: Ubuntu\nSuite: resolute-updates\n%s\n" % date_line(epoch))

    def mirror_silent(self):
        if self.answer.exists():
            self.answer.unlink()

    def security_index(self, epoch):
        name = "_etc_apt_mirrors_ubuntu-security-nearby.list_dists_resolute-security_InRelease"
        (self.lists / name).write_text("Origin: Ubuntu\n%s\n" % date_line(epoch))

    def probed(self):
        calls = self.calls.read_text().split() if self.calls.exists() else []
        return [c for c in calls if not c.startswith("http://archive.ubuntu.com/")]

    def run(self, *args):
        env = dict(os.environ, DPKG_ROOT=str(self.root), RAYE_MIRROR_PROBE=str(self.probe))
        return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True,
                              text=True, timeout=60)

    @property
    def nearby(self):
        return self.mirrors / "ubuntu-nearby.list"

    @property
    def security(self):
        return self.mirrors / "ubuntu-security-nearby.list"


@pytest.fixture
def m(tmp_path):
    return Machine(tmp_path)


STOCK_ARCHIVE = ["http://archive.ubuntu.com/ubuntu/", "http://ca.archive.ubuntu.com/ubuntu/",
                 "http://gb.archive.ubuntu.com/ubuntu/"]
STOCK_SECURITY = ["http://security.ubuntu.com/ubuntu/", "http://ca.archive.ubuntu.com/ubuntu/",
                  "http://gb.archive.ubuntu.com/ubuntu/"]
FR = "http://fr.archive.ubuntu.com/ubuntu/"


def test_country_mirror_goes_first_and_security_server_stays_first(m):
    m.mirror_answers()
    r = m.run("--refresh")
    assert r.returncode == 0, r.stderr
    assert uris(m.nearby) == [FR] + STOCK_ARCHIVE
    assert uris(m.security) == [STOCK_SECURITY[0], FR] + STOCK_SECURITY[1:]
    assert m.probed() == [FR + "dists/resolute-updates/InRelease"]


def test_every_server_has_its_own_priority_in_order(m):
    # without a priority apt picks among the servers at random
    m.mirror_answers()
    m.run("--refresh")
    for path in (m.nearby, m.security):
        assert [meta for _, meta in lines(path)] == \
            ["priority:%d" % i for i in range(1, len(lines(path)) + 1)]


def test_no_country_mirror_means_exactly_the_shipped_order(m):
    # Canada: ca.archive.ubuntu.com is Canonical's own server, not a mirror
    m.set_zone("America/Toronto")
    m.mirror_answers()
    m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE
    assert uris(m.security) == STOCK_SECURITY
    assert m.probed() == []


def test_utc_or_no_time_zone_adds_nothing(m):
    for zone in ("Etc/UTC", None):
        m.set_zone(zone)
        m.mirror_answers()
        assert m.run("--refresh").returncode == 0
        assert uris(m.nearby) == STOCK_ARCHIVE
    assert m.probed() == []


def test_a_mirror_that_does_not_answer_is_left_out_for_a_day(m):
    m.mirror_silent()
    r = m.run("--refresh")
    assert r.returncode == 0
    assert uris(m.nearby) == STOCK_ARCHIVE
    assert "left out for a day" in r.stderr
    assert len(m.probed()) == 1
    # the next update does not wait for it again
    m.mirror_answers()
    m.run("--refresh")
    assert len(m.probed()) == 1
    assert uris(m.nearby) == STOCK_ARCHIVE
    # a day later it is asked again
    skip = m.root / "var/lib/raye-system/ubuntu-country-mirror.skip"
    skip.write_text("fr %d\n" % (NOW - 1))
    m.run("--refresh")
    assert len(m.probed()) == 2
    assert uris(m.nearby)[0] == FR


def test_offline_leaves_the_mirror_out_this_time_only(m):
    # no answer from anybody: the network is down (or the installer's
    # chroot has no name service), which says nothing about the mirror
    m.mirror_silent()
    m.archive.unlink()
    r = m.run("--refresh")
    assert r.returncode == 0
    assert uris(m.nearby) == STOCK_ARCHIVE
    assert not (m.root / "var/lib/raye-system/ubuntu-country-mirror.skip").exists()
    m.mirror_answers()
    m.archive.write_text("Origin: Ubuntu\n%s\n" % date_line(NOW))
    m.run("--refresh")
    assert uris(m.nearby)[0] == FR


def test_a_mirror_days_behind_the_security_server_is_left_out(m):
    m.security_index(NOW)
    m.mirror_answers(NOW - 3 * DAY)
    r = m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE
    assert "3 days behind" in r.stderr


def test_a_mirror_a_few_hours_behind_is_fine(m):
    m.security_index(NOW)
    m.mirror_answers(NOW - 6 * 3600)
    m.run("--refresh")
    assert uris(m.nearby)[0] == FR


def test_old_without_a_security_index_is_judged_against_the_clock(m):
    m.mirror_answers(NOW - 10 * DAY)
    m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE


def test_an_answer_without_a_date_is_no_answer(m):
    m.answer.write_text("<html>Not Found</html>\n")
    m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE


def test_a_skip_for_another_country_does_not_count(m):
    skip = m.root / "var/lib/raye-system/ubuntu-country-mirror.skip"
    skip.parent.mkdir(parents=True)
    skip.write_text("de %d\n" % (NOW + DAY))
    m.mirror_answers()
    m.run("--refresh")
    assert uris(m.nearby)[0] == FR


def test_a_new_time_zone_is_picked_up_at_the_next_update(m):
    m.mirror_answers()
    m.run("--refresh")
    m.set_zone("Europe/Berlin")
    m.run("--refresh")
    assert uris(m.nearby) == ["http://de.archive.ubuntu.com/ubuntu/"] + STOCK_ARCHIVE
    m.set_zone("America/New_York")
    m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE


def test_https_mirrors_are_written_as_https(m):
    m.set_zone("Europe/Lisbon")
    m.mirror_answers()
    m.run("--refresh")
    assert uris(m.nearby)[0] == "https://pt.archive.ubuntu.com/ubuntu/"


def test_zone1970_and_old_zone_names_find_their_country(m):
    m.set_zone("Australia/Sydney")
    m.mirror_answers()
    m.run("--refresh")
    assert uris(m.nearby)[0] == "http://au.archive.ubuntu.com/ubuntu/"
    m.set_zone("Old/Paris")
    m.run("--refresh")
    assert uris(m.nearby)[0] == FR


def test_etc_timezone_when_localtime_is_not_a_link(m):
    m.set_zone(None)
    (m.root / "etc/timezone").write_text("Europe/Paris\n")
    m.mirror_answers()
    m.run("--refresh")
    assert uris(m.nearby)[0] == FR


def test_a_strange_zone_name_is_not_used(m):
    m.set_zone(None)
    (m.root / "etc/timezone").write_text("Europe/Paris$(touch /tmp/x)\n")
    m.mirror_answers()
    assert m.run("--refresh").returncode == 0
    assert uris(m.nearby) == STOCK_ARCHIVE


def test_the_conffiles_are_never_written(m):
    before = {p.name: p.read_bytes() for p in m.mirrors.iterdir()}
    m.mirror_answers()
    m.run()
    m.run("--refresh")
    for name, data in before.items():
        assert (m.mirrors / name).read_bytes() == data


def test_the_owners_servers_and_metadata_are_kept_in_their_order(m):
    (m.mirrors / "ubuntu.list").write_text(
        "# mine\nhttp://mirror.example.org/ubuntu/\tpriority:5 type:deb\n"
        "http://archive.ubuntu.com/ubuntu/\tpriority:1\n"
        "http://fr.archive.ubuntu.com/ubuntu/\tpriority:2\n")
    m.mirror_answers()
    m.run("--refresh")
    assert lines(m.nearby) == [
        (FR, "priority:1"),
        ("http://archive.ubuntu.com/ubuntu/", "priority:2"),
        ("http://mirror.example.org/ubuntu/", "priority:3 type:deb"),
    ]


def test_a_missing_conffile_still_gives_a_working_list(m):
    (m.mirrors / "ubuntu.list").unlink()
    (m.mirrors / "ubuntu-security.list").write_text("# all commented out\n")
    m.set_zone("America/Toronto")
    m.run("--refresh")
    assert uris(m.nearby) == STOCK_ARCHIVE
    assert uris(m.security) == STOCK_SECURITY


def test_nothing_is_rewritten_when_nothing_changed(m):
    m.mirror_answers()
    m.run("--refresh")
    os.utime(m.nearby, (1, 1))
    m.run("--refresh")
    assert m.nearby.stat().st_mtime == 1
    assert not list(m.mirrors.glob("*.raye-tmp"))
    assert oct(m.nearby.stat().st_mode & 0o777) == "0o644"


def test_refresh_leaves_the_sources_alone(m):
    src = m.root / "etc/apt/sources.list.d/ubuntu.sources"
    src.parent.mkdir(parents=True)
    src.write_text("Types: deb\nURIs: mirror+file:/etc/apt/mirrors/ubuntu.list\n")
    m.run("--refresh")
    assert "ubuntu-nearby" not in src.read_text()


def test_unknown_option_fails_without_writing(m):
    assert m.run("--nope").returncode == 2
    assert not m.nearby.exists()


# ------------------------------------------------------------ the table

def script_words(name):
    text = SCRIPT.read_text()
    block = re.search(r'^%s="([^"]*)"' % name, text, re.M | re.S).group(1)
    return block.split()


def test_countries_answered_by_canonicals_own_servers_are_not_listed():
    # measured: these resolve to the DNS wildcard, i.e. Canonical's own
    # servers, slower than archive.ubuntu.com's CDN for most of the world
    listed = set(script_words("COUNTRIES")) | set(script_words("COUNTRIES_HTTPS"))
    for cc in ("us", "ca", "gb", "jp", "in", "za", "mx", "ar", "ng", "eg", "pk"):
        assert cc not in listed
    # measured broken or stale on 2026-11-19
    for cc in ("gl", "bg", "ba"):
        assert cc not in listed


def test_the_table_holds_real_iso_codes_once():
    words = script_words("COUNTRIES") + script_words("COUNTRIES_HTTPS")
    assert len(words) == len(set(words))
    assert all(re.fullmatch(r"[a-z]{2}", w) for w in words)
    iso = pathlib.Path("/usr/share/zoneinfo/iso3166.tab")
    if iso.exists():
        known = {l.split("\t")[0].lower() for l in iso.read_text().splitlines()
                 if l and not l.startswith("#")}
        assert set(words) <= known


@pytest.mark.skipif(os.environ.get("RAYE_NET_TESTS") != "1",
                    reason="asks the Internet; RAYE_NET_TESTS=1 to run")
def test_listed_mirrors_still_answer_with_resolute():
    stale = []
    for cc in script_words("COUNTRIES") + script_words("COUNTRIES_HTTPS"):
        scheme = "https" if cc in script_words("COUNTRIES_HTTPS") else "http"
        out = subprocess.run(
            ["curl", "-fsS", "--max-time", "10", "-r", "0-1023",
             "%s://%s.archive.ubuntu.com/ubuntu/dists/resolute-updates/InRelease" % (scheme, cc)],
            capture_output=True, text=True)
        if "Date:" not in out.stdout:
            stale.append(cc)
    assert not stale, "these no longer answer: %s" % stale


# ------------------------------------------------------------- the hook

def test_the_hook_runs_before_each_update_and_cannot_stop_it(tmp_path):
    try:
        dump = subprocess.run(["apt-config", "-c", str(HOOK), "dump"], capture_output=True,
                              text=True, timeout=30)
    except FileNotFoundError:
        pytest.skip("apt-config is not installed here")
    assert dump.returncode == 0, dump.stderr
    cmds = re.findall(r'^APT::Update::Pre-Invoke:: "(.*)";$', dump.stdout, re.M)
    assert len(cmds) == 1
    cmd = cmds[0].replace('\\"', '"')
    assert "--refresh" in cmd and "|| true" in cmd
    # script missing, or failing: apt is told everything went well
    fake = tmp_path / "usr/libexec/raye-ubuntu-mirrors"
    for body in (None, "#!/bin/sh\nexit 9\n"):
        c = cmd.replace("/usr/libexec/raye-ubuntu-mirrors", str(fake))
        if body:
            fake.parent.mkdir(parents=True, exist_ok=True)
            fake.write_text(body)
            fake.chmod(0o755)
        assert subprocess.run(["sh", "-c", c]).returncode == 0


def test_raye_system_ships_the_hook():
    paths = [l.split() for l in (TOP / "debian/raye-release-paths").read_text().splitlines()]
    hook = [p for p in paths if len(p) >= 3 and p[1] == "release/apt/raye-ubuntu-mirrors.conf"]
    assert hook == [["raye-system", "release/apt/raye-ubuntu-mirrors.conf",
                     "etc/apt/apt.conf.d/59raye-ubuntu-mirrors"]]
