"""Hand the window focus back to the app pixnex is colour-syncing with.

pixnex is a small palette window: the user picks a colour here and then
wants the pen back in the drawing app (UDM Paint, Photoshop, and any
future Clip Studio / CSP backend).  Handing the foreground over is allowed
while *pixnex itself* is the foreground process, so a plain
``SetForegroundWindow`` on the target process' main window succeeds — no
elevation and no ``AllowSetForegroundWindow`` dance is needed.

The module is split so the interesting part stays testable off-Windows:

* :func:`pick_main_window` — pure selection over :class:`WindowInfo`
  records (no ctypes, no Win32);
* :class:`WindowFocusReturner` — the Win32 glue: enumerate the target
  process' top-level windows, then activate the chosen one.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

# 进程不出现在普通枚举里时，用窗口标题/类名里的这些标记识别它。
_PROCESS_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "udmpaintpro": ("udmpaint", "优动漫paint", "udm paint"),
    "udmpaintex": ("udmpaintex", "优动漫paint", "udm paint"),
}

# Window styles / API constants used below (documented in winuser.h).
_GWL_EXSTYLE = -20
_GW_OWNER = 4
_WS_EX_TOOLWINDOW = 0x00000080
_SW_RESTORE = 9


@dataclass(frozen=True)
class WindowInfo:
    """One top-level window of the target process."""

    hwnd: int
    pid: int
    title: str
    visible: bool
    iconic: bool        # minimized, still restorable
    owned: bool         # has an owner window (dialog / popup / tool panel)
    tool_window: bool   # WS_EX_TOOLWINDOW
    area: int           # width * height, 0 for degenerate windows


def pick_main_window(windows: "list[WindowInfo] | tuple[WindowInfo, ...]",
                     preferred: int = 0) -> int:
    """Pick the window that should receive the focus.

    ``preferred`` is a previously used hwnd (the window the user had
    focused last time); it wins whenever it still exists.  Otherwise the
    largest visible, titled, unowned, non-tool window wins — that is the
    application frame rather than a splash screen, hidden helper or
    floating panel.  Returns 0 when there is nothing to focus.
    """
    windows = list(windows)
    if not windows:
        return 0

    if preferred:
        for win in windows:
            if win.hwnd == preferred and (win.visible or win.iconic):
                return win.hwnd

    candidates = [w for w in windows if not w.owned and not w.tool_window]
    if not candidates:
        candidates = [w for w in windows if not w.owned]
    if not candidates:
        candidates = windows

    shown = [w for w in candidates if w.visible or w.iconic]
    if shown:
        candidates = shown

    titled = [w for w in candidates if w.title.strip()]
    if titled:
        candidates = titled

    return max(candidates, key=lambda w: w.area).hwnd


def pids_for_process_names(names) -> "list[int]":
    """Running pids whose executable name matches ``names`` (case-insensitive).

    Window matching runs first: some drawing apps (UDM Paint) deny a later
    ``OpenProcess`` for a while after psutil scans them, so the target process
    must not be touched before the real handle is opened.
    """
    wanted = {str(n).lower() for n in names if n}
    if not wanted or not IS_WINDOWS:
        return []

    pids: list[int] = []
    try:
        pids.extend(pid for pid in _window_pids_for_names(wanted)
                    if pid not in pids)
    except NameError:  # pragma: no cover - non-Windows
        pass
    if pids:
        return pids

    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil ships with the app
        return pids
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            if (proc.info.get("name") or "").lower() in wanted:
                pid = int(proc.info["pid"])
                if pid not in pids:
                    pids.append(pid)
    except Exception:
        pass
    return pids


# ---------------------------------------------------------------------------
# Win32 glue
# ---------------------------------------------------------------------------
if IS_WINDOWS:  # pragma: no cover - exercised on a real desktop only
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.EnumWindows.argtypes = (_WNDENUMPROC, wintypes.LPARAM)
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.IsWindow.argtypes = (wintypes.HWND,)
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    _user32.GetWindow.restype = wintypes.HWND
    _user32.GetWindowRect.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = (
        wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = ()
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.AttachThreadInput.argtypes = (
        wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    _user32.AttachThreadInput.restype = wintypes.BOOL

    _get_window_long = getattr(_user32, "GetWindowLongPtrW", None) \
        or _user32.GetWindowLongW
    _get_window_long.argtypes = (wintypes.HWND, ctypes.c_int)
    _get_window_long.restype = ctypes.c_ssize_t

    _kernel32.GetCurrentThreadId.argtypes = ()
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def _window_pid(hwnd: int) -> int:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    _kernel32.OpenProcess.argtypes = (
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD))
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    def _window_pids_for_names(wanted: set[str]) -> list[int]:
        """PIDs of processes owning a top-level window that identifies them.

        Deliberately does **not** open the target process: some drawing apps
        (UDM Paint) deny a later ``OpenProcess(ALL_ACCESS)`` for a short time
        after any probe handle was opened, which would break the memory sync.
        The executable name is matched against window titles/class names
        instead (e.g. ``GDI+ Window (UDMPaintPRO.exe)``).
        """
        markers: set[str] = set()
        for name in wanted:
            stem = os.path.splitext(name)[0].lower()
            markers.add(name.lower())
            markers.add(stem)
            for hint in _PROCESS_NAME_HINTS.get(stem, ()):  # type: ignore[name-defined]
                markers.add(hint.lower())

        found: list[int] = []
        seen: set[int] = set()

        def _callback(hwnd, _lparam):
            hwnd = int(hwnd)
            pid = _window_pid(hwnd)
            if not pid or pid in seen:
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, title, length + 1)
            class_name = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(hwnd, class_name, 256)
            haystack = f"{title.value} {class_name.value}".lower()
            if any(marker in haystack for marker in markers):
                seen.add(pid)
                found.append(pid)
            return True

        _user32.EnumWindows(_WNDENUMPROC(_callback), 0)
        return found

    def _foreground_pid() -> int:
        hwnd = _user32.GetForegroundWindow()
        return _window_pid(int(hwnd)) if hwnd else 0

    def _enumerate_windows(pid: int) -> list[WindowInfo]:
        """Every top-level window owned by ``pid`` (visible or not)."""
        records: list[WindowInfo] = []

        def _callback(hwnd, _lparam):
            hwnd = int(hwnd)
            if _window_pid(hwnd) != pid:
                return True
            rect = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            length = _user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            ex_style = int(_get_window_long(hwnd, _GWL_EXSTYLE) or 0)
            records.append(WindowInfo(
                hwnd=hwnd,
                pid=pid,
                title=buffer.value,
                visible=bool(_user32.IsWindowVisible(hwnd)),
                iconic=bool(_user32.IsIconic(hwnd)),
                owned=bool(_user32.GetWindow(hwnd, _GW_OWNER)),
                tool_window=bool(ex_style & _WS_EX_TOOLWINDOW),
                area=max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top),
            ))
            return True

        _user32.EnumWindows(_WNDENUMPROC(_callback), 0)
        return records

    def activate_window(hwnd: int) -> bool:
        """Bring ``hwnd`` (or at least its process) to the foreground."""
        if not hwnd or not _user32.IsWindow(hwnd):
            return False
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, _SW_RESTORE)

        if _user32.SetForegroundWindow(hwnd):
            if _foreground_pid() == _window_pid(hwnd):
                return True

        # Foreground lock fallback: share the input queue with the threads
        # that currently own the foreground / the target window, retry, then
        # detach again.
        current_tid = int(_kernel32.GetCurrentThreadId())
        targets = [int(_user32.GetForegroundWindow() or 0), hwnd]
        attached: list[int] = []
        for target in targets:
            tid = int(_user32.GetWindowThreadProcessId(target, None)) if target else 0
            if tid and tid != current_tid and tid not in attached:
                if _user32.AttachThreadInput(current_tid, tid, True):
                    attached.append(tid)
        try:
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                _user32.AttachThreadInput(current_tid, tid, False)

        return _foreground_pid() == _window_pid(hwnd)

else:  # pragma: no cover - pixnex targets Windows, but keep imports safe
    def activate_window(hwnd: int) -> bool:
        return False

    def _window_pid(hwnd: int) -> int:
        return 0

    def _enumerate_windows(pid: int) -> list[WindowInfo]:
        return []


class WindowFocusReturner:
    """Finds the synced app's main window and gives it the focus back.

    The remembered hwnd is re-used across calls so the focus returns to the
    window the user actually had in front, not merely the biggest one.
    """

    def __init__(self) -> None:
        self._pid = 0
        self._hwnd = 0

    def focus(self, pid: "int | None" = None,
              process_names=()) -> bool:
        """Focus the window of ``pid`` (or of one of ``process_names``)."""
        if not IS_WINDOWS:
            return False

        if pid:
            if self._try_pid(int(pid)):
                return True

        # 后端还没连上（拿不到 pid）时的兜底：按进程名找。psutil 要扫描整个
        # 进程表，所以只在 pid 这条路走不通时才走它。
        for candidate in pids_for_process_names(process_names):
            if pid and candidate == int(pid):
                continue
            if self._try_pid(candidate):
                return True
        return False

    def _try_pid(self, pid: int) -> bool:
        hwnd = self._resolve_window(pid)
        if hwnd and activate_window(hwnd):
            self._pid = pid
            self._hwnd = hwnd
            return True
        return False

    def _resolve_window(self, pid: int) -> int:
        remembered = self._hwnd if self._pid == pid else 0
        if remembered and _window_pid(remembered) != pid:
            remembered = 0
        return pick_main_window(_enumerate_windows(pid), preferred=remembered)
