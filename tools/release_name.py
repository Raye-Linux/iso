#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The release people read, from ONE place, written everywhere it shows.

The place is two files of this repository:

    VERSION         the release as people say it: "1.0 Beta 2"
    release-names   its name, one line per release: "1.0 Beta 2: Sundog"
                    (shown as "1.0 Beta Sundog": the name takes the place
                    of the beta's number, see shown())

Everything else that shows the release is derived from them, and this tool
is what derives it:

    os-release, lsb-release, issue, issue.net   (raye-release, what Settings >
                                                 About and every tool read)
    python-apt's raye.info                       (the software sources dialog)
    tools/release.conf RELEASE_TITLE, RELEASE    (the publish tools; RELEASE is
                                                 the series: 1.0-beta)
    installer: branding.desc strings, VERSION    (Raye Setup's own words)
    settings, store, handbook: VERSION           (mirrors of iso/VERSION)

    tools/release_name.py              print the release ("1.0 Beta Sundog")
    tools/release_name.py --name       print the name alone (empty if none yet)
    tools/release_name.py --check      exit 1 and name every file out of step
    tools/release_name.py --write      put every file in step (then commit them)

--check and --write take the repositories beside this one (../installer,
../settings...); one that is not checked out is named and left alone.

The image build refuses to start when --check fails, so a name filled in
release-names cannot ship half-applied: fill it, run --write, commit.
"""
import argparse
import pathlib
import re
import sys

ISO = pathlib.Path(__file__).resolve().parent.parent
RELEASE_DIR = pathlib.Path("packages/raye-base/release")
PRODUCT = "Raye Linux"
SHORT_PRODUCT = "Raye"
# a name is letters only: no accent, space, quote or digit
NAME_RE = re.compile(r"[A-Za-z]+")
# "0.5 Beta", "1.0 Beta 2", "1.0", "1.1 Beta"
VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?: Beta(?: \d+)?)?")


class ReleaseError(Exception):
    pass


def read_version(iso=ISO):
    text = (iso / "VERSION").read_text()
    version = text.strip()
    if text != version + "\n" or not VERSION_RE.fullmatch(version):
        raise ReleaseError(f"VERSION is {text!r}: one line, like \"1.0 Beta 2\"")
    return version


def read_names(iso=ISO):
    """release-names as {version: name}; a version may have no name yet ("")."""
    names = {}
    for n, line in enumerate((iso / "release-names").read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        version, colon, name = line.partition(":")
        version, name = version.strip(), name.strip()
        if not colon or not VERSION_RE.fullmatch(version):
            raise ReleaseError(f"release-names line {n}: \"<version>: <Name>\", got {line!r}")
        if name and not NAME_RE.fullmatch(name):
            raise ReleaseError(f"release-names line {n}: the name of {version} is letters only, got {name!r}")
        if version in names:
            raise ReleaseError(f"release-names line {n}: {version} is named twice")
        names[version] = name
    return names


def shown(version, name):
    """The release as people read it. A name takes the place of the beta's
    number: "1.0 Beta 2" named Sundog is "1.0 Beta Sundog", as "1.0 Beta"
    named Brocken was "1.0 Beta Brocken". Without a name the number stays."""
    if not name:
        return version
    without_number = re.sub(r"( Beta) \d+$", r"\1", version)
    return f"{without_number} {name}"


def release(iso=ISO):
    """(version, name, full): ("1.0 Beta 2", "Sundog", "1.0 Beta Sundog")."""
    version = read_version(iso)
    names = read_names(iso)
    if version not in names:
        raise ReleaseError(f"release-names has no line for \"{version}\" (VERSION); add \"{version}:\"")
    name = names[version]
    return version, name, shown(version, name)


def slug(version):
    """The release in a file name or a tag: "1.0 Beta 2" -> "1.0-beta-2"."""
    return version.lower().replace(" ", "-")


def series(version):
    """The folder and tag the publish tools use (release.conf RELEASE): the
    release without the number of its beta, "1.0 Beta 2" -> "1.0-beta".
    Each beta of a series replaces the last one under the same address, so
    the download links people were given keep working."""
    return slug(re.sub(r"( Beta) \d+$", r"\1", version))


# --- what each file says ------------------------------------------------------

def _set_lines(text, rules):
    """rules: [(regex for a whole line, new line)]; each must match once."""
    out = text
    for pattern, new in rules:
        found = re.findall(pattern, out, re.M)
        if len(found) != 1:
            raise ReleaseError(f"expected one line like {pattern!r}, found {len(found)}")
        out = re.sub(pattern, lambda _m: new, out, count=1, flags=re.M)
    return out


def derived(iso, version, full):
    """[(repo, path, transform)]: transform(old text) -> the text it must be."""
    number = version.split()[0]
    pretty = f"{PRODUCT} {full}"
    rel = iso / RELEASE_DIR
    out = [
        ("iso", rel / "os-release", lambda t: _set_lines(t, [
            (r"^PRETTY_NAME=.*$", f'PRETTY_NAME="{pretty}"'),
            (r"^VERSION_ID=.*$", f'VERSION_ID="{number}"'),
            (r"^VERSION=.*$", f'VERSION="{full}"')])),
        ("iso", rel / "lsb-release", lambda t: _set_lines(t, [
            (r"^DISTRIB_RELEASE=.*$", f"DISTRIB_RELEASE={number}"),
            (r"^DISTRIB_DESCRIPTION=.*$", f'DISTRIB_DESCRIPTION="{pretty}"')])),
        ("iso", rel / "issue", lambda t: f"{pretty} \\n \\l\n\n"),
        ("iso", rel / "issue.net", lambda t: f"{pretty}\n"),
        # every paragraph of the template describes this system
        ("iso", rel / "python-apt" / "raye.info",
         lambda t: re.sub(r"^Description: Raye Linux.*$", lambda _m: f"Description: {pretty}", t, flags=re.M)),
        ("iso", iso / "tools" / "release.conf", lambda t: _set_lines(t, [
            (r"^RELEASE=.*$", f"RELEASE={series(version)}"),
            (r"^RELEASE_TITLE=.*$", f"RELEASE_TITLE={pretty}")])),
    ]
    installer = iso.parent / "installer"
    out += [
        ("installer", installer / "VERSION", lambda t: version + "\n"),
        ("installer", installer / "etc/calamares/branding/raye/branding.desc", lambda t: _set_lines(t, [
            (r"^    version:( +).*$", f"    version:             {full}"),
            (r"^    shortVersion:( +).*$", f"    shortVersion:        {full}"),
            (r"^    versionedName:( +).*$", f"    versionedName:       {pretty}"),
            (r"^    shortVersionedName:( +).*$", f"    shortVersionedName:  {SHORT_PRODUCT} {full}")])),
    ]
    for repo in ("settings", "store", "handbook"):
        out.append((repo, iso.parent / repo / "VERSION", lambda t: version + "\n"))
    return out


def run(iso=ISO, write=False, stream=sys.stdout):
    """Check (or write) every derived file. Returns the files out of step."""
    version, _name, full = release(iso)
    if "Description: Raye Linux" not in (iso / RELEASE_DIR / "python-apt" / "raye.info").read_text():
        raise ReleaseError("raye.info has no \"Description: Raye Linux\" line to keep in step")
    drift, missing = [], set()
    for repo, path, transform in derived(iso, version, full):
        if not (iso.parent / repo).is_dir() and repo != "iso":
            missing.add(repo)
            continue
        old = path.read_text()
        new = transform(old)
        if new == old:
            continue
        drift.append(path)
        if write:
            path.write_text(new)
            print(f"wrote {path}", file=stream)
        else:
            print(f"out of step: {path}", file=stream)
    for repo in sorted(missing):
        print(f"note: no {iso.parent / repo} beside this repository, its files were not compared", file=stream)
    return drift


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--name", action="store_true", help="the release name alone")
    group.add_argument("--check", action="store_true", help="exit 1 when a file is out of step")
    group.add_argument("--write", action="store_true", help="put every file in step")
    ap.add_argument("--iso", type=pathlib.Path, default=ISO, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        version, name, full = release(args.iso)
        if args.name:
            print(name)
        elif args.check or args.write:
            drift = run(args.iso, write=args.write)
            if drift and args.check:
                print(f"{len(drift)} file(s) do not say \"{PRODUCT} {full}\": run {args.iso / 'tools/release_name.py'} --write",
                      file=sys.stderr)
                return 1
        else:
            print(full)
    except (ReleaseError, OSError) as error:
        print(f"release_name: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
