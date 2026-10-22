"""滤镜图像查看器。

内部持有一个「滤镜方案」：选择单个滤镜即创建一个只含该滤镜的方案，也可以
直接选择已保存的方案；「方案参数」按钮打开方案管理面板（可叠加 / 删除 / 排序
滤镜并调整参数）。

表现层说明：
    * 顶部选择条是自适应布局：宽度足够时排成一行，窗口变窄时自动折成两行，
      不会把下拉框挤出窗口；
    * 方案管理面板是独立的无边框对话框，弹出位置始终被限制在当前屏幕的可用
      区域内（多显示器 / 小屏幕也不会跑到屏幕外）；
    * 本文件不写内联样式，颜色、字号、间距全部来自设计令牌。
"""

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QSize, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGridLayout, QSizePolicy, QVBoxLayout, QWidget,
)

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.filter_lib import ImageFilter, ImageConvert
    from colorPickerPro.filter_scheme import (
        FilterScheme, filter_class_by_name, get_scheme_store,
    )
    from colorPickerPro.filter_scheme_panel import FilterSchemePanel
    from colorPickerPro.image_viewer import ImageViewer
    from colorPickerPro.ui.components import (
        CaptionLabel, IconButton, SecondaryButton, hbox,
    )
    from colorPickerPro.ui.theme import ensure_theme
    from colorPickerPro.ui.tokens import SPACE
else:
    from .filter_lib import ImageFilter, ImageConvert
    from .filter_scheme import FilterScheme, filter_class_by_name, get_scheme_store
    from .filter_scheme_panel import FilterSchemePanel
    from .image_viewer import ImageViewer
    from .ui.components import (
        CaptionLabel, IconButton, SecondaryButton, hbox,
    )
    from .ui.theme import ensure_theme
    from .ui.tokens import SPACE


# 下拉框至少保留的宽度：再窄就放不下滤镜名，会让布局挤在一起。
_COMBO_MIN_WIDTH = 120


class _SchemeBar(QWidget):
    """滤镜 / 方案选择条（自适应：单行 / 双行）。

    用 :class:`QGridLayout` 承载同一批控件：宽度够时全部排在第 0 行，宽度不足
    时把「方案」这一组挪到第 1 行。切换只是重新挂载控件，不改任何尺寸策略，
    因此下拉框在两种排布下都能随窗口横向伸展。
    """

    def __init__(self, filter_label: QWidget, filter_combo: QWidget,
                 refresh_button: QWidget, scheme_label: QWidget,
                 scheme_combo: QWidget, params_button: QWidget,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(SPACE.sm)
        self._grid.setVerticalSpacing(SPACE.xs)
        self._parts = (filter_label, filter_combo, refresh_button,
                       scheme_label, scheme_combo, params_button)
        self._compact = None
        self._reflowing = False
        # 先按「两行」建立：此时还不知道真实宽度，按两行报告最小尺寸才不会
        # 把宿主窗口的最小宽度撑大（真正宽起来后 resizeEvent 会切回一行）。
        self._set_compact(True, force=True)

    # ------------------------------------------------------------------
    @property
    def compact(self) -> bool:
        return bool(self._compact)

    def _wide_min_width(self) -> int:
        widths = [self._part_min_width(w)
                  for w in self._parts if not w.isHidden()]
        spacing = self._grid.horizontalSpacing() * max(0, len(widths) - 1)
        return sum(widths) + spacing + SPACE.xs

    @staticmethod
    def _part_min_width(widget: QWidget) -> int:
        """控件的最小宽度：minimumWidth()（如下拉框的 120）也要算进来。"""
        return max(widget.minimumWidth(), widget.minimumSizeHint().width())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """按「两行排布」报告最小尺寸。

        如果按单行排布报告，这个最小宽度会顺着布局传给窗口，把窗口的最小宽度
        撑到放不下第二行的程度，窗口就再也缩不窄（自适应会失效）。折行后的
        最小宽度才是这个控件真正能否放下的依据。
        """
        spacing = self._grid.horizontalSpacing()
        margins = self._grid.contentsMargins()
        width = 0
        height = 0
        for row in (self._parts[:3], self._parts[3:]):
            visible = [w for w in row if not w.isHidden()]
            if not visible:
                continue
            width = max(
                width,
                sum(self._part_min_width(w) for w in visible)
                + spacing * (len(visible) - 1))
            height += max(w.minimumSizeHint().height() for w in visible)
        if height:
            height += self._grid.verticalSpacing()
        return QSize(width + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def _set_compact(self, compact: bool, force: bool = False) -> None:
        if compact == self._compact and not force:
            return
        if self._reflowing:
            return
        self._reflowing = True
        try:
            self._compact = compact
            for widget in self._parts:
                self._grid.removeWidget(widget)
            for column in range(6):
                self._grid.setColumnStretch(column, 0)

            filter_label, filter_combo, refresh, scheme_label, scheme_combo, params = \
                self._parts
            if compact:
                self._grid.addWidget(filter_label, 0, 0)
                self._grid.addWidget(filter_combo, 0, 1)
                self._grid.addWidget(refresh, 0, 2)
                self._grid.addWidget(scheme_label, 1, 0)
                self._grid.addWidget(scheme_combo, 1, 1)
                self._grid.addWidget(params, 1, 2)
                self._grid.setColumnStretch(1, 1)
            else:
                self._grid.addWidget(filter_label, 0, 0)
                self._grid.addWidget(filter_combo, 0, 1)
                self._grid.addWidget(refresh, 0, 2)
                self._grid.addWidget(scheme_label, 0, 3)
                self._grid.addWidget(scheme_combo, 0, 4)
                self._grid.addWidget(params, 0, 5)
                self._grid.setColumnStretch(1, 1)
                self._grid.setColumnStretch(4, 1)
            self.updateGeometry()
            # 立刻重排：隐藏窗口里没有下一轮事件循环，晚一步就会拿到旧几何。
            self._grid.activate()
        finally:
            self._reflowing = False

    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._reflowing:
            return
        self._set_compact(self.width() < self._wide_min_width())


class FilterImageViewer(QWidget):
    """滤镜图像查看器（方案选择 + 参数面板 + 图像画布）。"""

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

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.xs)

        self._viewer = ImageViewer(rotate_speed=30.0, default_name="")
        layout.addWidget(self._viewer, 1)

        self._filter_combo = QComboBox()
        self._filter_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        self._filter_combo.setMinimumWidth(_COMBO_MIN_WIDTH)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self._scheme_combo = QComboBox()
        self._scheme_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        self._scheme_combo.setMinimumWidth(_COMBO_MIN_WIDTH)
        self._scheme_combo.currentIndexChanged.connect(self._on_scheme_changed)

        self._btn_refresh = IconButton("refresh", tooltip="刷新方案")
        self._btn_refresh.clicked.connect(self.refresh_schemes)

        self._btn_params = IconButton("settings", tooltip="方案参数")
        self._btn_params.clicked.connect(self._toggle_params_panel)
        self._btn_params.setVisible(False)

        self._bar = _SchemeBar(
            CaptionLabel("滤镜"), self._filter_combo, self._btn_refresh,
            CaptionLabel("方案"), self._scheme_combo, self._btn_params,
        )
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        layout.addLayout(hbox(self._bar, spacing=SPACE.sm,
                              margins=(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.sm),
                              stretch=0))

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

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 方案参数面板
    # ------------------------------------------------------------------
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

    def _place_params_panel(self) -> None:
        """把方案面板摆到按钮下方，并保证完整落在当前屏幕可用区域内。"""
        panel = self._param_panel
        if panel is None:
            return
        anchor_point = self._btn_params.mapToGlobal(
            self._btn_params.rect().center())
        screen = QGuiApplication.screenAt(anchor_point)
        if screen is None:
            window = self.window()
            screen = window.screen() if window is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        margin = SPACE.sm
        max_width = max(SPACE.xl * 8, available.width() - margin * 2)
        max_height = max(SPACE.xl * 8, available.height() - margin * 2)
        panel.resize(min(panel.width(), max_width),
                     min(panel.height(), max_height))

        below = self._btn_params.mapToGlobal(
            QPoint(0, self._btn_params.height()))
        x = below.x()
        y = below.y()
        if x + panel.width() > available.right() - margin:
            x = available.right() - margin - panel.width()
        if y + panel.height() > available.bottom() - margin:
            # 下方放不下就翻到按钮上方，仍然放不下时再夹回屏幕内。
            above = self._btn_params.mapToGlobal(QPoint(0, 0)).y()
            y = above - panel.height() - SPACE.xs
        x = max(available.left() + margin, x)
        y = max(available.top() + margin, y)
        panel.move(x, y)

    def _toggle_params_panel(self):
        if self._param_panel is not None and self._param_panel.isVisible():
            self._close_params_panel()
            return
        if self._scheme is None or not self._scheme.layers:
            return
        if self._param_panel is None:
            # 以宿主顶层窗口为父：若以子控件为父，Qt.Tool 在部分宿主里
            # 会变成非激活窗口，导致边缘缩放第一次点击被“激活”吃掉。
            self._param_panel = FilterSchemePanel(
                self._scheme, parent=self.window())
            self._param_panel.schemeChanged.connect(self._request_debounce_process)
            self._param_panel.schemeReplaced.connect(self._on_scheme_replaced)
            self._param_panel.schemesChanged.connect(self.refresh_schemes)
        else:
            # 复用同一个面板：方案对象没换就不要重绑（否则会清掉未保存标记）
            self._param_panel.sync_scheme(self._scheme)
        self._place_params_panel()
        self._param_panel.show()
        self._param_panel.raise_()
        self._param_panel.activateWindow()

    # ------------------------------------------------------------------
    # 方案切换
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
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
    ensure_theme(app)

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

    if len(pixmaps) >= 2:
        _idx = [0]

        def on_switch():
            _idx[0] = 1 - _idx[0]
            viewer.set_image(pixmaps[_idx[0]])

        btn_switch = SecondaryButton("切换图像")
        btn_switch.clicked.connect(on_switch)
        hint = CaptionLabel("滚轮缩放 · 拖动平移 · 侧键旋转")
        outer.addLayout(hbox(btn_switch, None, hint, spacing=SPACE.sm,
                             margins=(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.sm)))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
