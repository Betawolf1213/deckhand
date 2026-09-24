"""Tests for services.ui_settings (persisted GUI settings + hotkey chords)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import ui_settings as us  # noqa: E402


class LoadSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cfg" / "ui_settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_empty_dict(self):
        self.assertEqual(us.load(self.path), {})

    def test_corrupt_or_non_object_file_gives_empty_dict(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{oops", encoding="utf-8")
        self.assertEqual(us.load(self.path), {})
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(us.load(self.path), {})

    def test_round_trip_creates_parent_and_keeps_tts_key_format(self):
        data = {"tts": {"enabled": True, "voice_id": "", "volume": 150, "rate": 0},
                "theme": {"preset": "Cyan", "custom": {}}, "hotkey": "f8"}
        us.save(self.path, data)
        self.assertEqual(us.load(self.path), data)
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())

    def test_save_does_not_drop_keys_written_by_others(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"window": {"w": 1}, "hotkey": "f1"}), encoding="utf-8")
        us.save(self.path, {"hotkey": "f2"})
        self.assertEqual(us.load(self.path), {"window": {"w": 1}, "hotkey": "f2"})


class HotkeyTests(unittest.TestCase):
    def test_default_hotkey(self):
        self.assertEqual(us.DEFAULT_HOTKEY, "ctrl+shift+f12")
        self.assertEqual(us.hotkey_of({}), "ctrl+shift+f12")
        self.assertEqual(us.hotkey_of({"hotkey": ""}), "")  # explicitly disabled
        self.assertEqual(us.hotkey_of({"hotkey": 5}), "ctrl+shift+f12")

    def test_normalize_chord_lowercases_and_strips_spaces(self):
        self.assertEqual(us.normalize_chord(" Ctrl + Shift + F12 "), "ctrl+shift+f12")
        self.assertEqual(us.normalize_chord("F8"), "f8")
        self.assertEqual(us.normalize_chord("control+alt+k"), "ctrl+alt+k")

    def test_normalize_chord_orders_modifiers(self):
        self.assertEqual(us.normalize_chord("shift+ctrl+f1"), "ctrl+shift+f1")

    def test_empty_chord_means_disabled(self):
        self.assertEqual(us.normalize_chord(""), "")
        self.assertEqual(us.normalize_chord("   "), "")

    def test_invalid_chords_raise(self):
        for bad in ("ctrl+", "ctrl+shift", "a+b", "ctrl++f1", "ctrl+ctrl+f1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    us.normalize_chord(bad)


class AudioDeviceTests(unittest.TestCase):
    def test_device_choices_put_windows_default_first(self):
        devices = [{"id": "{a}", "name": "Headset", "is_default": True},
                   {"id": "{b}", "name": "Webcam mic", "is_default": False}]
        self.assertEqual(us.device_choices(devices), [
            ("", "Windows default"),
            ("{a}", "Headset (default)"),
            ("{b}", "Webcam mic"),
        ])

    def test_device_choices_skip_garbage(self):
        self.assertEqual(us.device_choices([{"name": "no id"}, "x", None]), [("", "Windows default")])
        self.assertEqual(us.device_choices(None), [("", "Windows default")])


if __name__ == "__main__":
    unittest.main()
