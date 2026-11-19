# Raye Linux 1.0 Beta Brocken

The first beta of Raye Linux 1.0: a desktop laid out like Windows 11, drawn
in Raye's own colors, with updates that install themselves. It is a beta.
Install it on a spare computer or next to your current system, not on the
only machine you depend on. A 0.5 Beta already installed gets all of this
through Raye Update; the new installer only matters for new installs.

Français : https://dl.rayelinux.com/iso/1.0-beta/release-notes-1.0-beta.fr.md

## New in 1.0 Beta

- **Clock**, a new app: alarms that ring even with the window closed (days,
  sound, Snooze), timers, a stopwatch with laps and world clocks.
- **Graphics Card**, a new app: live readings of your graphics card. On AMD
  Radeon cards it sets the performance mode, the workload profile, the
  power limit and a fan curve, kept across restarts. NVIDIA cards get the
  NVIDIA Control Panel, installed with the driver and named so in Start.
- **Settings > System > Performance options**: one choice turns animations,
  transparency and shadows off on a slow PC, or set each effect on its own.
- **Raye Store** is much bigger: search a Windows program (Photoshop, Office,
  Battle.net...) and it finds the apps that do the same job. Steam and
  Heroic are up front, and Steam Play is on for every game once the Store
  installs Steam. TeamViewer, Mullvad VPN and balenaEtcher were added.
- **.deb files** install with a double-click, in a small window that fetches
  what they need and explains any problem in plain words.
- **Windows programs** get the fonts they ask for, start in their own
  folder, and 32-bit games can use 4 GB of memory. Microsoft Store packages
  (.msix, .appx) open with Raye, or say plainly why they can't.
- **File Explorer**: the mouse wheel scrolls three lines per notch like
  Windows, copies to a USB drive show what is really written and finish only
  when the drive is safe to remove, and Properties and Folder options are
  clearer.
- **Raye Update** is quieter and more reliable: Plasma updates arrive in one
  set, a file that fails to download is simply tried again later, checking
  for updates no longer hangs for minutes when a server goes quiet, and
  Settings shows the download speed, the time left and each update's status.
- **Faster start**: no boot menu wait while starts go well, smaller start-up
  files, and helpers for older programs start only when one needs them.
- **Older graphics cards**: if the desktop fails to show twice in a row,
  Raye switches to a simpler display mode by itself.
- **The installer** can install next to another Linux (it can make ext4 and
  btrfs partitions smaller), works on PCs started in BIOS mode, and asks
  before it erases a disk, deletes a partition or makes one smaller. The USB
  menu has "Check the USB stick for errors", and a stick written badly says
  so instead of a cryptic error.
- **The web apps** you install from your browser and pin to the taskbar keep
  their own icon and name.
- Ctrl+Win+Enter turns the screen reader on or off.

## Install

Download the image from https://rayelinux.com, check it, and write it to a
USB stick of 8 GB or more with Rufus (DD Image mode) or balenaEtcher.
Start the computer from the stick (often F12, F11, F8 or Esc at power on).

## Known issues

- Older AMD cards (RX 400 and 500 series) can start at a low resolution with
  low frame rates on some PCs. The automatic simpler display mode helps some
  cards, not all; we are still working on it.
- The Raye kernel is not offered on PCs that use NVIDIA's driver: NVIDIA's
  prebuilt modules only load on the standard kernel.
- The Graphics Card panel's fan curve and power limit have been checked on
  test data, not yet on every generation of AMD card.
- Not every Windows program runs, and apps built only for the Microsoft
  Store cannot run at all. Programs that also exist for Raye (Discord,
  Steam) are better installed from the Raye Store.
- Alarms ring only while the PC is on: Clock cannot wake it from sleep yet.

## Report a problem

Open an issue at https://github.com/Raye-Linux/releases/issues, or write
to bonjour@rayelinux.com. Say what computer you have, what you did, what
you expected and what happened. A photo of the screen helps.

Raye Linux is based on Ubuntu. It is not affiliated with or endorsed by
Canonical Ltd.
