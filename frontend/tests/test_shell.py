"""Shell smoke tests: the real App in a withdrawn Tk root with a stubbed IPC client."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deckhand_ui  # noqa: E402
from fake_ctx import FakeCommands  # noqa: E402
from pages.base import Answer  # noqa: E402
from pages.voice import HistoryBuffer, format_entry  # noqa: E402
from services import themes  # noqa: E402
from services.tts_settings import TEST_PHRASE  # noqa: E402

MY_PAGES = {
    "VOICE": "voice",
    "HOW TO": "how_to",
    "CUSTOMIZE": "customize",
    "GUIDES": "guides",
    "ANNOUNCEMENTS": "announcements",
    "CREDIT": "credit",
    "BROKEN": "no_such_page_module_xyz",
}


class StubIpc:
    def __init__(self):
        self.sent: list[dict] = []
        self.started = False
        self.stopped = False
        self.on_msg = None
        self.on_conn = None

    def on_message(self, cb):
        self.on_msg = cb

    def on_connection(self, cb):
        self.on_conn = cb

    def send(self, msg):
        self.sent.append(msg)

    def is_connected(self):
        return True

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def types(self):
        return [m["type"] for m in self.sent]


# ------------------------------------------------------------------ history


class HistoryBufferTests(unittest.TestCase):
    def test_entries_are_capped(self):
        h = HistoryBuffer(maxlen=3)
        for i in range(5):
            h.add("info", f"line {i}", now=float(i * 10))
        self.assertEqual([e.text for e in h.entries], ["line 2", "line 3", "line 4"])

    def test_unknown_kind_becomes_info(self):
        e = HistoryBuffer().add("sparkles", "x", now=0.0)
        self.assertEqual(e.kind, "info")

    def test_immediate_duplicate_is_dropped_but_later_repeat_is_kept(self):
        h = HistoryBuffer(dedupe_s=3.0)
        self.assertIsNotNone(h.add("heard", "where can I mine iron", now=100.0))
        self.assertIsNone(h.add("heard", "where can I mine iron", now=101.0))
        self.assertIsNotNone(h.add("heard", "where can I mine iron", now=110.0))
        self.assertIsNotNone(h.add("answer", "where can I mine iron", now=110.5))

    def test_format_has_timestamp_and_label(self):
        e = HistoryBuffer().add("command", "Landing Gear", now=time.mktime((2026, 9, 23, 14, 5, 9, 0, 0, -1)))
        self.assertEqual(format_entry(e), "[14:05:09]  COMMAND   Landing Gear")


# ------------------------------------------------------------------ shell


class ShellTestBase(unittest.TestCase):
    page_order = MY_PAGES
    initial_settings: dict = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "ui_settings.json"
        if self.initial_settings:
            self.settings_path.write_text(json.dumps(self.initial_settings), encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        self.ipc = StubIpc()
        self.answers: list[str] = []
        self.answer_result = Answer(speech="Iron: Aberdeen, Daymar.", page="CREDIT",
                                    payload={"ore": "iron"}, details=["Aberdeen", "Daymar"])
        self.app = deckhand_ui.App(
            self.root, ipc=self.ipc, settings_path=self.settings_path,
            answer_fn=self._answer, page_order=self.page_order,
            command_store=FakeCommands([{"id": "landing_gear", "label": "Landing Gear",
                                         "phrases": ["landing gear"], "action": {"type": "tap", "keys": "n"}}]),
        )

    def tearDown(self):
        try:
            self.app.close()
        except tk.TclError:
            pass
        self.tmp.cleanup()

    def _answer(self, text, commands):
        self.answers.append(text)
        return self.answer_result

    def feed(self, *msgs):
        for m in msgs:
            self.ipc.on_msg(m)  # same path as the reader thread
        self.app.pump()

    def connect(self):
        self.ipc.on_conn(True)
        self.app.pump()

    def wait_for(self, cond, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            self.app.pump()
            self.root.update()
            if cond():
                return True
            time.sleep(0.01)
        return False

    def history_texts(self, kind=None):
        return [e.text for e in self.app.history_buffer.entries if kind is None or e.kind == kind]


class ShellStructureTests(ShellTestBase):
    def test_window_title_and_ipc_started(self):
        self.assertEqual(self.root.title(), "Deckhand")
        self.assertTrue(self.ipc.started)

    def test_every_page_is_built_and_broken_module_gets_placeholder(self):
        self.assertEqual(list(self.app.pages), list(MY_PAGES))
        broken = self.app.pages["BROKEN"]
        self.assertIsInstance(broken, deckhand_ui.PlaceholderPage)
        self.assertIn("no_such_page_module_xyz", broken.error)
        self.assertTrue(any("BROKEN" in t for t in self.history_texts("warn")))

    def test_page_that_raises_while_building_gets_placeholder_with_traceback(self):
        import types
        mod = types.ModuleType("pages.exploding_test_page")

        class Exploding(deckhand_ui.Page):
            def build(self):
                raise RuntimeError("kaboom")

        mod.PAGE_CLASS = Exploding
        sys.modules["pages.exploding_test_page"] = mod
        try:
            page = self.app._build_page("EXPLODING", "exploding_test_page")
        finally:
            del sys.modules["pages.exploding_test_page"]
        self.assertIsInstance(page, deckhand_ui.PlaceholderPage)
        self.assertIn("kaboom", page.error)
        self.assertTrue(any("EXPLODING" in t and "kaboom" in t for t in self.history_texts("error")))

    def test_show_page_switches_and_passes_payload(self):
        self.app.show_page("CUSTOMIZE")
        self.assertEqual(self.app.current_page, "CUSTOMIZE")
        self.assertEqual(self.app.page_var.get(), "CUSTOMIZE")
        self.app.show_page("NOT A PAGE")
        self.assertEqual(self.app.current_page, "CUSTOMIZE")

    def test_nav_highlights_current_page(self):
        self.app.show_page("GUIDES")
        self.assertEqual(str(self.app.nav_buttons["GUIDES"].cget("style")), "NavActive.TButton")
        self.assertEqual(str(self.app.nav_buttons["CREDIT"].cget("style")), "Nav.TButton")

    def test_command_store_save_triggers_backend_reload(self):
        for fn in self.app.commands._listeners:
            fn()
        self.assertIn({"type": "reload_config"}, self.ipc.sent)


class ConnectTests(ShellTestBase):
    initial_settings = {"tts": {"enabled": False, "voice_id": "V", "volume": 120, "rate": 2},
                        "audio_device_id": "{mic-2}", "hotkey": "alt+f10"}

    def test_on_connect_pings_and_pushes_settings(self):
        self.connect()
        self.assertEqual(self.ipc.sent[0], {"type": "ping"})
        self.assertIn({"type": "set_tts_enabled", "enabled": False}, self.ipc.sent)
        self.assertIn({"type": "set_tts_voice", "id": "V"}, self.ipc.sent)
        self.assertIn({"type": "set_tts_volume", "volume": 120}, self.ipc.sent)
        self.assertIn({"type": "set_tts_rate", "rate": 2}, self.ipc.sent)
        self.assertIn({"type": "set_hotkey", "chord": "alt+f10"}, self.ipc.sent)
        self.assertIn({"type": "set_audio_device", "id": "{mic-2}"}, self.ipc.sent)
        self.assertEqual(self.ipc.types()[-1], "list_audio_devices")
        self.assertEqual(self.app.status_var.get(), "BACKEND CONNECTED")

    def test_disconnect_updates_status(self):
        self.connect()
        self.ipc.on_conn(False)
        self.app.pump()
        self.assertEqual(self.app.status_var.get(), "BACKEND OFFLINE")


class DefaultConnectTests(ShellTestBase):
    def test_defaults_send_default_hotkey_and_no_audio_device(self):
        self.connect()
        self.assertIn({"type": "set_hotkey", "chord": "ctrl+shift+f12"}, self.ipc.sent)
        self.assertNotIn("set_audio_device", self.ipc.types())


class MessageTests(ShellTestBase):
    def test_mic_ready_shows_device_name_on_voice_and_customize(self):
        self.feed({"type": "mic_ready", "sample_rate": 16000, "channels": 1,
                   "device_id": "{a}", "device_name": "Headset Mic"})
        self.assertIn("Headset Mic", self.app.pages["VOICE"].mic_var.get())
        self.assertIn("Headset Mic", self.app.pages["CUSTOMIZE"].current_device_var.get())

    def test_audio_level_moves_meter(self):
        self.feed({"type": "audio_level", "peak": 0.5})
        self.assertAlmostEqual(self.app.pages["VOICE"].level_var.get(), 50.0)

    def test_audio_devices_fill_picker_and_selection_is_persisted_and_sent(self):
        self.feed({"type": "audio_devices", "current_id": "{a}", "devices": [
            {"id": "{a}", "name": "Headset", "is_default": True},
            {"id": "{b}", "name": "Webcam", "is_default": False}]})
        cust = self.app.pages["CUSTOMIZE"]
        self.assertEqual(list(cust.device_combo["values"]), ["Windows default", "Headset (default)", "Webcam"])
        self.assertEqual(cust.device_combo.current(), 0)  # nothing saved -> Windows default
        cust.select_device(2)
        self.assertIn({"type": "set_audio_device", "id": "{b}"}, self.ipc.sent)
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["audio_device_id"], "{b}")

    def test_hotkey_status_ok_and_failure(self):
        cust = self.app.pages["CUSTOMIZE"]
        self.feed({"type": "hotkey_status", "chord": "ctrl+shift+f12", "ok": True, "error": ""})
        self.assertIn("ctrl+shift+f12", cust.hotkey_status_var.get())
        self.assertIn("active", cust.hotkey_status_var.get().lower())
        self.feed({"type": "hotkey_status", "chord": "f8", "ok": False, "error": "already in use"})
        self.assertIn("already in use", cust.hotkey_status_var.get())
        self.assertTrue(any("already in use" in t for t in self.history_texts("warn")))

    def test_hotkey_save_and_clear(self):
        cust = self.app.pages["CUSTOMIZE"]
        cust.hotkey_var.set("Shift + Ctrl + F9")
        cust.save_hotkey()
        self.assertIn({"type": "set_hotkey", "chord": "ctrl+shift+f9"}, self.ipc.sent)
        self.assertEqual(self.app.settings["hotkey"], "ctrl+shift+f9")
        cust.hotkey_var.set("ctrl+shift")
        n = len(self.ipc.sent)
        cust.save_hotkey()
        self.assertEqual(len(self.ipc.sent), n)  # invalid -> nothing sent
        self.assertIn("invalid", cust.hotkey_status_var.get().lower())
        cust.clear_hotkey()
        self.assertIn({"type": "set_hotkey", "chord": ""}, self.ipc.sent)
        self.assertEqual(self.app.settings["hotkey"], "")

    def test_question_is_answered_spoken_logged_and_page_shown(self):
        self.feed({"type": "question", "text": "where can I mine iron"})
        spoken = {"type": "speak_text", "text": "Iron: Aberdeen, Daymar."}
        self.assertTrue(self.wait_for(lambda: spoken in self.ipc.sent))
        self.assertEqual(self.answers, ["where can I mine iron"])
        self.assertIn("where can I mine iron", self.history_texts("heard"))
        self.assertIn("Iron: Aberdeen, Daymar.", self.history_texts("answer"))
        self.assertIn("Aberdeen", self.history_texts())
        self.assertEqual(self.app.current_page, "CREDIT")

    def test_unanswerable_question_gets_fallback_speech(self):
        self.answer_result = None
        self.feed({"type": "question", "text": "what is the meaning of life"})
        self.assertTrue(self.wait_for(lambda: "speak_text" in self.ipc.types()))
        spoken = [m["text"] for m in self.ipc.sent if m["type"] == "speak_text"]
        self.assertIn("can't answer", spoken[0])
        self.assertEqual(self.app.current_page, "VOICE")

    def test_system_action_stop_listening_clears_listening(self):
        voice = self.app.pages["VOICE"]
        self.feed({"type": "status", "listening": True, "elevated": True, "engine": "vosk"})
        self.assertTrue(voice.listening_var.get())
        self.assertEqual(self.app.listen_state_var.get(), "LISTENING")
        self.feed({"type": "system_action", "op": "stop_listening", "id": "voice_off"})
        self.assertFalse(voice.listening_var.get())
        self.assertEqual(self.app.listen_state_var.get(), "PAUSED")
        self.assertTrue(any("stop" in t.lower() for t in self.history_texts("info")))

    def test_config_reloaded_is_logged(self):
        self.feed({"type": "config_reloaded", "commands": 42, "phrases": 120, "path": "config/commands.json"})
        self.assertTrue(any("42" in t and "120" in t for t in self.history_texts("info")))

    def test_transcript_command_and_no_match_feed_history(self):
        self.feed({"type": "transcript_final", "text": "landing gear", "confidence": 0.9},
                  {"type": "command_fired", "id": "landing_gear"},
                  {"type": "no_match", "text": "banana"},
                  {"type": "log", "level": "error", "msg": "boom"})
        self.assertIn("landing gear", self.history_texts("heard"))
        self.assertTrue(any("Landing Gear" in t for t in self.history_texts("command")))
        self.assertTrue(any("banana" in t for t in self.history_texts("warn")))
        self.assertIn("boom", self.history_texts("error"))
        text = self.app.pages["VOICE"].history_text.get("1.0", "end")
        self.assertIn("COMMAND", text)

    def test_voice_page_controls_send_messages(self):
        voice = self.app.pages["VOICE"]
        voice.stop_speaking()
        self.assertIn({"type": "stop_speaking"}, self.ipc.sent)
        voice.listening_var.set(False)
        voice.toggle_listening()
        self.assertIn({"type": "set_listening", "enabled": True}, self.ipc.sent)
        voice.tts_var.set(False)
        voice.toggle_tts()
        self.assertIn({"type": "set_tts_enabled", "enabled": False}, self.ipc.sent)
        self.assertFalse(self.app.settings["tts"]["enabled"])

    def test_page_exception_in_message_handler_does_not_break_dispatch(self):
        def boom(_msg):
            raise RuntimeError("page bug")
        self.app.pages["HOW TO"].on_backend_message = boom
        self.feed({"type": "audio_level", "peak": 0.25})
        self.assertAlmostEqual(self.app.pages["VOICE"].level_var.get(), 25.0)


class ThemeIntegrationTests(ShellTestBase):
    def test_preset_colour_and_reset_are_applied_and_persisted(self):
        cust = self.app.pages["CUSTOMIZE"]
        cust.select_preset("Cyan")
        self.assertEqual(self.app.theme.colors["accent"], themes.PRESETS["Cyan"]["accent"])
        cust.set_color("bg", "#010203")
        self.assertEqual(self.app.theme.colors["bg"], "#010203")
        self.assertEqual(cust.preset_var.get(), "Custom")
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["theme"], {"preset": "Cyan", "custom": {"bg": "#010203"}})
        cust.reset_theme()
        self.assertEqual(self.app.theme.colors, themes.PRESETS["Industrial Orange"])
        self.assertEqual(cust.preset_var.get(), "Industrial Orange")


class TtsPanelTests(ShellTestBase):
    def test_test_voice_speaks_test_phrase(self):
        self.app.pages["CUSTOMIZE"].test_voice()
        self.assertIn({"type": "speak_text", "text": TEST_PHRASE}, self.ipc.sent)


class FullPageOrderTests(ShellTestBase):
    page_order = None  # the real pages.PAGE_ORDER (other agents' pages may be missing)

    def test_app_builds_with_real_page_order(self):
        import pages
        self.assertEqual(list(self.app.pages), list(pages.PAGE_ORDER))
        for name in self.app.pages:
            self.app.show_page(name)
            self.assertEqual(self.app.current_page, name)


class ShutdownTests(unittest.TestCase):
    def test_close_stops_ipc_and_destroys_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = tk.Tk()
            root.withdraw()
            ipc = StubIpc()
            app = deckhand_ui.App(root, ipc=ipc, settings_path=Path(d) / "s.json",
                                  answer_fn=None, page_order={"VOICE": "voice"},
                                  command_store=FakeCommands([]))
            app.close()
            self.assertTrue(ipc.stopped)
            with self.assertRaises(tk.TclError):
                root.winfo_exists()


class ErrorLogTests(unittest.TestCase):
    def test_hooks_write_tracebacks_to_the_log(self):
        import logging
        import threading
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "front.log"
            old_sys, old_thr = sys.excepthook, threading.excepthook
            try:
                deckhand_ui.install_error_logging(log)
                try:
                    raise ValueError("synthetic failure")
                except ValueError:
                    sys.excepthook(*sys.exc_info())
                for h in logging.getLogger("deckhand").handlers:
                    h.flush()
                self.assertIn("synthetic failure", log.read_text(encoding="utf-8"))
            finally:
                sys.excepthook, threading.excepthook = old_sys, old_thr
                lg = logging.getLogger("deckhand")
                for h in list(lg.handlers):
                    if isinstance(h, logging.FileHandler):
                        h.close()
                        lg.removeHandler(h)


if __name__ == "__main__":
    unittest.main()
