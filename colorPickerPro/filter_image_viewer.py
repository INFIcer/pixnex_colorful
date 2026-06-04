import sys
import numpy as np
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel,
)
from PySide6.QtGui import QPixmap

if __name__ == "__main__" and __package__ is None:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.filter_lib import ImageFilter, ImageConvert
    from colorPickerPro.screenFilter import _FilterParamsPanel
    from colorPickerPro.image_viewer import ImageViewer
else:
    from .filter_lib import ImageFilter, ImageConvert
    from .screenFilter import _FilterParamsPanel
    from .image_viewer import ImageViewer


class FilterImageViewer(QWidget):
    def __init__(self, pixmap: QPixmap = None, filter_name: str = "", parent=None):
        super().__init__(parent)
        self._input_pixmap = pixmap
        self._filter = None
        self._param_panel = None

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._reprocess)

        self._build_ui()
        self._init_filters()

        if pixmap is not None and not pixmap.isNull():
            self._viewer.set_content(pixmap)

        if filter_name:
            self.set_filter_by_name(filter_name)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._viewer = ImageViewer(rotate_speed=30.0, default_name="")
        layout.addWidget(self._viewer, 1)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 6)
        toolbar.setSpacing(6)

        lbl_filter = QLabel("滤镜:")
        lbl_filter.setStyleSheet("color: #ccc; font-size: 12px;")
        toolbar.addWidget(lbl_filter)

        self._filter_combo = QComboBox()
        self._filter_combo.setStyleSheet("""
            QComboBox { background: #3a3a3a; color: white; border: 1px solid #555;
                        border-radius: 3px; padding: 4px 8px; font-size: 12px; }
            QComboBox:hover { border: 1px solid #888; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView { background: #3a3a3a; color: white;
                                          selection-background-color: #5C6BC0;
                                          border: 1px solid #555; }
        """)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        toolbar.addStretch()

        self._btn_params = QPushButton("⚙ 参数")
        self._btn_params.setStyleSheet("""
            QPushButton { padding: 4px 12px; font-size: 11px;
                background-color: #5C6BC0; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #3F51B5; }
            QPushButton:pressed { background-color: #303F9F; }
        """)
        self._btn_params.setCursor(Qt.PointingHandCursor)
        self._btn_params.clicked.connect(self._toggle_params_panel)
        self._btn_params.setVisible(False)
        toolbar.addWidget(self._btn_params)

        layout.addLayout(toolbar)

    def _init_filters(self):
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        self._filter_combo.addItem("(无滤镜)", None)
        for cls in ImageFilter.all_filters():
            self._filter_combo.addItem(f"  {cls.name()}", cls)
        self._filter_combo.blockSignals(False)

    @property
    def image_viewer(self):
        return self._viewer

    @property
    def transformChanged(self):
        return self._viewer.transformChanged

    @property
    def input_pixmap(self):
        return self._input_pixmap

    def set_image(self, pixmap: QPixmap):
        self._input_pixmap = pixmap
        if pixmap is not None and not pixmap.isNull():
            if self._filter is not None:
                self._reprocess()
            else:
                self._viewer.set_content(pixmap)
        else:
            self._viewer.set_content(pixmap)

    def current_filter(self) -> Optional[ImageFilter]:
        return self._filter

    def set_filter_by_name(self, name: str):
        for i in range(self._filter_combo.count()):
            cls = self._filter_combo.itemData(i)
            if cls is not None and cls.name() == name:
                self._filter_combo.setCurrentIndex(i)
                return

    def _close_params_panel(self):
        if self._param_panel:
            self._param_panel.close()
            self._param_panel = None
            self._debounce_timer.stop()

    def _on_filter_changed(self, idx):
        self._close_params_panel()
        cls = self._filter_combo.itemData(idx)
        if cls is None:
            self._filter = None
            self._btn_params.setVisible(False)
            if self._input_pixmap is not None and not self._input_pixmap.isNull():
                self._viewer.set_content(self._input_pixmap)
            return

        self._filter = cls()
        has_params = len(self._filter.exposed_parameters()) > 0
        self._btn_params.setVisible(has_params)

        if self._input_pixmap is not None and not self._input_pixmap.isNull():
            self._reprocess()

    def _toggle_params_panel(self):
        if self._param_panel and self._param_panel.isVisible():
            self._close_params_panel()
            return
        if self._filter is None:
            return
        params = self._filter.exposed_parameters()
        if not params:
            return
        self._param_panel = _FilterParamsPanel(params, self._request_debounce_process, self)
        btn_global = self._btn_params.mapToGlobal(QPoint(0, self._btn_params.height()))
        self._param_panel.move(btn_global)
        self._param_panel.show()

    def _request_debounce_process(self):
        self._debounce_timer.start(80)

    def _reprocess(self):
        self._debounce_timer.stop()
        if (self._filter is None or self._input_pixmap is None
                or self._input_pixmap.isNull()):
            return
        try:
            img_np = ImageConvert.pixmap_to_numpy(self._input_pixmap)
            result = self._filter.process(img_np)
            result_pm = ImageConvert.numpy_to_pixmap(result)
            self._viewer.set_content(result_pm)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[FilterImageViewer] {ex}")


def run_demo():
    import os

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(script_dir, os.pardir, "示例图.png"),
        os.path.join(script_dir, os.pardir, "示例图2.png"),
    ]
    pixmaps = []
    for p in paths:
        if os.path.exists(p):
            pixmaps.append(QPixmap(p))

    if not pixmaps:
        print("警告：未找到示例图片，使用空画布")
        pixmaps.append(QPixmap())

    window = QWidget()
    window.setWindowTitle("滤镜图像查看器演示")
    window.resize(900, 680)

    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    viewer = FilterImageViewer(pixmaps[0])
    outer.addWidget(viewer, 1)

    demo_bar = QHBoxLayout()
    demo_bar.setContentsMargins(8, 4, 8, 6)

    if len(pixmaps) >= 2:
        _idx = [0]

        def on_switch():
            _idx[0] = 1 - _idx[0]
            viewer.set_image(pixmaps[_idx[0]])

        btn_switch = QPushButton("切换图像")
        btn_switch.setStyleSheet("""
            QPushButton { padding: 4px 14px; font-size: 11px;
                background-color: #FF8F00; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #FF6F00; }
            QPushButton:pressed { background-color: #E65100; }
        """)
        btn_switch.setCursor(Qt.PointingHandCursor)
        btn_switch.clicked.connect(on_switch)
        demo_bar.addWidget(btn_switch)

    demo_bar.addStretch()
    lbl_hint = QLabel("左键拖拽平移 | 滚轮缩放 | 侧键旋转")
    lbl_hint.setStyleSheet("color: #999; font-size: 11px;")
    demo_bar.addWidget(lbl_hint)

    outer.addLayout(demo_bar)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
