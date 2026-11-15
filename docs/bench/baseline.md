# Baseline

Where Raye stands before the final pass changes anything: the image of
2026-10-30 as the installer leaves it on a disk. Every optimisation of
the final pass (KP-3 to KP-13) is compared with these numbers.

**These are virtual machine numbers.** The disk, the timer and the
graphics are virtual and the host was shared with other work. They are
good for one thing: seeing whether a change made the boot slower or
faster on the same VM. They are not Raye's boot time and are never
published. The real hardware column is at the end, still empty.

How the disk was built and how each boot was measured:
[boot-analysis.md](boot-analysis.md#how-it-was-measured). Where the time
goes and what to cut: the rest of that file.

## What was measured

| | |
|---|---|
| Image | Raye Linux 0.1 "Preview", build 20261030 (`raye-system`, `raye-desktop` 0.1~dev5) |
| Kernel | 7.0.0-42-generic, the base's stock kernel (the Raye kernel is not in this image yet) |
| Command line | `root=UUID=… ro rootflags=subvol=@ quiet splash panic=30` |
| Software | systemd 259.9, Plasma and KWin 6.6.6, Mesa 26.0.8, SDDM 0.21 |
| Disk | btrfs (`@`, `@home`, `@var_log`, `@cache`, zstd:1), 1 GiB EFI, no encryption |
| VM | QEMU/KVM, 4 vCPUs of an AMD EPYC 7551P, 4 GiB, virtio disk (`cache=none`), virtio GPU without 3D, network by DHCP |
| Started by | the firmware (UEFI) straight into the kernel: no firmware or boot menu time |
| Runs | 2026-10-31, cold boots from the same disk state: series base (5 boots, host load 55–71 on 16 cores) and rbase (3 boots, load 34–38); QEMU at `nice -10` |

Vendor suffixes of version numbers are left out here and in the JSON.

## Boot

Seconds since the kernel started. "Login screen shown" is when the
greeter puts its window on screen (journal), not `graphical.target`.

| Measure | Median | Min–max | base-1 | base-2 | base-3 | base-4 | base-5 |
|---|---|---|---|---|---|---|---|
| Kernel + initramfs | **6.50** | 6.27–7.37 | 7.37 | 6.53 | 6.27 | 6.50 | 6.31 |
| Userspace to boot finished | **7.82** | 7.22–7.93 | 7.56 | 7.82 | 7.82 | 7.22 | 7.93 |
| Boot finished (systemd) | 14.24 | 13.71–14.93 | 14.93 | 14.35 | 14.10 | 13.71 | 14.24 |
| Login screen started (SDDM) | 13.34 | 12.53–14.33 | 14.33 | 13.10 | 12.53 | 13.34 | 13.64 |
| `graphical.target` reached | **13.71** | 13.21–14.87 | 14.87 | 13.71 | 13.21 | 13.65 | 14.20 |
| **Login screen shown** | **19.64** | 19.53–21.63 | 21.63 | 19.53 | 19.64 | 19.54 | 20.43 |
| Host load when it started | | | 66.6 | 71.3 | 67.1 | 61.5 | 55.3 |

A second series of three boots (rbase), taken later the same evening on
a quieter host (load 34–38), as the control for the what-if boots of
[boot-analysis.md](boot-analysis.md):

| Measure | Median | Min–max | rbase-1 | rbase-2 | rbase-3 |
|---|---|---|---|---|---|
| Kernel + initramfs | **6.37** | 6.07–6.75 | 6.07 | 6.37 | 6.75 |
| Userspace to boot finished | **6.57** | 6.24–6.77 | 6.77 | 6.57 | 6.24 |
| Boot finished (systemd) | 12.94 | 12.83–12.99 | 12.83 | 12.94 | 12.99 |
| Login screen started (SDDM) | 12.35 | 11.79–12.61 | 12.35 | 11.79 | 12.61 |
| `graphical.target` reached | **12.79** | 12.21–12.95 | 12.79 | 12.21 | 12.95 |
| **Login screen shown** | **18.66** | 17.96–20.25 | 18.66 | 17.96 | 20.25 |
| Host load when it started | | | 36.1 | 37.7 | 34.3 |

The same image boots 1.3 s faster on the quieter host: compare two
images only with boots taken back to back, never with the table of
another day.

The time from SDDM starting to the login screen being on screen is 6.3 s
here (KWin and the greeter drawing in software, there is no GPU in this
VM). On a real graphics card it is much shorter; it is still the part
that `graphical.target` does not count.

## After boot, at the login screen

| Measure | Median | Min–max |
|---|---|---|
| Memory in use (total minus available), nobody logged in | 680 MiB | 662–689 (all eight boots) |
| Disk used by `/` (btrfs, compressed) | 3.58 GiB | - |
| Files on `/` before compression | 6.4 GiB | - |

App launch times (the `launch` suite of KP-1) need a Plasma session and
were not taken here; they go in with the first real hardware run.

## After signing in

Taken on the 0.3 Beta, in the same 4 GB virtual machine with two
screens: restart, sign in, wait 180 s with nothing open, then read
`free -m` as root through the guest agent (no ssh session open).

| Measure | Value | |
|---|---|---|
| Memory in use after signing in, nothing open | 1198 MiB | system updated from 0.2 (PSS of all processes 949 MB, 63 processes) |
| The same, fresh install | 1200 MiB | PSS 956 MB, 63 processes |

## Reproducible?

The rule is every run within ±10 % of the median of its series.

- **rbase (3 boots, load 34–38): every measure is within it.** The
  widest are the login screen shown (−3.8 % to +8.5 %) and the kernel
  part (−4.7 % to +6.0 %); the boot as a whole is within ±0.9 %.
- base (5 boots, load 55–71): boot finished, userspace and SDDM start
  are within it for all five runs. One run (base-1, started while the
  load rose to 71) is +13.5 % on the kernel part and +10.1 % on the
  login screen shown; the other four are within ±4 %.
- Memory: within ±3 % in all eight boots.

A busy host is what spreads the numbers: take VM boots on a quiet host,
and the two sides of a comparison one right after the other.

The first boot of a new install is not in the table: it rebuilt the
linker cache (`ldconfig`, 5.7 s) and set up snapshots (2.0 s), and took
19.2 s to `graphical.target`, 27.0 s to the login screen.

## Real hardware

To fill when Raye runs on its own disk on the owner's PC (KP-15), with
`raye-bench` after three cold boots and `raye-bench.ps1` on the same PC's
Windows. Targets from the spec: firmware handover to login screen under
5 s on NVMe, kernel + initrd under 2 s, faster than the same PC's
Windows without Fast Startup.

| Measure | Raye (median, min–max) | Windows 11, Fast Startup off | Windows 11, Fast Startup on |
|---|---|---|---|
| Firmware | TODO | TODO | TODO |
| Boot menu | TODO | TODO | TODO |
| Kernel + initramfs | TODO | - | - |
| To login screen | TODO | TODO | TODO |
| Memory after login | TODO | TODO | TODO |
| Disk used | TODO | TODO | TODO |

## Files

- `baseline.json`: the five base boots joined by `raye-bench --merge`,
  in KP-1's format (format 2); `baseline-rbase.json`: the same for the
  three rbase boots.
- `boot-analysis.json`: every run with the extra measures (login screen,
  network, phases), the scenarios, units, initcalls and initramfs.
- `boot-vm.svg`: `systemd-analyze plot` of base-2, the median run.
