#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RULE_SRC="$ROOT/integrations/claude-code/99-mi-tm1806-led.rules"
RULE_DST="/etc/udev/rules.d/99-mi-tm1806-led.rules"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if ! getent group plugdev >/dev/null; then
  echo "Group plugdev does not exist. Create it or edit $RULE_SRC for another group." >&2
  exit 1
fi

install -m 0644 "$RULE_SRC" "$RULE_DST"
udevadm control --reload
udevadm trigger --subsystem-match=leds || true
udevadm trigger --subsystem-match=wmi || true

echo "Installed $RULE_DST and reloaded udev rules."
echo "If permissions do not update, reload the driver: sudo modprobe -r mi_tm1806_led && sudo modprobe mi_tm1806_led"
