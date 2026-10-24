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
from .win_process import is_pid_running

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


# -- COM apartment helpers ---------------------------------------------------
# pywin32 must be initialised *per thread*: SyncController talks to Photoshop
# from its worker QThread, and without CoInitialize every Dispatch call fails
# with CO_E_NOTINITIALIZED (0x800401F0) — which silently degraded sync to the
# CEP script bridge and made the status read 「已同步」 while nothing synced.
def com_initialize() -> bool:
    """Initialise COM for the calling thread; True when it is usable now."""
    if pythoncom is None:
        return False
    try:
        pythoncom.CoInitialize()
        return True
    except Exception:
        return False


def com_uninitialize() -> None:
    """Balance :func:`com_initialize` for the calling thread."""
    if pythoncom is None:
        return
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass


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
        self._com_failed_ts: float = 0.0
        self._connect_ts: float = 0.0
        self.last_error: str = ""
        self.permission_issue: bool = False

    #: 一次 COM 失败后，隔多久再试（避免绿色版每 0.1 秒重试一次 Dispatch）
    COM_RETRY_SECONDS = 10.0

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
        # 完全没连上时最多每秒尝试一次：Dispatch / 进程枚举都很贵，轮询循环
        # 每 100ms 调一次 connect 会把 Photoshop 拖卡。
        now = time.monotonic()
        if (self._app is None and self._disp is None and self._bridge is None
                and now - self._connect_ts < 1.0):
            return False
        self._connect_ts = now

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

        # 已部署的脚本桥只有真的在写心跳才算连上：deploy() 成功只代表文件
        # 写进去了，Photoshop 没重启时面板并没有运行（旧代码在这里误报已同步）。
        if (self._bridge is not None and self._bridge.is_deployed()
                and self._bridge.is_alive() and self._is_process_alive()):
            self.last_error = ""
            return True

        self._reset()

        instances = self._detect()
        target = pick_target(instances, self.current_version)
        if target is None:
            self.last_error = "未检测到运行中的 Photoshop 进程（请先启动 Photoshop）"
            return False

        self._pid = target.pid
        self._maybe_retry_com()
        if target.kind == COM_KIND and not self._com_failed:
            if self._connect_com(target):
                return True
            self._com_failed = True
            self._com_failed_ts = time.monotonic()
            if self.current_version in ("", "auto"):
                for inst in instances:
                    if inst is not target and inst.kind == COM_KIND:
                        self._pid = inst.pid
                        if self._connect_com(inst):
                            self._com_failed = False
                            return True
            self._pid = target.pid
        return self._connect_bridge(target)

    def _maybe_retry_com(self) -> None:
        """Allow COM again after a cooldown (green editions stay on the bridge)."""
        if (self._com_failed
                and time.monotonic() - self._com_failed_ts >= self.COM_RETRY_SECONDS):
            self._com_failed = False

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
        already_deployed = self._bridge.is_deployed()
        if not already_deployed and not self._bridge.deploy():
            self.last_error = "脚本桥部署失败（目录不可写？请以管理员身份运行）"
            return False
        self.backend = SCRIPT_BRIDGE_KIND
        if self._bridge.is_alive():
            self.last_error = ""
            return True
        # 部署成功 ≠ 生效：CEP 面板只有在 Photoshop 重启后才会跑起来。
        self.last_error = (
            "脚本桥已部署，但 Photoshop 里没有响应：请重启 Photoshop 后生效"
            if not already_deployed
            else "脚本桥没有心跳：请重启 Photoshop（绿色版）后重试")
        return False

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
                # 原生进程快照兜底（禁止 psutil：会破坏 UDM 的内存访问）。
                return is_pid_running(self._pid)
        return self.K32.WaitForSingleObject(self._proc_handle, 0) != 0

    # -- slot readers ---------------------------------------------------------------
    #: index 0 = foreground, 1 = background (ExtendScript property names)
    _SLOT_PROPS = ("foregroundColor", "backgroundColor")

    def _bridge_state(self, key: str, index: int) -> dict[str, int] | None:
        if self._bridge is None:
            return None
        state = self._bridge.read_state()
        if state is None:
            return None
        slot = state[key]
        return {"r": slot["r"], "g": slot["g"], "b": slot["b"], "index": index}

    def _read_slot_js(self, index: int) -> dict[str, int]:
        """Read a colour slot through ``DoJavaScript``.

        The COM property path is deliberately avoided: on Photoshop CC 2018
        ``app.ForegroundColor`` hands out a per-client copy — mutating its RGB
        is silently ignored and reading it can keep returning a stale snapshot
        while Photoshop displays a different colour.  ``DoJavaScript`` runs in
        Photoshop itself, so it is the ground truth for both directions.
        """
        prop = self._SLOT_PROPS[index]
        result = self._invoke_js(
            f"var c=app.{prop}.rgb;"
            "Math.round(c.red)+'|'+Math.round(c.green)+'|'+Math.round(c.blue)")
        parts = str(result).split("|")
        if len(parts) != 3:
            raise ValueError(f"unexpected DoJavaScript result: {result!r}")
        return {"r": clamp8(float(parts[0])), "g": clamp8(float(parts[1])),
                "b": clamp8(float(parts[2])), "index": index}

    def _write_slot_js(self, index: int, r: int, g: int, b: int) -> None:
        prop = self._SLOT_PROPS[index]
        self._invoke_js(
            "var c=new SolidColor();"
            f"c.rgb.red={int(r)};c.rgb.green={int(g)};c.rgb.blue={int(b)};"
            f"app.{prop}=c;")

    def _get_slot(self, index: int) -> dict[str, int] | None:
        if self.backend == SCRIPT_BRIDGE_KIND:
            return self._bridge_state("fg" if index == 0 else "bg", index)
        if self._app is None:
            self.connect()
        # connect() 可能把 backend 切到脚本桥（绿色版），需要重新分派。
        if self.backend == SCRIPT_BRIDGE_KIND:
            return self._bridge_state("fg" if index == 0 else "bg", index)
        if self._app is None:
            return None
        if not self._is_process_alive():
            self._reset()
            return None
        try:
            return self._read_slot_js(index)
        except Exception as exc:
            if _com_hresult(exc) in _PERMISSION_HRESULTS:
                self.permission_issue = True
            name = "前景色" if index == 0 else "背景色"
            self.last_error = f"读取 Photoshop {name}失败：{exc}"
            self._reset()
            return None

    def get_color(self) -> dict[str, int] | None:
        return self._get_slot(0)

    def get_bg_color(self) -> dict[str, int] | None:
        return self._get_slot(1)

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
        color_index = 1 if color_index else 0

        if self.backend == SCRIPT_BRIDGE_KIND:
            if self._bridge is None:
                return False
            return self._bridge.send_color(
                str(time.time_ns()), color_index, r, g, b)

        if self._app is None and not self.connect():
            return False
        if self.backend == SCRIPT_BRIDGE_KIND:
            if self._bridge is None:
                return False
            return self._bridge.send_color(
                str(time.time_ns()), color_index, r, g, b)

        if not self._is_process_alive():
            self._reset()
            return False

        try:
            current = self._read_slot_js(color_index)
            if (current["r"], current["g"], current["b"]) == (r, g, b):
                return True  # 已经是这个颜色，不做无谓写入
            self._write_slot_js(color_index, r, g, b)
            self.last_error = ""
            return True
        except Exception as exc:
            if _com_hresult(exc) in _PERMISSION_HRESULTS:
                self.permission_issue = True
            self.last_error = f"写入 Photoshop 颜色失败：{exc}"
            self._reset()
            return False

    # -- status / meta -----------------------------------------------------------
    @property
    def target_pid(self) -> int | None:
        """PID of the Photoshop instance we talk to (None when detached)."""
        return self._pid

    def focus_process_names(self) -> tuple[str, ...]:
        """Executable that may host the Photoshop window."""
        return (PROCESS_NAME,)

    def _bridge_connected(self) -> bool:
        """Deployed **and** heartbeating — deploying alone does not sync."""
        return bool(self._bridge is not None
                    and self._bridge.is_deployed()
                    and self._bridge.is_alive()
                    and self._is_process_alive())

    def _com_connected(self) -> bool:
        return self._disp is not None and self._is_process_alive()

    def _connected(self) -> bool:
        return self._com_connected() or self._bridge_connected()

    def status(self) -> dict[str, object]:
        connected = self._connected()
        if not connected:
            self.connect()
            connected = self._connected()

        bridge = self._bridge
        return {
            "connected": connected,
            "running": connected or bool(self._detect()),
            "pid": self._pid if connected else None,
            "version": self.current_version,
            "processName": self.process_name,
            "backend": self.backend,
            "bridgeAlive": bool(bridge is not None and bridge.is_alive()),
            "panelStale": bool(bridge is not None
                               and bridge.panel_version() != PANEL_VERSION),
            "lastError": self.last_error,
        }

    def status_lite(self) -> dict[str, object]:
        connected = self._connected()
        bridge = self._bridge
        return {
            "connected": connected,
            "running": connected or bool(self._detect()),
            "pid": self._pid if connected else None,
            "version": self.current_version,
            "processName": self.process_name,
            "backend": self.backend,
            "bridgeAlive": bool(bridge is not None and bridge.is_alive()),
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
