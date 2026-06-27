import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "effects"))

import mi_tm1806_sysfs as sysfs  # noqa: E402
from tests.test_kbdctl import make_fake_sysfs  # noqa: E402


class SysfsBackendTest(unittest.TestCase):
    def test_validate_driver_reports_missing_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sysfs, "LED_PREFIX", Path(tmp) / "leds"), \
                 mock.patch.object(sysfs, "WMI_DEV", Path(tmp) / "wmi"):
                with self.assertRaises(sysfs.DriverUnavailable) as ctx:
                    sysfs.validate_driver()
        self.assertIn("mi-tm1806-led sysfs interface is not available", str(ctx.exception))

    def test_paint_frame_writes_zones_effect_secondary_and_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            led_prefix, wmi_dev = make_fake_sysfs(Path(tmp))
            with mock.patch.object(sysfs, "LED_PREFIX", led_prefix), \
                 mock.patch.object(sysfs, "WMI_DEV", wmi_dev):
                sysfs.paint_frame(
                    ["FF0000", "00FF00", "0000FF", "FFFFFF"],
                    effect="colorful",
                    speed=1,
                    secondary="0x00ffff",
                )

            self.assertEqual((led_prefix / "mi_tm1806::kbd_bar" / "multi_intensity").read_text(), "255 0 0")
            self.assertEqual((led_prefix / "mi_tm1806::kbd_left" / "multi_intensity").read_text(), "0 255 0")
            self.assertEqual((wmi_dev / "effect").read_text(), "4")
            self.assertEqual((wmi_dev / "speed").read_text(), "1")
            self.assertEqual((wmi_dev / "secondary_color").read_text(), "00ffff")
            self.assertEqual((wmi_dev / "commit").read_text(), "1")

    def test_paint_frame_rejects_bad_color_and_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            led_prefix, wmi_dev = make_fake_sysfs(Path(tmp))
            with mock.patch.object(sysfs, "LED_PREFIX", led_prefix), \
                 mock.patch.object(sysfs, "WMI_DEV", wmi_dev):
                with self.assertRaises(ValueError):
                    sysfs.paint_frame(["bad", "00FF00", "0000FF", "FFFFFF"])
                with self.assertRaises(ValueError):
                    sysfs.paint_frame(["FF0000", "00FF00", "0000FF", "FFFFFF"], speed=9)


if __name__ == "__main__":
    unittest.main()
