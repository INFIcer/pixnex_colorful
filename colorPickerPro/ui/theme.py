"""Apply the pixnex theme to a Qt application.

Call :func:`configure_application` *before* creating ``QApplication`` and
:func:`apply_theme` right after – every window created later inherits the same
look.  Individual widgets should not call ``setStyleSheet``; they set semantic
properties through :func:`set_role`, :func:`set_variant` and :func:`set_state`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QLibraryInfo, QPoint, QRect, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .stylesheet import build_stylesheet
from .tokens import DEFAULT_PALETTE, Palette, Role, State, TYPE, Variant

_APPLIED = False
_TRANSLATOR: Optional[QTranslator] = None


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------

def configure_application() -> None:
    """Process-wide settings that must be configured before QApplication exists."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    # Use the Qt (theme-able) file / colour dialogs instead of the native ones,
    # otherwise the OS dialogs would be the only light windows left.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)


def _install_translations(app: QApplication) -> None:
    """Load Qt's Simplified-Chinese strings for standard dialog buttons."""
    global _TRANSLATOR
    if _TRANSLATOR is not None:
        return
    translator = QTranslator(app)
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", directory):
        app.installTranslator(translator)
        _TRANSLATOR = translator


def _build_palette(palette: Palette) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: palette.window,
        QPalette.ColorRole.WindowText: palette.text,
        QPalette.ColorRole.Base: palette.input,
        QPalette.ColorRole.AlternateBase: palette.surface,
        QPalette.ColorRole.Text: palette.text,
        QPalette.ColorRole.Button: palette.surface_alt,
        QPalette.ColorRole.ButtonText: palette.text,
        QPalette.ColorRole.BrightText: palette.on_accent,
        QPalette.ColorRole.Highlight: palette.accent,
        QPalette.ColorRole.HighlightedText: palette.on_accent,
        QPalette.ColorRole.ToolTipBase: palette.tooltip,
        QPalette.ColorRole.ToolTipText: palette.text,
        QPalette.ColorRole.PlaceholderText: palette.text_faint,
        QPalette.ColorRole.Link: palette.accent,
        QPalette.ColorRole.Mid: palette.border,
        QPalette.ColorRole.Dark: palette.border_strong,
        QPalette.ColorRole.Light: palette.surface_hover,
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    disabled = QPalette.ColorGroup.Disabled
    p.setColor(disabled, QPalette.ColorRole.WindowText, QColor(palette.text_faint))
    p.setColor(disabled, QPalette.ColorRole.Text, QColor(palette.text_faint))
    p.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(palette.text_faint))
    p.setColor(disabled, QPalette.ColorRole.Base, QColor(palette.surface))
    p.setColor(disabled, QPalette.ColorRole.Button, QColor(palette.surface))
    return p


def _build_font() -> QFont:
    font = QFont()
    font.setFamilies([TYPE.family, TYPE.family_fallback])
    font.setPixelSize(TYPE.body_px)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def apply_theme(app: Optional[QApplication] = None,
                palette: Palette = DEFAULT_PALETTE) -> QApplication:
    """Install palette, font, translations and the global stylesheet (idempotent)."""
    global _APPLIED
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("apply_theme() requires a running QApplication")
    # 若调用方忘了在创建 QApplication 之前调用 configure_application()，
    # 这里再补一次（该属性对之后创建的对话框仍然有效）。
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app.setStyle("Fusion")
    app.setPalette(_build_palette(palette))
    app.setFont(_build_font())
    app.setStyleSheet(build_stylesheet(palette))
    _install_translations(app)
    # Qt >= 6.8: ask the platform for its dark colour scheme as well, which is
    # what gives Windows a dark native title bar and dark system menus.
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except (AttributeError, TypeError):
        pass
    app.setProperty("pixnexPalette", palette.window)
    _APPLIED = True
    return app


def is_applied() -> bool:
    app = QApplication.instance()
    return bool(_APPLIED and app is not None and app.styleSheet())


def ensure_theme(app: Optional[QApplication] = None) -> QApplication:
    """Apply the theme only when it has not been installed yet."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("ensure_theme() requires a running QApplication")
    if not is_applied():
        apply_theme(app)
    return app


# ---------------------------------------------------------------------------
# Semantic properties
# ---------------------------------------------------------------------------

def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_role(widget: QWidget, role: str) -> QWidget:
    widget.setProperty("role", role)
    repolish(widget)
    return widget


def set_variant(widget: QWidget, variant: str) -> QWidget:
    widget.setProperty("variant", variant)
    repolish(widget)
    return widget


def set_state(widget: QWidget, state: str) -> QWidget:
    widget.setProperty("state", state)
    repolish(widget)
    return widget


__all__ = [
    "apply_theme",
    "configure_application",
    "ensure_theme",
    "is_applied",
    "repolish",
    "set_role",
    "set_state",
    "set_variant",
    "Role",
    "State",
    "Variant",
    "Palette",
    "DEFAULT_PALETTE",
]
