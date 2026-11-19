"""Print to PDF: the printer, the backend and the save dialog."""

import importlib.machinery
import importlib.util
import io
import os
import pathlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

PRINT = pathlib.Path(__file__).resolve().parent.parent
BASE = PRINT.parent.parent
NBSP = "\u00a0"
sys.dont_write_bytecode = True


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


backend = load("raye_pdf", PRINT / "raye-pdf")
save = load("raye_pdf_save", PRINT / "raye-pdf-save")


class Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


class Recorder:
    """Stands for subprocess.run: answers by program name, keeps the calls."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, cmd, **kw):
        stdin = kw.get("stdin")
        data = stdin.read() if hasattr(stdin, "read") else None
        self.calls.append((cmd, kw.get("env"), data))
        answer = self.answers.get(os.path.basename(cmd[0]), Result())
        return answer(cmd) if callable(answer) else answer

    def programs(self):
        return [os.path.basename(c[0][0]) for c in self.calls]


class Backend(unittest.TestCase):
    def setUp(self):
        self.me = pwd.getpwuid(os.getuid())
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_lists_itself_for_add_printer(self):
        out = io.StringIO()
        sys.stdout, old = out, sys.stdout
        try:
            self.assertEqual(backend.main(["raye-pdf"]), 0)
        finally:
            sys.stdout = old
        self.assertTrue(out.getvalue().startswith("direct raye-pdf:/ "))

    def test_only_real_accounts(self):
        self.assertIsNone(backend.account("no-such-account-here"))
        system = [e for e in pwd.getpwall() if 0 < e.pw_uid < 1000 and os.path.isdir(e.pw_dir)]
        if system:
            self.assertIsNone(backend.account(system[0].pw_name), "a system account")

    def test_becomes_the_person_who_printed(self):
        run = Recorder()
        (self.tmp / str(self.me.pw_uid)).mkdir()
        (self.tmp / str(self.me.pw_uid) / "bus").touch()
        ok = backend.handoff(self.me, io.BytesIO(b"%PDF-1.7"), "notes.txt", "12", run, str(self.tmp))
        self.assertTrue(ok)
        cmd, env, data = run.calls[0]
        self.assertEqual(cmd[:5], ["setpriv", "--reuid=%d" % self.me.pw_uid, "--regid=%d" % self.me.pw_gid,
                                   "--init-groups", "--"])
        self.assertEqual(cmd[5:], [backend.SAVE, "--receive", "12", "notes.txt"])
        self.assertEqual(data, b"%PDF-1.7")
        self.assertEqual(env["XDG_RUNTIME_DIR"], str(self.tmp / str(self.me.pw_uid)))
        self.assertEqual(env["HOME"], self.me.pw_dir)

    def test_no_session_no_session_bus(self):
        run = Recorder()
        backend.handoff(self.me, io.BytesIO(b""), "x", "3", run, str(self.tmp))
        self.assertNotIn("XDG_RUNTIME_DIR", run.calls[0][1])

    def test_bad_calls_fail_the_job(self):
        self.assertEqual(backend.main(["raye-pdf", "1", "2"]), backend.FAILED)
        self.assertEqual(backend.main(["raye-pdf", "1", "no-such-account-here", "t", "1", ""]), backend.FAILED)

    def test_runs_as_root_only_through_its_mode(self):
        rules = (BASE / "debian" / "rules").read_text()
        self.assertIn("chmod 0700 debian/raye-desktop/usr/lib/cups/backend/raye-pdf", rules)


class FileNames(unittest.TestCase):
    W = save.WORDS["en"]

    def test_from_the_job_title(self):
        cases = {
            "Untitled - Notepad": "Document.pdf",
            "notes.txt - Notepad": "notes.pdf",
            "Rapport final.docx": "Rapport final.pdf",
            "https://rayelinux.com/download/": "download.pdf",
            "C:\\Users\\me\\Plan.xlsx": "Plan.pdf",
            "Budget: 2026?": "Budget 2026.pdf",
            "": "Document.pdf",
            "(stdin)": "Document.pdf",
            "already.pdf": "already.pdf",
            "photo.JPG": "photo.pdf",
        }
        for title, want in cases.items():
            self.assertEqual(save.file_name(title, self.W), want, title)

    def test_long_titles_are_cut(self):
        self.assertEqual(len(save.file_name("x" * 400, self.W)), 124)

    def test_never_over_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(save.free_path(d, "a.pdf"), os.path.join(d, "a.pdf"))
            pathlib.Path(d, "a.pdf").touch()
            pathlib.Path(d, "a (2).pdf").touch()
            self.assertEqual(save.free_path(d, "a.pdf"), os.path.join(d, "a (3).pdf"))

    def test_language(self):
        self.assertEqual(save.language({"LANG": "fr_CA.UTF-8"}), "fr")
        self.assertEqual(save.language({"LANGUAGE": "fr:en", "LANG": "en_US.UTF-8"}), "fr")
        self.assertEqual(save.language({"LANG": "de_DE.UTF-8"}), "en")
        self.assertEqual(save.language({}), "en")

    def test_words(self):
        self.assertEqual(set(save.WORDS["en"]), set(save.WORDS["fr"]))
        self.assertNotEqual(save.WORDS["en"]["saved"], save.WORDS["fr"]["saved"])
        for lang in save.WORDS.values():
            self.assertNotRegex(" ".join(lang.values()), r"Wine|CUPS|cups|KDE")


class Saving(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.docs = self.home / "Documents"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.env = {"HOME": str(self.home), "LANG": "en_CA.UTF-8", "PATH": str(self.bin)}
        self.pdf = self.tmp / "job-7.pdf"
        self.pdf.write_bytes(b"%PDF-1.7 test")
        self.xdg = Result(0, str(self.docs) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def kdialog(self, code, out=""):
        path = self.bin / "kdialog"
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return Result(code, out)

    def test_documents_comes_from_the_user_folders(self):
        run = Recorder({"xdg-user-dir": Result(0, str(self.home / "Docs") + "\n")})
        self.assertEqual(save.documents(self.env, run), str(self.home / "Docs"))
        self.assertTrue((self.home / "Docs").is_dir())
        run = Recorder({"xdg-user-dir": Result(0, str(self.home) + "\n")})
        self.assertEqual(save.documents(self.env, run), str(self.docs), "no folder set")

    def test_no_screen_saves_to_documents_and_says_so(self):
        run = Recorder({"xdg-user-dir": self.xdg})
        target = save.ask(str(self.pdf), "notes.txt - Notepad", self.env, run)
        self.assertEqual(target, str(self.docs / "notes.pdf"))
        self.assertEqual(pathlib.Path(target).read_bytes(), b"%PDF-1.7 test")
        notify = [c for c in run.calls if c[0][0] == "notify-send"][0][0]
        self.assertIn("Saved to Documents", notify)
        self.assertIn("notes.pdf", notify)

    def test_dialog_asks_where(self):
        self.env["WAYLAND_DISPLAY"] = "wayland-0"
        chosen = self.tmp / "elsewhere" / "Invoice"
        chosen.parent.mkdir()
        run = Recorder({"xdg-user-dir": self.xdg, "kdialog": self.kdialog(0, str(chosen) + "\n")})
        target = save.ask(str(self.pdf), "Invoice 12", self.env, run)
        self.assertEqual(target, str(chosen) + ".pdf")
        self.assertTrue(pathlib.Path(target).exists())
        self.assertFalse(self.pdf.exists())
        dialog = [c[0] for c in run.calls if c[0][0] == "kdialog"][0]
        self.assertIn("Save as PDF", dialog)
        self.assertIn(str(self.docs / "Invoice 12.pdf"), dialog)
        self.assertNotIn("notify-send", run.programs())

    def test_cancel_keeps_nothing(self):
        self.env["DISPLAY"] = ":0"
        staged = self.tmp / "raye-pdf" / "job-7.pdf"
        staged.parent.mkdir()
        self.pdf.rename(staged)
        run = Recorder({"xdg-user-dir": self.xdg, "kdialog": self.kdialog(1)})
        self.assertIsNone(save.ask(str(staged), "x", self.env, run))
        self.assertFalse(staged.parent.exists())
        self.assertEqual(list(self.docs.iterdir()), [])

    def test_dialog_that_cannot_open_falls_back(self):
        self.env["DISPLAY"] = ":0"
        run = Recorder({"xdg-user-dir": self.xdg, "kdialog": self.kdialog(2)})
        self.assertEqual(save.ask(str(self.pdf), "x", self.env, run), str(self.docs / "x.pdf"))

    def test_french(self):
        self.env.update(LANG="fr_CA.UTF-8", DISPLAY=":0")
        run = Recorder({"xdg-user-dir": self.xdg, "kdialog": self.kdialog(1)})
        save.ask(str(self.pdf), "x", self.env, run)
        self.assertIn("Enregistrer en PDF", run.calls[-1][0])

    def test_receive_hands_over_to_the_session(self):
        runtime = self.tmp / "run"
        runtime.mkdir()
        (runtime / "bus").touch()
        self.env["XDG_RUNTIME_DIR"] = str(runtime)
        run = Recorder()
        staged = save.receive("42", "Plan", self.env, io.BytesIO(b"%PDF data"), run)
        self.assertEqual(staged, str(runtime / "raye-pdf" / "job-42.pdf"))
        self.assertEqual(pathlib.Path(staged).read_bytes(), b"%PDF data")
        self.assertEqual(os.stat(runtime / "raye-pdf").st_mode & 0o777, 0o700)
        cmd = run.calls[0][0]
        self.assertEqual(cmd[:4], ["systemd-run", "--user", "--quiet", "--collect"])
        self.assertEqual(cmd[-3:], [save.SELF, staged, "Plan"])

    def test_receive_without_the_session_manager(self):
        runtime = self.tmp / "run"
        runtime.mkdir()
        (runtime / "bus").touch()
        self.env["XDG_RUNTIME_DIR"] = str(runtime)
        run = Recorder({"systemd-run": Result(1), "xdg-user-dir": self.xdg})
        target = save.receive("5", "Plan", self.env, io.BytesIO(b"%PDF"), run)
        self.assertEqual(target, str(self.docs / "Plan.pdf"))
        self.assertFalse((runtime / "raye-pdf").exists(), "the staging folder is cleaned up")

    def test_receive_without_a_session(self):
        (self.docs).mkdir()
        (self.docs / "Plan.pdf").write_bytes(b"older")
        run = Recorder({"xdg-user-dir": self.xdg})
        target = save.receive("5", "Plan", self.env, io.BytesIO(b"%PDF"), run)
        self.assertEqual(target, str(self.docs / "Plan (2).pdf"))
        self.assertEqual((self.docs / "Plan.pdf").read_bytes(), b"older")


SETUP = PRINT / "raye-print-to-pdf"


class Main(unittest.TestCase):
    def test_saved_files_are_not_private_like_the_print_server(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, LANG="C", PATH="/nonexistent")
            env.pop("XDG_RUNTIME_DIR", None)
            out = subprocess.run([sys.executable, "-I", str(PRINT / "raye-pdf-save"), "--receive", "3", "a.txt"],
                                 input=b"%PDF", env=env, capture_output=True, preexec_fn=lambda: os.umask(0o077))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(os.stat(os.path.join(home, "Documents", "a.pdf")).st_mode & 0o777, 0o644)


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.fake("lpstat", "#!/bin/sh\ncat %s/queues 2>/dev/null\n" % self.tmp)
        self.fake("lpadmin", "#!/bin/sh\nprintf '%%s\\n' \"$@\" > %s/lpadmin\nexit ${LPADMIN_EXIT:-0}\n" % self.tmp)
        self.locale = self.tmp / "locale"
        self.env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "RAYE_PDF_DONE": str(self.tmp / "state" / "done"),
                    "RAYE_PDF_PPD": "/usr/share/raye/print-to-pdf.ppd", "RAYE_LOCALE_FILE": str(self.locale),
                    "RAYE_PAPERSIZE_FILE": str(self.tmp / "papersize")}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def setup(self, lang="en_CA.UTF-8"):
        self.locale.write_text('LANG="%s"\n' % lang)
        return subprocess.run(["sh", str(SETUP)], env=self.env, capture_output=True, text=True)

    def lpadmin(self):
        path = self.tmp / "lpadmin"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else None

    def test_adds_a_private_printer_with_a_readable_name(self):
        self.assertEqual(self.setup().returncode, 0)
        args = self.lpadmin()
        self.assertEqual(args[:2], ["-p", "Print%sto%sPDF" % (NBSP, NBSP)])
        for want in (["-v", "raye-pdf:/"], ["-P", "/usr/share/raye/print-to-pdf.ppd"],
                     ["-D", "Print to PDF"], ["-o", "printer-is-shared=false"], ["-o", "PageSize=Letter"]):
            self.assertIn(want, [args[i:i + 2] for i in range(len(args) - 1)])
        self.assertIn("-E", args)
        self.assertNotIn("-d", args, "never the default printer")
        self.assertTrue((self.tmp / "state" / "done").exists())

    def test_french_name_and_paper_elsewhere(self):
        self.setup("fr_FR.UTF-8")
        args = self.lpadmin()
        self.assertEqual(args[1], "Imprimer%sen%sPDF" % (NBSP, NBSP))
        self.assertIn("Imprimer en PDF", args)
        self.assertIn("PageSize=A4", args)

    def test_system_paper_size_wins(self):
        (self.tmp / "papersize").write_text("# set by the installer\nletter\n")
        self.setup("fr_FR.UTF-8")
        self.assertIn("PageSize=Letter", self.lpadmin())

    def test_once_only(self):
        self.setup()
        (self.tmp / "lpadmin").unlink()
        self.setup()
        self.assertIsNone(self.lpadmin(), "removed by the person, it stays removed")

    def test_an_existing_queue_is_kept(self):
        (self.tmp / "queues").write_text("device for PDF: raye-pdf:/\n")
        self.assertEqual(self.setup().returncode, 0)
        self.assertIsNone(self.lpadmin())
        self.assertTrue((self.tmp / "state" / "done").exists())

    def test_tries_again_when_the_server_fails(self):
        self.env["LPADMIN_EXIT"] = "1"
        self.assertEqual(self.setup().returncode, 1)
        self.assertFalse((self.tmp / "state" / "done").exists())


class Packaging(unittest.TestCase):
    PATHS = (BASE / "debian" / "raye-release-paths").read_text()

    def test_shipped_by_the_desktop(self):
        for src, dest in (("raye-pdf", "usr/lib/cups/backend/raye-pdf"),
                          ("raye-pdf-save", "usr/libexec/raye-pdf-save"),
                          ("raye-print-to-pdf", "usr/libexec/raye-print-to-pdf"),
                          ("raye-print-to-pdf.service", "usr/lib/systemd/system/raye-print-to-pdf.service"),
                          ("print-to-pdf.ppd", "usr/share/raye/print-to-pdf.ppd")):
            self.assertTrue(re.search(r"^raye-desktop\s+release/print/%s\s+%s\s*$" % (re.escape(src), re.escape(dest)),
                                      self.PATHS, re.M), src)

    def test_setup_runs_once_at_boot(self):
        unit = (PRINT / "raye-print-to-pdf.service").read_text()
        self.assertIn("ConditionPathExists=!/var/lib/raye-desktop/print-to-pdf", unit)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("WantedBy=multi-user.target", unit)
        self.assertIn("/var/lib/raye-desktop/print-to-pdf", SETUP.read_text())

    def test_ppd_turns_everything_into_pdf(self):
        ppd = (PRINT / "print-to-pdf.ppd").read_text(encoding="latin-1")
        self.assertIn('*cupsFilter2: "application/vnd.cups-pdf application/pdf 0 -"', ppd)
        for size in ("Letter", "A4", "Legal"):
            self.assertIn("*PageSize %s/" % size, ppd)
        if shutil.which("cupstestppd"):
            out = subprocess.run(["cupstestppd", "-W", "none", str(PRINT / "print-to-pdf.ppd")],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout)

    def test_programs_are_executable(self):
        for name in ("raye-pdf", "raye-pdf-save", "raye-print-to-pdf"):
            self.assertTrue(os.access(PRINT / name, os.X_OK), name)


if __name__ == "__main__":
    unittest.main()
