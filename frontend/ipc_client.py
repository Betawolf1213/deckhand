"""Named-pipe client for the Zig backend: threaded JSON-lines I/O with backoff reconnect."""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Callable

try:
    import win32file
    import win32pipe
    import pywintypes
    import winerror
    HAVE_WIN32 = True
except ImportError:
    HAVE_WIN32 = False


PIPE_NAME = r"\\.\pipe\deckhand"
RECONNECT_INITIAL_S = 0.5
RECONNECT_MAX_S = 5.0
READ_CHUNK = 4096


class IpcClient:
    def __init__(self, pipe_name: str = PIPE_NAME) -> None:
        if not HAVE_WIN32:
            raise RuntimeError(
                "pywin32 not installed. Run: pip install -r frontend/requirements.txt"
            )
        self.pipe_name = pipe_name
        self._handle = None
        self._out_q: queue.Queue[bytes] = queue.Queue()
        self._on_message: Callable[[dict[str, Any]], None] | None = None
        self._on_connection: Callable[[bool], None] | None = None
        self._connected = threading.Event()
        self._stopping = threading.Event()
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None

    def on_message(self, cb: Callable[[dict[str, Any]], None]) -> None:
        self._on_message = cb

    def on_connection(self, cb: Callable[[bool], None]) -> None:
        self._on_connection = cb

    def send(self, msg: dict[str, Any]) -> None:
        line = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
        self._out_q.put(line)

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        self._stopping.clear()
        self._reader = threading.Thread(target=self._reader_loop, name="ipc-reader", daemon=True)
        self._writer = threading.Thread(target=self._writer_loop, name="ipc-writer", daemon=True)
        self._reader.start()
        self._writer.start()

    def stop(self) -> None:
        self._stopping.set()
        self._close_handle()
        # Wake the writer if it's blocked on the queue.
        self._out_q.put(b"")

    # ---- Internals ----

    def _reader_loop(self) -> None:
        backoff = RECONNECT_INITIAL_S
        buffer = b""
        while not self._stopping.is_set():
            if not self._connect():
                time.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_S)
                continue
            backoff = RECONNECT_INITIAL_S
            self._connected.set()
            if self._on_connection:
                try: self._on_connection(True)
                except Exception: pass

            try:
                while not self._stopping.is_set():
                    # Peek first: a blocking ReadFile on the shared handle stalls WriteFile.
                    _, avail, _ = win32pipe.PeekNamedPipe(self._handle, 0)
                    if avail == 0:
                        time.sleep(0.01)
                        continue
                    hr, data = win32file.ReadFile(self._handle, min(avail, READ_CHUNK))
                    if not data:
                        break
                    buffer += data
                    while b"\n" in buffer:
                        line, _, buffer = buffer.partition(b"\n")
                        self._dispatch_line(line)
            except pywintypes.error:
                pass
            finally:
                self._connected.clear()
                if self._on_connection:
                    try: self._on_connection(False)
                    except Exception: pass
                self._close_handle()

    def _writer_loop(self) -> None:
        while not self._stopping.is_set():
            line = self._out_q.get()
            if not line:
                continue
            # Wait for a live connection; drop stale outbound after 5s.
            waited = 0.0
            while not self._connected.is_set() and not self._stopping.is_set():
                time.sleep(0.05)
                waited += 0.05
                if waited > 5.0:
                    break
            if not self._connected.is_set():
                continue
            try:
                win32file.WriteFile(self._handle, line)
            except pywintypes.error:
                self._connected.clear()

    def _connect(self) -> bool:
        try:
            self._handle = win32file.CreateFile(
                self.pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
            win32pipe.SetNamedPipeHandleState(
                self._handle,
                win32pipe.PIPE_READMODE_BYTE,
                None, None,
            )
            return True
        except pywintypes.error as e:
            self._handle = None
            if e.winerror == winerror.ERROR_PIPE_BUSY:
                try:
                    win32pipe.WaitNamedPipe(self.pipe_name, 2000)
                except pywintypes.error:
                    pass
            return False

    def _close_handle(self) -> None:
        if self._handle is not None:
            try: win32file.CloseHandle(self._handle)
            except pywintypes.error: pass
            self._handle = None

    def _dispatch_line(self, line: bytes) -> None:
        if not line:
            return
        try:
            msg = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return
        if self._on_message:
            try:
                self._on_message(msg)
            except Exception:
                pass
