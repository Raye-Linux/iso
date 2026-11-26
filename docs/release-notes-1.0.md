# Raye Linux 1.0

The first stable release of Raye Linux, out November 26, 2026. It brings
the Raye kernel, Raye Proton for games, a newer Windows layer, support for
older PCs, a Raye account that follows you, Raye Insider update channels,
four new languages and a new look.

Français : https://dl.rayelinux.com/iso/1.0/release-notes-1.0.fr.md

## Update or install

- **Already on Raye (0.5 Beta or a 1.0 Beta)?** You don't need the new
  download. Raye Update brings 1.0 by itself. To get it now, open
  Settings > Raye Update and click Check for updates, then restart when it
  asks. The update installs while the PC restarts; leave it on until the
  desktop is back.
- **New install:** download the image from https://rayelinux.com/en/download/,
  check it, and write it to a USB stick of 8 GB or more with Rufus (DD Image
  mode) or balenaEtcher. Start the computer from the stick (often F12, F11,
  F8 or Esc at power on). The stick opens Try Raye, with an Install icon on
  the desktop.

## New in Raye Linux 1.0

- **The Raye kernel.** CachyOS and XanMod patches plus Raye's own tuning,
  signed for Secure Boot, and open source. It replaces Ubuntu's kernel. On a
  PC with Secure Boot on, Raye asks once at startup to enroll its key (a
  6-digit code on a blue screen); Settings can do it later too. It is ready
  for Easy Anti-Cheat v2: we are sending our kernel key to Epic.
- **Raye Proton for Steam.** GE-Proton built by Raye from its sources, with
  Steam's own bridge, so Steamworks games can work. Steam uses it by default
  on a new setup, never against a choice you already made. Steam also sees
  your other drives.
- **A newer Windows layer** (Wine 11.22). Windows programs install silently
  with one real progress bar, see your drives, printers, network and ports,
  and the Windows programs page lists what you installed from the Store.
  When a program cannot run, Raye says so plainly.
- **Older PCs.** Raye starts in legacy BIOS mode (MBR disks too), on older
  processors like the Core 2 Duo, and with 2 to 4 GB of memory, where a
  light mode turns itself on. Memory at idle stays about the same on every
  PC, and the PC slows down a little instead of freezing when memory runs
  out.
- **More hardware.** More Wi-Fi drivers (Broadcom and others) install by
  themselves when a device needs them. New Printers & scanners page, a Scan
  app, and longer battery life on laptops.
- **Desktop.** The taskbar goes on any edge of the screen, its icons on the
  left or in the center, at the size you want. Wobbly windows are one switch
  in Settings. Hyprland is smoother, has a complete guide, and other
  Hyprland setups install in one step (and you can always go back to
  Raye's). WireGuard VPN is one click. An encrypted disk now has a real Raye
  unlock screen at startup.
- **Raye account.** Your settings follow you to every PC, with public
  profiles, badges and two-step sign-in on the new account website.
- **Raye Insider.** Settings > Raye Update has the Public Beta, Beta and Dev
  update channels. Leave any time: nothing is downgraded.
- **Raye Community, beta.** Raye's own chat, on the website and in Raye
  Linux, with your Raye account, roles, moderation and friends. It is an
  early beta: channels, images, private messages and tickets come in 1.1.
- **Languages.** Spanish, German, Brazilian Portuguese and Italian join
  English and French.
- **For developers.** Settings > System > Advanced has developer options and
  a local device portal.
- **New look.** A new Raye logo everywhere and a new boot animation.
- **Setup.** The stick starts in Try Raye with an Install icon, the boot menu
  is in English, and Setup opens full screen.

## Known issues

- Older AMD cards (RX 400 and 500 series) that fail to show the desktop
  switch to a simpler display mode by themselves; we could not try this on
  those cards yet. The flicker some NVIDIA cards show at 144 Hz is not fixed
  yet: if your PC has it, send us its logs (Settings > System > Advanced).
- A Steamworks game with Raye Proton was not yet tried with a real Steam
  account. If one fails, pick GE-Proton or Proton for that game in its
  Steam properties, and tell us.
- With the taskbar on the left or right side and its icons set to Center,
  the icons stay at the top. Desktop icons can sit under a taskbar on the
  left. A second screen does not get the side taskbar yet.
- Raye Community is a beta: expect missing features.
- Not every Windows program runs, and apps built only for the Microsoft
  Store cannot run at all.

## Report a problem

Tell us on Discord, https://discord.gg/TrxhUkabyB, or write to
bonjour@rayelinux.com. Say what computer you have, what you did, what you
expected and what happened. A photo of the screen helps.

Raye Linux is based on Ubuntu. It is not affiliated with or endorsed by
Canonical Ltd.
