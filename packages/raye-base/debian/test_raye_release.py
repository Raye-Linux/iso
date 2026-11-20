# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for debian/raye_release.py, the paths list it reads, the
maintainer scripts it feeds and the staged lines of debian/control."""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TOP = HERE.parent
spec = importlib.util.spec_from_file_location("raye_release", HERE / "raye_release.py")
rr = importlib.util.module_from_spec(spec)
sys.modules["raye_release"] = rr
spec.loader.exec_module(rr)

CONTROL = """\
Source: demo
Build-Depends: debhelper-compat (= 13)

Package: one
Architecture: all
Depends: base-files,
# staged: XX-1
#        later-thing,
         ${misc:Depends}
Description: first

Package: two
Architecture: all
Description: second
"""


def write(path, text="x", mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def tree(tmp_path, paths_text):
    write(tmp_path / "debian/control", CONTROL)
    write(tmp_path / "debian/raye-release-paths", paths_text)
    return tmp_path


def make_plan(root, strict=False):
    return rr.plan(root, strict=strict)


def dests(result, package=None):
    return sorted(d for _, d, p, _ in result.copies if package in (None, p))


# --------------------------------------------------------------- parsing

def test_parse_reads_fields_options_and_comments():
    entries = rr.parse("# a comment\n\n"
                       "one  release/a  usr/bin/a   # trailing\n"
                       "two  ?release/b/*.service  usr/lib/systemd/system  no-start\n")
    assert [(e.package, e.source, e.dest, e.optional, sorted(e.options)) for e in entries] == [
        ("one", "release/a", "usr/bin/a", False, []),
        ("two", "release/b/*.service", "usr/lib/systemd/system", True, ["no-start"]),
    ]
    assert entries[1].is_glob and not entries[0].is_glob


@pytest.mark.parametrize("line", [
    "one release/a",                      # no destination
    "one release/a usr/a nonsense",       # unknown option
    "one /release/a usr/a",               # absolute source
    "one release/../a usr/a",             # leaves the tree
    "one release/a /usr/a",               # absolute destination
    "one release/a usr/a;rm",             # characters a shell would read
    "one release/a usr/$(x)",
    "one release/a?b usr/a",              # "?" is only the optional mark
])
def test_parse_refuses_bad_lines(line):
    with pytest.raises(rr.PathsError):
        rr.parse(line + "\n")


def test_read_packages_skips_comments_inside_fields():
    assert rr.read_packages(CONTROL) == {"one", "two"}


# --------------------------------------------------------------- planning

def test_file_source_goes_to_the_full_destination(tmp_path):
    root = tree(tmp_path, "one release/x/tool usr/libexec/raye-tool\n")
    write(root / "release/x/tool", mode=0o755)
    result = make_plan(root)
    assert result.errors == []
    assert dests(result) == ["usr/libexec/raye-tool"]


def test_folder_source_keeps_its_tree_and_never_ships_tests_or_notes(tmp_path):
    root = tree(tmp_path, "one release/skel etc/skel\n")
    write(root / "release/skel/Desktop/trash.desktop")
    write(root / "release/skel/.config/user-dirs.conf")
    write(root / "release/skel/tests/test_skel.sh", mode=0o755)
    write(root / "release/skel/README")
    write(root / "release/skel/notes.md")
    write(root / "release/skel/__pycache__/x.pyc")
    result = make_plan(root)
    assert result.errors == []
    assert dests(result) == ["etc/skel/.config/user-dirs.conf", "etc/skel/Desktop/trash.desktop"]


def test_glob_puts_files_under_the_destination_by_their_path_after_the_glob(tmp_path):
    root = tree(tmp_path, "one release/boot/*.d/*.conf usr/lib/systemd/system\n"
                          "one release/n/*.notifyrc etc/xdg\n")
    write(root / "release/boot/cups.service.d/raye.conf")
    write(root / "release/boot/tests/x.service.d/raye.conf")
    write(root / "release/n/powerdevil.notifyrc")
    result = make_plan(root)
    assert result.errors == []
    assert dests(result) == ["etc/xdg/powerdevil.notifyrc",
                             "usr/lib/systemd/system/cups.service.d/raye.conf"]


def test_glob_that_matches_nothing(tmp_path):
    root = tree(tmp_path, "one ?release/n/*.notifyrc etc/xdg\n")
    assert make_plan(root).errors == []
    assert make_plan(root, strict=True).errors
    root = tree(tmp_path, "one release/n/*.notifyrc etc/xdg\n")
    assert any("matches nothing" in e for e in make_plan(root).errors)


def test_first_line_that_covers_a_file_wins(tmp_path):
    root = tree(tmp_path, "one release/n/raye-n.notifyrc usr/share/knotifications6/raye-n.notifyrc\n"
                          "two ?release/n/*.notifyrc etc/xdg\n"
                          "two ?release/n usr/share/raye/n\n")
    write(root / "release/n/raye-n.notifyrc")
    write(root / "release/n/powerdevil.notifyrc")
    write(root / "release/n/words.json")
    result = make_plan(root)
    assert result.errors == []
    assert sorted((d, p) for _, d, p, _ in result.copies) == [
        ("etc/xdg/powerdevil.notifyrc", "two"),
        ("usr/share/knotifications6/raye-n.notifyrc", "one"),
        ("usr/share/raye/n/words.json", "two"),
    ]


def test_a_file_named_twice_is_an_error(tmp_path):
    root = tree(tmp_path, "one release/a usr/share/a\none release/a usr/share/b\n")
    write(root / "release/a")
    assert any("listed twice" in e for e in make_plan(root).errors)


def test_a_destination_shipped_twice_is_an_error(tmp_path):
    root = tree(tmp_path, "one release/a usr/share/x\ntwo release/b usr/share/x\n")
    write(root / "release/a")
    write(root / "release/b")
    assert any("shipped twice" in e for e in make_plan(root).errors)


def test_every_release_file_must_be_listed(tmp_path):
    root = tree(tmp_path, "one release/a usr/share/a\n")
    write(root / "release/a")
    write(root / "release/new/thing.service")
    write(root / "release/new/tests/test_thing.py")
    write(root / "release/new/README.md")
    errors = make_plan(root).errors
    assert errors == ["release/new/thing.service: not listed in debian/raye-release-paths"]


def test_missing_sources(tmp_path):
    root = tree(tmp_path, "one release/a usr/share/a\none ?release/b usr/share/b\n")
    result = make_plan(root)
    assert any("release/a: missing" in e for e in result.errors)
    assert not any("release/b" in e for e in result.errors)
    assert any("release/b" in n for n in result.notes)
    assert any("release/b" in e for e in make_plan(root, strict=True).errors)


def test_unknown_package_is_an_error(tmp_path):
    root = tree(tmp_path, "three release/a usr/share/a\n")
    write(root / "release/a")
    assert any("three is not a package" in e for e in make_plan(root).errors)


@pytest.mark.parametrize("dest", ["usr/bin/a", "usr/sbin/a", "usr/libexec/a",
                                  "etc/grub.d/41_a", "etc/update-motd.d/10-a"])
def test_programs_must_be_executable(tmp_path, dest):
    root = tree(tmp_path, f"one release/a {dest}\n")
    write(root / "release/a", mode=0o644)
    assert any("not executable" in e for e in make_plan(root).errors)
    (root / "release/a").chmod(0o755)
    assert make_plan(root).errors == []


def test_no_start_only_on_system_units(tmp_path):
    root = tree(tmp_path, "one release/a.service usr/lib/systemd/user/a.service no-start\n")
    write(root / "release/a.service")
    assert any("no-start" in e for e in make_plan(root).errors)


def test_divert_only_on_a_file(tmp_path):
    root = tree(tmp_path, "one release/d usr/share/d divert\n")
    write(root / "release/d/a")
    assert any("divert" in e for e in make_plan(root).errors)


def test_queries(tmp_path):
    root = tree(tmp_path,
                "one release/grub/raye-update-grub usr/sbin/update-grub divert\n"
                "one ?release/grub/30_raye_windows etc/grub.d/30_raye_windows\n"
                "one release/boot.service usr/lib/systemd/system/raye-boot-ok.service no-start\n"
                "two ?release/xdg/user-dirs.defaults etc/xdg/user-dirs.defaults divert\n"
                "two release/conf.d usr/share/initramfs-tools/conf.d\n")
    write(root / "release/grub/raye-update-grub", mode=0o755)
    write(root / "release/boot.service")
    write(root / "release/conf.d/raye")
    result = make_plan(root)
    assert result.errors == []
    assert rr.diversions(result, "one") == ["/usr/sbin/update-grub"]
    assert rr.diversions(result, "two") == []          # not written yet
    assert rr.no_start(result, "one") == ["raye-boot-ok.service"]
    assert rr.started_units(result, "one") == []
    assert rr.ships(result, "one", "usr/sbin/update-grub")
    assert not rr.ships(result, "one", "etc/grub.d/30_raye_windows")
    assert rr.needs_initramfs(result, "two") and not rr.needs_initramfs(result, "one")


def test_started_units_are_the_other_system_units(tmp_path):
    root = tree(tmp_path, "one release/a.service usr/lib/systemd/system/a.service\n"
                          "one release/b.path usr/lib/systemd/system/b.path no-start\n"
                          "one release/c.service usr/lib/systemd/user/c.service\n"
                          "one release/x.service.d usr/lib/systemd/system/x.service.d\n"
                          "two release/d.timer usr/lib/systemd/system/d.timer\n")
    for name in ("a.service", "b.path", "c.service", "x.service.d/raye.conf", "d.timer"):
        write(root / "release" / name)
    result = make_plan(root)
    assert result.errors == []
    assert rr.started_units(result, "one") == ["a.service"]
    assert rr.no_start(result, "one") == ["b.path"]
    assert rr.started_units(result, "two") == ["d.timer"]


def test_command_line_queries(tmp_path, capsys):
    root = tree(tmp_path, "one release/a usr/sbin/a divert\n")
    write(root / "release/a", mode=0o755)
    assert rr.main(["divert", "one", "--root", str(root)]) == 0
    assert capsys.readouterr().out.split() == ["/usr/sbin/a"]
    assert rr.main(["ships", "one", "usr/sbin/a", "--root", str(root)]) == 0
    assert rr.main(["ships", "one", "usr/sbin/b", "--root", str(root)]) == 1


# --------------------------------------------------------------- install

def test_install_copies_modes_and_links(tmp_path):
    root = tree(tmp_path, "one release/tool usr/libexec/raye-tool\none release/d usr/share/d\n")
    write(root / "release/tool", "#!/bin/sh\n", mode=0o755)
    write(root / "release/d/a", "a")
    os.symlink("a", root / "release/d/b")
    result = make_plan(root)
    assert result.errors == []
    rr.install(result, root)
    staged = root / "debian/one"
    assert os.access(staged / "usr/libexec/raye-tool", os.X_OK)
    assert (staged / "usr/share/d/a").read_text() == "a"
    assert os.readlink(staged / "usr/share/d/b") == "a"


def test_install_refuses_to_follow_a_link_out_of_the_package(tmp_path):
    root = tree(tmp_path, "one release/a usr/share/x/a\n")
    write(root / "release/a")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "debian/one/usr/share").mkdir(parents=True)
    os.symlink(outside, root / "debian/one/usr/share/x")
    with pytest.raises(rr.PathsError):
        rr.install(make_plan(root), root)
    assert not (outside / "a").exists()


# --------------------------------------------------------------- this package

def test_the_real_list_matches_the_tree():
    result = rr.plan(TOP, strict=False)
    assert result.errors == []
    # every optional line is a file a later package writes under release/
    for entry in rr.parse((TOP / "debian/raye-release-paths").read_text()):
        if entry.optional:
            assert entry.source.startswith("release/"), entry


def test_no_optional_line_is_stale():
    """A "?" on a path that is THERE guards nothing, and hides a loss.

    The header of debian/raye-release-paths says it: the day the part
    lands, the "?" goes, because on a path that is there it does nothing
    but hide its disappearance later. Left on, the line is skipped when
    the file vanishes -- a renamed or deleted file stops being shipped and
    the build stays green.

    Nothing counted them until now. Measured 2026-11-06 with this repo's
    own parser: 20 of the 50 optional lines resolved, and were cleared.

    The list is derived here, never written down: a list of expected
    stale lines would go out of date in exactly the way this check is
    meant to catch.
    """
    entries = rr.parse((TOP / "debian/raye-release-paths").read_text())
    optional = [e for e in entries if e.optional]
    assert optional, ("no optional line was parsed at all: either every '?' is "
                      "gone (then drop this check) or the parse looked at the "
                      "wrong file -- an empty sweep must not pass as green")
    stale = sorted(e.source for e in optional if rr._sources(TOP, e))
    assert not stale, (
        f"{len(stale)} optional line(s) of debian/raye-release-paths point at "
        f"something that is there: drop the leading '?' so the build stops if it "
        f"ever goes away -- " + ", ".join(stale))


def test_every_package_of_the_list_is_in_control():
    names = rr.read_packages((TOP / "debian/control").read_text())
    for entry in rr.parse((TOP / "debian/raye-release-paths").read_text()):
        assert entry.package in names, entry


def control_paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if "Package:" in p]


def depends_of(paragraph, field="Depends"):
    """Names in a field, comments left out."""
    value, inside = [], False
    for line in paragraph.splitlines():
        if line.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            if inside:
                value.append(line)
            continue
        inside = line.startswith(field + ":")
        if inside:
            value.append(line.split(":", 1)[1])
    names = set()
    for alt in re.split(r"[,|]", " ".join(value)):
        name = re.sub(r"\(.*?\)", "", alt).strip()
        if name:
            names.add(name)
    return names


def staged_lines(paragraph):
    return [l for l in paragraph.splitlines() if re.match(r"^#\s{2,}\S", l)]


def test_nothing_waits_in_recommends():
    """The image build sets APT::Install-Recommends "false" (iso/build.sh),
    and apt-get install never pulls a Recommends there. So a Recommends is
    not "installed unless you refuse it", it is "never installed", and
    nothing says so at build time. Whatever the image needs is a Depends.
    """
    text = (TOP / "debian/control").read_text()
    for para in control_paragraphs(text):
        name = re.search(r"^Package: (\S+)", para, re.M).group(1)
        rec = depends_of(para, "Recommends")
        assert not rec, (
            f"{name} recommends {sorted(rec)}: the image build has "
            "Recommends off, so it would never be installed"
        )


def test_the_spice_agent_is_a_hard_dependency():
    """Raye in a VM has to work over SPICE with nothing to install: the
    agent carries the clipboard, the resize to the window and a visible
    cursor. As a Recommends it was simply absent from every image."""
    text = (TOP / "debian/control").read_text()
    para = [p for p in control_paragraphs(text) if "Package: raye-desktop" in p][0]
    assert "spice-vdagent" in depends_of(para)


def test_minecraft_deb_finds_the_old_gdk_pixbuf_name():
    """minecraft.net's .deb depends on libgdk-pixbuf2.0-0 (>= 2.22.0),
    a name no package has had since 24.04, so apt refused it outright."""
    text = (TOP / "debian/control").read_text()
    para = [p for p in control_paragraphs(text) if "Package: raye-gaming" in p][0]
    assert "libgdk-pixbuf-2.0-0" in depends_of(para)
    m = re.search(r"^Provides:.*\blibgdk-pixbuf2\.0-0 \(= (\d+)\.(\d+)", para, re.M)
    assert m and (int(m.group(1)), int(m.group(2))) >= (2, 22)


def test_staged_lines_become_valid_depends_lines_when_uncommented():
    text = (TOP / "debian/control").read_text()
    count = 0
    for para in control_paragraphs(text):
        for line in staged_lines(para):
            count += 1
            assert re.match(r"^#( {8})[a-z0-9][a-z0-9+.-]+( \([<>=]+ [^)]+\))?,$", line), line
    assert count > 0


def test_staged_packages_are_not_also_active():
    text = (TOP / "debian/control").read_text()
    for para in control_paragraphs(text):
        active = depends_of(para)
        for line in staged_lines(para):
            name = line.strip("# ,").split(" ")[0]
            assert name not in active, (name, para.splitlines()[0])


def test_desktop_never_pulls_both_sides_of_a_replacement():
    para = next(p for p in control_paragraphs((TOP / "debian/control").read_text())
                if p.startswith("Package: raye-desktop"))
    active = depends_of(para)
    for new, old in (("raye-files", "dolphin"), ("sddm-theme-raye", "sddm-theme-breeze")):
        assert not ({new, old} <= active), (new, old)


# --------------------------------------------------------------- maintainer scripts

def maintscript(tmp_path, name, tokens):
    """The script as dh_installdeb writes it: tokens filled in, debhelper's
    snippets left out, every command it runs logged by fakes on PATH."""
    text = (HERE / name).read_text()
    for key, value in tokens.items():
        text = text.replace(f"#{key}#", value)
    text = text.replace("#DEBHELPER#", "")
    assert "#RAYE_" not in text and "#DEB_" not in text
    script = write(tmp_path / name, text, mode=0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    return script, bin_dir


def fake(bin_dir, name, body=""):
    write(bin_dir / name, f"#!/bin/sh\necho \"{name} $*\" >> \"$LOG\"\n{body}\n", mode=0o755)


def run(script, bin_dir, tmp_path, *args, env=None):
    log = tmp_path / "log"
    log.write_text("")
    environ = {"PATH": f"{bin_dir}:/usr/bin:/bin", "LOG": str(log),
               "DPKG_ROOT": str(tmp_path / "root")}
    environ.update(env or {})
    proc = subprocess.run(["/bin/sh", str(script), *args], env=environ,
                          capture_output=True, text=True)
    return proc, log.read_text().splitlines()


def test_system_preinst_diverts_what_the_build_shipped(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.preinst",
                                  {"RAYE_DIVERT": "/usr/sbin/update-grub"})
    fake(bin_dir, "dpkg-divert")
    proc, log = run(script, bin_dir, tmp_path, "install")
    assert proc.returncode == 0, proc.stderr
    assert log == ["dpkg-divert --package raye-system --add --rename "
                   "--divert /usr/sbin/update-grub.ubuntu /usr/sbin/update-grub"]


def test_system_preinst_with_nothing_to_divert(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.preinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    proc, log = run(script, bin_dir, tmp_path, "upgrade", "0.1")
    assert proc.returncode == 0 and log == []


DIVERSIONS = ("diversion of /usr/sbin/update-grub to /usr/sbin/update-grub.ubuntu by raye-system\n"
              "diversion of /etc/old to /etc/old.ubuntu by raye-system\n"
              "diversion of /etc/other to /etc/other.real by other-package\n"
              "local diversion of /etc/mine to /etc/mine.local\n")


def test_system_postinst_drops_diversions_the_package_no_longer_needs(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "/usr/sbin/update-grub", "RAYE_WINDOWS_ENTRY": ""})
    fake(bin_dir, "dpkg-divert", f'[ "$1" = --list ] && printf "{DIVERSIONS}"\ntrue')
    fake(bin_dir, "dpkg-statoverride", "exit 1")
    fake(bin_dir, "chmod")
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert proc.returncode == 0, proc.stderr
    assert ("dpkg-divert --package raye-system --remove --rename --divert /etc/old.ubuntu /etc/old"
            in log)
    assert not any("--remove" in l and "update-grub" in l for l in log)


def test_system_postinst_turns_off_os_prober_once_the_windows_entry_ships(tmp_path):
    write(tmp_path / "root/etc/grub.d/30_os-prober", mode=0o755)
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": "yes"})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "dpkg-statoverride", '[ "$1" = --list ] && exit 1\ntrue')
    fake(bin_dir, "chmod")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert ("dpkg-statoverride --update --add root root 0644 /etc/grub.d/30_os-prober" in log)
    assert (tmp_path / "root/var/lib/raye-system/os-prober-off").exists()


def test_system_postinst_sets_the_override_even_without_os_prober(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": "yes"})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "dpkg-statoverride", '[ "$1" = --list ] && exit 1\ntrue')
    fake(bin_dir, "chmod")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert "dpkg-statoverride --add root root 0644 /etc/grub.d/30_os-prober" in log


def test_system_postinst_gives_os_prober_back_when_the_entry_goes(tmp_path):
    marker = write(tmp_path / "root/var/lib/raye-system/os-prober-off", "")
    write(tmp_path / "root/etc/grub.d/30_os-prober", mode=0o644)
    write(tmp_path / "root/etc/netplan/01-network-manager-all.yaml", mode=0o644)
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "dpkg-statoverride", "true")
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert proc.returncode == 0, proc.stderr
    assert "dpkg-statoverride --remove /etc/grub.d/30_os-prober" in log
    assert not marker.exists()
    assert os.access(tmp_path / "root/etc/grub.d/30_os-prober", os.X_OK)


def test_system_postrm_undoes_everything(tmp_path):
    write(tmp_path / "root/var/lib/raye-system/os-prober-off", "")
    script, bin_dir = maintscript(tmp_path, "raye-system.postrm", {})
    fake(bin_dir, "dpkg-divert", f'[ "$1" = --list ] && printf "{DIVERSIONS}"\ntrue')
    fake(bin_dir, "dpkg-statoverride", "true")
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert proc.returncode == 0, proc.stderr
    assert sum("--remove --rename" in l for l in log) == 2
    assert "dpkg-statoverride --remove /etc/grub.d/30_os-prober" in log
    proc, log = run(script, bin_dir, tmp_path, "upgrade", "0.2")
    assert log == []


def test_system_postinst_starts_the_upgrade_guard_on_demand_once(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "chmod")
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    # apt-daily-upgrade.service brings it along for each run
    helper = [l for l in log if l.startswith("deb-systemd-helper")]
    assert helper == ["deb-systemd-helper disable unattended-upgrades.service"]
    assert (tmp_path / "root/var/lib/raye-system/upgrade-guard-on-demand").exists()
    # an upgrade leaves alone a guard someone turned back on
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert proc.returncode == 0, proc.stderr
    assert not any(l.startswith("deb-systemd-helper") for l in log)


def test_system_postinst_sets_up_the_firewall(tmp_path):
    root = tmp_path / "root"
    write(root / "usr/libexec/raye-firewall-setup", '#!/bin/sh\necho "setup root=$RAYE_ROOT" >> "$LOG"\n', mode=0o755)
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "chmod")
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert f"setup root={root}" in log


def test_system_postinst_leaves_the_guard_alone_without_the_helper(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-system.postinst",
                                  {"RAYE_DIVERT": "", "RAYE_WINDOWS_ENTRY": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "chmod")
    proc, log = run(script, bin_dir, tmp_path, "configure", "",
                    env={"PATH": f"{bin_dir}:/nonexistent"})
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "root/var/lib/raye-system/upgrade-guard-on-demand").exists()


def test_system_postrm_gives_the_guard_back(tmp_path):
    mark = write(tmp_path / "root/var/lib/raye-system/upgrade-guard-on-demand", "")
    script, bin_dir = maintscript(tmp_path, "raye-system.postrm", {})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "upgrade", "0.2")
    assert proc.returncode == 0, proc.stderr
    assert mark.exists() and log == []
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert proc.returncode == 0, proc.stderr
    assert "deb-systemd-helper enable unattended-upgrades.service" in log
    assert not mark.exists()


def test_desktop_postinst_sets_the_app_defaults(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "flatpak")
    fake(bin_dir, "deb-systemd-helper")
    fake(bin_dir, "ufw", 'echo "Status: inactive"')
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert "flatpak override --system --env=ELECTRON_OZONE_PLATFORM_HINT=auto" in log
    assert not any(l.startswith("ufw allow") for l in log)


def test_desktop_postinst_closes_the_profiles_opened_to_every_network_once(tmp_path):
    # private networks reach the phone and discovery ports; a rule open to
    # any network would reach them from a public one too
    write(tmp_path / "root/etc/ufw/applications.d/raye-phone", "[raye-phone]\n")
    write(tmp_path / "root/etc/ufw/applications.d/raye-network-discovery", "[raye-network-discovery]\n")
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "flatpak")
    fake(bin_dir, "ufw", '[ "$1" = status ] && echo "Status: active"\ntrue')
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.5.20")
    assert proc.returncode == 0, proc.stderr
    assert "ufw delete allow raye-phone" in log
    assert "ufw delete allow raye-network-discovery" in log
    assert not any(l.startswith("ufw allow") for l in log)
    proc, log = run(script, bin_dir, tmp_path, "configure", "1.0~beta2")
    assert not any(l.startswith("ufw") and "status" not in l for l in log)


def test_desktop_postinst_leaves_an_inactive_firewall_alone(tmp_path):
    write(tmp_path / "root/etc/ufw/applications.d/raye-phone", "[raye-phone]\n")
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "flatpak")
    fake(bin_dir, "ufw", 'echo "Status: inactive"')
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert not any(l.startswith("ufw delete") or l.startswith("ufw allow") for l in log)


def test_network_discovery_profile_opens_only_udp_replies():
    profile = (HERE.parent / "release/network/raye-network-discovery").read_text()
    ports = [l.split("=", 1)[1] for l in profile.splitlines() if l.startswith("ports=")]
    # no TCP: nothing on this PC is offered to the network by it
    assert ports == ["3702/udp|5353/udp"]


def test_desktop_postinst_without_flatpak_or_ufw(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    proc, log = run(script, bin_dir, tmp_path, "configure", "",
                    env={"PATH": f"{bin_dir}:/nonexistent"})
    assert proc.returncode == 0, proc.stderr


def test_desktop_postinst_starts_printing_on_demand_once(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    helper = [l for l in log if l.startswith("deb-systemd-helper") and "cups" in l]
    # disabling the service follows its Also= and takes the socket and
    # the path unit with it: they are enabled again after
    assert helper == ["deb-systemd-helper disable cups.service",
                      "deb-systemd-helper enable cups.socket cups.path"]
    assert (tmp_path / "root/var/lib/raye-desktop/cups-on-demand").exists()
    # an upgrade leaves alone a cups.service the user turned back on
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert proc.returncode == 0, proc.stderr
    assert not any(l.startswith("deb-systemd-helper") for l in log)


def test_desktop_postinst_keeps_the_stock_synth_from_sign_in(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "")
    assert proc.returncode == 0, proc.stderr
    assert "deb-systemd-helper --user disable fluidsynth.service" in log
    assert (tmp_path / "root/var/lib/raye-desktop/fluidsynth-off").exists()
    # once only: someone who turns it back on keeps it
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert not any("fluidsynth" in l for l in log)


def test_desktop_postinst_leaves_printing_alone_without_the_helper(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    proc, log = run(script, bin_dir, tmp_path, "configure", "",
                    env={"PATH": f"{bin_dir}:/nonexistent"})
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "root/var/lib/raye-desktop/cups-on-demand").exists()


def test_desktop_postrm_forgets_printing_on_purge_only(tmp_path):
    mark = write(tmp_path / "root/var/lib/raye-desktop/cups-on-demand", "")
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postrm", {})
    fake(bin_dir, "dpkg-divert")
    fake(bin_dir, "flatpak")
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert proc.returncode == 0, proc.stderr
    assert mark.exists()
    proc, log = run(script, bin_dir, tmp_path, "purge")
    assert proc.returncode == 0, proc.stderr
    assert not mark.exists()


def test_desktop_scripts_undo_on_remove(tmp_path):
    write(tmp_path / "root/etc/ufw/applications.d/raye-phone", "[raye-phone]\n")
    script, bin_dir = maintscript(tmp_path, "raye-desktop.prerm", {})
    fake(bin_dir, "ufw", '[ "$1" = status ] && echo "Status: active"\ntrue')
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert proc.returncode == 0, proc.stderr
    assert "ufw delete allow raye-phone" in log
    write(tmp_path / "root/etc/ufw/applications.d/raye-network-discovery", "[raye-network-discovery]\n")
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert "ufw delete allow raye-network-discovery" in log
    script, bin_dir = maintscript(tmp_path, "raye-desktop.postrm", {})
    fake(bin_dir, "dpkg-divert", '[ "$1" = --list ] && echo "diversion of /etc/xdg/user-dirs.defaults '
                                 'to /etc/xdg/user-dirs.defaults.ubuntu by raye-desktop"\ntrue')
    fake(bin_dir, "flatpak")
    proc, log = run(script, bin_dir, tmp_path, "purge")
    assert proc.returncode == 0, proc.stderr
    assert ("dpkg-divert --package raye-desktop --remove --rename --divert "
            "/etc/xdg/user-dirs.defaults.ubuntu /etc/xdg/user-dirs.defaults") in log
    assert "flatpak override --system --unset-env=ELECTRON_OZONE_PLATFORM_HINT" in log


RELEASE_FIXED = ["/usr/lib/os-release", "/etc/lsb-release", "/etc/issue", "/etc/issue.net",
                 "/etc/update-motd.d/10-help-text"]


def test_release_preinst_diverts_the_fixed_files_and_the_motd_one(tmp_path):
    script, bin_dir = maintscript(tmp_path, "raye-release.preinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert")
    proc, log = run(script, bin_dir, tmp_path, "install")
    assert proc.returncode == 0, proc.stderr
    diverted = [l.split()[-1] for l in log]
    assert diverted == RELEASE_FIXED


def test_release_postinst_keeps_the_fixed_diversions(tmp_path):
    listing = "".join(f"diversion of {f} to {f}.ubuntu by raye-release\\n" for f in RELEASE_FIXED)
    listing += "diversion of /etc/update-motd.d/50-motd-news to /etc/update-motd.d/50-motd-news.ubuntu by raye-release\\n"
    script, bin_dir = maintscript(tmp_path, "raye-release.postinst", {"RAYE_DIVERT": ""})
    fake(bin_dir, "dpkg-divert", f'[ "$1" = --list ] && printf "{listing}"\ntrue')
    fake(bin_dir, "deb-systemd-helper")
    proc, log = run(script, bin_dir, tmp_path, "configure", "0.1")
    assert proc.returncode == 0, proc.stderr
    removed = [l.split()[-1] for l in log if "--remove" in l]
    assert removed == ["/etc/update-motd.d/50-motd-news"]


def test_release_postrm_gives_every_file_back(tmp_path):
    listing = "".join(f"diversion of {f} to {f}.ubuntu by raye-release\\n"
                      for f in RELEASE_FIXED)
    script, bin_dir = maintscript(tmp_path, "raye-release.postrm", {})
    fake(bin_dir, "dpkg-divert", f'[ "$1" = --list ] && printf "{listing}"\ntrue')
    proc, log = run(script, bin_dir, tmp_path, "remove")
    assert proc.returncode == 0, proc.stderr
    assert len([l for l in log if "--remove" in l]) == 5


def test_firmware_updates_can_reach_the_uefi_flasher():
    """fwupd flashes a BIOS through fwupdx64.efi, run from the ESP at the
    next start. Under Secure Boot only the signed copy is loaded, and it is
    in its own package: without it every capsule update fails with
    "fwupdx64.efi ... cannot be found" (seen on a Dell Latitude 5420)."""
    text = (TOP / "debian/control").read_text()
    para = [p for p in control_paragraphs(text) if "Package: raye-system" in p][0]
    assert {"fwupd", "fwupd-signed"} <= depends_of(para)


# --- what one binary package needs from another of raye-base ---------------
#
# 2026-11-19: Raye Update installed raye-desktop 1.0 in use and left
# raye-system at 0.5 for the next restart. raye-desktop's sign-in settings
# named /usr/libexec/raye-amd-cursor, which only raye-system 1.0 has: after
# a plain restart, no sign-in screen. A file that names a path another
# package of this source ships needs that package at this version or newer,
# so apt can never bring one without the other.

# pairs that name each other's files and keep working without them; each
# with the reason it is safe. Never add one to make the test pass.
TOLERATED = {
    # raye-kernel-setup runs raye-tpm "quietly; 127 when it is not
    # installed"; raye-system already depends on raye-kernel.
    ("raye-kernel", "raye-system"),
}
SAME_VERSION = re.compile(r"\((?:>=|=) \$\{(?:source|binary):Version\}\)")


def _control_depends():
    """Package -> the text of its Depends (live lines only)."""
    out, pkg, field_ = {}, None, None
    for line in (TOP / "debian/control").read_text().splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("Package:"):
            pkg, field_ = line.split()[1], None
            out[pkg] = ""
        elif re.match(r"^[A-Za-z-]+:", line):
            field_ = line.split(":", 1)[0]
            if field_ in ("Depends", "Pre-Depends") and pkg:
                out[pkg] += " " + line.split(":", 1)[1]
        elif line.startswith((" ", "\t")) and field_ in ("Depends", "Pre-Depends") and pkg:
            out[pkg] += " " + line
    return out


def _depends_on_this_version(depends, other):
    for rel in depends.split(","):
        for alt in rel.split("|"):
            alt = alt.strip()
            if alt.split(" ", 1)[0].split(":", 1)[0] == other and SAME_VERSION.search(alt):
                return True
    return False


def _cross_references():
    """(package, other package) -> [(its file, the other's path it names)]."""
    result = rr.plan(TOP, False)
    owner = {"/" + dest.lstrip("/"): pkg for _src, dest, pkg, _o in result.copies}
    links = []
    for f in (TOP / "debian").glob("*.links"):
        for line in f.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                target, name = line.split()[:2]
                owner.setdefault("/" + name.lstrip("/"), f.name[:-len(".links")])
                links.append((f.name[:-len(".links")], name, "/" + target.lstrip("/")))
    found = {}
    for src, dest, pkg, _o in result.copies:
        try:
            text = pathlib.Path(src).read_text()
        except (UnicodeDecodeError, IsADirectoryError):
            continue
        for path, other in owner.items():
            # a whole path, not the start of a longer one
            if other != pkg and re.search(re.escape(path) + r"(?![\w.-])", text):
                found.setdefault((pkg, other), []).append((dest, path))
    for pkg, name, target in links:
        other = owner.get(target)
        if other and other != pkg:
            found.setdefault((pkg, other), []).append((name, target))
    return found


def test_a_package_naming_another_ones_file_needs_that_version():
    depends = _control_depends()
    refs = _cross_references()
    assert refs, "the scan found nothing: it no longer reads the packages"
    missing = []
    for (pkg, other), where in sorted(refs.items()):
        if (pkg, other) in TOLERATED:
            continue
        if not _depends_on_this_version(depends.get(pkg, ""), other):
            missing.append(f"{pkg} needs '{other} (>= ${{source:Version}})': "
                           + ", ".join(f"{d} names {p}" for d, p in where[:3]))
    assert not missing, "\n".join(missing)


def test_the_tolerated_pairs_are_still_real():
    refs = _cross_references()
    stale = [pair for pair in TOLERATED if pair not in refs]
    assert not stale, f"no longer naming each other, take them out of TOLERATED: {stale}"


def test_desktop_and_system_move_together():
    """The case of 2026-11-19, named on its own."""
    assert _depends_on_this_version(_control_depends()["raye-desktop"], "raye-system")
