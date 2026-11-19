"""Raye Synth: started on demand, stopped once idle, named the Raye way."""

import os
import pathlib
import re
import subprocess
import tempfile
import time
import unittest

MIDI = pathlib.Path(__file__).resolve().parent.parent
BASE = MIDI.parent.parent
SCRIPT = MIDI / "raye-synth"
UNIT = MIDI / "raye-synth.service"

KERNEL_LIST = """\
Client info
  cur  clients : 4
  peak clients : 5
  max  clients : 192

Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-)
    Connecting To: 15:0
  Port   1 : "Announce" (R-e-)
    Connecting To: 15:0
Client  14 : "Midi Through" [Kernel Legacy]
  Port   0 : "Midi Through Port-0" (RWe-)
Client 129 : "Windows MIDI" [User Legacy]
  Port   0 : "MIDI Out" (R-e-)
    Connecting To: 128:0
  Output pool :
    Pool size          : 500
    Cells in use       : 0
    Peak cells in use  : 3
    Alloc success      : 900
    Alloc failures     : 0
"""


def synth_block(events=0, connected=""):
    block = 'Client 128 : "Raye Synth" [User Legacy]\n  Port   0 : "Raye Synth" (-We-)\n'
    if connected:
        block += "    Connected From: %s\n" % connected
    block += ("  Output pool :\n    Pool size          : 500\n    Alloc success      : 7\n"
              "  Input pool :\n    Pool size          : 200\n    Cells in use       : 0\n"
              "    Alloc success      : %d\n    Alloc failures     : 0\n" % events)
    return block


# Stands for fluidsynth: puts the synth in the client list while it runs,
# writes its arguments down, and quits at the end of its input like the real
# one.
FAKE_SYNTH = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_DIR/args"
cat "$FAKE_DIR/base" "$FAKE_DIR/block" > "$RAYE_SEQ_CLIENTS"
cat >/dev/null
cp "$FAKE_DIR/base" "$RAYE_SEQ_CLIENTS"
echo stopped >> "$FAKE_DIR/log"
"""


class Synth(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.clients = self.tmp / "clients"
        (self.tmp / "base").write_text(KERNEL_LIST)
        (self.tmp / "block").write_text(synth_block())
        self.clients.write_text(KERNEL_LIST)
        self.font = self.tmp / "TimGM6mb.sf2"
        self.font.write_bytes(b"RIFF")
        self.fake("fluidsynth", FAKE_SYNTH)
        self.env = dict(os.environ, PATH="%s:/usr/bin:/bin" % self.bin, FAKE_DIR=str(self.tmp),
                        RAYE_SEQ_CLIENTS=str(self.clients), RAYE_SYNTH_FONTS=str(self.font),
                        XDG_RUNTIME_DIR=str(self.tmp), RAYE_SYNTH_CHECK="1", RAYE_SYNTH_IDLE="2")

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def fake(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def synth(self, *args, **kw):
        return subprocess.run(["sh", str(SCRIPT), *args], env=self.env, capture_output=True,
                              text=True, timeout=kw.get("timeout", 20))

    def test_status_reads_the_kernel_list(self):
        self.assertEqual(self.synth("status").stdout, "")
        self.clients.write_text(KERNEL_LIST + synth_block(1234, "129:0, 130:0"))
        self.assertEqual(self.synth("status").stdout, "1234 2\n")

    def test_status_counts_only_what_the_synth_received(self):
        self.clients.write_text(KERNEL_LIST + synth_block(5))
        self.assertEqual(self.synth("status").stdout, "5 0\n", "output pools and other clients")

    def test_status_without_a_sequencer(self):
        self.clients.unlink()
        out = self.synth("status")
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_start_does_nothing_when_it_runs(self):
        self.clients.write_text(KERNEL_LIST + synth_block())
        self.fake("systemctl", "#!/bin/sh\necho called >> %s/systemctl\n" % self.tmp)
        self.assertEqual(self.synth("start").returncode, 0)
        self.assertFalse((self.tmp / "systemctl").exists())

    def test_start_asks_the_session_and_waits_for_the_port(self):
        self.fake("systemctl", "#!/bin/sh\necho \"$@\" > %s/systemctl\n"
                  "(sleep 0.5; cat %s/base %s/block > %s) &\n" % (self.tmp, self.tmp, self.tmp, self.clients))
        out = self.synth("start")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((self.tmp / "systemctl").read_text().split(),
                         ["--user", "start", "--no-block", "raye-synth.service"])

    def test_start_without_a_session_runs_it_directly(self):
        self.fake("systemctl", "#!/bin/sh\nexit 1\n")
        out = self.synth("start")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Raye Synth", self.clients.read_text())
        self.wait_for(lambda: "stopped" in self.read("log"), 10)

    def test_start_gives_up_after_three_seconds(self):
        self.fake("systemctl", "#!/bin/sh\nexit 0\n")
        begin = time.monotonic()
        out = self.synth("start")
        self.assertEqual(out.returncode, 1)
        self.assertLess(time.monotonic() - begin, 6)
        self.assertIn("did not start", out.stderr)

    def test_run_stops_once_nothing_plays(self):
        begin = time.monotonic()
        out = self.synth("run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("stopped", self.read("log"))
        self.assertNotIn("Raye Synth", self.clients.read_text())
        self.assertLess(time.monotonic() - begin, 10)

    def test_run_keeps_going_while_held_open_or_playing(self):
        (self.tmp / "block").write_text(synth_block(0, "129:0"))
        proc = subprocess.Popen(["sh", str(SCRIPT), "run"], env=self.env)
        try:
            time.sleep(4.5)
            self.assertIsNone(proc.poll(), "a program has it open")
            for events in (10, 20, 30):
                self.clients.write_text(KERNEL_LIST + synth_block(events))
                time.sleep(1.2)
            self.assertIsNone(proc.poll(), "notes keep arriving")
            self.assertEqual(proc.wait(timeout=10), 0)
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_run_stops_when_its_port_never_shows(self):
        self.fake("fluidsynth", "#!/bin/sh\ncat >/dev/null\necho stopped >> $FAKE_DIR/log\n")
        self.assertEqual(self.synth("run").returncode, 0)
        self.assertIn("stopped", self.read("log"))

    def test_run_stops_the_synth_when_the_service_stops(self):
        (self.tmp / "block").write_text(synth_block(0, "129:0"))
        proc = subprocess.Popen(["sh", str(SCRIPT), "run"], env=self.env)
        self.wait_for(lambda: "Raye Synth" in self.clients.read_text(), 5)
        proc.terminate()
        self.assertEqual(proc.wait(timeout=5), 0)
        self.assertIn("stopped", self.read("log"))

    def test_run_plays_through_pipewire_under_the_raye_name(self):
        self.synth("run")
        args = self.read("args").splitlines()
        self.assertEqual(args[-1], str(self.font))
        joined = " ".join(args)
        for want in ("-a pipewire", "-m alsa_seq", "-o midi.portname=Raye Synth", "-o midi.autoconnect=0"):
            self.assertIn(want, joined)
        self.assertNotIn("-s", args, "the shell server listens on a TCP port")
        self.assertNotIn("-i", args, "without its shell it quits at once")

    def test_run_needs_a_sound_font(self):
        self.env["RAYE_SYNTH_FONTS"] = str(self.tmp / "none.sf2")
        out = self.synth("run")
        self.assertEqual(out.returncode, 1)
        self.assertIn("sound font", out.stderr)
        self.assertFalse((self.tmp / "args").exists())

    def test_first_font_found_wins(self):
        other = self.tmp / "default-GM.sf3"
        other.write_bytes(b"RIFF")
        self.env["RAYE_SYNTH_FONTS"] = "%s %s" % (other, self.font)
        self.synth("run")
        self.assertEqual(self.read("args").splitlines()[-1], str(other))

    def read(self, name):
        path = self.tmp / name
        return path.read_text() if path.exists() else ""

    def wait_for(self, check, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if check():
                return
            time.sleep(0.1)
        self.fail("timed out")


class Packaging(unittest.TestCase):
    def test_unit_is_started_on_demand_only(self):
        text = UNIT.read_text()
        self.assertIn("ExecStart=/usr/libexec/raye-synth run", text)
        self.assertNotIn("[Install]", text)

    def test_shipped_by_the_desktop(self):
        paths = (BASE / "debian" / "raye-release-paths").read_text()
        self.assertTrue(re.search(r"^raye-desktop\s+release/midi/raye-synth\s+usr/libexec/raye-synth$",
                                  paths, re.M))
        self.assertTrue(re.search(r"^raye-desktop\s+release/midi/raye-synth\.service\s+"
                                  r"usr/lib/systemd/user/raye-synth\.service$", paths, re.M))

    def test_desktop_brings_the_synth_and_a_font(self):
        control = (BASE / "debian" / "control").read_text()
        stanza = control.split("Package: raye-desktop\n", 1)[1].split("\nPackage:", 1)[0]
        stanza = re.sub(r"^#.*\n", "", stanza, flags=re.M)
        self.assertTrue(re.search(r"\bfluidsynth\b", stanza))
        self.assertTrue(re.search(r"\btimgm6mb-soundfont\b", stanza))

    def test_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
