#!/bin/sh
# Checks release/tuning/raye-min-free: the free memory the kernel keeps
# aside follows the size of the RAM, never goes up, and leaves a value set
# by hand in /etc alone.
#
#   sh release/tuning/tests/test-raye-min-free.sh
set -eu

here=$(cd "$(dirname "$0")" && pwd)
script=$here/../raye-min-free
work=$(mktemp -d "${TMPDIR:-/tmp}/raye-min-free.XXXXXX")
trap 'rm -r -f -- "$work"' EXIT INT TERM
failures=0

# /proc/zoneinfo of a PC with <dma32> and <normal> pages managed, the high
# watermarks of a kernel that kept 67584 kB aside for huge pages
zoneinfo() {
    cat > "$work/zoneinfo" <<ZONES
Node 0, zone      DMA
  pages free     3584
        boost    0
        min      17
        low      21
        high     25
        spanned  4095
        present  3999
        managed  3839
Node 0, zone    DMA32
  pages free     400000
        min      1926
        low      2407
        high     2888
        managed  $1
Node 0, zone   Normal
  pages free     900000
        min      14951
        low      18688
        high     22425
        managed  $2
Node 0, zone  Movable
  pages free     0
        min      32
        low      32
        high     32
        managed  0
ZONES
}

run() { # name, expected value left in the file, starting value
    printf '%s\n' "$3" > "$work/min_free_kbytes"
    RAYE_ZONEINFO=$work/zoneinfo RAYE_MIN_FREE_FILE=$work/min_free_kbytes \
        RAYE_SYSCTL_DIRS="$work/etc" sh "$script" > "$work/out" 2>&1 || {
        echo "FAIL $1 (exit $?): $(cat "$work/out")"; failures=$((failures + 1)); return; }
    got=$(cat "$work/min_free_kbytes")
    if [ "$got" = "$2" ]; then echo "ok   $1 ($got)"; else
        echo "FAIL $1: $got, wanted $2"; failures=$((failures + 1)); fi
}

mkdir -p "$work/etc"

# the kernel's own formula without huge pages: sqrt(16 x lowmem kB)
zoneinfo 486534 3584965     # 16 GB
run "16 GB" 16099 67584
zoneinfo 486534 3584965
run "a second run changes nothing" 16099 16099
zoneinfo 486534 563000      # 4 GB
run "4 GB" 8111 67584
zoneinfo 486534 16300000    # 64 GB
run "64 GB" 32756 67584
zoneinfo 486534 3584965
run "never raises a lower value" 9000 9000

printf 'vm.min_free_kbytes = 131072\n' > "$work/etc/80-mine.conf"
zoneinfo 486534 3584965
run "a value set in /etc wins" 67584 67584
rm "$work/etc/80-mine.conf"
printf '# vm.min_free_kbytes = 131072\n' > "$work/etc/80-mine.conf"
run "a commented line is no choice" 16099 67584

printf 'garbage\n' > "$work/zoneinfo"
run "an unreadable zoneinfo changes nothing" 67584 67584

[ "$failures" = 0 ] || { echo "$failures failed"; exit 1; }
echo "all good"
