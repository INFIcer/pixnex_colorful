"""Native Win32 process queries for the colour-sync backends.

The sync subsystem must **never import psutil**: importing it makes UDM Paint's
process protection deny memory access for the rest of the pixnex process
lifetime (the historical "sync stays on 连接中 after a UDM restart" bug).  This
module is the single place where "is the drawing app running?" is answered, and
it does so with a Toolhelp32 snapshot — no third-party process library, no
``OpenProcess`` on the target (opening the target's handle is what trips UDM's
protection and is therefore avoided on purpose).

Every function is deliberately total: on a non-Windows host, or when the
snapshot itself fails, they report **unknown** rather than pretending the app is
not running.  Callers can then show 「未连接」 instead of falsely claiming
「未启动」.
"""

from __future__ import annotations

import ctypes
import sys
import time

IS_WINDOWS = sys.platform == "win32"

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260
_MAX_IMAGE_PATH = 32768

#: Snapshots are cached for this long so the 10 Hz poll loop and the focus
#: helper share one system call burst instead of enumerating every 100 ms.
SNAPSHOT_TTL = 0.5

_snapshot_cache: tuple[float, tuple[tuple[int, str], ...] | None] | None = None


if IS_WINDOWS:  # pragma: no cover - exercised on a real desktop only
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * MAX_PATH),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    _kernel32.Process32NextW.restype = wintypes.BOOL

    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _ERROR_NO_MORE_FILES = 18

    _kernel32.OpenProcess.argtypes = (
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD))
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def _take_snapshot() -> tuple[tuple[int, str], ...] | None:
    """Return ``((pid, exe_name), ...)`` or ``None`` when unavailable."""
    if not IS_WINDOWS:
        return None
    handle = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not handle or handle == _INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(handle, ctypes.byref(entry)):
            return None
        processes: list[tuple[int, str]] = []
        while True:
            processes.append((int(entry.th32ProcessID), entry.szExeFile))
            if not _kernel32.Process32NextW(handle, ctypes.byref(entry)):
                break
        return tuple(processes)
    finally:
        _kernel32.CloseHandle(handle)


def process_snapshot() -> tuple[tuple[int, str], ...] | None:
    """Cached process list, or ``None`` when the system call failed."""
    global _snapshot_cache
    now = time.monotonic()
    if _snapshot_cache is not None and now - _snapshot_cache[0] < SNAPSHOT_TTL:
        return _snapshot_cache[1]
    snapshot = _take_snapshot()
    _snapshot_cache = (now, snapshot)
    return snapshot


def pids_for_process_names(names) -> list[int]:
    """Running pids whose executable name matches ``names`` (case-insensitive).

    Returns an empty list when nothing matches *or* when the process list is
    unavailable; use :func:`is_process_running` when "unknown" matters.
    """
    wanted = {str(name).casefold() for name in names if name}
    if not wanted:
        return []
    snapshot = process_snapshot()
    if not snapshot:
        return []
    return [pid for pid, exe in snapshot if str(exe).casefold() in wanted]


def is_process_running(names) -> bool | None:
    """``True``/``False`` whether one of *names* runs; ``None`` when unknown."""
    wanted = {str(name).casefold() for name in names if name}
    if not wanted:
        return False
    snapshot = process_snapshot()
    if snapshot is None:
        return None
    return any(str(exe).casefold() in wanted for _, exe in snapshot)


def is_pid_running(pid: int | None) -> bool:
    """Whether *pid* is still alive (no handle is opened on the process)."""
    if not pid:
        return False
    snapshot = process_snapshot()
    if snapshot is None:
        return False
    return any(candidate == int(pid) for candidate, _ in snapshot)


def _image_path(pid: int) -> str:
    """Full executable path of *pid* (empty string when it cannot be read)."""
    if not IS_WINDOWS or not pid:
        return ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(_MAX_IMAGE_PATH)
        size = wintypes.DWORD(_MAX_IMAGE_PATH)
        if not _kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def exe_paths_for_process_names(names) -> list[tuple[int, str]]:
    """``(pid, exe_path)`` for every running process in *names*.

    Only the image name is queried (``PROCESS_QUERY_LIMITED_INFORMATION``); the
    process memory is never touched, so this is safe to use for apps whose
    protection dislikes debugger-style access.  Processes whose path cannot be
    read (elevated / protected) are skipped, exactly like psutil's AccessDenied
    case was.
    """
    wanted = {str(name).casefold() for name in names if name}
    if not wanted:
        return []
    snapshot = process_snapshot()
    if not snapshot:
        return []
    found: list[tuple[int, str]] = []
    for pid, exe in snapshot:
        if str(exe).casefold() not in wanted:
            continue
        path = _image_path(pid)
        if path:
            found.append((pid, path))
    return found


def reset_cache() -> None:
    """Drop the cached snapshot (tests / immediately after a failed attach)."""
    global _snapshot_cache
    _snapshot_cache = None


__all__ = [
    "IS_WINDOWS",
    "exe_paths_for_process_names",
    "is_pid_running",
    "is_process_running",
    "pids_for_process_names",
    "process_snapshot",
    "reset_cache",
]
