import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HOTKEY_PATH = ROOT / "hotkey" / "daemon.py"

spec = importlib.util.spec_from_file_location("mi_hotkey_daemon", HOTKEY_PATH)
hotkey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hotkey
assert spec.loader is not None
spec.loader.exec_module(hotkey)


def wed(evt0: int, evt1: int) -> bytes:
    return evt0.to_bytes(2, "little") + evt1.to_bytes(2, "little") + bytes(28)


class HotkeyEventTest(unittest.TestCase):
    def test_mkey_event_dispatches_press(self):
        calls = []
        with mock.patch.object(hotkey, "call_wed", return_value=wed(0x0200, 0x01)), \
             mock.patch.object(hotkey, "dispatch", side_effect=lambda *args: calls.append(args)):
            hotkey._dispatch_miap()
        self.assertEqual(calls, [("m1", "press")])

    def test_fn_brightness_group_does_not_dispatch_as_mkey(self):
        calls = []
        with mock.patch.object(hotkey, "call_wed", return_value=wed(0x0100, 0x01)), \
             mock.patch.object(hotkey, "dispatch", side_effect=lambda *args: calls.append(args)), \
             mock.patch.object(hotkey, "log"):
            hotkey._dispatch_miap()
        self.assertEqual(calls, [])

    def test_wmi_pnp_event_routes_by_discovered_handler(self):
        calls = []
        with mock.patch.dict(hotkey.PNP_TO_HANDLER, {"PNP0C14:04": "miap_event"}, clear=True), \
             mock.patch.object(hotkey, "_dispatch_miap", side_effect=lambda: calls.append("miap")):
            hotkey.handle_event("wmi PNP0C14:04 00000080 00000000")
        self.assertEqual(calls, ["miap"])

    def test_fan_notify_routes_modes(self):
        calls = []
        with mock.patch.object(hotkey, "dispatch", side_effect=lambda *args: calls.append(args)), \
             mock.patch.object(hotkey, "log"):
            hotkey._dispatch_fan(0xA2)
            hotkey._dispatch_fan(0xA9)
            hotkey._dispatch_fan(0xAA)
        self.assertEqual(calls, [("fan", "mode_a"), ("fan", "mode_b")])


if __name__ == "__main__":
    unittest.main()
