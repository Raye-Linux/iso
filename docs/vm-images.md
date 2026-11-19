# Ready-made virtual machines

Raye already installed, for people who want to try it in a virtual machine
without going through the installer. Made from the ISO by `tools/vm-images`.

| File | For |
|---|---|
| `raye-<release>-amd64.qcow2` | QEMU, virt-manager, Proxmox, GNOME Boxes |
| `raye-<release>-amd64-virtualbox.ova` | VirtualBox: File > Import Appliance |
| `raye-<release>-amd64-vmware.ova` | VMware Workstation, Fusion, ESXi |
| `raye-<release>-amd64-vm.sha256` | their checksums |

Each machine: UEFI with Secure Boot off, 4 GB of memory, 2 processors, a
64 GiB disk that only takes what is written on it, an e1000 network card on
NAT, 3D off. The disk inside is the same in all
three.

## What is on the disk

The layout Raye Setup makes when it erases a disk: GPT, EFI (1 GiB, FAT),
`/boot` (2 GiB, ext4), btrfs for the rest with the subvolumes `@`, `@home`,
`@var_log` and `@cache`. The system is the squashfs of the ISO, minus casper,
plus the guest tools (qemu-guest-agent, spice-vdagent, open-vm-tools,
virtualbox-guest-utils and -x11). GRUB is installed for UEFI in `EFI/ubuntu`
and in the removable path `EFI/BOOT`, without touching any firmware entry.
`/etc/machine-id` is empty, so every copy gets its own.

## The first start

There is no account and no password in the image. The machine starts Raye
Setup with the questions of a new PC: language, region, keyboard, network,
PC name, account, privacy. Then it restarts once, to the sign-in screen.

How: SDDM signs in `raye-setup`, a system account with a locked password,
into the same setup session as the USB stick. `/usr/local/bin/calamares`
starts Calamares with the settings in `/var/lib/raye-first-start/xdg`
(`dont-chroot`, no disk page). Its last job runs `raye-first-start done`;
at the next start `raye-first-start.service`, before the sign-in screen,
deletes `raye-setup`, removes Calamares and itself. The pages are Raye
Setup's own, copied from the image with a few words changed
(`BRANDING_EDITS` in `tools/raye_vmimage.py`); if Setup's pages change under
those words, the build stops and says which.

The files the image gets for this are in `tools/first-start/`.

## Building

As root, on a machine with qemu-img, squashfs-tools, btrfs-progs,
dosfstools and e2fsprogs (the agents' chroot has them all):

    tools/vm-images --iso /var/tmp/raye/isos/latest.iso --name raye-1.0-beta-amd64
    tools/vm-images check /var/tmp/raye/vm-images/raye-1.0-beta-amd64.qcow2
    tools/vm-images --dry-run           # what it would run

About 8 minutes and 10 GB of disk for the three files, about 20 GB while it
works. It only writes to a file under `--work` and to loop devices it
attaches to that file; everything is detached at the end, also on failure.
`check` opens an image read-only, compares it with its raw copy and looks
for the things that make a broken machine (no boot loader, an account
already made, a shared machine id, entries of the build machine in the boot
menu...).

## Publishing

Next to the ISO, in the same release folder:

    https://dl.rayelinux.com/iso/<release>/raye-<release>-amd64.qcow2
    https://dl.rayelinux.com/iso/<release>/raye-<release>-amd64-virtualbox.ova
    https://dl.rayelinux.com/iso/<release>/raye-<release>-amd64-vmware.ova

and their lines added to that release's SHA256SUMS before it is signed.
Each file is about 3.1 GB: over GitHub's 2 GiB limit per release file, so
on GitHub they would have to be cut in parts like the ISO.
