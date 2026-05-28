"""
自定义无边框窗口，支持标题栏、拖拽、缩放和折叠。

提供：
- PixmapWidget：双缓冲 QPixmap 显示控件
- CustomFramelessWindow：可复用的无边框窗口基类
"""

from typing import Optional

from PySide6.QtCore import QEvent, Qt, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QCursor, QMouseEvent, QResizeEvent, QShortcut
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout


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
            scaled = self._pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)


class CustomFramelessWindow(QWidget):
    """
    可复用的无边框窗口，提供：

    - 带关闭和最小化按钮的标题栏
    - 通过 add_title_bar_button() 插入自定义按钮
    - 标题栏拖拽
    - 边缘/角缩放
    - 双击标题栏或按空格键折叠/展开
    - 可配置的边框颜色
    - 内容控件区域
    """

    EDGE_MARGIN = 8
    BTN_SIZE = 26

    def __init__(self, title: str = "Window", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        self._drag_active = False
        self._resize_active = False
        self._resize_edge = 0
        self._resize_start_geo = None
        self._resize_start_global = None
        self._drag_start = None
        self._collapsed = False
        self._restore_size = None

        self._border_color = QColor(0, 120, 215)

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.resize(480, 360)
        self.setMinimumSize(200, 120)

        self._setup_style()
        self._build_title_bar()
        self._content = QWidget(self)
        self._content.setAutoFillBackground(True)
        self._content.setMouseTracking(True)
        self._content.installEventFilter(self)

        QShortcut(Qt.Key_Space, self, self._toggle_collapse)

    def _setup_style(self):
        self.setStyleSheet("""
            #_customFrameWin { background-color: #1a1a1a; }
            #titleBar { background-color: #2a2a2a; }
        """)
        self.setObjectName("_customFrameWin")

    def _build_title_bar(self):
        self._title_bar = QWidget(self)
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setFixedHeight(32)

        self._title_lbl = QLabel(f"  {self.windowTitle()}", self._title_bar)
        self._title_lbl.setStyleSheet(
            "color:white;font-size:13px;font-weight:bold;background:transparent;"
        )
        self._title_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._btn_min = QPushButton("\u2500", self._title_bar)
        self._btn_min.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._btn_min.setStyleSheet(self._btn_style("#555"))

        self._btn_close = QPushButton("\u2715", self._title_bar)
        self._btn_close.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._btn_close.setStyleSheet(self._btn_style("#C33"))

        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_close.clicked.connect(self.close)

        self._title_layout = QHBoxLayout(self._title_bar)
        self._title_layout.setContentsMargins(4, 0, 4, 0)
        self._title_layout.setSpacing(2)
        self._title_layout.addWidget(self._title_lbl)
        self._title_layout.addStretch()
        self._title_layout.addWidget(self._btn_min)
        self._title_layout.addWidget(self._btn_close)

        self._title_bar.setMouseTracking(True)
        self._title_bar.installEventFilter(self)

    def add_title_bar_button(self, btn: QPushButton) -> QPushButton:
        # pos = self._title_layout.count() - 2
        self._title_layout.insertWidget(2, btn)
        return btn

    def content_widget(self) -> QWidget:
        return self._content

    def set_content_widget(self, w: QWidget):
        old = self._content
        self._content = w
        self._content.setParent(self)
        self._content.setMouseTracking(True)
        self._content.installEventFilter(self)
        if old is not None:
            old.deleteLater()

    def set_title(self, title: str):
        self._title_lbl.setText(f"  {title}")

    def set_border_color(self, color: QColor):
        self._border_color = color
        self.update()

    def _should_allow_resize(self) -> bool:
        return True

    # ---- 事件处理 -----------------------------------------------------

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove:
            self.mouseMoveEvent(event)
            return False
        return super().eventFilter(obj, event)

    def resizeEvent(self, e: QResizeEvent):
        super().resizeEvent(e)
        w, h = e.size().width(), e.size().height()
        self._title_bar.resize(w, 32)
        self._content.setGeometry(4, 36, w - 8, h - 40)

    def _edge_at(self, pos: QPoint) -> Optional[int]:
        r, m = self.rect(), self.EDGE_MARGIN
        e = Qt.Edge(0)
        if pos.x() <= m:
            e |= Qt.LeftEdge
        if pos.x() >= r.width() - m:
            e |= Qt.RightEdge
        if pos.y() <= m:
            e |= Qt.TopEdge
        if pos.y() >= r.height() - m:
            e |= Qt.BottomEdge
        return e if e else None

    @staticmethod
    def _resize_cursor(edge: int) -> Qt.CursorShape:
        if edge in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edge in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edge in (Qt.LeftEdge, Qt.RightEdge):
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        if self._should_allow_resize() and not self._collapsed:
            edge = self._edge_at(pos)
            if edge:
                self._resize_active = True
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_global = e.globalPosition().toPoint()
                self.setCursor(self._resize_cursor(edge))
                e.accept()
                return

        if pos.y() < 32:
            self._drag_active = True
            self._drag_start = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return

    def mouseMoveEvent(self, e: QMouseEvent):
        gpos = e.globalPosition().toPoint()
        local_pos = self.mapFromGlobal(gpos)
        if self._drag_active and self._drag_start is not None:
            self.move(gpos - self._drag_start)
            e.accept()
            return

        if self._resize_active:
            delta = gpos - self._resize_start_global
            g = QRect(self._resize_start_geo)
            ed = self._resize_edge
            if ed & Qt.LeftEdge:
                g.setLeft(g.left() + delta.x())
            if ed & Qt.RightEdge:
                g.setRight(g.right() + delta.x())
            if ed & Qt.TopEdge:
                g.setTop(g.top() + delta.y())
            if ed & Qt.BottomEdge:
                g.setBottom(g.bottom() + delta.y())
            if g.width() >= self.minimumWidth() and g.height() >= self.minimumHeight():
                self.setGeometry(g)
            e.accept()
            return

        edge = self._edge_at(local_pos)
        if edge and self._should_allow_resize() and not self._collapsed:
            self.setCursor(self._resize_cursor(edge))
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_active = False
            self._resize_active = False
            self._resize_edge = 0
            self._resize_start_geo = None
            self._resize_start_global = None
            self._drag_start = None
            self.setCursor(Qt.ArrowCursor)
            e.accept()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton and e.position().toPoint().y() < 32:
            self._toggle_collapse()

    def paintEvent(self, e):
        p = QPainter(self)

        if self._collapsed:
            p.setPen(QPen(QColor(0, 120, 215), 1))
            p.drawLine(2, 31, self.width() - 2, 31)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self._border_color, 2))
            r = self._content.geometry().adjusted(-4, -4, 4, 4)
            p.drawRect(r.adjusted(1, 1, -1, -1))

    def _toggle_collapse(self):
        if self._collapsed:
            self._collapsed = False
            self.setMinimumSize(200, 120)
            self._content.show()
            if self._restore_size is not None:
                g = self.geometry()
                self.setGeometry(g.x(), g.y(), self._restore_size.width(), self._restore_size.height())
                self._restore_size = None
        else:
            self._collapsed = True
            self._restore_size = self.geometry().size()
            self.setMinimumSize(0, 0)
            self._content.hide()
            g = self.geometry()
            self.setGeometry(g.x(), g.y(), g.width(), 32)

    @staticmethod
    def _btn_style(bg: str) -> str:
        return (
            f"QPushButton{{background:rgba(40,40,40,180);color:white;"
            f"border:none;font-size:13px;border-radius:4px;}}"
            f"QPushButton:hover{{background:{bg};}}"
        )


def run_demo():
    from PySide6.QtWidgets import QApplication  
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    demo = CustomFramelessWindow()
    demo.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_demo()