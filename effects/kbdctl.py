#!/usr/bin/env python3
"""Small CLI for the mi-tm1806-led sysfs backend."""

from __future__ import annotations

import sys
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mi_tm1806_sysfs import (
    DriverUnavailable,
    LED_PREFIX,
    WMI_DEV,
    ZONES,
    paint_frame,
    validate_driver,
)

CLI_ZONES = {
    "bar": "bar",
    "left": "left",
    "mid": "mid",
    "right": "right",
    "kb-left": "left",
    "kb-mid": "mid",
    "kb-right": "right",
}

COLORS = {
    "red": "FF0000",
    "green": "00FF00",
    "blue": "0000FF",
    "yellow": "FFFF00",
    "cyan": "00FFFF",
    "magenta": "FF00FF",
    "white": "FFFFFF",
    "orange": "FF8000",
    "purple": "8000FF",
    "pink": "FF8080",
    "black": "000000",
    "off": "000000",
}


def usage() -> int:
    print(
        "Usage: kbdctl.py {solid COLOR|breath COLOR [--speed N]|wave COLOR [--speed N]|"
        "colorful COLOR1 COLOR2 [--speed N]|zone ZONE COLOR|"
        "frame C1 C2 C3 C4 [--effect NAME] [--secondary COLOR] [--speed N]|"
        "doctor}",
        file=sys.stderr,
    )
    return 1


def color(value: str) -> str:
    key = value.lower()
    if key in COLORS:
        return COLORS[key]
    h = value.strip().lstrip("#").removeprefix("0x")
    if len(h) == 6:
        int(h, 16)
        return h.upper()
    raise ValueError(f"unknown color: {value}")


def parse_speed(args: list[str]) -> tuple[list[str], int]:
    if "--speed" not in args:
        return args, 2
    idx = args.index("--speed")
    if idx + 1 >= len(args):
        raise ValueError("--speed requires 0, 1, or 2")
    speed = int(args[idx + 1])
    if speed not in (0, 1, 2):
        raise ValueError("speed must be 0, 1, or 2")
    return args[:idx] + args[idx + 2 :], speed


def pop_option(args: list[str], name: str, default: str | None = None) -> tuple[list[str], str | None]:
    if name not in args:
        return args, default
    idx = args.index(name)
    if idx + 1 >= len(args):
        raise ValueError(f"{name} requires a value")
    return args[:idx] + args[idx + 2 :], args[idx + 1]


def current_colors() -> list[str]:
    validate_driver()
    colors: list[str] = []
    for zone in ("bar", "left", "mid", "right"):
        raw = (LED_PREFIX / f"mi_tm1806::kbd_{zone}" / "multi_intensity").read_text()
        vals = [int(v) for v in raw.split()[:3]]
        if len(vals) != 3:
            raise ValueError(f"cannot parse current color for {zone}: {raw!r}")
        colors.append(f"{vals[0]:02X}{vals[1]:02X}{vals[2]:02X}")
    return colors


@dataclass
class Check:
    ok: bool
    label: str
    detail: str = ""


def _run(argv: list[str], timeout: int = 3) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _is_writable(path: Path) -> bool:
    import os

    return path.exists() and os.access(path, os.W_OK)


def _is_readable(path: Path) -> bool:
    import os

    return path.exists() and os.access(path, os.R_OK)


def _print_check(check: Check) -> None:
    mark = "OK" if check.ok else "WARN"
    detail = f" - {check.detail}" if check.detail else ""
    print(f"[{mark}] {check.label}{detail}")


def doctor() -> int:
    checks: list[Check] = []

    modinfo = _run(["modinfo", "mi_tm1806_led"])
    if modinfo and modinfo.returncode == 0:
        fields = {}
        for line in modinfo.stdout.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        detail = fields.get("filename", "module found")
        if fields.get("vermagic"):
            detail += f"; vermagic={fields['vermagic']}"
        if fields.get("signer"):
            detail += f"; signer={fields['signer']}"
        checks.append(Check(True, "modinfo mi_tm1806_led", detail))
    else:
        checks.append(Check(False, "modinfo mi_tm1806_led", "module is not installed in the module path"))

    modules = _read(Path("/proc/modules")) or ""
    checks.append(Check("mi_tm1806_led " in modules, "module loaded", "use `sudo modprobe mi_tm1806_led`" if "mi_tm1806_led " not in modules else "loaded"))

    if shutil.which("dkms"):
        dkms = _run(["dkms", "status", "mi-tm1806-led"])
        ok = bool(dkms and dkms.returncode == 0 and "installed" in dkms.stdout)
        detail = (dkms.stdout.strip() if dkms else "") or "not installed"
        checks.append(Check(ok, "DKMS status", detail))
    else:
        checks.append(Check(False, "DKMS status", "dkms command not found"))

    required_missing = False
    for zone in ZONES:
        zone_dir = LED_PREFIX / f"mi_tm1806::kbd_{zone}"
        for attr in ("multi_intensity", "brightness"):
            path = zone_dir / attr
            required_ok = path.exists() and _is_readable(path)
            writable = _is_writable(path)
            required_missing = required_missing or not required_ok
            perm = []
            if path.exists():
                perm.append("readable" if _is_readable(path) else "not-readable")
                perm.append("writable" if writable else "not-writable")
            checks.append(Check(required_ok and writable, f"LED {zone}/{attr}", ", ".join(perm) if perm else "missing"))

    for attr in ("effect", "speed", "secondary_color", "panel_brightness", "commit"):
        path = WMI_DEV / attr
        required_ok = path.exists() and (attr == "commit" or _is_readable(path))
        writable = _is_writable(path)
        required_missing = required_missing or not required_ok
        if attr == "commit":
            detail = "writable" if writable else ("not-writable" if path.exists() else "missing")
        else:
            val = _read(path)
            detail = f"value={val}" if val is not None else "missing"
            detail += "; writable" if writable else "; not-writable"
        checks.append(Check(required_ok and writable, f"WMI {attr}", detail))

    kbbr = _read(WMI_DEV / "panel_brightness")
    if kbbr == "5":
        checks.append(Check(False, "panel wake state", "panel_brightness=5; press Fn+keyboard-brightness once"))

    if shutil.which("systemctl"):
        svc = _run(["systemctl", "is-active", "mi-hotkey"])
        active = bool(svc and svc.returncode == 0 and svc.stdout.strip() == "active")
        checks.append(Check(active, "mi-hotkey service", "active" if active else "not active or not accessible"))

    for check in checks:
        _print_check(check)

    if required_missing:
        print("Next step: load the driver with `sudo modprobe mi_tm1806_led` and check DKMS/install docs.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return usage()
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "doctor":
            if args:
                return usage()
            return doctor()
        args, speed = parse_speed(args)
        if cmd in ("solid", "static"):
            if len(args) != 1:
                return usage()
            c = color(args[0])
            paint_frame([c, c, c, c], "static", speed)
        elif cmd in ("breath", "wave"):
            if len(args) != 1:
                return usage()
            c = color(args[0])
            paint_frame([c, c, c, c], cmd, speed)
        elif cmd == "colorful":
            if len(args) != 2:
                return usage()
            c1, c2 = color(args[0]), color(args[1])
            paint_frame([c1, c1, c1, c1], "colorful", speed, c2)
        elif cmd == "zone":
            if len(args) != 2:
                return usage()
            zone = CLI_ZONES.get(args[0])
            if zone is None:
                raise ValueError(f"unknown zone: {args[0]}")
            c = color(args[1])
            current = current_colors()
            current[("bar", "left", "mid", "right").index(zone)] = c
            paint_frame(current, "static", speed)
        elif cmd == "frame":
            args, effect = pop_option(args, "--effect", "static")
            args, secondary = pop_option(args, "--secondary")
            if len(args) != 4:
                return usage()
            paint_frame([color(v) for v in args], effect or "static", speed,
                        color(secondary) if secondary else None)
        else:
            return usage()
    except (ValueError, DriverUnavailable, OSError) as exc:
        print(f"kbdctl.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
