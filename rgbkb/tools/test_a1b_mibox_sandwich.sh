#!/bin/bash
# test_a1b_mibox_sandwich.sh — second discriminating test for A1.
#
# Mi Gaming Box's quanta_KBC handler (per Ghidra) does, per single zone:
#   SetLightEffect(LETY=N) -> SetColour(C0Z=color) -> SetLightEffect(LETY=N)
# i.e. the SAME LETY both times, with the colour stage between.
#
# test_a1 tested a different pattern: stage all C-regs first, THEN issue 4×
# bare LightEffect(LETY=N). That failed. But the Mi Gaming Box pattern
# wraps the SetColour in TWO LightEffect calls and uses the target LETY
# from the start — never going through LETY=01.
#
# This test runs the Mi Gaming Box per-zone sandwich for each of the 4
# keyboard zones with LETY=02 (breath) and observes whether the panel
# transitions to red and breathes WITHOUT a static prepass.
#
# Run: sudo bash ~/rgb-test/test_a1b_mibox_sandwich.sh

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
[ "$KBBR" = "5" ] && { echo "panel off (KBBR=5). Press Fn+brightness once and re-run." >&2; exit 1; }
LEBR=$(printf '%02X' "$KBBR")
echo "[setup] KBBR=$KBBR (LEBR=$LEBR)"

mk_buf() {
    local b="0x$1,0x$2,0x$3,0x$4,0x$5,0x$6,0x$7,0x$8,0x$9,0x${10},0x${11},0x${12}"
    for _ in $(seq 1 20); do b="$b,0x00"; done
    echo "{$b}"
}
send() { echo "$1" > "$WSAA"; tr -d '\0' < "$WSAA" > /dev/null; }
stage_c() { send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 01 01 $1 02 00 00 $2 $3 $4 00)"; }
lighteffect() { send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 00 01 $1 00 00 00 $2 02 $LEBR 00)"; }

RGBKB="$(dirname "$0")/../rgbkb"

echo "[step 1] baseline: solid WHITE via rgbkb"
"$RGBKB" solid white >/dev/null
sleep 2

echo "[step 2] for each LEDZ 04..07: LightEffect(LETY=02) -> SetColour(C0Z=red) -> LightEffect(LETY=02)"
for ledz in 04 05 06 07; do
    lighteffect $ledz 02
    stage_c 01 FF 00 00
    lighteffect $ledz 02
done

echo "[observe] watching for 4 seconds..."
sleep 4

echo "[verify]"
read_field() { echo "$1" > "$WSAA"; tr -d '\0' < "$WSAA"; }
echo "  LETY = $(read_field '\_SB_.PCI0.LPCB.EC0.LETY')   (expect 0x2)"
echo "  C0Z R = $(read_field '\_SB_.PCI0.LPCB.EC0.C0ZR')   (expect 0xff)"
echo "  KBBR = $(read_kbbr)   (expect $KBBR)"

echo
echo "REPORT:"
echo "  PASS    — panel turned RED and is breathing"
echo "  FAIL    — panel is still WHITE (steady or breathing white)"
echo "  PARTIAL — panel is RED but not animating, or animating but wrong color"
