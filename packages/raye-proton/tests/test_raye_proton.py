"""Raye Proton: GE-Proton built by Raye, named for Steam, offered in both
Steams and set as their default for Windows games when nobody chose."""
import hashlib
import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import subprocess
import tarfile

import pytest

HERE = pathlib.Path(__file__).resolve().parent.parent
RAYE = HERE / "raye"

TEMPLATE = '''"compatibilitytools"
{
  "compat_tools"
  {
    "raye-proton" // Internal name of this tool
    {
      "install_path" "."

      // For this template, we're going to substitute the display_name key in here, e.g.:
      "display_name" "raye-proton"

      "from_oslist"  "windows"
      "to_oslist"    "linux"
    }
  }
}
'''

CONFIG = '''"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"AutoUpdateWindowEnabled"\t\t"0"
\t\t\t\t"CompatToolMapping"
\t\t\t\t{
\t\t\t\t\t"391540"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"proton_9"
\t\t\t\t\t\t"config"\t\t""
\t\t\t\t\t\t"priority"\t\t"250"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\t"SurveyDate"\t\t"2026-11-25"
\t\t\t}
\t\t}
\t}
\t"Music"
\t{
\t\t"CrawlSteamInstallFolders"\t\t"1"
\t}
}
'''


def load_default():
    loader = importlib.machinery.SourceFileLoader("rpd", str(RAYE / "raye-proton-default"))
    spec = importlib.util.spec_from_loader("rpd", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


rpd = load_default()


def make_tool(where, bridge=True, version="1764100000 raye-proton\n"):
    where.mkdir(parents=True, exist_ok=True)
    (where / "compatibilitytool.vdf").write_text(TEMPLATE.replace('"raye-proton"\n', '"Raye Proton"\n'))
    (where / "proton").write_text("#!/usr/bin/env python3\n")
    (where / "proton").chmod(0o755)
    (where / "version").write_text(version)
    if bridge:
        b = where / rpd.BRIDGE
        b.parent.mkdir(parents=True)
        b.write_bytes(b"MZ")
    return where


def mapping(text):
    steam = rpd.parse(text).get("InstallConfigStore").get("Software").get("Valve").get("Steam")
    return steam.get("CompatToolMapping")


def run_default(home, proc, tool, *args):
    env = dict(os.environ, HOME=str(home), RAYE_PROC=str(proc), RAYE_PROTON_SRC=str(tool))
    return subprocess.run([str(RAYE / "raye-proton-default"), *args], env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def world(tmp_path):
    home = tmp_path / "home"
    proc = tmp_path / "proc"
    proc.mkdir()
    tool = make_tool(tmp_path / "system" / "raye-proton")
    apt = home / ".local/share/Steam"
    (apt / "config").mkdir(parents=True)
    (apt / "config/config.vdf").write_text(CONFIG)
    return home, proc, tool, apt


# ---- the name ------------------------------------------------------------
def test_the_build_is_named_raye_proton_for_steam(tmp_path):
    (tmp_path / "compatibilitytool.vdf").write_text(TEMPLATE)
    subprocess.run(["sh", str(RAYE / "raye-proton-name"), str(tmp_path)], check=True)
    out = (tmp_path / "compatibilitytool.vdf").read_text()
    assert '"display_name" "Raye Proton"' in out
    # the name Steam remembers games by stays raye-proton
    assert rpd.tool_name(str(tmp_path / "compatibilitytool.vdf")) == ["raye-proton"]
    assert out.replace('"Raye Proton"', '"raye-proton"') == TEMPLATE


def test_another_tool_is_not_renamed(tmp_path):
    (tmp_path / "compatibilitytool.vdf").write_text(TEMPLATE.replace("raye-proton", "GE-Proton11-14"))
    r = subprocess.run(["sh", str(RAYE / "raye-proton-name"), str(tmp_path)], capture_output=True)
    assert r.returncode != 0


# ---- the archives --------------------------------------------------------
def test_only_the_pinned_archives_are_packaged(tmp_path):
    shutil.copy(HERE / "build-ge.sh", tmp_path)
    shutil.copy(HERE / "ge-version.txt", tmp_path)
    up = tmp_path / "up"
    up.mkdir()
    for n in ("raye-proton.tar.gz", "raye-proton-licenses.tar.gz"):
        (up / n).write_bytes(n.encode())
    (tmp_path / "upstream.sha512").write_text("".join(
        "%s  %s\n" % (hashlib.sha512((up / n).read_bytes()).hexdigest(), n)
        for n in ("raye-proton.tar.gz", "raye-proton-licenses.tar.gz")))
    check = lambda: subprocess.run(["sh", str(tmp_path / "build-ge.sh"), "check", str(up)],
                                   capture_output=True).returncode
    assert check() == 0
    (up / "raye-proton.tar.gz").write_bytes(b"other")
    assert check() != 0


def test_the_pinned_archives_are_this_build():
    lines = (HERE / "upstream.sha512").read_text().split("\n")
    names = sorted(l.split()[1] for l in lines if l.strip())
    assert names == ["raye-proton-licenses.tar.gz", "raye-proton.tar.gz"]
    ver = (HERE / "ge-version.txt").read_text()
    assert "tag=GE-Proton" in ver and "commit=" in ver


def test_the_package_keeps_the_tool_as_built_and_ships_the_licences():
    rules = (HERE / "debian/rules").read_text()
    for step in ("override_dh_strip:", "override_dh_shlibdeps:", "override_dh_strip_nondeterminism:",
                 "override_dh_dwz:"):
        assert step + "\n" in rules  # empty: nothing done to the binaries
    assert "build-ge.sh check" in rules
    assert "raye-proton-licenses.tar.gz" in rules and "usr/share/doc/raye-proton" in rules
    control = (HERE / "debian/control").read_text()
    assert "Replaces: raye-gaming" in control and "Breaks: raye-gaming" in control


# ---- Steam's default -----------------------------------------------------
def test_nobody_chose_so_raye_proton_becomes_the_default(world):
    home, proc, tool, apt = world
    r = run_default(home, proc, tool)
    assert r.returncode == 0, r.stderr
    text = (apt / "config/config.vdf").read_text()
    zero = mapping(text).get("0")
    assert zero.get("name") == "raye-proton" and zero.get("priority") == "75"
    # the game set one by one keeps its tool, and nothing else moved
    assert mapping(text).get("391540").get("name") == "proton_9"
    assert text.replace(rpd.block_text("0", [("name", "raye-proton"), ("config", ""), ("priority", "75")],
                                       "\t\t\t\t\t"), "") == CONFIG
    assert (apt / "config" / rpd.MARK).exists()


def test_a_tool_the_person_chose_is_kept(world):
    home, proc, tool, apt = world
    chosen = CONFIG.replace('\t\t\t\t\t"391540"', '\t\t\t\t\t"0"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"'
                            '\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"75"\n\t\t\t\t\t}\n\t\t\t\t\t"391540"')
    (apt / "config/config.vdf").write_text(chosen)
    run_default(home, proc, tool)
    assert (apt / "config/config.vdf").read_text() == chosen


def test_turning_it_off_in_steam_is_final(world):
    home, proc, tool, apt = world
    run_default(home, proc, tool)
    (apt / "config/config.vdf").write_text(CONFIG)  # Steam Play turned off again
    run_default(home, proc, tool)
    assert (apt / "config/config.vdf").read_text() == CONFIG


def test_the_old_launcher_never_becomes_the_default(world):
    home, proc, tool, apt = world
    shutil.rmtree(tool / "files")  # no Steam bridge: the raye-wine launcher
    run_default(home, proc, tool)
    assert (apt / "config/config.vdf").read_text() == CONFIG
    assert not (apt / "config" / rpd.MARK).exists()


def test_nothing_is_written_while_steam_is_open(world):
    home, proc, tool, apt = world
    p = proc / "4242"
    p.mkdir()
    (p / "comm").write_text("steamwebhelper\n")
    r = run_default(home, proc, tool)
    assert r.returncode == 0 and "Steam is open" in r.stderr
    assert (apt / "config/config.vdf").read_text() == CONFIG


def test_a_config_without_steam_s_section_gets_one(world):
    home, proc, tool, apt = world
    bare = '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t}\n\t}\n}\n'
    (apt / "config/config.vdf").write_text(bare)
    run_default(home, proc, tool)
    assert mapping((apt / "config/config.vdf").read_text()).get("0").get("name") == "raye-proton"
    (apt / "config/config.vdf").write_text('"InstallConfigStore"\n{\n}\n')
    (apt / "config" / rpd.MARK).unlink()
    run_default(home, proc, tool)
    assert mapping((apt / "config/config.vdf").read_text()).get("0").get("name") == "raye-proton"


def test_a_config_it_does_not_understand_is_left_alone(world):
    home, proc, tool, apt = world
    (apt / "config/config.vdf").write_text('"InstallConfigStore"\n{\n\t"Software"\n')
    run_default(home, proc, tool)
    assert (apt / "config/config.vdf").read_text() == '"InstallConfigStore"\n{\n\t"Software"\n'


def test_the_store_s_steam_gets_it_with_its_own_copy(world):
    home, proc, tool, apt = world
    fp = home / ".var/app/com.valvesoftware.Steam/data/Steam"
    (fp / "config").mkdir(parents=True)
    (fp / "config/config.vdf").write_text(CONFIG)
    run_default(home, proc, tool)
    assert (fp / "config/config.vdf").read_text() == CONFIG  # no copy there yet
    make_tool(fp / "compatibilitytools.d/raye-proton")
    run_default(home, proc, tool)
    assert mapping((fp / "config/config.vdf").read_text()).get("0").get("name") == "raye-proton"


# ---- the Store's Steam: the copy -----------------------------------------
@pytest.fixture
def flatpak(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "flatpak.log"
    (bin_ / "flatpak").write_text('#!/bin/sh\necho "$*" >> %s\n[ "$1" = info ] && exit "${FAKE_NO_STEAM:-0}"\nexit 0\n' % log)
    (bin_ / "flatpak").chmod(0o755)
    return bin_, log


def run_setup(home, tool, bin_, *args, **env):
    e = dict(os.environ, HOME=str(home), RAYE_PROTON_SRC=str(tool), PATH="%s:%s" % (bin_, os.environ["PATH"]), **env)
    return subprocess.run(["sh", str(RAYE / "raye-proton-setup"), *args], env=e, capture_output=True, text=True)


def test_setup_copies_the_whole_tool_where_the_store_s_steam_looks(tmp_path, flatpak):
    bin_, log = flatpak
    home = tmp_path / "home"
    tool = make_tool(tmp_path / "system/raye-proton")
    assert run_setup(home, tool, bin_).returncode == 0
    dest = home / ".var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d/raye-proton"
    assert (dest / rpd.BRIDGE).is_file() and os.access(dest / "proton", os.X_OK)
    assert "talk-name" not in log.read_text()  # it runs in the sandbox, nothing to ask for
    # a new build from Raye Update is copied again, the same one is not
    (dest / "marker").write_text("x")
    run_setup(home, tool, bin_)
    assert (dest / "marker").exists()
    (tool / "version").write_text("1765000000 raye-proton\n")
    run_setup(home, tool, bin_)
    assert not (dest / "marker").exists() and (dest / "version").read_text().startswith("1765")


def test_setup_takes_away_what_the_first_launcher_set_up(tmp_path, flatpak):
    bin_, log = flatpak
    home = tmp_path / "home"
    tool = make_tool(tmp_path / "system/raye-proton")
    old = home / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d"
    (old / "raye-proton").mkdir(parents=True)
    (old / "raye-proton/proton").write_text("old")
    (old / ".raye-proton-override").write_text("")
    run_setup(home, tool, bin_)
    assert not (old / "raye-proton").exists() and not (old / ".raye-proton-override").exists()
    assert "--no-talk-name=org.freedesktop.Flatpak" in log.read_text()


def test_setup_does_nothing_without_the_store_s_steam(tmp_path, flatpak):
    bin_, log = flatpak
    home = tmp_path / "home"
    tool = make_tool(tmp_path / "system/raye-proton")
    run_setup(home, tool, bin_, FAKE_NO_STEAM="1")
    assert not (home / ".var").exists()


def test_units_run_both_steps_and_watch_both_steams():
    path = (RAYE / "raye-proton-default.path").read_text()
    assert "%h/.local/share/Steam/config/config.vdf" in path
    assert "%h/.var/app/com.valvesoftware.Steam/data/Steam/config/config.vdf" in path
    for unit in ("raye-proton-setup.service", "raye-proton-default.service"):
        text = (RAYE / unit).read_text()
        assert "raye-proton-setup" in text and "raye-proton-default --wait" in text
