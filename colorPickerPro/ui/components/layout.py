"""Layout helpers: builders, flow layout and scroll containers.

These wrappers keep the feature code free of repeated boilerplate
(``QVBoxLayout(); setContentsMargins(...); setSpacing(...)``) and provide the
two responsive primitives the app needs:

* :class:`FlowLayout` – wraps tool buttons onto a second row instead of letting
  them overflow a narrow window.
* :class:`ScrollArea` – makes a tall panel usable when the window gets short.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLayout, QLayoutItem, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ..tokens import SPACE


# ---------------------------------------------------------------------------
# Layout builders
# ---------------------------------------------------------------------------

def _fill(layout, children, stretch=None) -> None:
    for index, child in enumerate(children):
        if child is None:
            layout.addStretch(1)
        elif isinstance(child, QLayout):
            layout.addLayout(child, 1 if index == stretch else 0)
        else:
            layout.addWidget(child, 1 if index == stretch else 0)


def hbox(*children, spacing: int = SPACE.sm,
         margins: tuple[int, int, int, int] = (0, 0, 0, 0),
         stretch: int | None = None) -> QHBoxLayout:
    """Horizontal layout; ``None`` child inserts a stretch, *stretch* item grows."""
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    _fill(layout, children, stretch)
    return layout


def vbox(*children, spacing: int = SPACE.sm,
         margins: tuple[int, int, int, int] = (0, 0, 0, 0),
         stretch: int | None = None) -> QVBoxLayout:
    """Vertical layout; ``None`` child inserts a stretch, *stretch* item grows."""
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    _fill(layout, children, stretch)
    return layout


class ScrollArea(QScrollArea):
    """Frameless, themed scroll area that never forces a horizontal scrollbar."""

    def __init__(self, widget: QWidget | None = None,
                 parent: QWidget | None = None, *,
                 horizontal: bool = False):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viewport().setAutoFillBackground(False)
        if widget is not None:
            self.setWidget(widget)


# ---------------------------------------------------------------------------
# Flow layout (wrapping rows)
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """Left-to-right layout that wraps items onto new lines when space runs out.

    Used for toolbars whose buttons would otherwise overflow a narrow window.
    """

    def __init__(self, parent: QWidget | None = None, *, margin: int = 0,
                 h_spacing: int = SPACE.xs, v_spacing: int = SPACE.xs):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # QLayout interface -------------------------------------------------
    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:  # noqa: N802 (Qt API)
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt API)
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 (Qt API)
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 (Qt API)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt API)
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt API)
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt API)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # internal ----------------------------------------------------------
    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y = area.x(), area.y()
        line_height = 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if (next_x - self._h_spacing > area.right() + 1
                    and line_height > 0):
                x = area.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def flow(*children, spacing: int = SPACE.xs,
         margins: tuple[int, int, int, int] = (0, 0, 0, 0),
         parent: QWidget | None = None) -> FlowLayout:
    """Build a :class:`FlowLayout` and add *children* (widgets)."""
    layout = FlowLayout(parent, margin=0, h_spacing=spacing, v_spacing=spacing)
    layout.setContentsMargins(*margins)
    for child in children:
        layout.addWidget(child)
    return layout


__all__ = ["hbox", "vbox", "ScrollArea", "FlowLayout", "flow"]
