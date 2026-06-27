# Architecture

How the keyboard-control surface is wired together on TM1806. This is the mental model behind both `rgbkb/` and `hotkey/`.

## Layers

```
   Userspace
   ┌─────────────────────────────────────────────────────────────┐
   │  rgbkb (Bash)             daemon.py (Python)                │
   │   │                        │                                │
   │   │  /proc/acpi/call       │  /proc/acpi/call (for _WED)    │
   │   │  /dev/mem (KBBR read)  │  acpi_listen netlink           │
   └───┼────────────────────────┼────────────────────────────────┘
       │                        │
   Kernel
   ┌───▼────────────────────────▼────────────────────────────────┐
   │  acpi_call DKMS module        ACPI subsystem (WMI bus)      │
   │   │                            │                            │
   │   │  evaluates AML method      │  surfaces _WDG / events    │
   └───┼────────────────────────────┼────────────────────────────┘
       │                            │
   ACPI / EC
   ┌───▼────────────────────────────▼────────────────────────────┐
   │  \_SB_.MIAP.WSAA   (32-byte buffer, opcodes FA00/FB00)      │
   │  \_SB_.MIAP._WED   (returns 32-byte EVBF for last notify)   │
   │  EC0 namespace: LETY, LSPD, LEBR, LEDZ, C0Z..C7Z, KBBR, ... │
   │  EMEM SystemMemory region @ 0xFE708000                      │
   └─────────────────────────────────────────────────────────────┘
```

## The two protocols

### 1. WSAA (RGB write surface)

`\_SB_.MIAP.WSAA(arg0=0, arg1=Buffer{32})` is the only useful entry point for color/effect changes. The buffer is 32 raw bytes (not ASCII-hex; the Mi Gaming Box utility builds an ASCII-hex string internally for logging, then decodes it before the WBEM `PutInstance` call):

```
offset 0..1   16-bit opcode prefix      bytes 00 FB    (i.e. 0xFB00 little-endian within the field)
offset 2..3   16-bit subcommand          bytes 00 01 / 01 01 / 00 04 — see table below
offset 4..7   four bytes                 (zone idx / commit value / etc., subcommand-dependent)
offset 8..11  LETY, LSPD, LEBR, ...      (subcommand-dependent)
offset 12+    payload + zero pad
```

The opcode prefix and subcommand are 16-bit fields decoded by the AML as `DAT0` and `DAT1`. The subcommand values appear in the table below as their 16-bit form (`0x0100`, `0x0101`, `0x0400`).

The subcommand selects which EC fields are written. Concretely on this firmware:

- `FB00 0100` (SetLightEffect): writes `LETY`, `LSPD`, `LEBR`, `LEDZ`. **Triggers paint from C-registers** when `LEDZ` is in `04..07` (keyboard zones) and `LEBR` matches current `KBBR`.
- `FB00 0101` (SetColour): writes one of `C0Z..C7Z` (selected by DT2A=01..08). Stages a 24-bit RGB triplet. Does not paint.
- `FB00 0400` (KeyboardBackLight): writes `KBBL`, `KBIT`. Master backlight on/off (`KBIT=0xFF` is safe; `KBIT=0` is asymmetric and hard to recover from).
- `FA00 0100` (GetLedStatus): returns `LCAM`, `LETY`, `LSPD`, `LEBR`, plus a pair of C-register values selected by `DT3A`. **Side-effects**: writes `LEDZ=GWF2` and `LCAM=DT3B`. So it's not a pure read.

### 2. WMI events (hotkey input surface)

The macro keys (M1–M5, Fan key, Fn+brightness, etc.) don't reach `/dev/input`. Instead the EC fires ACPI WMI notifications. On TM1806 the relevant GUIDs are:

- `B74AF83F-8B2F-4069-ACAC-36D176F62FC0` notify `0x80` — Quanta status change (M1–M5 + Fn+brightness). EVT0 group code disambiguates: `0x0200` = M-keys, `0x0100` = Fn+brightness.
- `EB2464D2-D6F5-483F-BC9C-685E89F536F6` notify `0xA2` — Fan key, mode A
- `B35609C4-7608-439B-A8F0-8F0E3ED2D04F` notify `0xA9` — Fan key, mode B

Per-key disambiguation requires reading the 32-byte EVBF buffer via `\_SB_.MIAP._WED(0x80)` since the Linux kernel's WMI bus doesn't surface the EventDetail payload to userspace for unbound GUIDs.

## Why /dev/mem for KBBR

`KBBR` (keyboard brightness register, `0x30D` within the `EMEM` operation region declared at `0xFE708000`) is the brightness state the painter reads. Reading it via WSAA is awkward (you'd have to use `FA00 0100` which has side effects), and there's no `/sys/class/leds/` entry exposed. Linux ≥6.10 with `STRICT_DEVMEM` allows `mmap` of memory regions listed in `/proc/iomem`, and `pnp 00:01` covers the EMEM range. So a 4 KiB mmap with `PROT_READ` is the cheapest reliable way to sample KBBR live.

## The painter mechanism

The EC has internal SRAM holding the "currently displayed color" for each zone. The 8 C-registers are a separate write-staging area; the painter snapshots them into per-zone SRAM only when triggered.

Triggers (verified empirically on this firmware):

| Trigger                                   | Effect                                                      |
|-------------------------------------------|-------------------------------------------------------------|
| `FB00/0100 LEDZ=04..07 LETY=01 LEBR=cur`  | Paint from `C0Z` into target zone's SRAM. Panel stays lit.  |
| `FB00/0100 LEDZ=04..07 LETY=N≠1 LEBR=cur` | Switches animation mode. Does NOT refresh from C-registers. |
| `FB00/0100 LEDZ=01 LETY=any`              | Does not trigger paint on TM1806; LEDZ=01 is the LOGO slot, which has no LED on this hardware. |
| Fn+brightness press (hardware)            | Paints from C-registers into all "pending" zones. |

Because animated modes don't refresh from C-registers, `rgbkb` issues a static prepass before switching to LETY≠1 — that's the canonical two-pass.

## Future direction: kernel module

The current stack depends on `acpi_call` (third-party DKMS) and `/dev/mem`. A small kernel-style WMI bus driver in C would eliminate both dependencies and expose a sysfs interface. Sketch:

1. `struct wmi_driver` binding to GUID `E2A89D40-784F-4E91-BE22-AE373CDEA97A`.
2. WSAA writes via `wmidev_block_set(wdev, 0, &buf)` — uses the kernel's WMI bus serialization, which arbitrates concurrent ACPI evaluators (a property `acpi_call` does not guarantee).
3. KBBR via `request_mem_region` + `ioremap` of the EMEM range.
4. Expose `struct led_classdev_mc` with multi-color subleds.

Estimated ~200–300 LOC. Distribution via DKMS or a signed module if Secure Boot is on. C is currently the practical choice; Rust-for-Linux did not yet provide bindings for `<linux/wmi.h>` or `<linux/leds.h>` as of the kernel versions tested during development (6.10–6.17).

Mainline submission would require evidence the driver is useful on more than one BIOS revision. Adding 2–3 confirmed-working TIMI/Quanta variants is a reasonable bar before approaching `platform-driver-x86`.
