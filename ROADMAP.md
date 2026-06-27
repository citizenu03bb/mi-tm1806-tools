# Roadmap

This project is intentionally hardware-specific: TM1806/Quanta WSAA keyboard
control on Linux. The first public goal is a reproducible hacker release for
owners of this exact machine, not broad laptop support.

## Near term

- Keep the kernel driver as the primary backend and use the sysfs
  store-and-commit interface from high-level tools.
- Keep `rgbkb/` as a legacy userspace implementation and protocol diagnostic
  reference.
- Add a `doctor`/`status` command for the kernel-driver path.
- Add a small non-hardware test suite for public-regression coverage.

## Phased implementation plan

### Phase 1: `doctor` command

Add a read-mostly diagnostic command that can be run before filing an issue.
The command should live next to the sysfs backend helper and be callable as:

```sh
python3 effects/kbdctl.py doctor
```

It should report:

- kernel module resolution: `modinfo mi_tm1806_led` path, version metadata, and
  whether the module is currently loaded
- DKMS status for `mi-tm1806-led`, if `dkms` is installed
- LED sysfs availability for all four zones
- WMI sysfs attributes: `effect`, `speed`, `secondary_color`,
  `panel_brightness`, and `commit`
- current readable values for effect, speed, secondary color, and panel
  brightness
- write-permission status for LED zone attributes and WMI attributes
- hotkey service status, if `systemctl` is available

The command must not change keyboard colors. It may optionally perform a commit
write only behind an explicit flag such as `--test-commit`.

Acceptance criteria:

- exits `0` when required driver sysfs files exist and are readable
- exits non-zero when the driver sysfs surface is missing
- prints actionable messages for missing module, missing sysfs node, missing
  permissions, or `panel_brightness=5`
- works without root when files are readable

### Phase 2: non-hardware tests

Add a test suite that runs without TM1806 hardware by mocking filesystem and
subprocess boundaries. Prefer Python `unittest` or `pytest`; if no test
dependency is desired, use `unittest` from the standard library.

Initial coverage:

- color parsing in `effects/kbdctl.py`: names, `RRGGBB`, `#RRGGBB`, `0xRRGGBB`,
  invalid values
- frame command validation: exactly four colors, valid effect, speed range,
  secondary color handling
- sysfs backend path construction and missing-file errors using a temporary
  fake sysfs tree
- preset JSON validation/playback command construction for uniform and per-zone
  frames
- hotkey config loading with valid TOML, missing file fallback, and malformed
  config behavior
- WMI event mapping: macro-key EVT0/EVT1 dispatch is gated separately from
  Fn-brightness events

Acceptance criteria:

- `python3 -m unittest discover` or one documented command runs the suite
- tests do not require root, `/sys`, `/proc/acpi/call`, OpenRGB, PipeWire, or
  the physical keyboard
- CI can run the tests on a generic Linux host

### Phase 3: public issue template and CI

After the command and tests exist, wire them into public maintenance:

- document `python3 effects/kbdctl.py doctor` in the README and issue template
- ask users to paste doctor output when reporting hardware/setup issues
- add a basic CI workflow for Python compile checks, Bash syntax checks,
  non-hardware tests, and markdown/path sanity scans
- keep kernel/OpenRGB builds documented as local verification steps unless a
  reliable CI environment is added for those dependencies

## Later

- Package a repeatable install path for DKMS, udev permissions, the hotkey
  service, and optional integrations.
- Collect confirmations from additional BIOS revisions or closely related
  TIMI/Quanta models before considering upstream kernel work.
- Improve effect tooling performance if more audio bands or faster animation
  modes are added.
