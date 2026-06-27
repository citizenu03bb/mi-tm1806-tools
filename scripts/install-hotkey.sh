#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

install -m 0755 "$ROOT/hotkey/daemon.py" /usr/local/bin/mi-hotkey-daemon
install -m 0644 "$ROOT/hotkey/mi-hotkey.service" /etc/systemd/system/mi-hotkey.service
install -d /etc/mi-hotkey

if [ ! -e /etc/mi-hotkey/config.toml ]; then
  install -m 0644 "$ROOT/hotkey/config.example.toml" /etc/mi-hotkey/config.toml
  echo "Installed initial /etc/mi-hotkey/config.toml; edit it for system defaults."
else
  echo "Keeping existing /etc/mi-hotkey/config.toml."
fi

systemctl daemon-reload
systemctl enable --now mi-hotkey

echo "Installed and started mi-hotkey.service."
