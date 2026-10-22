"""SVG icon lookup.

Every icon used by the interface is a vector asset under
``colorPickerPro/ui/assets/icons``.  Widgets never draw icon glyphs as text;
they either set a :class:`QIcon` (buttons) or let the global stylesheet embed
the SVG (combo/spin arrows, checkbox check mark).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap

ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"


@lru_cache(maxsize=64)
def icon(name: str) -> QIcon:
    """Return the cached QIcon for *name* (without the ``.svg`` suffix)."""
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        return QIcon()
    return QIcon(str(path))


def icon_names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


def icon_pixmap(name: str, size: int = 16, dpr: float = 1.0) -> QPixmap:
    """Rasterise an icon at an explicit size (for custom-painted widgets)."""
    qicon = icon(name)
    px = max(1, int(round(size * dpr)))
    return qicon.pixmap(QSize(px, px))


def icon_path(name: str) -> str:
    """Absolute POSIX path of an icon file (used by QSS placeholders)."""
    return (ICON_DIR / f"{name}.svg").as_posix()


__all__ = ["ICON_DIR", "icon", "icon_names", "icon_pixmap", "icon_path"]
