# hotkey/

Python daemon that turns the M1–M5 + Fan keys (the dedicated column on the far left of the TM1806's built-in keyboard) into runnable actions. These keys never reach `/dev/input` — they fire ACPI WMI events that no standard Linux driver binds to.

The daemon runs as a single system service and dispatches **per-user**: each event is attributed to whoever is currently active on `seat0` (via `loginctl`), and that user's `~/.config/mi-hotkey/config.toml` is consulted before falling back to the system default at `/etc/mi-hotkey/config.toml`.

See the [top-level README](../README.md) for context, requirements, and the bigger picture.

## Files

- `daemon.py` — the daemon. Listens on `acpi_listen` (netlink), gates on the EVT0 group code, calls `\_SB.MIAP._WED(0x80)` via `acpi_call` to extract the per-key code, resolves the active seat0 user, loads their config, dispatches.
- `config.example.toml` — annotated template covering every action type (`shell`, `exec`, `key` via uinput, `notify`). Copy fragments to your own `~/.config/mi-hotkey/config.toml`.
- `mi-hotkey.service` — systemd unit, runs as root from `/usr/local/bin/mi-hotkey-daemon`. Discovers each user's session env by scanning `/proc/*/environ` and picking the richest set of `DISPLAY` / `WAYLAND_DISPLAY` / `DBUS_SESSION_BUS_ADDRESS` / etc. — necessary because system services start before the X session imports those.

## Install

```sh
sudo ../scripts/install-hotkey.sh
```

To remove the daemon and systemd unit while keeping configs: `sudo ../scripts/uninstall-hotkey.sh`.

## Configuration

Two places, in this order of precedence:

1. **`~/.config/mi-hotkey/config.toml`** — per-user override. Edit yours; macros invoked while you are the seat0-active user use this.
2. **`/etc/mi-hotkey/config.toml`** — system default. Used for anyone without a per-user file.

The daemon re-reads the resolved config on every event (mtime-checked, no restart needed). On user switch (fast user switching, login/logout), the new user's config picks up automatically.

Override knobs (env in the systemd unit):

- `MI_HOTKEY_CONFIG=/some/path/config.toml` — override the system fallback path.
- `MI_HOTKEY_USER=username` — bypass `loginctl` detection and dispatch as a fixed user. Useful for headless testing.

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

## PNP enumeration

Kernels ≥6.10 deliver unbound WMI events as `wmi PNP0C14:NN <notify> <data>` rather than `<GUID> <notify> <data>`. The daemon resolves the `PNP0C14:NN → handler-kind` mapping dynamically at startup by walking `/sys/bus/wmi/devices/<GUID>/` for each event-firing GUID we know about and reading its `realpath` to find the parent `PNP0C14:NN` device — so the mapping stays correct across BIOS updates that reorder ACPI enumeration.
