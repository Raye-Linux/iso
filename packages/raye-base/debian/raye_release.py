#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Puts the files of release/ into the raye-base binary packages.

debian/raye-release-paths says which package ships each file, folder or
glob, and where. This script checks that list against the tree (nothing
missing, nothing left out, no path shipped twice, programs executable)
and copies the files into debian/<package>/. The maintainer scripts and
debian/rules ask it what the build really shipped (files to move aside,
units never to start).

    raye_release.py check               check only
    raye_release.py install             check, then copy
    raye_release.py divert PACKAGE      files PACKAGE puts in place of another package's
    raye_release.py no-start PACKAGE    system units PACKAGE enables but never starts
    raye_release.py units PACKAGE       its other system units
    raye_release.py ships PACKAGE PATH  exit 0 when PACKAGE ships PATH
    raye_release.py triggers            add the initramfs trigger where it is needed
    raye_release.py verify X.deb...     compare built packages with the list

RAYE_PATHS_STRICT=1 makes a missing "?" line an error.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

LIST = "debian/raye-release-paths"
# Every file under these must be listed (or be one never shipped).
SHIPPED_ROOTS = ("release",)
# Never shipped, never required: tests, notes and test byproducts.
SKIPPED_DIRS = ("tests", "__pycache__")
SKIPPED_NAMES = ("README*", "*.md", "*.pyc", "*.pyo", "*~")
# Files under these get run, so they must keep their exec bit.
PROGRAM_DIRS = ("usr/bin/", "usr/sbin/", "usr/libexec/", "etc/grub.d/", "etc/update-motd.d/")
SYSTEM_UNITS = "usr/lib/systemd/system/"
UNIT_SUFFIXES = (".service", ".target", ".timer", ".path", ".socket", ".mount")
INITRAMFS = "usr/share/initramfs-tools/"
OPTIONS = ("divert", "no-start")
# Paths end up in maintainer scripts: nothing a shell would read twice.
SAFE_PATH = re.compile(r"[A-Za-z0-9._@+*\[\]/-]+")
GLOB_CHARS = ("*", "[")
# Added by the packaging tools, not by this list.
DEB_EXTRAS = ("usr/share/doc/", "usr/share/lintian/", "usr/share/man/", "usr/share/bug/")


class PathsError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    package: str
    source: str
    dest: str
    optional: bool
    options: frozenset
    line: int

    @property
    def is_glob(self) -> bool:
        return any(c in self.source for c in GLOB_CHARS)


@dataclass
class Plan:
    copies: list = field(default_factory=list)  # (source path, dest, package, options)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _clean_path(text: str, lineno: int, glob: bool) -> str:
    parts = text.split("/")
    if (not text or text.startswith("/") or text.endswith("/") or ".." in parts
            or "." in parts or "" in parts or not SAFE_PATH.fullmatch(text)
            or (not glob and any(c in text for c in GLOB_CHARS))):
        raise PathsError(f"{LIST} line {lineno}: bad path {text!r}")
    return text


def parse(text: str) -> list[Entry]:
    entries = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) < 3:
            raise PathsError(f"{LIST} line {lineno}: expected 'package source destination [options]'")
        package, source, dest, options = fields[0], fields[1], fields[2], fields[3:]
        bad = [o for o in options if o not in OPTIONS]
        if bad:
            raise PathsError(f"{LIST} line {lineno}: unknown option {bad[0]!r}")
        optional = source.startswith("?")
        source = _clean_path(source[1:] if optional else source, lineno, glob=True)
        dest = _clean_path(dest, lineno, glob=False)
        entries.append(Entry(package, source, dest, optional, frozenset(options), lineno))
    return entries


def read_packages(text: str) -> set[str]:
    """Binary package names of debian/control (comment lines left out)."""
    names = set()
    for line in text.splitlines():
        match = re.match(r"Package:\s*(\S+)", line)
        if match:
            names.add(match.group(1))
    return names


def _skipped(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in SKIPPED_DIRS for p in parts[:-1])
            or any(fnmatch.fnmatch(parts[-1], pat) for pat in SKIPPED_NAMES))


def _files(base: pathlib.Path):
    """Files and symlinks under base (or base itself), relative to base."""
    if base.is_symlink() or base.is_file():
        yield ""
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS
                             and not os.path.islink(os.path.join(dirpath, d)))
        links = [d for d in os.listdir(dirpath)
                 if os.path.islink(os.path.join(dirpath, d)) and os.path.isdir(os.path.join(dirpath, d))]
        for name in sorted(filenames + links):
            rel = os.path.relpath(os.path.join(dirpath, name), base)
            if not _skipped(rel):
                yield rel


def _join(a: str, b: str) -> str:
    return f"{a}/{b}" if b else a


def _glob_matches(root: pathlib.Path, source: str):
    """(source file, path below the glob's fixed folder) for each match."""
    parts = source.split("/")
    fixed = 0
    while fixed < len(parts) and not any(c in parts[fixed] for c in GLOB_CHARS):
        fixed += 1
    base = "/".join(parts[:fixed])
    found = []
    for path in sorted((root / base).glob("/".join(parts[fixed:])) if (root / base).is_dir() else []):
        if path.is_dir() and not path.is_symlink():
            continue
        rel = path.relative_to(root / base).as_posix()
        if not _skipped(rel):
            found.append((_join(base, rel), rel))
    return found


def _sources(root: pathlib.Path, entry: Entry):
    """(source file, destination) pairs one line names."""
    if entry.is_glob:
        return [(src, _join(entry.dest, rel)) for src, rel in _glob_matches(root, entry.source)]
    base = root / entry.source
    if not (base.exists() or base.is_symlink()):
        return None
    return [(_join(entry.source, rel), _join(entry.dest, rel)) for rel in _files(base)]


def _check_options(entry: Entry, dest: str, is_file_line: bool, errors: list) -> None:
    if "no-start" in entry.options and not (dest.startswith(SYSTEM_UNITS)
                                            and dest.endswith(UNIT_SUFFIXES)):
        errors.append(f"line {entry.line}: no-start is for system units, not {dest}")
    if "divert" in entry.options and not (is_file_line or entry.is_glob):
        errors.append(f"line {entry.line}: divert is for files or a glob of files, not a folder")


def plan(root: pathlib.Path, strict: bool) -> Plan:
    root = pathlib.Path(root)
    result = Plan()
    try:
        packages = read_packages((root / "debian/control").read_text())
        entries = parse((root / LIST).read_text())
    except (OSError, PathsError) as exc:
        result.errors.append(str(exc))
        return result

    claimed: dict[str, Entry] = {}  # source file -> line that ships it
    owner: dict[str, Entry] = {}    # destination -> line that ships it
    for entry in entries:
        if entry.package not in packages:
            result.errors.append(f"line {entry.line}: {entry.package} is not a package of debian/control")
            continue
        pairs = _sources(root, entry)
        if not pairs:
            what = "matches nothing" if entry.is_glob else "missing"
            if entry.optional and not strict:
                result.notes.append(f"{entry.source}: not there yet, skipped")
            else:
                result.errors.append(f"{entry.source}: {what} (line {entry.line})")
            continue
        is_file_line = not entry.is_glob and pairs == [(entry.source, entry.dest)]
        for src, dest in pairs:
            if src in claimed:
                # a wider line after a narrower one: the first line wins
                if is_file_line:
                    result.errors.append(f"{src}: listed twice (lines {claimed[src].line} and {entry.line})")
                continue
            claimed[src] = entry
            if dest in owner:
                result.errors.append(f"{dest}: shipped twice (lines {owner[dest].line} and {entry.line})")
                continue
            owner[dest] = entry
            _check_options(entry, dest, is_file_line, result.errors)
            path = root / src
            if (dest.startswith(PROGRAM_DIRS) and not path.is_symlink()
                    and not os.access(path, os.X_OK)):
                result.errors.append(f"{src}: a program, but not executable")
            result.copies.append((path, dest, entry.package, entry.options))

    for top in SHIPPED_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for rel in _files(base):
            src = _join(top, rel)
            if src not in claimed:
                result.errors.append(f"{src}: not listed in {LIST}")
    return result


def diversions(result: Plan, package: str) -> list[str]:
    return sorted("/" + d for _, d, p, o in result.copies if p == package and "divert" in o)


def no_start(result: Plan, package: str) -> list[str]:
    return sorted(os.path.basename(d) for _, d, p, o in result.copies
                  if p == package and "no-start" in o)


def started_units(result: Plan, package: str) -> list[str]:
    """System units of PACKAGE that debhelper may start as usual."""
    return sorted(os.path.basename(d) for _, d, p, o in result.copies
                  if p == package and "no-start" not in o
                  and os.path.dirname(d) + "/" == SYSTEM_UNITS and d.endswith(UNIT_SUFFIXES))


def ships(result: Plan, package: str, dest: str) -> bool:
    return any(p == package and d == dest for _, d, p, _ in result.copies)


def needs_initramfs(result: Plan, package: str) -> bool:
    return any(p == package and d.startswith(INITRAMFS) for _, d, p, _ in result.copies)


def _inside(staged: pathlib.Path, path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(staged)
    except ValueError:
        return False
    return True


def install(result: Plan, root: pathlib.Path) -> None:
    root = pathlib.Path(root)
    for path, dest, package, _ in result.copies:
        staged = (root / "debian" / package).resolve()
        target = staged / dest
        # A symlink to a folder inside the staging tree would otherwise
        # take the copy out of the package, silently.
        if not _inside(staged, target.parent):
            raise PathsError(f"{dest}: lands outside debian/{package}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        if path.is_symlink():
            target.symlink_to(os.readlink(path))
        else:
            shutil.copy2(path, target)


def add_triggers(result: Plan, root: pathlib.Path) -> list[str]:
    """Packages with files for the initramfs get its trigger (dh_installinitramfs
    only looks at hook scripts). Run after dh_installdeb."""
    done = []
    for package in sorted({p for _, _, p, _ in result.copies}):
        if not needs_initramfs(result, package):
            continue
        triggers = pathlib.Path(root) / "debian" / package / "DEBIAN/triggers"
        line = "activate-noawait update-initramfs"
        old = triggers.read_text().splitlines() if triggers.exists() else []
        if line not in old:
            triggers.parent.mkdir(parents=True, exist_ok=True)
            triggers.write_text("\n".join(old + [line]) + "\n")
        done.append(package)
    return done


def compare_deb(expected: set[str], actual: set[str]) -> tuple[list, list]:
    actual = {p for p in actual if not p.startswith(DEB_EXTRAS)}
    return sorted(expected - actual), sorted(actual - expected)


def _deb_files(deb: str) -> tuple[str, set[str]]:
    package = subprocess.run(["dpkg-deb", "-f", deb, "Package"], check=True,
                             capture_output=True, text=True).stdout.strip()
    listing = subprocess.run(["dpkg-deb", "-c", deb], check=True,
                             capture_output=True, text=True).stdout
    files = set()
    for line in listing.splitlines():
        # folders, and links (from debian/*.links), are not in the list
        if line.startswith(("d", "l")):
            continue
        name = line.split(None, 5)[5].split(" -> ")[0]
        files.add(name.removeprefix("./"))
    return package, files


def main(argv=None, env=None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="raye_release.py")
    parser.add_argument("command", choices=("check", "install", "divert", "no-start", "units",
                                            "ships", "triggers", "verify"))
    parser.add_argument("args", nargs="*")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    strict = env.get("RAYE_PATHS_STRICT", "") not in ("", "0")
    root = pathlib.Path(args.root)
    result = plan(root, strict)
    if args.command == "check":
        for note in result.notes:
            print(f"raye-release-paths: {note}")
    elif args.command == "install" and result.notes:
        print(f"raye-release-paths: {len(result.notes)} lines wait for parts not written yet"
              " (\"raye_release.py check\" lists them)")
    for error in result.errors:
        print(f"raye-release-paths: error: {error}", file=sys.stderr)
    if result.errors:
        return 1

    wanted = {"divert": 1, "no-start": 1, "units": 1, "ships": 2}.get(args.command, None)
    if wanted is not None and len(args.args) != wanted:
        parser.error(f"{args.command} needs {wanted} argument(s)")
    if args.command == "install":
        install(result, root)
    elif args.command == "divert":
        print(" ".join(diversions(result, args.args[0])))
    elif args.command == "no-start":
        print(" ".join(no_start(result, args.args[0])))
    elif args.command == "units":
        print(" ".join(started_units(result, args.args[0])))
    elif args.command == "ships":
        return 0 if ships(result, args.args[0], args.args[1]) else 1
    elif args.command == "triggers":
        for package in add_triggers(result, root):
            print(f"raye-release-paths: {package} rebuilds the initramfs")
    elif args.command == "verify":
        expected: dict[str, set[str]] = {}
        for path, dest, package, _ in result.copies:
            if not path.is_symlink():
                expected.setdefault(package, set()).add(dest)
        bad = False
        for deb in args.args:
            package, files = _deb_files(deb)
            missing, extra = compare_deb(expected.get(package, set()), files)
            for path in missing:
                print(f"{package}: missing {path}", file=sys.stderr)
            for path in extra:
                print(f"{package}: not in the list {path}", file=sys.stderr)
            bad = bad or bool(missing or extra)
            print(f"{package}: {len(files)} entries, {'differs' if missing or extra else 'matches'}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
