"""External drawing-app color sync (UDM Paint, Adobe Photoshop).

Port of colorink's brush-color sync backends (GPL-3.0), adapted for the
pixnex PySide6 codebase.  The package exposes:

* ``UDMSync`` — pymem-based memory sync for UDM Paint (``udm_brush_link``)
* ``PhotoshopSync`` — COM automation + green-edition script bridge
* ``SyncController`` — a QThread that polls the active backend and keeps
  the picker color in sync with the target application.
"""

from .brush_color_spaces import (
    SPACE_ORDER,
    encode_space_values,
    rgb_to_space_values,
    space_to_rgb_values,
)
from .udm_brush_link import UDMSync
from .photoshop_instances import (
    COM_KIND,
    SCRIPT_BRIDGE_KIND,
    detect_instances,
    pick_target,
)
from .photoshop_script_bridge import PhotoshopScriptBridge
from .photoshop_color_sync import PhotoshopSync
from .controller import SyncController

__all__ = [
    "SPACE_ORDER",
    "encode_space_values",
    "rgb_to_space_values",
    "space_to_rgb_values",
    "UDMSync",
    "COM_KIND",
    "SCRIPT_BRIDGE_KIND",
    "detect_instances",
    "pick_target",
    "PhotoshopScriptBridge",
    "PhotoshopSync",
    "SyncController",
]
