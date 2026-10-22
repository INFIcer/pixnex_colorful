"""图像拖放区：拖入文件 / 拖入图像 / Ctrl+V 粘贴，都可读取图像。

外观完全自绘（虚线圆角边框 + 面板底色 + 拖拽高亮），颜色、圆角、字号全部来自
设计令牌，本文件不写内联样式表。``dragActive`` 是动态属性：拖拽进入时置为
True 并 repolish，样式表 / 自绘都能据此切换高亮态。
"""

import os
import sys

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFont,
    QImage, QKeySequence, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QSizePolicy, QVBoxLayout, QWidget,
)

from .ui.components import CaptionLabel, SubtitleLabel, TitleLabel
from .ui.theme import ensure_theme, repolish
from .ui.tokens import RADIUS, SPACE, TYPE, qcolor


def _soft_accent() -> QColor:
    """accent 的低透明度版本（令牌里的 accent_soft 是 CSS 字符串，绘制时用 QColor）。"""
    color = qcolor("accent")
    color.setAlpha(40)
    return color


def _elide(painter: QPainter, text: str, rect: QRectF) -> str:
    """小尺寸下用省略号代替被裁掉的文字（拖放区宽度随窗口变化）。"""
    available = max(0, int(rect.width()) - SPACE.sm * 2)
    if available <= 0:
        return text
    return painter.fontMetrics().elidedText(
        text, Qt.TextElideMode.ElideRight, available)


class ImageDropWidget(QWidget):
    imageReceived = Signal(object, str)

    def __init__(self, placeholder_text="拖入或粘贴图像",
                 drop_hint="释放以载入", parent=None):
        super().__init__(parent)
        self._placeholder_text = placeholder_text
        self._drop_hint_text = drop_hint
        self._pixmap = QPixmap()
        self._drag_hover = False

        self._placeholder_font = QFont(TYPE.family)
        self._placeholder_font.setPixelSize(TYPE.caption_px)
        self._drop_hint_font = QFont(TYPE.family)
        self._drop_hint_font.setPixelSize(TYPE.body_px)
        self._drop_hint_font.setBold(True)
        self._placeholder_color = qcolor("text_muted")
        self._drop_hint_color = qcolor("accent")

        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("dragActive", False)
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

    # ------------------------------------------------------------------
    # 文本 / 图像
    # ------------------------------------------------------------------
    @property
    def placeholder_text(self) -> str:
        return self._placeholder_text

    @placeholder_text.setter
    def placeholder_text(self, text: str):
        self._placeholder_text = text
        self.update()

    @property
    def drop_hint_text(self) -> str:
        return self._drop_hint_text

    @drop_hint_text.setter
    def drop_hint_text(self, text: str):
        self._drop_hint_text = text
        self.update()

    def set_placeholder_style(self, font: QFont = None, color: QColor = None):
        if font is not None:
            self._placeholder_font = font
        if color is not None:
            self._placeholder_color = color
        self.update()

    def set_drop_hint_style(self, font: QFont = None, color: QColor = None):
        if font is not None:
            self._drop_hint_font = font
        if color is not None:
            self._drop_hint_color = color
        self.update()

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def pixmap(self) -> QPixmap:
        return self._pixmap

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(240, 88)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(120, 44)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def _set_drag_active(self, active: bool):
        if self._drag_hover == active:
            return
        self._drag_hover = active
        self.setProperty("dragActive", active)
        repolish(self)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        active = bool(self.property("dragActive"))

        if active:
            painter.setBrush(_soft_accent())
            pen = QPen(qcolor("accent"), 2)
        else:
            painter.setBrush(qcolor("surface"))
            pen = QPen(qcolor("accent") if self.hasFocus()
                       else qcolor("border_strong"), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(outer, RADIUS.lg, RADIUS.lg)

        inner = outer.adjusted(SPACE.sm, SPACE.sm, -SPACE.sm, -SPACE.sm)
        if not self._pixmap.isNull() and inner.width() > 0 and inner.height() > 0:
            scaled = self._pixmap.scaled(
                inner.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(inner.center())
            painter.drawPixmap(target.toRect(), scaled)

        if active:
            painter.setPen(self._drop_hint_color)
            painter.setFont(self._drop_hint_font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             _elide(painter, self._drop_hint_text, outer))
        elif self._pixmap.isNull():
            painter.setPen(self._placeholder_color)
            painter.setFont(self._placeholder_font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             _elide(painter, self._placeholder_text, outer))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    # ------------------------------------------------------------------
    # 拖放 / 键盘
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            self._set_drag_active(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent):
        self._set_drag_active(False)
        self._process_mime_data(event.mimeData())
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_from_clipboard()
        else:
            super().keyPressEvent(event)

    def _paste_from_clipboard(self):
        mime = QApplication.clipboard().mimeData()
        self._process_mime_data(mime)

    def _process_mime_data(self, mime):
        if mime.hasImage():
            image = mime.imageData()
            if isinstance(image, QImage) and not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self._pixmap = pixmap
                self.imageReceived.emit(pixmap, "")
                self.update()
                return

        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    pixmap = QPixmap(path)
                    if not pixmap.isNull():
                        self._pixmap = pixmap
                        name = os.path.basename(path)
                        self.imageReceived.emit(pixmap, name)
                        self.update()
                        return

        if mime.hasText():
            path = mime.text().strip().strip('"').strip("'")
            if os.path.isfile(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._pixmap = pixmap
                    name = os.path.basename(path)
                    self.imageReceived.emit(pixmap, name)
                    self.update()


def run_demo():
    app = QApplication.instance() or QApplication(sys.argv)
    ensure_theme(app)

    window = QWidget()
    window.setWindowTitle("图像拖放控件演示")
    window.resize(500, 400)

    layout = QVBoxLayout(window)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    layout.addWidget(TitleLabel("图像拖放区"))
    layout.addWidget(SubtitleLabel("拖入图像，或按 Ctrl+V 粘贴"))

    drop_widget = ImageDropWidget()
    layout.addWidget(drop_widget, 1)

    info = CaptionLabel("等待图像")
    info.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(info)

    def on_image(pixmap, name):
        text = "已载入"
        if name:
            text += f"：{name}"
        text += f"（{pixmap.width()}×{pixmap.height()}）"
        info.setText(text)

    drop_widget.imageReceived.connect(on_image)
    drop_widget.setFocus()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
