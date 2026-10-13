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
    from colorPickerPro.filter_scheme import FilterScheme, filter_class_by_name, get_scheme_store
    from colorPickerPro.filter_scheme_panel import FilterSchemePanel
    from colorPickerPro.image_viewer import ImageViewer
else:
    from .filter_lib import ImageFilter, ImageConvert
    from .filter_scheme import FilterScheme, filter_class_by_name, get_scheme_store
    from .filter_scheme_panel import FilterSchemePanel
    from .image_viewer import ImageViewer


class FilterImageViewer(QWidget):
    """滤镜图像查看器。

    内部持有一个「滤镜方案」：选择单个滤镜即创建一个只含该滤镜的方案，
    也可以直接选择已保存的方案；「⚙」打开方案管理面板（可叠加/删除/排序滤镜）。
    """

    def __init__(self, pixmap: QPixmap = None, filter_name: str = "", parent=None):
        super().__init__(parent)
        self._input_pixmap = pixmap
        self._scheme: Optional[FilterScheme] = None
        self._param_panel = None
        self._store = get_scheme_store()

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._reprocess)

        self._build_ui()
        self._init_filters()
        self.refresh_schemes()

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

        combo_style = """
            QComboBox { background: #3a3a3a; color: white; border: 1px solid #555;
                        border-radius: 3px; padding: 4px 8px; font-size: 12px; }
            QComboBox:hover { border: 1px solid #888; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView { background: #3a3a3a; color: white;
                                          selection-background-color: #5C6BC0;
                                          border: 1px solid #555; }
        """

        lbl_filter = QLabel("滤镜:")
        lbl_filter.setStyleSheet("color: #ccc; font-size: 12px;")
        toolbar.addWidget(lbl_filter)

        self._filter_combo = QComboBox()
        self._filter_combo.setStyleSheet(combo_style)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        lbl_scheme = QLabel("方案:")
        lbl_scheme.setStyleSheet("color: #ccc; font-size: 12px;")
        toolbar.addWidget(lbl_scheme)

        self._scheme_combo = QComboBox()
        self._scheme_combo.setStyleSheet(combo_style)
        self._scheme_combo.currentIndexChanged.connect(self._on_scheme_changed)
        toolbar.addWidget(self._scheme_combo)

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setToolTip("刷新已保存方案列表")
        self._btn_refresh.setStyleSheet("""
            QPushButton { padding: 4px 8px; font-size: 11px;
                background-color: #455A64; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #37474F; }
        """)
        self._btn_refresh.setCursor(Qt.PointingHandCursor)
        self._btn_refresh.clicked.connect(self.refresh_schemes)
        toolbar.addWidget(self._btn_refresh)

        toolbar.addStretch()

        self._btn_params = QPushButton("⚙ 方案")
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

    def refresh_schemes(self):
        """重新读取已保存的方案列表。"""
        keep = self._scheme_combo.currentData()
        self._scheme_combo.blockSignals(True)
        self._scheme_combo.clear()
        self._scheme_combo.addItem("(无方案)", None)
        names = self._store.names()
        for name in names:
            self._scheme_combo.addItem(f"  {name}", name)
        if keep in names:
            self._scheme_combo.setCurrentIndex(names.index(keep) + 1)
        self._scheme_combo.blockSignals(False)

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
            if self._scheme is not None:
                self._reprocess()
            else:
                self._viewer.set_content(pixmap)
        else:
            self._viewer.set_content(pixmap)

    def current_scheme(self) -> Optional[FilterScheme]:
        return self._scheme

    def current_filter(self):
        """兼容旧接口：返回方案第一层的滤镜（方案为空时返回 None）。"""
        if self._scheme is not None and self._scheme.layers:
            return self._scheme.layers[0].filter
        return None

    def set_scheme(self, scheme: Optional[FilterScheme]):
        """直接设置当前滤镜方案。"""
        self._apply_scheme(scheme)

    def set_filter_by_name(self, name: str):
        """按滤镜显示名选择滤镜（等价于创建一个只含该滤镜的方案）。"""
        index = -1
        for i in range(self._filter_combo.count()):
            cls = self._filter_combo.itemData(i)
            if cls is not None and cls.name() == name:
                index = i
                break
        if index < 0:
            cls = filter_class_by_name(name)
            if cls is None:
                return
            index = self._filter_combo.findData(cls)
            if index < 0:
                return
        if index == self._filter_combo.currentIndex():
            self._on_filter_changed(index)
        else:
            self._filter_combo.setCurrentIndex(index)

    def _close_params_panel(self, flush: bool = True):
        # 只隐藏、保留面板对象：下次打开复用同一个面板，
        # 这样未保存修改的标记、选中的图层都不会丢。
        if self._param_panel is not None:
            self._param_panel.hide()
            if flush:
                self._flush_pending_process()

    def _flush_pending_process(self):
        """把还在防抖等待中的改动立刻渲染，避免关掉面板就丢掉最后一次修改。"""
        if self._debounce_timer.isActive():
            self._reprocess()

    def _apply_scheme(self, scheme: Optional[FilterScheme],
                      reset_filter_combo: bool = True,
                      reset_scheme_combo: bool = True):
        self._close_params_panel(flush=False)
        self._scheme = scheme

        if reset_filter_combo:
            self._filter_combo.blockSignals(True)
            self._filter_combo.setCurrentIndex(0)
            self._filter_combo.blockSignals(False)
        if reset_scheme_combo:
            self._scheme_combo.blockSignals(True)
            self._scheme_combo.setCurrentIndex(0)
            self._scheme_combo.blockSignals(False)

        has_layers = scheme is not None and bool(scheme.layers)
        self._btn_params.setVisible(has_layers)

        if self._input_pixmap is None or self._input_pixmap.isNull():
            return
        if not has_layers:
            self._viewer.set_content(self._input_pixmap)
            return
        self._request_debounce_process()

    def _on_filter_changed(self, idx):
        cls = self._filter_combo.itemData(idx)
        scheme = FilterScheme.single(cls) if cls is not None else None
        self._apply_scheme(scheme, reset_filter_combo=False)

    def _on_scheme_changed(self, idx):
        name = self._scheme_combo.itemData(idx)
        stored = self._store.get(name) if name else None
        scheme = stored.clone() if stored is not None else None
        self._apply_scheme(scheme, reset_scheme_combo=False)

    def _toggle_params_panel(self):
        if self._param_panel is not None and self._param_panel.isVisible():
            self._close_params_panel()
            return
        if self._scheme is None or not self._scheme.layers:
            return
        if self._param_panel is None:
            self._param_panel = FilterSchemePanel(self._scheme, parent=self)
            self._param_panel.schemeChanged.connect(self._request_debounce_process)
            self._param_panel.schemeReplaced.connect(self._on_scheme_replaced)
            self._param_panel.schemesChanged.connect(self.refresh_schemes)
        else:
            # 复用同一个面板：方案对象没换就不要重绑（否则会清掉未保存标记）
            self._param_panel.sync_scheme(self._scheme)
        btn_global = self._btn_params.mapToGlobal(QPoint(0, self._btn_params.height()))
        self._param_panel.move(btn_global)
        self._param_panel.show()
        self._param_panel.raise_()

    def _on_scheme_replaced(self, scheme):
        """面板换掉了方案对象（加载方案），查看器必须改用新对象渲染。"""
        self._scheme = scheme

        # 下拉框同步：滤镜选择清空，方案选择指向刚加载的方案（如果它在列表里）
        self._filter_combo.blockSignals(True)
        self._filter_combo.setCurrentIndex(0)
        self._filter_combo.blockSignals(False)
        index = self._scheme_combo.findData(scheme.name) if scheme is not None else -1
        self._scheme_combo.blockSignals(True)
        self._scheme_combo.setCurrentIndex(index if index > 0 else 0)
        self._scheme_combo.blockSignals(False)

        has_layers = scheme is not None and bool(scheme.layers)
        self._btn_params.setVisible(has_layers)
        if self._input_pixmap is None or self._input_pixmap.isNull():
            return
        if not has_layers:
            self._viewer.set_content(self._input_pixmap)
            return
        self._request_debounce_process()

    def _request_debounce_process(self):
        self._debounce_timer.start(80)

    def _reprocess(self):
        self._debounce_timer.stop()
        if (self._scheme is None or self._input_pixmap is None
                or self._input_pixmap.isNull()):
            return
        try:
            img_np = ImageConvert.pixmap_to_numpy(self._input_pixmap)
            result = self._scheme.process(img_np)
            result_pm = ImageConvert.numpy_to_pixmap(result)
            self._viewer.set_content(result_pm)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[FilterImageViewer] {ex}")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_schemes()


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
