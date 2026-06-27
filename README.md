# mi-tm1806-tools

Linux tools for the Xiaomi Mi Gaming Laptop 15.6 (TIMI **TM1806**, 2019).

Four pieces, from lowest to highest level:

- **`driver/`** — Linux kernel module. Registers the 4-zone keyboard as `/sys/class/leds/mi_tm1806::kbd_*` with a **store-and-commit** model for flicker-free updates and sysfs interface.
- **`rgbkb/`** — Bash CLI. Paints colours and firmware effects via `/proc/acpi/call` (acpi_call).
- **`effects/`** — Preset launcher + visual editor. 7 built-in flashy effects, a JSON preset system, and a PyQt5 GUI for composing per-zone colour sequences.
- **`hotkey/`** — Python daemon that wires M1–M5 + Fan macro keys via ACPI WMI events (these keys never reach `/dev/input`).

Plus two integrations:

- **`integrations/openrgb-plugin/`** — OpenRGB plugin: the keyboard appears alongside USB peripherals in the OpenRGB GUI, with a preset-player tab.
- **`integrations/claude-code/`** — Claude Code hook that uses the bar zone as a session-status indicator.

This is documentation for hackers who own this exact hardware and want to control it from Linux. It is not a general-purpose utility.

## Quanta vs. XMG/Clevo on the same chip

The keyboard controller is an ITE 8910 (`USB 048d:8910`) — the same chip used in XMG and Clevo laptops. Reverse-engineering of the XMG/Clevo flavor is documented at:
<https://chocapikk.com/posts/2026/reverse-engineering-ite8910-keyboard-rgb/>

But the firmware on the Quanta-built Mi laptop speaks a **different protocol**: ACPI **WSAA** via the WMI bus, not HID feature reports. tuxedo-drivers' `ite_829x` binds to the device on Mi hardware but every write is silently dropped at the firmware level. So this repo's tools are not "yet another ITE 8910 driver" — they're for the Quanta WSAA flavor specifically.

## Requirements

- Linux 6.10+ (for `/dev/mem` mmap of EMEM under `STRICT_DEVMEM`, and for kernel-module build)
- `acpi_call` DKMS module loaded (for the Bash CLI and hotkey daemon; not needed for the kernel driver)
- root (acpi_call's `/proc/acpi/call` is mode-600 root; EMEM mmap needs CAP_SYS_RAWIO; kernel module insmod/rmmod needs root)
- Secure Boot disabled, OR modules signed with an MOK-enrolled key
- Python 3.10+, `python3-evdev` (for hotkey daemon), `python3-pyqt5` (for effects editor)
- `acpid` (for the hotkey daemon — provides `acpi_listen` to receive WMI events as netlink messages)

## Usage

### Kernel driver (`driver/`)

Flicker-free store-and-commit model. All writes are buffered; a single `commit` attribute batch-paints all zones simultaneously:

```sh
cd driver && make && sudo insmod mi-tm1806-led.ko

# Write colours (no EC calls, no flicker)
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity

# Configure effect + speed
echo 2 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/effect

# Atomically paint all 4 zones — no sequential wipe
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/commit
```

See [`driver/README.md`](driver/README.md) for full usage, DKMS setup, and design rationale.

### Backlight CLI (`rgbkb/`)

The CLI is a single Bash script. From the repo root:

```
sudo ./rgbkb/rgbkb solid     red
sudo ./rgbkb/rgbkb breath    blue       --speed 1
sudo ./rgbkb/rgbkb wave      cyan       --speed 2
sudo ./rgbkb/rgbkb colorful  red blue   --speed 2
sudo ./rgbkb/rgbkb zone      kb-mid     yellow
sudo ./rgbkb/rgbkb brightness 2          # 0=max, 5=off
sudo ./rgbkb/rgbkb status                # dump EC state
```

### Effects (`effects/`)

Flashy presets and a visual composer:

```sh
# Built-in effects
sudo ./effects/rgbkb-effects rainbow   # spectrum cycle
sudo ./effects/rgbkb-effects police    # red/blue alternating zones
sudo ./effects/rgbkb-effects disco     # random colours + modes
sudo ./effects/rgbkb-effects all       # cycle through all 7 effects

# Custom presets
sudo ./effects/rgbkb-effects preset my-effect

# Visual editor
python3 ./effects/editor.py
```

See [`effects/README.md`](effects/README.md) for full documentation.

### Macro-key daemon (`hotkey/`)

See [`hotkey/README.md`](hotkey/README.md) for setup.

## Known limitations

- **Panel can't be woken from `KBBR=5` by software.** Press Fn+keyboard-brightness once after a cold boot; after that, everything works.
- **Hardware-specific.** Tested only on TM1806 with BIOS XMGCF5R0P0202. The WMI GUID, EMEM physical address, KBBR offset, and zone mapping are all DSDT-derived and may differ on other TIMI models or after a BIOS update.

## Layout

```
driver/                  Linux kernel module (LED classdev + WMI)
  mi-tm1806-led.c
  Makefile / dkms.conf
  README.md

rgbkb/                   Bash CLI for the 4-zone backlight
  rgbkb                  the CLI
  tools/                 diagnostic + validation scripts
  README.md

effects/                 Preset launcher + visual editor
  rgbkb-effects          7 built-in effects + preset player
  editor.py              PyQt5 visual composer
  presets/               JSON preset files
  README.md

hotkey/                  Python ACPI-WMI daemon for M1–M5 + Fan keys
  daemon.py / README.md

integrations/
  openrgb-plugin/        OpenRGB plugin (device + preset-player tab)
  claude-code/           Claude Code keyboard status indicator

docs/
  architecture.md        how the WSAA protocol is wired together
  DSDT-extracts.md       relevant _Q-handlers, MIAP namespace, EMEM regions
```

## Credits

- **chocapikk** — broader ITE 8910 reverse-engineering blog post (XMG/Clevo flavor)
- **TUXEDO drivers** team — `ite_829x` binding logic
- **OpenRGB** — CalcProgrammer1's cross-platform RGB control

## Status

Not yet on GitHub or any registry. Run from a local clone. License: MIT (see `LICENSE`).
