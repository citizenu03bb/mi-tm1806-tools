#!/bin/bash
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

systemctl disable --now mi-hotkey 2>/dev/null || true
rm -f /etc/systemd/system/mi-hotkey.service
rm -f /usr/local/bin/mi-hotkey-daemon
systemctl daemon-reload

echo "Removed mi-hotkey service and daemon."
echo "Left /etc/mi-hotkey and per-user ~/.config/mi-hotkey configs untouched."
