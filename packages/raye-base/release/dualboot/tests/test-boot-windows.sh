#!/bin/sh
# tests of raye-boot-windows --check with a fake efibootmgr / findmnt
S=$(cd "$(dirname "$0")/.." && pwd)/raye-boot-windows
T=$(mktemp -d); fail=0
mk() { printf '#!/bin/sh\ncat <<"X"\n%s\nX\n' "$1" > "$T/efi"; chmod +x "$T/efi"; }
printf '#!/bin/sh\necho "$MNT"\n' > "$T/fm"; chmod +x "$T/fm"
mkdir -p "$T/byp" "$T/esp/EFI/Microsoft/Boot"
check() { want=$1; shift; got=$(EFIBOOTMGR=$T/efi BY_PARTUUID=$T/byp FINDMNT=$T/fm sh "$S" --check 2>/dev/null); rc=$?
  if [ "$want" = none ]; then [ $rc -ne 0 ] && echo "ok: $*" || { echo "FAIL: $* (got $got)"; fail=1; }
  else [ "$got" = "$want" ] && echo "ok: $*" || { echo "FAIL: $* (got '$got')"; fail=1; }; fi; }
TAB=$(printf '\t')
mk "Boot0001* Windows Boot Manager${TAB}HD(1,GPT,AAAA-1111,0x800,0x82000)/\\EFI\\Microsoft\\Boot\\bootmgfw.efi"
MNT=; export MNT
check none "Windows erased: its partition is gone"
: > "$T/byp/aaaa-1111"
check 0001 "partition exists, not mounted"
MNT=$T/esp; export MNT
check none "partition mounted but the Windows loader is gone"
: > "$T/esp/EFI/Microsoft/Boot/bootmgfw.efi"
check 0001 "partition mounted with the Windows loader"
mk "Boot0002* Windows Boot Manager${TAB}VenHw(1234)"; MNT=; export MNT
check 0002 "firmware that names no partition"
mk "Boot0003* ubuntu${TAB}HD(1,GPT,BBBB,0x800,0x82000)/\\EFI\\ubuntu\\shimx64.efi"
check none "no Windows entry at all"
exit $fail
