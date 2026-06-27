#!/bin/bash
# Paint the keyboard a uniform color WITHOUT Fn. Combines:
#   1. Stage colors via FB00/0101 to all 8 C-registers
#   2. Trigger paint via FB00/0100 LightEffect on LEDZ=04..07
#      with LEBR = CURRENT KBBR (preserves brightness, doesn't blank)
#
# This is the working Fn-bypass discovered 2026-05-10.
#
# Usage: sudo ./paint_no_fn.sh <color_name|RR GG BB>
set -u
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -e /proc/acpi/call ] || modprobe acpi_call

case "${1,,:-green}" in
    red)     R=FF; G=00; B=00 ;;
    green)   R=00; G=FF; B=00 ;;
    blue)    R=00; G=00; B=FF ;;
    yellow)  R=FF; G=FF; B=00 ;;
    cyan)    R=00; G=FF; B=FF ;;
    magenta) R=FF; G=00; B=FF ;;
    white)   R=FF; G=FF; B=FF ;;
    orange)  R=FF; G=80; B=00 ;;
    *) echo "usage: $0 <color_name>"; exit 1 ;;
esac

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

KBBR=$(read_kbbr)
echo "paint_no_fn: $R $G $B   current KBBR=$KBBR"
if [ "$KBBR" = "5" ]; then
    echo "!! Panel is OFF (KBBR=5). Press Fn+brightness once to wake, then re-run."
    exit 1
fi
LEBR=$(printf '%02X' "$KBBR")
echo "  using LEBR=$LEBR (matches current KBBR — won't blank)"

# Stage color in C0Z (only C-reg the static painter reads)
BUF=$(mk_buf 00 FB 01 01 01 02 00 00 $R $G $B 00)
echo "\\_SB_.MIAP.WSAA 0x0 $BUF" > /proc/acpi/call
tr -d '\0' < /proc/acpi/call > /dev/null
echo "  staged color in C0Z (only C-reg the painter reads)"

# Trigger paint on the 4 keyboard zones with LEBR=current
for LEDZ in 04 05 06 07; do
    BUF=$(mk_buf 00 FB 00 01 $LEDZ 00 00 00 01 02 $LEBR 00)
    echo "\\_SB_.MIAP.WSAA 0x0 $BUF" > /proc/acpi/call
    tr -d '\0' < /proc/acpi/call > /dev/null
done
echo "  fired LightEffect on LEDZ=04..07"

KBBR2=$(read_kbbr)
echo "  KBBR after = $KBBR2 (was $KBBR — should match)"
