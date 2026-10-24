"""自动折叠的共享工具（主窗口 / 屏幕滤镜窗口共用）。

两个窗口的「鼠标离开 → 收起为标题栏，鼠标进入 → 展开」轮询逻辑相同，差异只在
折叠动作本身，因此这里只集中放置容易写错的公共判断：

- ``mouse_button_pressed()``：当前是否真的按着鼠标键（拖拽未结束）；
- ``modal_or_popup_open()``：是否有可见的模态对话框 / 弹出层（此时鼠标在窗口外
  是正常现象，不应触发折叠）。

注意：不能用 ``QApplication.mouseButtons()`` 判断拖拽。屏幕取色器 / 覆盖层在
``mousePressEvent`` 里就隐藏自己，物理松键事件不会再进入本进程，Qt 的按键状态
会永远停在 press 上，自动折叠就再也不会触发。Windows 下用 ``GetAsyncKeyState``
读取物理按键状态；其他平台退回 Qt 状态。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# 自动折叠轮询间隔（毫秒）：鼠标离开 / 进入窗口后最迟这么久响应一次。
AUTO_COLLAPSE_POLL_MS = 120

# Win32 虚拟键码：左 / 右 / 中键。
_VK_LBUTTON, _VK_RBUTTON, _VK_MBUTTON = 0x01, 0x02, 0x04


def mouse_button_pressed() -> bool:
    """鼠标按键此刻是否真的被按住（判断拖拽是否未结束）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            return any(user32.GetAsyncKeyState(vk) & 0x8000
                       for vk in (_VK_LBUTTON, _VK_RBUTTON, _VK_MBUTTON))
        except Exception:
            pass
    return QApplication.mouseButtons() != Qt.MouseButton.NoButton


def modal_or_popup_open() -> bool:
    """是否有可见的模态对话框或弹出层。"""
    modal = QApplication.activeModalWidget()
    if modal is not None and modal.isVisible():
        return True
    popup = QApplication.activePopupWidget()
    return popup is not None and popup.isVisible()


__all__ = ["AUTO_COLLAPSE_POLL_MS", "modal_or_popup_open",
           "mouse_button_pressed"]
