"""pixnex 主窗口。

界面全部由 ``colorPickerPro.ui`` 的设计系统组合而成：

- 顶部是应用标题；
- 中间是纵向滚动的卡片列表（色彩模型 / 图形化选色 / 滑块 / 当前颜色 /
  颜色同步 / 滤镜入口），窗口变矮时自动出现滚动条；
- 每个卡片内部只有一种职责，复杂控件（取色盘、滑块组、信息面板）各自
  封装在 ``color_picker_widgets`` 里。

这里只保留“窗口级”的职责：模型切换、颜色同步与焦点归还状态机。
"""

import os
import sys

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QLineEdit,
    QMainWindow, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget,
)

from .auto_collapse import (
    AUTO_COLLAPSE_POLL_MS, modal_or_popup_open, mouse_button_pressed,
)
from .color_picker_widgets import (
    ALL_MODELS,
    BaseColorModel,
    ColorInfoPanel,
    DynamicSlidersWidget,
    GraphicalPicker,
    OKLCHModel,
)
from .filter_scheme_selector import FilterSchemeSelectorDialog
from .image_drop_widget import ImageDropWidget
from .image_filter_compare import ImageFilterCompareWindow
from .screenFilter import ScreenFilterWindow
from .screenPicker import ScreenPicker
from .sync.controller import (
    STATUS_CONNECTING, STATUS_DISCONNECTED, STATUS_IDLE, STATUS_NOT_RUNNING,
    STATUS_SYNCED, STATUS_WRITE_FAILED, SyncController,
)
from .ui import apply_theme, configure_application
from .ui.app_icon import app_icon
from .ui.components import (
    Card, CaptionLabel, FieldLabel, FramelessWindowMixin, IconButton,
    PrimaryButton, ScrollArea, StatusLabel, hbox,
)
from .ui.theme import set_variant
from .ui.tokens import SIZE, SPACE, State, Variant
from .window_state import (
    WindowState, WindowStateStore, clamp_geometry, screen_available_rects,
)

# 正在输入数值/文本的控件：此时归还焦点会打断输入，需要等编辑结束。
_TEXT_EDIT_WIDGETS = (
    QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit,
)

# 折叠后只保留标题栏，外加 1px 上边框与 1px 下边框。
_COLLAPSED_EXTRA = 2

# Qt 中“不限制最大尺寸”的约定值。
_QT_SIZE_UNLIMITED = 16777215


# 状态标签文案 → 语义颜色。「未启动」是提示而不是错误，用 warning 色；
# 「写入失败」说明连接在但推不过去，按错误处理。
_SYNC_STATUS_STATES = {
    STATUS_SYNCED: State.SUCCESS,
    STATUS_IDLE: State.NEUTRAL,
    STATUS_NOT_RUNNING: State.WARNING,
    STATUS_DISCONNECTED: State.DANGER,
    STATUS_WRITE_FAILED: State.DANGER,
}


class MainWindow(FramelessWindowMixin, QMainWindow):
    def __init__(self, state_store: WindowStateStore | None = None):
        super().__init__()
        self.setWindowTitle("pixnex")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(320, 460)
        self.resize(380, 640)

        # 界面状态（自动折叠 / 置顶 / 位置尺寸）。不传存储时只在内存里记，
        # 测试和预览不会写用户的真实配置；正式启动由 main() 注入持久化存储。
        self._state_store = (
            state_store if state_store is not None else WindowStateStore())
        saved_state = self._state_store.load()
        self._always_on_top = saved_state.always_on_top
        self._auto_collapse_enabled = saved_state.auto_collapse
        self._saved_geometry = saved_state.geometry
        # 折叠相关：折叠标记、展开后的尺寸与最小高度（折叠只改高度，宽度保留）。
        self._collapsed = False
        self._expanded_size: QSize | None = None
        self._expanded_min_height = self.minimumHeight()

        # 自动折叠轮询：只在开关打开且窗口可见时运行。
        self._auto_collapse_timer = QTimer(self)
        self._auto_collapse_timer.setInterval(AUTO_COLLAPSE_POLL_MS)
        self._auto_collapse_timer.timeout.connect(self._on_auto_collapse_tick)

        self._model: BaseColorModel = OKLCHModel()
        self._model.set_from_srgb(1.0, 0.0, 0.0)
        self._applying_ext = False

        self._sync = SyncController()
        self._sync.colorChanged.connect(self._on_sync_external)
        self._sync.statusChanged.connect(self._on_sync_status)
        self._sync.messageChanged.connect(self._on_sync_message)
        self._sync_mode = "off"
        self._sync_enabled = False

        # 选色后归还焦点：勾选框状态 + 交互状态机
        self._focus_return_enabled = True
        self._focus_pending = False     # 本次选色还没归还焦点
        self._mouse_down = False        # 鼠标按下中（拖拽选色未结束）
        self._edit_dirty = False        # 正在键入数值
        self._last_pushed_rgb = None    # 上次同步出去的 RGB

        self._screen_picker = ScreenPicker()
        self._filter_windows = []
        self._compare_windows = []

        self._build_ui()
        self._restore_window_geometry()
        # 主窗口必须监听自己的模型：否则首次切换模型之前，取色变化既不会
        # 推送到同步软件，也不会触发焦点归还。
        self._model.add_listener(self._on_model_sync)
        self._sync.start()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("FramelessBody")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.init_frameless(
            "pixnex", layout=outer, icon=app_icon(),
            show_minimize=True, show_maximize=False, show_close=True,
            resizable=True, double_click=None)

        # 标题栏按钮：自动折叠 / 置顶（都在最小化左边）。
        self._auto_collapse_btn = IconButton(
            "collapse", tooltip="鼠标离开后折叠为标题栏", checkable=True)
        self._auto_collapse_btn.setChecked(self._auto_collapse_enabled)
        self._auto_collapse_btn.toggled.connect(self._on_auto_collapse_toggled)
        self.title_bar.add_button(self._auto_collapse_btn)

        self._pin_btn = IconButton("pin", tooltip="置顶", checkable=True)
        self._pin_btn.setChecked(self._always_on_top)
        self._pin_btn.toggled.connect(self._set_always_on_top)
        self.title_bar.add_button(self._pin_btn)

        self._body = QWidget()
        self._body.setObjectName("FramelessBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(
            SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        self._body_layout.setSpacing(SPACE.md)
        outer.addWidget(self._body, 1)

        self._scroll = ScrollArea()
        self._content = QWidget()
        self._content.setObjectName("AppRoot")
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(SPACE.md)
        self._scroll.setWidget(self._content)
        self._body_layout.addWidget(self._scroll, 1)

        content.addWidget(self._build_model_card())
        content.addWidget(self._build_picker_card())
        content.addWidget(self._build_sliders_card())
        content.addWidget(self._build_color_card())
        content.addWidget(self._build_sync_card())
        content.addWidget(self._build_tools_card())
        content.addStretch(1)

    def _build_model_card(self) -> Card:
        card = Card("色彩模型")
        row = hbox(FieldLabel("模型"))
        self._combo = QComboBox()
        self._combo.addItems(list(ALL_MODELS.keys()))
        self._combo.currentTextChanged.connect(self._on_model_switch)
        row.addWidget(self._combo, 1)
        card.add_layout(row)
        return card

    def _build_picker_card(self) -> Card:
        card = Card("图形选色器")
        self._graph = GraphicalPicker(self._model, size=220)
        card.add(self._graph)
        return card

    def _build_sliders_card(self) -> Card:
        card = Card("滑块")
        self._slider_widget = DynamicSlidersWidget(self._model)
        card.add(self._slider_widget)
        return card

    def _build_color_card(self) -> Card:
        card = Card("当前颜色")
        self._info_panel = ColorInfoPanel(self._model)
        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)
        self._screen_picker.colorPicked.connect(self._on_picked)
        self._screen_picker.cancelled.connect(self._on_pick_cancelled)
        card.add(self._info_panel)
        return card

    def _build_sync_card(self) -> Card:
        card = Card("颜色同步")
        self._sync_status = StatusLabel(STATUS_IDLE, State.NEUTRAL)
        # 同步状态可能是一句较长的错误信息：限制宽度避免把标题行撑开，
        # 完整内容放在 tooltip 里（StatusLabel.set_message 会自动设置）。
        self._sync_status.setMaximumWidth(220)
        card.add_header_widget(self._sync_status)

        row = hbox(FieldLabel("目标软件"))
        self._sync_combo = QComboBox()
        self._sync_combo.addItem("关闭", "off")
        self._sync_combo.addItem("UDM Paint", "udm")
        self._sync_combo.addItem("Photoshop", "ps")
        self._sync_combo.currentIndexChanged.connect(self._on_sync_mode_change)
        row.addWidget(self._sync_combo, 1)

        self._sync_btn = PrimaryButton("开启同步")
        self._sync_btn.setEnabled(False)
        self._sync_btn.clicked.connect(self._on_sync_toggle)
        row.addWidget(self._sync_btn)
        card.add_layout(row)

        self._focus_chk = QCheckBox("选色后归还焦点")
        self._focus_chk.setToolTip("选色结束后将焦点交还同步软件")
        self._focus_chk.setChecked(True)
        self._focus_chk.setEnabled(False)
        self._focus_chk.toggled.connect(self._on_focus_return_toggled)
        card.add_layout(hbox(self._focus_chk, None))
        return card

    def _build_tools_card(self) -> Card:
        card = Card("滤镜")
        self._image_drop = ImageDropWidget(
            placeholder_text="拖入或粘贴图像",
            drop_hint="释放以对比滤镜",
        )
        self._image_drop.setMinimumHeight(56)
        self._image_drop.imageReceived.connect(self._on_drop_image)
        card.add(self._image_drop)

        self._screen_filter_btn = PrimaryButton("打开屏幕滤镜")
        self._screen_filter_btn.setToolTip("创建置顶的实时滤镜窗口")
        self._screen_filter_btn.clicked.connect(self._on_pick_screen_filter)
        card.add_layout(hbox(self._screen_filter_btn, None))
        return card

    # ------------------------------------------------------------------
    # 窗口状态：位置尺寸 / 自动折叠
    # ------------------------------------------------------------------
    def _restore_window_geometry(self) -> None:
        """恢复上次关闭时的位置与尺寸；屏幕变化后越界的部分自动夹回。"""
        if self._saved_geometry is None:
            return
        x, y, width, height = self._saved_geometry
        target = clamp_geometry(
            QRect(x, y, width, height), screen_available_rects(),
            QSize(self.minimumWidth(), self.minimumHeight()))
        self.setGeometry(target)

    def _persist_geometry(self) -> QRect:
        """要保存的窗口矩形：折叠时用展开后的尺寸，避免重启后只剩标题栏。"""
        if self._collapsed and self._expanded_size is not None:
            return QRect(self.x(), self.y(),
                         self._expanded_size.width(),
                         self._expanded_size.height())
        return self.geometry()

    def _save_window_state(self) -> None:
        """保存自动折叠 / 置顶 / 位置尺寸；切换开关与退出时调用。"""
        rect = self._persist_geometry()
        self._state_store.save(WindowState(
            auto_collapse=self._auto_collapse_enabled,
            always_on_top=self._always_on_top,
            geometry=(rect.x(), rect.y(), rect.width(), rect.height()),
        ))

    def is_collapsed(self) -> bool:
        """窗口当前是否折叠为一条标题栏。"""
        return self._collapsed

    def toggle_collapse(self) -> None:
        """折叠 / 展开窗口（保留标题栏）。"""
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def _collapsed_height(self) -> int:
        return SIZE.title_bar_height + _COLLAPSED_EXTRA

    def _collapse(self) -> None:
        """折叠为标题栏：只改高度，宽度与当前位置保留。"""
        if self._collapsed or self.isMinimized() or self.isMaximized():
            return
        self._expanded_size = QSize(self.width(), self.height())
        self._expanded_min_height = self.minimumHeight()
        self._collapsed = True
        self._body.hide()
        self._apply_collapsed_height()
        self._place_size_grip()
        self.update()

    def _expand(self) -> None:
        """展开回折叠前的尺寸；窗口被拖到屏幕边缘时先夹回屏幕内。"""
        if not self._collapsed:
            return
        self._collapsed = False
        self._body.show()
        self.setMaximumHeight(_QT_SIZE_UNLIMITED)
        self.setMinimumHeight(self._expanded_min_height)
        size = self._expanded_size or QSize(self.width(), self.height())
        target = clamp_geometry(
            QRect(self.x(), self.y(), size.width(), size.height()),
            screen_available_rects(),
            QSize(self.minimumWidth(), self.minimumHeight()))
        self.setGeometry(target)
        self._place_size_grip()
        self.update()

    def _apply_collapsed_height(self) -> None:
        # 先设 max 再设 min：Qt 在 min > max 时会反向改掉另一项。
        height = self._collapsed_height()
        self.setMaximumHeight(height)
        self.setMinimumHeight(height)
        if self.height() != height:
            self.resize(self.width(), height)

    # ---- 自动折叠 -----------------------------------------------------
    def _on_auto_collapse_toggled(self, enabled: bool) -> None:
        self._auto_collapse_enabled = bool(enabled)
        self._update_auto_collapse_timer()
        if not self._auto_collapse_enabled and self._collapsed:
            self._expand()   # 关掉开关立即展开，不能把窗口留在折叠状态
        self._save_window_state()

    def _update_auto_collapse_timer(self) -> None:
        running = self._auto_collapse_enabled and self.isVisible()
        if running and not self._auto_collapse_timer.isActive():
            self._auto_collapse_timer.start()
        elif not running and self._auto_collapse_timer.isActive():
            self._auto_collapse_timer.stop()

    def _on_auto_collapse_tick(self) -> None:
        self._auto_collapse_step(QCursor.pos())

    def _auto_collapse_step(self, cursor_pos: QPoint) -> None:
        """按光标位置折叠 / 展开。参数显式传入，测试不需要移动真实鼠标。"""
        if not self._auto_collapse_enabled or not self.isVisible():
            return
        if self.isMinimized() or self.isMaximized():
            return                      # 最小化 / 最大化时先不折叠，避免破坏窗口状态
        if mouse_button_pressed():
            return                      # 正在拖拽（取色 / 移动 / 缩放）
        if modal_or_popup_open():
            return                      # 模态对话框 / 弹出层打开时鼠标本来就在窗口外
        inside = self.geometry().contains(cursor_pos)
        if self._collapsed:
            if inside:
                self._expand()
        elif not inside:
            self._collapse()

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        # 折叠期间布局或外部 resize 可能试图撑高窗口，这里持续锁死标题栏高度。
        if self._collapsed and self.height() != self._collapsed_height():
            self._apply_collapsed_height()

    # ------------------------------------------------------------------
    # 模型切换
    # ------------------------------------------------------------------
    def _on_model_switch(self, name):
        old_rgb = self._model.to_srgb_tuple()
        self._model.remove_listener(self._on_model_sync)
        self._model = ALL_MODELS[name]()
        self._model.set_from_srgb(old_rgb[0], old_rgb[1], old_rgb[2])

        self._graph.set_model(self._model)
        self._slider_widget.set_model(self._model)
        self._info_panel.set_model(self._model)
        self._model.add_listener(self._on_model_sync)

        self._graph_hint.setText("拖动取色")

    def _set_always_on_top(self, enabled: bool) -> None:
        """切换主窗口置顶（标题栏图钉按钮）。

        Windows 下使用 SetWindowPos 修改原生置顶状态：setWindowFlag() 会
        销毁并重建平台窗口，导致可见窗口闪烁/像重新打开一次。
        """
        self._always_on_top = bool(enabled)
        self._apply_topmost(self._always_on_top)
        if self._always_on_top:
            self.raise_()
        self._save_window_state()

    def _apply_topmost(self, enabled: bool) -> None:
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = (
                    wintypes.HWND, wintypes.HWND, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint)
                user32.SetWindowPos(
                    hwnd, -1 if enabled else -2, 0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010)  # NOSIZE | NOMOVE | NOACTIVATE
            except Exception:
                pass
            return
        # 非 Windows：改 flag 会隐藏窗口，必须在改完后重新显示（否则置顶按钮
        # 会把窗口藏起来，恢复 always_on_top=true 时启动也是不可见窗口）。
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()
            self.raise_()

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        if self._always_on_top:
            self._apply_topmost(True)
        # 自动折叠要等窗口真正可见后才轮询（构造阶段只恢复开关状态）。
        self._update_auto_collapse_timer()

    def hideEvent(self, event):  # noqa: N802 (Qt API)
        self._auto_collapse_timer.stop()
        super().hideEvent(event)

    def _on_constrain(self):
        self._model.constrain_to_gamut()

    def _on_picked(self, r, g, b):
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)
        # 屏幕取色的那次点击发生在取色器覆盖层里，覆盖层随即隐藏，松键事件
        # 不会再回到本进程，所以这里直接结束"鼠标按下"状态并归还焦点。
        self._mouse_down = False
        self._try_return_focus()

    def _on_filter_color_picked(self, r, g, b):
        """屏幕滤镜窗口图像区域左键取色：同步为当前颜色。

        点击发生在滤镜窗口里，松键事件会正常派发到应用事件过滤器，因此不需要
        手动复位 ``_mouse_down``；颜色变化经模型监听器触发颜色同步与焦点归还。
        """
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)

    def _format_picked_color(self, r, g, b) -> str:
        """取色提示文案：当前颜色模型的样式，如 ``L-0.61 C-0.25 H-321.7``。"""
        return self._model.format_srgb(r / 255.0, g / 255.0, b / 255.0)

    def _on_pick_cancelled(self):
        # 取色器覆盖层同样在 mousePressEvent 里隐藏自己，右键 / Esc 取消时
        # 松键事件不会回到本进程；这里清掉"鼠标按下"状态，避免状态机卡住。
        self._mouse_down = False

    # ------------------------------------------------------------------
    # 屏幕滤镜 / 图像对比入口
    # ------------------------------------------------------------------
    def _on_pick_screen_filter(self):
        """选择滤镜或已保存方案，然后创建只承载该方案的屏幕滤镜窗口。"""
        dlg = FilterSchemeSelectorDialog(self, "选择屏幕滤镜 / 滤镜方案")
        if dlg.exec() != QDialog.Accepted:
            return
        scheme = dlg.current_scheme()
        if scheme is None:
            return
        self._create_screen_filter(scheme)

    def _create_screen_filter(self, scheme):
        win = ScreenFilterWindow(scheme)
        # 屏幕滤镜窗口的「图像区域左键取色」直接同步到当前颜色；
        # 提示文案按主窗口「当前颜色模型」格式化（切换模型后立即生效）。
        win.set_color_formatter(self._format_picked_color)
        win.colorPicked.connect(self._on_filter_color_picked)
        offset = 30 * (len(self._filter_windows) % 8)
        win.move(100 + offset, 100 + offset)
        win.start()
        self._filter_windows.append(win)
        win.destroyed.connect(lambda w=win: self._on_filter_closed(w))

    def _on_filter_closed(self, win):
        if win in self._filter_windows:
            self._filter_windows.remove(win)

    def _on_drop_image(self, pixmap, filename):
        dlg = FilterSchemeSelectorDialog(self, "选择对比滤镜 / 方案", multi_select=True)
        if dlg.exec() != QDialog.Accepted:
            return
        schemes = dlg.selected_schemes()
        if not schemes:
            return
        win = ImageFilterCompareWindow(pixmap, schemes)
        win.show()
        self._compare_windows.append(win)
        win.destroyed.connect(
            lambda w=win: self._compare_windows.remove(w) if w in self._compare_windows else None)

    def closeEvent(self, e):
        self._auto_collapse_timer.stop()
        # 退出前保存界面状态：下次启动恢复自动折叠 / 置顶 / 位置尺寸。
        self._save_window_state()
        for win in self._filter_windows[:]:
            win.stop()
            win.close()
        self._filter_windows.clear()
        for win in self._compare_windows[:]:
            win.close()
        self._compare_windows.clear()
        self._sync.stop_thread()
        super().closeEvent(e)

    # ------------------------------------------------------------------
    # 颜色同步
    # ------------------------------------------------------------------
    def _on_sync_mode_change(self, index):
        self._sync_mode = self._sync_combo.itemData(index)
        active = self._sync_mode != "off"
        self._sync.set_mode(self._sync_mode)
        self._sync_btn.setEnabled(active)
        self._focus_chk.setEnabled(active)
        if not active:
            self._sync_enabled = False
            self._sync_pending_off()
            self._sync.set_enabled(False)
            self._update_sync_button()
            self._sync_status.set_message(STATUS_IDLE, State.NEUTRAL)

    def _on_sync_toggle(self):
        self._sync_enabled = not self._sync_enabled
        self._sync.set_enabled(self._sync_enabled)
        self._update_sync_button()
        if self._sync_enabled:
            self._last_pushed_rgb = None   # 开启后第一次选色一定归还
            self._push_sync_color()
            # 只是短暂过渡：第一次轮询就会给出「已同步 / 未启动 / 未连接」。
            self._sync_status.set_message(STATUS_CONNECTING, State.ACCENT)
        else:
            self._sync_pending_off()
            self._sync_status.set_message(STATUS_IDLE, State.NEUTRAL)

    def _update_sync_button(self):
        self._sync_btn.setText("关闭同步" if self._sync_enabled else "开启同步")
        set_variant(self._sync_btn,
                    Variant.DEFAULT if self._sync_enabled else Variant.PRIMARY)

    def _sync_pending_off(self):
        self._focus_pending = False
        self._last_pushed_rgb = None

    def _push_sync_color(self):
        if not (self._sync_enabled and self._sync_mode != "off"):
            return
        r, g, b = self._model.to_srgb_tuple()
        self._sync.write_color(
            round(r * 255), round(g * 255), round(b * 255))

    def _on_model_sync(self, model, source):
        if self._applying_ext:
            return
        self._push_sync_color()
        self._maybe_return_focus()

    def _on_sync_external(self, r, g, b):
        self._applying_ext = True
        try:
            self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)
        finally:
            self._applying_ext = False
        # 记下同步软件那边的颜色，这样用户之后在 pixnex 里再选回同一个
        # 颜色时，仍然算"颜色变了"，照样归还焦点。
        self._last_pushed_rgb = (r, g, b)

    # ------------------------------------------------------------------
    # 焦点归还
    # ------------------------------------------------------------------
    # 规则：只有"因用户交互而改变颜色"才归还焦点（同步软件改色不算），且
    # 拖拽尚未结束或正在键入数值时不打断；这两件事一结束立即归还。
    def _focus_return_active(self):
        return (self._focus_return_enabled and self._sync_enabled
                and self._sync_mode != "off")

    def _on_focus_return_toggled(self, checked):
        self._focus_return_enabled = bool(checked)
        if not checked:
            self._focus_pending = False

    def _maybe_return_focus(self):
        if not self._focus_return_active():
            return
        r, g, b = self._model.to_srgb_tuple()
        rgb = (round(r * 255), round(g * 255), round(b * 255))
        if rgb == self._last_pushed_rgb:
            return  # 颜色没变（例如切换色彩模型），不算一次选色
        self._last_pushed_rgb = rgb
        self._focus_pending = True
        self._try_return_focus()

    def _try_return_focus(self):
        if not self._focus_pending:
            return
        if not self._focus_return_active():
            self._focus_pending = False
            return
        if self._mouse_down:
            return  # 还在拖拽，松手时再归还
        if self._edit_dirty and self._is_text_editing():
            return  # 还在键入数值，回车或点到别处时再归还
        self._focus_pending = False
        self._sync.return_focus()

    @staticmethod
    def _is_text_editing():
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, _TEXT_EDIT_WIDGETS):
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            self._mouse_down = True
            self._edit_dirty = False
        elif etype == QEvent.MouseButtonRelease:
            self._mouse_down = False
            self._try_return_focus()
        elif etype == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._edit_dirty = False
                self._try_return_focus()
            elif self._is_text_editing():
                self._edit_dirty = True
        elif etype in (QEvent.WindowDeactivate, QEvent.UngrabMouse):
            self._mouse_down = False
        return super().eventFilter(obj, event)

    def _on_sync_status(self, mode, connected):
        if mode != self._sync_mode:
            return
        if self._sync_mode == "off" or not self._sync_enabled:
            # 同步关闭/未开启时控制器也会报告 connected=False，这里不能显示成
            # 红色「未连接」，否则看起来像是出错了。
            self._sync_status.set_message(STATUS_IDLE, State.NEUTRAL)
            return
        if connected:
            self._sync_status.set_message(STATUS_SYNCED, State.SUCCESS)
        else:
            self._sync_status.set_message(STATUS_DISCONNECTED, State.DANGER)

    def _on_sync_message(self, text, detail=""):
        if self._sync_mode == "off" or not self._sync_enabled or not text:
            return
        state = _SYNC_STATUS_STATES.get(text, State.WARNING)
        self._sync_status.set_message(text, state, detail)


def main():
    if getattr(sys, "frozen", False):
        os.environ["QT_PLUGIN_PATH"] = os.path.join(
            sys._MEIPASS, "PySide6", "plugins")
    configure_application()
    app = QApplication(sys.argv)
    app.setApplicationName("pixnex")
    app.setApplicationDisplayName("pixnex")
    # 整个应用的窗口图标（任务栏 / Alt-Tab / 未单独设置图标的对话框都继承）。
    app.setWindowIcon(app_icon())
    apply_theme(app)
    # 界面状态落盘：自动折叠 / 置顶 / 窗口位置尺寸，重启后恢复上次关闭时的样子。
    win = MainWindow(WindowStateStore.persistent())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
