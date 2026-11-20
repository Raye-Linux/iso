# SPDX-License-Identifier: GPL-3.0-or-later
"""publish-repo, and apt reading its tree through the shipped mirror list:
the first mirror down, the second one answering, Raye Update seeing the
update. Needs dpkg-deb, apt-ftparchive, apt-get, gpg and gpgv.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
"""
import functools
import http.server
import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
ISO = TOOLS.parent
APT_DIR = ISO / "packages/raye-base/release/apt"
UPDATE = ISO.parent / "update/src"

sys.dont_write_bytecode = True  # no __pycache__ in the repo
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import raye_publish as rp  # noqa: E402
from testkey import make_test_key  # noqa: E402

loader = importlib.machinery.SourceFileLoader("publish_repo", str(TOOLS / "publish-repo"))
spec = importlib.util.spec_from_loader("publish_repo", loader)
pr = importlib.util.module_from_spec(spec)
loader.exec_module(pr)

NEEDED = ("dpkg-deb", "apt-ftparchive", "apt-get", "gpg", "gpgv")
missing = [t for t in NEEDED if not shutil.which(t)]


def make_deb(folder, name, version, payload="1", arch="all"):
    root = pathlib.Path(tempfile.mkdtemp(dir=folder))
    (root / "DEBIAN").mkdir()
    (root / "usr/share/demo").mkdir(parents=True)
    (root / "usr/share/demo" / name).write_text(payload)
    (root / "DEBIAN/control").write_text(
        f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\n"
        "Maintainer: Raye <bonjour@rayelinux.com>\nDescription: test package\n")
    digest = subprocess.run(["md5sum", f"usr/share/demo/{name}"], cwd=root,
                            capture_output=True, text=True, check=True).stdout
    (root / "DEBIAN/md5sums").write_text(digest)
    out = pathlib.Path(folder) / f"{name}_{version}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zgzip", "--build", str(root), str(out)],
                   capture_output=True, check=True)
    shutil.rmtree(root)
    return out


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(missing, f"missing {', '.join(missing)}")
class PublishRepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        home, cls.keyring, sub = make_test_key(cls.tmp)
        cls.conf = dict(rp.settings(), GNUPGHOME=str(home), SIGNING_KEY=sub)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                       env=dict(os.environ, GNUPGHOME=cls.conf["GNUPGHOME"]))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        self.debs = self.work / "debs"
        self.debs.mkdir()
        self.out = self.work / "apt"

    def build(self, debs=None, **kw):
        return pr.build(debs or sorted(self.debs.glob("*.deb")), self.out, self.conf,
                        keyring=self.keyring, **kw)

    def packages(self):
        index = self.out / "dists/resolute/main/binary-amd64/Packages"
        return {(p["Package"], p["Version"]): p for p in pr.parse_packages(index.read_text())}

    def test_tree_layout_and_signature(self):
        make_deb(self.debs, "raye-demo", "1.0")
        make_deb(self.debs, "raye-tool", "2.0", arch="amd64")
        self.build()
        suite = self.out / "dists/resolute"
        for name in ("InRelease", "Release", "Release.gpg", "main/binary-amd64/Packages.xz",
                     "main/binary-amd64/Packages.gz"):
            self.assertTrue((suite / name).is_file(), name)
        self.assertTrue(rp.verify(self.keyring, suite / "InRelease"))
        self.assertTrue(rp.verify(self.keyring, suite / "Release.gpg", suite / "Release"))
        release = pr.parse_paragraph((suite / "Release").read_text())
        self.assertEqual((release["Origin"], release["Suite"], release["Acquire-By-Hash"]),
                         ("Raye", "resolute", "yes"))
        self.assertNotIn("MD5Sum", release)
        pkgs = self.packages()
        self.assertEqual(pkgs[("raye-demo", "1.0")]["Filename"],
                         "pool/main/r/raye-demo/raye-demo_1.0_all.deb")
        self.assertIn(("raye-tool", "2.0"), pkgs)
        by_hash = suite / "main/binary-amd64/by-hash/SHA256"
        self.assertTrue((by_hash / rp.sha256(suite / "main/binary-amd64/Packages")).is_file())

    def test_signature_from_another_key_is_refused(self):
        make_deb(self.debs, "raye-demo", "1.0")
        other = self.tmp / "empty.gpg"
        other.write_bytes(b"")
        with self.assertRaises(rp.PublishError):
            pr.build(sorted(self.debs.glob("*.deb")), self.out, self.conf, keyring=other)
        self.assertFalse(self.out.exists())

    def test_rebuilt_package_with_same_contents_keeps_the_published_file(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        first = self.packages()[("raye-demo", "1.0")]["SHA256"]
        time.sleep(1.1)  # a rebuild has other timestamps, so other bytes
        rebuilt = self.work / "rebuilt"
        rebuilt.mkdir()
        deb = make_deb(rebuilt, "raye-demo", "1.0")
        files, _ = self.build([deb])
        self.assertEqual([note for _, _, note in files], ["unchanged"])
        self.assertEqual(self.packages()[("raye-demo", "1.0")]["SHA256"], first)

    def test_changed_contents_need_a_new_version(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        changed = self.work / "changed"
        changed.mkdir()
        deb = make_deb(changed, "raye-demo", "1.0", payload="2")
        with self.assertRaisesRegex(rp.PublishError, "raise its version"):
            self.build([deb])
        bumped = make_deb(changed, "raye-demo", "1.1", payload="2")
        files, gone = self.build([bumped])
        self.assertEqual(list(self.packages()), [("raye-demo", "1.1")])
        self.assertEqual(gone, ["raye-demo 1.0"])

    def test_old_indexes_stay_reachable_by_hash(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        old = rp.sha256(self.out / "dists/resolute/main/binary-amd64/Packages")
        newer = self.work / "newer"
        newer.mkdir()
        self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        by_hash = self.out / "dists/resolute/main/binary-amd64/by-hash/SHA256"
        self.assertTrue((by_hash / old).is_file())
        # older than two weeks: dropped at the next publish
        os.utime(by_hash / old, (0, 0))
        self.build([make_deb(newer, "raye-demo", "1.2", payload="3")])
        self.assertFalse((by_hash / old).exists())

    def test_the_old_version_stays_downloadable_for_a_while(self):
        """A PC that read the lists a minute before a publish downloads the
        version they name: its file stays in the pool, out of the index,
        for GRACE_HOURS, so a download in progress always ends."""
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        newer = self.work / "newer"
        newer.mkdir()
        files, gone = self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        self.assertEqual(gone, ["raye-demo 1.0"])
        self.assertEqual(list(self.packages()), [("raye-demo", "1.1")])
        old = self.out / "pool/main/r/raye-demo/raye-demo_1.0_all.deb"
        self.assertTrue(old.is_file())
        self.assertNotIn("raye-demo_1.0", (self.out / "dists/resolute/main/binary-amd64/Packages")
                         .read_text())
        self.assertEqual(rp.audit_tree(self.out, "resolute", self.keyring), [])
        # still young at the next publish: kept again
        self.build([make_deb(newer, "raye-demo", "1.2", payload="3")])
        self.assertTrue(old.is_file())
        self.assertTrue((self.out / "pool/main/r/raye-demo/raye-demo_1.1_all.deb").is_file())

    def test_an_old_version_goes_once_its_time_is_over(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        newer = self.work / "newer"
        newer.mkdir()
        self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        old = self.out / "pool/main/r/raye-demo/raye-demo_1.0_all.deb"
        past = time.time() - pr.GRACE_HOURS * 3600 - 60
        os.utime(old, (past, past))
        report = {}
        self.build([make_deb(newer, "raye-demo", "1.2", payload="3")], report=report)
        self.assertFalse(old.exists())
        self.assertIn("pool/main/r/raye-demo/raye-demo_1.0_all.deb", report["pruned"])
        self.assertIn("pool/main/r/raye-demo/raye-demo_1.1_all.deb", report["kept"])

    def test_old_versions_never_push_the_tree_over_its_limit(self):
        """GitHub Pages stays under 1 GB: the oldest old versions go first."""
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        newer = self.work / "newer"
        newer.mkdir()
        self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        old = self.out / "pool/main/r/raye-demo/raye-demo_1.0_all.deb"
        size = old.stat().st_size
        report = {}
        files, _ = pr.build([make_deb(newer, "raye-demo", "1.2", payload="3")], self.out,
                            self.conf, keyring=self.keyring, report=report,
                            grace_budget=1)
        self.assertFalse(old.exists())
        self.assertTrue(report["pruned"])
        self.assertGreater(size, 0)

    def test_a_kept_file_is_never_listed_nor_a_source(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        newer = self.work / "newer"
        newer.mkdir()
        self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        # the version comes back (a republish): it is in the index again, once
        self.build([make_deb(newer, "raye-demo", "1.0", payload="1"),
                    make_deb(newer, "raye-demo", "1.1", payload="2")])
        self.assertEqual(sorted(self.packages()), [("raye-demo", "1.0"), ("raye-demo", "1.1")])

    def test_a_kept_version_cannot_come_back_with_other_contents(self):
        """A PC may be downloading it: same version, other bytes is a hash
        mismatch there, as for a published one."""
        make_deb(self.debs, "raye-demo", "1.0")
        self.build()
        newer = self.work / "newer"
        newer.mkdir()
        self.build([make_deb(newer, "raye-demo", "1.1", payload="2")])
        with self.assertRaisesRegex(rp.PublishError, "raise its version"):
            self.build([make_deb(newer, "raye-demo", "1.0", payload="other"),
                        make_deb(newer, "raye-demo", "1.1", payload="2")])

    def test_dry_run_writes_nothing(self):
        make_deb(self.debs, "raye-demo", "1.0")
        self.assertEqual(pr.main(["--dry-run", "--debs", str(self.debs), "--out", str(self.out)]), 0)
        self.assertFalse(self.out.exists())

    def test_apt_falls_back_to_the_second_mirror_and_raye_update_sees_the_update(self):
        # another address than the live one: apt remembers a host whose
        # connection failed, port aside, and would skip it
        self.fallback(f"http://127.0.0.2:{free_port()}/apt/")

    def test_apt_falls_back_when_the_first_mirror_does_not_resolve(self):
        # the state of dl.rayelinux.com until its bucket and DNS exist:
        # the name gives no address at all (.invalid never resolves, RFC 6761)
        self.fallback("http://dl.raye-mirror-down.invalid/apt/")

    def fallback(self, dead):
        make_deb(self.debs, "raye-demo", "1.1", payload="new")
        self.build()
        missed = []

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_request(self, code="-", size="-"):
                if str(code) != "200":
                    missed.append((self.path, code))

            def log_message(self, *args):
                pass

        handler = functools.partial(Handler, directory=str(self.out))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        root = self.work / "client"
        for d in ("etc/sources.list.d", "etc/mirrors", "etc/apt.conf.d", "etc/preferences.d",
                  "state/lists/partial", "cache/archives/partial"):
            (root / d).mkdir(parents=True)
        # the shipped files, with test addresses in place of the real ones
        alive = f"http://127.0.0.1:{server.server_address[1]}/"
        mirrors = (APT_DIR / "raye-mirrors.list").read_text()
        mirrors = mirrors.replace("https://dl.rayelinux.com/apt/", dead)
        mirrors = mirrors.replace("https://raye-linux.github.io/packages/", alive)
        (root / "etc/mirrors/raye.list").write_text(mirrors)
        source = (APT_DIR / "raye.sources").read_text()
        source = source.replace("/etc/apt/mirrors/raye.list", str(root / "etc/mirrors/raye.list"))
        source = source.replace("/usr/share/keyrings/raye-archive-keyring.gpg", str(self.keyring))
        (root / "etc/sources.list.d/raye.sources").write_text(source)
        (root / "etc/sources.list").write_text("")
        (root / "state/status").write_text(
            "Package: raye-demo\nStatus: install ok installed\nVersion: 1.0\n"
            "Architecture: all\nMaintainer: Raye <bonjour@rayelinux.com>\n"
            "Description: test package\n\n")
        conf = root / "apt.conf"
        conf.write_text("\n".join([
            f'Dir::Etc "{root}/etc";',
            'Dir::Etc::sourcelist "sources.list";',
            'Dir::Etc::sourceparts "sources.list.d";',
            'Dir::Etc::parts "apt.conf.d";',
            'Dir::Etc::preferencesparts "preferences.d";',
            f'Dir::State "{root}/state";',
            f'Dir::State::status "{root}/state/status";',
            f'Dir::Cache "{root}/cache";',
            'APT::Architecture "amd64";',
            'APT::Architectures { "amd64"; };',
            'APT::Sandbox::User "root";',
            'Debug::NoLocking "true";',
            'Acquire::Languages "none";',
            'Acquire::Retries "0";',
        ]) + "\n")
        env = dict(os.environ, APT_CONFIG=str(conf), LC_ALL="C")
        update = subprocess.run(["apt-get", "update"], env=env, capture_output=True, text=True)
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        # apt only warns when a source fails, so look at what it printed
        self.assertNotRegex(update.stdout + update.stderr, r"(?m)^(W|E|Err):",
                            update.stdout + update.stderr)
        self.assertIn(f"Get:2 {alive.rstrip('/')} resolute InRelease", update.stdout)
        sim = subprocess.run(["apt-get", "-s", "upgrade", "--with-new-pkgs"], env=env,
                             capture_output=True, text=True)
        self.assertEqual(sim.returncode, 0, sim.stderr)
        self.assertIn("Inst raye-demo [1.0] (1.1 Raye", sim.stdout)
        if (UPDATE / "raye_update.py").is_file():
            sys.path.insert(0, str(UPDATE))
            import raye_update
            pending = raye_update.parse_simulation(sim.stdout)
            self.assertEqual([(p["name"], p["to"], p["kind"]) for p in pending],
                             [("raye-demo", "1.1", "system")])
            self.assertTrue(pending[0]["origin"].startswith("Raye:"))
        fetched = subprocess.run(["apt-get", "-y", "--download-only", "install", "raye-demo"],
                                 env=env, capture_output=True, text=True)
        self.assertEqual(fetched.returncode, 0, fetched.stdout + fetched.stderr)
        self.assertTrue((root / "cache/archives/raye-demo_1.1_all.deb").is_file())
        self.assertEqual(missed, [])


if __name__ == "__main__":
    unittest.main()
