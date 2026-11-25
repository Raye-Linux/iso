#!/bin/bash
#
# The Raye kernel in the image: the live session and the installer start
# Ubuntu's signed kernel (it boots everywhere with Secure Boot on, no key to
# enroll on a USB stick), and the Raye kernel only travels in
# /usr/share/raye/kernel/debs for the installed system, NVIDIA's modules for
# it included (an NVIDIA PC switches offline too).
#
#   tests/test_raye_kernel_in_image.sh
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
build=$here/build.sh
fail=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

block=$(sed -n '/if \[ -n "${KERNEL_DEBS:-}" \]; then/,/^    fi$/p' "$build")
[ -n "$block" ] && ok "the KERNEL_DEBS block is there" || bad "no KERNEL_DEBS block in build.sh"

# the block run on a folder of stand-in packages
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
mkdir -p "$t/k" "$t/root"
for f in linux-image-7.0.14-44r4-raye_1_amd64.deb linux-headers-7.0.14-44r4-raye_1_amd64.deb \
    linux-image-7.0.14-44r4-raye-dbg_1_amd64.deb \
    linux-modules-nvidia-580-open-7.0.14-44r4-raye_580.178.04+raye1_amd64.deb \
    linux-raye_1_amd64.deb linux-image-raye_1_amd64.deb; do : > "$t/k/$f"; done
(f() { KERNEL_DEBS=$t/k root=$t/root; eval "$block"; }; f)
got=$(ls "$t/root/usr/share/raye/kernel/debs" 2>/dev/null | tr '\n' ' ')
case "$got" in *linux-image-7.0.14-44r4-raye_1_amd64.deb*) ok "image shipped" ;; *) bad "image not shipped: $got" ;; esac
case "$got" in *linux-modules-nvidia-580-open-7.0.14-44r4-raye_*) ok "NVIDIA modules shipped" ;; *) bad "NVIDIA modules not shipped: $got" ;; esac
case "$got" in *-dbg_*) bad "debug package shipped" ;; *) ok "no debug package" ;; esac
case "$got" in *linux-raye_*|*linux-image-raye_*) bad "metapackages shipped (they come from the archive)" ;; *) ok "no metapackage" ;; esac

# the image installs no Raye kernel: the live kernel is what /boot holds
grep -nE 'apt-get install[^#]*(KERNEL_DEBS|kernel/debs|-raye)' "$build" && bad "a Raye kernel is installed in the image" ||
    ok "no Raye kernel installed in the live system"
grep -q 'cp "$root/boot/vmlinuz-$kver" "$iso/casper/vmlinuz"' "$build" && ok "live kernel taken from the image's /boot" ||
    bad "live kernel not from /boot"

exit $fail
