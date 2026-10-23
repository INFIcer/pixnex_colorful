"""Native Win32 process lookup used by the colour-sync backends.

pixnex must never import :mod:`psutil` while UDM Paint colour sync is in use.
On UDM Paint 4.0.5 merely importing psutil makes UDM's process protection
deny ``OpenProcess`` with memory rights to the whole pixnex process for the
rest of its lifetime (verified with a raw ``OpenProcess`` probe: every access
mask except ``PROCESS_QUERY_LIMITED_INFORMATION`` / ``SYNCHRONIZE`` fails with
``ERROR_ACCESS_DENIED`` afterwards, and it does not recover).  A single scan
while UDM Paint is starting up therefore used to break every later reconnect
until pixnex itself was restarted.

The sync code only needed three trivial psutil helpers, reimplemented here with
the Win32 process APIs (``EnumProcesses`` + ``PROCESS_QUERY_LIMITED_INFORMATION``),
which does not trip the protection.
"""

from __future__ import annotations

import ctypes
import os
import sys

IS_WINDOWS = sys.platform == "win32"

# Only query rights: anything wider on UDM Paint is refused once its
# protection was triggered, while this mask stays available.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

if IS_WINDOWS:  # pragma: no cover - exercised on a real desktop only
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    _psapi.EnumProcesses.argtypes = (
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD))
    _psapi.EnumProcesses.restype = wintypes.BOOL
    _enum_processes = _psapi.EnumProcesses

    _kernel32.OpenProcess.argtypes = (
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE

    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD))
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    def _enum_pids() -> list[int]:
        capacity = 4096
        while True:
            buffer = (wintypes.DWORD * capacity)()
            needed = wintypes.DWORD()
            ok = _enum_processes(
                buffer, ctypes.sizeof(buffer), ctypes.byref(needed))
            if not ok:
                return []
            count = needed.value // ctypes.sizeof(wintypes.DWORD)
            if count < capacity:
                return [int(buffer[i]) for i in range(count) if buffer[i]]
            capacity *= 2

    def _image_path(pid: int) -> str:
        handle = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not _kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value
        finally:
            _kernel32.CloseHandle(handle)

    def iter_process_image_names() -> list[tuple[int, str]]:
        """``(pid, executable path)`` for every process we may query."""
        out: list[tuple[int, str]] = []
        for pid in _enum_pids():
            path = _image_path(pid)
            if path:
                out.append((pid, path))
        return out

    def pid_exists(pid: int) -> bool:
        """Whether ``pid`` still names a running process."""
        if not pid:
            return False
        handle = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if handle:
            _kernel32.CloseHandle(handle)
            return True
        # Some security products filter EnumProcesses, and some processes
        # cannot be opened; try the enumeration as a second opinion.
        return int(pid) in _enum_pids()

else:  # pragma: no cover - pixnex targets Windows, keep imports safe
    def iter_process_image_names() -> list[tuple[int, str]]:
        return []

    def pid_exists(pid: int) -> bool:
        return False


def find_process_pids(names) -> list[int]:
    """PIDs whose executable basename matches ``names`` (case-insensitive)."""
    wanted = {os.path.basename(str(name)).lower() for name in names if name}
    if not wanted:
        return []
    pids: list[int] = []
    for pid, path in iter_process_image_names():
        if os.path.basename(path).lower() in wanted and pid not in pids:
            pids.append(pid)
    return pids
