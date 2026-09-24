"""Tk GUI shell + AppContext; threads only enqueue to self._q, tracebacks log to %TEMP%."""
from __future__ import annotations

import importlib
import json
import logging
import logging.handlers
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pages  # noqa: E402
from app_paths import (  # noqa: E402
    APP_NAME,
    APP_VERSION,
    COMMANDS_DEFAULT,
    COMMANDS_JSON,
    FRONTEND_LOG,
    UI_SETTINGS,
    ensure_dirs,
    load_dotenv,
)
from pages.base import Page  # noqa: E402
from services import themes, ui_settings  # noqa: E402
from services.tts_settings import TtsSettings  # noqa: E402

log = logging.getLogger("deckhand")
log.addHandler(logging.NullHandler())
log.propagate = False

WINDOW_TITLE = APP_NAME
DEFAULT_GEOMETRY = "1220x800"
PUMP_MS = 50
NO_ANSWER = "Sorry, I can't answer that yet."
_AUTO = object()


# ------------------------------------------------------------------ error logging


def install_error_logging(path: Path | str = FRONTEND_LOG) -> logging.Logger:
    """Send uncaught exceptions (main + worker threads) to `path`."""
    path = Path(path)
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path.resolve()
               for h in log.handlers):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
            log.addHandler(h)
        except OSError:
            pass
    log.setLevel(logging.INFO)

    def excepthook(exc_type, exc, tb):
        log.critical("uncaught exception\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    def thread_hook(args):
        log.error("uncaught exception in thread %s\n%s", getattr(args.thread, "name", "?"),
                  "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    return log


# ------------------------------------------------------------------ fallbacks


class ReadOnlyCommandStore:
    """Used only if services.command_store is missing/broken: reads the effective JSON."""

    def __init__(self, default_path: Path = COMMANDS_DEFAULT, user_path: Path = COMMANDS_JSON) -> None:
        self.default_path = Path(default_path)
        self.user_path = Path(user_path)
        self._commands: list[dict] = []
        self._listeners: list[Callable[[], None]] = []

    def load(self) -> None:
        path = self.user_path if self.user_path.exists() else self.default_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cmds = data.get("commands", []) if isinstance(data, dict) else []
        except (OSError, ValueError) as e:
            log.error("could not read %s: %s", path, e)
            cmds = []
        self._commands = [c for c in cmds if isinstance(c, dict)]

    def all(self) -> list[dict]:
        return list(self._commands)

    def get(self, command_id: str) -> dict | None:
        return next((c for c in self._commands if c.get("id") == command_id), None)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for c in self._commands:
            cat = "Custom Phrases" if c.get("custom") else c.get("category", "Other")
            if cat not in seen:
                seen.append(cat)
        return seen

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)


class PlaceholderPage(Page):
    """Shown instead of a page whose module is missing or crashed while building."""

    def __init__(self, parent: tk.Misc, ctx: Any, title: str, error: str) -> None:
        self.title = title
        self.error = error
        super().__init__(parent, ctx)

    def build(self) -> None:
        ttk.Label(self, text=self.title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="This page is not available right now.", style="Muted.TLabel").pack(anchor="w")
        t = tk.Text(self, height=12, wrap="word", font=("Consolas", 9))
        t.pack(fill="both", expand=True, pady=(8, 0))
        self.ctx.theme.style_text(t)
        t.insert("1.0", self.error)
        t.configure(state="disabled")


# ------------------------------------------------------------------ app


class App:
    """The GUI shell and the AppContext handed to every page."""

    def __init__(self, root: tk.Tk, ipc: Any = None, settings_path: Path | str = UI_SETTINGS,
                 answer_fn: Any = _AUTO, page_order: dict[str, str] | None = None,
                 command_store: Any = _AUTO) -> None:
        self.root = root
        self.settings_path = Path(settings_path)
        self._q: queue.Queue[tuple] = queue.Queue()
        self._closing = False
        self._pump_job: str | None = None
        self._pages_ready = False
        self._connected = False

        root.title(WINDOW_TITLE)
        root.report_callback_exception = self._report_tk_error
        root.minsize(980, 640)

        self.settings: dict[str, Any] = ui_settings.load(self.settings_path)
        self._restore_geometry()

        from pages.voice import HistoryBuffer  # the buffer lives with its renderer
        self.history_buffer = HistoryBuffer()
        self._startup_notes: list[tuple[str, str]] = []
        self._load_error_history_seen: set[str] = set()

        self.theme = themes.Theme(root, self.settings.get("theme"))
        self.commands = self._make_command_store() if command_store is _AUTO else command_store
        try:
            self.commands.add_listener(self._on_commands_saved)
        except Exception as e:  # noqa: BLE001
            log.error("command store add_listener failed: %s", e)
        self._answer_fn = self._load_answer_fn() if answer_fn is _AUTO else answer_fn

        if ipc is None:
            from ipc_client import IpcClient
            ipc = IpcClient()
        self.ipc = ipc
        self.ipc.on_message(lambda m: self._q.put(("ipc", m)))
        self.ipc.on_connection(lambda ok: self._q.put(("ipc", {"type": "_connection", "connected": bool(ok)})))

        self.pages: dict[str, Page] = {}
        self.current_page: str | None = None
        self._build_shell(pages.PAGE_ORDER if page_order is None else page_order)

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.ipc.start()
        self._pump_job = root.after(PUMP_MS, self._tick)

    # ---------------------------------------------------------- construction
    def _restore_geometry(self) -> None:
        window = self.settings.get("window")
        geo = window.get("geometry") if isinstance(window, dict) else None
        try:
            self.root.geometry(geo if isinstance(geo, str) and geo else DEFAULT_GEOMETRY)
        except tk.TclError:
            self.root.geometry(DEFAULT_GEOMETRY)

    def _make_command_store(self) -> Any:
        try:
            from services.command_store import CommandStore
            store = CommandStore(default_path=COMMANDS_DEFAULT, user_path=COMMANDS_JSON)
            store.load()
            return store
        except Exception as e:  # noqa: BLE001 - missing/half-written module must not kill the GUI
            log.error("services.command_store unavailable, using read-only commands: %s", e, exc_info=True)
            self._startup_notes.append((f"Command editor unavailable ({type(e).__name__}: {e}); "
                                        "commands are read-only.", "warn"))
            store = ReadOnlyCommandStore()
            store.load()
            return store

    def _load_answer_fn(self) -> Callable | None:
        try:
            from services.questions import answer
            return answer
        except Exception as e:  # noqa: BLE001
            log.warning("services.questions unavailable: %s", e)
            self._startup_notes.append(("Spoken questions are not available yet.", "info"))
            return None

    def _build_shell(self, order: dict[str, str]) -> None:
        root = self.root
        header = ttk.Frame(root, style="Header.TFrame", padding=(14, 8))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME.upper(), style="HeaderTitle.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{APP_VERSION}", style="HeaderMuted.TLabel").pack(side="left", padx=(8, 20))
        self.status_var = tk.StringVar(value="BACKEND OFFLINE")
        self.status_label = ttk.Label(header, textvariable=self.status_var, style="HeaderBad.TLabel")
        self.status_label.pack(side="left")
        self.listen_state_var = tk.StringVar(value="—")
        self.listen_label = ttk.Label(header, textvariable=self.listen_state_var, style="HeaderMuted.TLabel")
        self.listen_label.pack(side="left", padx=(16, 0))
        # Load-error banner (hidden unless CommandStore.load_error is set).
        self.load_warn_var = tk.StringVar(value="")
        self.load_warn_lbl = ttk.Label(header, textvariable=self.load_warn_var,
                                       style="HeaderBad.TLabel", cursor="hand2")
        self.load_warn_lbl.bind("<Button-1>", lambda _e: self._show_load_error_dialog())
        # Not packed here — _check_load_error() manages visibility.

        self.page_var = tk.StringVar()
        combo = ttk.Combobox(header, textvariable=self.page_var, state="readonly", width=24,
                             values=list(order))
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda _e: self.show_page(self.page_var.get()))
        ttk.Label(header, text="PAGE", style="HeaderMuted.TLabel").pack(side="right", padx=(0, 6))

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, style="Sidebar.TFrame", padding=(6, 8))
        sidebar.pack(side="left", fill="y")
        self.content = ttk.Frame(body, padding=(6, 4))
        self.content.pack(side="left", fill="both", expand=True)

        self.nav_buttons: dict[str, ttk.Button] = {}
        for name in order:
            b = ttk.Button(sidebar, text=name, style="Nav.TButton", width=18,
                           command=lambda n=name: self.show_page(n))
            b.pack(fill="x", pady=1)
            self.nav_buttons[name] = b

        for name, module in order.items():
            self.pages[name] = self._build_page(name, module)

        self._pages_ready = True
        voice = self.pages.get("VOICE")
        if voice is not None and hasattr(voice, "show_entries"):
            voice.show_entries(list(self.history_buffer.entries))
        for text, kind in self._startup_notes:
            self.history(text, kind)
        self._check_load_error()
        if self.pages:
            self.show_page(next(iter(self.pages)))

    def _check_load_error(self) -> None:
        """Reflect commands.load_error in the header banner + history."""
        err = getattr(self.commands, "load_error", None)
        if err:
            self.load_warn_var.set("⚠ commands.json load error (click)")
            if not self.load_warn_lbl.winfo_ismapped():
                self.load_warn_lbl.pack(side="left", padx=(16, 0))
            if err not in self._load_error_history_seen:
                self._load_error_history_seen.add(err)
                self.history(err, "warn")
        else:
            self.load_warn_var.set("")
            if self.load_warn_lbl.winfo_ismapped():
                self.load_warn_lbl.pack_forget()

    def _show_load_error_dialog(self) -> None:
        from tkinter import messagebox
        err = getattr(self.commands, "load_error", None) or "No error."
        retry = messagebox.askyesno(
            "commands.json load error",
            f"{err}\n\nThe app is running on the default command set. "
            "Retry loading commands.json now?",
            parent=self.root,
        )
        if retry:
            try:
                self.commands.load()
            except Exception as e:  # noqa: BLE001
                self.history(f"Retry failed: {e}", "error")
                self._check_load_error()
                return
            self._check_load_error()
            if not getattr(self.commands, "load_error", None):
                self.reload_backend_commands()
                self.history("commands.json reloaded successfully.", "info")

    def _build_page(self, name: str, module: str) -> Page:
        try:
            mod = importlib.import_module(f"pages.{module}")
            cls = getattr(mod, "PAGE_CLASS")
            return cls(self.content, self)
        except ModuleNotFoundError as e:
            if e.name != f"pages.{module}":
                return self._page_failed(name, module, e)
            # Expected while a page is still being written: one line, no traceback.
            log.warning("page %s: module pages.%s not found", name, module)
            self.history(f"Page {name} is not available yet (pages/{module}.py missing).", "warn")
            return PlaceholderPage(self.content, self, name, f"frontend/pages/{module}.py does not exist yet.")
        except Exception as e:  # noqa: BLE001 - one broken page never takes the app down
            return self._page_failed(name, module, e)

    def _page_failed(self, name: str, module: str, e: BaseException) -> Page:
        tb = traceback.format_exc()
        log.error("page %s (pages.%s) failed to load\n%s", name, module, tb)
        self.history(f"Page {name} failed to load: {type(e).__name__}: {e}", "error")
        return PlaceholderPage(self.content, self, name, f"pages.{module} could not be loaded:\n\n{tb}")

    # ---------------------------------------------------------- AppContext
    def send(self, msg: dict) -> None:
        connected = getattr(self.ipc, "is_connected", lambda: True)
        if not connected():
            log.debug("dropped (disconnected): %s", msg.get("type"))
            return
        self.ipc.send(msg)

    def speak(self, text: str) -> None:
        if text and text.strip():
            self.send({"type": "speak_text", "text": text})

    def history(self, text: str, kind: str = "info") -> None:
        entry = self.history_buffer.add(kind, text)
        if entry is None:
            return
        if entry.kind in ("warn", "error"):
            log.warning("history %s: %s", entry.kind, entry.text)
        if not self._pages_ready:
            return
        voice = self.pages.get("VOICE")
        if voice is not None and hasattr(voice, "append_entry"):
            try:
                voice.append_entry(entry)
            except Exception:  # noqa: BLE001
                log.exception("history render failed")

    def run_bg(self, fn: Callable[[], Any], on_done: Callable[[Any, Exception | None], None]) -> None:
        def work() -> None:
            try:
                result, err = fn(), None
            except Exception as e:  # noqa: BLE001 - delivered to on_done
                log.warning("background task failed: %s", e, exc_info=True)
                result, err = None, e
            if not self._closing:
                self._q.put(("call", on_done, (result, err)))

        threading.Thread(target=work, name="deckhand-bg", daemon=True).start()

    def show_page(self, name: str, payload: Any = None) -> None:
        page = self.pages.get(name)
        if page is None:
            log.warning("show_page: unknown page %r", name)
            return
        if self.current_page and self.current_page != name:
            self.pages[self.current_page].pack_forget()
        page.pack(fill="both", expand=True)
        self.current_page = name
        self.page_var.set(name)
        for n, b in self.nav_buttons.items():
            b.configure(style="NavActive.TButton" if n == name else "Nav.TButton")
        self._safe(page.on_show)
        if payload is not None:
            self._safe(page.show_payload, payload)

    def save_settings(self) -> None:
        try:
            ui_settings.save(self.settings_path, self.settings)
        except OSError as e:
            log.error("could not save %s: %s", self.settings_path, e)
            self.history(f"Could not save settings: {e}", "warn")

    def reload_backend_commands(self) -> None:
        self.send({"type": "reload_config"})

    def _on_commands_saved(self) -> None:
        """CommandStore listener — fires after every successful save."""
        self.reload_backend_commands()
        # A successful save writes commands.json and clears whatever old file was corrupt.
        if getattr(self, "_pages_ready", False):
            self._check_load_error()

    # ---------------------------------------------------------- IPC pump
    def _tick(self) -> None:
        self._pump_job = None
        if self._closing:
            return
        self.pump()
        if not self._closing:
            self._pump_job = self.root.after(PUMP_MS, self._tick)

    def pump(self) -> None:
        """Drain queued IPC messages and background results on the Tk thread."""
        while not self._closing:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                return
            if item[0] == "ipc":
                self._safe(self.handle_message, item[1])
            elif item[0] == "call":
                self._safe(item[1], *item[2])

    def handle_message(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        t = msg.get("type")
        if t == "_connection":
            self._on_connection(bool(msg.get("connected")))
        elif t == "status":
            self._set_listen_state(bool(msg.get("listening")))
        elif t == "system_action" and msg.get("op") == "stop_listening":
            self._set_listen_state(False)
        elif t == "question":
            self._handle_question(str(msg.get("text", "")))
        for name, page in self.pages.items():
            try:
                page.on_backend_message(msg)
            except Exception:  # noqa: BLE001 - keep dispatching to the other pages
                log.exception("page %s failed handling %s", name, t)

    def _on_connection(self, ok: bool) -> None:
        self._connected = ok
        if ok:
            self.status_var.set("BACKEND CONNECTED")
            self.status_label.configure(style="HeaderGood.TLabel")
            # Ask the backend to replay mic_ready/status/hotkey_status, then push our settings.
            self.send({"type": "ping"})
            for m in TtsSettings.from_dict(self.settings.get("tts")).ipc_messages():
                self.send(m)
            self.send({"type": "set_hotkey", "chord": ui_settings.hotkey_of(self.settings)})
            dev = self.settings.get("audio_device_id")
            if isinstance(dev, str) and dev:
                self.send({"type": "set_audio_device", "id": dev})
            self.send({"type": "list_audio_devices"})
            log.info("backend connected")
        else:
            self.status_var.set("BACKEND OFFLINE")
            self.status_label.configure(style="HeaderBad.TLabel")
            self.listen_state_var.set("—")
            self.listen_label.configure(style="HeaderMuted.TLabel")
            log.info("backend disconnected")

    def _set_listen_state(self, listening: bool) -> None:
        self.listen_state_var.set("LISTENING" if listening else "PAUSED")
        self.listen_label.configure(style="HeaderAccent.TLabel" if listening else "HeaderMuted.TLabel")

    # ---------------------------------------------------------- spoken questions
    def _handle_question(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.history(text, "heard")
        fn = self._answer_fn
        if fn is None:
            self._answer_done(None, None)
            return
        commands = self.commands.all()
        self.run_bg(lambda: fn(text, commands), self._answer_done)

    def _answer_done(self, result: Any, err: Exception | None) -> None:
        speech = getattr(result, "speech", "") if err is None and result is not None else ""
        if not speech:
            if err is not None:
                self.history(f"Question failed: {err}", "error")
            self.speak(NO_ANSWER)
            self.history(NO_ANSWER, "answer")
            return
        self.speak(speech)
        self.history(speech, "answer")
        for line in getattr(result, "details", None) or []:
            self.history(str(line), "answer")
        page = getattr(result, "page", None)
        if page:
            self.show_page(page, getattr(result, "payload", None))

    # ---------------------------------------------------------- errors / shutdown
    def _safe(self, fn: Callable, *args: Any) -> None:
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            log.exception("error in %s", getattr(fn, "__qualname__", fn))
            try:
                self.history(f"Internal error: {type(e).__name__}: {e}", "error")
            except Exception:  # noqa: BLE001
                pass

    def _report_tk_error(self, exc_type, exc, tb) -> None:
        log.error("Tk callback error\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            self.history(f"Internal error: {exc_type.__name__}: {exc}", "error")
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._pump_job is not None:
            try:
                self.root.after_cancel(self._pump_job)
            except tk.TclError:
                pass
            self._pump_job = None
        try:
            if self.root.state() == "normal":
                self.settings["window"] = {"geometry": self.root.geometry()}
                self.save_settings()
        except tk.TclError:
            pass
        try:
            self.ipc.stop()
        except Exception:  # noqa: BLE001
            log.exception("ipc stop failed")
        log.info("frontend closed")
        try:
            self.root.update_idletasks()  # let ttk's pending <<ThemeChanged>> run before destroy
        except tk.TclError:
            pass
        self.root.destroy()


def main() -> None:
    if sys.stderr is None or sys.stdout is None:  # pythonw: no console streams
        try:
            stream = open(FRONTEND_LOG, "a", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with
            sys.stdout = sys.stdout or stream
            sys.stderr = sys.stderr or stream
        except OSError:
            pass
    install_error_logging(FRONTEND_LOG)
    log.info("frontend starting (%s %s, python %s)", APP_NAME, APP_VERSION, sys.version.split()[0])
    ensure_dirs()
    load_dotenv()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
