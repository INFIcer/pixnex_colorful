"""Consistent dialog scaffolding and standard message dialogs.

Every dialog is frameless with the same custom title bar, body spacing and
footer as the main window.  Feature dialogs subclass :class:`ThemedDialog`
instead of assembling their own chrome.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLayout, QLineEdit, QVBoxLayout, QWidget,
)

from ..tokens import SPACE
from .buttons import PrimaryButton, SecondaryButton
from .frameless import FramelessWindowMixin
from .layout import ScrollArea
from .text import CaptionLabel, RoleLabel, SubtitleLabel
from ..tokens import Role


class ButtonBar(QWidget):
    """Right-aligned button row used in dialog footers and card headers."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE.sm)
        self._layout.addStretch(1)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_stretch(self, stretch: int = 1) -> None:
        self._layout.addStretch(stretch)

    def count(self) -> int:
        return self._layout.count()


class ThemedDialog(FramelessWindowMixin, QDialog):
    """Frameless dialog with the shared title bar, body area and footer.

    Subclasses add content with :meth:`add_content` /
    :meth:`add_content_layout` and the ``确定`` / ``取消`` actions with
    :meth:`add_accept_button` / :meth:`add_reject_button`.
    """

    def __init__(self, title: str = "", subtitle: str = "",
                 parent: QWidget | None = None, *,
                 margins: tuple[int, int, int, int] = (SPACE.lg, SPACE.lg,
                                                      SPACE.lg, SPACE.lg),
                 spacing: int = SPACE.md,
                 resizable: bool = True,
                 show_close: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setSizeGripEnabled(False)
        self._scrolling: Optional[ScrollArea] = None
        self._content_layout: Optional[QVBoxLayout] = None
        parent_topmost = bool(
            parent is not None
            and (parent.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.init_frameless(title, show_minimize=False, show_maximize=False,
                            show_close=show_close, resizable=resizable,
                            double_click=None, raise_on_show=True)
        if parent_topmost:
            # 父窗口置顶时，弹窗也置顶，避免被父窗口/其他置顶工具遮住。
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        outer.addWidget(self.title_bar)
        # Compatibility alias: older feature dialogs address the title label.
        self.title_label = self.title_bar.title_label

        body_host = QWidget(self)
        body_host.setObjectName("FramelessBody")
        self._body_host_layout = QVBoxLayout(body_host)
        self._body_host_layout.setContentsMargins(*margins)
        self._body_host_layout.setSpacing(spacing)
        outer.addWidget(body_host, 1)

        self.subtitle_label = SubtitleLabel("", word_wrap=True)
        self.subtitle_label.hide()
        self._body_host_layout.addWidget(self.subtitle_label)
        if subtitle:
            self.set_subtitle(subtitle)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(spacing)
        self._body_host_layout.addLayout(self.body, 1)

        self.footer = ButtonBar(self)
        self.footer.hide()
        self._footer_added = False

    # ------------------------------------------------------------------
    def set_title(self, text: str) -> None:
        self.setWindowTitle(text)
        self.title_bar.set_title(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def add_content(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._body_target().addWidget(widget, stretch)
        return widget

    def add_content_layout(self, layout: QLayout, stretch: int = 1) -> QLayout:
        self._body_target().addLayout(layout, stretch)
        return layout

    # Backwards-compatible aliases.
    add_body = add_content
    add_body_layout = add_content_layout

    def make_body_scrollable(self) -> QVBoxLayout:
        """Wrap the body in a scroll area; returns the inner content layout."""
        if self._scrolling is not None:
            raise RuntimeError("body is already scrollable")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(self.body.spacing())
        scroll = ScrollArea(content)
        self._scrolling = scroll
        self.body.addWidget(scroll, 1)
        self._content_layout = content_layout
        return content_layout

    def _body_target(self) -> QVBoxLayout:
        return self._content_layout or self.body

    # ------------------------------------------------------------------
    def _ensure_footer(self) -> ButtonBar:
        if not self._footer_added:
            self._body_host_layout.addWidget(self.footer)
            self.footer.show()
            self._footer_added = True
        return self.footer

    def add_accept_button(self, text: str = "确定") -> PrimaryButton:
        button = PrimaryButton(text, self)
        button.setDefault(True)
        button.setAutoDefault(True)
        button.clicked.connect(self.accept)
        self._ensure_footer().add(button)
        return button

    def add_reject_button(self, text: str = "取消") -> SecondaryButton:
        button = SecondaryButton(text, self)
        button.setAutoDefault(False)
        button.clicked.connect(self.reject)
        self._ensure_footer().add(button)
        return button

    def add_footer_button(self, button: QWidget) -> QWidget:
        self._ensure_footer()
        self.footer._layout.insertWidget(self.footer._layout.count() - 1, button)
        return button

    def set_body_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        self.body.setContentsMargins(left, top, right, bottom)


class MessageDialog(ThemedDialog):
    """Frameless replacement for QMessageBox (same custom chrome)."""

    def __init__(self, parent: QWidget | None, title: str, text: str, *,
                 confirm_text: str = "确定",
                 cancel_text: str | None = None):
        super().__init__(title, parent=parent)
        self._message = RoleLabel(text, role=Role.BODY, word_wrap=True)
        self._message.setMinimumWidth(320)
        self.add_content(self._message)
        if cancel_text is not None:
            self.add_reject_button(cancel_text)
        self.add_accept_button(confirm_text)
        self.setMinimumWidth(420)
        self.resize(440, 150)


class TextInputDialog(ThemedDialog):
    """Frameless replacement for QInputDialog's text prompt."""

    def __init__(self, parent: QWidget | None, title: str, label: str,
                 default: str = ""):
        super().__init__(title, parent=parent)
        caption = CaptionLabel(label, word_wrap=False)
        self._edit = QLineEdit(default)
        self._edit.selectAll()
        self._edit.returnPressed.connect(self.accept)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACE.sm)
        row_layout.addWidget(caption)
        row_layout.addWidget(self._edit, 1)
        self.add_content(row)

        self.add_reject_button("取消")
        self.add_accept_button("确定")
        self.setMinimumWidth(400)
        self.resize(420, 130)

    def value(self) -> str:
        return self._edit.text()

    def set_value(self, text: str) -> None:
        self._edit.setText(text)
        self._edit.selectAll()


# ---------------------------------------------------------------------------
# Standard helper functions
# ---------------------------------------------------------------------------

def confirm(parent: QWidget | None, title: str, text: str, *,
            ok_text: str = "确定", cancel_text: str = "取消") -> bool:
    dialog = MessageDialog(parent, title, text,
                           confirm_text=ok_text, cancel_text=cancel_text)
    return dialog.exec() == QDialog.DialogCode.Accepted


def alert(parent: QWidget | None, title: str, text: str, *,
          ok_text: str = "确定") -> None:
    MessageDialog(parent, title, text, confirm_text=ok_text).exec()


def prompt_text(parent: QWidget | None, title: str, label: str,
                default: str = "") -> tuple[str, bool]:
    dialog = TextInputDialog(parent, title, label, default)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.value(), accepted


__all__ = [
    "ButtonBar",
    "ThemedDialog",
    "MessageDialog",
    "TextInputDialog",
    "confirm",
    "alert",
    "prompt_text",
]
