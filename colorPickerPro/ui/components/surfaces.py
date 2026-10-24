"""Cards, dividers, swatches and badges – the small surface building blocks."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from ..tokens import SIZE, SPACE, qcolor
from .text import SectionTitle


class Card(QFrame):
    """A square-cornered panel with an optional section title and header actions.

    Usage::

        card = Card("滑块选色")
        card.add(widget)
        card.add_header_widget(status_label)
    """

    def __init__(self, title: str = "", parent: QWidget | None = None, *,
                 padding: int = SIZE.card_padding, spacing: int = SPACE.sm):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(padding, padding, padding, padding)
        outer.setSpacing(spacing)

        self._header: QHBoxLayout | None = None
        self.title_label: SectionTitle | None = None
        if title:
            self._header = QHBoxLayout()
            self._header.setContentsMargins(0, 0, 0, 0)
            self._header.setSpacing(SPACE.sm)
            self.title_label = SectionTitle(title)
            self._header.addWidget(self.title_label)
            self._header.addStretch(1)
            outer.addLayout(self._header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(spacing)
        outer.addLayout(self.body, 1)

    # ------------------------------------------------------------------
    def add(self, widget: QWidget, stretch: int = 0,
            alignment: Qt.AlignmentFlag | None = None) -> QWidget:
        if alignment is None:
            self.body.addWidget(widget, stretch)
        else:
            self.body.addWidget(widget, stretch, alignment)
        return widget

    def add_layout(self, layout, stretch: int = 0):
        self.body.addLayout(layout, stretch)
        return layout

    def add_spacing(self, pixels: int) -> None:
        self.body.addSpacing(pixels)

    def add_stretch(self) -> None:
        self.body.addStretch(1)

    def set_title(self, text: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(text)

    def add_header_widget(self, widget: QWidget) -> QWidget:
        """Add a small control to the title row (status text, button …)."""
        if self._header is None:
            raise RuntimeError("Card was created without a title")
        self._header.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        return widget


class Divider(QFrame):
    """One-pixel separator using the theme border colour."""

    def __init__(self, orientation: str = "horizontal", parent: QWidget | None = None):
        super().__init__(parent)
        if orientation == "vertical":
            self.setObjectName("VDivider")
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self.setObjectName("Divider")
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class ColorSwatch(QWidget):
    """Colour preview block; the only widget allowed to paint a raw colour."""

    def __init__(self, color: QColor | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color) if color is not None else None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumSize(64, 32)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def color(self) -> QColor | None:
        return QColor(self._color) if self._color is not None else None

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(160, 44)

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        border = qcolor("border_strong")
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._color is not None:
            painter.setBrush(self._color)
        else:
            painter.setBrush(qcolor("input"))
        pen = QPen(border, 1)
        painter.setPen(pen)
        painter.drawRect(rect)


class Badge(QLabel):
    """Compact square label for counts / modes."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


__all__ = ["Card", "Divider", "ColorSwatch", "Badge"]
