# Roadmap

This project is intentionally hardware-specific: TM1806/Quanta WSAA keyboard
control on Linux. The public target is a reproducible hacker release for owners
of this exact machine, not broad laptop support.

## Priority Order

1. **Supportability first** — make setup failures diagnosable without reading
   the source or guessing at sysfs paths.
2. **Regression coverage second** — protect the Python/Bash glue that can be
   tested without the physical keyboard.
3. **Public maintenance third** — make issue reports and CI useful.
4. **Packaging and upstream later** — only after the public support loop is
   stable.

## P0: Doctor/Status Command

Status: initial implementation exists in `effects/kbdctl.py doctor`; keep
iterating based on real issue reports.

Goal: one command a user can run before filing an issue:

```sh
python3 effects/kbdctl.py doctor
```

Implement it as a read-mostly diagnostic in `effects/kbdctl.py`, using helper
functions in `effects/mi_tm1806_sysfs.py` where practical. It must not change
keyboard colors. Any write test must require an explicit flag such as
`--test-commit`.

Report these checks:

- `modinfo mi_tm1806_led`: resolved module path, vermagic, signer if present
- loaded module state from `/proc/modules`
- DKMS status for `mi-tm1806-led`, if `dkms` is installed
- four LED sysfs nodes and their `multi_intensity` / `brightness` attributes
- WMI sysfs attributes: `effect`, `speed`, `secondary_color`,
  `panel_brightness`, `commit`
- readable current values for effect, speed, secondary color, and panel
  brightness
- read/write permission status for LED and WMI attributes
- hotkey service status when `systemctl` is available
- warnings for common states: driver missing, permissions missing,
  `panel_brightness=5`, missing DKMS install, hotkey service inactive

Acceptance criteria:

- exits `0` when required driver sysfs files exist and are readable
- exits non-zero when the kernel-driver sysfs surface is missing
- prints actionable next steps, not only raw failures
- works without root when files are readable

## P1: Non-Hardware Test Suite

Status: initial `unittest` coverage exists for color parsing, frame validation,
fake sysfs reads/writes, doctor success/failure behavior, and hotkey event
gating.

Goal: test public-facing glue on any Linux machine without TM1806 hardware,
root, `/sys`, `/proc/acpi/call`, OpenRGB, PipeWire, or the physical keyboard.

Use standard-library `unittest` unless a stronger reason appears to add a test
dependency. Put tests under `tests/` and make this command work:

```sh
python3 -m unittest discover
```

Initial coverage:

- color parsing in `effects/kbdctl.py`: names, `RRGGBB`, `#RRGGBB`, `0xRRGGBB`,
  invalid values
- `frame` command validation: exactly four colors, valid effect, speed range,
  secondary color handling
- sysfs backend path construction and missing-file errors with a temporary fake
  sysfs tree
- `doctor` output/exit behavior with mocked subprocess and fake sysfs state
- preset JSON playback command construction for uniform and per-zone frames
- hotkey config loading: valid TOML, missing file fallback, malformed config
- WMI event mapping: macro-key EVT0/EVT1 dispatch stays separate from
  Fn-brightness events

Acceptance criteria:

- all tests pass with `python3 -m unittest discover`
- tests are deterministic and do not touch real hardware sysfs paths
- Python compile checks and Bash syntax checks remain green

## P2: Public Maintenance Loop

Status: initial GitHub issue template and generic-host CI workflow exist.

Goal: make public issue handling repeatable.

- Document `python3 effects/kbdctl.py doctor` in the README and relevant
  component READMEs.
- Add a GitHub issue template that asks for doctor output, kernel version,
  BIOS version, install method, and whether `KBBR=5` was observed.
- Add basic CI for Python compile checks, Bash syntax checks, unit tests, and a
  scan for hard-coded personal paths.
- Keep kernel and OpenRGB builds as documented local verification steps unless
  a reliable CI image is added for kernel headers and OpenRGB sources.

Acceptance criteria:

- a new user has a single diagnostic command and a clear issue-report path
- CI catches syntax/test regressions before merge
- hardware-specific failures remain documented as manual verification

## P3: Installer/Packaging Pass

Goal: reduce manual setup once the diagnostic and test foundations are stable.

- Add documented install/uninstall targets or helper scripts for DKMS, udev
  permissions, the hotkey service, and optional integrations.
- Keep scripts explicit and reversible; avoid hiding privileged operations.
- Ensure Secure Boot signing/MOK instructions remain accurate.

Acceptance criteria:

- a fresh TM1806 install can follow one documented path from clone to working
  driver/effects/hotkeys
- uninstall removes installed files without touching user presets/configs

## P4: Compatibility And Upstream Research

Goal: decide whether this can grow beyond one confirmed machine.

- Collect confirmations from additional BIOS revisions or closely related
  TIMI/Quanta models.
- Record WMI GUID, DSDT paths, KBBR behavior, zone mapping, and panel wake
  behavior for each confirmed machine.
- Revisit mainline `platform-driver-x86` only after 2-3 independent confirmed
  variants exist.

Acceptance criteria:

- compatibility table exists
- unsupported machines fail safely and are clearly documented
- upstream discussion has evidence beyond one laptop

## Deferred

- Audio visualizer performance work, unless more bands or faster update modes
  make CPU usage a real problem.
- Broader OpenRGB packaging, unless OpenRGB users become a primary audience.
