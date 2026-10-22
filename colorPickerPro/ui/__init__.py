"""Reusable UI building blocks for the pixnex desktop app.

The package has two layers:

``colorPickerPro.ui.tokens`` / ``.stylesheet`` / ``.theme``
    The design system: one palette, one spacing scale, one global stylesheet.

``colorPickerPro.ui.components``
    Small, single-purpose widgets (labels, buttons, cards, field rows, dialogs)
    that already carry the right semantic roles.  Feature code composes these
    instead of styling raw Qt widgets, which keeps every window consistent and
    keeps style knowledge out of feature modules.
"""

from .theme import (
    DEFAULT_PALETTE,
    Palette,
    Role,
    State,
    Variant,
    apply_theme,
    configure_application,
    ensure_theme,
    is_applied,
    repolish,
    set_role,
    set_state,
    set_variant,
)
from .tokens import RADIUS, SIZE, SPACE, TYPE

__all__ = [
    "apply_theme",
    "configure_application",
    "ensure_theme",
    "is_applied",
    "repolish",
    "set_role",
    "set_state",
    "set_variant",
    "DEFAULT_PALETTE",
    "Palette",
    "Role",
    "State",
    "Variant",
    "RADIUS",
    "SIZE",
    "SPACE",
    "TYPE",
]
