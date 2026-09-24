"""Tests for services.tts_settings (voice discovery + persisted TTS settings)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tts_settings as ts  # noqa: E402

SAPI = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens"
ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"


def fake_reader(tables):
    """Build a registry reader returning [(key_name, display_name)] per category path."""
    def read(category_path):
        if category_path not in tables:
            raise FileNotFoundError(category_path)
        return tables[category_path]
    return read


class ListVoicesTests(unittest.TestCase):
    def test_lists_default_then_desktop_and_onecore_voices_with_full_token_ids(self):
        read = fake_reader({
            SAPI: [("TTS_MS_EN-US_ZIRA_11.0", "Microsoft Zira Desktop - English (United States)")],
            ONECORE: [("MSTTS_V110_enUS_MarkM", "Microsoft Mark - English (United States)")],
        })
        voices = ts.list_voices(read)
        self.assertEqual(voices[0].token_id, "")  # Windows default comes first
        ids = [v.token_id for v in voices]
        self.assertIn(SAPI + r"\TTS_MS_EN-US_ZIRA_11.0", ids)
        self.assertIn(ONECORE + r"\MSTTS_V110_enUS_MarkM", ids)
        mark = next(v for v in voices if v.token_id.endswith("MarkM"))
        self.assertIn("Mark", mark.label)

    def test_missing_category_is_skipped_not_fatal(self):
        read = fake_reader({SAPI: [("TTS_MS_EN-US_DAVID_11.0", "Microsoft David Desktop")]})
        voices = ts.list_voices(read)
        self.assertEqual(len(voices), 2)  # default + David

    def test_blank_display_name_falls_back_to_key_name(self):
        read = fake_reader({SAPI: [("SOME_THIRD_PARTY_VOICE", "")]})
        voices = ts.list_voices(read)
        self.assertIn("SOME_THIRD_PARTY_VOICE", voices[1].label)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ui_settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_defaults(self):
        s = ts.TtsSettings.load(self.path)
        self.assertTrue(s.enabled)
        self.assertEqual(s.voice_id, "")
        self.assertEqual(s.volume, ts.DEFAULT_VOLUME)
        self.assertEqual(s.rate, 0)

    def test_round_trip(self):
        s = ts.TtsSettings(enabled=False, voice_id=SAPI + r"\X", volume=220, rate=-2)
        s.save(self.path)
        back = ts.TtsSettings.load(self.path)
        self.assertEqual(back, s)

    def test_out_of_range_values_are_clamped_on_load(self):
        self.path.write_text(json.dumps({"tts": {"volume": 9999, "rate": -50, "voice_id": 7}}), encoding="utf-8")
        s = ts.TtsSettings.load(self.path)
        self.assertEqual(s.volume, ts.MAX_VOLUME)
        self.assertEqual(s.rate, -10)
        self.assertEqual(s.voice_id, "")

    def test_corrupt_file_falls_back_to_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(ts.TtsSettings.load(self.path), ts.TtsSettings())

    def test_save_preserves_other_top_level_keys(self):
        self.path.write_text(json.dumps({"window": {"w": 900}}), encoding="utf-8")
        ts.TtsSettings(volume=180).save(self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["window"], {"w": 900})
        self.assertEqual(data["tts"]["volume"], 180)

    def test_dict_round_trip_matches_the_file_format(self):
        s = ts.TtsSettings(enabled=False, voice_id="V", volume=220, rate=-2)
        self.assertEqual(s.to_dict(), {"enabled": False, "voice_id": "V", "volume": 220, "rate": -2})
        self.assertEqual(ts.TtsSettings.from_dict(s.to_dict()), s)

    def test_from_dict_tolerates_garbage(self):
        self.assertEqual(ts.TtsSettings.from_dict(None), ts.TtsSettings())
        self.assertEqual(ts.TtsSettings.from_dict({"volume": "x", "rate": 99}).rate, 10)

    def test_ipc_messages_apply_every_setting(self):
        msgs = ts.TtsSettings(enabled=True, voice_id="V", volume=150, rate=3).ipc_messages()
        by_type = {m["type"]: m for m in msgs}
        self.assertEqual(by_type["set_tts_enabled"]["enabled"], True)
        self.assertEqual(by_type["set_tts_voice"]["id"], "V")
        self.assertEqual(by_type["set_tts_volume"]["volume"], 150)
        self.assertEqual(by_type["set_tts_rate"]["rate"], 3)


if __name__ == "__main__":
    unittest.main()
