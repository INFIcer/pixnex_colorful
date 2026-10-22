"""图像查看器：缩放、平移、旋转、翻转的画布。

工具栏使用 :class:`FlowLayout`，窗口变窄时按钮自动换行，不会挤出窗口；
所有颜色 / 字号 / 间距都来自设计令牌（``colorPickerPro.ui``），本文件不写
任何内联样式表。画布本身是 ``QGraphicsView``，objectName 为 ``ImageCanvas``，
外观由全局 QSS 负责。

交互约定（保持不变）：
    滚轮缩放、左键拖动平移、中键适应窗口、鼠标侧键按住旋转、
    右键菜单保存 / 复制图像、``transformChanged`` 通知外部同步变换。
"""

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsScene, QGraphicsView, QLineEdit,
    QMenu, QSizePolicy, QVBoxLayout, QWidget,
)

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.ui.components import (
        CaptionLabel, IconButton, flow, get_save_file_name,
    )
    from colorPickerPro.ui.theme import ensure_theme
    from colorPickerPro.ui.tokens import SPACE
else:
    from .ui.components import (
        CaptionLabel, IconButton, flow, get_save_file_name,
    )
    from .ui.theme import ensure_theme
    from .ui.tokens import SPACE


class ViewTransform:
    """一个视图的缩放 / 旋转 / 翻转 / 中心点状态（跨视图同步的单位）。"""

    def __init__(self, zoom=1.0, rotation=0.0, flip_h=False, flip_v=False,
                 center_x=0.0, center_y=0.0):
        self.zoom = zoom
        self.rotation = rotation
        self.flip_h = flip_h
        self.flip_v = flip_v
        self.center_x = center_x
        self.center_y = center_y

    def copy(self):
        out = ViewTransform(self.zoom, self.rotation, self.flip_h, self.flip_v,
                            self.center_x, self.center_y)
        if hasattr(self, '_scroll_bar'):
            out._scroll_bar = self._scroll_bar
        return out


class _GraphicsView(QGraphicsView):
    """画布：负责绘制与交互，不涉及工具栏控件。"""

    zoomChanged = Signal(float)
    rotationChanged = Signal(float)
    transformChanged = Signal()
    saveRequested = Signal()
    copyRequested = Signal()

    def __init__(self, rotate_speed=30.0, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # 缩放锚点跟随鼠标；但窗口尺寸变化时锚点必须改成「视口中心」，
        # 否则画面会朝着鼠标位置挪，横向对比缩放窗口时表现为图像偏移。
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._vt = ViewTransform()
        self._min_zoom = 0.05
        self._max_zoom = 50.0
        self._rotate_speed = rotate_speed
        self._rot_dir = 0
        self._pixmap_item = None
        self._in_resize = False

        self._rot_timer = QTimer(self)
        self._rot_timer.setInterval(30)
        self._rot_timer.timeout.connect(self._on_rot_tick)

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------
    def set_image(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        margin = 50000
        r = self._pixmap_item.boundingRect()
        self.scene().setSceneRect(r.adjusted(-margin, -margin, margin, margin))
        self.fit_in_view()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        # QGraphicsView 的默认 sizeHint 取自屏幕（例如 1920x1080）。如果直接
        # 透传给布局，会把所在卡片 / 窗口的最小宽度撑到屏幕大小，窗口就再也
        # 缩不窄。这里给一个普通画布尺寸，实际大小由布局的 stretch 决定。
        return QSize(320, 240)

    def update_content(self, pixmap: QPixmap):
        self._orig_pixmap = pixmap
        self._pixmap_item.setPixmap(pixmap)
        margin = 50000
        r = self._pixmap_item.boundingRect()
        self.scene().setSceneRect(r.adjusted(-margin, -margin, margin, margin))

    # ------------------------------------------------------------------
    # 变换
    # ------------------------------------------------------------------
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
        if self._pixmap_item is None:
            return
        vt = self._vt
        vt.rotation = 0.0
        vt.flip_h = False
        vt.flip_v = False
        vp = self.viewport().rect()
        scene_rect = self._pixmap_item.boundingRect()
        if scene_rect.isEmpty() or vp.width() <= 0 or vp.height() <= 0:
            return
        scale_x = vp.width() / scene_rect.width()
        scale_y = vp.height() / scene_rect.height()
        vt.zoom = min(scale_x, scale_y)
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
            sb_h = self.horizontalScrollBar()
            sb_v = self.verticalScrollBar()
            if sb_h:
                sb_h.setValue(vt._scroll_bar[0])
                sb_v.setValue(vt._scroll_bar[1])
        # 场景中心是唯一与视口尺寸无关的量：最后再以它为准。
        # 否则尺寸不同的视图会各自套用对方的滚动条像素值而错位，
        # 横向对比缩放窗口时就会「图像偏移」（README 已知问题）。
        self.centerOn(QPointF(vt.center_x, vt.center_y))
        # 滚动条是整数像素，centerOn() 会把中心量化（缩放小于 100% 时误差被
        # 放大）；这里保留请求值，让它成为同步的不动点，避免每次同步都向下
        # 取整造成累积漂移。
        self._vt.center_x = vt.center_x
        self._vt.center_y = vt.center_y

    def _on_rot_tick(self):
        step = self._rotate_speed * (self._rot_timer.interval() / 1000.0)
        self._vt.rotation = (self._vt.rotation + step * self._rot_dir) % 360
        self._apply_transform()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        """窗口尺寸变化时保持「上一次确定的场景中心」不变。

        滚动条是整数像素，Qt 在视口尺寸变化时会按像素重新取整；如果不纠正，
        横向对比每次缩放窗口都会把中心往下取整一点，看起来就是画面慢慢偏移。
        这里用已记录的中心再居中一次，并把请求值写回 ``_vt``，让同步保持不动点。
        """
        requested = None
        if self._pixmap_item is not None:
            requested = QPointF(self._vt.center_x, self._vt.center_y)
        self._in_resize = True
        try:
            super().resizeEvent(event)
        finally:
            self._in_resize = False
        if requested is None:
            return
        self._in_resize = True
        try:
            self.centerOn(requested)
        finally:
            self._in_resize = False
        self._vt.center_x = requested.x()
        self._vt.center_y = requested.y()
        self.transformChanged.emit()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.XButton1:
            self._rot_dir = -1
            self._rot_timer.start()
            event.accept()
            return
        if event.button() == Qt.MouseButton.XButton2:
            self._rot_dir = 1
            self._rot_timer.start()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.fit_in_view()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.XButton1, Qt.MouseButton.XButton2):
            self._rot_timer.stop()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._sync_center()
        self.transformChanged.emit()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        # 尺寸变化期间的滚动是 Qt 按像素重算造成的，不算用户平移，
        # 不能覆盖已记录的中心（否则会累积取整漂移）。
        if self._in_resize:
            return
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
    """带工具栏的图像画布（工具栏在底部，窄窗口自动换行）。"""

    def __init__(self, pixmap: QPixmap = None, rotate_speed=30.0,
                 default_name="", parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._default_name = default_name
        self._build_ui(rotate_speed)
        if pixmap is not None and not pixmap.isNull():
            self._view.set_image(pixmap)

    # ------------------------------------------------------------------
    # 构建界面
    # ------------------------------------------------------------------
    def _build_ui(self, rotate_speed):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.xs)

        scene = QGraphicsScene(self)
        self._view = _GraphicsView(rotate_speed=rotate_speed)
        self._view.setObjectName("ImageCanvas")
        self._view.setScene(scene)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        self._view.zoomChanged.connect(self._on_zoom_changed)
        self._view.rotationChanged.connect(self._on_rotation_changed)
        self._view.saveRequested.connect(self._save_image)
        self._view.copyRequested.connect(self._copy_image)
        layout.addWidget(self._view, 1)

        self._zoom_edit = QLineEdit("100%")
        self._zoom_edit.setObjectName("ViewerValueEdit")
        self._zoom_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_edit.setMinimumWidth(58)
        self._zoom_edit.setMaximumWidth(70)
        self._zoom_edit.setToolTip("缩放百分比，回车确认")
        self._zoom_edit.returnPressed.connect(self._on_zoom_edit)

        self._btn_100 = IconButton("zoom-reset", tooltip="原始比例 (1:1)")
        self._btn_100.clicked.connect(self._view.set_zoom_100)

        self._btn_fit = IconButton("fit", tooltip="适应窗口")
        self._btn_fit.clicked.connect(self._view.fit_in_view)

        self._rot_edit = QLineEdit("0°")
        self._rot_edit.setObjectName("ViewerValueEdit")
        self._rot_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rot_edit.setMinimumWidth(52)
        self._rot_edit.setMaximumWidth(64)
        self._rot_edit.setToolTip("旋转角度，回车确认")
        self._rot_edit.returnPressed.connect(self._on_rot_edit)

        self._btn_rot90 = IconButton("rotate-90", tooltip="顺时针旋转 90°")
        self._btn_rot90.clicked.connect(self._view.rotate_90)

        self._btn_reset_rot = IconButton("refresh", tooltip="旋转角度归零")
        self._btn_reset_rot.clicked.connect(self._view.reset_rotation)

        self._btn_flip_h = IconButton("flip-h", tooltip="水平翻转")
        self._btn_flip_h.clicked.connect(self._view.flip_horizontal)

        self._btn_flip_v = IconButton("flip-v", tooltip="垂直翻转")
        self._btn_flip_v.clicked.connect(self._view.flip_vertical)

        separator = QFrame()
        separator.setObjectName("ToolbarSeparator")
        separator.setFrameShape(QFrame.Shape.NoFrame)
        separator.setFixedSize(1, 16)

        layout.addLayout(flow(
            self._zoom_edit, self._btn_100, self._btn_fit, separator,
            self._rot_edit, self._btn_rot90, self._btn_reset_rot,
            self._btn_flip_h, self._btn_flip_v,
            spacing=SPACE.xs,
            margins=(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.sm),
        ))

        # 画布本身没有固定尺寸需求；最小尺寸取「工具栏在最窄处换行后仍放得下」
        # 的自然最小值（minimumSizeHint 约 74x106），再给画布留一点高度余量。
        self.setMinimumSize(120, 110)

    # ------------------------------------------------------------------
    # 公开接口（保持不变）
    # ------------------------------------------------------------------
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
            if self._view._pixmap_item is None:
                self._view.set_image(pixmap)
            else:
                self._view.update_content(pixmap)

    # ------------------------------------------------------------------
    # 工具栏回调
    # ------------------------------------------------------------------
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
        path, _ = get_save_file_name(
            self, "保存图像", directory=self._default_name,
            filters="PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;BMP 图片 (*.bmp)",
            default_suffix="png",
        )
        if path:
            self._pixmap.save(path)

    def _copy_image(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        QApplication.clipboard().setPixmap(self._pixmap)


def run_demo():
    """本地演示：左侧画布 + 底部演示按钮（仅用于手动检查交互）。"""
    import os

    app = QApplication.instance() or QApplication(sys.argv)
    ensure_theme(app)

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

    from .ui.components import SecondaryButton, hbox

    window = QWidget()
    window.setWindowTitle("图像查看器演示")
    window.resize(900, 680)

    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    viewer = ImageViewer(pixmaps[0], rotate_speed=30.0, default_name="示例图")
    outer.addWidget(viewer, 1)

    _idx = [0]
    btn_switch = SecondaryButton("切换图像")
    _saved_vt = [None]
    btn_export = SecondaryButton("导出变换")
    btn_import = SecondaryButton("导入变换")

    def on_switch():
        _idx[0] = 1 - _idx[0]
        btn_switch.setText(f"图像 {_idx[0] + 1}")
        viewer.set_content(pixmaps[_idx[0]])

    def on_export():
        _saved_vt[0] = viewer.export_view_transform()
        btn_export.setText("已导出")

    def on_import():
        if _saved_vt[0] is not None:
            viewer.import_view_transform(_saved_vt[0])

    btn_switch.clicked.connect(on_switch)
    btn_export.clicked.connect(on_export)
    btn_import.clicked.connect(on_import)

    hint = CaptionLabel("滚轮缩放 · 拖动平移 · 侧键旋转")
    outer.addLayout(hbox(
        btn_switch, btn_export, btn_import, None, hint,
        spacing=SPACE.sm, margins=(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.sm)))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
