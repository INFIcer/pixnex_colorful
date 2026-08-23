"""Color-space math and on-disk layout for the host brush-color struct.

Port of colorink's ``core.brush_color_spaces`` (GPL-3.0).  UDM Paint and
Photoshop both expose the active brush color as a contiguous struct that
holds the same color expressed in several spaces (RGB / CMYK / HSV / HLS),
each channel persisted as a 32-bit unsigned integer proportional to that
channel's natural maximum.  This module is the single source of truth for
the fixed per-channel offsets, the scaling helpers and the space
conversions used by the sync backends.

This module has **no** PySide / numpy dependency so it stays importable in
isolation.
"""

from __future__ import annotations

import colorsys
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Dict, Tuple

# ---------------------------------------------------------------------------
# Fixed struct layout (offsets relative to the RGB slot start)
# ---------------------------------------------------------------------------
_RGB_OFFS: tuple[int, ...] = (0x00, 0x04, 0x08)
_CMYK_OFFS: tuple[int, ...] = (0x0C, 0x10, 0x14, 0x18)
_HSV_OFFS: tuple[int, ...] = (0x1C, 0x20, 0x24)
_HLS_OFFS: tuple[int, ...] = (0x28, 0x2C, 0x30)

_RGB_MAX: tuple[float, ...] = (255.0, 255.0, 255.0)
_CMYK_MAX: tuple[float, ...] = (100.0, 100.0, 100.0, 100.0)
_HSV_MAX: tuple[float, ...] = (360.0, 100.0, 100.0)
_HLS_MAX: tuple[float, ...] = (360.0, 100.0, 100.0)

SPACE_ORDER: tuple[str, ...] = ("rgb", "cmyk", "hsv", "hls")

_U32_LIMIT = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# GCR curve for CMYK synthesis (mirrors what the host apps write)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _GcrCurve:
    lightness_kick_in: float = 65.0
    lightness_saturated: float = 35.0
    lightness_exponent: float = 1.2
    chroma_suppress_ref: float = 80.0
    saturation_exponent: float = 2.0
    total_ink_cap: float = 3.0


_GCR = _GcrCurve()


# ---------------------------------------------------------------------------
# Internal clipping helpers
# ---------------------------------------------------------------------------
def _clip_int(value: float, low: int, high: int) -> int:
    if value <= low:
        return low
    if value >= high:
        return high
    return int(round(value))


def _clip_float(value: float, ceiling: float) -> float:
    ceiling = float(ceiling)
    if value <= 0.0:
        return 0.0
    if value >= ceiling:
        return ceiling
    return float(value)


def _byte(value: float) -> int:
    return _clip_int(value, 0, 255)


def _percent(value: float) -> int:
    return _clip_int(value, 0, 100)


def _hue(value: float) -> int:
    return _clip_int(value, 0, 360)


def normalize_hue_for_colorsys(h: int) -> float:
    h_int = _hue(h)
    return 0.0 if h_int >= 360 else h_int / 360.0


# ---------------------------------------------------------------------------
# u32 scaling
# ---------------------------------------------------------------------------
def encode_scaled_u32(value: float, max_value: float) -> int:
    if max_value <= 0:
        return 0
    ratio = _clip_float(value, max_value) / float(max_value)
    packed = int(round(ratio * _U32_LIMIT))
    if packed < 0:
        return 0
    if packed > _U32_LIMIT:
        return _U32_LIMIT
    return packed


def decode_scaled_u32(raw: int, max_value: float) -> int:
    if max_value <= 0:
        return 0
    normalized = (int(raw) & _U32_LIMIT) / _U32_LIMIT
    return int(round(normalized * float(max_value)))


# ---------------------------------------------------------------------------
# Color-space descriptor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColorSpaceSpec:
    name: str
    channels: tuple[str, ...]
    maxima: tuple[float, ...]
    relative_offsets: tuple[int, ...]

    def channel_offsets(self, anchor: int) -> tuple[int, ...]:
        base = int(anchor)
        return tuple(base + off for off in self.relative_offsets)

    def channel_addresses(self, anchor: int) -> tuple[int, ...]:
        base = int(anchor)
        return tuple(base + off for off in self.relative_offsets)

    def decode(self, raws: Sequence[int]) -> dict[str, int]:
        return {
            ch: decode_scaled_u32(raw, mx)
            for ch, raw, mx in zip(self.channels, raws, self.maxima)
        }

    def encode(self, values: Mapping[str, int]) -> tuple[int, ...]:
        return tuple(
            encode_scaled_u32(values[ch], mx)
            for ch, mx in zip(self.channels, self.maxima)
        )

    def render(self, values: Mapping[str, int]) -> str:
        return ", ".join(
            f"{ch.upper()}={int(values[ch])}" for ch in self.channels
        )


_RGB = ColorSpaceSpec("rgb", ("r", "g", "b"), _RGB_MAX, _RGB_OFFS)
_CMYK = ColorSpaceSpec("cmyk", ("c", "m", "y", "k"), _CMYK_MAX, _CMYK_OFFS)
_HSV = ColorSpaceSpec("hsv", ("h", "s", "v"), _HSV_MAX, _HSV_OFFS)
_HLS = ColorSpaceSpec("hls", ("h", "l", "s"), _HLS_MAX, _HLS_OFFS)

_REGISTRY: dict[str, ColorSpaceSpec] = {
    spec.name: spec for spec in (_RGB, _CMYK, _HSV, _HLS)
}


def _lookup(name: str) -> ColorSpaceSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown color space: {name!r}") from None


def build_space_offsets(rgb_base_offset: int) -> dict[str, tuple[int, ...]]:
    return {name: spec.channel_offsets(rgb_base_offset) for name, spec in _REGISTRY.items()}


def build_space_addresses(rgb_base_address: int) -> dict[str, tuple[int, ...]]:
    return {name: spec.channel_addresses(rgb_base_address) for name, spec in _REGISTRY.items()}


def decode_space_raws(space_name: str, raws: Sequence[int]) -> dict[str, int]:
    return _lookup(space_name).decode(raws)


def encode_space_values(space_name: str, values: Mapping[str, int]) -> tuple[int, ...]:
    return _lookup(space_name).encode(values)


def encode_space_values_float(space_name: str, values: Mapping[str, float]) -> tuple[int, ...]:
    spec = _lookup(space_name)
    return tuple(
        encode_scaled_u32(float(values[ch]), mx)
        for ch, mx in zip(spec.channels, spec.maxima)
    )


def format_space_values(space_name: str, values: Mapping[str, int]) -> str:
    return _lookup(space_name).render(values)


# ---------------------------------------------------------------------------
# Raw-value inspection
# ---------------------------------------------------------------------------
def space_has_nonzero_raws(raws: Sequence[int]) -> bool:
    return any((int(raw) & _U32_LIMIT) != 0 for raw in raws)


def any_space_has_nonzero_raws(snapshots: Mapping[str, Mapping[str, Any]]) -> bool:
    for snapshot in snapshots.values():
        raws = snapshot.get("raws") or ()
        if space_has_nonzero_raws(raws):
            return True
    return False


# ---------------------------------------------------------------------------
# Direct space conversions (integer, human range)
# ---------------------------------------------------------------------------
def rgb_to_hsv_values(rgb: Mapping[str, int]) -> dict[str, int]:
    r = _byte(rgb["r"]) / 255.0
    g = _byte(rgb["g"]) / 255.0
    b = _byte(rgb["b"]) / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return {"h": _hue(h * 360.0), "s": _percent(s * 100.0), "v": _percent(v * 100.0)}


def hsv_to_rgb_values(values: Mapping[str, int]) -> dict[str, int]:
    r, g, b = colorsys.hsv_to_rgb(
        normalize_hue_for_colorsys(values["h"]),
        _percent(values["s"]) / 100.0,
        _percent(values["v"]) / 100.0,
    )
    return {"r": _byte(r * 255.0), "g": _byte(g * 255.0), "b": _byte(b * 255.0)}


def rgb_to_hls_values(rgb: Mapping[str, int]) -> dict[str, int]:
    r = _byte(rgb["r"]) / 255.0
    g = _byte(rgb["g"]) / 255.0
    b = _byte(rgb["b"]) / 255.0
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return {"h": _hue(h * 360.0), "l": _percent(l * 100.0), "s": _percent(s * 100.0)}


def hls_to_rgb_values(values: Mapping[str, int]) -> dict[str, int]:
    r, g, b = colorsys.hls_to_rgb(
        normalize_hue_for_colorsys(values["h"]),
        _percent(values["l"]) / 100.0,
        _percent(values["s"]) / 100.0,
    )
    return {"r": _byte(r * 255.0), "g": _byte(g * 255.0), "b": _byte(b * 255.0)}


# ---------------------------------------------------------------------------
# Float-precision conversions (no int rounding)
# ---------------------------------------------------------------------------
def _clip_float_255(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 255.0:
        return 255.0
    return float(value)


def rgb_to_hsv_float(rgb: Mapping[str, Any]) -> dict[str, float]:
    r = _clip_float_255(float(rgb["r"])) / 255.0
    g = _clip_float_255(float(rgb["g"])) / 255.0
    b = _clip_float_255(float(rgb["b"])) / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h_deg = h * 360.0
    if h_deg >= 360.0:
        h_deg = 0.0
    return {"h": h_deg, "s": s * 100.0, "v": v * 100.0}


def hsv_to_rgb_float(values: Mapping[str, Any]) -> dict[str, float]:
    h = float(values["h"]) % 360.0
    s = _clip_float(float(values["s"]), 100.0) / 100.0
    v = _clip_float(float(values["v"]), 100.0) / 100.0
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
    return {"r": r * 255.0, "g": g * 255.0, "b": b * 255.0}


def rgb_to_hls_float(rgb: Mapping[str, Any]) -> dict[str, float]:
    r = _clip_float_255(float(rgb["r"])) / 255.0
    g = _clip_float_255(float(rgb["g"])) / 255.0
    b = _clip_float_255(float(rgb["b"])) / 255.0
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h_deg = h * 360.0
    if h_deg >= 360.0:
        h_deg = 0.0
    return {"h": h_deg, "l": l * 100.0, "s": s * 100.0}


def hls_to_rgb_float(values: Mapping[str, Any]) -> dict[str, float]:
    h = float(values["h"]) % 360.0
    l = _clip_float(float(values["l"]), 100.0) / 100.0
    s = _clip_float(float(values["s"]), 100.0) / 100.0
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return {"r": r * 255.0, "g": g * 255.0, "b": b * 255.0}


# --- CIE L*a*b* path (drives the CMYK GCR curve) -------------------------
def _srgb_to_linear(c: float) -> float:
    if c > 0.04045:
        return math.pow((c + 0.055) / 1.055, 2.4)
    return c / 12.92


_XYZ_D65_TO_D50 = (
    (1.0478112, 0.0228866, -0.0501270),
    (0.0295424, 0.9904844, -0.0170491),
    (-0.0092345, 0.0150436, 0.7521316),
)

_LINEAR_TO_XYZ_D65 = (
    (0.4124564390896922, 0.357576077643909, 0.18043748326639894),
    (0.21267285140562253, 0.715152155287818, 0.07217499330655958),
    (0.019330818715591851, 0.11919477979462598, 0.9505321522496607),
)


def _mat3_vec3(m, v):
    a, b, c = v
    return (
        m[0][0] * a + m[0][1] * b + m[0][2] * c,
        m[1][0] * a + m[1][1] * b + m[1][2] * c,
        m[2][0] * a + m[2][1] * b + m[2][2] * c,
    )


def _linear_rgb_to_xyz_d65(r: float, g: float, b: float) -> tuple[float, float, float]:
    x, y, z = _mat3_vec3(_LINEAR_TO_XYZ_D65, (r, g, b))
    return x * 100.0, y * 100.0, z * 100.0


def _xyz_d65_to_d50(x: float, y: float, z: float) -> tuple[float, float, float]:
    return _mat3_vec3(_XYZ_D65_TO_D50, (x, y, z))


def _lab_nonlinear(t: float) -> float:
    delta = 6.0 / 29.0
    threshold = delta ** 3
    if t > threshold:
        return math.pow(t, 1.0 / 3.0)
    return t / (3.0 * delta * delta) + 4.0 / 29.0


_D50_X, _D50_Y, _D50_Z = 96.422, 100.0, 82.521


def _xyz_d50_to_lab(x: float, y: float, z: float) -> tuple[float, float, float]:
    fx = _lab_nonlinear(x / _D50_X)
    fy = _lab_nonlinear(y / _D50_Y)
    fz = _lab_nonlinear(z / _D50_Z)
    L_star = 116.0 * fy - 16.0
    a_star = 500.0 * (fx - fy)
    b_star = 200.0 * (fy - fz)
    return (
        max(0.0, min(100.0, round(L_star * 100.0) / 100.0)),
        max(-128.0, min(127.0, round(a_star * 100.0) / 100.0)),
        max(-128.0, min(127.0, round(b_star * 100.0) / 100.0)),
    )


def rgb_to_lab_values(rgb: Mapping[str, int]) -> dict[str, float]:
    r = _srgb_to_linear(_byte(rgb["r"]) / 255.0)
    g = _srgb_to_linear(_byte(rgb["g"]) / 255.0)
    b = _srgb_to_linear(_byte(rgb["b"]) / 255.0)
    x65, y65, z65 = _linear_rgb_to_xyz_d65(r, g, b)
    x50, y50, z50 = _xyz_d65_to_d50(x65, y65, z65)
    L, a, b_lab = _xyz_d50_to_lab(x50, y50, z50)
    return {"l": L, "a": a, "b": b_lab}


def _gcr_k_fraction(rgb: Mapping[str, int]) -> float:
    lab = rgb_to_lab_values(rgb)
    chroma = math.sqrt(lab["a"] * lab["a"] + lab["b"] * lab["b"])
    saturation = min(1.0, max(0.0, rgb_to_hsv_values(rgb)["s"] / 100.0))
    lightness_factor = 0.0
    if lab["l"] < _GCR.lightness_kick_in:
        span = max(1.0, _GCR.lightness_kick_in - _GCR.lightness_saturated)
        t = min(1.0, max(0.0, (_GCR.lightness_kick_in - lab["l"]) / span))
        lightness_factor = math.pow(t, _GCR.lightness_exponent)
    chroma_suppress = min(1.0, max(0.0, 1.0 - chroma / _GCR.chroma_suppress_ref))
    saturation_suppress = math.pow(1.0 - saturation, _GCR.saturation_exponent)
    return min(1.0, max(0.0, lightness_factor * max(chroma_suppress, saturation_suppress)))


def rgb_to_cmyk_values(rgb: Mapping[str, int]) -> dict[str, int]:
    r = _byte(rgb["r"])
    g = _byte(rgb["g"])
    b = _byte(rgb["b"])
    c_pure = 1.0 - r / 255.0
    m_pure = 1.0 - g / 255.0
    y_pure = 1.0 - b / 255.0
    neutral = min(c_pure, m_pure, y_pure)
    k = neutral * _gcr_k_fraction({"r": r, "g": g, "b": b})
    c = max(0.0, c_pure - k)
    m = max(0.0, m_pure - k)
    y = max(0.0, y_pure - k)
    total = c + m + y + k
    if total > _GCR.total_ink_cap:
        chroma_sum = max(1e-6, c + m + y)
        scale = (_GCR.total_ink_cap - k) / chroma_sum
        c *= scale
        m *= scale
        y *= scale
    return {
        "c": _percent(c * 100.0),
        "m": _percent(m * 100.0),
        "y": _percent(y * 100.0),
        "k": _percent(k * 100.0),
    }


def cmyk_to_rgb_values(values: Mapping[str, int]) -> dict[str, int]:
    c = _percent(values["c"]) / 100.0
    m = _percent(values["m"]) / 100.0
    y = _percent(values["y"]) / 100.0
    k = _percent(values["k"]) / 100.0
    return {
        "r": _byte((1.0 - c) * (1.0 - k) * 255.0),
        "g": _byte((1.0 - m) * (1.0 - k) * 255.0),
        "b": _byte((1.0 - y) * (1.0 - k) * 255.0),
    }


def _gcr_k_fraction_float(rgb: Mapping[str, Any]) -> float:
    lab = rgb_to_lab_values(rgb)
    chroma = math.sqrt(lab["a"] * lab["a"] + lab["b"] * lab["b"])
    saturation = min(1.0, max(0.0, rgb_to_hsv_float(rgb)["s"] / 100.0))
    lightness_factor = 0.0
    if lab["l"] < _GCR.lightness_kick_in:
        span = max(1.0, _GCR.lightness_kick_in - _GCR.lightness_saturated)
        t = min(1.0, max(0.0, (_GCR.lightness_kick_in - lab["l"]) / span))
        lightness_factor = math.pow(t, _GCR.lightness_exponent)
    chroma_suppress = min(1.0, max(0.0, 1.0 - chroma / _GCR.chroma_suppress_ref))
    saturation_suppress = math.pow(1.0 - saturation, _GCR.saturation_exponent)
    return min(1.0, max(0.0, lightness_factor * max(chroma_suppress, saturation_suppress)))


def rgb_to_cmyk_float(rgb: Mapping[str, Any]) -> dict[str, float]:
    r = _clip_float_255(float(rgb["r"]))
    g = _clip_float_255(float(rgb["g"]))
    b = _clip_float_255(float(rgb["b"]))
    c_pure = 1.0 - r / 255.0
    m_pure = 1.0 - g / 255.0
    y_pure = 1.0 - b / 255.0
    neutral = min(c_pure, m_pure, y_pure)
    k = neutral * _gcr_k_fraction_float({"r": r, "g": g, "b": b})
    c = max(0.0, c_pure - k)
    m = max(0.0, m_pure - k)
    y = max(0.0, y_pure - k)
    total = c + m + y + k
    if total > _GCR.total_ink_cap:
        chroma_sum = max(1e-6, c + m + y)
        scale = (_GCR.total_ink_cap - k) / chroma_sum
        c *= scale
        m *= scale
        y *= scale
    return {"c": c * 100.0, "m": m * 100.0, "y": y * 100.0, "k": k * 100.0}


def cmyk_to_rgb_float(values: Mapping[str, Any]) -> dict[str, float]:
    c = _clip_float(float(values["c"]), 100.0) / 100.0
    m = _clip_float(float(values["m"]), 100.0) / 100.0
    y = _clip_float(float(values["y"]), 100.0) / 100.0
    k = _clip_float(float(values["k"]), 100.0) / 100.0
    return {
        "r": (1.0 - c) * (1.0 - k) * 255.0,
        "g": (1.0 - m) * (1.0 - k) * 255.0,
        "b": (1.0 - y) * (1.0 - k) * 255.0,
    }


# ---------------------------------------------------------------------------
# RGB <-> any-space dispatch tables
# ---------------------------------------------------------------------------
_RGB_TO_SPACE: dict[str, Callable[[Mapping[str, int]], dict[str, int]]] = {
    "rgb": lambda rgb: {"r": _byte(rgb["r"]), "g": _byte(rgb["g"]), "b": _byte(rgb["b"])},
    "cmyk": rgb_to_cmyk_values,
    "hsv": rgb_to_hsv_values,
    "hls": rgb_to_hls_values,
}

_SPACE_TO_RGB: dict[str, Callable[[Mapping[str, int]], dict[str, int]]] = {
    "rgb": lambda v: {"r": _byte(v["r"]), "g": _byte(v["g"]), "b": _byte(v["b"])},
    "cmyk": cmyk_to_rgb_values,
    "hsv": hsv_to_rgb_values,
    "hls": hls_to_rgb_values,
}


def rgb_to_space_values(space_name: str, rgb: Mapping[str, int]) -> dict[str, int]:
    try:
        return _RGB_TO_SPACE[space_name](rgb)
    except KeyError:
        raise KeyError(f"unknown color space: {space_name!r}") from None


def space_to_rgb_values(space_name: str, values: Mapping[str, int]) -> dict[str, int]:
    try:
        return _SPACE_TO_RGB[space_name](values)
    except KeyError:
        raise KeyError(f"unknown color space: {space_name!r}") from None


_RGB_TO_SPACE_FLOAT: dict[str, Callable[[Mapping[str, Any]], dict[str, float]]] = {
    "rgb": lambda rgb: {"r": float(rgb["r"]), "g": float(rgb["g"]), "b": float(rgb["b"])},
    "cmyk": rgb_to_cmyk_float,
    "hsv": rgb_to_hsv_float,
    "hls": rgb_to_hls_float,
}

_SPACE_TO_RGB_FLOAT: dict[str, Callable[[Mapping[str, Any]], dict[str, float]]] = {
    "rgb": lambda v: {"r": float(v["r"]), "g": float(v["g"]), "b": float(v["b"])},
    "cmyk": cmyk_to_rgb_float,
    "hsv": hsv_to_rgb_float,
    "hls": hls_to_rgb_float,
}


def rgb_to_space_float(space_name: str, rgb: Mapping[str, Any]) -> dict[str, float]:
    try:
        return _RGB_TO_SPACE_FLOAT[space_name](rgb)
    except KeyError:
        raise KeyError(f"unknown color space: {space_name!r}") from None


def space_to_rgb_float(space_name: str, values: Mapping[str, Any]) -> dict[str, float]:
    try:
        return _SPACE_TO_RGB_FLOAT[space_name](values)
    except KeyError:
        raise KeyError(f"unknown color space: {space_name!r}") from None


# ---------------------------------------------------------------------------
# Snapshot resolution
# ---------------------------------------------------------------------------
def resolve_active_rgb(
    snapshots: Mapping[str, Mapping[str, Any]]
) -> tuple[str, dict[str, int], dict[str, int]]:
    for name in SPACE_ORDER:
        snapshot = snapshots.get(name)
        if not snapshot:
            continue
        raws = snapshot.get("raws") or ()
        if space_has_nonzero_raws(raws):
            values = snapshot["values"]
            return name, space_to_rgb_values(name, values), values
    return "rgb", {"r": 0, "g": 0, "b": 0}, {"r": 0, "g": 0, "b": 0}
