"""Tk smoke tests for PHRASES, KEYBINDS, CUSTOM WORDS pages on a real CommandStore (temp files)."""
from __future__ import annotations

import json
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_ctx import FakeContext  # noqa: E402
from services.command_store import CommandStore  # noqa: E402
from test_command_store import DEFAULTS  # noqa: E402
from pages import custom_words, keybinds, phrases  # noqa: E402
from pages.keybind_widget import (  # noqa: E402
    ActionEditor, KeybindEditor, apply_modifiers, event_key_name, split_modifiers,
)


_ROOT: tk.Tk | None = None


def setUpModule():  # one Tk root for the whole module (several roots make ttk print Tcl noise)
    global _ROOT
    _ROOT = tk.Tk()
    _ROOT.withdraw()


def tearDownModule():
    _ROOT.update_idletasks()
    _ROOT.destroy()


class TkTestCase(unittest.TestCase):
    @property
    def root(self) -> tk.Tk:
        return _ROOT

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.default_path = d / "commands.default.json"
        self.user_path = d / "commands.json"
        self.default_path.write_text(json.dumps({"version": 2, "commands": DEFAULTS}), encoding="utf-8")
        self.store = CommandStore(self.default_path, self.user_path)
        self.store.load()
        self.saves = []
        self.store.add_listener(lambda: self.saves.append(1))
        self.ctx = FakeContext(self.root, commands=self.store)
        self.errors = []
        self.infos = []
        patches = [
            mock.patch("tkinter.messagebox.showerror", side_effect=lambda t, m, **k: self.errors.append(m)),
            mock.patch("tkinter.messagebox.showinfo", side_effect=lambda t, m, **k: self.infos.append(m)),
            mock.patch("tkinter.messagebox.showwarning", side_effect=lambda t, m, **k: self.errors.append(m)),
            mock.patch("tkinter.messagebox.askyesno", return_value=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.pages = []

    def tearDown(self):
        for p in self.pages:
            p.destroy()
        self._tmp.cleanup()

    def build(self, module, ctx=None):
        page = module.PAGE_CLASS(self.root, ctx or self.ctx)
        page.pack()
        page.on_show()
        self.root.update_idletasks()
        self.pages.append(page)
        return page

    def saved(self, cid=None):
        cmds = json.loads(self.user_path.read_text(encoding="utf-8"))["commands"]
        if cid is None:
            return cmds
        return next((c for c in cmds if c["id"] == cid), None)

    def assert_info_logged(self):
        self.assertTrue(any(kind == "info" for kind, _ in self.ctx.hist), self.ctx.hist)


class FakeEvent:
    def __init__(self, keysym, keycode):
        self.keysym, self.keycode = keysym, keycode


class KeyHelperTests(TkTestCase):
    def test_split_and_apply_modifiers(self):
        self.assertEqual(split_modifiers("left alt+n"), (False, True, False, "Left", "n"))
        self.assertEqual(split_modifiers("ctrl+shift+k"), (True, False, True, "Standard", "k"))
        self.assertEqual(split_modifiers("left shift"), (False, False, True, "Left", ""))
        self.assertEqual(apply_modifiers("n", False, True, False, "Right"), "right alt+n")
        self.assertEqual(apply_modifiers("left alt+n", True, True, False, "Standard"), "ctrl+alt+n")
        self.assertEqual(apply_modifiers("left alt+n", False, False, False, "Left"), "n")

    def test_event_key_name(self):
        self.assertEqual(event_key_name("a", 65), "a")
        self.assertEqual(event_key_name("A", 65), "a")
        self.assertEqual(event_key_name("exclam", 49), "1")
        self.assertEqual(event_key_name("F12", 123), "f12")
        self.assertEqual(event_key_name("KP_Home", 103), "numpad7")
        self.assertEqual(event_key_name("Return", 13), "enter")
        self.assertEqual(event_key_name("Shift_L", 16), "left shift")
        self.assertEqual(event_key_name("Alt_R", 18), "right alt")
        self.assertEqual(event_key_name("space", 32), "space")
        self.assertIsNone(event_key_name("??", 0))

    def test_keybind_editor_modifiers_and_capture(self):
        ed = KeybindEditor(self.root)
        self.addCleanup(ed.destroy)
        ed.set("left alt+n")
        self.assertTrue(ed.alt_var.get())
        self.assertEqual(ed.side_var.get(), "Left")
        ed.ctrl_var.set(True)
        ed.apply_modifier_toggles()
        self.assertEqual(ed.get(), "left ctrl+left alt+n")
        # capture: hold right ctrl, press K
        ed.start_capture()
        ed.feed_key(FakeEvent("Control_R", 17), pressed=True)
        ed.feed_key(FakeEvent("k", 75), pressed=True)
        self.assertEqual(ed.get(), "right ctrl+k")
        self.assertFalse(ed.capturing)
        # capture a lone modifier (press + release)
        ed.start_capture()
        ed.feed_key(FakeEvent("Shift_L", 16), pressed=True)
        ed.feed_key(FakeEvent("Shift_L", 16), pressed=False)
        self.assertEqual(ed.get(), "left shift")

    def test_action_editor_round_trip(self):
        ed = ActionEditor(self.root)
        self.addCleanup(ed.destroy)
        for action in (
            {"type": "tap", "keys": "left alt+n"},
            {"type": "hold", "keys": "b", "duration_ms": 1200},
            {"type": "mouse", "button": "right", "kind": "click", "keys": "left alt"},
            {"type": "mouse", "button": "left", "kind": "click"},
            {"type": "scroll", "direction": "up", "amount": 1},
            {"type": "system", "op": "say_random", "responses": ["hi"]},
        ):
            with self.subTest(action=action):
                ed.set_action(action)
                self.assertEqual(ed.get_action(), action)
        ed.set_action({"type": "tap", "keys": "k"})
        ed.type_var.set("Hold")
        ed.hold_var.set("abc")
        with self.assertRaises(ValueError):
            ed.get_action()


class PhrasesPageTests(TkTestCase):
    def test_title_and_groups(self):
        self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        page = self.build(phrases)
        self.assertEqual(page.title, "PHRASES")
        self.assertEqual(list(page.group_combo["values"]), self.store.categories())
        page.select_group("Custom Phrases")
        self.assertEqual(page.visible_ids, ["wave"])

    def test_disable_phrase_and_save(self):
        page = self.build(phrases)
        page.select_group("Landing & ATC")
        page.select_command("landing_gear")
        self.assertEqual([p for p, _ in page.phrase_rows], ["landing gear", "gear"])
        dict(page.phrase_rows)["gear"].set(False)
        page.update_preview()
        self.assertIn("landing gear", page.preview_var.get())
        self.assertNotIn('"gear"', page.preview_var.get())
        page.save()
        saved = self.saved("landing_gear")
        self.assertEqual(saved["phrases"], ["landing gear"])
        self.assertEqual(saved["disabled_phrases"], ["gear"])
        self.assertEqual(self.saves, [1])
        self.assert_info_logged()
        self.assertEqual(self.errors, [])

    def test_add_remove_phrase_and_change_action(self):
        page = self.build(phrases)
        page.select_group("Flight")
        page.select_command("vtol")
        page.new_phrase_var.set("Toggle VTOL")
        page.add_phrase()
        page.remove_phrase("vtol")
        page.action_editor.type_var.set("Hold")
        page.action_editor.on_type_changed()
        page.action_editor.keys.set("left ctrl+g")
        page.action_editor.hold_var.set("1.5")
        page.save()
        saved = self.saved("vtol")
        self.assertEqual(saved["phrases"], ["toggle vtol"])
        self.assertEqual(saved["action"], {"type": "hold", "keys": "left ctrl+g", "duration_ms": 1500})

    def test_duplicate_phrase_is_rejected(self):
        page = self.build(phrases)
        page.select_group("Flight")
        page.select_command("vtol")
        page.new_phrase_var.set("power on")
        page.add_phrase()
        page.save()
        self.assertTrue(self.errors)
        self.assertIn("power on", self.errors[-1])
        self.assertTrue(any(kind == "warn" for kind, _ in self.ctx.hist))
        self.assertFalse(self.user_path.exists())
        self.assertEqual(self.store.get("vtol")["phrases"], ["vtol"])

    def test_bad_key_is_rejected(self):
        page = self.build(phrases)
        page.select_group("Flight")
        page.select_command("vtol")
        page.action_editor.keys.set("ctrl+floop")
        page.save()
        self.assertTrue(self.errors)
        self.assertFalse(self.user_path.exists())

    def test_reset_to_default(self):
        self.store.set_phrases("vtol", ["my vtol"], [])
        self.store.save()
        page = self.build(phrases)
        page.select_group("Flight")
        page.select_command("vtol")
        page.reset_to_default()
        self.assertEqual(self.saved("vtol")["phrases"], ["vtol"])
        self.assertEqual([p for p, _ in page.phrase_rows], ["vtol"])

    def test_corrupt_user_file_is_reported(self):
        self.user_path.write_text("{ broken", encoding="utf-8")
        self.store.load()
        self.build(phrases)
        self.assertTrue(any(kind == "warn" and "commands.json" in text for kind, text in self.ctx.hist))

    def test_refreshes_when_store_saved_elsewhere(self):
        page = self.build(phrases)
        self.store.create_custom("Wave", "Emotes", ["wave"], {"type": "tap", "keys": "j"})
        self.store.save()
        self.assertIn("Custom Phrases", page.group_combo["values"])


class KeybindsPageTests(TkTestCase):
    def rows(self, page):
        return list(page.tree.get_children())

    def test_filter_search_clear(self):
        page = self.build(keybinds)
        self.assertEqual(page.title, "KEYBINDS")
        self.assertEqual(len(self.rows(page)), len(DEFAULTS))
        page.search_var.set("F12")
        page.filter_by_keybind()
        self.assertEqual(self.rows(page), ["hide_chat"])
        page.search_var.set("f4")
        page.filter_by_keybind()
        self.assertEqual(self.rows(page), [])
        page.search_var.set("alt+f4")
        page.filter_by_keybind()
        self.assertEqual(self.rows(page), ["quit_game"])
        page.search_var.set("gear")
        page.search_all()
        self.assertEqual(self.rows(page), ["landing_gear"])
        page.clear()
        self.assertEqual(page.search_var.get(), "")
        self.assertEqual(len(self.rows(page)), len(DEFAULTS))
        values = page.tree.item("quit_game", "values")
        self.assertEqual(values[1], "alt+f4")

    def test_show_payload_from_spoken_answer(self):
        # The real Answer payloads from services.questions must filter this page.
        from services import questions
        page = self.build(keybinds)
        a = questions.answer("what is f twelve bound to", self.store.all())
        self.assertEqual(a.page, "KEYBINDS")
        page.show_payload(a.payload)
        self.assertEqual(self.rows(page), ["hide_chat"])
        # Combo keys: the spoken display form ("Alt plus F4") must still filter.
        a = questions.answer("what is alt f four bound to", self.store.all())
        page.show_payload(a.payload)
        self.assertEqual(self.rows(page), ["quit_game"])

    def test_show_payload_by_command(self):
        page = self.build(keybinds)
        page.show_payload({"kind": "by_command", "command_id": "hide_chat"})
        self.assertEqual(tuple(page.tree.selection()), ("hide_chat",))
        page.show_payload("not a dict")  # ignored, no exception

    def test_edit_key_and_save(self):
        page = self.build(keybinds)
        page.select("hide_chat")
        self.assertEqual(page.key_editor.get(), "f12")
        page.key_editor.set("Ctrl + H")
        page.save()
        self.assertEqual(self.saved("hide_chat")["action"], {"type": "tap", "keys": "ctrl+h"})
        self.assertEqual(page.tree.item("hide_chat", "values")[1], "ctrl+h")
        self.assert_info_logged()

    def test_conflict_hint_and_mouse_modifiers(self):
        page = self.build(keybinds)
        page.select("hide_chat")
        page.key_editor.set("k")
        page.update_conflicts()
        self.assertIn("VTOL", page.conflict_var.get())
        page.select("ship_zoom")
        self.assertEqual(page.key_editor.get(), "left alt")
        page.key_editor.set("left ctrl")
        page.save()
        self.assertEqual(self.saved("ship_zoom")["action"],
                         {"type": "mouse", "button": "right", "kind": "click", "keys": "left ctrl"})

    def test_bad_key_rejected(self):
        page = self.build(keybinds)
        page.select("hide_chat")
        page.key_editor.set("floop")
        page.save()
        self.assertTrue(self.errors)
        self.assertFalse(self.user_path.exists())

    def test_scroll_action_not_key_editable(self):
        page = self.build(keybinds)
        page.select("preset_next")
        page.save()
        self.assertTrue(self.errors)
        self.assertFalse(self.user_path.exists())


class CustomWordsPageTests(TkTestCase):
    def fill(self, page, name="Wave Hello", sub="Emotes", key="j"):
        page.clear_form()
        page.name_var.set(name)
        page.subcat_var.set(sub)
        page.key_editor.set(key)
        page.key_editor.ctrl_var.set(True)
        page.key_editor.apply_modifier_toggles()
        page.type_var.set("Hold")
        page.hold_var.set("0.5")
        page.phrase_rows[0][1].set("wave hello")
        page.add_phrase_row("say hi", enabled=False)

    def test_create_select_delete_flow(self):
        page = self.build(custom_words)
        self.assertEqual(page.title, "CUSTOM WORDS")
        self.fill(page)
        page.save()
        self.assertEqual(self.errors, [])
        c = self.saved("wave_hello")
        self.assertTrue(c["custom"])
        self.assertEqual(c["category"], "Emotes")
        self.assertEqual(c["phrases"], ["wave hello"])
        self.assertEqual(c["disabled_phrases"], ["say hi"])
        self.assertEqual(c["action"], {"type": "hold", "keys": "ctrl+j", "duration_ms": 500})
        self.assertEqual(page.existing_ids, ["wave_hello"])
        self.assertIn("Emotes", page.subcat_combo["values"])
        self.assert_info_logged()

        page.select_existing("wave_hello")
        self.assertEqual(page.name_var.get(), "Wave Hello")
        self.assertEqual(page.selected_phrases_list.get(0, "end"), ("wave hello", "say hi (off)"))
        page.selected_phrases_list.selection_set(0)
        page.delete_selected_phrase()
        c = self.saved("wave_hello")
        self.assertEqual(c["phrases"], [])
        self.assertEqual(c["disabled_phrases"], ["say hi"])
        page.selected_phrases_list.selection_set(0)
        page.delete_selected_phrase()  # last phrase -> refused
        self.assertTrue(self.errors)
        self.assertEqual(self.saved("wave_hello")["disabled_phrases"], ["say hi"])

        page.delete_custom_command()
        self.assertIsNone(self.saved("wave_hello"))
        self.assertEqual(page.existing_ids, [])

    def test_edit_existing_custom(self):
        page = self.build(custom_words)
        self.fill(page)
        page.save()
        page.select_existing("wave_hello")
        page.name_var.set("Big Wave")
        page.phrase_rows[0][1].set("big wave")
        page.type_var.set("Tap")
        page.save()
        c = self.saved("wave_hello")
        self.assertEqual(c["label"], "Big Wave")
        self.assertEqual(c["phrases"], ["big wave"])
        self.assertEqual(c["action"], {"type": "tap", "keys": "ctrl+j"})
        self.assertEqual(len([x for x in self.saved() if x["custom"]]), 1)

    def test_validation_errors(self):
        page = self.build(custom_words)
        self.fill(page, name="  ")
        page.save()
        self.assertTrue(self.errors)
        self.fill(page, name="Clash")
        page.phrase_rows[0][1].set("gear")
        page.save()
        self.assertIn("gear", self.errors[-1])
        self.fill(page, name="No phrases")
        for _, text_var, *_ in page.phrase_rows:
            text_var.set("")
        page.save()
        self.assertFalse(self.user_path.exists())
        self.assertTrue(all(kind == "warn" for kind, _ in self.ctx.hist))

    def test_phrase_rows_add_remove(self):
        page = self.build(custom_words)
        page.clear_form()
        self.assertEqual(len(page.phrase_rows), 1)
        page.add_phrase_row("two")
        page.add_phrase_row("three")
        page.remove_phrase_row(1)
        self.assertEqual([r[1].get() for r in page.phrase_rows], ["", "three"])


class ReadOnlyContextTests(TkTestCase):
    def test_pages_build_with_plain_fake_commands(self):
        ctx = FakeContext(self.root, commands=DEFAULTS)
        for module in (phrases, keybinds, custom_words):
            with self.subTest(module.__name__):
                page = self.build(module, ctx)
                self.assertTrue(page.read_only)


class RealDefaultsTests(TkTestCase):
    def test_pages_build_with_shipped_defaults(self):
        from test_commands_default import DEFAULT_FILE
        store = CommandStore(DEFAULT_FILE, self.user_path)
        store.load()
        ctx = FakeContext(self.root, commands=store)
        for module in (phrases, keybinds, custom_words):
            self.build(module, ctx)
        kb = self.pages[1]
        kb.search_var.set("num 7")
        kb.filter_by_keybind()
        self.assertEqual(list(kb.tree.get_children()), ["shield_top"])


if __name__ == "__main__":
    unittest.main()
