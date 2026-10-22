"""Text widgets with semantic roles.

Feature code should build labels from these classes instead of calling
``setStyleSheet`` – the global stylesheet decides sizes/colours from the role.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..theme import set_role, set_state
from ..tokens import Role, State, TYPE


class RoleLabel(QLabel):
    """QLabel carrying one of the :class:`~colorPickerPro.ui.tokens.Role` values."""

    def __init__(self, text: str = "", role: str = Role.BODY,
                 parent: QWidget | None = None, *, word_wrap: bool = False):
        super().__init__(text, parent)
        set_role(self, role)
        self.setWordWrap(word_wrap)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)


class TitleLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 *, word_wrap: bool = False):
        super().__init__(text, Role.TITLE, parent, word_wrap=word_wrap)


class DisplayLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, Role.DISPLAY, parent)


class SubtitleLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 *, word_wrap: bool = True):
        super().__init__(text, Role.SUBTITLE, parent, word_wrap=word_wrap)


class SectionTitle(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 *, word_wrap: bool = False):
        super().__init__(text, Role.SECTION, parent, word_wrap=word_wrap)


class CaptionLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 *, word_wrap: bool = False):
        super().__init__(text, Role.CAPTION, parent, word_wrap=word_wrap)


class HintLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 *, word_wrap: bool = True):
        super().__init__(text, Role.HINT, parent, word_wrap=word_wrap)


class FieldLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, Role.FIELD, parent)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)


class ValueLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, Role.VALUE, parent)


class MonoLabel(RoleLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, Role.MONO, parent)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)


class StatusLabel(RoleLabel):
    """One-line status text whose colour follows a semantic state."""

    def __init__(self, text: str = "", state: str = State.NEUTRAL,
                 parent: QWidget | None = None):
        super().__init__(text, Role.STATUS, parent)
        self._state = state
        set_state(self, state)
        # Status text usually sits at the right of a header row: keep its
        # natural width (a size policy of Ignored would collapse it to 0px in
        # a layout) but let callers cap it when the text can get long.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        set_state(self, state)

    def set_message(self, text: str, state: str | None = None) -> None:
        if state is not None:
            self.set_state(state)
        self.setText(text)
        self.setToolTip(text)


class ElidedLabel(QLabel):
    """Single-line label that appends an ellipsis instead of forcing width."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 role: str = Role.BODY):
        super().__init__(parent)
        self._full_text = ""
        self._role = role
        set_role(self, role)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setText(text)

    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._apply_elide()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        fm = self.fontMetrics()
        width = min(fm.horizontalAdvance(self._full_text) + 4, 360)
        return QSize(width, fm.height() + 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        fm = self.fontMetrics()
        return QSize(0, fm.height() + 2)

    def _apply_elide(self) -> None:
        available = self.width()
        if available <= 0:
            QLabel.setText(self, self._full_text)
            return
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, available)
        QLabel.setText(self, elided)


__all__ = [
    "RoleLabel",
    "TitleLabel",
    "DisplayLabel",
    "SubtitleLabel",
    "SectionTitle",
    "CaptionLabel",
    "HintLabel",
    "FieldLabel",
    "ValueLabel",
    "MonoLabel",
    "StatusLabel",
    "ElidedLabel",
]
