import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QComboBox, QCheckBox, QSizePolicy,
    QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit, QDialog,
)
from PySide6.QtCore import Qt, QEvent

from .screenPicker import ScreenPicker
from .screenFilter import ScreenFilterWindow
from .image_drop_widget import ImageDropWidget
from .filter_scheme_selector import FilterSchemeSelectorDialog
from .image_filter_compare import ImageFilterCompareWindow
from .color_picker_widgets import (
    OKLCHModel, HSVModel, CIELCHModel, CIELabModel, HSIModel,
    BaseColorModel, ALL_MODELS,
    GraphicalPicker, DynamicSlidersWidget, ColorInfoPanel,
)
from .sync.controller import SyncController


# 正在输入数值/文本的控件：此时归还焦点会打断输入，需要等编辑结束。
_TEXT_EDIT_WIDGETS = (
    QAbstractSpinBox, QLineEdit, QTextEdit, QPlainTextEdit,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('pixnex')
        self.setMinimumSize(300, 660)
        self.setMaximumSize(700, 800)

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

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 6, 10, 6)

        sel_layout = QHBoxLayout()
        sel_layout.addStretch()
        lbl = QLabel("颜色模型:")
        lbl.setStyleSheet("font-weight: bold;")
        sel_layout.addWidget(lbl)
        self._combo = QComboBox()
        self._combo.addItems(list(ALL_MODELS.keys()))
        self._combo.currentTextChanged.connect(self._on_model_switch)
        sel_layout.addWidget(self._combo)
        sel_layout.addStretch()
        layout.addLayout(sel_layout)

        self._desc_label = QLabel("")
        self._desc_label.setAlignment(Qt.AlignCenter)
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("font-size: 10px; color: #666; padding: 2px 8px;")
        layout.addWidget(self._desc_label)

        self._title1 = QLabel("图形化选色")
        self._title1.setStyleSheet("font-size: 12px; font-weight: bold; color: #555;")
        self._title1.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title1)

        self._graph = GraphicalPicker(self._model, size=240)
        layout.addWidget(self._graph, alignment=Qt.AlignCenter)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        self._title2 = QLabel("滑块选色")
        self._title2.setStyleSheet("font-size: 12px; font-weight: bold; color: #555;")
        self._title2.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title2)

        self._slider_widget = DynamicSlidersWidget(self._model)
        layout.addWidget(self._slider_widget)

        self._info_panel = ColorInfoPanel(self._model)
        layout.addWidget(self._info_panel)

        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)
        self._screen_picker.colorPicked.connect(self._on_picked)

        self._model.add_listener(self._on_model_sync)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        self._build_sync_row(layout)
        self._filter_windows = []
        self._compare_windows = []

        filter_btn_layout = QHBoxLayout()
        filter_btn_layout.addStretch()

        self._screen_filter_btn = QPushButton("🎨 屏幕滤镜")
        self._screen_filter_btn.setToolTip("选择滤镜或已保存的滤镜方案，创建置顶滤镜窗口")
        self._screen_filter_btn.setStyleSheet("""
            QPushButton { padding: 6px 16px; font-size: 12px;
                background-color: #7B1FA2; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #6A1B9A; }
            QPushButton:pressed { background-color: #4A148C; }
        """)
        self._screen_filter_btn.setCursor(Qt.PointingHandCursor)
        self._screen_filter_btn.clicked.connect(self._on_pick_screen_filter)

        filter_btn_layout.addWidget(self._screen_filter_btn)

        self._image_drop = ImageDropWidget(
            placeholder_text="拖入图像进行滤镜对比",
            drop_hint="释放以对比滤镜"
        )
        self._image_drop.setFixedSize(150, 40)
        self._image_drop.imageReceived.connect(self._on_drop_image)
        filter_btn_layout.addWidget(self._image_drop)

        filter_btn_layout.addStretch()
        layout.addLayout(filter_btn_layout)

        self._desc_label.setText(self._model.description)
        self._sync.start()

        # 全局事件过滤：跟踪鼠标按键与键入状态，用于判断"选色交互"是否结束。
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build_sync_row(self, layout):
        row = QHBoxLayout()
        lbl = QLabel("🎨 颜色同步")
        lbl.setStyleSheet("font-weight: bold; font-size: 11px;")
        row.addWidget(lbl)

        self._sync_combo = QComboBox()
        self._sync_combo.addItem("关闭", "off")
        self._sync_combo.addItem("UDM Paint", "udm")
        self._sync_combo.addItem("Photoshop", "ps")
        self._sync_combo.currentIndexChanged.connect(self._on_sync_mode_change)
        row.addWidget(self._sync_combo)

        self._sync_btn = QPushButton("开启同步")
        self._sync_btn.setStyleSheet("""
            QPushButton { padding: 3px 12px; font-size: 11px;
                background-color: #00897B; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #00796B; }
            QPushButton:disabled { background-color: #B0BEC5; }
        """)
        self._sync_btn.setCursor(Qt.PointingHandCursor)
        self._sync_btn.setEnabled(False)
        self._sync_btn.clicked.connect(self._on_sync_toggle)
        row.addWidget(self._sync_btn)

        self._focus_chk = QCheckBox("归还焦点")
        self._focus_chk.setToolTip(
            "开启同步后，每次选色操作结束时自动把窗口焦点归还给同步软件"
            "（例如 CSP）；正在拖拽或输入数值时不会打断。")
        self._focus_chk.setStyleSheet("font-size: 10px;")
        self._focus_chk.setChecked(True)
        self._focus_chk.setEnabled(False)
        self._focus_chk.toggled.connect(self._on_focus_return_toggled)
        row.addWidget(self._focus_chk)

        self._sync_status = QLabel("未同步")
        self._sync_status.setStyleSheet("font-size: 10px; color: #888;")
        # 状态文字最不关键：窗口被拖窄时优先压缩它，别挤掉勾选框。
        self._sync_status.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._sync_status.setMinimumWidth(0)
        row.addWidget(self._sync_status, 1)
        layout.addLayout(row)

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
        off = 30 * (len(self._filter_windows) % 8)
        win.move(100 + off, 100 + off)
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
        win.destroyed.connect(lambda w=win: self._compare_windows.remove(w) if w in self._compare_windows else None)

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

    def _on_model_switch(self, name):
        old_rgb = self._model.to_srgb_tuple()
        self._model = ALL_MODELS[name]()
        self._model.set_from_srgb(old_rgb[0], old_rgb[1], old_rgb[2])

        layout = self.centralWidget().layout()
        idx = layout.indexOf(self._graph)
        layout.removeWidget(self._graph)
        self._graph.deleteLater()
        self._graph = GraphicalPicker(self._model, size=240)
        layout.insertWidget(idx, self._graph, alignment=Qt.AlignCenter)

        idx2 = layout.indexOf(self._slider_widget)
        layout.removeWidget(self._slider_widget)
        self._slider_widget.deleteLater()
        self._slider_widget = DynamicSlidersWidget(self._model)
        layout.insertWidget(idx2, self._slider_widget)

        idx3 = layout.indexOf(self._info_panel)
        layout.removeWidget(self._info_panel)
        self._info_panel.deleteLater()
        self._info_panel = ColorInfoPanel(self._model)
        layout.insertWidget(idx3, self._info_panel)
        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)
        self._model.add_listener(self._on_model_sync)

        self._title1.setText(f"图形化选色 - {name}")
        self._title2.setText(f"滑块选色 - {name}")
        self._desc_label.setText(self._model.description)

    def _on_constrain(self):
        self._model.constrain_to_gamut()

    def _on_picked(self, r, g, b):
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)
        # 屏幕取色的那次点击发生在取色器覆盖层里，覆盖层随即隐藏，松键事件
        # 不会再回到本进程，所以这里直接结束"鼠标按下"状态并归还焦点。
        self._mouse_down = False
        self._try_return_focus()

    # ----- color sync ------------------------------------------------------
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
            self._sync_btn.setText("开启同步")
            self._sync_status.setText("未同步")

    def _on_sync_toggle(self):
        self._sync_enabled = not self._sync_enabled
        self._sync.set_enabled(self._sync_enabled)
        self._sync_btn.setText("关闭同步" if self._sync_enabled else "开启同步")
        if self._sync_enabled:
            self._last_pushed_rgb = None   # 开启后第一次选色一定归还
            self._push_sync_color()
            self._sync_status.setText("连接中…")
        else:
            self._sync_pending_off()

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

    # ----- focus hand-back -------------------------------------------------
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
        if connected:
            self._sync_status.setText("✓ 已同步")
            self._sync_status.setStyleSheet("font-size: 10px; color: #4CAF50;")
        else:
            self._sync_status.setText("未连接")
            self._sync_status.setStyleSheet("font-size: 10px; color: #f44336;")

    def _on_sync_message(self, message):
        if self._sync_mode == "off" or not message:
            return
        self._sync_status.setText(message)
        self._sync_status.setStyleSheet("font-size: 10px; color: #f9A825;")


def main():
    if getattr(sys, 'frozen', False):
        os.environ['QT_PLUGIN_PATH'] = os.path.join(sys._MEIPASS, 'PySide6', 'plugins')
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
