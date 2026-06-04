import os
import sys

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPen, QFont, QKeySequence, QImage,
    QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent,
)


class ImageDropWidget(QWidget):
    imageReceived = Signal(object, str)

    def __init__(self, placeholder_text="在此处粘贴或拖入图像",
                 drop_hint="释放以读取图像", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder_text
        self._drop_hint = drop_hint
        self._pixmap = QPixmap()
        self._drag_hover = False
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def pixmap(self) -> QPixmap:
        return self._pixmap

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        if self._drag_hover:
            p.fillRect(self.rect(), QColor(30, 42, 58))
            overlay = QColor(0, 120, 215, 30)
            p.fillRect(self.rect(), overlay)
            pen = QPen(QColor(0, 120, 215), 2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.setPen(QColor(0, 120, 215))
            font = QFont("Microsoft YaHei", 14)
            font.setBold(True)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignCenter, self._drop_hint)
        else:
            p.fillRect(self.rect(), QColor(26, 26, 26))
            pen = QPen(QColor(85, 85, 85), 2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
            p.setPen(QColor(150, 150, 150))
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(self.rect(), Qt.AlignCenter, self._placeholder)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            self._drag_hover = True
            self.update()
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._drag_hover = False
        self.update()

    def dropEvent(self, event: QDropEvent):
        self._drag_hover = False
        self._process_mime_data(event.mimeData())
        self.update()
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
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
    app.setStyle("Fusion")

    window = QWidget()
    window.setWindowTitle("图像拖放控件演示")
    window.resize(500, 400)
    window.setStyleSheet("background-color: #1a1a1a;")

    layout = QVBoxLayout(window)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    label = QLabel("将图像文件拖入下方区域，或点击区域后按 Ctrl+V 粘贴")
    label.setStyleSheet("color: #ccc; font-size: 13px;")
    label.setAlignment(Qt.AlignCenter)
    layout.addWidget(label)

    drop_widget = ImageDropWidget()
    layout.addWidget(drop_widget, 1)

    info = QLabel("等待图像...")
    info.setStyleSheet("color: #999; font-size: 12px;")
    info.setAlignment(Qt.AlignCenter)
    layout.addWidget(info)

    def on_image(pixmap, name):
        text = f"已载入图像"
        if name:
            text += f": {name}"
        text += f"  ({pixmap.width()}×{pixmap.height()})"
        info.setText(text)

    drop_widget.imageReceived.connect(on_image)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
