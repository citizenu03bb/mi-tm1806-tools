#!/usr/bin/env python3
"""Test: does writing KBBR via /dev/mem trigger the painter?

Procedure:
  1. Read current KBBR. If not 5 (off), prompt user to press Fn+brightness
     until panel goes off (so we have a clear "before/after" oracle).
  2. Run rgbkb solid <color> via WSAA — stages new color in C-registers AND
     forces KBBR=5 (panel off, color staged but not painted).
  3. Write KBBR := 1 (near-max brightness) directly via /dev/mem.
  4. Hold for 5 seconds. User observes whether the panel lights up <color>
     without any Fn press.
  5. Report KBBR value over time so we know if EC overwrote it.

Outcome interpretation:
  - Panel paints <color> while KBBR=1 → BREAKTHROUGH. Painter polls EMEM.
  - Panel stays off, KBBR stays 1 → KBBR write isn't the trigger; some
    other EC state controls the painter.
  - KBBR gets immediately overwritten to 5 → EC enforces its own state;
    we'd need to find the controlling field.
"""
import mmap, os, subprocess, sys, time

EMEM_PHYS = 0xFE708000
KBBR_OFF = 0x30D
COLOR = sys.argv[1] if len(sys.argv) > 1 else "green"
TARGET_KBBR = int(sys.argv[2]) if len(sys.argv) > 2 else 1
RGBKB = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "rgbkb")


def main():
    if os.geteuid() != 0:
        print("run as root", file=sys.stderr); sys.exit(1)

    fd = os.open('/dev/mem', os.O_RDWR)
    m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                  offset=EMEM_PHYS)

    print(f"current KBBR = {m[KBBR_OFF]}  (5=off, 0=max)")
    if m[KBBR_OFF] != 5:
        print(">>> PRESS Fn+brightness until panel is OFF, then hit Enter")
        input()
        print(f"after your input, KBBR = {m[KBBR_OFF]}")
    if m[KBBR_OFF] != 5:
        print("WARN: KBBR is not 5; oracle won't be clean")

    print(f"\n[1/3] running rgbkb solid {COLOR}")
    subprocess.run([RGBKB, "solid", COLOR], capture_output=True)
    print(f"  KBBR after rgbkb = {m[KBBR_OFF]} (expect 5)")

    print(f"\n[2/3] writing KBBR := {TARGET_KBBR} via /dev/mem")
    m[KBBR_OFF] = TARGET_KBBR
    print(f"  immediate read-back = {m[KBBR_OFF]}")

    print(f"\n[3/3] holding {TARGET_KBBR}s — WATCH THE KEYBOARD NOW")
    print(f"  expecting: {COLOR} at brightness {6 - TARGET_KBBR}/5 (if painter polls EMEM)")
    for i in range(10):
        time.sleep(0.5)
        print(f"  +{(i+1)*0.5:.1f}s KBBR = {m[KBBR_OFF]}")

    m.close()
    os.close(fd)


if __name__ == "__main__":
    main()
