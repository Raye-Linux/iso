# Raye Linux 1.0 Beta Sundog

The second beta of Raye Linux 1.0, out November 21, 2026. It brings a
second desktop you can pick, a Windows 10 look, your files from Windows,
an automatic game mode and many fixes. It is still a beta: install it on a
spare computer or next to your current system, not on the only machine you
depend on.

Français : https://dl.rayelinux.com/iso/1.0-beta/release-notes-1.0-beta.fr.md

## Update or install

- **Already on Raye (0.5 Beta or 1.0 Beta Brocken)?** You don't need the new
  download. Raye Update brings Sundog by itself. To get it now, open
  Settings > Raye Update and click Check for updates, then restart when it
  asks. The update installs while the PC restarts; leave it on until the
  desktop is back.
- **New install:** download the image from https://rayelinux.com/en/download/,
  check it, and write it to a USB stick of 8 GB or more with Rufus (DD Image
  mode) or balenaEtcher. Start the computer from the stick (often F12, F11,
  F8 or Esc at power on).

## New in 1.0 Beta Sundog

- **Pick your desktop.** Setup asks which desktop you want: KDE Plasma (the
  Raye desktop you know) or Hyprland, a lighter tiling desktop with the same
  taskbar, Start menu, quick settings and notifications. Settings >
  Personalization > Desktop environment switches between them in a few
  seconds, without a password, and your open apps come back. The sign-in
  screen shows which desktop it will open.
- **A Windows 10 look.** Settings > Personalization offers a Windows 10
  style: taskbar on the left with a search box, square corners, and a Start
  menu with an app list and tile groups you can resize.
- **Windows-style motion.** Windows open and close the Windows 11 way,
  maximize and snapping animate, and Start, flyouts and menus fade smoothly.
- **Your files from Windows.** A new page, Settings > Accounts > Files from
  Windows, copies Documents, Pictures, Music, Videos, Downloads and the
  Desktop of each Windows account, with the wallpaper and browser favorites.
  Windows is only read, never changed, and every file is checked after the
  copy. When you install Raye next to Windows, you are offered this after
  the first sign-in. When Raye replaces another system, it now also keeps
  your wallpaper, saved Wi-Fi networks, your Firefox or Chrome profile and
  your Flatpak apps.
- **Game Mode turns on by itself** while a Steam, Store or Windows game
  runs: full processor speed, a game scheduler, effects paused and the best
  power mode while plugged in. Everything comes back when the game ends.
  Settings > Gaming > Game Mode lists the games it found.
- **NVIDIA:** games run at full speed again after the driver is installed
  or updated (this fix was also sent as an urgent update on November 20).
  Settings offers only the recommended NVIDIA driver, and Display and
  Graphics opens the NVIDIA Control Panel.
- **Newer AMD cards** (RX 5000 and later, recent Ryzen graphics) no longer
  get a black screen with no boot screen during the first update. PCs that
  were stuck on the low resolution safe mode get their normal graphics
  back.
- **Updates you can trust.** An update always ends on the newest version,
  even when a new one comes out during the download. Updates no longer stop
  halfway, and a PC that was left half updated repairs itself (also sent as
  an urgent update on November 20). Check for updates always gives an
  answer, also right after the install. Ubuntu updates now come from a
  server in your country first, with the others as backup.
- **Less memory.** About 850 MB at idle, down from about 1 GB. The Store,
  Settings, Clock, Task Manager and File Explorer use clearly less.
- **Raye Store:** Affinity, TikTok LIVE Studio and rekordbox, and searching
  for a DJ app also shows Mixxx. 14 more Windows programs, each one
  installed and tried first (foobar2000, ShareX, WinMerge, SumatraPDF,
  iTunes, the EA app and more). The Library lists only the apps you
  installed, Get updates installs app updates right away, the Store has its
  own settings page and Windows-style keyboard shortcuts (F1 lists them).
  Synaptic is gone: the Store does its job.
- **Windows programs** open and save files with Raye's own window, starting
  in Documents. They see your webcam, get a built-in MIDI synth and a Print
  to PDF printer, and get what they need the first time they start (Visual
  Basic 6, .NET 6 to 9 and more). Task Manager shows each one under its own
  name and icon.
- **Safe by default:** the firewall is on, each Wi-Fi network gets a private
  hardware address, and encrypted DNS is one click away in the network
  properties. OpenVPN files (.ovpn) can be added in Settings > VPN.
- **Sleep that doesn't break things.** If a PC does not wake up from sleep
  twice in a row, Raye turns sleep off and says so; closing the lid then
  locks the PC and turns off the screen. Settings > System > Power turns it
  back on.
- **Clock** alarms wake the PC from sleep when the PC allows it, and say so
  plainly when it doesn't. The calendar under the taskbar clock has an
  "Alarms & clock" button.
- **More Settings, like Windows 11:** Storage Sense on a schedule, Do not
  disturb during set hours, smaller taskbar buttons, find the pointer with
  Ctrl, a keyboard layout per window, spelling, and more.
- **Setup** says when the processor is too old for some apps and games
  (without stopping the install), Try Raye never touches the PC's own swap,
  and the new system uses the Ubuntu server of the country you pick.
- **Smaller fixes:** taskbar buttons, Start and the clock take clicks right
  to the screen edge and corners, maximize no longer glitches, the Merge
  folders window in File Explorer is fixed, and Chromebooks (Intel and AMD)
  get their top row of keys mapped.

## Known issues

- Memory at idle is about 850 MB (up to 1 GB right after the first sign-in),
  not yet the 600 to 700 MB we aim for in the final 1.0.
- The NVIDIA game speed fix is tested on our test machines, not yet by us on
  a real NVIDIA card. If games are still slow, tell us.
- Hyprland is new in this beta and was tested mostly in virtual machines.
  After switching desktops with automatic sign-in, the password store
  (KWallet) may stay locked until you unlock it.
- The new Raye kernel is not in this beta yet; it comes in a later update.
- The release name does not show in the boot menu yet, only in Settings >
  About and on the sign-in screen.
- On a PC updated from an earlier beta, Synaptic can show under "Recently
  added" in Start for about 15 minutes, until Raye Update removes it.
- In the Store Library, Get updates says nothing when there is nothing to
  update.
- Some older AMD cards (RX 400 and 500 series) can still start at a low
  resolution with low frame rates on some PCs. We are still working on it.
- Not every Windows program runs, and apps built only for the Microsoft
  Store cannot run at all. Programs that also exist for Raye (Discord,
  Steam) are better installed from the Raye Store.

## Report a problem

Tell us on Discord, https://discord.gg/TrxhUkabyB, or write to
bonjour@rayelinux.com. Say what computer you have, what you did, what you
expected and what happened. A photo of the screen helps.

## Before: Raye Linux 1.0 Beta Brocken (November 19, 2026)

The first beta of Raye Linux 1.0: a desktop laid out like Windows 11, drawn
in Raye's own colors, with updates that install themselves. It is a beta.
Install it on a spare computer or next to your current system, not on the
only machine you depend on. A 0.5 Beta already installed gets all of this
through Raye Update; the new installer only matters for new installs.

### New in 1.0 Beta Brocken

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
- **Reviews in the Raye Store**: each app's page shows its stars and what
  people say about it, and once an app is installed you can rate it and
  write your own review. Reviews are shared with other Linux app stores.
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
- **Try Raye Linux without installing**: the USB menu has a new choice that
  opens the desktop straight from the stick, without Setup popping up.
  Nothing on the PC changes.
- **Replace and keep your files**: when Raye replaces Windows or another
  system, Setup can bring your Desktop, Documents, Downloads, Music,
  Pictures and Videos along. It checks there is room first and asks before
  it deletes anything.
- **Virtual machines**: Raye now comes with the VirtualBox and VMware guest
  tools, and the PC stays awake while Setup installs.
- **The web apps** you install from your browser and pin to the taskbar keep
  their own icon and name.
- Ctrl+Win+Enter turns the screen reader on or off.

Raye Linux is based on Ubuntu. It is not affiliated with or endorsed by
Canonical Ltd.
