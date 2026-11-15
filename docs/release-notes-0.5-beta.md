# Raye Linux 0.5 Beta Alpenglow

An update to the 0.3 Beta of Raye Linux: a desktop laid out like Windows 11,
drawn in Raye's own colors, with updates that install themselves. It is a
beta. Install it on a spare computer or next to your current system, not
on the only machine you depend on. A 0.3 Beta already installed gets all
of this through Raye Update.

Français : https://dl.rayelinux.com/iso/0.5-beta/release-notes-0.5-beta.fr.md

## New in 0.5

- **Archives in File Explorer**, with Raye's own archive engine: ZIP, 7z,
  RAR, tar and more open like folders, even with no extension. Extract
  all, Extract here, Compress to ZIP, 7z or tar.zst, and an Add to archive
  window with levels, split parts and passwords. RAR archives open but are
  not made.
- **Windows programs** run on Raye's own layer, which brings .NET, the web
  engine some programs embed, and DirectX through Vulkan. Microsoft's
  Visual C++ runtimes and core fonts arrive in the background once the PC
  is online. A program no longer opens the screen share picker by itself,
  screen capture works through the picker, OBS Studio for Windows starts
  and records, and FL Studio can run its sound at 44.1 kHz. Typing notepad
  or regedit in a terminal opens the Raye app.
- **Raye Store** offers popular Windows programs and says how each runs
  here: Optimized for Raye, Works on Raye, or Doesn't work on Raye, with
  the reason.
- **Device security**, in Settings: turn disk encryption on or off while
  the PC runs, with a recovery key shown once, and the steps to turn
  Secure Boot on.
- **Control Panel** is filled with the classic items and their tasks.
- **Settings**: Sounds and Controllers pages, Virus & threat protection,
  and a switch for the short sound played when you change the volume.
- **For developers**, in Settings > System > Advanced: Developer Mode,
  Device Portal (a web page to manage this PC from another one on your
  network) and OpenSSH with keys only.
- **Updates**: Ctrl+Alt+Del and the lock screen offer Update and restart
  when updates are ready, Install now says when it waits for the charger,
  and a restart is asked for again when newer versions of the same
  packages arrive.
- **Root access** is what password prompts ask for, and accounts are Sudo
  user or Standard user. Registry Editor asks for the root password for
  every system change and leaves alone the files packages own.
- **Network**: no Wi-Fi pages or Wi-Fi list on a PC without a Wi-Fi card,
  and Quick settings say Ethernet when a cable is plugged in.
- **Start and boot**: a smaller start-up image and no wait for the
  network make the start quicker, the boot screen sits in the middle of
  every screen, the boot menu has a "Raye Linux, earlier states" entry to
  start from a restore point, and an install without encryption keeps the
  boot menu hidden.
- **Desktop**: the notification center and the calendar always fit on the
  screen, Start slides up smoothly, search answers sooner, and a short
  sound plays when you change the volume.
- **Setup** looks calmer: flat pictures, named password boxes and a way to
  show the disk password.
- **Game mode** switches to a scheduler made for games while a game runs.
- Task Manager's Performance page no longer blinks, menus and flyouts are
  solid again, and the texts use American spelling.

## New in 0.3

- **Task Manager** with Processes, Performance, Startup apps, Users,
  Details and Services. It replaces System Monitor.
- **File Explorer** redrawn: tabs in the title row, address row and
  command bar, Home, This PC, Gallery, the eight Windows views and a new
  Properties dialog.
- **Calendar**, **Control Panel** and **Registry Editor**, Raye's own.
  The clock shows the day's events.
- **Updates without a restart**: only the kernel, drivers, firmware and
  the desktop itself wait for a restart, and each one says so. The rest
  installs while you work.
- **Start and shutdown** stay on the Raye picture from the boot menu to
  the sign-in screen, with no text.
- **Quick settings** pages for the network, Bluetooth and sound, calmer
  colors, new wallpapers (two of them animated) and new pointers.
- **Restore points** are taken every day and around each update, and
  Restore Points lets you go back.

## What's in it

- **Desktop**: centered taskbar with Start, pinned apps and the clock on
  every screen, a right-click menu with Task Manager and Taskbar settings,
  Win+R to run a program, folder or web address. Raye Night colors,
  the Inter font, Raye wallpapers and icons.
- **Installer**: a guided setup in English and French. It follows the
  network live, can keep Windows next to Raye, and can encrypt the disk
  with the TPM so you only type a password when something changed.
- **Raye Settings**: one app for the system, with Display (choose the main
  screen), Taskbar, Wi-Fi, Bluetooth, sound, accounts, updates, drivers
  and the Raye kernel.
- **Raye Store**: apps from Flathub and Raye's own, with progress and
  Cancel while installing, Open and Uninstall once installed. Links from
  the Start menu search open the app's page in the Store.
- **Raye Update**: system, security and app updates are downloaded in the
  background. Most install right away; the ones that need a restart are
  installed on the next restart, with the progress on the boot screen. It waits when you are on battery, on a metered connection
  or playing.
- **Windows programs**: many .exe installers open with a double-click and
  get a Start menu entry.
- **Secure Boot** stays on. The Raye kernel 7.0 is included and can be
  turned on from Settings, offline.
- **Lock and sign-in screens** in the Raye style, with the password field
  on the screen where the mouse is, and working Shut down and Restart.

## Before you start

- A 64-bit Intel or AMD computer that starts in UEFI mode (most computers
  from 2012 on). Older BIOS-only machines cannot start this image.
- 4 GB of memory (8 GB recommended) and 25 GB of free disk space, which
  is the figure the installer itself requires.
- A USB stick of 8 GB or more. Everything on it will be erased.
- An internet connection during setup is useful but not required.
- Raye uses about 680 MiB of memory at the sign-in screen, before anyone
  signs in (the median of eight boots in a 4 GB virtual machine), and about
  1200 MiB once you have signed in, with nothing open. So 4 GB is the
  minimum that works and 8 GB is the comfortable figure.

## Download and check

| File | |
|---|---|
| `raye-0.5-beta-amd64.iso` | the image, from https://dl.rayelinux.com/iso/0.5-beta/ |
| `raye-0.5-beta-amd64.iso.part1`, `.part2` | the same image in two parts, on GitHub (2 GB limit per file) |
| `SHA256SUMS`, `SHA256SUMS.asc` | checksums and their signature |
| `raye-archive.asc` | the Raye Linux archive key |

From GitHub, put the parts back together first:

    cat raye-0.5-beta-amd64.iso.part1 raye-0.5-beta-amd64.iso.part2 > raye-0.5-beta-amd64.iso

In a Command Prompt instead: `copy /b raye-0.5-beta-amd64.iso.part1 + raye-0.5-beta-amd64.iso.part2 raye-0.5-beta-amd64.iso`

Then check the download:

    gpg --show-keys raye-archive.asc      # fingerprint EA73 69D4 C3A3 10B2 DF3D  FC16 D3AA 2E62 5DDE 161E
    gpg --import raye-archive.asc
    gpg --verify SHA256SUMS.asc SHA256SUMS
    sha256sum --check --ignore-missing SHA256SUMS

`gpg --verify` must say "Good signature from Raye Linux Archive Signing
Key", and `sha256sum` must print `raye-0.5-beta-amd64.iso: OK`.

## Write it to a USB stick

- **Rufus**: choose the ISO and, when asked, write it in **DD image mode**.
  The ISO mode of Rufus gives a stick that does not start.
- **balenaEtcher**: choose the ISO, the stick, then Flash.
- **dd** on Linux (replace `sdX` with your stick, check twice with `lsblk`):
  `sudo dd if=raye-0.5-beta-amd64.iso of=/dev/sdX bs=4M conv=fsync status=progress`

Start the computer from the stick (often F12, F11, F8 or Esc at power on).

## Known issues

- The screen goes black for 3 to 5 seconds just before the sign-in screen
  appears.
- Some apps still show their own look: the terminal, the screenshot tool
  and a few dialogs are themed but not yet redrawn as Raye apps.
- The Start menu and the taskbar are close to Windows 11 but not identical
  yet (search field, recommended section).
- The default account picture is not the same on the sign-in screen and
  on the lock screen. A lone "OK" button shows under "Wrong password".
- Windows programs: the first program opened after setup takes a while,
  some installers show a grey old-style window, and not every program
  runs. Programs that also exist for Raye (Discord, Steam) are better
  installed from the Raye Store.
- Microsoft's core fonts arrive only once the PC has been online after
  setup. A Windows program opened before that is given one of the
  system's fonts instead, so a few dialogs are laid out wrongly.
- Windows games have hardly been tried. Programs draw through Vulkan, but
  the only game played so far is an old Direct3D 9 one, and no Direct3D 11
  or 12 game has been tried on a real graphics card.
- Programs built on .NET have hardly been tried. Raye brings .NET and the
  web engine some programs embed, but Paint.NET's installer still stops
  on an error.
- Roblox Studio cannot be signed in to from its own window yet: use
  Login via Browser.
- Raye Update checks rayelinux.com and GitHub for Raye's own packages.
  Until you are online, Settings shows that updates could not be checked.
- Benchmarks against Windows on real hardware are not done yet.
- `add-apt-repository -c` and `-p` (adding a component or a pocket) can pick
  Raye's own package source and rewrite it. apt then reports 404 for Raye's
  packages, and the file belongs to a package, so it is replaced on the next
  update. Add a PPA with plain `add-apt-repository ppa:...`, which writes its
  own file. If it already happened:
  `sudo apt install --reinstall raye-archive-keyring`.
- Source packages are listed but switched off, so `apt update` does not
  download 18 MB of source indexes on every machine. To build a package from
  source, turn them on first:
  `sudo sed -i 's/^Enabled: no$/Enabled: yes/' /etc/apt/sources.list.d/ubuntu.sources && sudo apt update`.
- The outline that marks the focused control is faint on a few dark
  surfaces, and fainter still if you pick a very light or very dark accent
  color. Text and controls themselves keep their contrast; it is the thin
  focus ring that does not always reach the 3:1 that a keyboard user wants.

## Report a problem

Open an issue at https://github.com/Raye-Linux/releases/issues, or write
to bonjour@rayelinux.com. Say what computer you have, what you did, what
you expected and what happened. A photo of the screen helps.

Raye Linux is based on Ubuntu. It is not affiliated with or endorsed by
Canonical Ltd.
