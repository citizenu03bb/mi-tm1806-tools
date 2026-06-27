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

if ! command -v dkms >/dev/null 2>&1; then
  echo "dkms is required. Install it with your distribution package manager." >&2
  exit 1
fi

if [ -e "$SRC" ]; then
  echo "Refusing to overwrite existing $SRC" >&2
  echo "Run scripts/uninstall-dkms.sh first, or remove that directory manually." >&2
  exit 1
fi

install -d "$SRC"
cp -a "$DRIVER_DIR"/. "$SRC"/

dkms add -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION"
dkms install -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION"
depmod -a

if lsmod | grep -q '^mi_tm1806_led '; then
  modprobe -r mi_tm1806_led
fi
modprobe mi_tm1806_led

echo "Installed ${PACKAGE_NAME}/${PACKAGE_VERSION} via DKMS and loaded mi_tm1806_led."
