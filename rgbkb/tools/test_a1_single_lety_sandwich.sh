#!/bin/bash
# test_a1_single_lety_sandwich.sh — discriminating test for A1 band-aid.
#
# Hypothesis: the two-pass (4× LETY=01 then 4× LETY=N) in rgbkb apply_uniform
# is unnecessary with LEBR=current_KBBR. A single 4× LETY=N pass after staging
# should both refresh from C-regs AND start animating in mode N.
#
# Old reasoning held under LEBR=05 (panel forced off) — couldn't see whether
# LETY=N painted because panel was dark. With LEBR=current_KBBR, panel stays
# lit so we can observe directly.
#
# The DSDT handler for FB00/0100 reads only LETY/LSPD/LEBR/LEDZ — no per-mode
# color parameter. Same paint trigger should fire regardless of LETY.
#
# Run as: sudo bash ~/rgb-test/test_a1_single_lety_sandwich.sh
#
# Procedure:
#   1. Establish known baseline: solid white via current rgbkb (two-pass not used; LETY=01 only).
#   2. Stage all 8 C-regs to RED via FB00/0101.
#   3. Single 4× FB00/0100 LETY=02 (breath) on LEDZ=04..07 with LEBR=current_KBBR.
#   4. Pause 4 seconds — observe panel.
#
# Expected outcomes:
#   PASS — panel transitions to red and starts breathing (breath red anim).
#          → Two-pass band-aid is unnecessary; rgbkb can drop the LETY=01 prepass.
#   FAIL — panel stays white (or shows white breathing).
#          → Two-pass is needed; some EC-internal reason animated modes don't
#            refresh from C-regs. Keep the band-aid as documented.
#   PARTIAL — panel turns red but doesn't animate.
#          → Refresh works but mode-switch needs a separate trigger.

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
echo "[setup] KBBR=$KBBR (LEBR will be $LEBR)"

mk_buf() {
    local b="0x$1,0x$2,0x$3,0x$4,0x$5,0x$6,0x$7,0x$8,0x$9,0x${10},0x${11},0x${12}"
    for _ in $(seq 1 20); do b="$b,0x00"; done
    echo "{$b}"
}

send() { echo "$1" > "$WSAA"; tr -d '\0' < "$WSAA" > /dev/null; }
stage_c() { send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 01 01 $1 02 00 00 $2 $3 $4 00)"; }

RGBKB="$(dirname "$0")/../rgbkb"

echo "[step 1] baseline: solid WHITE via existing rgbkb (LETY=01 only)"
"$RGBKB" solid white >/dev/null
sleep 2

echo "[step 2] stage 8 C-regs to RED (FF 00 00)"
for dt2a in 01 02 03 04 05 06 07 08; do
    stage_c $dt2a FF 00 00
done

echo "[step 3] single-pass: 4× FB00/0100 LETY=02 (breath) on LEDZ=04..07, LEBR=$LEBR"
for ledz in 04 05 06 07; do
    send "\\_SB_.MIAP.WSAA 0x0 $(mk_buf 00 FB 00 01 $ledz 00 00 00 02 02 $LEBR 00)"
done

echo "[observe] watching for 4 seconds..."
sleep 4

echo "[verify] EC fields after test:"
read_field() { echo "$1" > "$WSAA"; tr -d '\0' < "$WSAA"; }
echo "  LETY = $(read_field '\_SB_.PCI0.LPCB.EC0.LETY')   (expect 0x2)"
echo "  LSPD = $(read_field '\_SB_.PCI0.LPCB.EC0.LSPD')"
echo "  LEBR = $(read_field '\_SB_.PCI0.LPCB.EC0.LEBR')"
echo "  KBBR = $(read_kbbr)   (expect unchanged: $KBBR)"

echo
echo "REPORT what you saw:"
echo "  PASS    — panel turned RED and is breathing"
echo "  FAIL    — panel is still WHITE (steady or breathing white)"
echo "  PARTIAL — panel is RED but not animating (steady red)"
echo "  OTHER   — describe"
