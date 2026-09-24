"""Rules for config/commands.default.json; allowed key names are read from backend vk_map.zig."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "config" / "commands.default.json"
VK_MAP = ROOT / "backend" / "src" / "input" / "vk_map.zig"

NEW_UPSTREAM_IDS = {
    "contact_atc", "flight_mode", "unlock_components", "night_vision",
    "quit_star_citizen", "shield_top", "shield_bottom", "weapon_preset_next",
    "weapon_preset_prev", "hide_chat", "ship_zoom", "weapon_4", "jump",
}
SYSTEM_IDS = {"voice_off", "stop_talking", "thanks_computer"}

KEY_ACTIONS = {"tap", "press", "release", "hold"}
MOUSE_BUTTONS = {"left", "right", "middle", "x1", "x2"}
MOUSE_KINDS = {"click", "double", "down", "up"}
SYSTEM_OPS = {"stop_listening", "stop_speaking", "say_random"}
MODIFIERS = {
    "ctrl", "control", "alt", "shift", "left ctrl", "right ctrl", "left control",
    "right control", "left alt", "right alt", "left shift", "right shift",
}


def vk_key_names() -> set[str]:
    """Every key name backend/src/input/vk_map.zig's lookup() accepts (lower-case)."""
    src = VK_MAP.read_text(encoding="utf-8")
    names = set(re.findall(r'\.\{\s*"((?:[^"\\]|\\.)+)"\s*,\s*VK\.', src))
    names = {n.replace("\\\\", "\\") for n in names}
    names |= {chr(c) for c in range(ord("a"), ord("z") + 1)}
    names |= {str(d) for d in range(10)}
    names |= {f"f{n}" for n in range(1, 25)}
    if 'startsWith(u8, lower, "numpad")' in src:
        names |= {f"numpad{d}" for d in range(10)}
    if 'startsWith(u8, lower, "kp_")' in src:
        names |= {"kp_" + r for r in re.findall(r'eql\(u8, rest, "(\w+)"\)', src)}
    return names


def norm_phrase(p: str) -> str:
    return " ".join(p.lower().split())


def action_problems(action: dict, allowed: set[str]) -> list[str]:
    """Validate one action per docs/COMMANDS.md; returns human-readable problems."""
    problems: list[str] = []

    def check_keys(keys, allow_modifier_only=True):
        if not isinstance(keys, str) or not keys.strip():
            problems.append(f"missing keys in {action}")
            return
        parts = [p.strip().lower() for p in keys.split("+")]
        base = [p for p in parts if p not in MODIFIERS]
        for p in parts:
            if p not in allowed:
                problems.append(f"unknown key {p!r} in {keys!r}")
        if len(base) > 1:
            problems.append(f"more than one base key in {keys!r}")
        if not base and not allow_modifier_only:
            problems.append(f"no base key in {keys!r}")

    t = action.get("type")
    if t in KEY_ACTIONS:
        check_keys(action.get("keys"))
        if t == "hold":
            d = action.get("duration_ms")
            if not isinstance(d, int) or not 1 <= d <= 60000:
                problems.append(f"bad duration_ms in {action}")
    elif t == "mouse":
        if action.get("button") not in MOUSE_BUTTONS:
            problems.append(f"bad mouse button in {action}")
        if action.get("kind") not in MOUSE_KINDS:
            problems.append(f"bad mouse kind in {action}")
        if "keys" in action:
            check_keys(action["keys"])
    elif t == "scroll":
        if action.get("direction") not in {"up", "down"}:
            problems.append(f"bad scroll direction in {action}")
        a = action.get("amount")
        if not isinstance(a, int) or not 1 <= a <= 100:
            problems.append(f"bad scroll amount in {action}")
    elif t == "system":
        if action.get("op") not in SYSTEM_OPS:
            problems.append(f"bad system op in {action}")
        if action.get("op") == "say_random":
            r = action.get("responses")
            if not isinstance(r, list) or not r or not all(isinstance(x, str) and x.strip() for x in r):
                problems.append(f"say_random needs non-empty responses in {action}")
    else:
        problems.append(f"unknown action type {t!r}")
    return problems


class DefaultCommandsFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = DEFAULT_FILE.read_text(encoding="utf-8")
        cls.data = json.loads(cls.raw)
        cls.commands = cls.data["commands"]
        cls.by_id = {c["id"]: c for c in cls.commands}

    def test_version_is_2(self):
        self.assertEqual(self.data["version"], 2)

    def test_ids_unique_and_well_formed(self):
        ids = [c["id"] for c in self.commands]
        self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
        for i in ids:
            self.assertRegex(i, r"^[a-z0-9_]+$")

    def test_every_command_has_label_category_and_phrase_lists(self):
        for c in self.commands:
            with self.subTest(c["id"]):
                self.assertTrue(str(c.get("label", "")).strip())
                self.assertTrue(str(c.get("category", "")).strip())
                self.assertIsInstance(c["phrases"], list)
                self.assertTrue(c["phrases"], "defaults ship with >= 1 enabled phrase")
                self.assertIsInstance(c.get("disabled_phrases", []), list)
                self.assertFalse(c.get("custom", False))

    def test_every_phrase_maps_to_exactly_one_command(self):
        owner: dict[str, str] = {}
        clashes = []
        for c in self.commands:
            for p in list(c["phrases"]) + list(c.get("disabled_phrases", [])):
                self.assertTrue(p.strip(), f"empty phrase in {c['id']}")
                n = norm_phrase(p)
                if n in owner:
                    clashes.append(f"{n!r}: {owner[n]} vs {c['id']}")
                owner[n] = c["id"]
        self.assertEqual(clashes, [])

    def test_every_action_valid(self):
        allowed = vk_key_names()
        problems = []
        for c in self.commands:
            problems += [f"{c['id']}: {p}" for p in action_problems(c["action"], allowed)]
        self.assertEqual(problems, [])

    def test_vk_name_parser_sanity(self):
        names = vk_key_names()
        for n in ("a", "0", "f12", "left alt", "right alt", "backspace", "space", "tab", "\\"):
            self.assertIn(n, names)

    def test_new_upstream_actions_present(self):
        self.assertEqual(NEW_UPSTREAM_IDS - self.by_id.keys(), set())

    def test_system_commands_present(self):
        self.assertEqual(SYSTEM_IDS - self.by_id.keys(), set())
        self.assertEqual(self.by_id["voice_off"]["action"], {"type": "system", "op": "stop_listening"})
        self.assertTrue(self.by_id["voice_off"].get("tts_ack"))
        self.assertEqual(self.by_id["stop_talking"]["action"]["op"], "stop_speaking")
        thanks = self.by_id["thanks_computer"]["action"]
        self.assertEqual(thanks["op"], "say_random")
        self.assertGreaterEqual(len(thanks["responses"]), 6)
        for p in ("computer turn off", "computer off", "computer stop listening", "computer stop", "computer disable"):
            self.assertIn(p, self.by_id["voice_off"]["phrases"])
        for p in ("thank you computer", "thanks computer", "thank you robot", "thanks robot"):
            self.assertIn(p, self.by_id["thanks_computer"]["phrases"])

    def test_new_upstream_default_keys(self):
        expect = {
            "contact_atc": "left alt+n", "flight_mode": "left alt+c",
            "unlock_components": "right alt+k", "night_vision": "right alt+l",
            "quit_star_citizen": "alt+f4", "hide_chat": "f12", "weapon_4": "4",
            "jump": "space", "shield_top": "numpad7", "shield_bottom": "numpad1",
        }
        for cid, keys in expect.items():
            with self.subTest(cid):
                self.assertEqual(self.by_id[cid]["action"]["type"], "tap")
                self.assertEqual(self.by_id[cid]["action"]["keys"], keys)
        self.assertEqual(self.by_id["weapon_preset_next"]["action"],
                         {"type": "scroll", "direction": "down", "amount": 1})
        self.assertEqual(self.by_id["weapon_preset_prev"]["action"],
                         {"type": "scroll", "direction": "up", "amount": 1})
        self.assertEqual(self.by_id["ship_zoom"]["action"],
                         {"type": "mouse", "button": "right", "kind": "click", "keys": "left alt"})

    def test_upstream_phrases_merged(self):
        def has(cid, phrase):
            return phrase in self.by_id[cid]["phrases"]
        self.assertTrue(has("landing_gear", "retract gear"))
        self.assertTrue(has("shields_front", "boost front shields"))
        self.assertTrue(has("contact_atc", "request landing"))
        self.assertTrue(has("mobiglas", "open mobi glass"))

    def test_existing_ids_kept(self):
        for cid in ("landing_gear", "flight_ready", "engage_boosters", "quantum_drive",
                    "shields_front", "power_all_off", "map_ping", "screenshot"):
            self.assertIn(cid, self.by_id)


if __name__ == "__main__":
    unittest.main()
