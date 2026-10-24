"""Custom window chrome for every top-level window.

All windows in the application are frameless and draw the same title bar and
1px border, so the main window, dialogs, tool panels and popups share one look.
Dragging and resizing are delegated to the OS through
``QWindow.startSystemMove()`` / ``startSystemResize()``; this keeps native
behaviour (snap, multi-monitor, DPI) instead of re-implementing it by hand.

Hosts combine the mixin with the Qt window class and install the chrome after
building their root layout::

    class MyDialog(FramelessWindowMixin, QDialog):
        def __init__(self):
            super().__init__(parent)
            root = QVBoxLayout(self)
            root.setContentsMargins(1, 1, 1, 1)
            self.init_frameless("标题", layout=root, show_close=True)
"""

from __future__ import annotations
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QSizeGrip, QVBoxLayout, QWidget,
)

from ..tokens import SIZE, SPACE, qcolor
from .buttons import IconButton
from .text import ElidedLabel


class TitleBar(QWidget):
    """Themed title bar with drag support and window-control buttons."""

    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()
    collapseRequested = Signal()

    def __init__(self, title: str = "", parent: QWidget | None = None, *,
                 subtitle: str = "", icon: QIcon | None = None,
                 show_minimize: bool = True,
                 show_maximize: bool = False, show_close: bool = True,
                 double_click: str | None = "maximize"):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(SIZE.title_bar_height)
        self.setMouseTracking(True)
        self._double_click = double_click
        self._drag_offset: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE.md, 0, SPACE.sm, 0)
        layout.setSpacing(SPACE.sm)

        # 应用图标（只有主窗口传 icon，其余窗口标题栏保持纯文字）。
        self._icon_label: QLabel | None = None
        self._icon: QIcon | None = None
        self.set_icon(icon)

        self.title_label = ElidedLabel(title, self)
        self.title_label.setObjectName("TitleBarTitle")
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)

        self.subtitle_label = ElidedLabel(subtitle, self)
        self.subtitle_label.setObjectName("TitleBarSubtitle")
        self.subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle_label)

        layout.addStretch(1)
        self._button_layout = layout

        self._btn_min: IconButton | None = None
        if show_minimize:
            self._btn_min = IconButton("minimize", self, tooltip="最小化")
            self._btn_min.clicked.connect(self.minimizeRequested.emit)
            layout.addWidget(self._btn_min)

        self._btn_max: IconButton | None = None
        if show_maximize:
            self._btn_max = IconButton("maximize", self, tooltip="最大化")
            self._btn_max.clicked.connect(self.maximizeRequested.emit)
            layout.addWidget(self._btn_max)

        self._btn_close: IconButton | None = None
        if show_close:
            self._btn_close = IconButton("close", self, tooltip="关闭", danger=True)
            self._btn_close.clicked.connect(self.closeRequested.emit)
            layout.addWidget(self._btn_close)

    # ------------------------------------------------------------------
    def set_icon(self, icon: QIcon | None) -> None:
        """Show *icon* left of the title (no-op for a null icon).

        The icon is a static label, not a button: it must not take clicks away
        from the drag-to-move area, hence ``WA_TransparentForMouseEvents``.
        """
        if icon is None or icon.isNull():
            return
        self._icon = icon
        label = self._icon_label
        if label is None:
            label = QLabel(self)
            label.setObjectName("TitleBarIcon")
            label.setFixedSize(SIZE.title_bar_icon, SIZE.title_bar_icon)
            label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.layout().insertWidget(0, label)
            self._icon_label = label
        self._refresh_icon_pixmap()
        label.setVisible(True)

    def _refresh_icon_pixmap(self) -> None:
        """Re-rasterise the icon for the current screen's device pixel ratio.

        The .ico ships 16/20/24/28/32/40 px frames, so a 150 % or 200 % screen
        gets a genuinely sharp 24/32 px source instead of an upscaled 16 px one.
        """
        label, icon = self._icon_label, self._icon
        if label is None or icon is None:
            return
        ratio = self.devicePixelRatioF() or 1.0
        pixmap = icon.pixmap(
            QSize(SIZE.title_bar_icon, SIZE.title_bar_icon), ratio)
        pixmap.setDevicePixelRatio(ratio)
        label.setPixmap(pixmap)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt API)
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._refresh_icon_pixmap()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        # 窗口第一次显示时才知道最终所在屏幕的缩放比例。
        self._refresh_icon_pixmap()
        super().showEvent(event)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def set_maximized(self, maximized: bool) -> None:
        if self._btn_max is None:
            return
        self._btn_max.set_icon("restore" if maximized else "maximize")
        self._btn_max.setToolTip("还原" if maximized else "最大化")

    def add_button(self, button: QWidget) -> QWidget:
        """Insert a window-control-like button before the built-in buttons."""
        index = self._button_layout.count()
        for candidate in (self._btn_min, self._btn_max, self._btn_close):
            if candidate is not None:
                index = self._button_layout.indexOf(candidate)
                break
        self._button_layout.insertWidget(max(0, index), button)
        return button

    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        window = self.window()
        global_pos = event.globalPosition().toPoint()
        if window.isMaximized():
            # 标准拖动最大化窗口的四步：
            # 1) 先记录鼠标在标题栏中的相对位置（必须在还原前计算）；
            # 2) 还原窗口；
            # 3) 按相对位置移动还原后的窗口，使同一点仍位于光标下；
            # 4) 交给系统继续拖动。
            title_width = max(1, self.width())
            rel_x = event.position().x() if event.position().x()<title_width/2 else event.position().x()-title_width
            rel_y = max(0.0, event.position().y())
            normal = window.normalGeometry()
            restored_w = (normal.width()
                          if normal.isValid() and normal.width() > 0
                          else window.width())
            restored_h = (normal.height()
                          if normal.isValid() and normal.height() > 0
                          else window.height())

            # 2) 还原
            window.showNormal()

            # 3) 移动：同一条标题栏相对位置重新贴到光标下
            target_x = global_pos.x() - int(min(restored_w/2, rel_x)  if rel_x>0 else max(restored_w/2, restored_w+rel_x))
            target_y = global_pos.y() - int(rel_y)
            screen = QGuiApplication.screenAt(global_pos) or window.screen()
            if screen is not None:
                available = screen.availableGeometry()
                target_x = max(available.left() - restored_w + 120,
                               min(target_x, available.right() - 120))
                target_y = max(available.top(),
                               min(target_y, available.bottom() - 40))
            window.setGeometry(target_x, target_y,
                               restored_w, restored_h)
        # 4) 系统拖动
        handle = window.windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._drag_offset = (global_pos - window.frameGeometry().topLeft())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._double_click:
            if self._double_click == "collapse":
                self.collapseRequested.emit()
            elif self._double_click == "maximize":
                self.maximizeRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class FramelessWindowMixin:
    """Mixin that gives a top-level QWidget/QDialog/QMainWindow custom chrome.

    Call :meth:`init_frameless` once the window's root layout exists.  The
    layout must keep a 1px margin so the painted border stays visible.
    """

    EDGE_MARGIN = 6

    def init_frameless(self, title: str = "", *, layout: QVBoxLayout | None = None,
                       subtitle: str = "", icon: QIcon | None = None,
                       show_minimize: bool = False,
                       show_maximize: bool = False, show_close: bool = True,
                       resizable: bool = True, double_click: str | None = "maximize",
                       border_color: QColor | str | None = None,
                       raise_on_show: bool = False) -> TitleBar:
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMouseTracking(True)
        self._frameless_resizable = bool(resizable)
        self._frameless_border = QColor(
            border_color if border_color is not None else qcolor("border_strong"))
        self._frameless_manual_edge = 0
        self._frameless_manual_start: QPoint | None = None
        self._frameless_manual_geo: QRect | None = None
        self._raise_on_show = bool(raise_on_show)

        self.title_bar = TitleBar(
            title, self, subtitle=subtitle, icon=icon, show_minimize=show_minimize,
            show_maximize=show_maximize, show_close=show_close,
            double_click=double_click)
        self.title_bar.minimizeRequested.connect(self.showMinimized)
        self.title_bar.maximizeRequested.connect(self.toggle_maximize)
        self.title_bar.closeRequested.connect(self.close)
        self.title_bar.collapseRequested.connect(self.toggle_collapse)
        if layout is not None:
            layout.insertWidget(0, self.title_bar)
        self._frameless_layout = layout

        self._frameless_grip = QSizeGrip(self) if resizable else None
        if self._frameless_grip is not None:
            self._frameless_grip.setFixedSize(14, 14)
            self._frameless_grip.raise_()

        self._install_frameless_event_filter()
        return self.title_bar

    # ---- public helpers ------------------------------------------------
    def set_window_title(self, title: str) -> None:
        self.setWindowTitle(title)
        self.title_bar.set_title(title)

    def set_window_subtitle(self, text: str) -> None:
        self.title_bar.set_subtitle(text)

    def set_border_color(self, color: QColor | str) -> None:
        self._frameless_border = QColor(color)
        self.update()

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        # 复用窗口（例如关掉后再打开的滤镜方案面板）close() 时事件过滤器会被
        # 移除；showEvent 里确保重新挂上，否则边缘缩放 / 缩放光标会永久失效。
        self._install_frameless_event_filter()
        self._place_size_grip()
        if getattr(self, "_raise_on_show", False):
            self.raise_()
            self.activateWindow()

    def _install_frameless_event_filter(self) -> None:
        """把窗口挂到应用级事件过滤器；重复调用安全。"""
        if getattr(self, "_frameless_filter_installed", False):
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._frameless_filter_installed = True

    def _remove_frameless_event_filter(self) -> None:
        if not getattr(self, "_frameless_filter_installed", False):
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._frameless_filter_installed = False

    def toggle_maximize(self) -> None:
        if not self._frameless_resizable:
            return
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def toggle_collapse(self) -> None:
        """Hook for windows that can collapse (screen filter); no-op by default."""

    def is_frameless(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)

    # ---- layout / painting --------------------------------------------
    def _can_resize(self) -> bool:
        if getattr(self, "_collapsed", False):
            return False
        return self._frameless_resizable and not self.isMaximized()

    def _edge_at(self, pos: QPoint) -> int:
        if not self._can_resize():
            return 0
        rect, margin = self.rect(), self.EDGE_MARGIN
        edge = Qt.Edge(0)
        if pos.x() <= margin:
            edge |= Qt.Edge.LeftEdge
        if pos.x() >= rect.width() - margin:
            edge |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edge |= Qt.Edge.TopEdge
        if pos.y() >= rect.height() - margin:
            edge |= Qt.Edge.BottomEdge
        return int(edge.value)

    @staticmethod
    def _resize_cursor(edge: int) -> Qt.CursorShape:
        left = edge & Qt.Edge.LeftEdge.value
        right = edge & Qt.Edge.RightEdge.value
        top = edge & Qt.Edge.TopEdge.value
        bottom = edge & Qt.Edge.BottomEdge.value
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _update_resize_cursor(self, global_pos: QPoint) -> None:
        edge = self._edge_at(self.mapFromGlobal(global_pos))
        if edge:
            self.setCursor(self._resize_cursor(edge))
        else:
            self.unsetCursor()

    def _apply_manual_resize(self, global_pos: QPoint) -> None:
        if (not self._frameless_manual_edge
                or self._frameless_manual_start is None
                or self._frameless_manual_geo is None):
            return
        delta = global_pos - self._frameless_manual_start
        geo = QRect(self._frameless_manual_geo)
        if self._frameless_manual_edge & Qt.Edge.LeftEdge.value:
            geo.setLeft(geo.left() + delta.x())
        if self._frameless_manual_edge & Qt.Edge.RightEdge.value:
            geo.setRight(geo.right() + delta.x())
        if self._frameless_manual_edge & Qt.Edge.TopEdge.value:
            geo.setTop(geo.top() + delta.y())
        if self._frameless_manual_edge & Qt.Edge.BottomEdge.value:
            geo.setBottom(geo.bottom() + delta.y())

        # 单方向到达最小/最大尺寸时只夹紧该方向，另一方向仍继续响应，
        # 避免"一边到极限后整个窗口卡住"。
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        max_w, max_h = self.maximumWidth(), self.maximumHeight()
        width = max(min_w, min(max_w, geo.width()))
        height = max(min_h, min(max_h, geo.height()))
        if self._frameless_manual_edge & Qt.Edge.LeftEdge.value:
            geo.setLeft(geo.right() - width + 1)
        elif self._frameless_manual_edge & Qt.Edge.RightEdge.value:
            geo.setRight(geo.left() + width - 1)
        if self._frameless_manual_edge & Qt.Edge.TopEdge.value:
            geo.setTop(geo.bottom() - height + 1)
        elif self._frameless_manual_edge & Qt.Edge.BottomEdge.value:
            geo.setBottom(geo.top() + height - 1)
        self.setGeometry(geo)

    def _place_size_grip(self) -> None:
        grip = getattr(self, "_frameless_grip", None)
        if grip is not None:
            grip.move(self.width() - grip.width() - 2,
                      self.height() - grip.height() - 2)
            grip.setVisible(self._can_resize())
            grip.raise_()

    def _begin_manual_resize(self, edge: int, global_pos: QPoint) -> None:
        self._frameless_manual_edge = edge
        self._frameless_manual_start = global_pos
        self._frameless_manual_geo = self.geometry()
        self.setCursor(self._resize_cursor(edge))
        self.grabMouse()

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        super().paintEvent(event)
        border = getattr(self, "_frameless_border", None)
        if border is None:
            return
        painter = QPainter(self)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._place_size_grip()

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self._remove_frameless_event_filter()
        super().closeEvent(event)

    # ---- window system interaction ------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        if isinstance(obj, QWidget) and obj.window() is self:
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress:
                if (event.button() == Qt.MouseButton.LeftButton
                        and self._can_resize()):
                    grip = getattr(self, "_frameless_grip", None)
                    if obj is grip:
                        # 创建时窗口可能还没激活，QSizeGrip 的原生缩放会失效；
                        # 直接走同一套手动缩放，保证手柄始终可用。
                        self._begin_manual_resize(
                            Qt.Edge.RightEdge.value | Qt.Edge.BottomEdge.value,
                            event.globalPosition().toPoint())
                        return True
                    edge = self._edge_at(self.mapFromGlobal(
                        event.globalPosition().toPoint()))
                    if edge:
                        self._begin_manual_resize(
                            edge, event.globalPosition().toPoint())
                        return True
            elif etype == QEvent.Type.MouseMove:
                if (self._frameless_manual_edge
                        and event.buttons() & Qt.MouseButton.LeftButton):
                    self._apply_manual_resize(
                        event.globalPosition().toPoint())
                    return True
                self._update_resize_cursor(event.globalPosition().toPoint())
            elif etype == QEvent.Type.MouseButtonRelease:
                if self._frameless_manual_edge:
                    self._frameless_manual_edge = 0
                    self.releaseMouse()
                    self.unsetCursor()
                    return True
            elif etype in (QEvent.Type.UngrabMouse,
                           QEvent.Type.WindowDeactivate):
                self._frameless_manual_edge = 0
                self.unsetCursor()
            elif etype == QEvent.Type.WindowStateChange:
                title_bar = getattr(self, "title_bar", None)
                if title_bar is not None:
                    title_bar.set_maximized(self.isMaximized())
                grip = getattr(self, "_frameless_grip", None)
                if grip is not None:
                    grip.setVisible(self._can_resize())
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802 (Qt API)
        if (self._frameless_manual_edge
                and event.buttons() & Qt.MouseButton.LeftButton):
            self._apply_manual_resize(event.globalPosition().toPoint())
            event.accept()
            return
        self._update_resize_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802 (Qt API)
        self._frameless_manual_edge = 0
        self.unsetCursor()
        super().mouseReleaseEvent(event)
