#!/bin/bash
# Issue FB00/0100 SetLightEffect on the 4 keyboard zones (LEDZ=04..07).
# The painter triggers when LEBR matches current KBBR (the LEBR=current_KBBR
# trick); when LEBR=05, the painter forces KBBR=5 and the panel blanks until
# the next Fn+brightness press.
#
# Run AFTER staging colors with pure_color_test.sh.
#
# Usage: sudo ./non_blanking_lighteffect_test.sh [lebr]   # default 00
set -u
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -e /proc/acpi/call ] || modprobe acpi_call
LEBR=${1:-00}

mk_buf() {
    local b="0x$1,0x$2,0x$3,0x$4,0x$5,0x$6,0x$7,0x$8,0x$9,0x${10},0x${11},0x${12}"
    for _ in $(seq 1 20); do b="$b,0x00"; done
    echo "{$b}"
}

read_kbbr() {
    python3 -c "
import mmap, os
fd = os.open('/dev/mem', os.O_RDONLY)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ, offset=0xFE708000)
print(m[0x30D])
m.close(); os.close(fd)
"
}

KBBR_PRE=$(read_kbbr)
echo "FB00/0100 LightEffect on LEDZ=04..07 with LEBR=$LEBR"
echo "  KBBR before = $KBBR_PRE  (5=off, 0=max)"

if [ "$KBBR_PRE" = "5" ]; then
    echo "!! Panel is OFF. Wake it first (Fn+brightness)."
    exit 1
fi

# For each keyboard zone, issue FB00/0100 LETY=01 LSPD=02 LEBR=$LEBR
# Per the canonical packet from test_blank_t3: byte order is
#   00 FB 00 01 LEDZ ?? ?? ?? LETY LSPD LEBR ??
for LEDZ in 04 05 06 07; do
    BUF=$(mk_buf 00 FB 00 01 $LEDZ 00 00 00 01 02 $LEBR 00)
    echo "  [$(date +%H:%M:%S.%3N)] LEDZ=$LEDZ LETY=01 LEBR=$LEBR"
    echo "\\_SB_.MIAP.WSAA 0x0 $BUF" > /proc/acpi/call
    tr -d '\0' < /proc/acpi/call > /dev/null
done

KBBR_POST=$(read_kbbr)
echo
echo "  KBBR after = $KBBR_POST  (was $KBBR_PRE)"
echo "  WATCH KEYBOARD: did colors change without going dark?"
