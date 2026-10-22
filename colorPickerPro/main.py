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

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QLineEdit,
    QMainWindow, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget,
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
from .sync.controller import SyncController
from .ui import apply_theme, configure_application
from .ui.components import (
    Card, CaptionLabel, FieldLabel, FramelessWindowMixin, IconButton,
    PrimaryButton, ScrollArea, StatusLabel, hbox,
)
from .ui.theme import set_variant
from .ui.tokens import SPACE, State, Variant

# 正在输入数值/文本的控件：此时归还焦点会打断输入，需要等编辑结束。
_TEXT_EDIT_WIDGETS = (
    QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit,
)


class MainWindow(FramelessWindowMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pixnex")
        self.setMinimumSize(320, 460)
        self.resize(380, 640)

        self._model: BaseColorModel = OKLCHModel()
        self._model.set_from_srgb(1.0, 0.0, 0.0)
        self._applying_ext = False
        self._always_on_top = False

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
            "pixnex", layout=outer, subtitle="色彩工具",
            show_minimize=True, show_maximize=False, show_close=True,
            resizable=True, double_click=None)
        self._pin_btn = IconButton("pin", tooltip="置顶", checkable=True)
        self._pin_btn.toggled.connect(self._set_always_on_top)
        self.title_bar.add_button(self._pin_btn)

        body = QWidget()
        body.setObjectName("FramelessBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(
            SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        self._body_layout.setSpacing(SPACE.md)
        outer.addWidget(body, 1)

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
        card = Card("图形化选色")
        self._graph_hint = CaptionLabel("拖动取色")
        card.add_header_widget(self._graph_hint)
        self._graph = GraphicalPicker(self._model, size=220)
        card.add(self._graph)
        return card

    def _build_sliders_card(self) -> Card:
        card = Card("滑块微调")
        self._slider_widget = DynamicSlidersWidget(self._model)
        card.add(self._slider_widget)
        return card

    def _build_color_card(self) -> Card:
        card = Card("当前颜色")
        self._info_panel = ColorInfoPanel(self._model)
        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)
        self._screen_picker.colorPicked.connect(self._on_picked)
        card.add(self._info_panel)
        return card

    def _build_sync_card(self) -> Card:
        card = Card("颜色同步")
        self._sync_status = StatusLabel("未同步", State.NEUTRAL)
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
        card = Card("滤镜与图像对比")
        card.add_header_widget(CaptionLabel("方案可叠加滤镜"))
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
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self.isVisible():
            self.show()
            self.raise_()

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        if self._always_on_top:
            self._apply_topmost(True)

    def _on_constrain(self):
        self._model.constrain_to_gamut()

    def _on_picked(self, r, g, b):
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)
        # 屏幕取色的那次点击发生在取色器覆盖层里，覆盖层随即隐藏，松键事件
        # 不会再回到本进程，所以这里直接结束"鼠标按下"状态并归还焦点。
        self._mouse_down = False
        self._try_return_focus()

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
            self._sync_status.set_message("未同步", State.NEUTRAL)

    def _on_sync_toggle(self):
        self._sync_enabled = not self._sync_enabled
        self._sync.set_enabled(self._sync_enabled)
        self._update_sync_button()
        if self._sync_enabled:
            self._last_pushed_rgb = None   # 开启后第一次选色一定归还
            self._push_sync_color()
            self._sync_status.set_message("连接中…", State.ACCENT)
        else:
            self._sync_pending_off()

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
        if self._sync_mode == "off":
            # 同步关闭时控制器也会报告 connected=False，这里不能显示成
            # 红色「未连接」，否则看起来像是出错了。
            self._sync_status.set_message("未同步", State.NEUTRAL)
            return
        if connected:
            self._sync_status.set_message("已同步", State.SUCCESS)
        else:
            self._sync_status.set_message("未连接", State.DANGER)

    def _on_sync_message(self, message):
        if self._sync_mode == "off" or not message:
            return
        self._sync_status.set_message(message, State.WARNING)


def main():
    if getattr(sys, "frozen", False):
        os.environ["QT_PLUGIN_PATH"] = os.path.join(
            sys._MEIPASS, "PySide6", "plugins")
    configure_application()
    app = QApplication(sys.argv)
    app.setApplicationName("pixnex")
    app.setApplicationDisplayName("pixnex")
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
