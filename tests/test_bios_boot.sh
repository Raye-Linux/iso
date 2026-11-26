#!/bin/bash
# Old PCs started in BIOS mode (no UEFI): the image starts in BIOS mode
# from a DVD and from a USB stick, and the system Setup installs keeps
# its GRUB up to date (grub-pc goes in, installer raye-bios-grub).
#   tests/test_bios_boot.sh
here=$(cd "$(dirname "$0")/.." && pwd)
b=$here/build.sh
cfg=$here/boot/grub/grub.cfg
bad=0
fail() { echo "FAIL: $*"; bad=1; }

# the GRUB files for BIOS come with raye-system
grep -qE '^ .*grub-pc-bin,' "$here/packages/raye-base/debian/control" || fail "raye-system does not bring grub-pc-bin"
grep -q 'die "grub-pc-bin is missing from the image: no BIOS boot"' "$b" || fail "build.sh does not refuse an image without BIOS GRUB"

# El Torito image for BIOS, with what the menu needs built in
grep -q 'grub-mkimage -O i386-pc-eltorito' "$b" || fail "no BIOS El Torito image"
mods=$(sed -n '/grub-mkimage -O i386-pc-eltorito/,/vbe/p' "$b" | tr -s ' \\\n' ' ')
for m in biosdisk iso9660 part_msdos part_gpt search normal configfile linux test font gfxterm vbe sleep reboot; do
    case " $mods " in *" $m "*) ;; *) fail "BIOS image lacks the $m module" ;; esac
done
# DVD in BIOS mode, then the UEFI image; the hybrid MBR for a USB stick
grep -q -- '-b /boot/grub/i386-pc/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info' "$b" ||
    fail "the BIOS El Torito entry is missing"
grep -q -- '--grub2-mbr "$bios/boot_hybrid.img"' "$b" || fail "no hybrid MBR: a USB stick would not start in BIOS mode"
grep -q -- '--mbr-force-bootable' "$b" || fail "the MBR partition is not marked bootable (some BIOSes skip it)"

# the menu: nothing UEFI-only runs in BIOS mode
grep -q 'search --no-floppy --set=root --file /casper/vmlinuz' "$cfg" || fail "the menu does not look for the kernel"
awk '/insmod efi_gop/ && !inif { bad = 1 } /grub_platform.*efi/ { inif = 1 } /^ *fi$/ { inif = 0 } END { exit bad }' "$cfg" ||
    fail "efi_gop is loaded outside the UEFI test"
grep -B3 'fwsetup' "$cfg" | grep -q 'grub_platform" = "efi"' || fail "fwsetup is offered in BIOS mode"

# grub-pc for the installed system, at the image's GRUB version
grep -q "dpkg-query -W -f='\${Version}' grub-pc-bin" "$b" || fail "grub-pc is not matched to the image's GRUB"
grep -q 'apt-get download -q grub-pc=$grub_version grub-gfxpayload-lists' "$b" || fail "build.sh does not carry grub-pc"
grep -q 'die "grub-pc is not in the image: BIOS installs would never update GRUB"' "$b" || fail "a missing grub-pc is not caught"

[ "$bad" = 0 ] && echo "ok: the image starts in BIOS mode and BIOS installs get grub-pc"
exit $bad
