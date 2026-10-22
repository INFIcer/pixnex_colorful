"""
无边框窗口基础设施
==================

- ``PixmapWidget``           双缓冲 QPixmap 显示控件
- ``CustomFramelessWindow``  无边框窗口基类

所有窗口统一使用 ``colorPickerPro.ui.components.FramelessWindowMixin`` 提供的
自绘标题栏与 1px 边框；这里只补充“内容区替换 / 折叠 / 屏幕捕获矩形”这些屏幕
滤镜窗口特有的能力。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QVBoxLayout, QWidget

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.ui.components import FramelessWindowMixin
    from colorPickerPro.ui.tokens import SIZE, qcolor
else:
    from .ui.components import FramelessWindowMixin
    from .ui.tokens import SIZE, qcolor


class PixmapWidget(QWidget):
    """双缓冲 QPixmap 显示控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = QPixmap()

    def setPixmap(self, pm: QPixmap):
        self._pm = pm
        self.update()

    def pixmap(self) -> QPixmap:
        return self._pm

    def paintEvent(self, e):
        if not self._pm.isNull():
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            scaled = self._pm.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)


class CustomFramelessWindow(FramelessWindowMixin, QWidget):
    """可复用的无边框窗口（屏幕滤镜专用）。

    提供：统一样式标题栏、边缘缩放、双击标题栏/空格键折叠、可替换内容区，
    以及屏幕捕获需要的 ``content_rect_global()``。
    """

    def __init__(self, title: str = "Window", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._collapsed = False
        self._restore_size = None
        self._restore_min_height = 140

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self._title_bar = self.init_frameless(
            title, layout=root, show_minimize=True, show_maximize=False,
            show_close=True, resizable=True, double_click="collapse",
            border_color=qcolor("accent"))

        self._content_host = QWidget(self)
        self._content_host.setObjectName("FramelessBody")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        root.addWidget(self._content_host, 1)

        self._content: QWidget = QWidget(self._content_host)
        self._content_layout.addWidget(self._content)

        self.resize(480, 360)
        self.setMinimumSize(280, 140)
        QShortcut(Qt.Key_Space, self, self.toggle_collapse)

    # ---- 内容区 ---------------------------------------------------------
    def content_widget(self) -> QWidget:
        return self._content

    def set_content_widget(self, w: QWidget):
        """替换内容控件；旧控件会被销毁。"""
        old = self._content
        self._content = w
        w.setParent(self._content_host)
        self._content_layout.addWidget(w)
        w.show()
        if old is not None:
            self._content_layout.removeWidget(old)
            old.deleteLater()

    def content_rect_global(self) -> QRect:
        """内容区在屏幕上的全局矩形（屏幕捕获窗口据此取像素）。"""
        return QRect(self._content.mapToGlobal(QPoint(0, 0)), self._content.size())

    # ---- 标题栏 ---------------------------------------------------------
    def add_title_bar_button(self, btn: QWidget) -> QWidget:
        return self.title_bar.add_button(btn)

    def set_title(self, title: str):
        self.set_window_title(title)

    def set_subtitle(self, subtitle: str):
        self.set_window_subtitle(subtitle)

    def _should_allow_resize(self) -> bool:
        return True

    def _can_resize(self) -> bool:
        return super()._can_resize() and self._should_allow_resize()

    def is_collapsed(self) -> bool:
        return self._collapsed

    # ---- 折叠 -----------------------------------------------------------
    def toggle_collapse(self):
        if self._collapsed:
            self._collapsed = False
            self._content_host.show()
            self.setMinimumHeight(self._restore_min_height)
            self.setMaximumHeight(16777215)
            if self._restore_size is not None:
                position = self.geometry()
                self.resize(self._restore_size)
                self.move(position.x(), position.y())
                self._restore_size = None
            self.update()
        else:
            self._collapsed = True
            self._restore_min_height = self.minimumHeight()
            self._restore_size = self.size()
            self._content_host.hide()
            collapsed_height = SIZE.title_bar_height + 2
            self.setMinimumHeight(collapsed_height)
            self.setMaximumHeight(collapsed_height)
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._collapsed:
            collapsed_height = SIZE.title_bar_height + 2
            if self.height() != collapsed_height:
                self.setFixedHeight(collapsed_height)


def run_demo():
    from PySide6.QtWidgets import QApplication

    if __name__ == "__main__" and (__package__ is None or __package__ == ""):
        from colorPickerPro.ui import apply_theme, configure_application
    else:
        from .ui import apply_theme, configure_application

    configure_application()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    demo = CustomFramelessWindow("无边框窗口")
    demo.show()
    app.exec()


if __name__ == "__main__":
    run_demo()
