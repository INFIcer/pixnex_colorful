import sys
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QGraphicsView,
    QGraphicsScene, QFileDialog, QMessageBox, QSizePolicy, QMenu,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QWheelEvent,
    QMouseEvent, QClipboard, QTransform, QAction,
)


class ViewTransform:
    def __init__(self, zoom=1.0, rotation=0.0, flip_h=False, flip_v=False, center_x=0.0, center_y=0.0):
        self.zoom = zoom
        self.rotation = rotation
        self.flip_h = flip_h
        self.flip_v = flip_v
        self.center_x = center_x
        self.center_y = center_y

    def copy(self):
        out = ViewTransform(self.zoom, self.rotation, self.flip_h, self.flip_v, self.center_x, self.center_y)
        if hasattr(self, '_scroll_bar'):
            out._scroll_bar = self._scroll_bar
        return out


class _GraphicsView(QGraphicsView):
    zoomChanged = Signal(float)
    rotationChanged = Signal(float)
    transformChanged = Signal()
    saveRequested = Signal()
    copyRequested = Signal()

    def __init__(self, rotate_speed=30.0, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self._vt = ViewTransform()
        self._min_zoom = 0.05
        self._max_zoom = 50.0
        self._rotate_speed = rotate_speed
        self._rot_dir = 0

        self._rot_timer = QTimer(self)
        self._rot_timer.setInterval(30)
        self._rot_timer.timeout.connect(self._on_rot_tick)

    def set_image(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        margin = 50000
        r = self._pixmap_item.boundingRect()
        self.scene().setSceneRect(r.adjusted(-margin, -margin, margin, margin))
        self.fit_in_view()

    def update_content(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        self._pixmap_item.setPixmap(pixmap)
        margin = 50000
        r = self._pixmap_item.boundingRect()
        self.scene().setSceneRect(r.adjusted(-margin, -margin, margin, margin))

    def _sync_center(self):
        c = self.mapToScene(self.viewport().rect().center())
        self._vt.center_x = c.x()
        self._vt.center_y = c.y()

    def _apply_transform(self):
        vt = self._vt
        self.resetTransform()
        self.scale(vt.zoom, vt.zoom)
        self.rotate(vt.rotation)
        if vt.flip_h:
            self.scale(-1, 1)
        if vt.flip_v:
            self.scale(1, -1)
        self._sync_center()
        self.zoomChanged.emit(vt.zoom)
        self.rotationChanged.emit(vt.rotation)
        self.transformChanged.emit()

    def set_zoom(self, zoom):
        self._vt.zoom = max(self._min_zoom, min(self._max_zoom, zoom))
        self._apply_transform()

    def set_zoom_100(self):
        self.set_zoom(1.0)

    def set_rotation(self, angle):
        self._vt.rotation = angle % 360
        self._apply_transform()

    def fit_in_view(self):
        if not hasattr(self, '_pixmap_item') or self._pixmap_item is None:
            return
        vt = self._vt
        vt.rotation = 0.0
        vt.flip_h = False
        vt.flip_v = False
        vp = self.viewport().rect()
        scene_rect = self._pixmap_item.boundingRect()
        if scene_rect.isEmpty():
            return
        scale_x = vp.width() / scene_rect.width()
        scale_y = vp.height() / scene_rect.height()
        s = min(scale_x, scale_y)
        vt.zoom = s
        self._apply_transform()
        self.centerOn(scene_rect.center())
        self._sync_center()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        cur = self._vt.zoom
        if event.angleDelta().y() > 0:
            new_zoom = cur * factor
        else:
            new_zoom = cur / factor
        new_zoom = max(self._min_zoom, min(self._max_zoom, new_zoom))
        if new_zoom != cur:
            self._vt.zoom = new_zoom
            self._apply_transform()

    def flip_horizontal(self):
        self._vt.flip_h = not self._vt.flip_h
        self._apply_transform()

    def flip_vertical(self):
        self._vt.flip_v = not self._vt.flip_v
        self._apply_transform()

    def rotate_90(self):
        self._vt.rotation = (self._vt.rotation + 90) % 360
        self._apply_transform()

    def reset_rotation(self):
        self._vt.rotation = 0.0
        self._apply_transform()

    def export_transform(self) -> ViewTransform:
        out = self._vt.copy()
        sb_h = self.horizontalScrollBar()
        sb_v = self.verticalScrollBar()
        if sb_h:
            out._scroll_bar = (sb_h.value(), sb_v.value())
        return out

    def import_transform(self, vt: ViewTransform):
        self._vt = vt.copy()
        self._apply_transform()
        if hasattr(vt, '_scroll_bar') and vt._scroll_bar is not None:
            self.centerOn(QPointF(vt.center_x, vt.center_y))
            sb_h = self.horizontalScrollBar()
            sb_v = self.verticalScrollBar()
            if sb_h:
                sb_h.setValue(vt._scroll_bar[0])
                sb_v.setValue(vt._scroll_bar[1])
        else:
            self.centerOn(QPointF(vt.center_x, vt.center_y))
        self._sync_center()

    def _on_rot_tick(self):
        step = self._rotate_speed * (self._rot_timer.interval() / 1000.0)
        self._vt.rotation = (self._vt.rotation + step * self._rot_dir) % 360
        self._apply_transform()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.XButton1:
            self._rot_dir = -1
            self._rot_timer.start()
            event.accept()
            return
        if event.button() == Qt.XButton2:
            self._rot_dir = 1
            self._rot_timer.start()
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self.fit_in_view()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.XButton1, Qt.XButton2):
            self._rot_timer.stop()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._sync_center()
        self.transformChanged.emit()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._sync_center()
        self.transformChanged.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_save = QAction("保存图像", self)
        act_save.triggered.connect(self.saveRequested.emit)
        menu.addAction(act_save)
        act_copy = QAction("复制图像", self)
        act_copy.triggered.connect(self.copyRequested.emit)
        menu.addAction(act_copy)
        menu.exec(event.globalPos())


class ImageViewer(QWidget):
    def __init__(self, pixmap: QPixmap = None, rotate_speed=30.0, default_name="", parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._default_name = default_name
        self._build_ui(rotate_speed)
        if pixmap is not None and not pixmap.isNull():
            self._view.set_image(pixmap)

    def _build_ui(self, rotate_speed):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        scene = QGraphicsScene(self)
        self._view = _GraphicsView(rotate_speed=rotate_speed)
        self._view.setScene(scene)
        self._view.zoomChanged.connect(self._on_zoom_changed)
        self._view.rotationChanged.connect(self._on_rotation_changed)
        self._view.saveRequested.connect(self._save_image)
        self._view.copyRequested.connect(self._copy_image)
        layout.addWidget(self._view, 1)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(8, 6, 8, 2)
        top_bar.setSpacing(6)

        self._zoom_label = QLabel("缩放:")
        top_bar.addWidget(self._zoom_label)

        self._zoom_edit = QLineEdit("100%")
        self._zoom_edit.setFixedWidth(65)
        self._zoom_edit.setAlignment(Qt.AlignCenter)
        self._zoom_edit.setStyleSheet(
            "font-size: 12px; padding: 2px 4px; border: 1px solid #888; border-radius: 3px;"
        )
        self._zoom_edit.returnPressed.connect(self._on_zoom_edit)
        top_bar.addWidget(self._zoom_edit)

        self._btn_100 = QPushButton("1:1")
        self._btn_100.setStyleSheet(self._btn_style("#5C6BC0"))
        self._btn_100.setCursor(Qt.PointingHandCursor)
        self._btn_100.clicked.connect(self._view.set_zoom_100)
        top_bar.addWidget(self._btn_100)

        self._btn_fit = QPushButton("适应")
        self._btn_fit.setStyleSheet(self._btn_style("#5C6BC0"))
        self._btn_fit.setCursor(Qt.PointingHandCursor)
        self._btn_fit.clicked.connect(self._view.fit_in_view)
        top_bar.addWidget(self._btn_fit)

        sep1 = QLabel("│")
        sep1.setStyleSheet("color: #bbb; font-size: 14px; padding: 0 2px;")
        top_bar.addWidget(sep1)

        self._rot_label = QLabel("旋转:")
        top_bar.addWidget(self._rot_label)

        self._rot_edit = QLineEdit("0°")
        self._rot_edit.setFixedWidth(55)
        self._rot_edit.setAlignment(Qt.AlignCenter)
        self._rot_edit.setStyleSheet(
            "font-size: 12px; padding: 2px 4px; border: 1px solid #888; border-radius: 3px;"
        )
        self._rot_edit.returnPressed.connect(self._on_rot_edit)
        top_bar.addWidget(self._rot_edit)

        self._btn_rot90 = QPushButton("90°")
        self._btn_rot90.setStyleSheet(self._btn_style("#7B1FA2"))
        self._btn_rot90.setCursor(Qt.PointingHandCursor)
        self._btn_rot90.clicked.connect(self._view.rotate_90)
        top_bar.addWidget(self._btn_rot90)

        self._btn_reset_rot = QPushButton("复位")
        self._btn_reset_rot.setStyleSheet(self._btn_style("#E53935"))
        self._btn_reset_rot.setCursor(Qt.PointingHandCursor)
        self._btn_reset_rot.clicked.connect(self._view.reset_rotation)
        top_bar.addWidget(self._btn_reset_rot)

        sep2 = QLabel("│")
        sep2.setStyleSheet("color: #bbb; font-size: 14px; padding: 0 2px;")
        top_bar.addWidget(sep2)

        self._btn_flip_h = QPushButton("↔")
        self._btn_flip_h.setStyleSheet(self._btn_style("#7B1FA2"))
        self._btn_flip_h.setCursor(Qt.PointingHandCursor)
        self._btn_flip_h.clicked.connect(self._view.flip_horizontal)
        top_bar.addWidget(self._btn_flip_h)

        self._btn_flip_v = QPushButton("↕")
        self._btn_flip_v.setStyleSheet(self._btn_style("#7B1FA2"))
        self._btn_flip_v.setCursor(Qt.PointingHandCursor)
        self._btn_flip_v.clicked.connect(self._view.flip_vertical)
        top_bar.addWidget(self._btn_flip_v)

        layout.addLayout(top_bar)

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{ padding: 4px 10px; font-size: 11px;
                background-color: {color}; color: white;
                border: none; border-radius: 3px; }}
            QPushButton:hover {{ background-color: {color}; }}
            QPushButton:pressed {{ background-color: {color}; }}
        """

    @property
    def transformChanged(self):
        return self._view.transformChanged

    def export_view_transform(self) -> ViewTransform:
        return self._view.export_transform()

    def import_view_transform(self, vt: ViewTransform):
        self._view.import_transform(vt)

    def set_content(self, pixmap: QPixmap):
        self._pixmap = pixmap
        if pixmap is not None and not pixmap.isNull():
            if not hasattr(self._view, '_pixmap_item') or self._view._pixmap_item is None:
                self._view.set_image(pixmap)
            else:
                self._view.update_content(pixmap)

    def _on_zoom_changed(self, zoom):
        self._zoom_edit.setText(f"{zoom * 100:.1f}%")

    def _on_zoom_edit(self):
        text = self._zoom_edit.text().replace("%", "").strip()
        try:
            val = float(text)
            if val <= 0:
                return
            self._view.set_zoom(val / 100.0)
        except ValueError:
            pass

    def _on_rotation_changed(self, angle):
        self._rot_edit.setText(f"{angle:.1f}°")

    def _on_rot_edit(self):
        text = self._rot_edit.text().replace("°", "").strip()
        try:
            val = float(text)
            self._view.set_rotation(val)
        except ValueError:
            pass

    def _save_image(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存图像", self._default_name,
            "PNG 图像 (*.png);;JPEG 图像 (*.jpg *.jpeg);;BMP 图像 (*.bmp)"
        )
        if path:
            self._pixmap.save(path)

    def _copy_image(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        QApplication.clipboard().setPixmap(self._pixmap)


def _demo_btn_style(color: str) -> str:
    return f"""
        QPushButton {{ padding: 4px 14px; font-size: 11px;
            background-color: {color}; color: white;
            border: none; border-radius: 3px; }}
        QPushButton:hover {{ background-color: {color}; }}
        QPushButton:pressed {{ background-color: {color}; }}
    """


def run_demo():
    import os
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(script_dir, os.pardir, "示例图.png"),
        os.path.join(script_dir, os.pardir, "示例图2.png"),
    ]
    for p in paths:
        if not os.path.exists(p):
            print(f"错误：未找到示例图像文件: {p}")
            sys.exit(1)

    pixmaps = [QPixmap(p) for p in paths]
    for pm in pixmaps:
        if pm.isNull():
            print("错误：无法加载示例图像")
            sys.exit(1)

    window = QWidget()
    window.setWindowTitle("图像查看器演示")
    window.resize(900, 680)

    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    viewer = ImageViewer(pixmaps[0], rotate_speed=30.0, default_name="示例图")
    outer.addWidget(viewer, 1)

    demo_bar = QHBoxLayout()
    demo_bar.setContentsMargins(8, 4, 8, 6)

    _idx = [0]
    btn_switch = QPushButton("切换图像")
    btn_switch.setStyleSheet(_demo_btn_style("#FF8F00"))
    btn_switch.setCursor(Qt.PointingHandCursor)

    def on_switch():
        _idx[0] = 1 - _idx[0]
        btn_switch.setText(f"图像 {_idx[0] + 1}")
        viewer.set_content(pixmaps[_idx[0]])

    btn_switch.clicked.connect(on_switch)
    demo_bar.addWidget(btn_switch)

    _saved_vt = [None]
    btn_export = QPushButton("导出")
    btn_export.setStyleSheet(_demo_btn_style("#00897B"))
    btn_export.setCursor(Qt.PointingHandCursor)
    def on_export():
        _saved_vt[0] = viewer.export_view_transform()
        btn_export.setText("已导出")
    btn_export.clicked.connect(on_export)
    demo_bar.addWidget(btn_export)

    btn_import = QPushButton("导入")
    btn_import.setStyleSheet(_demo_btn_style("#5C6BC0"))
    btn_import.setCursor(Qt.PointingHandCursor)
    def on_import():
        if _saved_vt[0] is not None:
            viewer.import_view_transform(_saved_vt[0])
    btn_import.clicked.connect(on_import)
    demo_bar.addWidget(btn_import)

    demo_bar.addStretch()

    lbl_hint = QLabel("左键拖拽平移 | 滚轮缩放 | 侧键旋转")
    lbl_hint.setStyleSheet("color: #999; font-size: 11px;")
    demo_bar.addWidget(lbl_hint)

    outer.addLayout(demo_bar)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
