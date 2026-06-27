# mi-tm1806-tools

Linux user-space tools for the Xiaomi Mi Gaming Laptop 15.6 (TIMI **TM1806**, 2019).

Two pieces:

- **`hotkey/`** — Python daemon that wires up the M1–M5 + Fan macro keys via ACPI WMI events (these keys never reach `/dev/input`).
- **`rgbkb/`** — Bash CLI for the 4-zone keyboard backlight via ACPI WSAA, with a Fn-bypass trick that lets you change colors and modes.

This is documentation for hackers who own this exact hardware and want to control it from Linux. It is not a general-purpose utility.

## Quanta vs. XMG/Clevo on the same chip

The keyboard controller is an ITE 8910 (`USB 048d:8910`) — the same chip used in XMG and Clevo laptops. Reverse-engineering of the XMG/Clevo flavor is documented at:
<https://chocapikk.com/posts/2026/reverse-engineering-ite8910-keyboard-rgb/>

But the firmware on the Quanta-built Mi laptop speaks a **different protocol**: ACPI **WSAA** via the WMI bus, not HID feature reports. tuxedo-drivers' `ite_829x` binds to the device on Mi hardware but every write is silently dropped at the firmware level. So this repo's tools are not "yet another ITE 8910 driver" — they're for the Quanta WSAA flavor specifically.

## Requirements

- Linux 6.10+ (for `/dev/mem` mmap of EMEM under `STRICT_DEVMEM`; the region is exposed in `/proc/iomem` as `pnp 00:01`)
- `acpi_call` DKMS module loaded (used to invoke `\_SB_.MIAP.WSAA`)
- root (acpi_call's `/proc/acpi/call` is mode-600 root, EMEM mmap needs CAP_SYS_RAWIO)
- Secure Boot disabled, OR `acpi_call.ko` signed with an MOK-enrolled key
- Python 3.10+ with `python3-evdev` (for the hotkey daemon's optional `key` action type, uinput injection)
- `acpid` (for the hotkey daemon — provides `acpi_listen` to receive WMI events as netlink messages)

The tools are tested on TM1806 with BIOS XMGCF5R0P0202. Other TIMI models (TM1807, TM1900) have different DSDTs and are **not** supported; see "Hardware-specific" under "Known limitations" below.

## Usage

### Backlight CLI (`rgbkb/`)

The CLI is a single Bash script with no install step required. From the repo root:

```
sudo ./rgbkb/rgbkb solid     red
sudo ./rgbkb/rgbkb breath    blue       --speed 1
sudo ./rgbkb/rgbkb wave      cyan       --speed 2
sudo ./rgbkb/rgbkb colorful  red blue   --speed 2
sudo ./rgbkb/rgbkb zone      kb-mid     yellow
sudo ./rgbkb/rgbkb brightness 2          # 0=max, 5=off
sudo ./rgbkb/rgbkb status                # dump EC state
```

If you want it on `$PATH`, symlink `~/bin/rgbkb -> /path/to/repo/rgbkb/rgbkb` or copy it to `/usr/local/bin/`.

Zones: `bar` (LEDZ=04, hotkey strip on the left), `kb-left`, `kb-mid`, `kb-right` (LEDZ=05/06/07).

Colors by name: `red green blue yellow cyan magenta white orange purple pink black/off`, or 6-hex `RRGGBB`.

### Macro-key daemon (`hotkey/`)

ACPI WMI-driven. The daemon also depends on `acpi_call` (it calls `\_SB_.MIAP._WED(0x80)` to read each event's per-key payload, since the Linux WMI bus doesn't surface EventDetail to userspace for unbound GUIDs).

Set up the config and install the unit:

```
cp hotkey/config.example.toml hotkey/config.toml
$EDITOR hotkey/config.toml
sudo cp hotkey/mi-hotkey.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mi-hotkey.service
journalctl -u mi-hotkey.service -f
```

Maps M1–M5 (the 5 keys at the far left of the keyboard) and the Fan key. EVT0 group code is checked so Fn+brightness presses (which fire the same notify code) are not misdispatched.

## Known limitations

- **Panel can't be woken from `KBBR=5` by software.** Press Fn+keyboard-brightness once after a cold boot; after that, software controls everything.
- **`brightness` and KBBR-mode interaction.** Once you've issued any FB00/0100 LightEffect, the painter is in KBBR-driven brightness mode and the LEBR-sweep brightness control is silently ignored until reboot. `rgbkb brightness` reads KBBR and warns when this happens.
- **Hardware-specific.** Tested only on TM1806 with BIOS XMGCF5R0P0202. The WMI GUID, EMEM physical address, KBBR offset, and zone mapping are all DSDT-derived and may differ on other TIMI models or after a BIOS update.
- **Acpi_call dependency.** The kernel's wmi-bus exposes the device but does not provide a userspace write interface for `setable` data blocks (the kernel's sysfs attribute is spelled that way) at the kernel versions tested. Future direction: replace the userspace stack with a small WMI bus driver in C; see `docs/architecture.md`.

## Credits

- **chocapikk** — broader ITE 8910 reverse-engineering blog post (XMG/Clevo flavor); useful background even though the protocol differs.
- **TUXEDO drivers** team — `ite_829x` binding logic informed the early HID-path investigations (which turned out to be a dead end on Quanta firmware, but the reading list was right).

## Layout

```
hotkey/                  Python ACPI-WMI daemon for M1–M5 + Fan keys
  daemon.py              the daemon
  config.example.toml    template (copy to config.toml and edit)
  mi-hotkey.service      systemd unit
  README.md

rgbkb/                   Bash CLI for the 4-zone backlight
  rgbkb                  the CLI
  tools/                 diagnostic + validation scripts (incl. paint_no_fn.sh)
  README.md

docs/
  architecture.md        how the WSAA protocol is wired together
  DSDT-extracts.md       relevant _Q-handlers, MIAP namespace, EMEM regions
```

## Status

Not yet on GitHub or any registry. Run from a local clone. License: MIT (see `LICENSE`).
