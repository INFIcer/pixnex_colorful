import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QComboBox, QMenu
)
from PySide6.QtCore import Qt

from .screenPicker import ScreenPicker
from .filter_lib import ImageFilter
from .screenFilter import ScreenFilterWindow
from .image_drop_widget import ImageDropWidget
from .list_selection_dialog import ListSelectionDialog
from .image_filter_compare import ImageFilterCompareWindow
from .color_picker_widgets import (
    OKLCHModel, HSVModel, CIELCHModel, CIELabModel, HSIModel,
    BaseColorModel, ALL_MODELS,
    GraphicalPicker, DynamicSlidersWidget, ColorInfoPanel,
)
from .sync.controller import SyncController


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
        self._screen_filter_btn.setStyleSheet("""
            QPushButton { padding: 6px 16px; font-size: 12px;
                background-color: #7B1FA2; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #6A1B9A; }
            QPushButton:pressed { background-color: #4A148C; }
        """)
        self._screen_filter_btn.setCursor(Qt.PointingHandCursor)

        self._filter_menu = QMenu(self)
        for cls in ImageFilter.all_filters():
            action = self._filter_menu.addAction(cls.name())
            action.triggered.connect(lambda checked, c=cls: self._create_screen_filter(c))
        self._screen_filter_btn.setMenu(self._filter_menu)

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

        self._sync_status = QLabel("未同步")
        self._sync_status.setStyleSheet("font-size: 10px; color: #888;")
        row.addWidget(self._sync_status, 1)
        layout.addLayout(row)

    def _create_screen_filter(self, filter_cls):
        fi = filter_cls()
        win = ScreenFilterWindow(fi)
        off = 30 * (len(self._filter_windows) % 8)
        win.move(100 + off, 100 + off)
        win.start()
        self._filter_windows.append(win)
        win.destroyed.connect(lambda w=win: self._on_filter_closed(w))

    def _on_filter_closed(self, win):
        if win in self._filter_windows:
            self._filter_windows.remove(win)

    def _on_drop_image(self, pixmap, filename):
        all_filters = ImageFilter.all_filters()
        names = [cls.name() for cls in all_filters]
        dlg = ListSelectionDialog(
            self, "选择对比滤镜", names,
            selection_mode="multiple", checked_indices=[]
        )
        if dlg.exec() == ListSelectionDialog.Accepted:
            indices = dlg.get_selected_indices()
            if not indices:
                return
            selected_names = [names[i] for i in indices]
            win = ImageFilterCompareWindow(pixmap, selected_names)
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

    # ----- color sync ------------------------------------------------------
    def _on_sync_mode_change(self, index):
        self._sync_mode = self._sync_combo.itemData(index)
        active = self._sync_mode != "off"
        self._sync.set_mode(self._sync_mode)
        self._sync_btn.setEnabled(active)
        if not active:
            self._sync_enabled = False
            self._sync.set_enabled(False)
            self._sync_btn.setText("开启同步")
            self._sync_status.setText("未同步")

    def _on_sync_toggle(self):
        self._sync_enabled = not self._sync_enabled
        self._sync.set_enabled(self._sync_enabled)
        self._sync_btn.setText("关闭同步" if self._sync_enabled else "开启同步")
        if self._sync_enabled:
            self._push_sync_color()
            self._sync_status.setText("连接中…")

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

    def _on_sync_external(self, r, g, b):
        self._applying_ext = True
        try:
            self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)
        finally:
            self._applying_ext = False

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
