"""Tests for services.themes (presets, custom colours, ttk application)."""
from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import themes  # noqa: E402

KEYS = {"bg", "panel", "fg", "muted", "accent", "accent_fg", "entry_bg", "border", "good", "warn", "bad"}


class PresetTests(unittest.TestCase):
    def test_six_presets_with_industrial_orange_default(self):
        self.assertEqual(
            list(themes.PRESETS),
            ["Midnight Blue", "Blackout", "Purple Nebula", "Cyan", "Industrial Orange", "Danger Red"],
        )
        self.assertEqual(themes.DEFAULT_PRESET, "Industrial Orange")

    def test_every_preset_defines_every_contract_key(self):
        for name, colors in themes.PRESETS.items():
            self.assertEqual(set(colors), KEYS, name)

    def test_upstream_colours_are_mapped_onto_our_keys(self):
        orange = themes.PRESETS["Industrial Orange"]
        self.assertEqual(orange["bg"], "#120d08")
        self.assertEqual(orange["panel"], "#1c150e")
        self.assertEqual(orange["entry_bg"], "#291e13")  # upstream panel2
        self.assertEqual(orange["fg"], "#fff4e8")        # upstream text
        self.assertEqual(orange["accent"], "#ffad42")
        self.assertEqual(themes.PRESETS["Midnight Blue"]["accent"], "#4da3ff")


class HelperTests(unittest.TestCase):
    def test_accent_text_is_dark_on_bright_and_white_on_dark(self):
        self.assertEqual(themes.accent_text_color("#ffffff"), "#130d08")
        self.assertEqual(themes.accent_text_color("#ffad42"), "#130d08")
        self.assertEqual(themes.accent_text_color("#202060"), "#ffffff")

    def test_normalize_hex(self):
        self.assertEqual(themes.normalize_hex("#ABCDEF"), "#abcdef")
        self.assertEqual(themes.normalize_hex("abc"), "#aabbcc")
        self.assertIsNone(themes.normalize_hex("#12"))
        self.assertIsNone(themes.normalize_hex("red"))
        self.assertIsNone(themes.normalize_hex(None))


class ResolveTests(unittest.TestCase):
    def test_missing_settings_resolve_to_default_preset(self):
        self.assertEqual(themes.resolve(None), themes.PRESETS["Industrial Orange"])
        self.assertEqual(themes.resolve({}), themes.PRESETS["Industrial Orange"])

    def test_unknown_preset_falls_back_to_default(self):
        self.assertEqual(themes.resolve({"preset": "Hot Pink"}), themes.PRESETS["Industrial Orange"])

    def test_custom_overrides_apply_on_top_of_the_preset(self):
        colors = themes.resolve({"preset": "Cyan", "custom": {"bg": "#000000"}})
        self.assertEqual(colors["bg"], "#000000")
        self.assertEqual(colors["accent"], themes.PRESETS["Cyan"]["accent"])

    def test_invalid_or_unknown_overrides_are_ignored(self):
        colors = themes.resolve({"preset": "Cyan", "custom": {"bg": "nope", "sparkle": "#ffffff"}})
        self.assertEqual(colors, themes.PRESETS["Cyan"])

    def test_accent_text_follows_a_custom_accent(self):
        colors = themes.resolve({"preset": "Blackout", "custom": {"accent": "#101050"}})
        self.assertEqual(colors["accent_fg"], "#ffffff")

    def test_display_name_is_custom_when_overrides_exist(self):
        self.assertEqual(themes.display_name({"preset": "Cyan"}), "Cyan")
        self.assertEqual(themes.display_name({"preset": "Cyan", "custom": {"bg": "#000000"}}), "Custom")
        self.assertEqual(themes.display_name(None), "Industrial Orange")

    def test_with_preset_and_with_color_build_new_settings(self):
        s = themes.with_preset("Danger Red")
        self.assertEqual(s, {"preset": "Danger Red", "custom": {}})
        s2 = themes.with_color(s, "accent", "#00FF00")
        self.assertEqual(s2, {"preset": "Danger Red", "custom": {"accent": "#00ff00"}})
        self.assertEqual(s, {"preset": "Danger Red", "custom": {}})  # input untouched
        with self.assertRaises(ValueError):
            themes.with_color(s, "accent", "green")
        with self.assertRaises(ValueError):
            themes.with_preset("Nope")


class TkThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.update_idletasks()
        cls.root.destroy()

    def test_apply_configures_contract_styles(self):
        theme = themes.Theme(self.root, {"preset": "Midnight Blue"})
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup("Title.TLabel", "foreground"), "#4da3ff")
        self.assertEqual(style.lookup("Muted.TLabel", "foreground"), theme.colors["muted"])
        self.assertEqual(style.lookup("Accent.TButton", "background"), "#4da3ff")
        self.assertEqual(style.lookup("TFrame", "background"), theme.colors["bg"])
        for name in ("Card.TFrame", "Card.TLabelframe"):
            self.assertEqual(style.lookup(name, "background"), theme.colors["bg"])

    def test_registered_text_widgets_are_restyled_on_change(self):
        theme = themes.Theme(self.root, {"preset": "Cyan"})
        text = tk.Text(self.root)
        box = tk.Listbox(self.root)
        theme.style_text(text)
        theme.style_listbox(box)
        self.assertEqual(text.cget("background"), themes.PRESETS["Cyan"]["entry_bg"])
        theme.load({"preset": "Danger Red", "custom": {"fg": "#abcdef"}})
        self.assertEqual(text.cget("background"), themes.PRESETS["Danger Red"]["entry_bg"])
        self.assertEqual(text.cget("foreground"), "#abcdef")
        self.assertEqual(box.cget("background"), themes.PRESETS["Danger Red"]["entry_bg"])
        self.assertEqual(theme.name, "Custom")

    def test_destroyed_widgets_are_dropped_without_error(self):
        theme = themes.Theme(self.root, None)
        text = tk.Text(self.root)
        theme.style_text(text)
        text.destroy()
        theme.load({"preset": "Blackout"})  # must not raise
        self.assertEqual(theme.colors["bg"], themes.PRESETS["Blackout"]["bg"])

    def test_listeners_run_after_each_apply(self):
        theme = themes.Theme(self.root, None)
        seen = []
        theme.add_listener(lambda: seen.append(theme.colors["accent"]))
        theme.load({"preset": "Cyan"})
        self.assertEqual(seen, [themes.PRESETS["Cyan"]["accent"]])


if __name__ == "__main__":
    unittest.main()
