# SPDX-License-Identifier: GPL-3.0-or-later
"""The parts of vm-images that need no root: the disk layout, the files
written into the image, the converter's command lines, the OVF descriptors.

vm-images itself does the root work (loop devices, mounts, chroot) and
calls these. Everything here returns text or lists and touches nothing.
"""
from __future__ import annotations

import hashlib
import html
import os
import pathlib
import re
import uuid

MIB = 1024 ** 2
GIB = 1024 ** 3
SECTOR = 512
ALIGN = MIB // SECTOR

# The same layout as Raye Setup's "erase the disk" (rayedisk_core.py):
# EFI, then /boot on ext4 (GRUB writes its recordfail flag there), then
# btrfs for the rest.
ESP_SIZE = 1 * GIB
BOOT_SIZE = 2 * GIB
ROOT_MINIMUM = 25 * GIB
ESP_TYPE = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX_TYPE = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
# backup GPT at the end of the disk: header and 128 entries
GPT_TAIL = 33

DEFAULT_SIZE = 64 * GIB
MEMORY_MIB = 4096
CPUS = 2
VIDEO_MIB = 128

# installer mount.conf: subvolume, mount point
SUBVOLUMES = [("@", "/"), ("@home", "/home"), ("@var_log", "/var/log"), ("@cache", "/var/cache")]
BTRFS_OPTIONS = "defaults,noatime,compress=zstd:1"
ESP_OPTIONS = "umask=0077"

# What the image keeps for the first start: Raye Setup asks for the account
# then. The packages job of a real install purges these from the new system
# (casper/filesystem.manifest-remove); casper goes at build time, the setup
# ones only once the first start is done.
PURGE_AT_BUILD = ["casper"]
PURGE_AFTER_FIRST_START = ["calamares-settings-raye", "calamares", "calamares-data",
                           "libcalamares3.3", "libcalamaresui3.3"]

# qemu-guest-agent and spice-vdagent are in the image already
GUEST_TOOLS = ["qemu-guest-agent", "spice-vdagent", "open-vm-tools", "open-vm-tools-desktop",
               "virtualbox-guest-utils", "virtualbox-guest-x11"]

FIRST_START = "/var/lib/raye-first-start"
SETUP_USER = "raye-setup"

FORMATS = ("qcow2", "virtualbox", "vmware")


class LayoutError(ValueError):
    pass


def align_up(sectors):
    return -(-sectors // ALIGN) * ALIGN


def align_down(sectors):
    return sectors // ALIGN * ALIGN


def parse_size(text):
    """64G, 80GiB, 70000M or plain bytes."""
    m = re.fullmatch(r"\s*(\d+)\s*([KMGT]?)(?:i?B)?\s*", str(text), re.I)
    if not m:
        raise LayoutError("not a size: %r" % text)
    unit = {"": 1, "K": 1024, "M": MIB, "G": GIB, "T": 1024 * GIB}[m.group(2).upper()]
    return int(m.group(1)) * unit


def partition_plan(disk_bytes):
    """The three partitions, in sectors, on 1 MiB boundaries."""
    if disk_bytes % SECTOR:
        raise LayoutError("the disk size is not a whole number of sectors")
    total = disk_bytes // SECTOR
    plan, at = [], ALIGN

    def take(role, sectors, ptype, name):
        nonlocal at
        plan.append({"role": role, "start": at, "sectors": sectors, "type": ptype, "name": name})
        at += sectors

    take("esp", align_up(ESP_SIZE // SECTOR), ESP_TYPE, "EFI")
    take("boot", align_up(BOOT_SIZE // SECTOR), LINUX_TYPE, "raye_boot")
    rest = align_down(total - GPT_TAIL - at)
    if rest * SECTOR < ROOT_MINIMUM:
        raise LayoutError("a disk of %d bytes leaves less than 25 GiB for Raye" % disk_bytes)
    take("root", rest, LINUX_TYPE, "raye")
    return plan


def sfdisk_script(plan):
    lines = ["label: gpt", "unit: sectors", "sector-size: %d" % SECTOR, ""]
    for part in plan:
        lines.append('start=%d, size=%d, type=%s, name="%s"'
                     % (part["start"], part["sectors"], part["type"], part["name"]))
    return "\n".join(lines) + "\n"


def mkfs_argv(role, node):
    return {
        "esp": ["mkfs.vfat", "-F", "32", "-n", "EFI", node],
        "boot": ["mkfs.ext4", "-F", "-q", "-L", "raye_boot", node],
        "root": ["mkfs.btrfs", "-f", "-q", "-L", "raye", node],
    }[role]


def mounts(root_node, boot_node, esp_node, target):
    """What to mount for the system, parents first: (source, where, type, options).

    The EFI partition comes last and is mounted after the system is
    unpacked: FAT has no owners, and unpacking onto it would fail on them.
    """
    out = []
    for subvol, point in SUBVOLUMES:
        out.append((root_node, target + point.rstrip("/") if point != "/" else target,
                    "btrfs", "subvol=/%s,%s" % (subvol, BTRFS_OPTIONS)))
    out.append((boot_node, target + "/boot", "ext4", "defaults"))
    out.append((esp_node, target + "/boot/efi", "vfat", ESP_OPTIONS))
    return out


def fstab(root_uuid, boot_uuid, esp_uuid):
    """/etc/fstab as Calamares' fstab job writes it for this layout."""
    for value in (root_uuid, boot_uuid, esp_uuid):
        if not re.fullmatch(r"[0-9A-Fa-f-]{4,36}", value or ""):
            raise LayoutError("not a filesystem UUID: %r" % value)
    rows = []
    for subvol, point in SUBVOLUMES:
        rows.append(("UUID=" + root_uuid, point, "btrfs", "subvol=/%s,%s" % (subvol, BTRFS_OPTIONS), 0))
    rows.append(("UUID=" + boot_uuid, "/boot", "ext4", "defaults", 2))
    rows.append(("UUID=" + esp_uuid, "/boot/efi", "vfat", ESP_OPTIONS, 2))
    rows.sort(key=lambda r: r[1])
    text = ["# /etc/fstab: static file system information.",
            "#",
            "# Use 'blkid' to print the universally unique identifier for a device; this may",
            "# be used with UUID= as a more robust way to name devices that works even if",
            "# disks are added and removed. See fstab(5).",
            "#",
            "# <file system>             <mount point>  <type>  <options>  <dump>  <pass>"]
    for source, point, kind, options, passno in rows:
        text.append("%-45s %-12s %-6s %s 0 %d" % (source, point, kind, options, passno))
    return "\n".join(text) + "\n"


def grub_install_argv():
    """Two runs. --no-nvram: the firmware the image starts on is not this
    one. EFI/ubuntu is where the signed GRUB finds grub.cfg; EFI/BOOT is
    what a new virtual machine starts from."""
    common = ["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi",
              "--bootloader-id=ubuntu", "--uefi-secure-boot", "--no-nvram", "--recheck"]
    return [common, common + ["--removable"]]


def convert_argv(fmt, raw, out):
    if fmt == "qcow2":
        return ["qemu-img", "convert", "-f", "raw", "-O", "qcow2", "-c",
                "-o", "cluster_size=65536", raw, out]
    if fmt == "vmdk":
        return ["qemu-img", "convert", "-f", "raw", "-O", "vmdk",
                "-o", "subformat=streamOptimized,adapter_type=lsilogic", raw, out]
    raise ValueError(fmt)


# ------------------------------------------------------------------ names

def names(iso_path, name=None):
    """Output file names from the ISO's: raye-1.0-beta-amd64.iso gives
    raye-1.0-beta-amd64.qcow2 and so on."""
    stem = name or pathlib.Path(iso_path).resolve().name
    if stem.endswith(".iso"):
        stem = stem[:-4]
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", stem):
        raise ValueError("unusable name: %r" % stem)
    return {
        "stem": stem,
        "raw": stem + ".raw",
        "qcow2": stem + ".qcow2",
        "vmdk": stem + "-disk1.vmdk",
        "virtualbox": stem + "-virtualbox.ova",
        "vmware": stem + "-vmware.ova",
        "ovf": stem + ".ovf",
        "mf": stem + ".mf",
        "sums": stem + "-vm.sha256",
    }


def title_of(disk_info):
    """"Raye Linux 1.0 Beta Brocken - amd64 (20261119)" -> name, version."""
    line = (disk_info or "").strip().splitlines()[0] if (disk_info or "").strip() else ""
    m = re.match(r"(Raye Linux)\s+(.+?)\s+-\s+\S+", line)
    if not m:
        return "Raye Linux", ""
    return m.group(1), m.group(2)


# ------------------------------------------------------------------ OVF

OVF_NS = "http://schemas.dmtf.org/ovf/envelope/1"
RASD_NS = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
VSSD_NS = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData"
VBOX_NS = "http://www.virtualbox.org/ovf/machine"
VMW_NS = "http://www.vmware.com/schema/ovf"
STREAM = "http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized"
# CIM operating system id: "Ubuntu 64-Bit"
OS_ID = 94


def _uuid(stem, what):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://rayelinux.com/vm/%s/%s" % (stem, what)))


def _item(fields, required=True):
    attr = "" if required else ' ovf:required="false"'
    body = "".join("        <rasd:%s>%s</rasd:%s>\n" % (k, html.escape(str(v), quote=False), k)
                   for k, v in sorted(fields.items()))
    return "      <Item%s>\n%s      </Item>\n" % (attr, body)


def _product(product, version):
    return ("    <ProductSection>\n"
            "      <Info>What this machine holds</Info>\n"
            "      <Product>%s</Product>\n"
            "      <Vendor>Raye Linux</Vendor>\n"
            "      <Version>%s</Version>\n"
            "      <ProductUrl>https://rayelinux.com</ProductUrl>\n"
            "      <VendorUrl>https://rayelinux.com</VendorUrl>\n"
            "    </ProductSection>\n" % (html.escape(product), html.escape(version)))


def ovf(flavour, stem, product, version, capacity, vmdk_name, vmdk_size,
        memory_mib=MEMORY_MIB, cpus=CPUS):
    """The OVF descriptor of the appliance, for VirtualBox or for VMware.

    Both get UEFI, the memory and processors above, one SATA disk, one
    e1000-type network card on NAT and no 3D: every guest kernel has the
    drivers for those, and 3D is what breaks most often in a new VM.
    """
    if flavour not in ("virtualbox", "vmware"):
        raise ValueError(flavour)
    vm_id = "raye"
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Envelope ovf:version="1.0" xml:lang="en-US" xmlns="%s" xmlns:ovf="%s"'
            ' xmlns:rasd="%s" xmlns:vssd="%s"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' % (OVF_NS, OVF_NS, RASD_NS, VSSD_NS))
    head += (' xmlns:vbox="%s">\n' % VBOX_NS) if flavour == "virtualbox" else (' xmlns:vmw="%s">\n' % VMW_NS)
    disk_uuid = _uuid(stem, "disk")
    disk_attr = (' vbox:uuid="%s"' % disk_uuid) if flavour == "virtualbox" else ""
    out = [head,
           "  <References>\n"
           '    <File ovf:id="file1" ovf:href="%s" ovf:size="%d"/>\n'
           "  </References>\n" % (html.escape(vmdk_name), vmdk_size),
           "  <DiskSection>\n"
           "    <Info>List of the virtual disks used in the package</Info>\n"
           '    <Disk ovf:capacity="%d" ovf:diskId="vmdisk1" ovf:fileRef="file1" ovf:format="%s"%s/>\n'
           "  </DiskSection>\n" % (capacity, STREAM, disk_attr),
           "  <NetworkSection>\n"
           "    <Info>Logical networks used in the package</Info>\n"
           '    <Network ovf:name="NAT">\n'
           "      <Description>Logical network used by this appliance.</Description>\n"
           "    </Network>\n"
           "  </NetworkSection>\n",
           '  <VirtualSystem ovf:id="%s">\n' % vm_id,
           "    <Info>A virtual machine</Info>\n",
           "    <Name>%s</Name>\n" % html.escape(product),
           _product(product, version)]
    if flavour == "virtualbox":
        out.append('    <OperatingSystemSection ovf:id="%d">\n'
                   "      <Info>The kind of installed guest operating system</Info>\n"
                   "      <Description>Ubuntu_64</Description>\n"
                   '      <vbox:OSType ovf:required="false">Ubuntu_64</vbox:OSType>\n'
                   "    </OperatingSystemSection>\n" % OS_ID)
        family, sata, nic, mem_units = "virtualbox-2.2", "AHCI", "E1000", "MegaBytes"
    else:
        out.append('    <OperatingSystemSection ovf:id="%d" vmw:osType="ubuntu64Guest">\n'
                   "      <Info>The kind of installed guest operating system</Info>\n"
                   "    </OperatingSystemSection>\n" % OS_ID)
        family, sata, nic, mem_units = "vmx-14", "vmware.sata.ahci", "E1000e", "byte * 2^20"
    out.append("    <VirtualHardwareSection>\n"
               "      <Info>Virtual hardware requirements for a virtual machine</Info>\n"
               "      <System>\n"
               "        <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>\n"
               "        <vssd:InstanceID>0</vssd:InstanceID>\n"
               "        <vssd:VirtualSystemIdentifier>%s</vssd:VirtualSystemIdentifier>\n"
               "        <vssd:VirtualSystemType>%s</vssd:VirtualSystemType>\n"
               "      </System>\n" % (vm_id, family))
    cpu = {"Caption": "%d virtual CPU" % cpus, "Description": "Number of virtual CPUs",
           "ElementName": "%d virtual CPU" % cpus, "InstanceID": 1, "ResourceType": 3,
           "VirtualQuantity": cpus}
    if flavour == "vmware":
        cpu["AllocationUnits"] = "hertz * 10^6"
    out.append(_item(cpu))
    out.append(_item({"AllocationUnits": mem_units, "Caption": "%d MB of memory" % memory_mib,
                      "Description": "Memory Size", "ElementName": "%d MB of memory" % memory_mib,
                      "InstanceID": 2, "ResourceType": 4, "VirtualQuantity": memory_mib}))
    out.append(_item({"Address": 0, "Caption": "sataController0", "Description": "SATA Controller",
                      "ElementName": "sataController0", "InstanceID": 3, "ResourceSubType": sata,
                      "ResourceType": 20}))
    out.append(_item({"AddressOnParent": 0, "Caption": "disk1", "Description": "Disk Image",
                      "ElementName": "disk1", "HostResource": "/disk/vmdisk1"
                      if flavour == "virtualbox" else "ovf:/disk/vmdisk1",
                      "InstanceID": 4, "Parent": 3, "ResourceType": 17}))
    out.append(_item({"AutomaticAllocation": "true", "Caption": "Ethernet adapter on 'NAT'",
                      "Connection": "NAT", "ElementName": "Ethernet adapter on 'NAT'",
                      "InstanceID": 5, "ResourceSubType": nic, "ResourceType": 10}))
    if flavour == "vmware":
        out.append(_item({"Address": 0, "Caption": "usb", "ElementName": "usb", "InstanceID": 6,
                          "ResourceSubType": "vmware.usb.xhci", "ResourceType": 23}, required=False))
        video = _item({"Caption": "video", "ElementName": "video", "InstanceID": 7,
                       "ResourceType": 24}, required=False)
        video = video.replace("      </Item>\n",
                              '        <vmw:Config ovf:required="false" vmw:key="enable3DSupport" vmw:value="false"/>\n'
                              '        <vmw:Config ovf:required="false" vmw:key="videoRamSizeInKB" vmw:value="%d"/>\n'
                              "      </Item>\n" % (VIDEO_MIB * 1024))
        out.append(video)
        for key, value in (("firmware", "efi"), ("uefi.secureBoot.enabled", "false"),
                           ("tools.syncTimeWithHost", "true")):
            out.append('      <vmw:Config ovf:required="false" vmw:key="%s" vmw:value="%s"/>\n' % (key, value))
    out.append("    </VirtualHardwareSection>\n")
    if flavour == "virtualbox":
        out.append(_vbox_machine(stem, product, disk_uuid, memory_mib, cpus))
    out.append("  </VirtualSystem>\n</Envelope>\n")
    return "".join(out)


def _vbox_machine(stem, product, disk_uuid, memory_mib, cpus):
    # VirtualBox reads the firmware, the graphics and the pointer from its own
    # section only; the OVF items above carry the rest for any other reader.
    mac = "080027" + hashlib.sha256(stem.encode()).hexdigest()[:6].upper()
    return ('    <vbox:Machine ovf:required="false" version="1.16-linux" uuid="{%s}" name="%s"'
            ' OSType="Ubuntu_64" snapshotFolder="Snapshots">\n'
            "      <ovf:Info>Complete VirtualBox machine configuration in VirtualBox format</ovf:Info>\n"
            "      <Hardware>\n"
            '        <CPU count="%d">\n'
            '          <PAE enabled="true"/>\n'
            '          <LongMode enabled="true"/>\n'
            '          <HardwareVirtExLargePages enabled="true"/>\n'
            "        </CPU>\n"
            '        <Memory RAMSize="%d"/>\n'
            '        <Firmware type="EFI"/>\n'
            '        <HID Pointing="USBTablet" Keyboard="PS2Keyboard"/>\n'
            '        <Display controller="VMSVGA" VRAMSize="%d" accelerate3D="false"/>\n'
            '        <RemoteDisplay enabled="false"/>\n'
            "        <USB>\n"
            "          <Controllers>\n"
            '            <Controller name="xHCI" type="XHCI"/>\n'
            "          </Controllers>\n"
            "        </USB>\n"
            "        <Network>\n"
            '          <Adapter slot="0" enabled="true" MACAddress="%s" type="82540EM">\n'
            "            <NAT/>\n"
            "          </Adapter>\n"
            "        </Network>\n"
            '        <AudioAdapter controller="HDA" driver="Pulse" enabled="true" enabledIn="false" enabledOut="true"/>\n'
            '        <RTC localOrUTC="UTC"/>\n'
            '        <Clipboard mode="Bidirectional"/>\n'
            "      </Hardware>\n"
            "      <StorageControllers>\n"
            '        <StorageController name="SATA" type="AHCI" PortCount="1" useHostIOCache="false" Bootable="true" IDE0MasterEmulationPort="0" IDE0SlaveEmulationPort="1" IDE1MasterEmulationPort="2" IDE1SlaveEmulationPort="3">\n'
            '          <AttachedDevice type="HardDisk" hotpluggable="false" port="0" device="0">\n'
            '            <Image uuid="{%s}"/>\n'
            "          </AttachedDevice>\n"
            "        </StorageController>\n"
            "      </StorageControllers>\n"
            "    </vbox:Machine>\n"
            % (_uuid(stem, "machine"), html.escape(product), cpus, memory_mib, VIDEO_MIB, mac, disk_uuid))


def manifest(digests):
    """{name: sha256 hex} -> the .mf of the OVA, in the given order."""
    return "".join("SHA256(%s)= %s\n" % (n, d) for n, d in digests.items())


def ova_members(n):
    """The order inside the tar: the descriptor first, as OVF requires."""
    return [n["ovf"], n["mf"], n["vmdk"]]


# ------------------------------------------------------------------ first start

# Raye Setup's pages know each step by its position in settings.conf (the
# steps of strings.js). The first start shows fewer pages, so its copy of
# the branding gets its own list, and words that speak of a USB stick or of
# installing get first-start ones. Each edit has to match exactly once:
# when the branding changes under it, the build stops instead of shipping
# pages that point at the wrong step.
FIRST_START_STEPS = ["language", "region", "keyboard", "network", "device",
                     "account", "user", "privacy", "installing", "done"]

BRANDING_EDITS = [
    ('var steps = ["language", "region", "keyboard", "network", "disk", "device",\n'
     '             "account", "user", "privacy", "ready", "installing", "done"]',
     'var steps = ["language", "region", "keyboard", "network", "device",\n'
     '             "account", "user", "privacy", "installing", "done"]'),
    ('    { key: "stageDisk", steps: ["disk"] },\n', ''),
    ('{ key: "stageInstall", steps: ["ready", "installing", "done"] }',
     '{ key: "stageInstall", steps: ["installing", "done"] }'),
    ('setupName: "Installation de Raye",', 'setupName: "Configuration de Raye",'),
    ('stageInstall: "Install",', 'stageInstall: "Finish",'),
    ('stageInstall: "Installation",', 'stageInstall: "Finalisation",'),
    ('quitText: "Raye isn\'t installed yet. Your PC will restart, and nothing on it has been changed.",',
     'quitText: "Setup isn\'t finished yet. Your PC will restart, and Setup starts again.",'),
    ('quitText: "Raye n\'est pas encore installé. Votre PC va redémarrer, et rien n\'y a été modifié.",',
     'quitText: "La configuration n\'est pas terminée. Votre PC va redémarrer, puis elle reprendra.",'),
    ('doneTitle: "Raye is installed",', 'doneTitle: "You\'re all set",'),
    ('doneText: "Your PC restarts to finish. Take out the USB stick when the screen goes dark.",',
     'doneText: "Your PC restarts once more, then you can sign in.",'),
    ('doneTitle: "Raye est installé",', 'doneTitle: "Tout est prêt",'),
    ('doneText: "Votre PC redémarre pour terminer. Retirez la clé USB quand l\'écran devient noir.",',
     'doneText: "Votre PC redémarre une dernière fois, puis vous pourrez vous connecter.",'),
]


class BrandingChanged(RuntimeError):
    pass


def apply_edits(text, edits, what="strings.js"):
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            raise BrandingChanged("%s: expected one %r, found %d" % (what, old[:60], count))
        text = text.replace(old, new)
    return text


def first_start_branding_desc(text):
    out, count = re.subn(r"(?m)^componentName:\s*raye\s*$", "componentName: raye-first-start", text)
    if count != 1:
        raise BrandingChanged("branding.desc: no componentName: raye")
    return out


def first_start_show(settings_text):
    """The page modules of a settings.conf show list, in order."""
    show, inside = [], False
    for line in settings_text.splitlines():
        if re.match(r"^- show:\s*$", line):
            inside = not show
            continue
        if inside:
            m = re.match(r"^\s+-\s+(\S+)\s*$", line)
            if m:
                show.append(m.group(1))
            elif line.strip() and not line.lstrip().startswith("#"):
                inside = False
    return show


# ------------------------------------------------------------------ checks

GUEST_FILES = ["usr/sbin/qemu-ga", "usr/bin/spice-vdagent", "usr/bin/vmtoolsd", "usr/sbin/VBoxService"]


def check_tree(root, uuids=None):
    """What is wrong with an image's system, mounted at root: [] when nothing.

    uuids, when given: {"root":..., "boot":..., "esp":...} as blkid read them.
    """
    root = pathlib.Path(root)
    problems = []

    def need(rel, why):
        # links in the image point at absolute paths of the image
        if not os.path.lexists(root / rel):
            problems.append("%s: missing (%s)" % (rel, why))

    def text(rel):
        try:
            return (root / rel).read_text(errors="replace")
        except OSError:
            return ""

    need("boot/grub/grub.cfg", "boot menu")
    need("boot/efi/EFI/BOOT/BOOTX64.EFI", "what a new virtual machine starts")
    need("boot/efi/EFI/ubuntu/grubx64.efi", "signed GRUB")
    need("boot/efi/EFI/ubuntu/grub.cfg", "where GRUB finds /boot")
    if (root / "boot/efi/EFI/BOOT/fbx64.efi").exists():
        problems.append("boot/efi/EFI/BOOT/fbx64.efi: would add a boot entry under another name")
    if not list((root / "boot").glob("vmlinuz-*")):
        problems.append("boot/vmlinuz-*: no kernel")
    if not list((root / "boot").glob("initrd.img-*")):
        problems.append("boot/initrd.img-*: no initramfs")
    grub = text("boot/grub/grub.cfg")
    if "--class osprober" in grub:
        problems.append("boot/grub/grub.cfg: lists systems of the machine that built it")
    if grub and "rootflags=subvol=@" not in grub:
        problems.append("boot/grub/grub.cfg: does not start the @ subvolume")
    fs = text("etc/fstab")
    for key, value in (uuids or {}).items():
        if value and ("UUID=" + value) not in fs:
            problems.append("etc/fstab: no UUID=%s (%s)" % (value, key))
        if key == "root" and value and grub and value not in grub:
            problems.append("boot/grub/grub.cfg: does not name the root filesystem")
    if text("etc/machine-id").strip():
        problems.append("etc/machine-id: not empty, every copy would share it")
    if (root / "usr/sbin/policy-rc.d").exists():
        problems.append("usr/sbin/policy-rc.d: left from the build")
    if (root / "usr/share/initramfs-tools/scripts/casper").exists():
        problems.append("casper: still installed")
    for rel in GUEST_FILES:
        need(rel, "guest tools")
    accounts = []
    for line in text("etc/passwd").splitlines():
        f = line.split(":")
        if len(f) > 3 and f[2].isdigit() and 1000 <= int(f[2]) < 65534:
            accounts.append(f[0])
    if accounts:
        problems.append("etc/passwd: accounts already made: %s" % ", ".join(accounts))
    shadow = {l.split(":")[0]: l.split(":")[1] for l in text("etc/shadow").splitlines() if l.count(":") > 1}
    for name in ("root", SETUP_USER):
        if name in shadow and not shadow[name].startswith(("!", "*")):
            problems.append("etc/shadow: %s has a password" % name)
    if SETUP_USER not in shadow:
        problems.append("etc/shadow: no %s account for the first start" % SETUP_USER)
    fsd = FIRST_START.lstrip("/")
    for rel, why in ((fsd + "/xdg/calamares/settings.conf", "first-start Setup"),
                     (fsd + "/xdg/calamares/branding/raye-first-start/branding.desc", "its pages"),
                     (fsd + "/modules/rayefirststart/main.py", "its first job"),
                     (fsd + "/raye-first-start", "the cleanup"),
                     ("etc/sddm.conf.d/zz-raye-first-start.conf", "starts Setup"),
                     ("etc/sudoers.d/raye-first-start", "lets Setup run"),
                     ("usr/local/bin/calamares", "points Setup at its settings"),
                     ("etc/systemd/system/multi-user.target.wants/raye-first-start.service", "the cleanup"),
                     ("usr/share/wayland-sessions/raye-setup.desktop", "the setup session")):
        need(rel, why)
    strings = text(fsd + "/xdg/calamares/branding/raye-first-start/strings.js")
    if strings and '"disk"' in strings.split("var steps", 1)[-1].split("]", 1)[0]:
        problems.append("first-start branding: still has the disk step")
    return problems
