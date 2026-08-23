"""Sync controller — a QThread that mirrors the picker color with an app.

The controller owns the live UDM / Photoshop backends and runs a polling
loop on a worker thread so the GUI never blocks on process memory or COM.
It is a simplified, single-colour-slot adaptation of colorink's
``core.memory_sync``:

* the GUI calls :meth:`write_color` to push the current picker colour to
  the target app;
* the loop polls the app's live colour back and emits :attr:`colorChanged`
  when it differs from anything this controller itself wrote (an external
  change inside the drawing app).

Echo suppression uses a small tolerance plus the last-written value, so a
write that Photoshop/UDM echoes back does not yank the picker.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from .udm_brush_link import UDMSync
from .photoshop_color_sync import PhotoshopSync


def _close(a: tuple | None, b: tuple | None, tol: int = 2) -> bool:
    if a is None or b is None:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class SyncController(QThread):
    # A colour that changed inside the target app: (r, g, b)
    colorChanged = Signal(int, int, int)
    # Connection status for the active mode: (mode, connected)
    statusChanged = Signal(str, bool)
    # Human-readable status / error text for the active mode.
    messageChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._mode = "off"          # "off" | "udm" | "ps"
        self._enabled = False
        self._pending: tuple | None = None
        self._stop = False

        self.udm = UDMSync()
        self.ps = PhotoshopSync()

        self._last_written: tuple | None = None
        self._last_observed: tuple | None = None
        self._last_connected: bool | None = None
        self._last_message: str = ""

    # ----- public API (GUI thread) ---------------------------------------
    def set_mode(self, mode: str) -> None:
        mode = mode if mode in ("udm", "ps", "off") else "off"
        with self._lock:
            self._mode = mode
            self._pending = None
            self._last_written = None
            self._last_observed = None
            self._last_connected = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if not enabled:
                self._pending = None

    def write_color(self, r: int, g: int, b: int) -> None:
        with self._lock:
            self._pending = (r, g, b)

    def stop_thread(self, timeout_ms: int = 3000) -> None:
        self._stop = True
        if not self.wait(timeout_ms):
            self.terminate()
            self.wait(500)

    # ----- worker thread ---------------------------------------------------
    def run(self) -> None:
        while not self._stop:
            time.sleep(0.1)
            try:
                self._tick()
            except Exception as e:  # never let the loop die silently
                now = time.time()
                if now - getattr(self, "_last_err_ts", 0.0) > 5.0:
                    self._last_err_ts = now
                    print(f"[Sync] poll loop error: {e!r}", flush=True)

    def _tick(self) -> None:
        with self._lock:
            mode = self._mode
            enabled = self._enabled
            pending = self._pending
            if pending is not None and mode != "off":
                self._pending = None
            else:
                pending = None
        if mode == "off":
            self._emit_status("off", False, "同步已关闭")
            return
        if not enabled:
            self._emit_status(mode, False, "同步已暂停")
            return

        backend = self.udm if mode == "udm" else self.ps

        # 1) push a pending write from the GUI
        if pending is not None:
            r, g, b = pending
            if self._apply_write(backend, mode, r, g, b):
                self._last_written = (r, g, b)
                self._last_observed = (r, g, b)

        # 2) poll the app's live colour back
        color = self._read_color(backend, mode)
        connected = color is not None
        try:
            status = backend.status() if hasattr(backend, "status") else {}
        except Exception:
            status = {}
        if connected:
            rgb = (color["r"], color["g"], color["b"])
            if not _close(rgb, self._last_written):
                if not _close(rgb, self._last_observed):
                    self._last_observed = rgb
                    self.colorChanged.emit(rgb[0], rgb[1], rgb[2])
            else:
                self._last_observed = rgb
        else:
            self._last_observed = None

        self._emit_status(
            mode, bool(status.get("connected", connected)),
            status.get("lastError", "") if status else "")

    # ----- backend helpers ---------------------------------------------------
    def _apply_write(self, backend, mode: str, r: int, g: int, b: int) -> bool:
        try:
            if mode == "udm":
                return bool(backend.set_color(r, g, b))
            return bool(backend.set_color(r, g, b, color_index=0))
        except Exception as exc:
            print(f"[Sync] write failed: {exc!r}", flush=True)
            return False

    def _read_color(self, backend, mode: str):
        try:
            if mode == "udm":
                return backend.get_color()
            return backend.get_color()  # foreground slot 0
        except Exception:
            return None

    def _emit_status(self, mode: str, connected: bool, message: str) -> None:
        if connected != self._last_connected:
            self._last_connected = connected
            self.statusChanged.emit(mode, connected)
        if message != self._last_message:
            self._last_message = message
            self.messageChanged.emit(message)
