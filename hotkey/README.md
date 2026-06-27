# hotkey/

Python daemon that turns the M1–M5 + Fan keys (the dedicated column on the far left of the TM1806's built-in keyboard) into runnable actions. These keys never reach `/dev/input` — they fire ACPI WMI events that no standard Linux driver binds to.

See the [top-level README](../README.md) for context, requirements, and the bigger picture.

## Files

- `daemon.py` — the daemon. Listens on `acpi_listen` (netlink), gates on the EVT0 group code, calls `\_SB.MIAP._WED(0x80)` via `acpi_call` to extract the per-key code, dispatches per `config.toml`.
- `config.example.toml` — annotated template covering all four action types: `shell`, `exec`, `key` (uinput via python3-evdev), `notify`. Copy to `config.toml` and edit.
- `mi-hotkey.service` — systemd unit (system-wide, runs as root). Reads env from the user's graphical session by scanning `/proc/*/environ` and picking the richest set of `DISPLAY`/`WAYLAND_DISPLAY`/`DBUS_SESSION_BUS_ADDRESS`/etc.

## Per-key WMI mapping

Verified 2026-05-07 by `acpi_call` `_WED(0x80)` probe on a fresh TM1806:

| Key   | GUID + notify                            | Press EVT1 | Release EVT1 |
|-------|------------------------------------------|------------|--------------|
| M1    | `B74AF83F-...` notify `0x80` (EVT0=0x0200) | 0x01     | 0x06         |
| M2    | `B74AF83F-...` notify `0x80` (EVT0=0x0200) | 0x02     | 0x07         |
| M3    | `B74AF83F-...` notify `0x80` (EVT0=0x0200) | 0x03     | 0x08         |
| M4    | `B74AF83F-...` notify `0x80` (EVT0=0x0200) | 0x04     | 0x09         |
| M5    | `B74AF83F-...` notify `0x80` (EVT0=0x0200) | 0x05     | 0x0A         |
| Fan A | `EB2464D2-...` notify `0xA2`             | —         | —            |
| Fan B | `B35609C4-...` notify `0xA9`             | —         | —            |

The EVT0 gate is essential: Fn+brightness ALSO fires `B74AF83F` notify `0x80` with EVT0=`0x0100` and EVT1 set to the brightness level (0–5), which would otherwise collide with M1–M5.

## Caveat on PNP enumeration

Kernels ≥6.10 deliver unbound WMI events as `wmi PNP0C14:NN <notify> <data>` rather than `<GUID> <notify> <data>`. The daemon's `PNP_TO_HANDLER` dict currently hard-codes `PNP0C14:04` (m-keys) and `PNP0C14:00` (fan), which is stable on this firmware today but could shift on a BIOS update. Robust fix: walk `/sys/bus/wmi/devices/<GUID>/` at startup, resolve each parent, populate the dict dynamically. See top-level README's "Future direction" section.
