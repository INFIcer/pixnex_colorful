"""Global Qt stylesheet assembled from design tokens.

One stylesheet is applied to the whole ``QApplication`` so that every window –
main window, dialogs, frameless tool panels, popups – looks the same.  Widgets
never set their own colours; they only publish *semantic* properties:

    label.setProperty("role", Role.CAPTION)
    button.setProperty("variant", Variant.PRIMARY)
    status.setProperty("state", State.SUCCESS)

The selectors below turn those properties into the actual look.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from .tokens import DEFAULT_PALETTE, Palette, RADIUS, SIZE, SPACE, TYPE

_ASSETS = Path(__file__).resolve().parent / "assets" / "icons"


def _asset(name: str) -> str:
    return (_ASSETS / name).as_posix()


# ---------------------------------------------------------------------------
# Stylesheet template ($name placeholders, substituted from the palette)
# ---------------------------------------------------------------------------

_QSS = Template(
    """
/* Corner style: sharp.  Every radius token resolves to 0 (tokens.RADIUS),
   and the few literal radii below are zero as well – the whole UI is squared
   off.  Keep it that way: do not reintroduce rounding here. */

/* ============================== base ============================== */
* {
    outline: none;
}
QWidget {
    color: $text;
    font-family: "$font_family", "$font_fallback";
    font-size: ${font_body}px;
}
QMainWindow, QDialog {
    background-color: $window;
}
QWidget#AppRoot, QWidget#FramelessRoot, QWidget#FramelessBody {
    background-color: $window;
}
QWidget#FramelessBody {
    background: transparent;
}
QToolTip {
    background-color: $tooltip;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${radius_sm}px;
    padding: 1px 4px;
}

/* ============================== labels ============================== */
QLabel {
    background: transparent;
    color: $text;
    font-size: ${font_body}px;
}
QLabel[role="title"] {
    font-size: ${font_title}px;
    font-weight: bold;
    color: $text;
}
QLabel[role="display"] {
    font-size: ${font_display}px;
    font-weight: bold;
    color: $text;
}
QLabel[role="subtitle"] {
    font-size: ${font_caption}px;
    color: $text_muted;
}
QLabel[role="section"] {
    font-size: ${font_section}px;
    font-weight: bold;
    color: $text;
}
QLabel[role="caption"] {
    font-size: ${font_caption}px;
    color: $text_muted;
}
QLabel[role="hint"] {
    font-size: ${font_tiny}px;
    color: $text_faint;
}
QLabel[role="field"] {
    font-size: ${font_caption}px;
    font-weight: bold;
    color: $text_muted;
}
QLabel[role="value"] {
    font-size: ${font_caption}px;
    color: $text;
}
QLabel[role="mono"] {
    font-family: "$font_mono", monospace;
    font-size: ${font_caption}px;
    color: $text;
}
QLabel[role="status"] {
    font-size: ${font_caption}px;
    color: $text_muted;
}
QLabel[role="status"][state="success"] { color: $success; }
QLabel[role="status"][state="warning"] { color: $warning; }
QLabel[role="status"][state="danger"]  { color: $danger; }
QLabel[role="status"][state="accent"]  { color: $accent; }
QLabel[role="status"][state="neutral"] { color: $text_muted; }
QLabel:disabled {
    color: $text_faint;
}

/* ============================== surfaces ============================== */
QFrame#Card {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}
QWidget#CardBody {
    background: transparent;
}
QFrame#Divider {
    background-color: $border;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame#VDivider {
    background-color: $border;
    border: none;
    max-width: 1px;
    min-width: 1px;
}
QLabel#Badge {
    background-color: $surface_alt;
    color: $text_muted;
    border: 1px solid $border;
    border-radius: 0px;
    padding: 2px 9px;
    font-size: ${font_tiny}px;
}

/* ============================== buttons ============================== */
QPushButton {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: 2px 6px;
    min-height: 16px;
    font-size: ${font_body}px;
}
QPushButton:hover {
    background-color: $surface_hover;
    border-color: $border_strong;
}
QPushButton:pressed {
    background-color: $surface;
}
QPushButton:focus {
    border-color: $accent;
}
QPushButton:disabled {
    background-color: $surface;
    border-color: $border;
    color: $text_faint;
}
QPushButton[variant="primary"] {
    background-color: $accent;
    border: 1px solid $accent;
    color: $on_accent;
    font-weight: bold;
    padding: 2px 8px;
}
QPushButton[variant="primary"]:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}
QPushButton[variant="primary"]:pressed {
    background-color: $accent_pressed;
    border-color: $accent_pressed;
}
QPushButton[variant="primary"]:disabled {
    background-color: $surface_alt;
    border-color: $border;
    color: $text_faint;
}
QPushButton[variant="danger"] {
    background-color: $danger;
    border: 1px solid $danger;
    color: $on_accent;
    font-weight: bold;
}
QPushButton[variant="danger"]:hover {
    background-color: $danger_hover;
    border-color: $danger_hover;
}
QPushButton[variant="danger"]:pressed {
    background-color: $danger;
}
QPushButton[variant="danger"]:disabled {
    background-color: $surface_alt;
    border-color: $border;
    color: $text_faint;
}
QPushButton[variant="ghost"] {
    background: transparent;
    border: 1px solid transparent;
    color: $text_muted;
    padding: 2px 6px;
}
QPushButton[variant="ghost"]:hover {
    background-color: $surface_hover;
    border-color: $border;
    color: $text;
}
QPushButton[variant="ghost"]:pressed {
    background-color: $surface;
}
QPushButton[variant="ghost"]:disabled {
    background: transparent;
    border-color: transparent;
    color: $text_faint;
}
QPushButton[variant="icon"], QPushButton[variant="icon-danger"] {
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${radius_md}px;
    padding: 0px;
    min-width: ${icon_button}px;
    max-width: ${icon_button}px;
    min-height: ${icon_button}px;
    max-height: ${icon_button}px;
    font-size: ${font_title}px;
    color: $text_muted;
}
QPushButton[variant="icon"]:hover {
    background-color: $surface_hover;
    border-color: $border;
    color: $text;
}
QPushButton[variant="icon"]:pressed {
    background-color: $surface;
}
QPushButton[variant="icon"]:checked {
    background-color: $accent_soft;
    border-color: $accent;
    color: $accent;
}
QPushButton[variant="icon"]:disabled {
    color: $text_faint;
}
QPushButton[variant="icon-danger"]:hover {
    background-color: $danger_soft;
    border-color: $danger;
    color: $danger;
}
QPushButton::menu-indicator {
    image: none;
    width: 0px;
}

/* ============================== inputs ============================== */
QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: $input;
    color: $text;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: 2px 6px;
    min-height: 16px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {
    border-color: $border_strong;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: $accent;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    background-color: $surface;
    color: $text_faint;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: $input;
    color: $text;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: 2px 5px;
    min-height: 18px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: $border_strong;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $accent;
}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: $surface;
    color: $text_faint;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 18px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url($chevron_down);
    width: 10px;
    height: 10px;
}
QComboBox::down-arrow:disabled {
    image: url($chevron_down);
}
QComboBox QAbstractItemView {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${radius_md}px;
    padding: 2px;
    outline: 0px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 8px;
    border-radius: ${radius_sm}px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: $surface_hover;
}
QSpinBox, QDoubleSpinBox {
    padding-right: 18px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 14px;
    border-left: 1px solid $border;
    border-top-right-radius: ${radius_md}px;
    background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 14px;
    border-left: 1px solid $border;
    border-bottom-right-radius: ${radius_md}px;
    background: transparent;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: $surface_hover;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url($chevron_up);
    width: 8px;
    height: 8px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url($chevron_down);
    width: 8px;
    height: 8px;
}

/* ============================== check boxes ============================== */
QCheckBox, QRadioButton {
    background: transparent;
    color: $text_muted;
    spacing: 5px;
    font-size: ${font_caption}px;
}
QCheckBox:hover, QRadioButton:hover {
    color: $text;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $border_strong;
    border-radius: ${radius_sm}px;
    background-color: $input;
}
QCheckBox::indicator:hover {
    border-color: $accent;
}
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url($check);
}
QCheckBox::indicator:disabled {
    border-color: $border;
    background-color: $surface;
}
QCheckBox::indicator:checked:disabled {
    background-color: $surface_alt;
    border-color: $border_strong;
}

/* ============================== sliders ============================== */
QSlider {
    background: transparent;
}
QSlider::groove:horizontal {
    height: 4px;
    background-color: $border;
    border-radius: 0px;
}
QSlider::sub-page:horizontal {
    background-color: $accent;
    border-radius: 0px;
}
QSlider::add-page:horizontal {
    background-color: $border;
    border-radius: 0px;
}
QSlider::handle:horizontal {
    background-color: $text;
    width: 14px;
    height: 14px;
    margin: -6px 0px;
    border-radius: 0px;
    border: 1px solid $border_strong;
}
QSlider::handle:horizontal:hover {
    background-color: $on_accent;
}
QSlider::handle:horizontal:disabled {
    background-color: $text_faint;
}

/* ============================== lists & views ============================== */
QListWidget, QListView, QTreeWidget, QTableWidget {
    background-color: $input;
    color: $text;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: 2px;
    outline: 0px;
    alternate-background-color: $surface;
}
QListWidget::item, QTreeWidget::item {
    color: $text;
    border-radius: ${radius_sm}px;
    padding: 3px 6px;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: $surface_hover;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: $accent;
    color: $on_accent;
}
QListWidget::item:selected:active {
    background-color: $accent;
}
QListWidget::item:disabled {
    color: $text_faint;
}
QHeaderView::section {
    background-color: $surface_alt;
    color: $text_muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 3px 6px;
}

/* ============================== scroll bars ============================== */
QScrollBar:vertical {
    background: transparent;
    width: ${scrollbar_width}px;
    margin: 2px 0px 2px 0px;
}
QScrollBar::handle:vertical {
    background-color: $border_strong;
    min-height: 28px;
    border-radius: 0px;
    margin: 0px 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: $text_faint;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: ${scrollbar_width}px;
    margin: 0px 2px 0px 2px;
}
QScrollBar::handle:horizontal {
    background-color: $border_strong;
    min-width: 28px;
    border-radius: 0px;
    margin: 2px 0px;
}
QScrollBar::handle:horizontal:hover {
    background-color: $text_faint;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ============================== containers ============================== */
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QAbstractScrollArea::corner {
    background: transparent;
}
QSplitter {
    background: transparent;
}
QSplitter::handle {
    background: transparent;
}
QSplitter::handle:horizontal {
    width: ${space_sm}px;
}
QSplitter::handle:vertical {
    height: ${space_sm}px;
}
QSplitter::handle:hover {
    background-color: $accent_soft;
}
QGroupBox {
    background-color: transparent;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
    margin-top: 10px;
    padding: ${space_md}px ${space_md}px ${space_sm}px ${space_md}px;
    font-size: ${font_section}px;
    font-weight: bold;
    color: $text;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: ${space_md}px;
    padding: 0px 4px;
    color: $text_muted;
    background-color: $window;
}
QSizeGrip {
    background: transparent;
    width: 14px;
    height: 14px;
}

/* ============================== menus ============================== */
QMenu {
    background-color: $surface_alt;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: ${radius_md}px;
    padding: 3px;
}
QMenu::item {
    padding: 2px 16px 2px 8px;
    border-radius: ${radius_sm}px;
    font-size: ${font_caption}px;
}
QMenu::item:selected {
    background-color: $accent;
    color: $on_accent;
}
QMenu::item:disabled {
    color: $text_faint;
}
QMenu::separator {
    height: 1px;
    background-color: $border;
    margin: 2px 6px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
}

/* ============================== message boxes ============================== */
QMessageBox, QInputDialog, QFileDialog {
    background-color: $window;
}
QMessageBox QLabel {
    color: $text;
}
QMessageBox QPushButton {
    min-width: 56px;
}

/* ============================== frameless chrome ============================== */
QWidget#TitleBar {
    background-color: $surface;
    border: none;
    border-bottom: 1px solid $border;
}
QLabel#TitleBarTitle {
    color: $text;
    font-size: ${font_section}px;
    font-weight: bold;
    background: transparent;
}
QLabel#TitleBarSubtitle {
    color: $text_faint;
    font-size: ${font_tiny}px;
    background: transparent;
}
QLabel#TitleBarIcon {
    background: transparent;
}

/* ============================== content helpers ============================== */
QFrame#ColorSwatch {
    border: 1px solid $border_strong;
    border-radius: ${radius_md}px;
    background-color: $input;
}
QLabel#Placeholder {
    color: $text_faint;
}
QWidget#DropZone {
    background-color: $surface;
    border: 1px dashed $border_strong;
    border-radius: ${radius_lg}px;
}
QWidget#DropZone[dragActive="true"] {
    border-color: $accent;
    background-color: $accent_soft;
}
QFrame#ToolbarSeparator {
    background-color: $border_strong;
    border: none;
    min-width: 1px;
    max-width: 1px;
}
QLineEdit#ViewerValueEdit {
    background-color: $surface_alt;
    border: 1px solid $border_strong;
    border-radius: ${radius_sm}px;
    padding: 1px 3px;
    min-height: 14px;
    font-weight: 600;
}
QLineEdit#ViewerValueEdit:focus {
    border-color: $accent;
}
QWidget#ImageCanvas {
    background-color: $input;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
}
"""
)


def _template_values(palette: Palette) -> dict:
    return {
        # colours
        "window": palette.window,
        "surface": palette.surface,
        "surface_alt": palette.surface_alt,
        "surface_hover": palette.surface_hover,
        "input": palette.input,
        "border": palette.border,
        "border_strong": palette.border_strong,
        "text": palette.text,
        "text_muted": palette.text_muted,
        "text_faint": palette.text_faint,
        "accent": palette.accent,
        "accent_hover": palette.accent_hover,
        "accent_pressed": palette.accent_pressed,
        "accent_soft": palette.accent_soft,
        "on_accent": palette.on_accent,
        "success": palette.success,
        "success_soft": palette.success_soft,
        "warning": palette.warning,
        "warning_soft": palette.warning_soft,
        "danger": palette.danger,
        "danger_hover": palette.danger_hover,
        "danger_soft": palette.danger_soft,
        "tooltip": palette.tooltip,
        "shadow": palette.shadow,
        # metrics
        "space_sm": SPACE.sm,
        "space_md": SPACE.md,
        "radius_sm": RADIUS.sm,
        "radius_md": RADIUS.md,
        "radius_lg": RADIUS.lg,
        "icon_button": SIZE.icon_button,
        "scrollbar_width": SIZE.scrollbar_width,
        # typography
        "font_family": TYPE.family,
        "font_fallback": TYPE.family_fallback,
        "font_mono": TYPE.mono_family,
        "font_display": TYPE.display_px,
        "font_title": TYPE.title_px,
        "font_section": TYPE.section_px,
        "font_body": TYPE.body_px,
        "font_caption": TYPE.caption_px,
        "font_tiny": TYPE.tiny_px,
        # assets
        "chevron_down": _asset("chevron-down.svg"),
        "chevron_up": _asset("chevron-up.svg"),
        "check": _asset("check.svg"),
    }


def build_stylesheet(palette: Palette = DEFAULT_PALETTE) -> str:
    """Return the full application stylesheet for *palette*."""
    return _QSS.substitute(_template_values(palette))
