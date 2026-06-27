import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "effects"))

import kbdctl  # noqa: E402
import mi_tm1806_sysfs as sysfs  # noqa: E402


def make_fake_sysfs(root: Path) -> tuple[Path, Path]:
    led_prefix = root / "leds"
    wmi_dev = root / "wmi" / sysfs.WMI_GUID
    for zone in sysfs.ZONES:
        zone_dir = led_prefix / f"mi_tm1806::kbd_{zone}"
        zone_dir.mkdir(parents=True)
        (zone_dir / "multi_intensity").write_text("1 2 3")
        (zone_dir / "brightness").write_text("255")
    wmi_dev.mkdir(parents=True)
    for attr, value in {
        "effect": "1",
        "speed": "2",
        "secondary_color": "00ffff",
        "panel_brightness": "0",
        "commit": "",
    }.items():
        (wmi_dev / attr).write_text(value)
    return led_prefix, wmi_dev


class KbdctlTest(unittest.TestCase):
    def test_color_formats(self):
        self.assertEqual(kbdctl.color("red"), "FF0000")
        self.assertEqual(kbdctl.color("00ff80"), "00FF80")
        self.assertEqual(kbdctl.color("#00ff80"), "00FF80")
        self.assertEqual(kbdctl.color("0x00ff80"), "00FF80")
        with self.assertRaises(ValueError):
            kbdctl.color("not-a-color")
        with self.assertRaises(ValueError):
            kbdctl.color("ffff")

    def test_parse_speed(self):
        self.assertEqual(kbdctl.parse_speed(["red"]), (["red"], 2))
        self.assertEqual(kbdctl.parse_speed(["red", "--speed", "1"]), (["red"], 1))
        with self.assertRaises(ValueError):
            kbdctl.parse_speed(["--speed", "9"])

    def test_frame_command_validates_four_colors(self):
        with mock.patch.object(kbdctl, "paint_frame") as paint:
            self.assertEqual(kbdctl.main(["frame", "red", "green", "blue", "white"]), 0)
        paint.assert_called_once_with(["FF0000", "00FF00", "0000FF", "FFFFFF"], "static", 2, None)

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(kbdctl.main(["frame", "red", "green", "blue"]), 1)

    def test_current_colors_reads_fake_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            led_prefix, wmi_dev = make_fake_sysfs(Path(tmp))
            with mock.patch.object(sysfs, "LED_PREFIX", led_prefix), \
                 mock.patch.object(sysfs, "WMI_DEV", wmi_dev), \
                 mock.patch.object(kbdctl, "LED_PREFIX", led_prefix), \
                 mock.patch.object(kbdctl, "WMI_DEV", wmi_dev):
                self.assertEqual(kbdctl.current_colors(), ["010203"] * 4)

    def test_doctor_success_with_fake_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            led_prefix, wmi_dev = make_fake_sysfs(Path(tmp))

            def fake_run(argv, timeout=3):
                if argv[0] == "modinfo":
                    return subprocess.CompletedProcess(argv, 0, "filename: /lib/modules/x/mi.ko\nvermagic: test\n", "")
                if argv[0] == "dkms":
                    return subprocess.CompletedProcess(argv, 0, "mi-tm1806-led/0.2, test: installed\n", "")
                if argv[:2] == ["systemctl", "is-active"]:
                    return subprocess.CompletedProcess(argv, 0, "active\n", "")
                return subprocess.CompletedProcess(argv, 1, "", "")

            with mock.patch.object(kbdctl, "LED_PREFIX", led_prefix), \
                 mock.patch.object(kbdctl, "WMI_DEV", wmi_dev), \
                 mock.patch.object(kbdctl, "_run", fake_run), \
                 mock.patch.object(kbdctl.shutil, "which", return_value="/usr/bin/tool"), \
                 mock.patch.object(kbdctl, "_read", side_effect=lambda p: "mi_tm1806_led 1 0 - Live 0\n" if p == Path("/proc/modules") else p.read_text().strip()), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(kbdctl.doctor(), 0)
            self.assertIn("[OK] modinfo mi_tm1806_led", out.getvalue())

    def test_doctor_fails_when_sysfs_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            led_prefix = Path(tmp) / "missing-leds"
            wmi_dev = Path(tmp) / "missing-wmi"
            with mock.patch.object(kbdctl, "LED_PREFIX", led_prefix), \
                 mock.patch.object(kbdctl, "WMI_DEV", wmi_dev), \
                 mock.patch.object(kbdctl, "_run", return_value=subprocess.CompletedProcess([], 1, "", "")), \
                 mock.patch.object(kbdctl.shutil, "which", return_value=None), \
                 mock.patch.object(kbdctl, "_read", return_value=""), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(kbdctl.doctor(), 1)


if __name__ == "__main__":
    unittest.main()
