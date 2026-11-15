# SPDX-License-Identifier: GPL-3.0-or-later
"""release-files, publish-r2 and publish-github, without sending anything."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True  # no __pycache__ in the repo
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import raye_publish as rp  # noqa: E402
from testkey import make_test_key  # noqa: E402


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(TOOLS / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


rf, r2, gh = load("release-files"), load("publish-r2"), load("publish-github")
HAVE_GPG = all(shutil.which(t) for t in ("gpg", "gpgv"))


class SettingsTests(unittest.TestCase):
    def test_environment_wins_over_the_file(self):
        conf = rp.settings(env={"RELEASE": "9.9"})
        self.assertEqual(conf["RELEASE"], "9.9")
        self.assertTrue(conf["STAGE"].startswith("/srv/"))
        self.assertNotIn(conf["STAGE"].rstrip("/") + "/", "/srv/raye/")

    def test_mirror_addresses_match_the_shipped_mirror_list(self):
        conf = rp.settings(env={})
        mirrors = (TOOLS.parent / "packages/raye-base/release/apt/raye-mirrors.list").read_text()
        self.assertIn(conf["R2_PUBLIC"] + "/apt/\t", mirrors)
        self.assertIn(conf["GITHUB_PAGES"] + "/\t", mirrors)

    def test_the_release_name_is_the_one_in_VERSION(self):
        """VERSION is the single source of the version people read.

        release.conf carries it a second time, as the title of the
        release and as the slug of its tag, and nothing tied the two
        together: on 2026-11-05 one of the six places the version shows
        had drifted (the python-apt template said "Raye Linux 0.1"), so
        the copies that are not checked are the ones that drift. The
        number alone goes in RELEASE, because a tag and a file name take
        no space; the word stays in the title.
        """
        version = (TOOLS.parent / "VERSION").read_text().strip()
        # and the release name, from release-names: "Raye Linux 0.5 Beta Alpenglow"
        name = ""
        for line in (TOOLS.parent / "release-names").read_text().splitlines():
            if not line.startswith("#") and line.split()[:1] == [version.split()[0]]:
                name = " " + line.split()[1]
        conf = rp.settings(env={})
        self.assertEqual(conf["RELEASE_TITLE"], f"Raye Linux {version}{name}")
        self.assertEqual(conf["RELEASE"], version.lower().replace(" ", "-"))
        self.assertNotIn(" ", conf["RELEASE"])


class SplitTests(unittest.TestCase):
    def test_parts_join_back_into_the_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            data = os.urandom(2500)
            (tmp / "x.iso").write_bytes(data)
            digest, parts = rf.split(tmp / "x.iso", tmp / "parts", "x.iso", part_size=1000)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertEqual([(p, s) for p, s, _ in parts],
                             [("x.iso.part1", 1000), ("x.iso.part2", 1000), ("x.iso.part3", 500)])
            joined = b"".join((tmp / "parts" / p).read_bytes() for p, _, _ in parts)
            self.assertEqual(joined, data)

    def test_exact_multiple_leaves_no_empty_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "x.iso").write_bytes(b"a" * 2000)
            _, parts = rf.split(tmp / "x.iso", tmp / "parts", "x.iso", part_size=1000)
            self.assertEqual(len(parts), 2)
            self.assertEqual(sorted(os.listdir(tmp / "parts")), ["x.iso.part1", "x.iso.part2"])

    def test_part_size_is_under_the_github_limit(self):
        self.assertLess(rf.PART_SIZE, gh.RELEASE_FILE_LIMIT)


@unittest.skipUnless(HAVE_GPG, "needs gpg and gpgv")
class ReleaseFilesTests(unittest.TestCase):
    def test_signed_release_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            home, keyring, sub = make_test_key(tmp)
            conf = dict(rp.settings(), GNUPGHOME=str(home), SIGNING_KEY=sub)
            iso = tmp / "raye-0.1-20990101-amd64.iso"
            iso.write_bytes(os.urandom(3000))
            with mock.patch.object(rf, "PART_SIZE", 1024):
                info = rf.write(conf, iso, tmp / "out", keyring=keyring)
            out = tmp / "out"
            self.assertEqual(info["iso"], f"raye-{conf['RELEASE']}-amd64.iso")
            self.assertEqual(len(info["parts"]), 3)
            self.assertTrue(rp.verify(keyring, out / "SHA256SUMS.asc", out / "SHA256SUMS"))
            sums = (out / "SHA256SUMS").read_text().splitlines()
            self.assertEqual(sums[0], f"{info['sha256']}  {info['iso']}")
            self.assertEqual(len(sums), 4)
            self.assertEqual(json.loads((out / "release.json").read_text())["size"], 3000)
            for notes in rf.notes_of(conf):
                self.assertTrue((out / notes.name).is_file())
            subprocess.run(["gpgconf", "--kill", "gpg-agent"],
                           env=dict(os.environ, GNUPGHOME=str(home)))


class R2Tests(unittest.TestCase):
    def env_file(self, text, mode=0o600):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / "r2.env"
        path.write_text(text)
        path.chmod(mode)
        return path

    GOOD = ("R2_ACCOUNT_ID=acct\nR2_ACCESS_KEY_ID=key\n"
            "R2_SECRET_ACCESS_KEY=s3cr3t-value\nR2_BUCKET=raye\n")

    def test_reads_the_four_settings(self):
        values = r2.read_env(self.env_file(self.GOOD))
        self.assertEqual(values["R2_BUCKET"], "raye")
        env = r2.rclone_env(values, "/dev/null")
        self.assertEqual(env["RCLONE_CONFIG_R2_ENDPOINT"], "https://acct.r2.cloudflarestorage.com")

    def test_refuses_a_file_others_can_read(self):
        with self.assertRaisesRegex(rp.PublishError, "0600"):
            r2.read_env(self.env_file(self.GOOD, mode=0o644))

    def test_names_what_is_missing_without_values(self):
        with self.assertRaises(rp.PublishError) as e:
            r2.read_env(self.env_file("R2_ACCOUNT_ID=acct\nR2_SECRET_ACCESS_KEY=s3cr3t-value\n"))
        self.assertIn("R2_ACCESS_KEY_ID", str(e.exception))
        self.assertNotIn("s3cr3t", str(e.exception))

    def test_secret_never_on_a_command_line(self):
        values = r2.read_env(self.env_file(self.GOOD))
        steps = r2.apt_steps(pathlib.Path("/t/apt"), values["R2_BUCKET"])
        steps += r2.iso_steps(pathlib.Path("/t/rel"), {"release": "0.1-beta", "iso": "r.iso",
                                                       "source": "/x.iso"}, values["R2_BUCKET"])
        self.assertNotIn("s3cr3t-value", json.dumps(steps))

    def test_inrelease_goes_up_after_the_files_it_names(self):
        names = [what for what, _ in r2.apt_steps(pathlib.Path("/t/apt"), "b")]
        self.assertEqual(names, ["packages and old indexes", "indexes",
                                 "InRelease, Release, Release.gpg", "folder pages",
                                 "delete what left the tree"])
        pool = r2.apt_steps(pathlib.Path("/t/apt"), "b")[0][1]
        self.assertIn(r2.FOREVER, pool)
        top = r2.apt_steps(pathlib.Path("/t/apt"), "b")[2][1]
        self.assertEqual(top[-1], r2.SHORT)

    def test_no_head_after_upload(self):
        # R2 answers 501 to the HEAD ?versionId= rclone sends after a PUT
        self.assertIn('"--s3-no-head"', (TOOLS / "publish-r2").read_text())

    def test_dry_run_without_credentials_sends_nothing(self):
        with tempfile.TemporaryDirectory() as stage:
            stage = pathlib.Path(stage)
            (stage / "apt/dists/resolute").mkdir(parents=True)
            (stage / "apt/dists/resolute/InRelease").write_text("x")
            env = {"STAGE": str(stage), "R2_ENV": str(stage / "none.env")}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env), mock.patch("subprocess.run") as run, \
                    contextlib.redirect_stdout(out):
                run.return_value.returncode = 1
                self.assertEqual(r2.main(["--dry-run", "apt"]), 0)
            self.assertFalse(any(c.args[0][0] == "rclone" for c in run.call_args_list))
            self.assertIn("nothing sent", out.getvalue())


class GitHubTests(unittest.TestCase):
    def conf(self):
        return rp.settings(env={})

    def test_pages_job_pushes_one_commit_and_turns_pages_on(self):
        job = gh.apt_job(self.conf(), pathlib.Path("/srv/publish/apt"), "2026-11-02")
        self.assertIn("touch \"$work/.nojekyll\"", job)
        self.assertIn("git push -q --force git@github.com:Raye-Linux/packages.git main", job)
        self.assertIn("repos/Raye-Linux/packages/pages", job)
        self.assertIn("190692880+techoraye@users.noreply.github.com", job)

    def test_release_job_uploads_parts_checksums_key_and_notes(self):
        info = {"release": "0.1-beta", "title": "Raye Linux 0.1 Beta",
                "parts": [{"name": "r.iso.part1"}, {"name": "r.iso.part2"}],
                "urls": {"github": "https://github.com/Raye-Linux/releases/releases/tag/v0.1-beta"}}
        job = gh.iso_job(self.conf(), pathlib.Path("/srv/publish/release/0.1-beta"), info)
        for name in ("parts/r.iso.part1", "parts/r.iso.part2", "SHA256SUMS.asc",
                     "raye-archive.asc", "release-notes-0.1-beta.fr.md"):
            self.assertIn(name, job)
        self.assertIn("--prerelease", job)
        self.assertIn("--notes-file /srv/publish/release/0.1-beta/release-notes-0.1-beta.md", job)

    def test_problems_name_the_repos_to_create(self):
        out = "login=ok\nfree=10G\npages=off\nrelease=new\nrepo packages=missing\n" \
              "repo releases=PUBLIC empty=true\n"
        with mock.patch.object(rp, "guest_exec", return_value=(0, out)):
            facts, problems = gh.check(self.conf(), "all")
        self.assertIn("create the public repo Raye-Linux/packages", problems)
        self.assertTrue(any("is empty" in p for p in problems))

    def test_private_repo_is_refused(self):
        out = "login=ok\nrepo packages=PRIVATE empty=false\n"
        with mock.patch.object(rp, "guest_exec", return_value=(0, out)):
            _, problems = gh.check(self.conf(), "apt")
        self.assertEqual(problems, ["Raye-Linux/packages must be public (private now)"])


if __name__ == "__main__":
    unittest.main()
