"""全屏取色覆盖层：屏幕截图 + 放大镜 + 颜色读数。

交互行为保持不变：全屏覆盖、放大镜跟随光标、左键取色、右键/ESC 取消。
表现层改为使用统一设计令牌（颜色/字体/圆角），并保证放大镜与读数面板
在靠近屏幕边缘时仍被夹紧在屏幕内。
"""

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QPainter, QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from .ui.tokens import RADIUS, SPACE, TYPE, qcolor

# 取色覆盖层操作提示（尺寸测量与绘制共用同一份文案）。
HINT_TEXT = "左键取色 · 右键取消"


class ScreenPicker(QObject):
    colorPicked = Signal(int, int, int)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._picking = False
        self._overlay = _PickerOverlay()
        self._overlay.colorPicked.connect(self._on_pick)
        self._overlay.cancelled.connect(self._on_cancel)

    def start_pick(self):
        if self._picking:
            return
        self._picking = True
        self._overlay.start_picking()

    def _on_pick(self, r, g, b):
        self._picking = False
        self.colorPicked.emit(r, g, b)

    def _on_cancel(self):
        self._picking = False
        self.cancelled.emit()


class _PickerOverlay(QWidget):
    colorPicked = Signal(int, int, int)
    cancelled = Signal()

    MAG = 8          # 放大倍数
    SR = 5           # 采样半径（逻辑像素）
    PANEL_MIN_WIDTH = 176   # 读数面板最小宽度（逻辑像素）

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self._active = False
        self._screen = None
        self._cached_img = None
        self._target_screen = None

    # ------------------------------------------------------------------
    def start_picking(self):
        self._active = True
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        self._target_screen = screen
        geo = screen.geometry()
        raw = screen.grabWindow(0, 0, 0, geo.width(), geo.height())
        self._screen = raw
        self._cached_img = None
        self.setGeometry(geo)
        self.showFullScreen()
        self.raise_()
        QApplication.processEvents()
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    def _fonts(self):
        value_font = QFont(TYPE.mono_family)
        value_font.setPixelSize(TYPE.caption_px)
        hint_font = QFont(TYPE.family)
        hint_font.setPixelSize(TYPE.tiny_px)
        return value_font, hint_font

    def _cursor_position(self):
        """当前鼠标位置；单独成方法便于无屏幕抓取时渲染自检。"""
        return QCursor.pos()

    def _readout_size(self):
        """读数面板的尺寸（逻辑像素）：由字体度量算出，避免文字被裁切。"""
        value_font, hint_font = self._fonts()
        value_metrics = QFontMetrics(value_font)
        hint_metrics = QFontMetrics(hint_font)
        panel_pad = SPACE.sm
        swatch_size = TYPE.body_px + SPACE.md
        text_w = max(value_metrics.horizontalAdvance("R:255  G:255  B:255"),
                     value_metrics.horizontalAdvance("#" + "F" * 6),
                     hint_metrics.horizontalAdvance(HINT_TEXT))
        panel_w = max(self.PANEL_MIN_WIDTH,
                      panel_pad * 2 + swatch_size + SPACE.sm + text_w)
        panel_h = (panel_pad * 2 + value_metrics.height() * 2
                   + SPACE.xxs * 2 + hint_metrics.height())
        return panel_w, panel_h

    def _lens_and_panel_rects(self, cx, cy):
        """放大镜与读数面板的矩形，二者都夹紧在窗口内（靠近屏幕边缘也不越界）。"""
        lens = (self.SR * 2 + 1) * self.MAG
        pad = SPACE.md
        width, height = self.width(), self.height()
        panel_w, panel_h = self._readout_size()
        panel_w = min(panel_w, max(1, width - pad * 2))

        # 放大镜优先放在光标右下方，越界就翻到另一侧，最后夹紧在屏幕内。
        lx = cx + SPACE.xl
        if lx + lens > width - pad:
            lx = cx - SPACE.xl - lens
        lx = int(max(pad, min(lx, width - pad - lens)))
        ly = cy + SPACE.xl
        if ly + lens > height - pad:
            ly = cy - SPACE.xl - lens
        ly = int(max(pad, min(ly, height - pad - lens)))

        # 读数面板默认贴在放大镜下方，放不下就翻到上方，再整体夹紧。
        px = int(max(pad, min(lx, width - pad - panel_w)))
        py = ly + lens + SPACE.sm
        if py + panel_h > height - pad:
            py = ly - SPACE.sm - panel_h
        py = int(max(pad, min(py, height - pad - panel_h)))
        return QRect(lx, ly, lens, lens), QRect(px, py, panel_w, panel_h)

    def paintEvent(self, event):
        if not self._active or self._screen is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, self._screen)

        pos = self._cursor_position()
        geo = self.geometry()
        scale = self._screen.devicePixelRatio()
        cx = pos.x() - geo.x()
        cy = pos.y() - geo.y()
        sample_x = cx * scale
        sample_y = cy * scale
        color = self._sample(sample_x, sample_y)

        lens_rect, panel_rect = self._lens_and_panel_rects(cx, cy)

        sr_s = int(self.SR * scale)
        samp = self._screen.copy(
            QRect(sample_x - sr_s, sample_y - sr_s, sr_s * 2 + 1, sr_s * 2 + 1))
        if samp.width() > 0 and samp.height() > 0:
            # 最近邻放大，保持被采样的像素边界清晰。
            zoomed = samp.scaled(lens_rect.width(), lens_rect.height(),
                                 Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawPixmap(lens_rect.topLeft(), zoomed)

        border = qcolor("border_strong")
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(border, 1))
        painter.drawRect(lens_rect.adjusted(-1, -1, 1, 1))
        painter.setPen(QPen(qcolor("accent"), 2))
        painter.drawRect(lens_rect)

        center_x = lens_rect.left() + lens_rect.width() // 2
        center_y = lens_rect.top() + lens_rect.height() // 2
        painter.setPen(QPen(qcolor("text"), 2))
        painter.drawLine(center_x - 4, center_y, center_x + 4, center_y)
        painter.drawLine(center_x, center_y - 4, center_x, center_y + 4)

        self._draw_readout(painter, color, panel_rect)

    def _draw_readout(self, painter, color, panel):
        """在放大镜旁绘制颜色读数面板。"""
        r, g, b = color.red(), color.green(), color.blue()
        rgb_text = f"R:{r:3d}  G:{g:3d}  B:{b:3d}"
        hex_text = f"#{r:02X}{g:02X}{b:02X}"
        hint_text = HINT_TEXT

        value_font, hint_font = self._fonts()
        value_metrics = QFontMetrics(value_font)
        hint_metrics = QFontMetrics(hint_font)
        panel_pad = SPACE.sm
        swatch_size = TYPE.body_px + SPACE.md

        panel_bg = qcolor("window")
        panel_bg.setAlpha(235)
        border = qcolor("border_strong")
        painter.setPen(QPen(border, 1))
        painter.setBrush(panel_bg)
        painter.drawRoundedRect(panel, RADIUS.md, RADIUS.md)

        swatch_size = min(swatch_size, panel.height() - panel_pad * 2)
        swatch_y = panel.top() + (panel.height() - swatch_size) // 2
        swatch_rect = QRect(panel.left() + panel_pad, swatch_y,
                            swatch_size, swatch_size)
        painter.setPen(QPen(border, 1))
        painter.setBrush(color)
        painter.drawRoundedRect(swatch_rect, RADIUS.sm, RADIUS.sm)

        text_x = swatch_rect.right() + 1 + SPACE.sm
        top = panel.top() + panel_pad
        row_h = value_metrics.height()
        painter.setFont(value_font)
        painter.setPen(qcolor("text"))
        painter.drawText(text_x, top + value_metrics.ascent(), rgb_text)
        painter.drawText(text_x,
                         top + row_h + SPACE.xxs + value_metrics.ascent(),
                         hex_text)
        painter.setFont(hint_font)
        painter.setPen(qcolor("text_muted"))
        painter.drawText(text_x,
                         top + row_h * 2 + SPACE.xxs * 2 + hint_metrics.ascent(),
                         hint_text)

    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event):
        if self._active:
            self.repaint()

    def mousePressEvent(self, event):
        if not self._active:
            return
        if event.button() == Qt.LeftButton:
            pos = self._cursor_position()
            geo = self.geometry()
            scale = self._screen.devicePixelRatio()
            cx = (pos.x() - geo.x()) * scale
            cy = (pos.y() - geo.y()) * scale
            c = self._sample(cx, cy)
            self._active = False
            self.hide()
            self.colorPicked.emit(c.red(), c.green(), c.blue())
        if event.button() == Qt.RightButton:
            self._active = False
            self.hide()
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._active = False
            self.hide()
            self.cancelled.emit()

    def _sample(self, x, y):
        if self._screen is None:
            return QColor(0, 0, 0)
        if self._cached_img is None:
            self._cached_img = self._screen.toImage()
        img = self._cached_img
        if 0 <= x < img.width() and 0 <= y < img.height():
            return img.pixelColor(x, y)
        return QColor(0, 0, 0)
