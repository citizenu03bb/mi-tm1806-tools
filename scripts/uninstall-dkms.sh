#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DRIVER_DIR="$ROOT/driver"

source "$DRIVER_DIR/dkms.conf"

SRC="/usr/src/${PACKAGE_NAME}-${PACKAGE_VERSION}"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if lsmod | grep -q '^mi_tm1806_led '; then
  modprobe -r mi_tm1806_led
fi

if command -v dkms >/dev/null 2>&1; then
  dkms remove -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION" --all || true
fi

rm -rf "$SRC"
depmod -a

echo "Removed ${PACKAGE_NAME}/${PACKAGE_VERSION} DKMS registration and source tree."
