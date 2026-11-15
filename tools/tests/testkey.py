# SPDX-License-Identifier: GPL-3.0-or-later
"""A throw-away archive key for the tests: ed25519, certify-only primary
and a signing subkey, like the real one."""
import os
import subprocess


def _fprs(env):
    out = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env,
                         capture_output=True, text=True, check=True).stdout
    return [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]


def make_test_key(tmp):
    """(GNUPGHOME, exported public keyring, signing subkey fingerprint)."""
    home = tmp / "gnupg"
    home.mkdir(mode=0o700)
    env = dict(os.environ, GNUPGHOME=str(home))
    gpg = ["gpg", "--batch", "--quiet", "--passphrase", ""]
    subprocess.run(gpg + ["--quick-generate-key", "Test Archive <t@example.org>",
                          "ed25519", "cert", "never"], env=env, check=True)
    primary = _fprs(env)[0]
    subprocess.run(gpg + ["--quick-add-key", primary, "ed25519", "sign", "1y"], env=env, check=True)
    keyring = tmp / "keyring.gpg"
    keyring.write_bytes(subprocess.run(["gpg", "--batch", "--export", primary], env=env,
                                       capture_output=True, check=True).stdout)
    return home, keyring, _fprs(env)[1]
