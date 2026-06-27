#!/bin/bash
set -euo pipefail

RULE_DST="/etc/udev/rules.d/99-mi-tm1806-led.rules"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

rm -f "$RULE_DST"
udevadm control --reload

echo "Removed $RULE_DST and reloaded udev rules."
echo "Existing sysfs permissions may persist until the driver/device is reloaded."
