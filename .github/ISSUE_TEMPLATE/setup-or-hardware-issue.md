---
name: Setup or hardware issue
about: Report TM1806 driver, sysfs, hotkey, or effects problems
title: "[setup] "
labels: setup
assignees: ""
---

## Hardware

- Laptop model:
- BIOS version:
- Kernel version (`uname -a`):
- Install method: DKMS / manual insmod / other
- Secure Boot: enabled / disabled / unknown

## Doctor output

Run:

```sh
python3 effects/kbdctl.py doctor
```

Paste the full output here:

```text

```

## Problem

What did you run, what did you expect, and what happened?

## Notes

- Did `panel_brightness=5` appear in doctor output?
- Did pressing Fn+keyboard-brightness once change the behavior?
- Are you running commands as root, via sudo, or via udev-granted user access?
