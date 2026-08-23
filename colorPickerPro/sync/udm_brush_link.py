"""UDM Paint active brush-color memory synchronization.

Port of colorink's ``core.udm_brush_link`` (GPL-3.0).  Attaches to a
running ``UDMPaintPRO.exe`` / ``UDMPaintEX.exe`` process and mirrors the
in-memory brush color slot, translating between the host's packed
u32-per-channel encoding and regular RGB triples.

Two address-resolution modes are supported:

* **pointer mode** (default) — chase a build-specific anchor pointer from
  the loaded module base to the live color slot, with re-validation on
  every access so a transient zero-initialized buffer cannot hijack the
  resolved target.
* **absolute mode** — bypass the pointer chase and use fixed addresses
  from ``config.ini``.
"""

from __future__ import annotations

import configparser
import math
import os
import struct
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from pymem import Pymem
    from pymem.process import module_from_name
except ImportError:  # pragma: no cover
    Pymem = None
    module_from_name = None

from .brush_color_spaces import (
    SPACE_ORDER,
    any_space_has_nonzero_raws,
    build_space_addresses,
    build_space_offsets,
    decode_space_raws,
    encode_space_values,
    format_space_values,
    resolve_active_rgb,
    rgb_to_space_values,
)

SECTION_NAME = "UDMPaint"
DEFAULT_VERSION_KEY = "udm4.0"

_DEFAULT_RED_OFFSET = 0x20
_DEFAULT_GREEN_OFFSET = 0x24
_DEFAULT_BLUE_OFFSET = 0x28


@dataclass(frozen=True)
class _UDMBuildProfile:
    key: str
    process_name: str
    base_offset: int


_PROFILES: tuple[_UDMBuildProfile, ...] = (
    _UDMBuildProfile("udm4.0", "UDMPaintPRO.exe", 0x04AE73B0),
    _UDMBuildProfile("udm4.0-ex", "UDMPaintEX.exe", 0x04CD03B0),
)
_PROFILE_INDEX: dict[str, _UDMBuildProfile] = {p.key: p for p in _PROFILES}


def _normalize_version_key(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if text in ("udm4.0-ex", "udm40ex", "udm4.0ex", "udm4-ex"):
        return "udm4.0-ex"
    return "udm4.0"


_DEBUG = False


def _log(message: str) -> None:
    if _DEBUG:
        print(f"[UDMSync] {message}", file=sys.stderr, flush=True)


def _parse_int(text: str) -> int:
    return int(str(text).strip(), 0)


def _resolve_config_file() -> str:
    env_path = os.environ.get("UDM_SYNC_CONFIG", "").strip()
    if env_path:
        return env_path
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    local_cfg = os.path.join(app_dir, "config.ini")
    if os.path.exists(local_cfg):
        return local_cfg
    return os.path.abspath("config.ini")


def _clamp_byte(value: int) -> int:
    return max(0, min(255, int(value)))


def _u32_to_signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value > 0x7FFFFFFF else value


class UDMSync:
    """Memory-sync backend for UDM Paint's active brush color."""

    def __init__(self) -> None:
        self.pm: Pymem | None = None
        self.pid: int | None = None
        self.module_base: int | None = None
        self.target: int | None = None

        self._profile: _UDMBuildProfile = _PROFILE_INDEX[DEFAULT_VERSION_KEY]
        self.current_version: str = self._profile.key
        self.process_name: str = self._profile.process_name
        self.base_offset: int = self._profile.base_offset

        self.r_off: int = _DEFAULT_RED_OFFSET
        self.g_off: int = _DEFAULT_GREEN_OFFSET
        self.b_off: int = _DEFAULT_BLUE_OFFSET
        self.space_offsets = build_space_offsets(self.r_off)
        self._last_hsv_h: float = 0.0
        self._last_hsv_s: float = 0.0
        self._resolve_fail_count: int = 0
        self._RESOLVE_FAIL_LIMIT = 30

        self.use_abs: bool = False
        self.abs_r: int = 0
        self.abs_g: int = 0
        self.abs_b: int = 0
        self.abs_mode: str = "auto"

        self._apply_profile(_normalize_version_key(
            os.environ.get("UDM_SYNC_VERSION", DEFAULT_VERSION_KEY)))
        self._load_user_config()

    # ----- profile management ---------------------------------------------
    def _apply_profile(self, key: str) -> None:
        profile = _PROFILE_INDEX.get(key, _PROFILE_INDEX[DEFAULT_VERSION_KEY])
        self._profile = profile
        self.current_version = profile.key
        self.process_name = profile.process_name
        self.base_offset = profile.base_offset

    def _load_user_config(self) -> None:
        path = _resolve_config_file()
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        if not parser.has_section(SECTION_NAME):
            return
        sec = parser[SECTION_NAME]
        if self.current_version == DEFAULT_VERSION_KEY:
            self.process_name = sec.get("processname", self.process_name)
            self.base_offset = _parse_int(sec.get("baseoffset", hex(self.base_offset)))
        self.r_off = _parse_int(sec.get("redoffset", hex(self.r_off)))
        self.g_off = _parse_int(sec.get("greenoffset", hex(self.g_off)))
        self.b_off = _parse_int(sec.get("blueoffset", hex(self.b_off)))
        self.use_abs = sec.getboolean("useabsolute", fallback=False)
        self.abs_r = _parse_int(sec.get("absolutered", "0"))
        self.abs_g = _parse_int(sec.get("absolutegreen", "0"))
        self.abs_b = _parse_int(sec.get("absoluteblue", "0"))
        self.abs_mode = sec.get("absolutemode", "auto").strip().lower()
        self.space_offsets = build_space_offsets(self.r_off)

    def set_version(self, key: str) -> bool:
        normalized = _normalize_version_key(key)
        if normalized == self.current_version:
            return False
        self._apply_profile(normalized)
        self._drop_connection()
        return True

    # ----- connection management -----------------------------------------
    def connect(self) -> bool:
        if Pymem is None or module_from_name is None:
            return False
        requested = self._profile
        candidates = [requested] + [p for p in _PROFILES if p is not requested]
        for candidate in candidates:
            self._apply_profile(candidate.key)
            if self._try_open_with(candidate):
                if candidate is not requested:
                    _log(f"Auto-detected version {candidate.key}")
                return True
        self._apply_profile(requested.key)
        return False

    def _try_open_with(self, profile: _UDMBuildProfile) -> bool:
        try:
            self.pm = Pymem(profile.process_name)
            self.pid = self.pm.process_id
            mod = module_from_name(self.pm.process_handle, profile.process_name)
            if mod is None:
                raise ValueError("module not found")
            module_base = mod.lpBaseOfDll
            self.module_base = module_base
            ptr_addr = module_base + profile.base_offset
            self.target = int(self.pm.read_longlong(ptr_addr))
            return True
        except Exception:
            self._drop_connection()
            return False

    def _drop_connection(self) -> None:
        if self.pm is not None:
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None
        self.pid = None
        self.module_base = None
        self.target = None
        self._resolve_fail_count = 0

    # ----- memory accessors ----------------------------------------------
    def _read_u32(self, address: int) -> int:
        assert self.pm is not None
        return int(self.pm.read_int(address)) & 0xFFFFFFFF

    def _write_u32(self, address: int, value: int) -> None:
        assert self.pm is not None
        self.pm.write_int(address, _u32_to_signed(value))

    def _snapshot_color_slot(self, base_addr: int) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        for space_name, offsets in self.space_offsets.items():
            raws = tuple(self._read_u32(base_addr + off) for off in offsets)
            snapshots[space_name] = {
                "offsets": offsets,
                "raws": raws,
                "values": decode_space_raws(space_name, raws),
            }
        return snapshots

    def _resolve_space_addresses(self) -> dict[str, tuple[int, ...]] | None:
        if self.pm is None:
            return None

        if self.use_abs:
            if self.abs_r and self.abs_g and self.abs_b:
                addrs = build_space_addresses(self.abs_r)
                rgb_addrs = list(addrs["rgb"])
                rgb_addrs[1] = self.abs_g
                rgb_addrs[2] = self.abs_b
                addrs["rgb"] = tuple(rgb_addrs)
                self._resolve_fail_count = 0
                return addrs
            self._count_resolve_failure()
            return None

        if self.module_base is None:
            return None

        try:
            fresh_pointer = int(self.pm.read_longlong(self.module_base + self.base_offset))
            if fresh_pointer:
                try:
                    probe = self._snapshot_color_slot(fresh_pointer)
                    if any_space_has_nonzero_raws(probe) or self.target is None:
                        self.target = fresh_pointer
                except Exception:
                    pass
        except Exception:
            pass

        if self.target is None:
            self._count_resolve_failure()
            return None

        try:
            self._snapshot_color_slot(self.target)
        except Exception as exc:
            _log(f"_resolve_space_addresses: target 0x{self.target:X} unreadable: {exc}")
            self.target = None
            self._count_resolve_failure()
            return None

        self._resolve_fail_count = 0
        return {
            name: tuple(self.target + off for off in offsets)
            for name, offsets in self.space_offsets.items()
        }

    def _count_resolve_failure(self) -> None:
        self._resolve_fail_count += 1
        if self._resolve_fail_count >= self._RESOLVE_FAIL_LIMIT:
            _log(f"_resolve_space_addresses: {self._resolve_fail_count} consecutive failures")
            self._drop_connection()

    # ----- public color access -------------------------------------------
    def get_color(self) -> dict[str, int] | None:
        if self.pm is None and not self.connect():
            return None

        space_addrs = self._resolve_space_addresses()
        if not space_addrs:
            return None

        snapshots: dict[str, dict[str, Any]] = {}
        for space_name, addresses in space_addrs.items():
            raws = tuple(self._read_u32(addr) for addr in addresses)
            snapshots[space_name] = {
                "offsets": addresses,
                "raws": raws,
                "values": decode_space_raws(space_name, raws),
            }

        _source_space, rgb, source_values = resolve_active_rgb(snapshots)
        if source_values.get("h", 0) > 0 or source_values.get("s", 0) > 1:
            self._last_hsv_h = source_values.get("h", 0)
        if source_values.get("v", 0) > 1:
            self._last_hsv_s = source_values.get("s", 0)
        return rgb

    def set_color(self, r: int, g: int, b: int) -> bool:
        if self.pm is None and not self.connect():
            return False

        space_addrs = self._resolve_space_addresses()
        if not space_addrs:
            return False

        rgb = {"r": _clamp_byte(r), "g": _clamp_byte(g), "b": _clamp_byte(b)}
        try:
            hsv_vals: dict[str, Any] = rgb_to_space_values("hsv", rgb)
            if hsv_vals["s"] < 1:
                hsv_vals["h"] = self._last_hsv_h
            else:
                self._last_hsv_h = hsv_vals["h"]
            if hsv_vals["v"] < 1:
                hsv_vals["s"] = self._last_hsv_s
            else:
                self._last_hsv_s = hsv_vals["s"]
            for space_name in SPACE_ORDER:
                if space_name == "hsv":
                    values = hsv_vals
                else:
                    values = rgb_to_space_values(space_name, rgb)
                encoded = encode_space_values(space_name, values)
                for addr, raw in zip(space_addrs[space_name], encoded):
                    self._write_u32(addr, raw)
            return True
        except Exception as exc:
            _log(f"set_color: exception: {exc}")
            return False

    # ----- introspection --------------------------------------------------
    def status(self) -> dict[str, object]:
        if self.pm is None:
            self.connect()
        space_addrs = self._resolve_space_addresses() if self.pm is not None else None
        connected = (
            self.pm is not None
            and self.target is not None
            and space_addrs is not None
        )
        return {
            "connected": bool(connected),
            "pid": self.pid if connected else None,
            "baseOffset": f"0x{self.base_offset:X}",
            "target": f"0x{self.target:X}" if connected and self.target is not None else None,
            "version": self.current_version,
            "processName": self.process_name,
        }
