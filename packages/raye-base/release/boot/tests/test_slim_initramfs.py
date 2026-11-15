# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-slim-initramfs: what leaves the initramfs and what must stay."""
import os
import pathlib
import subprocess

HOOK = pathlib.Path(__file__).resolve().parent.parent / "raye-slim-initramfs"
VER = "7.0.0-1-generic"

# module: (firmware it asks for, modules it needs)
MODULES = {
    "kernel/drivers/net/ethernet/intel/e1000e/e1000e.ko.zst": ([], []),
    "kernel/drivers/net/ethernet/qlogic/qed/qed.ko.zst": (["qed/qed_init_values.bin"], []),
    "kernel/drivers/net/ethernet/broadcom/bnx2x/bnx2x.ko.zst": (["bnx2x/bnx2x-e2.fw", "shared.fw"], []),
    "kernel/drivers/infiniband/core/ib_core.ko.zst": ([], []),
    "kernel/drivers/scsi/qla2xxx/qla2xxx.ko.zst": (["ql2500_fw.bin"], ["kernel/drivers/scsi/scsi_transport_fc.ko.zst"]),
    "kernel/drivers/scsi/scsi_transport_fc.ko.zst": ([], []),
    "kernel/drivers/scsi/hv_storvsc.ko.zst": ([], ["kernel/drivers/scsi/scsi_transport_fc.ko.zst"]),
    "kernel/drivers/scsi/mpt3sas/mpt3sas.ko.zst": ([], []),
    "kernel/drivers/nvme/host/nvme-rdma.ko.zst": ([], ["kernel/drivers/infiniband/core/ib_core.ko.zst"]),
    "kernel/drivers/nvme/host/nvme-core.ko.zst": ([], []),
    "kernel/drivers/ata/ahci.ko.zst": ([], []),
    "kernel/drivers/hid/usbhid/usbhid.ko.zst": ([], []),
    "kernel/drivers/hid/hid-logitech-dj.ko.zst": ([], []),
    "kernel/drivers/gpu/drm/i915/i915.ko.zst": (["i915/tgl_dmc.bin", "shared.fw"], []),
    "kernel/drivers/thunderbolt/thunderbolt.ko.zst": ([], []),
    "kernel/fs/btrfs/btrfs.ko.zst": ([], []),
    "kernel/fs/nfs/nfs.ko.zst": ([], ["kernel/net/sunrpc/sunrpc.ko.zst"]),
    "kernel/net/sunrpc/sunrpc.ko.zst": ([], []),
    "kernel/drivers/misc/needs-a-nic.ko.zst": ([], ["kernel/drivers/net/ethernet/intel/e1000e/e1000e.ko.zst"]),
}
GONE = {
    "kernel/drivers/net/ethernet/intel/e1000e/e1000e.ko.zst",
    "kernel/drivers/net/ethernet/qlogic/qed/qed.ko.zst",
    "kernel/drivers/net/ethernet/broadcom/bnx2x/bnx2x.ko.zst",
    "kernel/drivers/infiniband/core/ib_core.ko.zst",
    "kernel/drivers/scsi/qla2xxx/qla2xxx.ko.zst",
    "kernel/drivers/nvme/host/nvme-rdma.ko.zst",
    "kernel/fs/nfs/nfs.ko.zst",
    "kernel/net/sunrpc/sunrpc.ko.zst",
    "kernel/drivers/misc/needs-a-nic.ko.zst",
}
FIRMWARE = ["qed/qed_init_values.bin.zst", "bnx2x/bnx2x-e2.fw.zst", "shared.fw.zst",
            "ql2500_fw.bin.zst", "i915/tgl_dmc.bin.zst", "rtl_builtin.fw.zst"]


def setup(tmp_path):
    root = tmp_path / "host"
    dest = tmp_path / "initramfs"
    mdir = f"/lib/modules/{VER}"
    fake_fw = []
    dep = []
    for m, (fw, deps) in MODULES.items():
        p = dest / mdir.lstrip("/") / m
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * 64)
        fake_fw += [f"{dest}{mdir}/{m}\t{f}" for f in fw]
        dep.append(f"{m}: {' '.join(deps)}".rstrip())
    hostmods = root / mdir.lstrip("/")
    hostmods.mkdir(parents=True)
    (hostmods / "modules.dep").write_text("\n".join(dep) + "\n")
    (hostmods / "modules.builtin.modinfo").write_bytes(b"r8169.firmware=rtl_builtin.fw\0r8169.license=GPL\0")
    for f in FIRMWARE:
        p = dest / "lib/firmware" / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fw")
    table = tmp_path / "fw-table"
    table.write_text("\n".join(fake_fw) + "\n")
    modinfo = tmp_path / "modinfo"
    modinfo.write_text(f'#!/bin/sh\nshift 2\nfor m in "$@"; do awk -F"\\t" -v m="$m" \'$1 == m {{ print $2 }}\' "{table}"; done\n')
    modinfo.chmod(0o755)
    env = dict(os.environ, DESTDIR=str(dest), MODULESDIR=mdir, version=VER, MODULES="most",
               RAYE_SLIM_ROOT=str(root), RAYE_SLIM_MODINFO=str(modinfo))
    return root, dest, mdir, env


def run(env):
    r = subprocess.run(["sh", str(HOOK)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def left(dest, mdir):
    base = dest / mdir.lstrip("/")
    return {str(p.relative_to(base)) for p in base.rglob("*.ko*")}


def firmware(dest):
    base = dest / "lib/firmware"
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


def test_network_and_san_drivers_go(tmp_path):
    _, dest, mdir, env = setup(tmp_path)
    run(env)
    assert left(dest, mdir) == set(MODULES) - GONE


def test_firmware_of_the_modules_that_go(tmp_path):
    _, dest, mdir, env = setup(tmp_path)
    run(env)
    # shared.fw is also asked for by i915, rtl_builtin by a built-in driver
    assert firmware(dest) == {"shared.fw.zst", "i915/tgl_dmc.bin.zst", "rtl_builtin.fw.zst"}
    assert not (dest / "lib/firmware/qed").exists()


def test_storage_and_input_stay(tmp_path):
    _, dest, mdir, env = setup(tmp_path)
    run(env)
    kept = left(dest, mdir)
    for m in ("kernel/drivers/scsi/scsi_transport_fc.ko.zst", "kernel/drivers/scsi/hv_storvsc.ko.zst",
              "kernel/drivers/scsi/mpt3sas/mpt3sas.ko.zst", "kernel/drivers/nvme/host/nvme-core.ko.zst",
              "kernel/drivers/ata/ahci.ko.zst", "kernel/drivers/hid/hid-logitech-dj.ko.zst",
              "kernel/drivers/thunderbolt/thunderbolt.ko.zst", "kernel/fs/btrfs/btrfs.ko.zst"):
        assert m in kept


def test_nothing_goes_with_modules_dep(tmp_path):
    _, dest, mdir, env = setup(tmp_path)
    run(dict(env, MODULES="dep"))
    assert left(dest, mdir) == set(MODULES)
    assert len(firmware(dest)) == len(FIRMWARE)


def test_nothing_goes_on_the_live_system(tmp_path):
    root, dest, mdir, env = setup(tmp_path)
    casper = root / "usr/share/initramfs-tools/scripts/casper"
    casper.parent.mkdir(parents=True)
    casper.write_text("")
    run(env)
    assert left(dest, mdir) == set(MODULES)


def test_network_kept_when_asked(tmp_path):
    root, dest, mdir, env = setup(tmp_path)
    conf = root / "etc/initramfs-tools/conf.d/network"
    conf.parent.mkdir(parents=True)
    conf.write_text("RAYE_INITRAMFS_NETWORK=yes\n")
    run(env)
    assert left(dest, mdir) == set(MODULES)


def test_prereqs():
    r = subprocess.run(["sh", str(HOOK), "prereqs"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ""
