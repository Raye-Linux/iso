# Boot analysis

Where the boot time of the 2026-10-30 image goes, what holds it back,
and what to cut. The numbers are in [baseline.md](baseline.md); this
file explains them and hands the work on: the cuts to KP-4, the
experiments to KP-13.

**Virtual machine numbers.** Virtual disk, virtual timer, no GPU, a
shared host: only the order of things and the differences between two
boots of the same VM mean something. A step that costs 2 s here can cost
0.2 s on a real NVMe PC. Every cut below is to be confirmed on real
hardware (KP-4 for the cuts, KP-13 for the experiments, KP-15 for the
final numbers).

## In short

1. **The network holds the boot.** `raye-kernel-finish.service` and
   `raye-drivers.service` both have `Wants=` and
   `After=network-online.target` and are enabled in
   `multi-user.target`. Their conditions fail on every normal boot, but a
   condition is only checked when the unit runs: the `Wants=` has already
   pulled `network-online.target` (and `NetworkManager-wait-online`) in,
   and the `After=` makes `multi-user.target` wait for it. **Confirmed**
   (see "The network-online pull").
   With a quick DHCP answer it costs little (the 0.46 s of
   `NetworkManager-wait-online`, at most, on `multi-user.target`; within
   the noise of this VM). Without one (Wi-Fi out
   of range, a cable with no router behind it) `multi-user.target` and
   `graphical.target` wait the full 60 s of `nm-online`, the boot ends
   with a failed unit, and `power-profiles-daemon` (the power mode in
   quick settings) starts only after that minute.
2. **The login screen is shown 6 s after SDDM starts** in this VM (KWin,
   then the greeter, all drawn in software). `graphical.target` is
   reached long before the login screen is on screen: measure the login
   screen itself.
3. **Before the login screen**, in order: kernel 2 s, initramfs 4.5 s
   (of which 1.5 s with nothing in the kernel log before the btrfs
   module loads, and 0.8–1.0 s loading btrfs), systemd's own start 2.1 s,
   mounts to `local-fs.target` 2.2 s, then `systemd-binfmt` (0.5–0.8 s,
   for one Python rule) holds `sysinit.target`, then D-Bus and
   NetworkManager (0.9 s) before SDDM may start.
4. **The initramfs is 96 MB.** 15 MB of it is Intel microcode, 17 MB
   firmware mostly for server network cards, 34 MB kernel modules (14 MB
   of them network drivers), and 14 MB the udev hardware database. The
   compressed part is only 30 MB.
5. Services started on every boot that a desktop only needs on demand:
   `gpu-manager` (0.7 s, ordered before the login screen), `snapperd`,
   `cups.service` (it is in the chain to `multi-user.target`),
   `e2scrub_reap`, `snapper-boot.timer` (a snapshot at every start), the
   parallel port modules `lp`/`ppdev`, `motd-news.timer`.

## How it was measured

The test VM `raye-test` was busy with other work, so these boots ran on
a throwaway virtual disk built from the same image. It is what the
installer leaves on a disk, done by hand:

- the image's `filesystem.squashfs` unpacked; the live-only packages
  removed as the installer does (`calamares*`, `casper`); a machine id,
  one user (`raye`, no automatic login), a host name; the driver step
  marked done ("nothing to install", as in a VM without NVIDIA); the
  initramfs rebuilt;
- a GPT disk: 1 GiB EFI (FAT32) and btrfs with the installer's
  subvolumes `@`, `@home`, `@var_log`, `@cache`, mounted
  `noatime,compress=zstd:1`, files written compressed (zstd 1) like the
  installer's copy;
- no disk encryption, no swap file (zram is there), GRUB not installed:
  the firmware (OVMF, UEFI) starts the kernel directly with the command
  line the installed GRUB gives
  (`root=UUID=… ro rootflags=subvol=@ quiet splash panic=30`), so there
  is no firmware or boot menu time in these numbers.

The VM: QEMU with KVM, 4 vCPUs (host CPU model), 4 GiB, virtio disk with
`cache=none` (no host page cache), virtio GPU without 3D, user-mode
network with DHCP. The host was shared with other builds (load 34–71 on
16 cores), so QEMU ran at `nice -10`; the load is kept with each run.

One boot first (not counted: it rebuilds the linker cache and sets up
snapshots), then each measured boot starts from a fresh copy-on-write
copy of that disk, so every boot is a cold boot from the same state.

A unit on the test disk only (never in the image) waits for the boot to
finish, saves `systemd-analyze`, `blame`, `critical-chain`, `plot`, the
unit and timer lists, the journal and `dmesg`, runs
`raye-bench --suites boot,memory,disk` (KP-1), and powers off:

```
[Unit]
DefaultDependencies=no       # graphical.target must not wait for it
After=graphical.target
[Service]
Type=exec                    # a oneshot here keeps the boot "starting" for ever
ExecStart=/usr/local/sbin/zz-measure   # systemctl is-system-running --wait, then the tools
```

"Login screen shown" comes from the journal: the line where the greeter
puts its window on screen (`sddm-greeter-qt6: Adding view for …`).

Scenarios, each from the same disk state:

| Name | What changes | Boots |
|---|---|---|
| base | nothing | 5 |
| initcall | `initcall_debug log_buf_len=16M` | 1 |
| nodhcp | network link up, nobody answers DHCP | 2 |
| wnet | the two network-online pulls removed (`systemd.mask=` of the two Raye units, which are skipped on these boots anyway) | 3 |
| wnodhcp | wnet without a DHCP answer | 2 |
| wtrim | wnet plus the cut candidates masked: `systemd-binfmt`, the binfmt_misc automount, `gpu-manager`, `snapperd`, `snapper-boot.timer`, `e2scrub_reap`, `cups.service` | 3 |
| rbase | nothing: the control for wtrim, taken right after it on the same, quieter host | 3 |

`systemd.mask=` on the kernel command line is only a quick way to see
what a unit costs; the real cuts (KP-4) disable or reorder, they do not
mask.

## Where the time goes

The median run (base-2), seconds since the kernel started:

| When | What | Took |
|---|---|---|
| 0.00 | kernel starts | |
| 1.27–1.75 | initramfs unpacked (94 MiB) | 0.5 |
| 1.93 | `/init` of the initramfs starts | kernel 1.93 |
| 1.93–3.00 | udev, drivers found (virtio, AHCI, GPU) | 1.1 |
| 3.00–4.45 | nothing in the kernel log: initramfs scripts (plymouth, `local-top`: clevis, cryptroot) | 1.5 |
| 4.45–5.62 | `modprobe btrfs`: raid6 benchmark, then loading btrfs itself (1.0) | 1.2 |
| 5.62–6.17 | root file system mounted | 0.55 |
| 6.17–6.53 | initramfs ends, switch to the disk, systemd starts | 0.35 |
| 6.53 | **userspace starts** (systemd's own clock; kernel + initramfs = 6.53) | |
| +0.0–2.1 | systemd: security setup, generators, loading units | 2.1 |
| +2.1–4.3 | journal, udev coldplug, root device seen at +3.7, `/home` `/var/log` `/var/cache` `/boot/efi` mounted (FAT check 0.3) | 2.2 |
| +4.3–5.15 | binfmt_misc mounted, `systemd-binfmt` (one rule, Python) → `sysinit.target` | 0.85 |
| +5.15–6.32 | D-Bus, NetworkManager started → `network.target` | 1.2 |
| +6.32–6.57 | `systemd-user-sessions`, `plymouth-quit` → **SDDM starts** | 0.25 |
| +6.97 | greeter session starts | |
| +8.76 | KWin (the login screen's compositor) ready | 1.8 |
| +10.59 | greeter loaded its theme | 1.8 |
| +13.0 | **login screen on screen** (the greeter's window is up) | 2.4 |
| +6.8 | `multi-user.target` (after NetworkManager-wait-online, 0.46 s) | |
| +7.18 | `graphical.target` | |

The kernel log and the journal give two clocks: the table uses the
kernel's for the first part and systemd's ("userspace +") after it.

`systemd-analyze critical-chain graphical.target` (base-2):

```
graphical.target @7.179s
└─power-profiles-daemon.service @6.805s +373ms
  └─multi-user.target @6.799s
    └─cups.service @6.336s +183ms
      └─network.target @6.317s
        └─NetworkManager.service @5.428s +887ms
          └─dbus.service @5.207s +193ms
            └─basic.target @5.170s
              └─sockets.target @5.169s
                └─uuidd.socket @5.169s +49us
                  └─sysinit.target @5.146s
                    └─systemd-binfmt.service @4.371s +774ms
                      └─proc-sys-fs-binfmt_misc.mount @4.421s +716ms
                        └─systemd-journald.socket @1.769s +73us
```

and for the login screen (`display-manager.service`):

```
sddm.service +54ms
└─plymouth-quit.service @6.412s +97ms
  └─systemd-user-sessions.service @6.345s +53ms
    └─network.target @6.317s
      └─NetworkManager.service @5.428s +887ms
        └─dbus.service @5.207s +193ms
          └─basic.target @5.170s … (same as above)
```

The plot of this boot is `boot-vm.svg` next to this file.

### The login screen comes after graphical.target

`graphical.target` is reached when SDDM has been started, not when
anything is on screen. In this VM the login screen appears 5.9 s after
`graphical.target` (median; 6.3 s after SDDM starts): KWin starts
(1.8 s), the greeter loads its theme (1.8 s), then puts its window up
(2.4 s), all in software rendering. A real GPU makes most of this go away, but
not all, and none of it is counted by `systemd-analyze`. KP-1's
`handover_to_login_s` is `graphical.target`; the "login screen shown"
time should be taken from the journal line above (a change for KP-1's
`suites/boot.py`, not done here).

## The network-online pull

**Confirmed.** In every base boot the journal shows, within a
millisecond of `network-online.target`:

```
raye-drivers.service - Install the graphics driver … skipped, unmet condition check ConditionPathExists=!/var/lib/raye/drivers-done
raye-kernel-finish.service - Switch to the Raye kernel … skipped, unmet condition check ConditionDirectoryNotEmpty=/var/lib/raye-kernel
Reached target multi-user.target
```

Both units waited for the network only to be skipped, and
`multi-user.target` waited for both. `systemctl list-dependencies
--reverse network-online.target` lists five units; the other three
(`fwupd-refresh`, `raye-store-catalog`, `raye-update`) are started by
timers, minutes later, not at boot. With the two units masked (wnet),
`network-online.target` and `NetworkManager-wait-online` are not started
at all: nothing else pulls them.

| Scenario | NM-wait-online | `multi-user.target` | `graphical.target` | Login screen shown | Boot finished |
|---|---|---|---|---|---|
| base (DHCP answers) | 0.46 s | 13.33 | 13.71 | 19.64 | 14.24 |
| wnet (pull removed) | not started | 13.15 | 13.79 | 21.06 | 14.41 |
| nodhcp (no answer) | 60.1 s, fails | **74.90** | **75.08** | 23.59 | **75.12** |
| wnodhcp (no answer, pull removed) | not started | 13.57 | 13.85 | 19.57 | 13.88 |

Medians, seconds since the kernel started (base 5 boots, wnet 3,
nodhcp and wnodhcp 2 each).

With a DHCP answer the difference is within the noise of this VM
(`multi-user.target` 0.2 s earlier; one wnet boot ran during a load peak
and had a 1.9 s `cups.service`, which pulls its login screen median
up). Without one, removing the pull takes the boot from 75 s back to
14 s, the same as a boot with network.

What the 60 s wait does when nobody answers DHCP:

- the login screen is shown on time (SDDM does not wait for
  `multi-user.target`), so a fast user logs in before the boot is over;
- `power-profiles-daemon` has `After=multi-user.target`: it starts only
  after the minute, so the power mode in quick settings and Settings
  has nothing to talk to until then;
- `NetworkManager-wait-online.service` ends **failed**, so every offline
  boot leaves a failed unit and the system "degraded";
- anything ordered after `multi-user.target` or `graphical.target`
  waits, and `systemd-analyze` reports a 75 s boot.

KP-8 already removes the pull from `raye-kernel-finish.service` (the
repo copy has `After=NetworkManager.service` and no `Wants=` now; the
image of 2026-10-30 still has the old one). It stays a oneshot in
`multi-user.target`, so a boot where the script does have work (the
switch to the Raye kernel, once) still waits for it; every other boot
does not.

**`raye-drivers.service` needs a change too, but not the same one.** The
script exits 75 ("try again later") when it has no network, and nothing
retries it but the next boot. Without the wait it would run before the
network is up and never install anything. What works: take it out of
`multi-user.target` and start it from a timer (`OnBootSec=1min`, with
`ConditionPathExists=!/var/lib/raye/drivers-done` on the timer and the
service) keeping `Wants=`/`After=network-online.target` on the service:
a service started by a timer does not hold any boot target.
`raye-drivers-check.service` is started on demand from Settings and may
keep its `Wants=`.

## What the cut candidates are worth

wtrim masks the cut candidates of the next section that are units, all
at once (the two network pulls, `systemd-binfmt` and its automount,
`gpu-manager`, `snapperd`, `snapper-boot.timer`, `e2scrub_reap`,
`cups.service`), compared with rbase, three boots each, back to back:

| Measure | rbase | wtrim | Difference |
|---|---|---|---|
| Userspace to boot finished | 6.57 (6.24–6.77) | 5.56 (5.48–6.32) | **−1.0 s** |
| `multi-user.target` | 12.48 | 11.22 | −1.3 s |
| `graphical.target` | 12.79 | 11.41 | −1.4 s |
| SDDM started, in userspace | +5.85 | +5.45 | −0.4 s |
| Login screen shown, in userspace | +12.60 | +11.72 | −0.9 s |
| Memory at the login screen | 679 MiB | 683 MiB | same |

Medians; the target lines in seconds since the kernel started. The
kernel part was 0.4 s shorter in wtrim too, which no unit can change:
that much of the `multi-user.target` and `graphical.target` differences
is the host. The userspace lines leave the kernel out and are the fair
ones: about one second of a 6.6 s userspace comes from units a desktop
does not need at boot. How much each is worth alone is for KP-4 to
measure, cut by cut.

## Slowest initcalls

One boot with `initcall_debug` (it is slower overall: 8.4 s kernel), the
20 slowest, built-in and module:

| ms | at (s) | initcall | where |
|---|---|---|---|
| 1678.7 | 16.60 | `svm_init` | kvm_amd (after boot; nested virtualisation, VM only) |
| 854.0 | 1.66 | `pci_subsys_init` | built in (PCI scan; slow in a VM) |
| 322.9 | 13.06 | `parport_pc_init` | parport_pc (parallel port, see below) |
| 238.0 | 2.78 | `slab_late_init` | built in |
| 184.0 | 2.44 | `sysfb_init` | built in (firmware frame buffer) |
| 146.0 | 0.79 | `acpi_init` | built in |
| 124.2 | 2.20 | `virtio_blk_init` | built in (VM disk) |
| 100.0 | 2.08 | `loop_init` | built in |
| 80.7 | 1.79 | `inet_init` | built in |
| 74.3 | 1.97 | `serial8250_init` | built in (legacy serial ports probed) |
| 72.4 | 6.42 | `init_module` | raid6_pq (benchmark, pulled in by btrfs) |
| 49.0 | 4.45 | `virtio_gpu_driver_init` | virtio_gpu (VM GPU) |
| 37.8 | 3.54 | `init_encrypted` | built in |
| 32.0 | 1.86 | `percpu_counter_startup` | built in |
| 26.7 | 2.54 | `load_system_certificate_list` | built in |
| 24.4 | 1.90 | `virtio_pci_driver_init` | built in |
| 23.0 | 1.70 | `chr_dev_init` | built in |
| 23.0 | 0.63 | `crc32_mod_init` | built in |
| 22.2 | 2.49 | `param_sysfs_builtin_init` | built in |
| 21.0 | 1.83 | `jent_mod_init` | built in |

11 initcalls are above 50 ms. In the boot path and not VM-only:
`raid6_pq` (72 ms), `loop_init` (100 ms), `serial8250_init` (74 ms) and
the parallel port. The PCI scan, the frame buffer and the virtio ones
are what a VM costs; they are measured again on real hardware before
anything is done about them.

Two things the initcalls do not show, from the timestamps around them
(same in all five base boots): 1.5 s between the last driver and
`modprobe btrfs` (initramfs scripts), and 0.8–1.0 s between the `xor`
initcall and `init_btrfs_fs`, which is the loading of the btrfs module
itself.

## Initramfs

`/boot/initrd.img-7.0.0-42-generic`, as `update-initramfs` builds it on
the installed system (`MODULES=most`, `COMPRESS=zstd`, level 1):
**96.3 MB**, four parts:

| Part | Size | Content |
|---|---|---|
| 1, not compressed | 0.3 MB | AMD microcode |
| 2, not compressed | 14.8 MB | Intel microcode |
| 3, not compressed | 51.5 MB | modules (34.0 MB) and firmware (17.2 MB), already `.zst` each |
| 4, zstd | 29.7 MB (74.2 MB unpacked) | programs and libraries: udev hardware database 14.4 MB, OpenSSL, GnuTLS, two libcurl, Kerberos, Plymouth's cairo/pango/X11 and 1.4 MB of stock UI fonts, btrfs, tpm2 tools, dhcpcd |

Unpacking takes 0.45–0.6 s in this VM ("Trying to unpack rootfs" to
"Freeing initrd memory"). On real hardware the bigger cost of a large
initramfs is usually the boot loader reading it from disk through the
firmware.

What part 3 carries that a desktop does not boot from: firmware for
Mellanox (3.8 MB), LiquidIO, Netronome, Chelsio, Broadcom NetXtreme II,
QLogic cards; 13.9 MB of network driver modules (NFS and iSCSI root
support), 5.4 MB of SCSI (Fibre Channel included), 1.0 MB InfiniBand.

Compression of part 4, measured in user space on this host (relative
only):

| Codec | Size | Decompress |
|---|---|---|
| zstd -1 (today) | 29.7 MB | 221 ms |
| zstd -3 | 26.6 MB | 210 ms |
| zstd -19 | 22.1 MB | 287 ms |
| lz4 -9 | 31.6 MB | 79 ms |

lz4 saves about 0.14 s of unpacking for 1.9 MB more; zstd -19 saves
7.6 MB to read for 0.07 s more. Neither is worth more than the cuts
above; KP-13 decides on real hardware, where reading speed is known.
`MODULES=dep` stays out (a disk moved to another computer would not
start).

## Every enabled unit and timer

Median of the five base boots. "Before login" counts the boots where the
unit started before SDDM. A unit that ran and is not in `blame` cost less
than a few milliseconds.

| Unit | Boot cost (s) | Before login | Note |
|---|---|---|---|
| `accounts-daemon.service` | 1.26 | 5/5 | the greeter's user list; D-Bus activated anyway |
| `udisks2.service` | 1.23 | 5/5 | disks in Files and Plasma; D-Bus activated anyway |
| `NetworkManager.service` | 0.97 | 5/5 | on the path to SDDM (`network.target`) |
| `snapper-boot.service` (by its timer) | 0.74 | 5/5 | a btrfs snapshot at every start |
| `gpu-manager.service` | 0.67 | 5/5 | `Before=display-manager.service`; hybrid graphics helper |
| `e2scrub_reap.service` | 0.55 | 5/5 | ext4 scrub snapshots; Raye is on btrfs |
| `snapperd.service` | 0.54 | 5/5 | enabled in `sysinit.target`, but it is a D-Bus service |
| `systemd-binfmt.service` (static) | 0.51 | 5/5 | holds `sysinit.target`; only rule: Python `.pyc` |
| `NetworkManager-wait-online.service` | 0.46 | 5/5 | pulled by the two Raye units, holds `multi-user.target` |
| `power-profiles-daemon.service` | 0.37 | after | `After=multi-user.target` |
| `keyboard-setup.service` | 0.35 | 5/5 | console keymap |
| `switcheroo-control.service` | 0.33 | 5/5 | GPU switching; D-Bus activated |
| `raye-dualboot.service` | 0.31 | 5/5 | finds Windows; could run after the login screen |
| `netplan-configure.service` | 0.31 | 5/5 | |
| `avahi-daemon.service` | 0.29 | 5/5 | network printers and shares |
| `cups.service` | 0.28 | 5/5 | in the chain to `multi-user.target`; `cups.socket` and `cups.path` are enough |
| `wpa_supplicant.service` | 0.25 | 5/5 | NetworkManager starts it on demand |
| `systemd-timesyncd.service` | 0.25 | 5/5 | |
| `systemd-resolved.service` | 0.20 | 5/5 | |
| `console-setup.service` | 0.17 | 5/5 | |
| `finalrd.service` | 0.14 | 5/5 | |
| `setvtrgb.service` | 0.13 | 5/5 | console colours |
| `sddm.service` | 0.09 | - | |
| `ufw.service` | 0.05 | 5/5 | firewall, keep |
| `NetworkManager-dispatcher.service` | - | 5/5 | D-Bus activated |
| `polkit-agent-helper.socket`, `uuidd.socket`, `cups.socket`, `avahi-daemon.socket`, resolved sockets | ~0 | - | sockets |
| `raye-drivers.service`, `raye-kernel-finish.service` | skipped | - | but wait for the network first (above) |
| `raye-snapshots.service` | skipped | - | first boot only (2.0 s then) |
| `smartmontools.service`, `ssl-cert.service`, `systemd-pstore.service`, `grub-initrd-fallback.service`, `grub2-common.service`, `tpm-udev.path` | skipped | - | conditions not met in the VM |
| `bluetooth.service` | not started | - | no Bluetooth in the VM |
| `getty@tty1.service` | - | - | |
| `unattended-upgrades.service` | ~0 | - | only acts at shutdown |

Timers (only `snapper-boot` runs before the login screen):

| Timer | When | Note |
|---|---|---|
| `snapper-boot.timer` | 1 s after boot | the 0.74 s snapshot above, while the login screen starts |
| `raye-store-catalog.timer` | 1 min after boot, then 12 h | Flatpak catalogue, idle priority; lands in the "5 minutes after login" measuring window |
| `motd-news.timer` | 1 min after start, then 12 h | downloads a news line for terminal logins; useless on a desktop |
| `raye-update.timer` | 10 min after boot, then 6 h | |
| `snapper-cleanup.timer`, `systemd-tmpfiles-clean.timer` | 10 and 15 min after boot | |
| `apt-daily.timer`, `apt-daily-upgrade.timer`, `fwupd-refresh.timer`, `dpkg-db-backup.timer`, `e2scrub_all.timer`, `fstrim.timer` | calendar, randomised | `Persistent=true`: a missed run starts right after boot |

Also loaded at every boot by `systemd-modules-load` (in `sysinit`):
`lp` and `ppdev` (from `cups-filters`, parallel port printers), which
bring `parport_pc` (323 ms initcall), plus `i2c_dev` and `msr` (fwupd),
`zram` and `ntsync`.

## Cuts for KP-4

In order of what they should save on real hardware. Each one is checked
with `systemctl list-dependencies --reverse <unit>` first, then boots
before and after (KP-1), and the feature it touches used once after the
cut.

| # | Cut | How | Expected | Check after |
|---|---|---|---|---|
| 1 | No `network-online.target` at boot | KP-8's fix of `raye-kernel-finish.service` (done in the repo); `raye-drivers.service` started by a timer instead of `multi-user.target` (above, owner of `release/drivers/`). Do **not** disable `NetworkManager-wait-online.service`: once nothing at boot pulls it, it costs nothing, and the timer services need a real "online" | up to 0.5 s with DHCP; **60 s, and no failed unit,** without network | network after login; driver install on a first boot with and without network (unplug, boot, plug in: installed within minutes); Raye kernel trial boot |
| 2 | `cups.service` on demand | preset `disable cups.service`, keep `cups.socket` and `cups.path` enabled | 0.3 s off `multi-user.target` | print a test page; `lpstat` |
| 3 | `snapperd.service` on demand | preset `disable snapperd.service` (D-Bus activation stays); only pays with cut 8, since `snapper-boot` asks for it at every boot | 0.5 s of CPU and disk at login, one daemon less | `snapper list` as root; an apt snapshot pair |
| 4 | `gpu-manager.service` | preset `disable` (it only matters for hybrid NVIDIA setups the driver flow handles; check `raye-drivers` first) | 0.7 s before the login screen | a hybrid laptop on real hardware (KP-15) |
| 5 | `e2scrub_reap.service` | preset `disable` (it removes leftover LVM snapshots of ext4 scrubs; Raye installs no LVM) | 0.5 s | - |
| 6 | `systemd-binfmt` | `/etc/binfmt.d/python3.14.conf → /dev/null` is not enough (the unit still runs); either leave it or mask the unit and the binfmt_misc automount if no Raye feature needs binfmt (none does today) | 0.5–0.8 s on the path to `sysinit.target` | `.exe` double-click still works (Raye's own launcher, not binfmt) |
| 7 | Parallel port modules | `install lp /bin/true` and `install ppdev /bin/true` in a `modprobe.d` file (a `blacklist` line does not stop a module named in `modules-load.d`; the `cups-filters` file is not Raye's to change) | 0.3 s of kernel work in `sysinit` | `systemd-modules-load` still succeeds |
| 8 | `snapper-boot.timer` | owner's call: a snapshot at each start is not what Windows does; restore points come from apt | 0.7 s of disk work at login, fewer snapshots | `snapper list` |
| 9 | `motd-news.timer` | preset `disable` | a download a minute after every boot | - |
| 10 | `accounts-daemon`, `udisks2`, `switcheroo-control` | try removing them from `graphical.target.wants` (they are D-Bus activated when asked) | CPU while the login screen starts | the greeter's user list; Files' devices; GPU offload menu |
| 11 | `power-profiles-daemon.service` | nothing to change: it waits for `multi-user.target`, which no longer waits for the network once cut 1 is in | power mode ready at login, also offline | quick settings power mode after an offline boot |
| 12 | `raye-dualboot.service` | order it after `graphical.target` (it only adds a menu entry) | 0.3 s | "Restart to Windows" shows |

Do not touch: `ufw`, `systemd-resolved`, `systemd-timesyncd`,
`NetworkManager` itself, `keyboard-setup`/`console-setup` (keyboard
layout on the text consoles), `avahi-daemon` (network printers,
Settings' printers page).

## Candidates for KP-13

Experiments that need real hardware or a kernel build:

- **btrfs built into the Raye kernel** (`CONFIG_BTRFS_FS=y`, KP-11's
  config): no module to load in the initramfs (0.8–1.0 s here) and the
  raid6 benchmark moves into the kernel; with
  `CONFIG_RAID6_PQ_BENCHMARK=n` it goes away (72 ms).
- **A smaller initramfs**: a hook that leaves out the server network
  firmware and the network/FC/InfiniBand modules (about 35 MB of 96),
  measured as boot loader read time plus unpack time. Not `MODULES=dep`.
- **initramfs compression**: zstd -1 (today) vs lz4 vs zstd -19 (table
  above), on NVMe and on a SATA SSD.
- **The 1.5 s gap in the initramfs** (plymouth, clevis, cryptroot in
  `local-top`): time each script on real hardware (`debug` on the
  kernel command line writes the initramfs trace) and on an encrypted
  install with TPM.
- **systemd's own start** (2.1 s here before the first unit): which
  generators run and what each costs.
- **`serial8250.nr_uarts`, `loop` device count**: the 74 ms and 100 ms
  initcalls, on real hardware.
- **The login screen itself**: KWin and the greeter's first frame with a
  real GPU; the Raye greeter theme (this image still shows the stock
  one) loaded and timed.

## Notes for other owners

- **KP-1** (`tools/bench/suites/boot.py`): add "login screen shown" from
  the journal (`sddm-greeter-qt6 … Adding view for`), and the userspace
  milestones `sysinit.target`, `network.target`, `sddm.service`;
  `handover_to_login_s` is `graphical.target` today.
- **raye-drivers.service** (`raye-base/release/drivers/`): the
  network-online pull, cut 1: a timer instead of `multi-user.target`.
- **SDDM theme**: the image of 2026-10-30 has `Current=breeze` in
  `/etc/sddm.conf.d/sddm-raye.conf`; the login screen measured here is
  the stock one.
- **Boot screen font** (Plymouth theme owner): the initramfs carries the
  base's stock UI fonts (1.4 MB, regular and mono) for Plymouth's text,
  and no Inter. The Raye theme draws its hints as pictures; any text it
  draws as text falls back to those fonts. Either ship Inter there or
  leave the stock fonts out (part of the smaller initramfs above).

## Real hardware

To do when Raye is on its own disk on the owner's PC: three cold boots
with `raye-bench`, one with `initcall_debug`, `systemd-analyze plot`
kept as `boot-hw.svg`, the same tables as above, and the cuts verified.
Firmware and boot menu times only exist there.
