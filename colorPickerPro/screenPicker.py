from PySide6.QtCore import Qt, QRect, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPixmap, QPen, QBrush, QFont, QCursor
from PySide6.QtWidgets import QApplication, QWidget


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
    MAG, SR, LS = 8, 5, 180

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self._active = False
        self._screen = None
        self._cached_img = None

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

    def paintEvent(self, event):
        if not self._active or self._screen is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, self._screen)
        pos = QCursor.pos()
        g = self.geometry()

        scale = self._screen.devicePixelRatio()

        cx, cy = pos.x() - g.x(), pos.y() - g.y()
        cx_s = cx * scale
        cy_s = cy * scale

        color = self._sample(cx_s, cy_s)
        sr, mag, ls = self.SR, self.MAG, self.LS

        sr_s = int(sr * scale)
        ss_s = sr_s * 2 + 1

        ss = sr * 2 + 1
        lx, ly = cx - ls // 2, cy + 30
        if ly + ls > self.height():
            ly = cy - ls - 30
        if lx < 10:
            lx = cx + 30
        if lx + ls > self.width():
            lx = cx - ls - 30
        samp = self._screen.copy(QRect(cx_s - sr_s, cy_s - sr_s, ss_s, ss_s))
        if samp.width() > 0 and samp.height() > 0:
            painter.drawPixmap(lx, ly, samp.scaled(ss * scale * mag, ss * scale * mag, Qt.IgnoreAspectRatio, Qt.FastTransformation))
        painter.setPen(QPen(QColor(255, 255, 255, 220), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(lx, ly, ss * mag, ss * mag)
        cx2, cy2 = lx + ss * mag // 2, ly + ss * mag // 2
        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(cx2 - 4, cy2, cx2 + 4, cy2)
        painter.drawLine(cx2, cy2 - 4, cx2, cy2 + 4)
        r, g, b_ = color.red(), color.green(), color.blue()
        px2, py2 = lx, ly + ss * mag + 8
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRoundedRect(px2, py2, ls, 72, 6, 6)
        painter.setBrush(color)
        painter.drawRoundedRect(px2 + 6, py2 + 6, 24, 24, 3, 3)
        painter.setPen(Qt.white)
        font = QFont("Consolas", 10)
        painter.setFont(font)
        painter.drawText(px2 + 36, py2 + 18, f"R:{r:3d}  G:{g:3d}  B:{b_:3d}")
        painter.drawText(px2 + 36, py2 + 38, f"#{r:02X}{g:02X}{b_:02X}")
        painter.drawText(px2 + 36, py2 + 58, "左键确定 右键取消")

    def mouseMoveEvent(self, event):
        if self._active:
            self.repaint()

    def mousePressEvent(self, event):
        if not self._active:
            return
        if event.button() == Qt.LeftButton:
            pos = QCursor.pos()
            g = self.geometry()
            scale = self._screen.devicePixelRatio()
            cx, cy = pos.x() - g.x(), pos.y() - g.y()
            cx *= scale
            cy *= scale
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
