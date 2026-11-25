"""Raye Proton: Steam's compatibility tool that runs a game on raye-wine
with Raye's settings, for Steam from the archive and the Store's Flatpak.
Wine, the GPU probe and Flatpak are stubs that log what they are asked."""
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PROTON = HERE / "proton"
SETUP = HERE / "raye-proton-setup"
PATHS = HERE.parents[1] / "debian" / "raye-release-paths"


class Layer:
    def __init__(self, tmp, gpu="RAYE_WINE_OVERRIDES='d3d11,dxgi=b'\n"):
        self.tmp = tmp
        self.wine = tmp / "raye-wine"
        (self.wine / "bin").mkdir(parents=True)
        self.log = tmp / "log"
        self.log.write_text("")
        self.home = tmp / "home"
        self.home.mkdir()
        self.data = tmp / "compatdata" / "620"
        line = (f'echo "$(basename "$0") $* | PFX=$WINEPREFIX DLL=$WINEDLLOVERRIDES '
                f'DISPLAY=${{DISPLAY:-}} NVAPI=${{DXVK_ENABLE_NVAPI:-}}" >> {self.log}\n')
        self.stub("wine", "#!/bin/sh\n" + line +
                  'case "$1" in --version) echo wine-11.21 ;; wineboot) mkdir -p "$WINEPREFIX/drive_c" ;; esac\nexit 0\n')
        for name in ("wineserver", "winepath"):
            self.stub(name, "#!/bin/sh\n" + line + "exit 0\n")
        self.stub("wineboot", "#!/bin/sh\n" + line + 'mkdir -p "$WINEPREFIX/drive_c"\n')
        self.stub("raye-wine-gpu", f"#!/bin/sh\nprintf '%s' \"{gpu}\"\n")

    def stub(self, name, text, where=None):
        p = (where or self.wine / "bin") / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self, *args, flatpak=None, **env):
        e = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "RAYE_WINE": str(self.wine),
             "STEAM_COMPAT_DATA_PATH": str(self.data), "DISPLAY": ":1",
             "RAYE_FLATPAK_INFO": str(flatpak or self.tmp / "no-flatpak-info")}
        e.update(env)
        return subprocess.run(["sh", str(PROTON), *args], env=e, capture_output=True, text=True)

    def lines(self, name=None):
        out = self.log.read_text().splitlines()
        return [l for l in out if name is None or l.split(" ", 1)[0] == name]


def test_scripts_are_valid_sh():
    for s in (PROTON, SETUP):
        assert subprocess.run(["sh", "-n", str(s)]).returncode == 0


def test_steam_sees_a_tool_called_raye_proton():
    tool = (HERE / "compatibilitytool.vdf").read_text()
    assert '"display_name" "Raye Proton"' in tool
    assert '"from_oslist" "windows"' in tool and '"to_oslist" "linux"' in tool
    manifest = (HERE / "toolmanifest.vdf").read_text()
    assert '"commandline" "/proton %verb%"' in manifest
    # it runs on the computer, never in Valve's runtime container, which
    # has no raye-wine
    assert "require_tool_appid" not in manifest


def test_installed_where_steam_looks_and_with_steam(tmp_path):
    paths = PATHS.read_text()
    for f in ("proton", "compatibilitytool.vdf", "toolmanifest.vdf"):
        assert f"raye-gaming  release/proton/{f}" in paths
        assert f"usr/share/steam/compatibilitytools.d/raye-proton/{f}" in paths
    assert "usr/lib/systemd/user/raye-proton-setup.service" in paths


def test_first_start_makes_the_space_out_of_sight_then_runs_the_game(tmp_path):
    w = Layer(tmp_path)
    r = w.run("waitforexitandrun", "/games/Game/game.exe", "-windowed")
    assert r.returncode == 0, r.stderr
    log = w.lines()
    pfx = f"PFX={w.data}/pfx"
    boot = [l for l in log if l.startswith("wineboot --init")]
    assert boot and pfx in boot[0] and "DISPLAY= " in boot[0]
    assert "winex11.drv,winewayland.drv=d" in boot[0]
    game = [l for l in log if l.startswith("wine /games/Game/game.exe -windowed")]
    assert game and pfx in game[0] and "DISPLAY=:1" in game[0]
    # Raye's settings: no Wine menu entries, the GPU probe's Direct3D choice
    assert "DLL=winemenubuilder.exe=d;d3d11,dxgi=b" in game[0]
    # waitforexitandrun waits for the space to be quiet
    assert log[-1].startswith("wineserver -w")
    assert (w.data / "raye-proton-version").read_text() == "wine-11.21\n"


def test_the_space_is_made_once_and_upgraded_when_the_layer_moves(tmp_path):
    w = Layer(tmp_path)
    w.run("run", "/g/a.exe")
    w.log.write_text("")
    w.run("run", "/g/a.exe")
    assert not [l for l in w.lines() if "wineboot" in l]
    (w.data / "raye-proton-version").write_text("wine-11.20\n")
    w.run("run", "/g/a.exe")
    assert [l for l in w.lines() if l.startswith("wineboot --update")]


def test_nvidia_gets_nvapi(tmp_path):
    w = Layer(tmp_path, gpu="DXVK_ENABLE_NVAPI=1\n")
    w.run("run", "/g/a.exe")
    assert "NVAPI=1" in [l for l in w.lines() if l.startswith("wine /g/a.exe")][0]


def test_steam_s_path_questions_go_to_winepath(tmp_path):
    w = Layer(tmp_path)
    w.run("getcompatpath", "/g/a.exe")
    assert w.lines("winepath")[-1].startswith("winepath -w /g/a.exe")


def test_says_so_without_raye_wine(tmp_path):
    w = Layer(tmp_path)
    r = w.run("run", "/g/a.exe", RAYE_WINE=str(tmp_path / "none"))
    assert r.returncode == 1 and "raye-wine" in r.stderr


def test_the_store_s_steam_hands_the_game_to_the_computer(tmp_path):
    w = Layer(tmp_path)
    info = tmp_path / "flatpak-info"
    info.write_text("[Application]\nname=com.valvesoftware.Steam\n")
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    w.stub("flatpak-spawn", f'#!/bin/sh\nfor a; do echo "$a"; done > {tmp_path}/spawn\n', where=sbin)
    home = w.home
    inside = f"{home}/.local/share/Steam/steamapps"
    r = w.run("waitforexitandrun", f"{inside}/common/Game/game.exe", "-dx11", "/mnt/games/x.exe",
              flatpak=info, PATH=f"{sbin}:/usr/bin:/bin",
              STEAM_COMPAT_DATA_PATH=f"{inside}/compatdata/620", SteamAppId="620")
    assert r.returncode == 0, r.stderr
    a = (tmp_path / "spawn").read_text().splitlines()
    host = f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps"
    assert a[0] == "--host"
    assert f"--env=STEAM_COMPAT_DATA_PATH={host}/compatdata/620" in a
    assert "--env=SteamAppId=620" in a
    i = a.index("waitforexitandrun")
    assert a[i:] == ["waitforexitandrun", f"{host}/common/Game/game.exe", "-dx11", "/mnt/games/x.exe"]
    # and nothing of the layer ran in the sandbox
    assert w.lines() == []


def test_setup_copies_it_into_the_store_s_steam_and_allows_the_hand_over(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for f in ("proton", "compatibilitytool.vdf", "toolmanifest.vdf"):
        (src / f).write_text((HERE / f).read_text())
    home = tmp_path / "home"
    home.mkdir()
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    log = tmp_path / "flatpak.log"
    fp = sbin / "flatpak"
    fp.write_text(f'#!/bin/sh\necho "flatpak $*" >> {log}\n'
                  f'case "$1 $3" in "override --show") cat {tmp_path}/shown 2>/dev/null ;; esac\nexit 0\n')
    fp.chmod(0o755)
    env = {"PATH": f"{sbin}:/usr/bin:/bin", "HOME": str(home), "RAYE_PROTON_SRC": str(src)}
    assert subprocess.run(["sh", str(SETUP)], env=env).returncode == 0
    dest = home / ".var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/raye-proton"
    assert (dest / "proton").read_text() == (HERE / "proton").read_text()
    assert os.access(dest / "proton", os.X_OK)
    asked = [l for l in log.read_text().splitlines() if "--talk-name" in l]
    assert asked == ["flatpak override --user --talk-name=org.freedesktop.Flatpak com.valvesoftware.Steam"]
    (tmp_path / "shown").write_text("[Session Bus Policy]\norg.freedesktop.Flatpak=talk\n")
    log.write_text("")
    subprocess.run(["sh", str(SETUP)], env=env)
    assert not [l for l in log.read_text().splitlines() if "--talk-name" in l]
    subprocess.run(["sh", str(SETUP), "--remove"], env=env)
    assert not dest.exists()
    assert "flatpak override --user --no-talk-name=org.freedesktop.Flatpak com.valvesoftware.Steam" in log.read_text()


def test_setup_does_nothing_without_the_store_s_steam(tmp_path):
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    fp = sbin / "flatpak"
    fp.write_text("#!/bin/sh\n[ \"$1\" = info ] && exit 1\necho called >> " + str(tmp_path / "log") + "\n")
    fp.chmod(0o755)
    env = {"PATH": f"{sbin}:/usr/bin:/bin", "HOME": str(tmp_path), "RAYE_PROTON_SRC": str(HERE)}
    assert subprocess.run(["sh", str(SETUP)], env=env).returncode == 0
    assert not (tmp_path / "log").exists() and not (tmp_path / ".var").exists()
