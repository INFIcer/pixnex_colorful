"""Buttons with a consistent set of variants.

All buttons are plain ``QPushButton`` subclasses that only publish the semantic
``variant`` property; the global stylesheet does the drawing.  Icons always come
from the SVG asset set – never from text glyphs.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QMenu, QPushButton, QSizePolicy, QWidget

from ..icons import icon
from ..tokens import SIZE, Variant

DEFAULT_ICON_SIZE = 16
TEXT_ICON_SIZE = 14


class BaseButton(QPushButton):
    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 variant: str = Variant.DEFAULT, tooltip: str = "",
                 icon_name: str = ""):
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            self.set_icon(icon_name)

    def set_icon(self, name: str, size: int = TEXT_ICON_SIZE) -> "BaseButton":
        """Attach an SVG icon from the shared asset set."""
        self.setIcon(icon(name))
        self.setIconSize(QSize(size, size))
        return self


class SecondaryButton(BaseButton):
    """Neutral button – the default action style."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tooltip: str = "", icon_name: str = ""):
        super().__init__(text, parent, variant=Variant.DEFAULT,
                         tooltip=tooltip, icon_name=icon_name)


class PrimaryButton(BaseButton):
    """Accent-filled button for the main action of a surface."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tooltip: str = "", icon_name: str = ""):
        super().__init__(text, parent, variant=Variant.PRIMARY,
                         tooltip=tooltip, icon_name=icon_name)


class DangerButton(BaseButton):
    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tooltip: str = "", icon_name: str = ""):
        super().__init__(text, parent, variant=Variant.DANGER,
                         tooltip=tooltip, icon_name=icon_name)


class GhostButton(BaseButton):
    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tooltip: str = "", icon_name: str = ""):
        super().__init__(text, parent, variant=Variant.GHOST,
                         tooltip=tooltip, icon_name=icon_name)


class IconButton(BaseButton):
    """Compact square button for SVG icon actions."""

    def __init__(self, icon_name: str, parent: QWidget | None = None, *,
                 tooltip: str = "", danger: bool = False,
                 checkable: bool = False, icon_size: int = DEFAULT_ICON_SIZE):
        variant = Variant.ICON_DANGER if danger else Variant.ICON
        super().__init__("", parent, variant=variant, tooltip=tooltip)
        self._icon_name = ""
        self.set_icon(icon_name, icon_size)
        self.setFixedSize(SIZE.icon_button, SIZE.icon_button)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if checkable:
            self.setCheckable(True)

    def set_icon(self, name: str, size: int = DEFAULT_ICON_SIZE) -> "IconButton":
        self._icon_name = name
        self.setIcon(icon(name))
        self.setIconSize(QSize(size, size))
        return self

    def icon_name(self) -> str:
        return self._icon_name


class MenuButton(PrimaryButton):
    """Button that opens a :class:`QMenu` when clicked (indicator hidden by QSS)."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tooltip: str = "", icon_name: str = ""):
        super().__init__(text, parent, tooltip=tooltip, icon_name=icon_name)

    def set_menu(self, menu: QMenu) -> QMenu:  # noqa: N802 (Qt naming)
        self.setMenu(menu)
        return menu


__all__ = [
    "BaseButton",
    "SecondaryButton",
    "PrimaryButton",
    "DangerButton",
    "GhostButton",
    "IconButton",
    "MenuButton",
]
