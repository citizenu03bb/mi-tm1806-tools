#!/usr/bin/env python3
"""Shared sysfs backend for the mi-tm1806-led kernel driver."""

from __future__ import annotations

from pathlib import Path

WMI_GUID = "E2A89D40-784F-4E91-BE22-AE373CDEA97A"
LED_PREFIX = Path("/sys/class/leds")
WMI_DEV = Path("/sys/bus/wmi/devices") / WMI_GUID
ZONES = ("bar", "left", "mid", "right")
EFFECTS = {"static": 1, "breath": 2, "wave": 3, "colorful": 4}


class DriverUnavailable(RuntimeError):
    """Raised when the kernel-driver sysfs surface is missing or unusable."""


def _zone_dir(zone: str) -> Path:
    if zone not in ZONES:
        raise ValueError(f"unknown zone {zone!r}; expected one of {', '.join(ZONES)}")
    return LED_PREFIX / f"mi_tm1806::kbd_{zone}"


def write_sysfs(path: Path, value: str | int) -> None:
    try:
        path.write_text(str(value))
    except OSError as exc:
        raise DriverUnavailable(f"cannot write {path}: {exc}") from exc


def validate_driver() -> None:
    missing = []
    for zone in ZONES:
        zone_path = _zone_dir(zone)
        if not (zone_path / "multi_intensity").exists():
            missing.append(str(zone_path / "multi_intensity"))
        if not (zone_path / "brightness").exists():
            missing.append(str(zone_path / "brightness"))
    for attr in ("effect", "speed", "secondary_color", "panel_brightness", "commit"):
        if not (WMI_DEV / attr).exists():
            missing.append(str(WMI_DEV / attr))
    if missing:
        raise DriverUnavailable(
            "mi-tm1806-led sysfs interface is not available; missing "
            + ", ".join(missing[:4])
            + (" ..." if len(missing) > 4 else "")
        )


def set_zone(zone: str, r: int, g: int, b: int, brightness: int = 255) -> None:
    zone_path = _zone_dir(zone)
    write_sysfs(zone_path / "multi_intensity", f"{r} {g} {b}")
    write_sysfs(zone_path / "brightness", brightness)


def set_effect(effect: str, speed: int = 2, secondary: str | None = None) -> None:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}; expected one of {', '.join(EFFECTS)}")
    if speed < 0 or speed > 2:
        raise ValueError("speed must be 0, 1, or 2")
    write_sysfs(WMI_DEV / "effect", EFFECTS[effect])
    write_sysfs(WMI_DEV / "speed", speed)
    if secondary:
        write_sysfs(WMI_DEV / "secondary_color", secondary.lstrip("#").removeprefix("0x"))


def commit() -> None:
    write_sysfs(WMI_DEV / "commit", "1")


def paint_frame(
    colors: list[str],
    effect: str = "static",
    speed: int = 2,
    secondary: str | None = None,
) -> None:
    if len(colors) != len(ZONES):
        raise ValueError(f"expected {len(ZONES)} colors, got {len(colors)}")
    validate_driver()
    for zone, raw in zip(ZONES, colors):
        h = raw.strip().lstrip("#").removeprefix("0x")
        if len(h) != 6:
            raise ValueError(f"invalid RGB hex color: {raw!r}")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        set_zone(zone, r, g, b)
    set_effect(effect, speed, secondary)
    commit()
