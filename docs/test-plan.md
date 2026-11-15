# Test plan

What to check on every ISO before it goes anywhere. The test machine is
the test VM: UEFI with Microsoft keys (Secure Boot on), a TPM 2.0,
4 GB of RAM and a blank 40 GB disk. Tick each line, note what fails.

## Live session

- [ ] Boots with Secure Boot on: shim, then the Raye boot menu, then the
      Raye boot screen (eye centred above the dots)
- [ ] Plasma opens: Raye wallpaper, 48 px bar, Start with the eye,
      Files / Firefox / Store / Settings pinned, no Discover
- [ ] Tray shows network, sound, battery; the rest is under the arrow
- [ ] Wired network is up (`nmcli -t dev` says connected)
- [ ] "Welcome to Raye Linux" window, Try / Install
- [ ] Konsole: tabs on top, no menu bar, Cascadia Mono, Raye colours
- [ ] `fastfetch` shows the eye and "Raye Linux 0.5 Beta Alpenglow"
- [ ] French entry of the boot menu gives a French session

## Installer

- [ ] No BitLocker / Windows warning on a blank disk
- [ ] Language, then keyboard
- [ ] Wi-Fi page: list of networks (VM: none, the page says online);
      time zone set from the location
- [ ] Erase disk, btrfs, swap file; tick **Encrypt**, set a passphrase
- [ ] Account page
- [ ] Install runs to the end, dark slideshow without a light frame
- [ ] Restart: the installed system starts, even with the ISO still in

## First boot

- [ ] With the TPM: no passphrase asked (clevis unlocks)
- [ ] Without the TPM (remove tpmstate0): passphrase asked, works; the
      recovery key from the home folder works too
- [ ] GRUB stays hidden
- [ ] SDDM login screen, on Wayland, Raye wallpaper
- [ ] Recovery key shown by raye-first-run at first login; the key file is
      `~/.local/share/raye/recovery-key` (0600), NOT a text file in home
- [ ] Tray tidied after the first login
- [ ] `snapper list` shows a config for / once something was installed
- [ ] `apt update` works against Ubuntu, Mozilla and the Raye repo; no
      proxy left in /etc/apt/apt.conf.d
- [ ] A software source can be added: `sudo add-apt-repository -n
      ppa:tatokis/ckb-next` adds it for the **resolute** series (not
      "raye"), `sudo add-apt-repository -r -n ppa:tatokis/ckb-next` takes
      it away, and Synaptic's Settings > Repositories dialog opens.
      `NoDistroTemplateException` means the python-apt template is gone;
      `tests/test_apt_template.sh --iso <iso>` says so before the ISO
      leaves. (software-properties-gtk is not shipped, so there is no
      "Software & Updates" window to try.)
- [ ] `unattended-upgrade --dry-run -d` lists the Ubuntu security origin

## Raye apps

- [ ] Settings: categories, cards open the Plasma pages inside the window
- [ ] Settings > Raye Update: status, "Check for updates" works without a
      password
- [ ] Settings > Device security: Secure Boot on, TPM present, encrypted
- [ ] Settings > Drivers, Gaming (MangoHud switch, Windows programs list)
- [ ] Win+I opens Raye Settings
- [ ] Store: catalogue loads, search works, install and remove a Flathub
      app without a password, Library shows it
- [ ] `raye-update status`; after `sudo raye-update auto` with updates
      pending, the "Updates are ready" notification shows
- [ ] Logout screen offers "Install updates and restart"; the restart
      installs them, with an apt snapshot before

## Windows apps

- [ ] Double-click an .exe: offer to fetch the Microsoft pieces, then it
      runs in ~/.local/share/raye/windows/<name>

## Crash

- [ ] `echo c | sudo tee /proc/sysrq-trigger`: crash screen, restart after
      30 s on its own
