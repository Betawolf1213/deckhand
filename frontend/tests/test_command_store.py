"""Tests for services.command_store.CommandStore."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.command_store import CommandStore, KEY_NAMES, key_display  # noqa: E402
from test_commands_default import DEFAULT_FILE, action_problems, vk_key_names  # noqa: E402

DEFAULTS = [
    {"id": "landing_gear", "label": "Landing Gear", "category": "Landing & ATC",
     "phrases": ["landing gear", "gear"], "action": {"type": "tap", "keys": "n"}, "tts_ack": "gear"},
    {"id": "ship_power", "label": "Ship Power", "category": "Ship Power",
     "phrases": ["power on", "power off"], "action": {"type": "tap", "keys": "u"}},
    {"id": "ship_zoom", "label": "Ship Zoom", "category": "Ship Weapons",
     "phrases": ["ship zoom"], "action": {"type": "mouse", "button": "right", "kind": "click", "keys": "left alt"}},
    {"id": "quit_game", "label": "Quit", "category": "Special",
     "phrases": ["turn off star citizen"], "action": {"type": "tap", "keys": "alt+f4"}},
    {"id": "hide_chat", "label": "Show / Hide Chat", "category": "Interface",
     "phrases": ["hide chat"], "action": {"type": "tap", "keys": "f12"}},
    {"id": "sprint", "label": "Sprint", "category": "On Foot - Movement",
     "phrases": ["sprint"], "action": {"type": "hold", "keys": "left shift", "duration_ms": 1500}},
    {"id": "vtol", "label": "VTOL", "category": "Flight",
     "phrases": ["vtol"], "action": {"type": "tap", "keys": "k"}},
    {"id": "preset_next", "label": "Next Preset", "category": "Ship Weapons",
     "phrases": ["next weapon preset"], "action": {"type": "scroll", "direction": "down", "amount": 1}},
]


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.default_path = self.dir / "commands.default.json"
        self.user_path = self.dir / "commands.json"
        self.write_defaults(DEFAULTS)
        self.store = self.new_store()

    def tearDown(self):
        self._tmp.cleanup()

    def write_defaults(self, commands):
        self.default_path.write_text(json.dumps({"version": 2, "commands": commands}), encoding="utf-8")

    def new_store(self):
        s = CommandStore(self.default_path, self.user_path)
        s.load()
        return s

    def saved(self):
        return json.loads(self.user_path.read_text(encoding="utf-8"))

    def ids(self, cmds):
        return [c["id"] for c in cmds]


class LoadTests(StoreTestCase):
    def test_load_defaults_when_no_user_file(self):
        cmds = self.store.all()
        self.assertEqual(self.ids(cmds), [c["id"] for c in DEFAULTS])
        gear = self.store.get("landing_gear")
        self.assertEqual(gear["phrases"], ["landing gear", "gear"])
        self.assertEqual(gear["disabled_phrases"], [])
        self.assertFalse(gear["custom"])
        self.assertEqual(gear["tts_ack"], "gear")
        self.assertIsNone(self.store.get("nope"))

    def test_all_and_get_return_copies(self):
        self.store.get("landing_gear")["phrases"].append("x")
        self.store.all()[0]["label"] = "changed"
        self.assertEqual(self.store.get("landing_gear")["phrases"], ["landing gear", "gear"])
        self.assertEqual(self.store.get("landing_gear")["label"], "Landing Gear")

    def test_categories_in_display_order_custom_last(self):
        self.store.create_custom("Wave", "Emotes", ["wave hello"], {"type": "tap", "keys": "j"})
        self.assertEqual(self.store.categories(), [
            "Landing & ATC", "Ship Power", "Ship Weapons", "Special", "Interface",
            "On Foot - Movement", "Flight", "Custom Phrases",
        ])

    def test_user_file_edits_kept_and_new_defaults_added(self):
        self.store.set_phrases("landing_gear", ["gear"], ["landing gear"])
        self.store.save()
        # an app update ships a new default command in the middle of the list
        self.write_defaults(DEFAULTS[:2] + [
            {"id": "contact_atc", "label": "Contact ATC", "category": "Landing & ATC",
             "phrases": ["contact atc"], "action": {"type": "tap", "keys": "left alt+n"}},
        ] + DEFAULTS[2:])
        store = self.new_store()
        self.assertEqual(store.get("landing_gear")["phrases"], ["gear"])
        self.assertEqual(store.get("landing_gear")["disabled_phrases"], ["landing gear"])
        self.assertEqual(self.ids(store.all())[:3], ["landing_gear", "ship_power", "contact_atc"])

    def test_user_file_without_label_gets_default_label(self):
        self.user_path.write_text(json.dumps({"version": 1, "commands": [
            {"id": "landing_gear", "phrases": ["gear"], "action": {"type": "tap", "keys": "n"}},
        ]}), encoding="utf-8")
        store = self.new_store()
        gear = store.get("landing_gear")
        self.assertEqual(gear["label"], "Landing Gear")
        self.assertEqual(gear["category"], "Landing & ATC")
        self.assertEqual(gear["phrases"], ["gear"])
        self.assertEqual(len(store.all()), len(DEFAULTS))

    def test_corrupt_user_file_falls_back_to_defaults(self):
        self.user_path.write_text("{ not json", encoding="utf-8")
        store = self.new_store()
        self.assertEqual(self.ids(store.all()), [c["id"] for c in DEFAULTS])
        self.assertTrue(store.load_error)

    def test_real_default_file_loads_and_round_trips(self):
        store = CommandStore(DEFAULT_FILE, self.user_path)
        store.load()
        before = store.all()
        self.assertGreaterEqual(len(before), 70)
        store.save()
        again = CommandStore(DEFAULT_FILE, self.user_path)
        again.load()
        self.assertEqual(again.all(), before)
        for c in before:
            self.assertFalse(again.is_modified(c["id"]), c["id"])


class SaveTests(StoreTestCase):
    def test_save_writes_full_v2_list_and_notifies(self):
        calls = []
        self.store.add_listener(lambda: calls.append(1))
        self.store.save()
        data = self.saved()
        self.assertEqual(data["version"], 2)
        self.assertEqual(self.ids(data["commands"]), [c["id"] for c in DEFAULTS])
        self.assertEqual(calls, [1])
        self.assertEqual([p.name for p in self.dir.iterdir()], sorted(["commands.default.json", "commands.json"]))

    def test_saved_actions_are_valid_for_backend(self):
        self.store.save()
        allowed = vk_key_names()
        for c in self.saved()["commands"]:
            self.assertEqual(action_problems(c["action"], allowed), [], c["id"])

    def test_failed_save_does_not_notify(self):
        calls = []
        self.store.add_listener(lambda: calls.append(1))
        self.user_path.mkdir()  # cannot replace a directory with a file
        with self.assertRaises(OSError):
            self.store.save()
        self.assertEqual(calls, [])


class PhraseTests(StoreTestCase):
    def test_set_phrases_normalises_and_dedupes(self):
        self.store.set_phrases("landing_gear", ["  Landing   GEAR ", "gear", "gear"], ["Gear Up", "gear"])
        gear = self.store.get("landing_gear")
        self.assertEqual(gear["phrases"], ["landing gear", "gear"])
        self.assertEqual(gear["disabled_phrases"], ["gear up"])

    def test_set_phrases_rejects_phrase_used_by_other_command(self):
        with self.assertRaisesRegex(ValueError, "power on.*Ship Power"):
            self.store.set_phrases("landing_gear", ["gear", "Power  On"], [])
        with self.assertRaises(ValueError):
            self.store.set_phrases("landing_gear", ["gear"], ["power off"])
        self.assertEqual(self.store.get("landing_gear")["phrases"], ["landing gear", "gear"])

    def test_default_command_may_have_all_phrases_disabled(self):
        self.store.set_phrases("vtol", [], ["vtol"])
        self.assertEqual(self.store.get("vtol")["phrases"], [])

    def test_add_and_remove_phrase(self):
        self.store.add_phrase("vtol", "Toggle VTOL")
        self.store.add_phrase("vtol", "vtol mode", enabled=False)
        vtol = self.store.get("vtol")
        self.assertEqual(vtol["phrases"], ["vtol", "toggle vtol"])
        self.assertEqual(vtol["disabled_phrases"], ["vtol mode"])
        self.store.remove_phrase("vtol", "VTOL MODE")
        self.store.remove_phrase("vtol", "vtol")
        self.assertEqual(self.store.get("vtol")["phrases"], ["toggle vtol"])
        self.assertEqual(self.store.get("vtol")["disabled_phrases"], [])

    def test_add_phrase_rejects_duplicates_and_empty(self):
        with self.assertRaises(ValueError):
            self.store.add_phrase("vtol", "gear")
        with self.assertRaises(ValueError):
            self.store.add_phrase("vtol", "   ")

    def test_custom_command_keeps_at_least_one_phrase(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave hello"], {"type": "tap", "keys": "j"})
        with self.assertRaisesRegex(ValueError, "at least one phrase"):
            self.store.remove_phrase(cid, "wave hello")
        with self.assertRaises(ValueError):
            self.store.set_phrases(cid, [], [])

    def test_unknown_command_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.store.set_phrases("nope", ["x"], [])


class ActionTests(StoreTestCase):
    def test_set_action_canonicalises_keys(self):
        self.store.set_action("vtol", {"type": "tap", "keys": " Left Alt + K "})
        self.assertEqual(self.store.get("vtol")["action"], {"type": "tap", "keys": "left alt+k"})
        self.store.set_action("vtol", {"type": "tap", "keys": "Num 7"})
        self.assertEqual(self.store.get("vtol")["action"]["keys"], "numpad7")
        self.store.set_action("vtol", {"type": "hold", "keys": "shift+ctrl+x", "duration_ms": 900})
        self.assertEqual(self.store.get("vtol")["action"], {"type": "hold", "keys": "ctrl+shift+x", "duration_ms": 900})

    def test_set_action_rejects_bad_keys(self):
        for keys in ("", "floop", "ctrl+floop", "a+b"):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.store.set_action("vtol", {"type": "tap", "keys": keys})
        self.assertEqual(self.store.get("vtol")["action"], {"type": "tap", "keys": "k"})

    def test_set_action_validates_other_types(self):
        with self.assertRaises(ValueError):
            self.store.set_action("vtol", {"type": "hold", "keys": "k"})
        with self.assertRaises(ValueError):
            self.store.set_action("vtol", {"type": "hold", "keys": "k", "duration_ms": 0})
        with self.assertRaises(ValueError):
            self.store.set_action("vtol", {"type": "mouse", "button": "top", "kind": "click"})
        with self.assertRaises(ValueError):
            self.store.set_action("vtol", {"type": "warp"})
        self.store.set_action("vtol", {"type": "mouse", "button": "right", "kind": "click", "keys": "Left Alt"})
        self.assertEqual(self.store.get("vtol")["action"]["keys"], "left alt")
        self.store.set_action("vtol", {"type": "scroll", "direction": "up", "amount": 2})
        self.store.set_action("vtol", {"type": "system", "op": "say_random", "responses": ["hi"]})
        with self.assertRaises(ValueError):
            self.store.set_action("vtol", {"type": "system", "op": "say_random", "responses": []})

    def test_modifier_only_hold_allowed(self):
        self.store.set_action("vtol", {"type": "hold", "keys": "Left Shift", "duration_ms": 300})
        self.assertEqual(self.store.get("vtol")["action"]["keys"], "left shift")


class CustomTests(StoreTestCase):
    def test_create_custom(self):
        cid = self.store.create_custom("Wave Hello!", "Emotes", ["Wave  Hello", "say hi"],
                                       {"type": "tap", "keys": "ctrl+j"})
        self.assertEqual(cid, "wave_hello")
        c = self.store.get(cid)
        self.assertTrue(c["custom"])
        self.assertEqual(c["label"], "Wave Hello!")
        self.assertEqual(c["category"], "Emotes")
        self.assertEqual(c["phrases"], ["wave hello", "say hi"])
        self.assertEqual(c["action"], {"type": "tap", "keys": "ctrl+j"})
        self.assertEqual(self.ids(self.store.all())[-1], cid)

    def test_create_custom_ids_are_unique(self):
        a = self.store.create_custom("Wave", "", ["wave one"], {"type": "tap", "keys": "j"})
        b = self.store.create_custom("Wave", "", ["wave two"], {"type": "tap", "keys": "j"})
        c = self.store.create_custom("Landing Gear", "", ["my gear"], {"type": "tap", "keys": "j"})
        d = self.store.create_custom("!!!", "", ["bang"], {"type": "tap", "keys": "j"})
        self.assertEqual((a, b), ("wave", "wave_2"))
        self.assertEqual(c, "landing_gear_2")
        self.assertRegex(d, r"^[a-z0-9_]+$")
        self.assertEqual(self.store.get(a)["category"], "Custom Phrases")

    def test_create_custom_disabled_phrases(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"},
                                       disabled_phrases=["wave maybe"])
        self.assertEqual(self.store.get(cid)["disabled_phrases"], ["wave maybe"])

    def test_create_custom_validation(self):
        with self.assertRaisesRegex(ValueError, "name"):
            self.store.create_custom("  ", "x", ["a phrase"], {"type": "tap", "keys": "j"})
        with self.assertRaisesRegex(ValueError, "phrase"):
            self.store.create_custom("Wave", "x", [], {"type": "tap", "keys": "j"})
        with self.assertRaisesRegex(ValueError, "gear"):
            self.store.create_custom("Wave", "x", ["gear"], {"type": "tap", "keys": "j"})
        with self.assertRaises(ValueError):
            self.store.create_custom("Wave", "x", ["wave"], {"type": "tap", "keys": "floop"})
        self.assertEqual(len(self.store.all()), len(DEFAULTS))

    def test_update_custom(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        self.store.update_custom(cid, label="Big Wave", category="Social")
        self.assertEqual(self.store.get(cid)["label"], "Big Wave")
        self.assertEqual(self.store.get(cid)["category"], "Social")
        with self.assertRaises(ValueError):
            self.store.update_custom(cid, label=" ")
        with self.assertRaises(ValueError):
            self.store.update_custom("vtol", label="x")

    def test_delete_custom(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        self.store.delete_custom(cid)
        self.assertIsNone(self.store.get(cid))
        with self.assertRaises(ValueError):
            self.store.delete_custom("vtol")

    def test_custom_survives_save_and_reload(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        self.store.save()
        store = self.new_store()
        self.assertTrue(store.get(cid)["custom"])
        self.assertEqual(store.categories()[-1], "Custom Phrases")


class ResetTests(StoreTestCase):
    def test_transaction_rolls_back_on_error(self):
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store.set_action("vtol", {"type": "tap", "keys": "j"})
                self.store.add_phrase("vtol", "gear")  # collides -> ValueError
        self.assertEqual(self.store.get("vtol")["action"], {"type": "tap", "keys": "k"})
        self.assertFalse(self.user_path.exists())

    def test_reset_and_is_modified(self):
        self.assertFalse(self.store.is_modified("vtol"))
        self.store.set_action("vtol", {"type": "tap", "keys": "j"})
        self.store.set_phrases("vtol", ["vtol"], ["toggle vtol"])
        self.assertTrue(self.store.is_modified("vtol"))
        self.store.reset_command("vtol")
        self.assertFalse(self.store.is_modified("vtol"))
        self.assertEqual(self.store.get("vtol")["action"], {"type": "tap", "keys": "k"})
        self.assertEqual(self.store.get("vtol")["disabled_phrases"], [])

    def test_reset_rejects_custom_and_phrase_stolen_by_custom(self):
        cid = self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        with self.assertRaises(ValueError):
            self.store.reset_command(cid)
        self.store.remove_phrase("vtol", "vtol")
        self.store.add_phrase(cid, "vtol")
        with self.assertRaisesRegex(ValueError, "vtol"):
            self.store.reset_command("vtol")


class SearchTests(StoreTestCase):
    def test_search_all_matches_label_phrase_category_keys(self):
        self.assertEqual(self.ids(self.store.search_all("gear")), ["landing_gear"])
        self.assertEqual(self.ids(self.store.search_all("POWER OFF")), ["ship_power"])
        self.assertEqual(self.ids(self.store.search_all("ship weapons")), ["ship_zoom", "preset_next"])
        self.assertIn("quit_game", self.ids(self.store.search_all("alt+f4")))
        self.assertEqual(len(self.store.search_all("")), len(DEFAULTS))

    def test_filter_by_keybind_is_exact(self):
        self.assertEqual(self.ids(self.store.filter_by_keybind("K")), ["vtol"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("alt+f4")), ["quit_game"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("Alt + F4")), ["quit_game"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("alt f4")), ["quit_game"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("F12")), ["hide_chat"])
        self.assertEqual(self.store.filter_by_keybind("f4"), [])
        self.assertEqual(self.store.filter_by_keybind("left alt+f4"), [])
        self.assertEqual(self.store.filter_by_keybind(""), [])

    def test_filter_bare_modifier_also_matches_left_variant(self):
        self.assertEqual(self.ids(self.store.filter_by_keybind("shift")), ["sprint"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("left shift")), ["sprint"])

    def test_filter_mouse_and_scroll(self):
        self.assertEqual(self.ids(self.store.filter_by_keybind("left alt+right mouse")), ["ship_zoom"])
        self.assertEqual(self.ids(self.store.filter_by_keybind("scroll down")), ["preset_next"])

    def test_commands_for_key(self):
        self.store.set_action("hide_chat", {"type": "tap", "keys": "k"})
        self.assertEqual(self.ids(self.store.commands_for_key("k")), ["hide_chat", "vtol"])
        self.assertEqual(self.store.commands_for_key("shift"), [])


class NormalizeTests(unittest.TestCase):
    def test_normalize_keys(self):
        n = CommandStore.normalize_keys
        self.assertEqual(n("Shift + Ctrl + K"), "ctrl+shift+k")
        self.assertEqual(n("k+left alt"), "left alt+k")
        self.assertEqual(n("Left Control+X"), "left ctrl+x")
        self.assertEqual(n("num 7"), n("numpad7"))
        self.assertEqual(n("Numpad 7"), "numpad7")
        self.assertEqual(n("alt f4"), "alt+f4")
        self.assertEqual(n("spacebar"), "space")
        self.assertEqual(n("Return"), "enter")
        self.assertEqual(n("esc"), "escape")
        self.assertEqual(n("page up"), "pageup")
        self.assertNotEqual(n("alt+f4"), n("left alt+f4"))
        self.assertEqual(n(""), "")

    def test_key_display(self):
        self.assertEqual(key_display({"type": "tap", "keys": "n"}), "n")
        self.assertEqual(key_display({"type": "mouse", "button": "right", "kind": "click", "keys": "left alt"}),
                         "left alt+right mouse")
        self.assertEqual(key_display({"type": "mouse", "button": "left", "kind": "click"}), "left mouse")
        self.assertEqual(key_display({"type": "scroll", "direction": "up", "amount": 1}), "scroll up")
        self.assertEqual(key_display({"type": "system", "op": "stop_speaking"}), "")

    def test_key_names_subset_of_backend_vk_map(self):
        self.assertEqual(set(KEY_NAMES) - vk_key_names(), set())


if __name__ == "__main__":
    unittest.main()
