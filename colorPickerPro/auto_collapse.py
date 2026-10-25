"""自动折叠的共享工具（主窗口 / 屏幕滤镜窗口共用）。

两个窗口的「鼠标离开 → 收起为标题栏，鼠标进入 → 展开」轮询逻辑相同，差异只在
折叠动作本身，因此这里集中放置容易写错的公共判断：

- ``mouse_button_pressed()``：当前是否真的按着鼠标键（拖拽未结束）；
- ``modal_or_popup_open()``：是否有可见的模态对话框 / 弹出层（此时鼠标在窗口外
  是正常现象，不应触发折叠）；
- ``CollapseDelay``：鼠标离开后的折叠延迟（默认 1 秒）。只有折叠延迟，
  展开始终立即执行；离开不足 1 秒就回到窗口不会折叠。

注意：不能用 ``QApplication.mouseButtons()`` 判断拖拽。屏幕取色器 / 覆盖层在
``mousePressEvent`` 里就隐藏自己，物理松键事件不会再进入本进程，Qt 的按键状态
会永远停在 press 上，自动折叠就再也不会触发。Windows 下用 ``GetAsyncKeyState``
读取物理按键状态；其他平台退回 Qt 状态。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# 自动折叠轮询间隔（毫秒）：鼠标离开 / 进入窗口后最迟这么久响应一次。
AUTO_COLLAPSE_POLL_MS = 120

# 鼠标离开窗口后需要持续离开多久才折叠（毫秒）；回到窗口则取消等待。
AUTO_COLLAPSE_DELAY_MS = 500

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


@dataclass
class CollapseDelay:
    """自动折叠的「离开延迟」状态机。

    只有折叠会延迟：鼠标离开后需持续离开 ``delay_ms`` 毫秒才返回 True；
    离开期间任意一次回到窗口都会取消等待。展开由调用方立即执行，不经过这里。

    ``should_collapse()`` 的 ``now`` 使用 ``time.monotonic()`` 秒数；测试可显式
    传入时间，避免真的等待 1 秒。
    """

    delay_ms: int = AUTO_COLLAPSE_DELAY_MS
    _outside_since: float | None = field(
        default=None, init=False, repr=False)

    def reset(self) -> None:
        """取消当前等待（回到窗口、开关关闭、窗口折叠/隐藏时调用）。"""
        self._outside_since = None

    def should_collapse(self, inside: bool, now: float | None = None) -> bool:
        if inside:
            self._outside_since = None
            return False
        moment = time.monotonic() if now is None else float(now)
        if self._outside_since is None:
            self._outside_since = moment
            return False
        return (moment - self._outside_since) * 1000.0 >= self.delay_ms


__all__ = ["AUTO_COLLAPSE_DELAY_MS", "AUTO_COLLAPSE_POLL_MS", "CollapseDelay",
           "modal_or_popup_open", "mouse_button_pressed"]
