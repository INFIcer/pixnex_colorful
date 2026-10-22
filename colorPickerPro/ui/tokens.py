"""Design tokens for the pixnex user interface.

Everything visual lives here so that every window shares exactly one palette,
one spacing rhythm, one type scale and one set of corner radii.  Widget code
must never hard-code a colour, font size or pixel gap – import from this module
(or better: use :mod:`colorPickerPro.ui.components`) instead.

The palette is a neutral dark theme: it keeps the chrome quiet so that colour
judgement in the picker / filters is not biased by a colourful interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from PySide6.QtGui import QColor


# ---------------------------------------------------------------------------
# Geometry scale (device independent pixels)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Spacing:
    xxs: int = 1
    xs: int = 2
    sm: int = 4
    md: int = 6
    lg: int = 8
    xl: int = 12
    xxl: int = 16


@dataclass(frozen=True)
class Radius:
    sm: int = 3
    md: int = 5
    lg: int = 8
    xl: int = 12


@dataclass(frozen=True)
class Sizing:
    control_height: int = 26
    button_height: int = 28
    icon_button: int = 24
    title_bar_height: int = 30
    min_window_width: int = 320
    min_window_height: int = 460
    card_padding: int = 8
    scrollbar_width: int = 8


@dataclass(frozen=True)
class Typography:
    family: str = "Microsoft YaHei UI"
    family_fallback: str = "Segoe UI"
    mono_family: str = "Consolas"
    display_px: int = 20
    title_px: int = 16
    section_px: int = 13
    body_px: int = 13
    caption_px: int = 12
    tiny_px: int = 11


SPACE = Spacing()
RADIUS = Radius()
SIZE = Sizing()
TYPE = Typography()


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    """Semantic colour roles – reference roles, never raw hex in widgets."""

    window: str
    surface: str
    surface_alt: str
    surface_hover: str
    input: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    on_accent: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_hover: str
    danger_soft: str
    tooltip: str
    shadow: str

    def qcolor(self, role: str) -> QColor:
        return QColor(getattr(self, role))

    def rgba(self, role: str, alpha: int) -> str:
        """CSS rgba() string for a palette role with an explicit 0-255 alpha."""
        color = QColor(getattr(self, role))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


DARK = Palette(
    window="#14171C",
    surface="#1B1F26",
    surface_alt="#232933",
    surface_hover="#2B323E",
    input="#11141A",
    border="#2B313C",
    border_strong="#3A4350",
    text="#E9EDF3",
    text_muted="#9BA6B6",
    text_faint="#6C7787",
    accent="#4C8DFF",
    accent_hover="#6AA1FF",
    accent_pressed="#3B78E8",
    accent_soft="rgba(76, 141, 255, 0.16)",
    on_accent="#FFFFFF",
    success="#3FBF8F",
    success_soft="rgba(63, 191, 143, 0.14)",
    warning="#E8A33D",
    warning_soft="rgba(232, 163, 61, 0.14)",
    danger="#E5544B",
    danger_hover="#F06A61",
    danger_soft="rgba(229, 84, 75, 0.14)",
    tooltip="#252B35",
    shadow="rgba(0, 0, 0, 0.45)",
)

DEFAULT_PALETTE = DARK


# ---------------------------------------------------------------------------
# Semantic role names shared by widgets and the stylesheet
# ---------------------------------------------------------------------------

class Role:
    """Values for the dynamic ``role`` property of QLabel / QFrame."""

    TITLE = "title"
    SUBTITLE = "subtitle"
    SECTION = "section"
    BODY = "body"
    CAPTION = "caption"
    FIELD = "field"
    VALUE = "value"
    MONO = "mono"
    HINT = "hint"
    STATUS = "status"


class Variant:
    """Values for the dynamic ``variant`` property of QPushButton."""

    DEFAULT = "default"
    PRIMARY = "primary"
    DANGER = "danger"
    GHOST = "ghost"
    ICON = "icon"
    ICON_DANGER = "icon-danger"


class State:
    """Values for the dynamic ``state`` property of status-ish widgets."""

    NEUTRAL = "neutral"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    ACCENT = "accent"


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """Blend two hex colours (used for hover/pressed tints)."""
    a, b = QColor(color_a), QColor(color_b)
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(a.red() + (b.red() - a.red()) * ratio),
        round(a.green() + (b.green() - a.green()) * ratio),
        round(a.blue() + (b.blue() - a.blue()) * ratio),
    ).name()


def qcolor(hex_or_role: str, palette: Palette = DEFAULT_PALETTE) -> QColor:
    """Resolve either a palette role name (``"accent"``) or a raw hex colour."""
    value = getattr(palette, hex_or_role, hex_or_role)
    return QColor(value)


def rgb(hex_or_role: str, palette: Palette = DEFAULT_PALETTE) -> Tuple[int, int, int]:
    color = qcolor(hex_or_role, palette)
    return color.red(), color.green(), color.blue()
