#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m py_compile \
  effects/kbdctl.py \
  effects/mi_tm1806_sysfs.py \
  effects/audiovisualizer.py \
  effects/editor.py \
  hotkey/daemon.py \
  tests/test_kbdctl.py \
  tests/test_sysfs_backend.py \
  tests/test_hotkey_events.py

python3 -m unittest discover

bash -n \
  scripts/check.sh \
  scripts/install-dkms.sh \
  scripts/install-hotkey.sh \
  scripts/install-udev.sh \
  scripts/uninstall-dkms.sh \
  scripts/uninstall-hotkey.sh \
  scripts/uninstall-udev.sh \
  effects/rgbkb-effects \
  rgbkb/rgbkb \
  integrations/claude-code/keyboard-status.sh

python3 - <<'PY'
import subprocess
import sys

bad = [
    "/home/" + "pat",
    "not yet on " + "GitHub",
    "Future direction: kernel " + "module",
]
files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
failed = False
for path in files:
    try:
        text = open(path, encoding="utf-8").read()
    except UnicodeDecodeError:
        continue
    for needle in bad:
        if needle in text:
            print(f"{path}: contains {needle!r}")
            failed = True
sys.exit(1 if failed else 0)
PY
