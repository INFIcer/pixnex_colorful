"""Photoshop colour sync — COM automation + green-edition script bridge.

Port of colorink's ``core.photoshop_color_sync`` (GPL-3.0).

Two backends, chosen automatically per running instance:

* **COM**: registered Photoshop installs are driven through the COM
  automation interface (``ForegroundColor`` / ``BackgroundColor``).
* **script-bridge**: green / portable editions register no COM interface,
  so we deploy an ExtendScript CEP bridge (see
  :mod:`.photoshop_script_bridge`).

Both backends support the two colour slots: ``color_index`` 0 =
foreground (main), 1 = background (sub).  Photoshop has no alpha channel.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from typing import Any, Optional, cast

import psutil

try:
    import pythoncom
    import win32com.client as _w32
except ImportError:  # pragma: no cover
    _w32 = None
    pythoncom = None

from .photoshop_instances import (
    COM_KIND,
    SCRIPT_BRIDGE_KIND,
    PhotoshopInstance,
    detect_instances,
    pick_target,
)
from .photoshop_script_bridge import (
    PANEL_VERSION,
    PhotoshopScriptBridge,
)

PROCESS_NAME = "Photoshop.exe"

_PROGIDS = (
    "Photoshop.Application",
    "Photoshop.Application.140",
)

_PERMISSION_HRESULTS = {
    0x80070005,   # E_ACCESSDENIED
    0x8001011B,   # RPC_E_ACCESS_DENIED
    0x800706BA,   # RPC_S_SERVER_UNAVAILABLE
}


def _com_hresult(exc: Exception) -> int | None:
    hres = getattr(exc, "hresult", None)
    if isinstance(hres, int):
        return hres & 0xFFFFFFFF
    return None


DEBUG = False


def log(msg: str) -> None:
    if DEBUG:
        print(f"[PhotoshopSync] {msg}", file=sys.stderr, flush=True)


def clamp8(v: int) -> int:
    return max(0, min(255, int(v)))


class PhotoshopSync:
    """Colour bridge to Adobe Photoshop (COM or green-edition script bridge).

    Usage::

        ps = PhotoshopSync()
        ps.connect()
        rgb = ps.get_color()          # -> {'r':..., 'g':..., 'b':..., 'index': 0}
        rgb_bg = ps.get_bg_color()    # -> {..., 'index': 1}
        ps.set_color(255, 0, 0)       # -> True (foreground)
        print(ps.status())            # -> {connected, backend, pid, ...}
    """

    def __init__(self) -> None:
        self._app: Any = None
        self._disp: Any = None
        self._dispid_js: int = 0
        self._pid: int | None = None
        self._proc_handle: int = 0
        self.current_version: str = "auto"
        self.process_name: str = PROCESS_NAME
        self.backend: str = ""
        self._bridge: PhotoshopScriptBridge | None = None
        self._instances: list[PhotoshopInstance] = []
        self._detect_ts: float = 0.0
        self._com_failed = False
        self.last_error: str = ""
        self.permission_issue: bool = False

    # -- instance discovery -------------------------------------------------
    def _detect(self, force: bool = False) -> list[PhotoshopInstance]:
        now = time.monotonic()
        if force or now - self._detect_ts > 2.0:
            try:
                self._instances = detect_instances()
            except Exception:
                self._instances = []
            self._detect_ts = now
        return self._instances

    # -- connect -------------------------------------------------------------
    def connect(self) -> bool:
        if self._app is not None and self._disp is not None:
            if not self._is_process_alive():
                self.last_error = "Photoshop 进程已退出，请重新启动 Photoshop 后再试"
                self._reset()
            else:
                try:
                    name = self._app.Name
                    if name:
                        return True
                except Exception:
                    self._reset()

        if (self._bridge is not None and self._bridge.is_deployed()
                and self._is_process_alive()):
            return True

        self._reset()

        if _w32 is None and self.backend != SCRIPT_BRIDGE_KIND:
            self.last_error = "pywin32 组件不可用（打包异常或未安装 pywin32）"
            return False

        instances = self._detect()
        target = pick_target(instances, self.current_version)
        if target is None:
            self.last_error = "未检测到运行中的 Photoshop 进程（请先启动 Photoshop）"
            return False

        self._pid = target.pid
        if target.kind == COM_KIND and not self._com_failed:
            if self._connect_com(target):
                return True
            self._com_failed = True
            if self.current_version in ("", "auto"):
                for inst in instances:
                    if inst is not target and inst.kind == COM_KIND:
                        self._pid = inst.pid
                        if self._connect_com(inst):
                            self._com_failed = False
                            return True
            self._pid = target.pid
        return self._connect_bridge(target)

    def _connect_com(self, target: PhotoshopInstance) -> bool:
        if _w32 is None:
            self.last_error = "pywin32 组件不可用（打包异常或未安装 pywin32）"
            return False
        progids = [target.progid] if target.progid else []
        progids += [p for p in _PROGIDS if p not in progids]
        for progid in progids:
            try:
                self._app = cast(Any, _w32).dynamic.Dispatch(progid)
                self._disp = self._app._oleobj_
                self._dispid_js = self._disp.GetIDsOfNames("DoJavaScript")
                if self._proc_handle:
                    self.K32.CloseHandle(self._proc_handle)
                    self._proc_handle = 0
                self.backend = COM_KIND
                self.last_error = ""
                self.permission_issue = False
                return True
            except Exception as exc:
                hres = _com_hresult(exc)
                if hres in _PERMISSION_HRESULTS:
                    self.permission_issue = True
                self.last_error = f"COM 连接 {progid} 失败:{exc}"

        self._app = None
        self._disp = None
        if self.permission_issue:
            self.last_error += (
                "（可能是权限不足:请让 Photoshop 与 pixnex 都"
                "以管理员身份运行）"
            )
        return False

    def _connect_bridge(self, target: PhotoshopInstance) -> bool:
        ps_dir = os.path.dirname(target.exe_path)
        self._bridge = PhotoshopScriptBridge(ps_dir)
        if not self._bridge.deploy():
            self.last_error = "脚本桥部署失败（目录不可写？请以管理员身份运行）"
            return False
        self.backend = SCRIPT_BRIDGE_KIND
        if self._bridge.is_alive():
            self.last_error = ""
            return True
        self.last_error = "脚本桥已部署：重启 Photoshop（绿色版）后生效"
        return True

    # -- colour I/O ----------------------------------------------------------
    def _invoke_js(self, script: str) -> object:
        result = self._disp.Invoke(
            self._dispid_js, 0, pythoncom.DISPATCH_METHOD, 1, script
        )
        if isinstance(result, str):
            try:
                return float(result)
            except ValueError:
                return result
        return result

    K32 = ctypes.windll.kernel32
    K32.OpenProcess.restype = ctypes.c_void_p
    K32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    K32.WaitForSingleObject.restype = ctypes.c_uint32
    K32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    K32.CloseHandle.argtypes = (ctypes.c_void_p,)

    def _is_process_alive(self) -> bool:
        if self._pid is None:
            return False
        if not self._proc_handle:
            self._proc_handle = self.K32.OpenProcess(0x00100000, False, self._pid)
            if not self._proc_handle:
                try:
                    return any(
                        p.info["pid"] == self._pid
                        for p in psutil.process_iter(["pid"])
                    )
                except Exception:
                    return False
        return self.K32.WaitForSingleObject(self._proc_handle, 0) != 0

    # -- slot readers ---------------------------------------------------------------
    def get_color(self) -> dict[str, int] | None:
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            state = self._bridge.read_state()
            if state is not None:
                fg = state["fg"]
                return {"r": fg["r"], "g": fg["g"], "b": fg["b"], "index": 0}
            return None
        if self._app is None:
            if not self.connect():
                return None
        assert self._app is not None

        if not self._is_process_alive():
            self._reset()
            return None

        try:
            rgb = self._app.ForegroundColor.RGB
            r = clamp8(round(float(rgb.Red)))
            g = clamp8(round(float(rgb.Green)))
            b = clamp8(round(float(rgb.Blue)))
            return {"r": r, "g": g, "b": b, "index": 0}
        except Exception as exc:
            if _com_hresult(exc) in _PERMISSION_HRESULTS:
                self.permission_issue = True
            self.last_error = f"读取 Photoshop 前景色失败：{exc}"
            self._reset()
            return None

    def get_bg_color(self) -> dict[str, int] | None:
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            state = self._bridge.read_state()
            if state is not None:
                bg = state["bg"]
                return {"r": bg["r"], "g": bg["g"], "b": bg["b"], "index": 1}
            return None
        if self._app is None:
            if not self.connect():
                return None
        assert self._app is not None

        if not self._is_process_alive():
            self._reset()
            return None

        try:
            rgb = self._app.BackgroundColor.RGB
            r = clamp8(round(float(rgb.Red)))
            g = clamp8(round(float(rgb.Green)))
            b = clamp8(round(float(rgb.Blue)))
            return {"r": r, "g": g, "b": b, "index": 1}
        except Exception as exc:
            if _com_hresult(exc) in _PERMISSION_HRESULTS:
                self.permission_issue = True
            self.last_error = f"读取 Photoshop 背景色失败：{exc}"
            self._reset()
            return None

    # -- slot writers ---------------------------------------------------------------
    def swap_slots(self) -> bool:
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            return self._bridge.send_swap(str(time.time_ns()))
        if self._app is None:
            if not self.connect():
                return False
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            return self._bridge.send_swap(str(time.time_ns()))
        assert self._app is not None
        if not self._is_process_alive():
            self._reset()
            return False
        try:
            self._invoke_js(
                "var t=app.foregroundColor;"
                "app.foregroundColor=app.backgroundColor;"
                "app.backgroundColor=t;"
            )
            return True
        except Exception as exc:
            self.last_error = f"交换 Photoshop 前后景色失败：{exc}"
            self._reset()
            return False

    def set_color(self, r: int, g: int, b: int, color_index: int = 0) -> bool:
        r, g, b = clamp8(r), clamp8(g), clamp8(b)

        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            return self._bridge.send_color(
                str(time.time_ns()), color_index, r, g, b)

        if self._app is None:
            if not self.connect():
                return False
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            return self._bridge.send_color(
                str(time.time_ns()), color_index, r, g, b)
        assert self._app is not None

        if not self._is_process_alive():
            self._reset()
            return False

        try:
            cur = self.get_color() if color_index == 0 else self.get_bg_color()
            if cur and cur["r"] == r and cur["g"] == g and cur["b"] == b:
                return True  # no-op
            slot = (self._app.ForegroundColor if color_index == 0
                    else self._app.BackgroundColor)
            rgb = slot.RGB
            rgb.Red = r
            rgb.Green = g
            rgb.Blue = b
            return True
        except Exception as exc:
            if _com_hresult(exc) in _PERMISSION_HRESULTS:
                self.permission_issue = True
            self.last_error = f"写入 Photoshop 颜色失败：{exc}"
            self._reset()
            return False

    # -- status / meta -----------------------------------------------------------
    def status(self) -> dict[str, object]:
        if self.backend == SCRIPT_BRIDGE_KIND and self._bridge is not None:
            connected = (self._bridge.is_deployed()
                         and self._is_process_alive())
            if not connected:
                self.connect()
                connected = (self._bridge is not None
                             and self._bridge.is_deployed()
                             and self._is_process_alive())
            return {
                "connected": connected,
                "pid": self._pid if connected else None,
                "version": self.current_version,
                "processName": self.process_name,
                "backend": self.backend,
                "bridgeAlive": bool(self._bridge is not None
                                    and self._bridge.is_alive()),
                "panelStale": bool(self._bridge is not None
                                   and self._bridge.panel_version()
                                   != PANEL_VERSION),
                "lastError": self.last_error,
            }

        connected = (self._disp is not None
                     or (self._bridge is not None and self._bridge.is_alive()))
        if not connected:
            self.connect()
            connected = (self._disp is not None
                         or (self._bridge is not None and self._bridge.is_alive()))

        return {
            "connected": connected,
            "pid": self._pid if connected else None,
            "version": self.current_version,
            "processName": self.process_name,
            "backend": self.backend,
            "bridgeAlive": bool(self._bridge is not None
                                and self._bridge.is_alive()),
            "lastError": self.last_error,
        }

    def status_lite(self) -> dict[str, object]:
        bridge_ok = (self._bridge is not None
                     and self._bridge.is_deployed()
                     and self._is_process_alive())
        return {
            "connected": bridge_ok or self._disp is not None,
            "pid": self._pid if bridge_ok or self._disp is not None else None,
            "version": self.current_version,
            "processName": self.process_name,
            "backend": self.backend,
            "bridgeAlive": bool(self._bridge is not None
                                and self._bridge.is_alive()),
            "lastError": self.last_error,
        }

    def set_version(self, version: str) -> bool:
        version = str(version or "auto").strip()
        if version == self.current_version:
            return False
        self.current_version = version
        self._reset()
        return True

    def recheck(self) -> bool:
        self._com_failed = False
        self._detect(force=True)
        return self.connect()

    def _reset(self) -> None:
        if self._proc_handle:
            self.K32.CloseHandle(self._proc_handle)
            self._proc_handle = 0
        self._app = None
        self._disp = None
        self._dispid_js = 0
        self._pid = None
        self._bridge = None
        self.backend = ""
