"""取色对话框：模型选择 + 图形取色 + 滑块 + 颜色信息，基于统一设计系统。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox

from .screenPicker import ScreenPicker
from .color_picker_widgets import (
    BaseColorModel, ALL_MODELS,
    GraphicalPicker, DynamicSlidersWidget, ColorInfoPanel,
)
from .ui.components import (
    CaptionLabel,
    Card,
    FieldLabel,
    ThemedDialog,
    hbox,
)
from .ui.tokens import SPACE


class ColorPickerDialog(ThemedDialog):
    """统一的取色对话框（ThemedDialog 外壳 + 可滚动内容区）。

    内容区在窗口很矮时会滚动，因此对话框在 360×560 的最小尺寸下依然可用；
    切换颜色模型只调用子控件的 ``set_model()``，不重建界面。
    """

    colorSelected = Signal(int, int, int)

    MIN_WIDTH = 320
    MIN_HEIGHT = 460
    DEFAULT_WIDTH = 400
    DEFAULT_HEIGHT = 680

    def __init__(self, parent=None, initial_color=None, model_name=None):
        super().__init__("取色对话框", parent=parent)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setWindowModality(Qt.WindowModal)

        self._requested_model_name = model_name
        if (self._requested_model_name is not None
                and self._requested_model_name in ALL_MODELS):
            self._model: BaseColorModel = ALL_MODELS[self._requested_model_name]()
        else:
            self._model: BaseColorModel = list(ALL_MODELS.values())[0]()
        self._model.set_from_srgb(1.0, 0.0, 0.0)

        if initial_color is not None:
            r, g, b = initial_color
            self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)

        self._screen_picker = ScreenPicker()
        self._screen_picker.colorPicked.connect(self._on_screen_picked)

        self._init_ui()

    # ------------------------------------------------------------------
    def _init_ui(self):
        # 内容区可滚动：窗口高度不足时出现滚动条，而不是把控件压到重叠。
        content = self.make_body_scrollable()

        # 颜色模型：与主窗口一致放进卡片，保证两个窗口的结构一致。
        model_card = Card("色彩模型", padding=SPACE.md)
        self._combo = QComboBox()
        self._combo.addItems(list(ALL_MODELS.keys()))
        self._combo.blockSignals(True)
        self._combo.setCurrentText(self._initial_model_name())
        self._combo.blockSignals(False)
        self._combo.currentTextChanged.connect(self._on_model_switch)
        combo_row = hbox(FieldLabel("模型"), self._combo, spacing=SPACE.sm)
        combo_row.setStretch(1, 1)
        model_card.add_layout(combo_row)
        content.addWidget(model_card)

        graph_card = Card("图形化选色", padding=SPACE.md)
        graph_card.add_header_widget(CaptionLabel("拖动取色"))
        self._graph = GraphicalPicker(self._model, size=180)
        graph_card.add(self._graph)
        content.addWidget(graph_card)

        slider_card = Card("滑块微调", padding=SPACE.md)
        self._slider_widget = DynamicSlidersWidget(self._model)
        slider_card.add(self._slider_widget)
        content.addWidget(slider_card)

        info_card = Card("当前颜色", padding=SPACE.md)
        self._info_panel = ColorInfoPanel(self._model)
        info_card.add(self._info_panel)
        content.addWidget(info_card)
        self._info_panel.pickStart.connect(self._screen_picker.start_pick)
        self._info_panel.constrainRequested.connect(self._on_constrain)

        # 内容比窗口矮时保持卡片顶部对齐。
        content.addStretch(1)

        self._cancel_btn = self.add_reject_button("取消")
        self._ok_btn = self.add_accept_button("确定")
        self._apply_default_size()

    def _apply_default_size(self) -> None:
        """默认尺寸适配内容与屏幕可用高度：放得下就一屏展示，否则滚动。"""
        width = self.DEFAULT_WIDTH
        height = self.DEFAULT_HEIGHT
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - 40)
            height = min(height, available.height() - 40)
        self.resize(max(self.MIN_WIDTH, width), max(self.MIN_HEIGHT, height))

    def _initial_model_name(self) -> str:
        if (self._requested_model_name is not None
                and self._requested_model_name in ALL_MODELS):
            return self._requested_model_name
        return list(ALL_MODELS.keys())[0]

    # ------------------------------------------------------------------
    def _on_model_switch(self, name):
        """切换模型：保留当前颜色，原地让三个子控件重新绑定模型。"""
        if name not in ALL_MODELS:
            return
        # 程序化切换（不走下拉框）时同步显示，避免界面与模型不一致。
        if self._combo.currentText() != name:
            self._combo.blockSignals(True)
            self._combo.setCurrentText(name)
            self._combo.blockSignals(False)
        old_rgb = self._model.to_srgb_tuple()
        model = ALL_MODELS[name]()
        model.set_from_srgb(old_rgb[0], old_rgb[1], old_rgb[2])

        self._model = model
        self._graph.set_model(model)
        self._slider_widget.set_model(model)
        self._info_panel.set_model(model)

    def _on_screen_picked(self, r, g, b):
        self._model.set_from_srgb(r / 255.0, g / 255.0, b / 255.0)

    def _on_constrain(self):
        self._model.constrain_to_gamut()

    def _on_accept(self):
        self.accept()

    def accept(self):
        r, g, b = self.get_color()
        self.colorSelected.emit(r, g, b)
        super().accept()

    def get_color(self):
        r, g, b = self._model.to_srgb_tuple()
        return (round(r * 255), round(g * 255), round(b * 255))

    def set_color(self, r, g, b):
        self._model.set_from_srgb(
            max(0, min(255, r)) / 255.0,
            max(0, min(255, g)) / 255.0,
            max(0, min(255, b)) / 255.0,
        )
