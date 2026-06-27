#!/bin/bash
# Pure FB00/0101 color-only test — NO FB00/0100 LightEffect writes at all.
# Stages C0Z..C7Z to a single color via SetColour; if the EC painter ever
# polls C-registers without an explicit trigger, the panel would change
# color. (Empirically it does not, on TM1806 — the panel only refreshes on
# FB00/0100 LightEffect with a keyboard LEDZ. This script demonstrates that.)
#
# Usage: sudo ./pure_color_test.sh <color_name>
set -u
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -e /proc/acpi/call ] || modprobe acpi_call

COLOR="${1:-green}"
case "${COLOR,,}" in
    red)     R=FF; G=00; B=00 ;;
    green)   R=00; G=FF; B=00 ;;
    blue)    R=00; G=00; B=FF ;;
    yellow)  R=FF; G=FF; B=00 ;;
    cyan)    R=00; G=FF; B=FF ;;
    magenta) R=FF; G=00; B=FF ;;
    white)   R=FF; G=FF; B=FF ;;
    *) echo "color: red green blue yellow cyan magenta white"; exit 1 ;;
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
echo "Pure FB00/0101 only  RGB=$R $G $B   initial KBBR=$KBBR (5=off, 0=max)"
if [ "$KBBR" = "5" ]; then
    echo "!! Panel is OFF. Press Fn+brightness ONCE to wake (KBBR will become 4), then re-run."
    exit 1
fi

# Issue FB00/0101 to all 8 C-registers using the canonical buffer.
for DT2A in 01 02 03 04 05 06 07 08; do
    BUF=$(mk_buf 00 FB 01 01 $DT2A 02 00 00 $R $G $B 00)
    echo "  [$(date +%H:%M:%S.%3N)] C$((10#$DT2A-1))Z = $R$G$B"
    echo "\\_SB_.MIAP.WSAA 0x0 $BUF" > /proc/acpi/call
    tr -d '\0' < /proc/acpi/call > /dev/null
done

KBBR2=$(read_kbbr)
echo
echo "  KBBR after = $KBBR2  (was $KBBR; should be unchanged with no FB00/0100)"
echo "  WATCH KEYBOARD: did colors change to RGB $R $G $B without you pressing anything?"
