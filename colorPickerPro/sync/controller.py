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
from .photoshop_color_sync import (
    PhotoshopSync,
    com_initialize,
    com_uninitialize,
)
from .window_focus import WindowFocusReturner


def _close(a: tuple | None, b: tuple | None, tol: int = 2) -> bool:
    if a is None or b is None:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


#: Status pill texts shared with the GUI (``main.py`` maps them to colours).
STATUS_IDLE = "未同步"
STATUS_CONNECTING = "连接中…"
STATUS_NOT_RUNNING = "未启动"
STATUS_DISCONNECTED = "未连接"
STATUS_SYNCED = "已同步"
STATUS_WRITE_FAILED = "写入失败"

TARGET_NAMES = {"udm": "UDM Paint", "ps": "Photoshop"}

#: 读颜色轮询间隔（秒）。UDM 读内存很便宜；Photoshop 每次都要跑一次
#: ExtendScript（DoJavaScript 单次约 50ms），按 10Hz 读会把 PS 拖卡。
READ_INTERVAL = {"udm": 0.1, "ps": 0.4}

#: 写入失败提示保留多久（秒）：失败后下一次读色会把颜色拉回真实值，
#: 提示不必一直挂着。
WRITE_ERROR_TTL = 5.0


def status_text(connected: bool, enabled: bool, status: dict,
                target: str = "绘画软件",
                write_error: str = "") -> tuple[str, str]:
    """Return ``(label, detail)`` for the sync status pill.

    The label is short enough for the 220 px pill; the detail becomes its
    tooltip.  The important distinction for the user is *why* nothing is
    syncing yet: 「未启动」 (the drawing app is not running) versus
    「未连接」 (it runs but the colour bridge is not up — version/permission),
    and 「写入失败」 (reads work but pushing a colour raised an error).
    """
    if not enabled:
        return STATUS_IDLE, "同步未开启；点击「开启同步」后开始连接。"
    if connected:
        if write_error:
            return STATUS_WRITE_FAILED, write_error
        return STATUS_SYNCED, ""
    detail = str(status.get("lastError") or "").strip()
    if status.get("running") is False:
        return (STATUS_NOT_RUNNING,
                detail or f"未检测到 {target} 进程，请先启动 {target} 再开启同步。")
    return (STATUS_DISCONNECTED,
            detail or f"已找到 {target}，但颜色数据尚未连通（请检查版本或权限）。")


class SyncController(QThread):
    # A colour that changed inside the target app: (r, g, b)
    colorChanged = Signal(int, int, int)
    # Connection status for the active mode: (mode, connected)
    statusChanged = Signal(str, bool)
    # Status pill text and its tooltip detail for the active mode.
    messageChanged = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._mode = "off"          # "off" | "udm" | "ps"
        self._enabled = False
        self._pending: tuple | None = None
        self._stop = False

        self.udm = UDMSync()
        self.ps = PhotoshopSync()
        # GUI-thread only: hands the window focus back to the synced app.
        self._focus = WindowFocusReturner()

        self._last_written: tuple | None = None
        self._last_observed: tuple | None = None
        self._last_connected: bool | None = None
        self._last_message: tuple[str, str] = ("", "")
        self._last_write_error: str = ""
        self._write_error_ts: float = 0.0
        self._last_read: dict[str, float] = {}
        self._last_color: dict[str, dict | None] = {}

    # ----- public API (GUI thread) ---------------------------------------
    def set_mode(self, mode: str) -> None:
        mode = mode if mode in ("udm", "ps", "off") else "off"
        with self._lock:
            self._mode = mode
            self._pending = None
            self._last_written = None
            self._last_observed = None
            self._last_connected = None
            self._last_write_error = ""
            self._last_read.clear()
            self._last_color.clear()
            # 重新开启后必须再发一次同样的文案，否则「连接中…」会一直留着。
            self._last_message = ("", "")

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if not enabled:
                self._pending = None
            self._last_connected = None
            self._last_message = ("", "")

    def write_color(self, r: int, g: int, b: int) -> None:
        with self._lock:
            self._pending = (r, g, b)

    def stop_thread(self, timeout_ms: int = 3000) -> None:
        self._stop = True
        if not self.wait(timeout_ms):
            self.terminate()
            self.wait(500)

    # ----- focus hand-back (GUI thread) -----------------------------------
    def sync_target(self) -> tuple[int | None, tuple[str, ...]] | None:
        """``(pid, process names)`` of the sync target, None while inactive.

        The pid comes from the live backend; the process names are the
        fallback used when the backend has not attached yet (the app is
        running but the colour bridge is still connecting).
        """
        with self._lock:
            mode = self._mode
            enabled = self._enabled
        if mode == "off" or not enabled:
            return None
        backend = self.udm if mode == "udm" else self.ps
        try:
            pid = backend.target_pid
        except Exception:
            pid = None
        try:
            names = tuple(backend.focus_process_names())
        except Exception:
            names = ()
        if not pid and not names:
            return None
        return pid, names

    def return_focus(self) -> bool:
        """Give the window focus back to the app being synced with."""
        target = self.sync_target()
        if target is None:
            return False
        pid, names = target
        try:
            return self._focus.focus(pid=pid, process_names=names)
        except Exception as exc:
            print(f"[Sync] focus return failed: {exc!r}", flush=True)
            return False

    # ----- worker thread ---------------------------------------------------
    def run(self) -> None:
        # COM 必须在线程内初始化：Photoshop 走 COM 时，调度线程没有
        # CoInitialize 会让 Dispatch 直接失败（0x800401F0），从而悄悄退回
        # 脚本桥并误报「已同步」。
        com_ready = com_initialize()
        try:
            while not self._stop:
                time.sleep(0.1)
                try:
                    self._tick()
                except Exception as e:  # never let the loop die silently
                    now = time.time()
                    if now - getattr(self, "_last_err_ts", 0.0) > 5.0:
                        self._last_err_ts = now
                        print(f"[Sync] poll loop error: {e!r}", flush=True)
        finally:
            if com_ready:
                com_uninitialize()

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
            self._emit_status("off", False, "", "")
            return
        if not enabled:
            text, detail = status_text(False, False, {})
            self._emit_status(mode, False, text, detail)
            return

        backend = self.udm if mode == "udm" else self.ps

        # 1) push a pending write from the GUI
        wrote = False
        if pending is not None:
            r, g, b = pending
            if self._apply_write(backend, mode, r, g, b):
                self._last_written = (r, g, b)
                self._last_observed = (r, g, b)
                self._last_write_error = ""
                wrote = True
            else:
                # 写失败要让用户看见，否则界面会一直显示「已同步」。
                self._last_write_error = (
                    str(getattr(backend, "last_error", "") or "").strip()
                    or f"写入 {TARGET_NAMES.get(mode, '目标软件')} 失败"
                )
                self._write_error_ts = time.monotonic()

        # 2) poll the app's live colour back
        now = time.monotonic()
        interval = READ_INTERVAL.get(mode, 0.1)
        last_read = self._last_read.get(mode)
        # 刚写完必须立刻重读，否则会用旧的缓存值把界面颜色「弹回」旧色。
        if (not wrote and last_read is not None
                and now - last_read < interval):
            color = self._last_color.get(mode)   # 复用上次结果，别每 0.1s 打一次 Photoshop
        else:
            color = self._read_color(backend, mode)
            self._last_read[mode] = now
            self._last_color[mode] = color
        # 只有真的读到颜色才算同步上：后端「连上了」但读不到颜色时，
        # 旧代码会显示「已同步」而实际什么都没同步。
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

        write_error = self._last_write_error
        if (write_error
                and time.monotonic() - self._write_error_ts > WRITE_ERROR_TTL):
            self._last_write_error = ""
            write_error = ""
        self._emit_status(
            mode, connected,
            *status_text(connected, True, status,
                         TARGET_NAMES.get(mode, "绘画软件"), write_error))

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

    def _emit_status(self, mode: str, connected: bool, text: str,
                     detail: str = "") -> None:
        if connected != self._last_connected:
            self._last_connected = connected
            self.statusChanged.emit(mode, connected)
        message = (text, detail)
        if message != self._last_message:
            self._last_message = message
            self.messageChanged.emit(text, detail)
