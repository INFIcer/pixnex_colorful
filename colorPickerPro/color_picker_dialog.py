from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from .screenPicker import ScreenPicker
from .color_picker_widgets import (
    BaseColorModel, ALL_MODELS,
    GraphicalPicker, DynamicSlidersWidget, ColorInfoPanel,
)


class ColorPickerDialog(QDialog):
    colorSelected = Signal(int, int, int)

    def __init__(self, parent=None, initial_color=None, model_name=None):
        super().__init__(parent)
        self.setWindowTitle("取色对话框")
        self.setMinimumSize(300, 600)

        self._requested_model_name = model_name

        if self._requested_model_name is not None and self._requested_model_name in ALL_MODELS:
            self._model: BaseColorModel = ALL_MODELS[self._requested_model_name]()
        else:
            self._model: BaseColorModel = list(ALL_MODELS.values())[0]()
        self._model.set_from_srgb(1.0, 0.0, 0.0)

        if initial_color is not None:
            r, g, b = initial_color
            self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)

        self.setWindowModality(Qt.WindowModal)
        self._screen_picker = ScreenPicker()
        self._screen_picker.colorPicked.connect(self._on_screen_picked)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        sel_layout = QHBoxLayout()
        sel_layout.addStretch()
        lbl = QLabel("颜色模型:")
        lbl.setStyleSheet("font-weight: bold;")
        sel_layout.addWidget(lbl)
        self._combo = QComboBox()
        self._combo.blockSignals(True)
        self._combo.addItems(list(ALL_MODELS.keys()))
        self._combo.setCurrentText(
            self._requested_model_name
            if self._requested_model_name is not None and self._requested_model_name in ALL_MODELS
            else list(ALL_MODELS.keys())[0]
        )
        self._combo.blockSignals(False)
        self._combo.currentTextChanged.connect(self._on_model_switch)
        sel_layout.addWidget(self._combo)
        sel_layout.addStretch()
        main_layout.addLayout(sel_layout)

        self._graph = GraphicalPicker(self._model, size=200)
        main_layout.addWidget(self._graph, alignment=Qt.AlignCenter)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(sep)

        self._slider_widget = DynamicSlidersWidget(self._model)
        main_layout.addWidget(self._slider_widget)

        self._info_panel = ColorInfoPanel(self._model)
        main_layout.addWidget(self._info_panel)
        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._ok_btn = QPushButton("确定")
        self._ok_btn.setStyleSheet("""
            QPushButton { padding: 8px 24px; font-size: 13px;
                background-color: #26A69A; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #00897B; }
            QPushButton:pressed { background-color: #00695C; }
        """)
        self._ok_btn.setCursor(Qt.PointingHandCursor)
        self._ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setStyleSheet("""
            QPushButton { padding: 8px 24px; font-size: 13px;
                background-color: #A98E3B; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #546E7A; }
            QPushButton:pressed { background-color: #37474F; }
        """)
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    def _on_model_switch(self, name):
        old_rgb = self._model.to_srgb_tuple()
        self._model = ALL_MODELS[name]()
        self._model.set_from_srgb(old_rgb[0], old_rgb[1], old_rgb[2])

        layout = self.layout()
        idx = layout.indexOf(self._graph)
        layout.removeWidget(self._graph)
        self._graph.deleteLater()
        self._graph = GraphicalPicker(self._model, size=200)
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


    def _on_screen_picked(self, r, g, b):
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)

    def _on_accept(self):
        r, g, b = self._model.to_srgb_tuple()
        ri = round(r * 255)
        gi = round(g * 255)
        bi = round(b * 255)
        self.colorSelected.emit(ri, gi, bi)
        self.accept()

    def _on_constrain(self):
        self._model.constrain_to_gamut()

    def get_color(self):
        r, g, b = self._model.to_srgb_tuple()
        return (round(r * 255), round(g * 255), round(b * 255))

    def set_color(self, r, g, b):
        self._model.set_from_srgb(
            max(0, min(255, r)) / 255.0,
            max(0, min(255, g)) / 255.0,
            max(0, min(255, b)) / 255.0,
        )
