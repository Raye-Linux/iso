# SPDX-License-Identifier: GPL-3.0-or-later
"""What the publish tools share: release.conf, checksums, signing, and
the guest agent path to the GitHub machine."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import subprocess

import raye_pages

HERE = pathlib.Path(__file__).resolve().parent
CONF = HERE / "release.conf"
KEYRING = HERE.parent / "packages/raye-base/keyring/raye-archive-keyring.gpg"


class PublishError(Exception):
    pass


def settings(path=CONF, env=None, local=None):
    """release.conf as a dict. release.local.conf next to it (not in git)
    overrides it for one machine, and an environment variable of the same
    name wins over both."""
    env = os.environ if env is None else env
    if local is None:
        local = pathlib.Path(path).with_name("release.local.conf") if path == CONF else None
    conf = {}
    lines = list(enumerate(pathlib.Path(path).read_text().splitlines(), 1))
    if local is not None and pathlib.Path(local).exists():
        lines += [(n, l) for n, l in enumerate(pathlib.Path(local).read_text().splitlines(), 1)]
    for n, line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.isidentifier():
            raise PublishError(f"{path}:{n}: not KEY=VALUE")
        conf[key] = value.strip()
    for key in conf:
        if env.get(key):
            conf[key] = env[key]
    return conf


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000


# ------------------------------------------------------------------ signing

def _gpg(conf, *args):
    env = dict(os.environ, GNUPGHOME=conf["GNUPGHOME"])
    p = subprocess.run(["gpg", "--batch", "--yes", "--quiet", *args], env=env,
                       capture_output=True, text=True)
    if p.returncode:
        raise PublishError("gpg: " + (p.stderr.strip() or f"exit {p.returncode}"))
    return p.stdout


def have_key(conf):
    # a missing GNUPGHOME would be created empty by gpg: look first
    if not os.path.isdir(conf["GNUPGHOME"]):
        return False
    try:
        _gpg(conf, "--list-secret-keys", conf["SIGNING_KEY"])
    except PublishError:
        return False
    return True


def _signer(conf):
    # the trailing ! makes gpg use exactly this subkey
    return ["--local-user", conf["SIGNING_KEY"] + "!", "--digest-algo", "SHA512"]


def sign_detached(conf, path, out):
    _gpg(conf, *_signer(conf), "--armor", "--detach-sign", "--output", str(out), str(path))


def sign_binary(conf, path, out):
    _gpg(conf, *_signer(conf), "--detach-sign", "--output", str(out), str(path))


def clearsign(conf, path, out):
    _gpg(conf, *_signer(conf), "--clearsign", "--output", str(out), str(path))


def verify(keyring, signature, data=None):
    """True when gpgv accepts the signature with only this keyring."""
    cmd = ["gpgv", "--keyring", str(keyring), str(signature)]
    if data is not None:
        cmd.append(str(data))
    return subprocess.run(cmd, capture_output=True).returncode == 0


# ------------------------------------------------------- what may go out

# The apt tree is public. Only package files and their indexes belong in
# it: an image (the owner's rule: the packages may be public, the ISO not)
# or anything that looks like secret key material must never get there,
# whatever it is named.
TREE_TOP = {"dists", "pool", ".nojekyll", raye_pages.INDEX}
POOL_SUFFIXES = (".deb", ".dsc", ".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst",
                 ".diff.gz", ".tar.gz.asc", ".tar.xz.asc", ".tar.bz2.asc")
FILE_LIMIT = 100 * 1000 * 1000        # GitHub refuses a file this big
TREE_LIMIT = 1000 * 1000 * 1000       # a GitHub Pages site stays under 1 GB
SECRET_MARKERS = (b"PRIVATE KEY BLOCK-----", b"PRIVATE KEY-----",
                  b"OPENSSH PRIVATE KEY", b"R2_SECRET_ACCESS_KEY")
SECRET_PARTS = {"private-keys-v1.d", "openpgp-revocs.d", "pubring.kbx", "trustdb.gpg",
                "raye-keys", "gnupg", ".gnupg", "r2.env"}
SECRET_SUFFIXES = (".key", ".pem", ".p12", ".sec", ".kbx")
ISO_OFFSETS = (0x8001, 0x8801, 0x9001)  # where ISO 9660 writes "CD001"


def _is_iso(path):
    with open(path, "rb") as f:
        for off in ISO_OFFSETS:
            f.seek(off)
            if f.read(5) == b"CD001":
                return True
    return False


def _openpgp_secret(head):
    """True when the file starts with an OpenPGP secret (sub)key packet."""
    if not head or not head[0] & 0x80:
        return False
    tag = head[0] & 0x3F if head[0] & 0x40 else (head[0] >> 2) & 0x0F
    return tag in (5, 7)


def _has_marker(path):
    tail = b""
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            chunk = tail + block
            if any(m in chunk for m in SECRET_MARKERS):
                return True
            tail = chunk[-64:]
    return False


# One apt tree, one suite per update channel (Raye Insider): Stable is the
# configured SUITE, then -public-beta, -beta and -dev.
CHANNEL_ENDINGS = ("", "-public-beta", "-beta", "-dev")


def channel_suites(suite):
    """The suites of every update channel, Stable first."""
    base = suite
    for ending in CHANNEL_ENDINGS[1:]:
        if base.endswith(ending):
            base = base[:-len(ending)]
    return [base + ending for ending in CHANNEL_ENDINGS]


def audit_channels(tree, conf, keyring=None):
    """audit_tree for every channel suite: a mirror never goes out with a
    channel missing, or a PC on that channel fails its apt update."""
    keyring = keyring or KEYRING
    problems = []
    for suite in channel_suites(conf["SUITE"]):
        if not (pathlib.Path(tree) / "dists" / suite).is_dir():
            problems.append(f"dists/{suite} is missing: publish every update channel "
                            f"(publish-repo --suite {suite}) before a mirror")
            continue
        for p in audit_tree(tree, suite, keyring):
            if p not in problems:
                problems.append(p)
    return problems


def audit_tree(tree, suite, keyring=KEYRING, signed=True):
    """Problems that forbid publishing this tree; [] when it may go out.

    Checks every file (an image, secret key material, sizes) and that the
    suite is signed by the shipped keyring, over the very Release that is
    in the tree.
    """
    tree = pathlib.Path(tree)
    problems, total = [], 0
    if not tree.is_dir():
        return [f"{tree}: no such folder"]
    for top in sorted(tree.iterdir()):
        if top.name not in TREE_TOP:
            problems.append(f"{top.name}: not part of an apt tree")
    for path in sorted(tree.rglob("*")):
        rel = path.relative_to(tree).as_posix()
        low = rel.lower()
        if path.is_symlink():
            problems.append(f"{rel}: a symbolic link")
            continue
        parts = low.split("/")
        if (any(p in SECRET_PARTS or p.startswith("secring") for p in parts)
                or low.endswith(SECRET_SUFFIXES)):
            problems.append(f"{rel}: the name of a key or secret file")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if low.endswith((".iso", ".img", ".qcow2")) or ".iso." in parts[-1]:
            problems.append(f"{rel}: an image file name")
        if size >= FILE_LIMIT:
            problems.append(f"{rel}: {human(size)}, GitHub refuses files of 100 MB or more")
        page = parts[-1] == raye_pages.INDEX
        if page and not raye_pages.is_folder_page(path):
            problems.append(f"{rel}: not a folder page")
        elif rel.startswith("pool/") and not page and not low.endswith(POOL_SUFFIXES):
            problems.append(f"{rel}: not a package file")
        with open(path, "rb") as f:
            head = f.read(4)
        if size > 0x8006 and _is_iso(path):
            problems.append(f"{rel}: an ISO 9660 image")
        if _openpgp_secret(head) or _has_marker(path):
            problems.append(f"{rel}: secret key material")
    if total >= TREE_LIMIT:
        problems.append(f"the tree is {human(total)}, a GitHub Pages site must stay under 1 GB")
    if not signed:
        return problems
    suite_dir = tree / "dists" / suite
    release, inrelease, detached = (suite_dir / n for n in ("Release", "InRelease", "Release.gpg"))
    if not release.is_file():
        problems.append(f"dists/{suite}/Release is missing")
    elif not (inrelease.is_file() and detached.is_file()):
        problems.append(f"dists/{suite}: Release is not signed (InRelease or Release.gpg missing)")
    else:
        signed = subprocess.run(["gpgv", "--keyring", str(keyring), "--output", "-", str(inrelease)],
                                capture_output=True)
        if signed.returncode:
            problems.append(f"dists/{suite}/InRelease does not verify with {keyring.name}")
        elif signed.stdout != release.read_bytes():
            problems.append(f"dists/{suite}/InRelease does not sign the Release that is there")
        if not verify(keyring, detached, release):
            problems.append(f"dists/{suite}/Release.gpg does not verify with {keyring.name}")
    return problems


# ------------------------------------------------------ the GitHub machine

def guest_exec(conf, script, timeout=60):
    """Runs a shell script on the GitHub VM through the Proxmox guest agent.

    Returns (exit code, output). There is no ssh into that VM: the guest
    agent on the host is the way in, and the GitHub login never leaves it.
    """
    remote = (f"qm guest exec {int(conf['GITHUB_VM'])} --timeout {int(timeout)} -- "
              f"sh -c {shlex.quote(script)}")
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", conf.get("GITHUB_HOST", "hypervisor"), remote],
                       capture_output=True, text=True, timeout=timeout + 30)
    if p.returncode:
        raise PublishError("guest agent: " + (p.stderr.strip() or f"exit {p.returncode}"))
    answer = json.loads(p.stdout)
    out = answer.get("out-data", "") + answer.get("err-data", "")
    return answer.get("exitcode", 1), out
