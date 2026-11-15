# SPDX-License-Identifier: GPL-3.0-or-later
"""The Raye apt source, its mirror list and the archive key, as shipped by
raye-archive-keyring."""
import base64
import hashlib
import importlib.util
import pathlib
import shutil
import sys

TOP = pathlib.Path(__file__).resolve().parents[3]
APT = TOP / "release/apt"
KEYRING = TOP / "keyring/raye-archive-keyring.gpg"
ARMORED = TOP / "keyring/raye-archive.asc"

PRIMARY = "EA7369D4C3A310B2DF3DFC16D3AA2E625DDE161E"
SIGNING = "E00515536D1382C4ABB31485A5B09A59F05E0DA0"
MIRRORS = ["https://dl.rayelinux.com/apt/", "https://raye-linux.github.io/packages/"]

spec = importlib.util.spec_from_file_location("raye_release", TOP / "debian/raye_release.py")
rr = importlib.util.module_from_spec(spec)
sys.modules.setdefault("raye_release", rr)
spec.loader.exec_module(rr)


def deb822(text):
    fields = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def mirror_lines(text):
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        uri, _, meta = line.partition("\t")
        out.append((uri, meta.split()))
    return out


def packets(data):
    """(tag, body) of each OpenPGP packet, new or old format headers."""
    i = 0
    while i < len(data):
        head = data[i]
        assert head & 0x80, "not an OpenPGP packet"
        if head & 0x40:
            tag, i = head & 0x3F, i + 1
            first = data[i]
            if first < 192:
                length, i = first, i + 1
            elif first < 224:
                length, i = ((first - 192) << 8) + data[i + 1] + 192, i + 2
            else:
                assert first == 255, "partial lengths are not used in keys"
                length, i = int.from_bytes(data[i + 1:i + 5], "big"), i + 5
        else:
            tag, kind, i = (head >> 2) & 0x0F, head & 3, i + 1
            size = (1, 2, 4)[kind]
            length, i = int.from_bytes(data[i:i + size], "big"), i + size
        yield tag, data[i:i + length]
        i += length


def fingerprint(body):
    return hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body).hexdigest().upper()


def test_source_uses_the_mirror_list_and_the_archive_key():
    src = deb822((APT / "raye.sources").read_text())
    assert src["Types"] == "deb"
    assert src["URIs"] == "mirror+file:/etc/apt/mirrors/raye.list"
    assert src["Suites"] == "resolute"
    assert src["Components"] == "main"
    assert src["Architectures"] == "amd64"
    assert src["Signed-By"] == "/usr/share/keyrings/raye-archive-keyring.gpg"
    assert src.get("Enabled", "yes") == "yes"


def test_mirror_list_names_rayelinux_first_and_github_second():
    lines = mirror_lines((APT / "raye-mirrors.list").read_text())
    assert [uri for uri, _ in lines] == MIRRORS
    # without a priority apt picks a mirror at random
    assert [meta for _, meta in lines] == [["priority:1"], ["priority:2"]]
    for uri, _ in lines:
        assert uri.startswith("https://") and uri.endswith("/")


def test_keyring_holds_only_the_archive_key():
    data = KEYRING.read_bytes()
    found = list(packets(data))
    keys = [fingerprint(body) for tag, body in found if tag == 6]
    subkeys = [fingerprint(body) for tag, body in found if tag == 14]
    assert keys == [PRIMARY]
    assert subkeys == [SIGNING]
    assert not any(tag in (5, 7) for tag, _ in found), "a secret key is in the keyring"


def test_armored_key_is_the_same_key():
    lines = ARMORED.read_text().splitlines()
    body = lines[lines.index("") + 1:]
    body = [line for line in body if not line.startswith(("=", "-----"))]
    assert base64.b64decode("".join(body)) == KEYRING.read_bytes()


def test_keyring_package_installs_source_mirrors_and_key(tmp_path):
    root = tmp_path / "raye-base"
    for part in ("debian", "keyring", "release"):
        shutil.copytree(TOP / part, root / part, symlinks=True)
    result = rr.plan(root, strict=False)
    assert result.errors == []
    rr.install(result, root)
    staged = root / "debian/raye-archive-keyring"
    source = staged / "etc/apt/sources.list.d/raye.sources"
    fields = deb822(source.read_text())
    mirrors = fields["URIs"].removeprefix("mirror+file:")
    assert (staged / mirrors.lstrip("/")).read_text() == (APT / "raye-mirrors.list").read_text()
    assert (staged / fields["Signed-By"].lstrip("/")).read_bytes() == KEYRING.read_bytes()
    # the tests of this folder stay out of the package
    assert not any("tests" in p.parts for p in staged.rglob("*"))
