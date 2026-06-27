#!/bin/bash
# test_a2_ledz_creg_map.sh — empirically map LEDZ -> C-register(s).
#
# The DSDT FA00/0100 GET handler pairs C-regs by 2: {C0,C1}, {C2,C3}, {C4,C5},
# {C6,C7}. This suggests the painter pairs them too. Mi has 4 hardware zones
# and 8 C-regs, so likely 1:1 zone:pair mapping. We don't know which pair
# corresponds to which zone — currently rgbkb's `apply_zone_override` brute-
# forces by staging all 8 C-regs to the new color, which tramples the others.
#
# Run: sudo bash ~/rgb-test/test_a2_ledz_creg_map.sh
#
# Procedure:
#   1. Stage 8 distinct colors into C0Z..C7Z.
#   2. Trigger LETY=01 paint on all 4 keyboard LEDZ (04..07) in sequence.
#   3. Observe the physical color on each of the 4 zones.
#   4. From the table below, infer the LEDZ -> C-reg mapping.
#
# Color key:
#   C0Z = RED      (FF 00 00)
#   C1Z = GREEN    (00 FF 00)
#   C2Z = BLUE     (00 00 FF)
#   C3Z = YELLOW   (FF FF 00)
#   C4Z = CYAN     (00 FF FF)
#   C5Z = MAGENTA  (FF 00 FF)
#   C6Z = WHITE    (FF FF FF)
#   C7Z = ORANGE   (FF 80 00)
#
# Physical zones (left→right with hotkey bar on the left edge):
#   bar       (LEDZ=04)
#   kb-left   (LEDZ=05)
#   kb-mid    (LEDZ=06)
#   kb-right  (LEDZ=07)
#
# After running, REPORT the 4 colors observed (one per physical zone).
# If a zone shows a blend or animates between two colors → that LEDZ reads
# from a PAIR (and pair members differ). If a zone shows a single solid
# color → that LEDZ reads from one C-reg, or both members of the pair are
# coincidentally that color.

set -u
WSAA=/proc/acpi/call

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo bash $0" >&2; exit 1; }
[ -e "$WSAA" ] || modprobe acpi_call

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
if [ "$KBBR" = "5" ]; then
    echo "panel is OFF (KBBR=5). press Fn+keyboard-brightness once to wake, then re-run." >&2
    exit 1
fi
LEBR=$(printf '%02X' "$KBBR")
echo "[setup] KBBR=$KBBR (LEBR=$LEBR)"

mk_buf() {
    local b="0x$1,0x$2,0x$3,0x$4,0x$5,0x$6,0x$7,0x$8,0x$9,0x${10},0x${11},0x${12}"
    for _ in $(seq 1 20); do b="$b,0x00"; done
    echo "{$b}"
}

send() { echo "$1" > "$WSAA"; tr -d '\0' < "$WSAA" > /dev/null; }
stage_c() { send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 01 01 $1 02 00 00 $2 $3 $4 00)"; }

echo "[stage] 8 distinct colors into C0Z..C7Z"
stage_c 01 FF 00 00   # C0Z = RED
stage_c 02 00 FF 00   # C1Z = GREEN
stage_c 03 00 00 FF   # C2Z = BLUE
stage_c 04 FF FF 00   # C3Z = YELLOW
stage_c 05 00 FF FF   # C4Z = CYAN
stage_c 06 FF 00 FF   # C5Z = MAGENTA
stage_c 07 FF FF FF   # C6Z = WHITE
stage_c 08 FF 80 00   # C7Z = ORANGE

echo "[paint] LETY=01 on LEDZ=04..07 in sequence"
for ledz in 04 05 06 07; do
    send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 00 01 $ledz 00 00 00 01 02 $LEBR 00)"
    sleep 0.1
done

echo
echo "Observe the panel and REPORT the color on each physical zone:"
echo "  bar      (LEDZ=04) = ?"
echo "  kb-left  (LEDZ=05) = ?"
echo "  kb-mid   (LEDZ=06) = ?"
echo "  kb-right (LEDZ=07) = ?"
echo
echo "Color key: red green blue yellow cyan magenta white orange"
echo "(if the zone shows a blend or animates between two, say so — indicates"
echo " that LEDZ reads a C-reg PAIR rather than a single C-reg)"
