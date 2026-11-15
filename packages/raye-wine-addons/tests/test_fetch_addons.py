"""Tests for fetch-addons.sh.

Most tests run the script on a copy of the package made of small fake
archives, with a fake curl that serves files from a folder: no network,
no real Wine file. The first tests read the real addons.sha256,
versions.txt and debian/changelog of the package.
"""

import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
SCRIPT = PKG / "fetch-addons.sh"

MONO, GECKO, DXVK, VKD3D = "10.4.1", "2.47.4", "2.5.2", "2.14"


def upstream_version(mono=MONO, gecko=GECKO, dxvk=DXVK, vkd3d=VKD3D):
    return f"{mono}+gecko{gecko}+dxvk{dxvk}+vkd3d{vkd3d}"


# ---------------------------------------------------------------- helpers

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_tar(path, members):
    """Write a tarball; members maps a name to bytes (None = folder)."""
    path = Path(path)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.mtime = 1700000000
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.size = len(data)
                info.mode = 0o775  # group-writable on purpose: must be fixed
                tar.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    if path.name.endswith(".tar.xz"):
        import lzma
        path.write_bytes(lzma.compress(raw))
    elif path.name.endswith(".tar.gz"):
        import gzip
        path.write_bytes(gzip.compress(raw, mtime=0))
    elif path.name.endswith(".tar.zst"):
        try:
            from compression import zstd
            path.write_bytes(zstd.compress(raw))
        except ImportError:
            path.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=raw,
                                            stdout=subprocess.PIPE, check=True).stdout)
    else:
        raise ValueError(path)
    return path


def fake_archives(folder):
    """The five archives with the layout of the real ones, made small."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    m = f"wine-mono-{MONO}"
    make_tar(folder / f"{m}-x86.tar.xz", {
        f"{m}/": None,
        f"{m}/bin/": None,
        f"{m}/bin/mono.exe": b"MZ mono",
        f"{m}/support/": None,
        f"{m}/support/winemono-support.msi": b"msi",
    })
    for arch in ("x86", "x86_64"):
        g = f"wine-gecko-{GECKO}-{arch}"
        make_tar(folder / f"{g}.tar.xz", {
            f"{g}/": None,
            f"{g}/VERSION": GECKO.encode(),
            f"{g}/xul.dll": b"MZ xul " + arch.encode(),
        })
    d = f"dxvk-{DXVK}"
    make_tar(folder / f"{d}.tar.gz", {
        f"{d}/": None,
        f"{d}/x32/": None,
        f"{d}/x32/d3d11.dll": b"MZ d3d11 32",
        f"{d}/x64/": None,
        f"{d}/x64/d3d11.dll": b"MZ d3d11 64",
    })
    v = f"vkd3d-proton-{VKD3D}"
    make_tar(folder / f"{v}.tar.zst", {
        f"{v}/": None,
        f"{v}/setup_vkd3d_proton.sh": b"#!/bin/sh\n",
        f"{v}/x86/": None,
        f"{v}/x86/d3d12.dll": b"MZ d3d12 32",
        f"{v}/x64/": None,
        f"{v}/x64/d3d12.dll": b"MZ d3d12 64",
    })
    return sorted(folder.iterdir())


CHANGELOG = """raye-wine-addons ({version}-1) resolute; urgency=medium

  * Test.

 -- Test <test@example.org>  Sat, 31 Oct 2026 19:00:00 -0400
"""

VERSIONS = """# wine mono gecko shipped
11.0      {mono}   {gecko}   yes
10.0      9.4.0    2.47.4   no
"""

FAKE_CURL = r"""#!/bin/sh
# fake curl: serves $FAKE_SERVER/<last part of the URL>, logs its arguments
printf '%s\n' "$*" >>"$FAKE_LOG"
out= url=
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out=$2; shift ;;
        http*://*|file://*) url=$1 ;;
    esac
    shift
done
[ -n "$FAKE_OFFLINE" ] && { echo "curl: (6) Could not resolve host" >&2; exit 6; }
src="$FAKE_SERVER/${url##*/}"
[ -f "$src" ] || { echo "curl: (22) 404" >&2; exit 22; }
cp "$src" "$out"
"""


class Pkg:
    """A throwaway copy of the package with fake archives."""

    def __init__(self, tmp):
        self.root = tmp / "src" / "raye-wine-addons"
        self.server = tmp / "server"
        self.bin = tmp / "bin"
        self.log = tmp / "curl.log"
        (self.root / "debian").mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / "fetch-addons.sh")
        (self.root / "README.md").write_text("readme\n")
        files = fake_archives(self.server)
        self.write_sums({f.name: sha256(f) for f in files})
        (self.root / "debian" / "changelog").write_text(
            CHANGELOG.format(version=upstream_version()))
        (self.root / "versions.txt").write_text(VERSIONS.format(mono=MONO, gecko=GECKO))
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text(FAKE_CURL)
        curl.chmod(0o755)

    def write_sums(self, sums):
        (self.root / "addons.sha256").write_text(
            "".join(f"{h}  {n}\n" for n, h in sums.items()))

    def env(self, **extra):
        env = dict(os.environ)
        env.pop("RAYE_ADDONS_MIRROR", None)
        env.update(PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_SERVER=str(self.server),
                   FAKE_LOG=str(self.log), LC_ALL="C.UTF-8")
        env.update(extra)
        return env

    def run(self, *args, **env):
        return subprocess.run(["sh", str(self.root / "fetch-addons.sh"), *args],
                              cwd=self.root, env=self.env(**env), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def curl_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    @property
    def upstream(self):
        return self.root / "upstream"

    @property
    def orig(self):
        return self.root.parent / f"raye-wine-addons_{upstream_version()}.orig.tar.xz"


@pytest.fixture
def pkg(tmp_path):
    return Pkg(tmp_path)


def tree(root):
    root = Path(root)
    return sorted(str(p.relative_to(root)) + ("/" if p.is_dir() else "")
                  for p in root.rglob("*"))


# ------------------------------------------------- the real package files

def test_real_sums_are_well_formed():
    lines = (PKG / "addons.sha256").read_text().splitlines()
    names = []
    for line in lines:
        assert re.fullmatch(r"[0-9a-f]{64}  [A-Za-z0-9][A-Za-z0-9._+-]*", line), line
        names.append(line.split("  ")[1])
    assert len(names) == 5
    kinds = sorted(re.sub(r"-[0-9].*", "", n) for n in names)
    assert kinds == ["dxvk", "vkd3d-proton", "wine-gecko", "wine-gecko", "wine-mono"]


def test_real_version_matches_changelog():
    out = subprocess.run(["sh", str(SCRIPT), "--version"], cwd=PKG, text=True,
                         stdout=subprocess.PIPE, check=True).stdout.strip()
    first = (PKG / "debian" / "changelog").read_text().splitlines()[0]
    full = re.match(r"raye-wine-addons \(([^)]+)\)", first).group(1)
    assert full.rsplit("-", 1)[0] == out


def test_real_shipped_row_matches_sums():
    rows = [line.split() for line in (PKG / "versions.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    assert all(len(r) == 4 and r[3] in ("yes", "no") for r in rows), rows
    shipped = [r for r in rows if r[3] == "yes"]
    assert shipped, "no shipped row"
    sums = (PKG / "addons.sha256").read_text()
    for wine, mono, gecko, _ in shipped:
        assert f"wine-mono-{mono}-x86.tar.xz" in sums
        assert f"wine-gecko-{gecko}-x86.tar.xz" in sums
        assert f"wine-gecko-{gecko}-x86_64.tar.xz" in sums
    # the WineHQ stable series Raye installs must be covered
    assert any(r[0] == "11.0" for r in shipped)


def test_real_urls():
    out = subprocess.run(["sh", str(SCRIPT), "--list"], cwd=PKG, text=True,
                         stdout=subprocess.PIPE, check=True).stdout.split("\n")
    urls = dict(line.split(" ", 1) for line in out if line)
    assert urls["wine-mono-10.4.1-x86.tar.xz"] == \
        "https://dl.winehq.org/wine/wine-mono/10.4.1/wine-mono-10.4.1-x86.tar.xz"
    assert urls["wine-gecko-2.47.4-x86_64.tar.xz"] == \
        "https://dl.winehq.org/wine/wine-gecko/2.47.4/wine-gecko-2.47.4-x86_64.tar.xz"
    assert urls["dxvk-2.5.2.tar.gz"] == \
        "https://github.com/doitsujin/dxvk/releases/download/v2.5.2/dxvk-2.5.2.tar.gz"
    assert urls["vkd3d-proton-2.14.tar.zst"] == \
        "https://github.com/HansKristian-Work/vkd3d-proton/releases/download/v2.14/vkd3d-proton-2.14.tar.zst"


def test_real_script_is_posix_sh():
    # debian/rules runs it with sh (dash on the build machines)
    if shutil.which("dash"):
        subprocess.run(["dash", "-n", str(SCRIPT)], check=True)
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


# ------------------------------------------------------------- fetching

def test_fetch_downloads_checks_and_writes_orig(pkg):
    r = pkg.run()
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in pkg.upstream.iterdir()) == sorted(
        p.name for p in pkg.server.iterdir())
    for f in pkg.upstream.iterdir():
        assert sha256(f) == sha256(pkg.server / f.name)
    calls = pkg.curl_calls()
    assert len(calls) == 5
    # https only, also after a redirect; fail on HTTP errors
    for c in calls:
        assert "--proto =https" in c and "--proto-redir =https" in c and "-f" in c.split()
    assert any("https://dl.winehq.org/wine/wine-mono/10.4.1/" in c for c in calls)

    assert pkg.orig.is_file()
    top = f"raye-wine-addons-{upstream_version()}"
    with tarfile.open(pkg.orig) as tar:
        names = sorted(tar.getnames())
    assert f"{top}/upstream/wine-mono-{MONO}-x86.tar.xz" in names
    assert f"{top}/fetch-addons.sh" in names
    assert f"{top}/addons.sha256" in names
    assert not any(n.startswith(f"{top}/debian") for n in names)
    assert not any(".part" in n for n in names)


def test_second_run_uses_what_is_there(pkg):
    assert pkg.run("--no-orig").returncode == 0
    pkg.log.unlink()
    r = pkg.run("--no-orig")
    assert r.returncode == 0, r.stderr
    assert pkg.curl_calls() == []
    assert not pkg.orig.exists()


def test_tampered_download_is_refused_and_removed(pkg):
    victim = pkg.server / f"dxvk-{DXVK}.tar.gz"
    victim.write_bytes(victim.read_bytes() + b"x")
    r = pkg.run("--no-orig")
    assert r.returncode != 0
    assert f"dxvk-{DXVK}.tar.gz" in r.stderr
    assert not (pkg.upstream / victim.name).exists()
    assert not [p for p in pkg.upstream.iterdir() if p.name.startswith(".")]


def test_altered_local_file_is_downloaded_again(pkg):
    assert pkg.run("--no-orig").returncode == 0
    local = pkg.upstream / f"wine-gecko-{GECKO}-x86.tar.xz"
    local.write_bytes(b"broken")
    pkg.log.unlink()
    r = pkg.run("--no-orig")
    assert r.returncode == 0, r.stderr
    assert len(pkg.curl_calls()) == 1
    assert sha256(local) == sha256(pkg.server / local.name)


def test_offline_fails_cleanly(pkg):
    r = pkg.run("--no-orig", FAKE_OFFLINE="1")
    assert r.returncode != 0
    assert "could not download" in r.stderr
    assert not pkg.upstream.exists() or not any(pkg.upstream.iterdir())


def test_cache_is_used_and_filled(pkg, tmp_path):
    cache = tmp_path / "cache"
    assert pkg.run("--no-orig", "--cache", str(cache)).returncode == 0
    assert sorted(p.name for p in cache.iterdir()) == sorted(p.name for p in pkg.server.iterdir())
    shutil.rmtree(pkg.upstream)
    pkg.log.unlink()
    r = pkg.run("--no-orig", "--cache", str(cache), FAKE_OFFLINE="1")
    assert r.returncode == 0, r.stderr
    assert pkg.curl_calls() == []
    assert len(list(pkg.upstream.iterdir())) == 5


def test_bad_file_in_cache_is_not_used(pkg, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"dxvk-{DXVK}.tar.gz").write_bytes(b"not it")
    r = pkg.run("--no-orig", "--cache", str(cache))
    assert r.returncode == 0, r.stderr
    assert sha256(pkg.upstream / f"dxvk-{DXVK}.tar.gz") == sha256(pkg.server / f"dxvk-{DXVK}.tar.gz")


def test_mirror_replaces_the_address(pkg):
    r = pkg.run("--no-orig", RAYE_ADDONS_MIRROR="https://mirror.example.org/addons/")
    assert r.returncode == 0, r.stderr
    for c in pkg.curl_calls():
        assert "https://mirror.example.org/addons/" in c
        assert "addons//" not in c


# ---------------------------------------------------- refusing bad input

def test_bad_name_in_sums_is_refused(pkg):
    text = (pkg.root / "addons.sha256").read_text()
    (pkg.root / "addons.sha256").write_text(text + "0" * 64 + "  ../evil.tar.gz\n")
    r = pkg.run("--no-orig")
    assert r.returncode != 0
    assert "addons.sha256" in r.stderr
    assert pkg.curl_calls() == []


def test_unknown_kind_is_refused(pkg):
    text = (pkg.root / "addons.sha256").read_text()
    (pkg.root / "addons.sha256").write_text(text + "0" * 64 + "  something-1.0.tar.gz\n")
    r = pkg.run("--version")
    assert r.returncode != 0
    assert "something-1.0.tar.gz" in r.stderr


def test_missing_gecko_arch_is_refused(pkg):
    lines = [line for line in (pkg.root / "addons.sha256").read_text().splitlines()
             if "x86_64" not in line]
    (pkg.root / "addons.sha256").write_text("\n".join(lines) + "\n")
    r = pkg.run("--version")
    assert r.returncode != 0
    assert "gecko" in r.stderr


def test_changelog_mismatch_is_refused(pkg):
    (pkg.root / "debian" / "changelog").write_text(
        CHANGELOG.format(version=upstream_version(dxvk="2.5.3")))
    r = pkg.run("--no-orig")
    assert r.returncode != 0
    assert "changelog" in r.stderr
    assert pkg.curl_calls() == []


def test_versions_table_mismatch_is_refused(pkg):
    (pkg.root / "versions.txt").write_text(VERSIONS.format(mono="10.4.0", gecko=GECKO))
    r = pkg.run("--no-orig")
    assert r.returncode != 0
    assert "versions.txt" in r.stderr


def test_versions_table_without_shipped_row_is_refused(pkg):
    (pkg.root / "versions.txt").write_text("10.0 9.4.0 2.47.4 no\n")
    r = pkg.run("--no-orig")
    assert r.returncode != 0
    assert "versions.txt" in r.stderr


def test_unknown_option(pkg):
    r = pkg.run("--frobnicate")
    assert r.returncode == 2
    assert "Usage" in r.stderr


# ------------------------------------------------------ check and unpack

def test_check_is_offline_and_strict(pkg):
    r = pkg.run("--check")
    assert r.returncode != 0 and "missing" in r.stderr
    assert pkg.run("--no-orig").returncode == 0
    pkg.log.unlink()
    assert pkg.run("--check").returncode == 0
    (pkg.upstream / f"vkd3d-proton-{VKD3D}.tar.zst").write_bytes(b"x")
    r = pkg.run("--check")
    assert r.returncode != 0 and f"vkd3d-proton-{VKD3D}.tar.zst" in r.stderr
    assert pkg.curl_calls() == []


def test_unpack_layout(pkg, tmp_path):
    assert pkg.run("--no-orig").returncode == 0
    dest = tmp_path / "dest"
    r = pkg.run("--unpack", str(dest))
    assert r.returncode == 0, r.stderr
    assert tree(dest) == sorted([
        "usr/", "usr/share/",
        "usr/share/raye/", "usr/share/raye/windows/",
        "usr/share/raye/windows/dxvk/",
        "usr/share/raye/windows/dxvk/VERSION",
        "usr/share/raye/windows/dxvk/x32/", "usr/share/raye/windows/dxvk/x32/d3d11.dll",
        "usr/share/raye/windows/dxvk/x64/", "usr/share/raye/windows/dxvk/x64/d3d11.dll",
        "usr/share/raye/windows/vkd3d-proton/",
        "usr/share/raye/windows/vkd3d-proton/VERSION",
        "usr/share/raye/windows/vkd3d-proton/x64/",
        "usr/share/raye/windows/vkd3d-proton/x64/d3d12.dll",
        "usr/share/raye/windows/vkd3d-proton/x86/",
        "usr/share/raye/windows/vkd3d-proton/x86/d3d12.dll",
        "usr/share/wine/",
        "usr/share/wine/gecko/",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86/",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86/VERSION",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86/xul.dll",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86_64/",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86_64/VERSION",
        f"usr/share/wine/gecko/wine-gecko-{GECKO}-x86_64/xul.dll",
        "usr/share/wine/mono/",
        f"usr/share/wine/mono/wine-mono-{MONO}/",
        f"usr/share/wine/mono/wine-mono-{MONO}/bin/",
        f"usr/share/wine/mono/wine-mono-{MONO}/bin/mono.exe",
        f"usr/share/wine/mono/wine-mono-{MONO}/support/",
        f"usr/share/wine/mono/wine-mono-{MONO}/support/winemono-support.msi",
    ])
    win = dest / "usr/share/raye/windows"
    assert (win / "dxvk/VERSION").read_text() == f"{DXVK}\n"
    assert (win / "vkd3d-proton/VERSION").read_text() == f"{VKD3D}\n"
    assert (win / "dxvk/x64/d3d11.dll").read_bytes() == b"MZ d3d11 64"
    for p in dest.rglob("*"):
        mode = p.stat().st_mode
        assert not mode & (stat.S_IWGRP | stat.S_IWOTH), p
        assert mode & stat.S_IROTH, p


def test_unpack_checks_first(pkg, tmp_path):
    assert pkg.run("--no-orig").returncode == 0
    (pkg.upstream / f"wine-mono-{MONO}-x86.tar.xz").write_bytes(b"x")
    dest = tmp_path / "dest"
    r = pkg.run("--unpack", str(dest))
    assert r.returncode != 0
    assert not dest.exists() or not any(dest.rglob("*.exe"))


def test_unpack_refuses_files_outside_the_expected_folder(pkg, tmp_path):
    bad = pkg.server / f"dxvk-{DXVK}.tar.gz"
    make_tar(bad, {
        f"dxvk-{DXVK}/": None,
        f"dxvk-{DXVK}/x64/d3d11.dll": b"MZ",
        "elsewhere/evil.dll": b"MZ evil",
    })
    sums = {f.name: sha256(f) for f in pkg.server.iterdir()}
    pkg.write_sums(sums)
    assert pkg.run("--no-orig").returncode == 0
    dest = tmp_path / "dest"
    r = pkg.run("--unpack", str(dest))
    assert r.returncode != 0
    assert f"dxvk-{DXVK}.tar.gz" in r.stderr
    assert not list(dest.rglob("evil.dll")) if dest.exists() else True


def test_unpack_needs_a_destination(pkg):
    r = pkg.run("--unpack")
    assert r.returncode == 2


def test_help(pkg):
    r = pkg.run("--help")
    assert r.returncode == 0
    assert "--unpack DEST" in r.stdout and "addons.sha256" in r.stdout
