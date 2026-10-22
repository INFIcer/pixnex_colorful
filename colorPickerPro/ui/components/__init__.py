"""Single-purpose widgets composed into every pixnex window.

Each module covers one responsibility:

``text``       labels with semantic roles (title, caption, status, elided …)
``buttons``    standard button variants + SVG icon buttons
``surfaces``   cards, separators, colour swatch, badges
``layout``     layout builders, wrapping flow layout, themed scroll area
``dialogs``    frameless dialog scaffold, footer bar, standard message dialogs
``frameless``  custom title bar + frameless-window mixin
"""

from .buttons import (
    BaseButton,
    DangerButton,
    GhostButton,
    IconButton,
    MenuButton,
    PrimaryButton,
    SecondaryButton,
)
from .dialogs import (
    ButtonBar,
    MessageDialog,
    TextInputDialog,
    ThemedDialog,
    alert,
    confirm,
    prompt_text,
)
from .file_dialog import FileDialog, get_open_file_name, get_save_file_name
from .frameless import FramelessWindowMixin, TitleBar
from .layout import FlowLayout, ScrollArea, flow, hbox, vbox
from .surfaces import Badge, Card, ColorSwatch, Divider
from .text import (
    CaptionLabel,
    DisplayLabel,
    ElidedLabel,
    FieldLabel,
    HintLabel,
    MonoLabel,
    RoleLabel,
    SectionTitle,
    StatusLabel,
    SubtitleLabel,
    TitleLabel,
    ValueLabel,
)

__all__ = [
    # text
    "RoleLabel", "TitleLabel", "DisplayLabel", "SubtitleLabel", "SectionTitle",
    "CaptionLabel", "HintLabel", "FieldLabel", "ValueLabel", "MonoLabel",
    "StatusLabel", "ElidedLabel",
    # buttons
    "BaseButton", "SecondaryButton", "PrimaryButton", "DangerButton",
    "GhostButton", "IconButton", "MenuButton",
    # surfaces
    "Card", "Divider", "ColorSwatch", "Badge",
    # layout
    "hbox", "vbox", "ScrollArea", "FlowLayout", "flow",
    # dialogs
    "ThemedDialog", "ButtonBar", "MessageDialog", "TextInputDialog",
    "confirm", "alert", "prompt_text",
    "FileDialog", "get_open_file_name", "get_save_file_name",
    # frameless
    "TitleBar", "FramelessWindowMixin",
]
