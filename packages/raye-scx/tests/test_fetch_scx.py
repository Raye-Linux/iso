"""Tests of fetch-scx.sh, run by the package build.

Every test works on a copy of the script in a temporary folder, with
small archives made on the spot: nothing is downloaded and cargo is a
stand-in that writes a fixed vendor/ folder.
"""

import hashlib
import io
import lzma
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "fetch-scx.sh"
V = "9.9.9"

CHANGELOG = f"""raye-scx ({V}-1) resolute; urgency=medium

  * Test.

 -- Test <test@example.org>  Sat, 31 Oct 2026 19:20:00 -0400
"""

CARGO_TOML = 'members = [\n    "a",\n    "b",\n]\n'
PATCH = """--- a/Cargo.toml
+++ b/Cargo.toml
@@ -1,4 +1,3 @@
 members = [
-    "a",
     "b",
 ]
"""

FAKE_CARGO = """#!/bin/sh
# stands in for cargo vendor: same crates every time
[ "$1" = vendor ] || exit 3
mkdir -p "$4/one" "$4/two"
printf 'one\\n' >"$4/one/lib.rs"
printf 'two\\n' >"$4/two/lib.rs"
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def add(tar, name, data=b"", kind="file", target=None):
    info = tarfile.TarInfo(name)
    info.mtime = 0
    if kind == "dir":
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tar.addfile(info)
    elif kind == "sym":
        info.type = tarfile.SYMTYPE
        info.linkname = target
        tar.addfile(info)
    elif kind == "hard":
        info.type = tarfile.LNKTYPE
        info.linkname = target
        tar.addfile(info)
    else:
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))


def release(extra=()):
    """The release tarball: scx-V/ with Cargo.toml, Cargo.lock, a lib link."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        top = f"scx-{V}"
        add(tar, top, kind="dir")
        add(tar, f"{top}/Cargo.toml", CARGO_TOML.encode())
        add(tar, f"{top}/Cargo.lock", b"version = 4\n")
        add(tar, f"{top}/lib", kind="dir")
        add(tar, f"{top}/lib/x.h", b"x\n")
        add(tar, f"{top}/a", kind="dir")
        add(tar, f"{top}/a/b", kind="dir")
        add(tar, f"{top}/a/b/lib", kind="sym", target="../../lib")
        for args in extra:
            add(tar, *args[:2], **args[2] if len(args) > 2 else {})
    return buf.getvalue()


def vendor_tar(names=("vendor/one/lib.rs",)):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        add(tar, "vendor", kind="dir")
        for n in names:
            add(tar, n, b"crate\n")
    return buf.getvalue()


class Pkg:
    def __init__(self, root, src=None, vendor=None, sums=None, patch=PATCH):
        self.dir = root / "raye-scx"
        (self.dir / "debian").mkdir(parents=True)
        (self.dir / "patches").mkdir()
        (self.dir / "upstream").mkdir()
        shutil.copy(SCRIPT, self.dir / "fetch-scx.sh")
        (self.dir / "debian" / "changelog").write_text(CHANGELOG)
        if patch is not None:
            (self.dir / "patches" / "0001-test.patch").write_text(patch)
        self.src = release() if src is None else src
        self.vendor_plain = vendor_tar() if vendor is None else vendor
        (self.dir / "upstream" / f"scx-{V}.tar.gz").write_bytes(self.src)
        (self.dir / "upstream" / f"scx-vendor-{V}.tar.xz").write_bytes(
            lzma.compress(self.vendor_plain))
        if sums is None:
            sums = (f"# test\n{sha(self.src)}  scx-{V}.tar.gz\n"
                    f"{sha(self.vendor_plain)}  scx-vendor-{V}.tar.xz\n")
        (self.dir / "scx.sha256").write_text(sums)

    def run(self, *args, env=None):
        e = dict(os.environ)
        e.pop("RAYE_SCX_MIRROR", None)
        e.update(env or {})
        return subprocess.run(["sh", str(self.dir / "fetch-scx.sh"), *args],
                              capture_output=True, text=True, env=e,
                              cwd=self.dir)


@pytest.fixture
def pkg(tmp_path):
    return Pkg(tmp_path)


# ------------------------------------------------------------ the real files

def test_real_list_names_one_release():
    out = subprocess.run(["sh", str(SCRIPT), "--version"],
                         capture_output=True, text=True, check=True).stdout
    assert re.fullmatch(r"\d+\.\d+\.\d+\n", out)


def test_real_changelog_matches_list():
    version = subprocess.run(["sh", str(SCRIPT), "--version"],
                             capture_output=True, text=True,
                             check=True).stdout.strip()
    first = (HERE / "debian" / "changelog").read_text().splitlines()[0]
    assert first.startswith(f"raye-scx ({version}-")


def test_real_list_points_at_the_release_tag():
    out = subprocess.run(["sh", str(SCRIPT), "--list"], capture_output=True,
                         text=True, check=True).stdout
    version = subprocess.run(["sh", str(SCRIPT), "--version"],
                             capture_output=True, text=True,
                             check=True).stdout.strip()
    assert (f"scx-{version}.tar.gz https://github.com/sched-ext/scx/archive/"
            f"refs/tags/v{version}.tar.gz") in out
    assert f"scx-vendor-{version}.tar.xz made here by cargo vendor" in out


def test_real_patch_keeps_only_the_two_schedulers():
    text = (HERE / "patches" / "0001-build-only-lavd-and-bpfland.patch").read_text()
    hunk = text.split("--- a/Cargo.lock")[0]
    kept = re.findall(r'^ +"([^"]+)",$', hunk, re.M)
    assert kept == ["scheds/rust/scx_bpfland", "scheds/rust/scx_lavd"]
    # the lock only loses packages: no version is added or moved
    lock = text.split("--- a/Cargo.lock", 1)[1]
    assert not re.search(r'^\+(name|version|checksum) = ', lock, re.M)


def test_rules_build_and_install_only_the_two():
    rules = (HERE / "debian" / "rules").read_text()
    assert re.search(r"^SCHEDS = scx_lavd scx_bpfland$", rules, re.M)
    assert "--frozen" in rules
    assert "fetch-scx.sh --unpack" in rules


# ------------------------------------------------------------ the list

@pytest.mark.parametrize("sums,error", [
    ("zz  scx-9.9.9.tar.gz\n", "is not '<sha256>  <file>'"),
    (("A" * 64) + "  scx-9.9.9.tar.gz\n", "bad SHA-256"),
    (("a" * 64) + "  other.tar.gz\n", "do not know what other.tar.gz is"),
    (("a" * 64) + "  scx-9.9.9.tar.gz\n", "no crates tarball"),
    (("a" * 64) + "  scx-vendor-9.9.9.tar.xz\n", "no release tarball"),
    (("a" * 64) + "  scx-9.9.9.tar.gz\n" + ("b" * 64)
     + "  scx-vendor-9.9.8.tar.xz\n", "the release is 9.9.9"),
    (("a" * 64) + "  scx-9.9.9.tar.gz\n" + ("a" * 64)
     + "  scx-9.9.8.tar.gz\n", "two release tarballs"),
    (("a" * 64) + "  scx-v9.tar.gz\n", "no version"),
    (("a" * 64) + "  scx-9.9.9.tar.gz extra\n", "is not '<sha256>  <file>'"),
])
def test_bad_lists_are_refused(tmp_path, sums, error):
    p = Pkg(tmp_path, sums=sums)
    r = p.run("--check")
    assert r.returncode != 0
    assert error in r.stderr


def test_changelog_must_name_the_same_version(pkg):
    (pkg.dir / "debian" / "changelog").write_text(
        CHANGELOG.replace(f"({V}-1)", "(1.0.0-1)"))
    r = pkg.run("--check")
    assert r.returncode != 0
    assert "debian/changelog says 1.0.0" in r.stderr


# ------------------------------------------------------------ checking

def test_check_passes_on_good_files(pkg):
    r = pkg.run("--check")
    assert r.returncode == 0, r.stderr


def test_check_refuses_a_changed_release(pkg):
    (pkg.dir / "upstream" / f"scx-{V}.tar.gz").write_bytes(release(
        extra=[("scx-9.9.9/more", b"more")]))
    r = pkg.run("--check")
    assert r.returncode != 0
    assert "SHA-256 does not match" in r.stderr


def test_vendor_hash_is_of_the_tar_not_the_xz(pkg):
    # the same tar packed by another xz setting still passes
    path = pkg.dir / "upstream" / f"scx-vendor-{V}.tar.xz"
    path.write_bytes(lzma.compress(pkg.vendor_plain, preset=1))
    assert pkg.run("--check").returncode == 0


def test_check_says_what_is_missing(pkg):
    (pkg.dir / "upstream" / f"scx-vendor-{V}.tar.xz").unlink()
    r = pkg.run("--check")
    assert r.returncode != 0
    assert "upstream/scx-vendor-9.9.9.tar.xz is missing" in r.stderr


# ------------------------------------------------------------ unpacking

def test_unpack_applies_patches_and_adds_the_crates(pkg, tmp_path):
    dest = tmp_path / "out"
    r = pkg.run("--unpack", str(dest))
    assert r.returncode == 0, r.stderr
    assert (dest / "Cargo.toml").read_text() == 'members = [\n    "b",\n]\n'
    assert (dest / "vendor" / "one" / "lib.rs").read_text() == "crate\n"
    assert os.readlink(dest / "a" / "b" / "lib") == "../../lib"
    assert not (dest / "Cargo.toml.orig").exists()


def test_unpack_refuses_a_full_folder(pkg, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "keep").write_text("mine")
    r = pkg.run("--unpack", str(dest))
    assert r.returncode != 0
    assert "is not empty" in r.stderr
    assert (dest / "keep").read_text() == "mine"


def test_unpack_stops_when_a_patch_does_not_apply(tmp_path):
    p = Pkg(tmp_path, patch=PATCH.replace('"a"', '"zz"'))
    r = p.run("--unpack", str(tmp_path / "out"))
    assert r.returncode != 0
    assert "patches/0001-test.patch does not apply" in r.stderr


@pytest.mark.parametrize("extra,word", [
    ([("../evil", b"x")], "outside scx-9.9.9/"),
    ([("scx-9.9.9/../../evil", b"x")], "outside scx-9.9.9/"),
    ([("scx-9.9.9/abs", b"", {"kind": "sym", "target": "/etc/passwd"})],
     "a link points to /etc/passwd"),
    ([("scx-9.9.9/up", b"", {"kind": "sym", "target": "../../etc"})],
     "a link points to ../../etc"),
    ([("scx-9.9.9/a/b/up", b"", {"kind": "sym",
                                 "target": "../../../x"})],
     "a link points to ../../../x"),
    ([("scx-9.9.9/hl", b"", {"kind": "hard", "target": "etc/passwd"})],
     "a link points to etc/passwd"),
])
def test_unpack_refuses_what_leaves_the_folder(tmp_path, extra, word):
    p = Pkg(tmp_path, src=release(extra=extra))
    dest = tmp_path / "out"
    r = p.run("--unpack", str(dest))
    assert r.returncode != 0
    assert word in r.stderr
    assert not dest.exists() or not any(dest.iterdir())


def test_unpack_refuses_crates_outside_vendor(tmp_path):
    p = Pkg(tmp_path, vendor=vendor_tar(names=("vendor/ok.rs", "other/x.rs")))
    r = p.run("--unpack", str(tmp_path / "out"))
    assert r.returncode != 0
    assert "other/x.rs is outside vendor/" in r.stderr


# ------------------------------------------------------------ fetching

def fake_cargo(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    cargo = bin_ / "cargo"
    cargo.write_text(FAKE_CARGO)
    cargo.chmod(cargo.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bin_}:{os.environ['PATH']}"}


def expected_vendor(tmp_path):
    """The tar fetch-scx.sh makes from the fake cargo's folder."""
    work = tmp_path / "expect"
    (work / "vendor" / "one").mkdir(parents=True)
    (work / "vendor" / "two").mkdir()
    (work / "vendor" / "one" / "lib.rs").write_text("one\n")
    (work / "vendor" / "two" / "lib.rs").write_text("two\n")
    out = subprocess.run(
        ["tar", "--sort=name", "--format=gnu", "--owner=0", "--group=0",
         "--numeric-owner", "--mode=u+rw,go+r,go-w", "--mtime=@0", "-cf", "-",
         "-C", str(work), "vendor"], capture_output=True, check=True)
    return out.stdout


def test_fetch_makes_the_crates_tarball(tmp_path):
    plain = expected_vendor(tmp_path)
    p = Pkg(tmp_path, vendor=plain)
    (p.dir / "upstream" / f"scx-vendor-{V}.tar.xz").unlink()
    r = p.run("--no-orig", env=fake_cargo(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "running cargo vendor" in r.stdout
    assert p.run("--check").returncode == 0
    assert sorted(os.listdir(p.dir / "upstream")) == [
        f"scx-{V}.tar.gz", f"scx-vendor-{V}.tar.xz"]


def test_fetch_refuses_crates_that_changed(tmp_path):
    p = Pkg(tmp_path, vendor=b"something else")
    (p.dir / "upstream" / f"scx-vendor-{V}.tar.xz").unlink()
    r = p.run("--no-orig", env=fake_cargo(tmp_path))
    assert r.returncode != 0
    assert "a crate changed" in r.stderr
    # no half-made tarball and no work folder left behind
    assert os.listdir(p.dir / "upstream") == [f"scx-{V}.tar.gz"]


def test_fetch_takes_files_from_the_cache(tmp_path):
    p = Pkg(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    for f in (p.dir / "upstream").iterdir():
        shutil.move(str(f), cache / f.name)
    r = p.run("--no-orig", "--cache", str(cache))
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("from the cache") == 2
    assert p.run("--check").returncode == 0


def test_fetch_fills_the_cache(tmp_path):
    p = Pkg(tmp_path)
    cache = tmp_path / "cache"
    assert p.run("--no-orig", "--cache", str(cache)).returncode == 0
    assert sorted(os.listdir(cache)) == [f"scx-{V}.tar.gz",
                                        f"scx-vendor-{V}.tar.xz"]


def test_fetch_writes_the_orig_tarball(pkg, tmp_path):
    (pkg.dir / "README.md").write_text("readme\n")
    r = pkg.run(env={"SOURCE_DATE_EPOCH": "0"})
    assert r.returncode == 0, r.stderr
    orig = tmp_path / f"raye-scx_{V}.orig.tar.xz"
    with tarfile.open(orig) as tar:
        names = tar.getnames()
    top = f"raye-scx-{V}"
    assert f"{top}/upstream/scx-{V}.tar.gz" in names
    assert f"{top}/upstream/scx-vendor-{V}.tar.xz" in names
    assert f"{top}/README.md" in names
    assert not [n for n in names if n.startswith(f"{top}/debian")]


def test_unknown_option_is_refused(pkg):
    r = pkg.run("--frobnicate")
    assert r.returncode == 2
    assert "Usage" in r.stderr


def test_help_prints_the_header(pkg):
    r = pkg.run("--help")
    assert r.returncode == 0
    assert "--unpack DEST" in r.stdout
