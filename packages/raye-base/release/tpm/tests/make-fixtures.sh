#!/bin/sh
# Records the event logs the unit tests replay, from real boots: OVMF
# with Secure Boot and the Microsoft keys, a software TPM, the signed
# shim and GRUB, and a signed kernel that starts a tiny initramfs which
# prints the event log, PCR 7 and the Secure Boot variables on the serial
# console, then powers off.
#
#   boot "stock"  the kernel as signed by its vendor
#   boot "mok"    the same kernel signed by a throwaway key enrolled in
#                 MokList: shim logs that certificate, as it does for the
#                 Raye kernel
#   boot "dbx"    like "stock" after a new hash was appended to dbx
#
# Needs qemu-system-x86_64, swtpm, swtpm_setup, virt-fw-vars, sbsign,
# sbattach, openssl, mtools, mkfs.vfat, cpio and a static busybox.
# Paths come from the environment:
#   OVMF_CODE OVMF_VARS SHIM GRUB KERNEL BUSYBOX   (files)
#   OUT                                            (fixture folder)
set -eu
: "${OVMF_CODE:?}" "${OVMF_VARS:?}" "${SHIM:?}" "${GRUB:?}" "${KERNEL:?}" "${BUSYBOX:?}"
OUT=${OUT:-$(dirname "$0")/fixtures}
work=$(mktemp -d)
trap 'kill $(cat "$work"/swtpm.pid 2>/dev/null) 2>/dev/null; rm -rf "$work"' EXIT
mkdir -p "$OUT"

# the initramfs: dump, then power off
mkdir -p "$work/root/bin" "$work/root/proc" "$work/root/sys" "$work/root/dev"
cp "$BUSYBOX" "$work/root/bin/busybox"
cat > "$work/root/init" <<'EOF'
#!/bin/busybox sh
/bin/busybox --install -s /bin
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs none /dev
mount -t securityfs none /sys/kernel/security
mount -t efivarfs none /sys/firmware/efi/efivars
sleep 1
dump() { echo "=== $1"; base64 "$2"; echo "=== end"; }
dump log /sys/kernel/security/tpm0/binary_bios_measurements
for b in sha1 sha256; do
    echo "=== pcr7-$b $(cat /sys/class/tpm/tpm0/pcr-$b/7 2>/dev/null)"
done
for f in /sys/firmware/efi/efivars/SecureBoot-* /sys/firmware/efi/efivars/PK-* \
         /sys/firmware/efi/efivars/KEK-* /sys/firmware/efi/efivars/db-* \
         /sys/firmware/efi/efivars/dbx-* /sys/firmware/efi/efivars/MokListRT-* \
         /sys/firmware/efi/efivars/MokSBStateRT-*; do
    [ -e "$f" ] && dump "var $(basename "$f")" "$f"
done
echo "=== done"
poweroff -f
EOF
chmod 755 "$work/root/init"
(cd "$work/root" && find . | cpio -o -H newc --quiet) | gzip > "$work/initrd"

# a throwaway key that stands for the Raye boot key
openssl req -new -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=Test boot key/" \
    -keyout "$work/mok.key" -out "$work/mok.pem" 2>/dev/null
openssl x509 -in "$work/mok.pem" -outform DER -out "$OUT/mok-cert.der"
cp "$KERNEL" "$work/vmlinuz.stock"
cp "$KERNEL" "$work/vmlinuz.mok"
sbattach --remove "$work/vmlinuz.mok"
sbsign --key "$work/mok.key" --cert "$work/mok.pem" --output "$work/vmlinuz.mok" "$work/vmlinuz.mok"

esp() { # $1 kernel, $2 image
    rm -f "$2"
    mkfs.vfat -C "$2" 98304 >/dev/null
    for d in /EFI /EFI/BOOT /EFI/ubuntu /boot /boot/grub; do mmd -i "$2" "::$d"; done
    mcopy -i "$2" "$SHIM" ::/EFI/BOOT/BOOTX64.EFI
    mcopy -i "$2" "$GRUB" ::/EFI/BOOT/grubx64.efi
    printf 'set timeout=0\nmenuentry k {\n linux /vmlinuz console=ttyS0 rdinit=/init\n initrd /initrd\n}\n' > "$work/grub.cfg"
    for d in /EFI/BOOT /EFI/ubuntu /boot/grub; do mcopy -i "$2" "$work/grub.cfg" "::$d/grub.cfg"; done
    mcopy -i "$2" "$1" ::/vmlinuz
    mcopy -i "$2" "$work/initrd" ::/initrd
}

boot() { # $1 name, $2 kernel, $3 vars
    rm -rf "$work/tpm" && mkdir -p "$work/tpm"
    swtpm_setup --tpm2 --tpmstate "$work/tpm" --pcr-banks sha1,sha256 \
        --createek --create-ek-cert --create-platform-cert --lock-nvram >/dev/null 2>&1
    swtpm socket --tpm2 --tpmstate dir="$work/tpm" --daemon --pid file="$work/swtpm.pid" \
        --ctrl type=unixio,path="$work/swtpm.sock"
    esp "$2" "$work/esp.img"
    timeout 300 qemu-system-x86_64 -machine q35,smm=on -enable-kvm -m 1024 -nographic \
        -global driver=cfi.pflash01,property=secure,value=on \
        -drive if=pflash,format=raw,unit=0,file="$OVMF_CODE",readonly=on \
        -drive if=pflash,format=raw,unit=1,file="$3" \
        -drive file="$work/esp.img",format=raw,if=virtio \
        -chardev socket,id=chrtpm,path="$work/swtpm.sock" \
        -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-crb,tpmdev=tpm0 \
        -serial file:"$work/$1.serial" -monitor none -display none </dev/null || true
    kill "$(cat "$work/swtpm.pid")" 2>/dev/null || true
    python3 - "$work/$1.serial" "$OUT/$1" <<'EOF'
import base64, os, sys
text = open(sys.argv[1], "rb").read().decode("latin-1").replace("\r", "")
out = sys.argv[2]
if "=== done" not in text:
    sys.exit("the boot did not finish: see the serial log")
os.makedirs(os.path.join(out, "efivars"), exist_ok=True)
lines = text.splitlines()
pcr = {}
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("=== pcr7-"):
        bank, _, value = line[len("=== pcr7-"):].partition(" ")
        pcr[bank] = value.strip().lower()
    elif line.startswith("=== log") or line.startswith("=== var "):
        body = []
        i += 1
        while lines[i] != "=== end":
            body.append(lines[i].strip())
            i += 1
        data = base64.b64decode("".join(body))
        if line.startswith("=== log"):
            path = os.path.join(out, "binary_bios_measurements")
        else:
            path = os.path.join(out, "efivars", line[len("=== var "):].strip())
        open(path, "wb").write(data)
    i += 1
with open(os.path.join(out, "pcr7.txt"), "w") as f:
    for bank in sorted(pcr):
        f.write("%s %s\n" % (bank, pcr[bank]))
EOF
}

cp "$OVMF_VARS" "$work/vars.stock"
boot stock "$work/vmlinuz.stock" "$work/vars.stock"

cp "$OVMF_VARS" "$work/vars.mok"
virt-fw-vars -i "$work/vars.mok" -o "$work/vars.mok.new" \
    --add-mok 605dab50-e046-4300-abb6-3dd810dd8b23 "$OUT/mok-cert.der" >/dev/null
boot mok "$work/vmlinuz.mok" "$work/vars.mok.new"

cp "$OVMF_VARS" "$work/vars.dbx"
virt-fw-vars -i "$work/vars.dbx" -o "$work/vars.dbx.new" \
    --add-dbx-hash 605dab50-e046-4300-abb6-3dd810dd8b23 \
    "$(printf 'raye-tpm test entry' | sha256sum | cut -d' ' -f1)" >/dev/null
boot dbx "$work/vmlinuz.stock" "$work/vars.dbx.new"
echo "fixtures written to $OUT"
