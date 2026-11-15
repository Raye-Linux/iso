#!/usr/bin/python3
"""Tests of raye-tpm.

The event logs under fixtures/ come from real boots (make-fixtures.sh):
OVMF with Secure Boot, a software TPM with both banks, the signed shim
and GRUB. Each folder holds the log, the Secure Boot variables and the
PCR 7 the TPM showed at that boot:

  stock  the kernel signed by its vendor
  mok    the kernel signed by a key enrolled in MokList (mok-cert.der),
         the way the Raye kernel is
  dbx    "stock" after a hash was appended to dbx

So "predict the next boot from this boot" is checked against what the
TPM really showed at that next boot.

Run: python3 -m unittest discover -s release/tpm/tests
"""

import base64
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import uuid

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
TOOL = os.path.join(HERE, "..", "raye-tpm")

_loader = importlib.machinery.SourceFileLoader("raye_tpm", TOOL)
_spec = importlib.util.spec_from_loader("raye_tpm", _loader)
rt = importlib.util.module_from_spec(_spec)
_loader.exec_module(rt)


def fixture_log(name):
    with open(os.path.join(FIXTURES, name, "binary_bios_measurements"), "rb") as f:
        return f.read()


def fixture_events(name):
    return rt.parse_event_log(fixture_log(name))


def fixture_pcr(name):
    with open(os.path.join(FIXTURES, name, "pcr7.txt")) as f:
        return {bank: bytes.fromhex(value) for bank, value in (l.split() for l in f)}


def efivars(name):
    return os.path.join(FIXTURES, name, "efivars")


with open(os.path.join(FIXTURES, "mok-cert.der"), "rb") as _f:
    CERT = _f.read()


# ---------------------------------------------------------------- log writers

def agile_log(events, algs=((0x0004, 20), (0x000B, 32))):
    """A crypto-agile log: Spec ID header, then TCG_PCR_EVENT2 records.
    events: (pcr, type, {bank: digest}, data)."""
    spec = b"Spec ID Event03\0" + struct.pack("<IBBBBI", 0, 0, 2, 0, 2, len(algs))
    for alg, size in algs:
        spec += struct.pack("<HH", alg, size)
    spec += b"\0"
    out = struct.pack("<II20sI", 0, rt.EV_NO_ACTION, bytes(20), len(spec)) + spec
    ids = {"sha1": 0x0004, "sha256": 0x000B}
    for pcr, etype, digests, data in events:
        out += struct.pack("<III", pcr, etype, len(digests))
        for bank, digest in digests.items():
            out += struct.pack("<H", ids[bank]) + digest
        out += struct.pack("<I", len(data)) + data
    return out


def legacy_log(events):
    """A SHA-1 only log: TCG_PCR_EVENT records, no header."""
    out = b""
    for pcr, etype, digests, data in events:
        out += struct.pack("<II20sI", pcr, etype, digests["sha1"], len(data)) + data
    return out


def as_tuples(events):
    return [(e.pcr, e.type, dict(e.digests), e.data) for e in events]


def hashes(data, banks=("sha1", "sha256")):
    return {b: hashlib.new(b, data).digest() for b in banks}


def write_var(folder, name, guid, value, attrs=7):
    with open(os.path.join(folder, "%s-%s" % (name, guid)), "wb") as f:
        f.write(struct.pack("<I", attrs) + value)


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def copy_vars(self, name):
        dst = os.path.join(self.tmp, "efivars-" + name)
        shutil.copytree(efivars(name), dst)
        return dst


# ---------------------------------------------------------------- parsing and replay

class ReplayTest(unittest.TestCase):
    def test_real_logs_replay_to_the_tpm_in_both_banks(self):
        for name in ("stock", "mok", "dbx"):
            events = fixture_events(name)
            for bank in ("sha1", "sha256"):
                with self.subTest(name=name, bank=bank):
                    self.assertEqual(rt.replay(events, bank), fixture_pcr(name)[bank])

    def test_log_banks(self):
        self.assertEqual(rt.log_banks(fixture_events("stock")), {"sha1", "sha256"})

    def test_pcr7_events_of_a_real_boot(self):
        kinds = [(e.type, (rt.parse_variable_data(e.data) or ("?",))[0])
                 for e in rt.pcr_events(fixture_events("mok"))]
        self.assertEqual(kinds[:6], [
            (rt.EV_EFI_VARIABLE_DRIVER_CONFIG, "SecureBoot"),
            (rt.EV_EFI_VARIABLE_DRIVER_CONFIG, "PK"),
            (rt.EV_EFI_VARIABLE_DRIVER_CONFIG, "KEK"),
            (rt.EV_EFI_VARIABLE_DRIVER_CONFIG, "db"),
            (rt.EV_EFI_VARIABLE_DRIVER_CONFIG, "dbx"),
            (rt.EV_SEPARATOR, "?"),
        ])
        self.assertEqual(kinds[-1], (rt.EV_EFI_VARIABLE_AUTHORITY, "MokListRT"))

    def test_sha1_only_log(self):
        events = fixture_events("stock")
        raw = legacy_log([t for t in as_tuples(events)])
        legacy = rt.parse_event_log(raw)
        self.assertEqual(rt.log_banks(legacy), {"sha1"})
        self.assertEqual(rt.replay(legacy, "sha1"), fixture_pcr("stock")["sha1"])
        with self.assertRaises(rt.LogError):
            rt.replay(legacy, "sha256")

    def test_zero_padding_after_the_last_event_is_ignored(self):
        raw = fixture_log("stock") + bytes(64)
        self.assertEqual(rt.replay(rt.parse_event_log(raw), "sha256"), fixture_pcr("stock")["sha256"])

    def test_cut_log_is_an_error(self):
        raw = fixture_log("stock")
        for cut in (10, 40, len(raw) - 3):
            with self.subTest(cut=cut), self.assertRaises(rt.LogError):
                rt.parse_event_log(raw[:cut])

    def test_undeclared_algorithm_is_an_error(self):
        raw = agile_log([(7, rt.EV_SEPARATOR, hashes(bytes(4)), bytes(4))], algs=((0x000B, 32),))
        with self.assertRaises(rt.LogError):
            rt.parse_event_log(raw)

    def test_no_action_events_do_not_extend(self):
        events = [(7, rt.EV_NO_ACTION, hashes(b"x"), b"x"), (7, rt.EV_SEPARATOR, hashes(bytes(4)), bytes(4))]
        got = rt.replay(rt.parse_event_log(agile_log(events)), "sha256")
        self.assertEqual(got, rt.extend("sha256", [hashlib.sha256(bytes(4)).digest()]))

    def test_variable_data_round_trip(self):
        data = rt.variable_data("dbx", rt.EFI_IMAGE_SECURITY_GUID, b"\x01\x02")
        self.assertEqual(rt.parse_variable_data(data), ("dbx", rt.EFI_IMAGE_SECURITY_GUID, b"\x01\x02"))
        self.assertIsNone(rt.parse_variable_data(data + b"\0"))
        self.assertIsNone(rt.parse_variable_data(b"short"))


# ---------------------------------------------------------------- prediction

class PredictTest(Folder):
    def check(self, log, kernel, varsdir, expected, cert=CERT, learned=None):
        events = fixture_events(log)
        for bank in ("sha1", "sha256"):
            with self.subTest(log=log, kernel=kernel, bank=bank):
                got = rt.predict(events, kernel, bank, varsdir, cert, learned)
                self.assertEqual(got.hex(), fixture_pcr(expected)[bank].hex())

    def test_same_kernel_nothing_changed(self):
        self.check("stock", "ubuntu", efivars("stock"), "stock")
        self.check("mok", "raye", efivars("mok"), "mok")

    def test_switch_to_a_kernel_verified_with_moklist(self):
        # the bind-next --kernel raye case: built from the certificate only
        self.check("stock", "raye", efivars("mok"), "mok")

    def test_switch_back_to_the_vendor_kernel(self):
        self.check("mok", "ubuntu", efivars("stock"), "stock")

    def test_dbx_update_written_but_not_booted(self):
        self.check("stock", "ubuntu", efivars("dbx"), "dbx")
        self.assertNotEqual(fixture_pcr("stock"), fixture_pcr("dbx"))

    def test_constructed_authority_event_matches_the_real_one(self):
        real = rt.learn_raye_authority(fixture_events("mok"), CERT)
        made = rt.raye_authority_event(CERT, {"sha256"}, efivars("mok")).data
        self.assertIsNotNone(real)
        self.assertEqual(made, real)

    def test_learned_bytes_win(self):
        learned = rt.learn_raye_authority(fixture_events("mok"), CERT)
        self.check("stock", "raye", efivars("stock"), "mok", learned=learned)

    def test_no_raye_event_without_secure_boot(self):
        varsdir = self.copy_vars("mok")
        write_var(varsdir, "SecureBoot", rt.EFI_GLOBAL_GUID, b"\x00")
        events = fixture_events("stock")
        raye = rt.predicted_events(events, "raye", varsdir, CERT)
        ubuntu = rt.predicted_events(events, "ubuntu", varsdir, CERT)
        self.assertEqual([e.data for e in raye], [e.data for e in ubuntu])

    def test_no_raye_event_when_shim_checks_are_off(self):
        varsdir = self.copy_vars("mok")
        write_var(varsdir, "MokSBStateRT", rt.SHIM_LOCK_GUID, b"\x01")
        events = fixture_events("stock")
        self.assertEqual(len(rt.predicted_events(events, "raye", varsdir, CERT)),
                         len(rt.predicted_events(events, "ubuntu", varsdir, CERT)))

    def test_missing_variable_is_measured_empty(self):
        varsdir = self.copy_vars("stock")
        os.unlink(os.path.join(varsdir, "dbx-" + rt.EFI_IMAGE_SECURITY_GUID))
        events = rt.predicted_events(fixture_events("stock"), "ubuntu", varsdir, CERT)
        dbx = [rt.parse_variable_data(e.data) for e in events
               if e.type == rt.EV_EFI_VARIABLE_DRIVER_CONFIG and rt.parse_variable_data(e.data)[0] == "dbx"]
        self.assertEqual(dbx, [("dbx", rt.EFI_IMAGE_SECURITY_GUID, b"")])

    def test_raye_kernel_needs_the_certificate(self):
        with self.assertRaises(rt.Refused):
            rt.predict(fixture_events("stock"), "raye", "sha256", efivars("mok"), None)

    def test_unknown_variable_measurement_is_refused(self):
        tuples = as_tuples(fixture_events("stock"))
        for i, (pcr, etype, digests, data) in enumerate(tuples):
            if etype == rt.EV_EFI_VARIABLE_DRIVER_CONFIG:
                tuples[i] = (pcr, etype, {b: bytes(len(d)) for b, d in digests.items()}, data)
                break
        events = rt.parse_event_log(agile_log(tuples))
        with self.assertRaises(rt.Refused):
            rt.predict(events, "ubuntu", "sha256", efivars("stock"), CERT)

    def test_unreadable_secure_boot_event_is_refused(self):
        tuples = [(7, rt.EV_EFI_VARIABLE_DRIVER_CONFIG, hashes(b"junk"), b"junk")]
        with self.assertRaises(rt.Refused):
            rt.predict(rt.parse_event_log(agile_log(tuples)), "ubuntu", "sha256", efivars("stock"), CERT)

    def test_firmware_that_hashes_the_value_only(self):
        # some firmware hashes the variable's value instead of the whole
        # structure: the new event is hashed the same way
        old = b"\x11" * 40
        data = rt.variable_data("dbx", rt.EFI_IMAGE_SECURITY_GUID, old)
        sep = (7, rt.EV_SEPARATOR, hashes(bytes(4)), bytes(4))
        events = rt.parse_event_log(agile_log([(7, rt.EV_EFI_VARIABLE_DRIVER_CONFIG, hashes(old), data), sep]))
        varsdir = os.path.join(self.tmp, "vars")
        os.mkdir(varsdir)
        new = b"\x22" * 48
        write_var(varsdir, "dbx", rt.EFI_IMAGE_SECURITY_GUID, new)
        got = rt.predict(events, "ubuntu", "sha256", varsdir, CERT)
        self.assertEqual(got, rt.extend("sha256", [hashlib.sha256(new).digest(), hashlib.sha256(bytes(4)).digest()]))

    def test_other_variable_events_are_kept_as_recorded(self):
        # a firmware variable outside the Secure Boot set is not recomputed
        data = rt.variable_data("Other", rt.EFI_GLOBAL_GUID, b"v")
        events = rt.parse_event_log(agile_log([(7, rt.EV_EFI_VARIABLE_DRIVER_CONFIG, hashes(b"x"), data)]))
        got = rt.predict(events, "ubuntu", "sha256", efivars("stock"), CERT)
        self.assertEqual(got, rt.extend("sha256", [hashlib.sha256(b"x").digest()]))

    def test_mok_owner(self):
        self.assertEqual(rt.mok_owner(efivars("mok"), CERT), uuid.UUID(rt.SHIM_LOCK_GUID).bytes_le)
        varsdir = os.path.join(self.tmp, "vars")
        os.mkdir(varsdir)
        owner = uuid.uuid4().bytes_le
        entry = owner + CERT
        sig_list = (uuid.UUID(rt.EFI_CERT_X509_GUID).bytes_le
                    + struct.pack("<III", 28 + len(entry), 0, len(entry)) + entry)
        write_var(varsdir, "MokListRT", rt.SHIM_LOCK_GUID, sig_list)
        self.assertEqual(rt.mok_owner(varsdir, CERT), owner)
        write_var(varsdir, "MokListRT", rt.SHIM_LOCK_GUID, b"\xff" * 10)
        self.assertEqual(rt.mok_owner(varsdir, CERT), uuid.UUID(rt.SHIM_LOCK_GUID).bytes_le)


# ---------------------------------------------------------------- commands, with a fake machine

class FakeMachine(rt.System):
    """A computer with one encrypted disk bound to a software TPM that
    behaves like clevis: a binding opens the disk only if the PCR 7 it
    was sealed to is the current one, or always if it has no PCR."""

    def __init__(self, tmp, log="stock", live="stock", kernel="ubuntu", raye_installed=False,
                 varsname="stock"):
        state = os.path.join(tmp, "state")
        certfile = os.path.join(tmp, "raye-boot.der")
        with open(certfile, "wb") as f:
            f.write(CERT)
        logfile = os.path.join(tmp, "log")
        if log is not None:
            with open(logfile, "wb") as f:
                f.write(fixture_log(log))
        super().__init__(event_log=logfile, efivars=efivars(varsname), state_dir=state,
                         cert=certfile, crypttab=os.path.join(tmp, "crypttab"),
                         boot_glob=os.path.join(tmp, "boot", "vmlinuz-*-raye"),
                         sysfs_pcr=os.path.join(tmp, "nope", "{bank}", "{index}"),
                         boot_id=os.path.join(tmp, "boot_id"))
        os.makedirs(os.path.join(tmp, "boot"))
        if raye_installed:
            open(os.path.join(tmp, "boot", "vmlinuz-7.0.0-42-raye"), "w").close()
        self.tmp = tmp
        self.kernel = kernel
        self.set_boot("boot-1")
        self.pcr = dict(fixture_pcr(live))
        self.calls = []
        self.binds = []
        self.unbinds = []
        self.unseals = 0
        self.old_clevis = False
        self.counter = 0
        # slot -> sealed (bank, value), passphrase
        self.slots = {1: {"cfg": {"hash": "sha256", "key": "ecc", "pcr_bank": "sha256", "pcr_ids": "7"},
                          "sealed": ("sha256", self.pcr["sha256"]), "pass": b"pass-one"}}
        self.disks = [("/dev/vda3", "11111111-2222-3333-4444-555555555555")]
        self.bind_ok = True

    def set_boot(self, boot):
        with open(self.boot_id_path, "w") as f:
            f.write(boot + "\n")

    def running_kernel(self):
        return self.kernel

    def luks_devices(self):
        return list(self.disks)

    def run(self, argv, data=None):
        assert isinstance(argv, list)
        self.calls.append(argv)
        if argv[:2] == ["tpm2_pcrread", "sha256:7"] or argv[:2] == ["tpm2_pcrread", "sha1:7"]:
            bank = argv[1].split(":")[0]
            return 0, ("  %s:\n    7 : 0x%s\n" % (bank, self.pcr[bank].hex().upper())).encode()
        if argv[:3] == ["clevis", "luks", "list"]:
            lines = ["%d: tpm2 '%s'" % (s, json.dumps(v["cfg"], separators=(",", ":")))
                     for s, v in sorted(self.slots.items())]
            lines.insert(0, "0: tang '{\"url\":\"http://x\"}'")
            return 0, ("\n".join(lines) + "\n").encode()
        if argv[:3] == ["bash", "-c", rt.UNSEAL_SLOT]:
            if self.old_clevis:
                return 2, b""
            argv = ["clevis", "luks", "pass", "-d", argv[4], "-s", argv[5]]
            self.unseals += 1
        if argv[:3] == ["clevis", "luks", "pass"]:
            slot = self.slots.get(int(argv[argv.index("-s") + 1]))
            if slot and (slot["sealed"] is None
                         or slot["sealed"] == (slot["sealed"][0], self.pcr[slot["sealed"][0]])):
                return 0, slot["pass"]
            return 1, b""
        if argv[:3] == ["clevis", "luks", "bind"]:
            self.binds.append((argv, data))
            cfg = json.loads(argv[-1])
            if not self.bind_ok or data.rstrip(b"\n") not in [s["pass"] for s in self.slots.values()]:
                return 1, b""
            if "pcr_ids" in cfg:
                digest = base64.urlsafe_b64decode(cfg["pcr_digest"] + "=" * (-len(cfg["pcr_digest"]) % 4))
                sealed = (cfg["pcr_bank"], digest)
            else:
                sealed = None
            self.counter += 1
            slot = max(self.slots) + 1
            # clevis lists the config with its defaults, never the digest
            stored = dict({"hash": "sha256", "key": "ecc"},
                          **{k: v for k, v in cfg.items() if k != "pcr_digest"})
            self.slots[slot] = {"cfg": stored, "sealed": sealed, "pass": b"pass-%d" % (slot * 7)}
            return 0, b""
        if argv[:3] == ["clevis", "luks", "unbind"]:
            self.unbinds.append(int(argv[argv.index("-s") + 1]))
            del self.slots[int(argv[argv.index("-s") + 1])]
            return 0, b""
        raise AssertionError("unexpected command %r" % argv)

    def reboot(self, live, kernel, boot, log=None):
        self.pcr = dict(fixture_pcr(live))
        self.kernel = kernel
        self.set_boot(boot)
        if log:
            with open(self.event_log, "wb") as f:
                f.write(fixture_log(log))


class CommandTest(Folder):
    def machine(self, **kw):
        return FakeMachine(self.tmp, **kw)

    def run_tool(self, m, *argv):
        out, err = io.StringIO(), io.StringIO()
        rc = rt.main(list(argv), system=m, out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    def state(self, m):
        with open(os.path.join(m.state_dir, "bindings.json")) as f:
            return json.load(f)

    def slots_state(self, m):
        return self.state(m)["disks"]["11111111-2222-3333-4444-555555555555"]["slots"]

    # -- replay / predict
    def test_replay_matches(self):
        rc, out, _ = self.run_tool(self.machine(), "replay")
        self.assertEqual(rc, 0)
        self.assertIn("matches the TPM", out)
        self.assertIn(fixture_pcr("stock")["sha256"].hex(), out)

    def test_replay_mismatch(self):
        rc, _, err = self.run_tool(self.machine(live="dbx"), "replay", "--bank", "sha1")
        self.assertEqual(rc, rt.EXIT_REFUSED)
        self.assertIn("differs", err)

    def test_predict_prints_the_next_value(self):
        m = self.machine(varsname="mok")
        rc, out, _ = self.run_tool(m, "predict", "--kernel", "raye")
        self.assertEqual((rc, out.strip()), (0, "sha256 " + fixture_pcr("mok")["sha256"].hex()))
        rc, out, _ = self.run_tool(m, "predict", "--kernel", "raye", "--bank", "sha1")
        self.assertEqual(out.strip(), "sha1 " + fixture_pcr("mok")["sha1"].hex())

    def test_bad_arguments_are_an_error_not_a_refusal(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            rt.main(["bind-next", "--kernel", "other"], system=self.machine())
        self.assertEqual(cm.exception.code, rt.EXIT_ERROR)

    def test_no_event_log(self):
        m = self.machine(log=None)
        rc, _, err = self.run_tool(m, "predict", "--kernel", "ubuntu")
        self.assertEqual(rc, rt.EXIT_NOTHING)
        self.assertIn("no TPM event log", err)

    def test_predict_refused_when_log_does_not_replay(self):
        rc, _, err = self.run_tool(self.machine(live="mok"), "predict", "--kernel", "raye")
        self.assertEqual(rc, rt.EXIT_REFUSED)
        self.assertIn("nothing was changed", err)

    # -- bind-next
    def test_bind_next_then_boot_opens_without_password(self):
        m = self.machine(varsname="mok")
        rc, out, _ = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(m.binds), 1)
        argv, data = m.binds[0]
        self.assertEqual(argv[:9], ["clevis", "luks", "bind", "-y", "-k", "-", "-d", "/dev/vda3", "tpm2"])
        cfg = json.loads(argv[9])
        self.assertEqual((cfg["pcr_bank"], cfg["pcr_ids"]), ("sha256", "7"))
        self.assertNotIn("=", cfg["pcr_digest"])
        self.assertEqual(data, b"pass-one\n")
        self.assertEqual(self.slots_state(m)["2"]["role"], "predicted")
        self.assertEqual(self.slots_state(m)["2"]["kernel"], "raye")
        # the next boot is the Raye kernel: the new binding opens the disk
        m.reboot("mok", "raye", "boot-2")
        rc, out, _ = self.run_tool(m, "status", "--json")
        report = json.loads(out)
        slots = {s["slot"]: s for s in report["disks"][0]["slots"]}
        self.assertTrue(slots[2]["opens"])
        self.assertFalse(slots[1]["opens"])
        self.assertEqual(report["kernel"], "raye")

    def test_the_key_never_touches_the_disk(self):
        m = self.machine(varsname="mok")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        for root, _, files in os.walk(m.state_dir):
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    content = fh.read()
                self.assertNotIn(b"pass-", content, f)
        mode = os.stat(os.path.join(m.state_dir, "bindings.json")).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertEqual(os.stat(m.state_dir).st_mode & 0o777, 0o700)

    def test_bind_next_twice_binds_once(self):
        m = self.machine(varsname="mok")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        rc, out, _ = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, 0)
        self.assertIn("already bound", out)
        self.assertEqual(len(m.binds), 1)

    def test_bind_next_when_the_current_binding_already_fits(self):
        m = self.machine()
        rc, out, _ = self.run_tool(m, "bind-next", "--kernel", "ubuntu")
        self.assertEqual(rc, 0)
        self.assertEqual(m.binds, [])
        self.assertIn("already", out)
        self.assertEqual(self.slots_state(m)["1"]["role"], "ubuntu-kernel")

    def test_bind_next_refused_changes_nothing(self):
        m = self.machine(live="mok", varsname="mok")
        rc, _, err = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, rt.EXIT_REFUSED)
        self.assertEqual(m.binds, [])
        self.assertIn("refused", err)

    def test_bind_next_without_a_working_binding(self):
        m = self.machine(varsname="mok")
        m.slots[1]["sealed"] = ("sha256", bytes(32))
        rc, _, err = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertEqual(m.binds, [])
        self.assertIn("password stays needed", err)

    def test_bind_next_when_clevis_fails(self):
        m = self.machine(varsname="mok")
        m.bind_ok = False
        rc, _, err = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertIn("could not bind", err)

    def test_bind_next_without_a_tpm_disk(self):
        m = self.machine()
        m.slots = {}
        rc, out, _ = self.run_tool(m, "bind-next", "--kernel", "raye")
        self.assertEqual(rc, rt.EXIT_NOTHING)
        self.assertIn("nothing to do", out)

    def test_bind_uses_the_bank_the_disk_already_uses(self):
        m = self.machine(varsname="mok")
        m.slots[1]["cfg"]["pcr_bank"] = "sha1"
        m.slots[1]["sealed"] = ("sha1", m.pcr["sha1"])
        self.run_tool(m, "bind-next", "--kernel", "raye")
        cfg = json.loads(m.binds[0][0][9])
        self.assertEqual(cfg["pcr_bank"], "sha1")
        digest = base64.urlsafe_b64decode(cfg["pcr_digest"] + "=")
        self.assertEqual(digest, fixture_pcr("mok")["sha1"])

    def test_tpm2_pcrread_is_the_fallback(self):
        m = self.machine()
        self.run_tool(m, "replay")
        self.assertIn(["tpm2_pcrread", "sha256:7"], m.calls)

    def test_sysfs_pcr_is_read_first(self):
        m = self.machine()
        os.makedirs(os.path.join(self.tmp, "nope", "sha256"))
        with open(os.path.join(self.tmp, "nope", "sha256", "7"), "w") as f:
            f.write(m.pcr["sha256"].hex().upper() + "\n")
        rc, _, _ = self.run_tool(m, "replay")
        self.assertEqual(rc, 0)
        self.assertNotIn(["tpm2_pcrread", "sha256:7"], m.calls)

    # -- firmware
    def test_prepare_firmware_binds_for_each_installed_kernel(self):
        m = self.machine(varsname="dbx", raye_installed=True)
        rc, out, _ = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, 0, out)
        sealed = sorted(json.loads(a[9])["pcr_digest"] for a, _ in m.binds
                        if "pcr_digest" in json.loads(a[9]))
        self.assertEqual(len(sealed), 2)
        kernels = sorted(r["kernel"] for r in self.slots_state(m).values() if r["role"] == "predicted")
        self.assertEqual(kernels, ["raye", "ubuntu"])
        # after the dbx update, the ubuntu binding opens the disk
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        rc, out, _ = self.run_tool(m, "status", "--json")
        opens = [s["slot"] for s in json.loads(out)["disks"][0]["slots"]
                 if s["opens"] and s["role"] != "suspended"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(self.slots_state(m)[str(opens[0])]["kernel"], "ubuntu")

    def test_prepare_firmware_without_raye_kernel(self):
        m = self.machine(varsname="dbx")
        self.run_tool(m, "prepare-firmware")
        self.assertEqual(len(m.binds), 2)  # the suspension, then Ubuntu's kernel

    # -- the watch on the Secure Boot variables
    def watch_argv(self):
        """What raye-tpm-watch.service really runs, after the tool's path."""
        with open(os.path.join(HERE, "..", "raye-tpm-watch.service")) as f:
            line = next(l for l in f if l.startswith("ExecStart="))
        argv = line.split("=", 1)[1].split()
        self.assertEqual(argv[0], "/usr/libexec/raye-tpm")
        return argv[1:]

    def test_watch_leaves_the_tpm_alone_when_nothing_was_written(self):
        # sbkeysync opens dbx for writing at every start and the firmware
        # turns the update down: the path unit fires, the variable is the same
        m = self.machine(raye_installed=True)
        rc, out, err = self.run_tool(m, *self.watch_argv())
        self.assertEqual(rc, rt.EXIT_NOTHING, out + err)
        self.assertEqual(m.binds, [])
        self.assertTrue(all("pcr_ids" in v["cfg"] for v in m.slots.values()))
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "suspended")))
        self.assertIn("nothing was written", out)

    def test_watch_after_a_real_dbx_write(self):
        m = self.machine(varsname="dbx", raye_installed=True)
        rc, out, err = self.run_tool(m, *self.watch_argv())
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.bound_cfgs(m)[0], {})
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        rc, _, _ = self.run_tool(m, "resume")
        self.assertEqual(rc, 0)
        self.assertTrue(all("pcr_ids" in v["cfg"] for v in m.slots.values()))

    def test_watch_sees_a_new_variable(self):
        # dbt was not there at boot: written now, the next start measures it
        m = self.machine()
        folder = self.copy_vars("stock")
        write_var(folder, "dbt", rt.EFI_IMAGE_SECURITY_GUID, b"new")
        m.efivars = folder
        self.assertFalse(rt.firmware_unchanged(fixture_events("stock"), folder))
        self.assertTrue(rt.firmware_unchanged(fixture_events("stock"), efivars("stock")))
        self.assertFalse(rt.firmware_unchanged(fixture_events("stock"), efivars("dbx")))

    def test_watch_without_an_event_log_still_suspends(self):
        # it cannot tell, and a written database would lock the disk out
        m = self.machine(log=None)
        rc, out, err = self.run_tool(m, *self.watch_argv())
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.bound_cfgs(m), [{}])

    def test_boots_with_a_refused_dbx_update_never_open_without_pcr(self):
        # the pattern seen in the test VM, start after start
        m = self.machine(raye_installed=True)
        for n in range(2, 8):
            m.reboot("stock", "ubuntu", "boot-%d" % n)
            self.run_tool(m, "resume")
            self.run_tool(m, *self.watch_argv())
            self.assertTrue(all("pcr_ids" in v["cfg"] for v in m.slots.values()), n)
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "suspended")))

    def test_suspend_reads_the_slots_inside_the_lock(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        m.reboot("stock", "ubuntu", "boot-2")
        real = rt.Lock

        class ResumeFirst(real):
            # resume held the lock and removed the old suspension meanwhile
            def __enter__(lock):
                for s in [s for s, v in m.slots.items() if v["sealed"] is None]:
                    del m.slots[s]
                return real.__enter__(lock)

        rt.Lock = ResumeFirst
        try:
            rc, out, err = self.run_tool(m, "suspend")
        finally:
            rt.Lock = real
        self.assertEqual(rc, 0, out + err)
        self.assertTrue([s for s, v in m.slots.items() if v["sealed"] is None])
        self.assertEqual(sorted(int(s) for s in self.slots_state(m)), sorted(m.slots))

    # -- suspension
    def bound_cfgs(self, m):
        return [json.loads(a[9]) for a, _ in m.binds]

    def opening_slots(self, m):
        rc, out, _ = self.run_tool(m, "status", "--json")
        return [s["slot"] for s in json.loads(out)["disks"][0]["slots"] if s["opens"]]

    def test_dbx_written_after_prepare_firmware_keeps_the_disk_open(self):
        # what Raye Update does: prepare, then fwupd writes the new dbx
        m = self.machine(raye_installed=True)
        rc, out, err = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, 0, out + err)
        # dbx is not written yet: Ubuntu's kernel has nothing new to predict,
        # the suspension is what will open the next start (the Raye kernel
        # gets its own prediction as usual)
        cfgs = self.bound_cfgs(m)
        self.assertEqual(cfgs[0], {})
        self.assertEqual([c["pcr_digest"] for c in cfgs[1:]],
                         [base64.urlsafe_b64encode(fixture_pcr("mok")["sha256"]).decode().rstrip("=")])
        self.assertEqual(self.slots_state(m)["2"]["role"], "suspended")
        self.assertTrue(os.path.exists(os.path.join(m.state_dir, "suspended")))
        m.efivars = efivars("dbx")
        # the next start measures the new dbx: only the suspension opens it
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        self.assertEqual(self.opening_slots(m), [2])
        rc, out, err = self.run_tool(m, "resume")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("sealed to the PCR 7 of this start", out)
        self.assertNotIn(2, m.slots)
        self.assertEqual(m.unbinds, [2])
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "suspended")))
        new = [s for s, v in m.slots.items() if v["sealed"] == ("sha256", fixture_pcr("dbx")["sha256"])]
        self.assertEqual(len(new), 1)
        self.assertEqual(self.slots_state(m)[str(new[0])]["role"], "ubuntu-kernel")
        # the Raye kernel was predicted for the new dbx as well
        kernels = {r["kernel"] for r in self.slots_state(m).values() if r["role"] == "predicted"}
        self.assertEqual(kernels, {"raye"})
        # and the start after opens with a PCR 7 binding, no suspension left
        m.reboot("dbx", "ubuntu", "boot-3", log="dbx")
        self.assertEqual(self.opening_slots(m), new)
        self.assertTrue(all("pcr_ids" in v["cfg"] for v in m.slots.values()))

    def test_prepare_firmware_again_after_the_write_predicts_it(self):
        m = self.machine()
        self.run_tool(m, "prepare-firmware")
        m.efivars = efivars("dbx")
        rc, out, _ = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, 0)
        self.assertIn("already suspended", out)
        self.assertEqual(len(m.binds), 2)  # one suspension, one prediction
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        rc, out, _ = self.run_tool(m, "resume")
        self.assertEqual(rc, 0)
        self.assertNotIn("sealed to", out)  # the prediction already opens it
        self.assertEqual(len(m.binds), 2)
        self.assertEqual(m.unbinds, [2])
        self.assertTrue(all("pcr_ids" in v["cfg"] for v in m.slots.values()))

    def test_resume_asks_clevis_once_per_slot(self):
        # each answer costs the disk's KDF: at boot, ask every slot once
        m = self.machine(raye_installed=True)
        self.run_tool(m, "prepare-firmware")
        m.efivars = efivars("dbx")
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        m.calls.clear()
        self.run_tool(m, "resume")
        asked = [c[5] for c in m.calls if c[:2] == ["bash", "-c"]]
        self.assertEqual(sorted(asked), sorted(set(asked)))
        self.assertFalse([c for c in m.calls if c[:3] == ["clevis", "luks", "pass"]])

    def test_old_clevis_falls_back_to_luks_pass(self):
        m = self.machine()
        m.old_clevis = True
        rc, out, _ = self.run_tool(m, "status")
        self.assertIn("slot 1 opens it now", out)
        self.assertIn(["clevis", "luks", "pass", "-d", "/dev/vda3", "-s", "1"], m.calls)

    def test_resume_on_the_start_that_suspended_does_nothing(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        rc, out, _ = self.run_tool(m, "resume")
        self.assertEqual(rc, rt.EXIT_NOTHING)
        self.assertIn("suspended until the next start", out)
        self.assertIn(2, m.slots)
        self.assertEqual(m.unbinds, [])

    def test_resume_without_a_suspension(self):
        m = self.machine()
        rc, _, _ = self.run_tool(m, "resume")
        self.assertEqual(rc, rt.EXIT_NOTHING)
        self.assertEqual((m.binds, m.unbinds), ([], []))

    def test_suspend_twice_binds_once(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        rc, out, _ = self.run_tool(m, "suspend")
        self.assertEqual(rc, 0)
        self.assertEqual(len(m.binds), 1)

    def test_suspend_needs_a_binding_that_opens_the_disk(self):
        m = self.machine()
        m.slots[1]["sealed"] = ("sha256", bytes(32))
        rc, _, err = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertEqual(m.binds, [])
        self.assertIn("password stays needed", err)

    def test_suspend_that_clevis_refuses(self):
        m = self.machine()
        m.bind_ok = False
        rc, _, err = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertIn("could not suspend", err)
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "suspended")))

    def test_firmware_without_a_tpm_disk(self):
        m = self.machine()
        m.slots = {}
        rc, _, _ = self.run_tool(m, "prepare-firmware")
        self.assertEqual(rc, rt.EXIT_NOTHING)

    def test_resume_when_the_event_log_does_not_replay(self):
        # sealing to this start's PCR 7 does not need the log
        m = self.machine()
        self.run_tool(m, "suspend")
        m.reboot("dbx", "ubuntu", "boot-2")  # log still "stock": no replay
        rc, out, err = self.run_tool(m, "resume")
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn(2, m.slots)
        self.assertEqual(self.opening_slots(m), [3])

    def test_a_suspension_that_cannot_be_resumed_never_stays(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        m.bind_ok = False
        rc, _, err = self.run_tool(m, "resume")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertIn("trying again", err)
        self.assertIn(2, m.slots)
        self.run_tool(m, "resume")  # same start: counted once
        self.assertIn(2, m.slots)
        m.reboot("dbx", "ubuntu", "boot-3", log="dbx")
        rc, _, err = self.run_tool(m, "resume")
        self.assertEqual(rc, rt.EXIT_FAILED)
        self.assertIn("password is needed", err)
        self.assertEqual(sorted(m.slots), [1])  # only clevis' own slots are ever removed
        self.assertEqual(m.unbinds, [2])
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "suspended")))

    def test_a_lost_state_still_finds_the_suspension(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        os.unlink(os.path.join(m.state_dir, "bindings.json"))
        rc, out, _ = self.run_tool(m, "status")
        self.assertIn("slot 2 opens it now (suspended)", out)
        m.reboot("dbx", "ubuntu", "boot-2", log="dbx")
        self.run_tool(m, "record")
        self.assertEqual(self.slots_state(m)["2"]["role"], "suspended")
        rc, _, _ = self.run_tool(m, "resume")
        self.assertEqual(rc, 0)
        self.assertNotIn(2, m.slots)

    def test_record_and_prune_leave_the_suspension_to_resume(self):
        m = self.machine()
        self.run_tool(m, "suspend")
        for n in range(2, 7):
            m.reboot("stock", "ubuntu", "boot-%d" % n)
            self.run_tool(m, "prune")
        self.assertEqual(self.slots_state(m)["2"]["role"], "suspended")
        self.assertIn(2, m.slots)

    def test_bindings_made_by_hand_without_pcr_are_left_alone(self):
        m = self.machine()
        m.slots[2] = {"cfg": {"hash": "sha256", "key": "ecc"}, "sealed": None, "pass": b"by-hand"}
        self.run_tool(m, "record")
        st = self.state(m)
        st["disks"]["11111111-2222-3333-4444-555555555555"]["slots"]["2"]["role"] = "ubuntu-kernel"
        with open(os.path.join(m.state_dir, "bindings.json"), "w") as f:
            json.dump(st, f)
        m.reboot("stock", "ubuntu", "boot-2")
        self.run_tool(m, "resume")
        self.assertIn(2, m.slots)

    # -- record and prune
    def test_record_promotes_the_predicted_binding(self):
        m = self.machine(varsname="mok")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        m.reboot("mok", "raye", "boot-2", log="mok")
        rc, out, _ = self.run_tool(m, "record")
        self.assertEqual(rc, 0)
        s = self.slots_state(m)
        self.assertEqual(s["2"]["role"], "raye-kernel")
        self.assertEqual(s["2"]["last_opened"], "boot-2")
        self.assertEqual(s["1"]["role"], "ubuntu-kernel")
        self.assertEqual(s["1"]["missed_boots"], 1)
        # the Raye kernel's real authority event is kept for later
        self.assertTrue(os.path.exists(os.path.join(m.state_dir, "raye-authority.bin")))

    def test_record_counts_a_boot_once(self):
        m = self.machine(varsname="mok")
        self.run_tool(m, "record")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        m.reboot("stock", "ubuntu", "boot-2")
        for _ in range(3):
            self.run_tool(m, "record")
        self.assertEqual(self.slots_state(m)["2"]["missed_boots"], 1)

    def test_prune_keeps_both_kernels_bindings(self):
        m = self.machine(varsname="mok", raye_installed=True)
        self.run_tool(m, "bind-next", "--kernel", "raye")
        for n in range(2, 7):
            m.reboot("stock", "ubuntu", "boot-%d" % n)
            rc, _, _ = self.run_tool(m, "prune")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(m.slots), [1, 2])  # the raye binding is still predicted

    def test_prune_removes_a_binding_no_kernel_uses(self):
        m = self.machine(varsname="dbx")
        self.run_tool(m, "bind-next", "--kernel", "raye")  # raye kernel never installed
        self.assertEqual(sorted(m.slots), [1, 2])
        m.efivars = efivars("stock")
        for n, expect in ((2, [1, 2]), (3, [1, 2]), (4, [1])):
            m.reboot("stock", "ubuntu", "boot-%d" % n)
            rc, out, _ = self.run_tool(m, "prune")
            self.assertEqual((rc, sorted(m.slots)), (0, expect), out)
        self.assertIn("removed binding 2", out)
        self.assertNotIn("2", self.slots_state(m))

    def test_prune_never_removes_the_binding_that_opens_the_disk(self):
        m = self.machine()
        self.run_tool(m, "record")
        self.slots_state(m)
        st = self.state(m)
        st["disks"]["11111111-2222-3333-4444-555555555555"]["slots"]["1"]["missed_boots"] = 9
        st["disks"]["11111111-2222-3333-4444-555555555555"]["slots"]["1"]["pcr7"] = "00" * 32
        with open(os.path.join(m.state_dir, "bindings.json"), "w") as f:
            json.dump(st, f)
        m.reboot("stock", "ubuntu", "boot-2")
        self.run_tool(m, "prune")
        self.assertEqual(sorted(m.slots), [1])

    def test_prune_does_nothing_when_the_log_does_not_replay(self):
        m = self.machine(varsname="dbx")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        m.efivars = efivars("stock")
        for n in range(2, 7):
            m.reboot("stock", "ubuntu", "boot-%d" % n)
            self.run_tool(m, "record")
        m.pcr["sha256"] = m.pcr["sha1"] = b"\x01" * 32  # log no longer matches the TPM
        m.slots[1]["sealed"] = ("sha256", m.pcr["sha256"])
        rc, _, _ = self.run_tool(m, "prune")
        self.assertEqual(rc, rt.EXIT_REFUSED)
        self.assertEqual(sorted(m.slots), [1, 2])

    def test_prune_forgets_slots_removed_by_hand(self):
        m = self.machine(varsname="mok")
        self.run_tool(m, "bind-next", "--kernel", "raye")
        del m.slots[2]
        self.run_tool(m, "record")
        self.assertEqual(list(self.slots_state(m)), ["1"])

    # -- status
    def test_status_text(self):
        m = self.machine()
        rc, out, _ = self.run_tool(m, "status")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "/dev/vda3: slot 1 opens it now (unknown)")
        self.assertFalse(os.path.exists(os.path.join(m.state_dir, "bindings.json")))

    def test_status_without_tpm_disk(self):
        m = self.machine()
        m.disks = []
        rc, out, _ = self.run_tool(m, "status", "--json")
        self.assertEqual(rc, rt.EXIT_NOTHING)
        self.assertEqual(json.loads(out)["disks"], [])


class CrypttabTest(Folder):
    def test_devices_from_crypttab(self):
        path = os.path.join(self.tmp, "crypttab")
        with open(path, "w") as f:
            f.write("# comment\n"
                    "root UUID=00000000-0000-0000-0000-000000000000 none luks\n"
                    "data /dev/null none luks,discard\n"
                    "swap /dev/null none\n"
                    "odd relative/path none\n")
        calls = []

        class S(rt.System):
            def run(self, argv, data=None):
                calls.append(argv)
                return 0, b"abcd-uuid\n"

        devs = S(crypttab=path).luks_devices()
        self.assertEqual(devs, [("/dev/null", "abcd-uuid")])
        self.assertEqual(calls, [["cryptsetup", "luksUUID", "/dev/null"]])

    def test_missing_crypttab(self):
        self.assertEqual(rt.System(crypttab=os.path.join(self.tmp, "none")).luks_devices(), [])

    def test_clevis_list_parsing(self):
        class S(rt.System):
            def run(self, argv, data=None):
                return 0, (b"1: tpm2 '{\"hash\":\"sha256\",\"pcr_bank\":\"sha256\",\"pcr_ids\":\"7\"}'\n"
                           b"2: sss '{\"t\":1,\"pins\":{}}'\n"
                           b"3: tpm2 'not json'\n")

        slots = S().tpm_slots("/dev/x")
        self.assertEqual(sorted(slots), [1, 3])
        self.assertEqual(rt.Tool.slot_bank(slots[1]), "sha256")
        self.assertIsNone(rt.Tool.slot_bank(slots[3]))
        self.assertIsNone(rt.Tool.slot_bank({"pcr_bank": "sha256", "pcr_ids": "0,7"}))
        self.assertEqual(rt.Tool.slot_bank({"pcr_ids": [7]}), "sha1")


class StateTest(Folder):
    def test_damaged_state_starts_over(self):
        path = os.path.join(self.tmp, "bindings.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(rt.load_state(self.tmp), {"version": 1, "disks": {}})

    def test_learned_bytes_ignored_for_another_certificate(self):
        m = FakeMachine(self.tmp, varsname="mok")
        rt.save_learned(m.state_dir, rt.variable_data("MokListRT", rt.SHIM_LOCK_GUID, b"\0" * 16 + b"other"))
        tool = rt.Tool(m, io.StringIO(), io.StringIO())
        self.assertIsNone(tool.learned())
        rt.save_learned(m.state_dir, rt.learn_raye_authority(fixture_events("mok"), CERT))
        self.assertIsNotNone(tool.learned())


if __name__ == "__main__":
    unittest.main()
