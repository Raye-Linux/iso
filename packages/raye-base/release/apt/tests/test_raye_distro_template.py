# SPDX-License-Identifier: GPL-3.0-or-later
"""The python-apt distribution template, as shipped by raye-release.

Without it, aptsources cannot describe the system: add-apt-repository,
software-properties and Synaptic's repository dialog all stop with
NoDistroTemplateException before doing anything at all.

Every check here goes through python-apt itself, on the files of this
tree, so a template that is missing, misnamed, unparsable or missing the
suite of the current codename turns this file red.
"""
import pathlib
import re

import pytest

apt_pkg = pytest.importorskip("apt_pkg", reason="python3-apt is a build dependency")
distinfo = pytest.importorskip("aptsources.distinfo")
distro_mod = pytest.importorskip("aptsources.distro")
sourceslist = pytest.importorskip("aptsources.sourceslist")

TOP = pathlib.Path(__file__).resolve().parents[3]
TEMPLATES = TOP / "release/python-apt"
RELEASE = TOP / "release"
PATHS = TOP / "debian/raye-release-paths"

# Where python-apt looks, and the only name it looks for: DistInfo builds
# the file name from the os-release ID, and SourceEntryMatcher globs
# *.info and uses the base name as the distribution of each template.
INSTALL_DIR = "usr/share/python-apt/templates"

# Names of other distributions must not reach anything a person reads.
OTHER_DISTROS = re.compile(r"ubuntu|canonical|debian|mint|pop!?_?os|kubuntu", re.I)
# Fields python-apt shows in a user interface.
SHOWN_FIELDS = ("Description", "CompDescription", "CompDescriptionLong")


def keyvalues(path):
    """(field, value) of every non-comment line, in file order."""
    out = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        field, sep, value = line.partition(":")
        if sep:
            out.append((field.strip(), value.strip()))
    return out


def osrelease():
    """os-release is shell-style KEY=value, not a tag file."""
    fields = {}
    for line in (RELEASE / "os-release").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip('"')
    return fields


OS = osrelease()
DIST = OS["ID"]
CODENAME = OS["VERSION_CODENAME"]
INFO = TEMPLATES / f"{DIST}.info"
MIRRORS = TEMPLATES / f"{DIST}.mirrors"


def sections(path):
    with apt_pkg.TagFile(str(path)) as tags:
        return [dict(section) for section in tags]


def suites(path):
    return [s for s in sections(path) if "Suite" in s]


# ----------------------------------------------------------------- the files


def test_template_exists_under_the_os_release_id():
    """DistInfo opens <base_dir>/<ID>.info, with the ID of os-release."""
    assert INFO.is_file(), (
        f"{INFO.relative_to(TOP)} is missing: aptsources would raise "
        f"NoDistroTemplateException for {DIST}/{CODENAME}"
    )


def test_mirrors_file_exists():
    assert MIRRORS.is_file()


def test_template_parses_as_a_tag_file():
    assert suites(INFO), "no Suite section: the template carries nothing"


# -------------------------------------------- no dependency on distro-info-data


def test_no_templated_suite():
    """A Suite with a brace sends python-apt to /usr/share/distro-info/<id>.csv.

    distro-info-data has no file for this distribution and never will, so
    every suite is written out. _expand_template only opens the CSV once it
    meets a braced Suite: a single one would raise FileNotFoundError.
    """
    braced = [s["Suite"] for s in suites(INFO) if "{" in s["Suite"]]
    assert not braced, f"templated suites need a distro-info CSV: {braced}"


def test_expands_without_a_distro_info_csv():
    """The real expansion, with a CSV path that cannot exist."""
    lines = list(distinfo._expand_template(str(INFO), "/nonexistent/raye.csv"))
    assert any(line.startswith("Suite:") for line in lines)


# --------------------------------------------------- comments are not comments


def test_every_suite_line_is_parsed_as_a_field():
    """apt_pkg.TagFile has no comment syntax.

    A "#" line inside a paragraph is read as a field name, and its
    continuation lines swallow the real field below it: a comment written
    above "Suite:" makes the whole suite vanish, silently. Counting the
    lines against the parsed sections catches that.
    """
    written = len(re.findall(r"(?m)^Suite:", INFO.read_text()))
    parsed = len(suites(INFO))
    assert parsed == written, (
        f"{written} 'Suite:' lines but {parsed} parsed: a comment inside a "
        "paragraph is eating a field"
    )


def test_no_comment_inside_a_paragraph():
    """Comments belong to the leading paragraph, the README holds the rest."""
    paragraphs = INFO.read_text().split("\n\n")
    for para in paragraphs[1:]:
        bad = [l for l in para.splitlines() if l.lstrip().startswith("#")]
        assert not bad, f"comment inside a paragraph: {bad[0]!r}"


# ----------------------------------------------------------------- the suites


def test_suite_for_the_current_codename():
    """Distribution.get_sources keeps a template only when its name is the
    codename of the running system (is_codename)."""
    names = [s["Suite"] for s in suites(INFO)]
    assert CODENAME in names, f"no 'Suite: {CODENAME}' among {sorted(set(names))}"


def test_every_suite_has_a_match_uri():
    """SourceEntryMatcher drops a template whose match_uri is None, so a
    suite without one is invisible to get_sources."""
    missing = [
        s["Suite"]
        for s in suites(INFO)
        if not any(k == "MatchURI" or k.startswith("MatchURI-") for k in s)
        and "ParentSuite" not in s
    ]
    assert not missing, f"suites without MatchURI: {missing}"


def test_security_updates_and_backports_are_described():
    names = {s["Suite"] for s in suites(INFO)}
    for pocket in ("-security", "-updates", "-backports"):
        assert CODENAME + pocket in names, f"missing {CODENAME}{pocket}"


def test_the_raye_archive_is_a_suite_of_its_own():
    """Raye's own packages must show up in the repository dialog too.

    Checked the way the matcher checks it: re.search of the suite's
    MatchURI against the URI the shipped source really carries, and
    against each server of the shipped mirror list.
    """
    source = dict(keyvalues(RELEASE / "apt/raye.sources"))
    uris = [source["URIs"]]
    for line in (RELEASE / "apt/raye-mirrors.list").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            uris.append(line.split()[0])
    for uri in uris:
        hit = [
            s
            for s in suites(INFO)
            if s["Suite"] == CODENAME
            and "MatchURI" in s
            and re.search(s["MatchURI"], uri)
        ]
        assert hit, f"no suite of {CODENAME} matches {uri}"
        assert "Raye" in hit[0]["Description"]


# -------------------------------------------------------------- what is shown


def test_shown_text_names_no_other_distribution():
    for field, value in keyvalues(INFO):
        if field.split("-")[0] in SHOWN_FIELDS:
            found = OTHER_DISTROS.search(value)
            assert not found, f"{field}: {value!r} names {found.group(0)!r}"


def test_descriptions_name_raye():
    first = [s for s in suites(INFO) if s["Suite"] == CODENAME][0]
    assert "Raye" in first["Description"]


# ------------------------------------------------------- python-apt, for real


def apt_root(tmp_path, sources):
    """An apt tree of our own, so the test never reads the build machine's."""
    etc = tmp_path / "etc/apt"
    (etc / "sources.list.d").mkdir(parents=True)
    (etc / "preferences.d").mkdir(parents=True)
    (etc / "sources.list").write_text(sources)
    apt_pkg.config.set("Dir::Etc", str(etc))
    apt_pkg.config.set("Dir::Etc::sourcelist", str(etc / "sources.list"))
    apt_pkg.config.set("Dir::Etc::sourceparts", str(etc / "sources.list.d"))
    return sourceslist.SourcesList(matcherPath=str(TEMPLATES) + "/")


def test_get_sources_finds_a_template(tmp_path):
    """The exact call that failed on the owner's machine."""
    base = [s for s in suites(INFO) if s["Suite"] == CODENAME and "BaseURI" in s][0]
    entries = f"deb {base['BaseURI']} {CODENAME} main\n"
    slist = apt_root(tmp_path, entries)
    dist = distro_mod.get_distro(
        DIST, CODENAME, OS["PRETTY_NAME"], OS["VERSION_ID"]
    )
    dist.get_sources(slist)  # raises NoDistroTemplateException without the template
    assert dist.source_template is not None
    assert dist.source_template.name == CODENAME
    assert dist.source_template.distribution == DIST


def test_components_of_the_base_suite_are_offered(tmp_path):
    base = [s for s in suites(INFO) if s["Suite"] == CODENAME and "BaseURI" in s][0]
    slist = apt_root(tmp_path, f"deb {base['BaseURI']} {CODENAME} main\n")
    dist = distro_mod.get_distro(
        DIST, CODENAME, OS["PRETTY_NAME"], OS["VERSION_ID"]
    )
    dist.get_sources(slist)
    names = {c.name for c in dist.source_template.components}
    assert {"main", "universe", "restricted", "multiverse"} <= names


def test_codename_is_the_series_a_ppa_resolves_to(tmp_path):
    """add-apt-repository asks the distribution for its codename and builds
    the PPA source with it; a PPA has no 'raye' series."""
    base = [s for s in suites(INFO) if s["Suite"] == CODENAME and "BaseURI" in s][0]
    slist = apt_root(tmp_path, f"deb {base['BaseURI']} {CODENAME} main\n")
    dist = distro_mod.get_distro(
        DIST, CODENAME, OS["PRETTY_NAME"], OS["VERSION_ID"]
    )
    dist.get_sources(slist)
    assert dist.codename == OS["UBUNTU_CODENAME"] == CODENAME


def test_mirrors_file_is_reachable_from_the_template(tmp_path):
    """MirrorsFile names a file next to the template; DistInfo reads it."""
    referenced = {v for f, v in keyvalues(INFO) if f.startswith("MirrorsFile")}
    assert referenced, "no MirrorsFile: the mirror list would never be read"
    for name in referenced:
        assert (TEMPLATES / name).is_file(), f"{name} is referenced but missing"
    info = distinfo.DistInfo(DIST, base_dir=str(TEMPLATES))
    base = [t for t in info.templates if t.name == CODENAME and t.mirror_set]
    assert base, "the base suite carries no mirror"


# -------------------------------------------------------------- what we ship


def test_both_files_are_shipped_by_raye_release():
    """A template kept out of a package would be lost at the next
    python-apt upgrade, which is the whole point of packaging it."""
    shipped = {}
    for line in PATHS.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        shipped.setdefault(parts[0], []).append((parts[1], parts[2]))
    lines = shipped.get("raye-release", [])
    for path in (INFO, MIRRORS):
        src = str(path.relative_to(TOP))
        hit = [
            dest
            for source, dest in lines
            if source.lstrip("?") in (src, "release/python-apt")
            or (source.lstrip("?").endswith("/*") and src.startswith(source.lstrip("?")[:-1]))
        ]
        assert hit, f"{src} is not in debian/raye-release-paths for raye-release"
        assert any(INSTALL_DIR in dest for dest in hit), (
            f"{src} does not go to /{INSTALL_DIR}: python-apt would not find it"
        )
