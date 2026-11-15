# Raye Linux ISO

The build of the Raye Linux live image, and the packages that turn a plain
Ubuntu base into Raye (`packages/`): the archive keyring, the base system
settings, the desktop, gaming and Windows-apps sets, and the tuning.

- `build.sh` builds the packages and the image
- `config/` what goes into the image
- `boot/` the boot menu
- `packages/` the Raye base packages
- `tools/` release and test tools
- `VERSION` the release number, which every other repo mirrors

## Build

On a Debian or Ubuntu machine (a VM is fine; the build needs real mounts):

    sudo apt install --no-install-recommends mmdebstrap ubuntu-keyring aptly \
        squashfs-tools xorriso mtools dosfstools debhelper build-essential \
        apt-cacher-ng nginx-light
    git clone https://github.com/Raye-Linux/iso
    git clone https://github.com/Raye-Linux/theme
    git clone https://github.com/Raye-Linux/installer
    cd iso && sudo ./build.sh

`./build.sh packages` rebuilds only the Raye packages, `./build.sh iso`
redoes the image. The image boots on UEFI, with Secure Boot on or off.

## Test

    tools/raye-tests              # every test suite of the repos found next to this one
    tools/raye-tests list         # what it would run

## Publishing

`tools/publishing.md` explains the release tools. Settings are in
`tools/release.conf`; the values for one machine go in
`tools/release.local.conf`, which is not in git.

## License

GPL-3.0-or-later (`LICENSE`).

## Links

- Website: https://rayelinux.com
- Discord: https://discord.gg/TrxhUkabyB (questions, bug reports, news)
