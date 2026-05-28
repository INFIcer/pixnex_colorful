"""
滤镜库：模块化设计，新增滤镜只需继承 ImageFilter
=============================================
包含：
- 参数类型：FilterParam, RangeParam, BoolParam, ColorParam
- 依赖系统：add_dependency()
- 滤镜基类：ImageFilter (自动注册子类)
- 内置滤镜：灰度、色度、边缘检测、反转、怀旧、正片叠底等
- 工具：ImageConvert, _RangeSlider
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QDoubleSpinBox,
    QSpinBox, QCheckBox, QFrame, QPushButton, QLineEdit, QGraphicsOpacityEffect,
)
from .colorMath import (
    bgr_to_cielch, bgr_to_gray,
    bgr_hsv_s_channel, bgr_hls_l_channel,
    bgra_to_bgr, invert, sepia, edge_detect,
)
from .color_picker_dialog import ColorPickerDialog


# ============================================================
# 参数类型
# ============================================================

class FilterParam:
    """描述一个滤镜暴露的可调参数。"""
    def __init__(self, name, description, vmin, vmax, default, step=1):
        self.name = name
        self.description = description
        self.vmin = vmin
        self.vmax = vmax
        self.default = default
        self.step = step
        self.value = default
        self._listeners = []
        self._container = None
        self._opacity_effect = None

    def on_value_changed(self, cb):
        self._listeners.append(cb)

    def _notify_value_changed(self):
        for cb in self._listeners:
            cb()

    def set_enabled(self, enabled):
        if self._container:
            if enabled:
                if self._opacity_effect:
                    self._container.setGraphicsEffect(None)
                    self._opacity_effect = None
            else:
                if self._opacity_effect is None:
                    self._opacity_effect = QGraphicsOpacityEffect()
                    self._opacity_effect.setOpacity(0.35)
                self._container.setGraphicsEffect(self._opacity_effect)
            self._container.setEnabled(enabled)

    @staticmethod
    def _val_to_slider(val, vmin, vmax):
        if vmax <= vmin:
            return 0
        return int(1000 * (val - vmin) / (vmax - vmin))

    @staticmethod
    def _slider_to_val(sv, vmin, vmax):
        return vmin + (sv / 1000.0) * (vmax - vmin)

    def create_widget(self, on_changed):
        container = QWidget()
        self._container = container
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(self.name)
        lbl.setObjectName("paramName")
        lbl.setFixedWidth(72)
        lbl.setToolTip(self.description)
        row.addWidget(lbl)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 1000)
        slider.setValue(self._val_to_slider(self.value, self.vmin, self.vmax))
        row.addWidget(slider, 1)

        spin = QDoubleSpinBox()
        spin.setRange(self.vmin, self.vmax)
        spin.setDecimals(1 if isinstance(self.step, int) and self.step >= 1 else 3)
        spin.setSingleStep(self.step)
        spin.setValue(self.value)
        spin.setFixedWidth(72)
        row.addWidget(spin)

        def on_slider(sv):
            val = self._slider_to_val(sv, self.vmin, self.vmax)
            self.value = val
            spin.blockSignals(True); spin.setValue(val); spin.blockSignals(False)
            self._notify_value_changed()
            on_changed()
        def on_spin(val):
            self.value = val
            slider.blockSignals(True); slider.setValue(self._val_to_slider(val, self.vmin, self.vmax)); slider.blockSignals(False)
            self._notify_value_changed()
            on_changed()
        slider.valueChanged.connect(on_slider)
        spin.valueChanged.connect(on_spin)

        return container


class RangeParam:
    """描述一个范围型参数（如阈值区间），包含最小值和最大值，且最小值不能越过最大值。"""
    def __init__(self, name, description, abs_min, abs_max, default_low, default_high, step=1):
        self.name = name
        self.description = description
        self.absolute_min = abs_min
        self.absolute_max = abs_max
        self.step = step
        self._low = default_low
        self._high = default_high
        self._listeners = []
        self._container = None
        self._opacity_effect = None

    def on_value_changed(self, cb):
        self._listeners.append(cb)

    def _notify_value_changed(self):
        for cb in self._listeners:
            cb()

    def set_enabled(self, enabled):
        if self._container:
            if enabled:
                if self._opacity_effect:
                    self._container.setGraphicsEffect(None)
                    self._opacity_effect = None
            else:
                if self._opacity_effect is None:
                    self._opacity_effect = QGraphicsOpacityEffect()
                    self._opacity_effect.setOpacity(0.35)
                self._container.setGraphicsEffect(self._opacity_effect)
            self._container.setEnabled(enabled)

    @property
    def low(self):
        return self._low

    @low.setter
    def low(self, v):
        self._low = min(v, self._high)

    @property
    def high(self):
        return self._high

    @high.setter
    def high(self, v):
        self._high = max(v, self._low)

    def create_widget(self, on_changed):
        container = QWidget()
        self._container = container
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        lbl = QLabel(self.name)
        lbl.setObjectName("paramName")
        lbl.setFixedWidth(48)
        lbl.setToolTip(self.description)
        row.addWidget(lbl)

        rs = _RangeSlider(self)
        row.addWidget(rs, 1)

        sp_low = QDoubleSpinBox()
        sp_low.setRange(self.absolute_min, self.absolute_max)
        sp_low.setDecimals(1 if isinstance(self.step, int) and self.step >= 1 else 3)
        sp_low.setSingleStep(self.step)
        sp_low.setValue(self.low)
        sp_low.setFixedWidth(64)
        row.addWidget(sp_low)

        sep = QLabel("~")
        sep.setStyleSheet("color: #666;")
        sep.setFixedWidth(16)
        sep.setAlignment(Qt.AlignCenter)
        row.addWidget(sep)

        sp_high = QDoubleSpinBox()
        sp_high.setRange(self.absolute_min, self.absolute_max)
        sp_high.setDecimals(1 if isinstance(self.step, int) and self.step >= 1 else 3)
        sp_high.setSingleStep(self.step)
        sp_high.setValue(self.high)
        sp_high.setFixedWidth(64)
        row.addWidget(sp_high)

        def on_range(low, high):
            sp_low.blockSignals(True); sp_low.setValue(low); sp_low.blockSignals(False)
            sp_high.blockSignals(True); sp_high.setValue(high); sp_high.blockSignals(False)
            self._notify_value_changed()
            on_changed()
        def on_sp_low(v):
            self.low = v
            rs.update()
            on_range(self.low, self.high)
        def on_sp_high(v):
            self.high = v
            rs.update()
            on_range(self.low, self.high)
        rs.rangeChanged.connect(on_range)
        sp_low.valueChanged.connect(on_sp_low)
        sp_high.valueChanged.connect(on_sp_high)

        return container


class BoolParam:
    """描述一个布尔型开关参数。"""

    def __init__(self, name, description, default=True):
        self.name = name
        self.description = description
        self.value = default
        self._listeners = []
        self._container = None
        self._opacity_effect = None

    def on_value_changed(self, cb):
        self._listeners.append(cb)

    def _notify_value_changed(self):
        for cb in self._listeners:
            cb()

    def set_enabled(self, enabled):
        if self._container:
            if enabled:
                if self._opacity_effect:
                    self._container.setGraphicsEffect(None)
                    self._opacity_effect = None
            else:
                if self._opacity_effect is None:
                    self._opacity_effect = QGraphicsOpacityEffect()
                    self._opacity_effect.setOpacity(0.35)
                self._container.setGraphicsEffect(self._opacity_effect)
            self._container.setEnabled(enabled)

    def create_widget(self, on_changed):
        container = QWidget()
        self._container = container
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        cb = QCheckBox(self.name)
        cb.setToolTip(self.description)
        cb.setChecked(self.value)
        cb.setStyleSheet("color: #bbb; font-size: 12px; spacing: 6px;")
        cb.toggled.connect(lambda checked: setattr(self, 'value', checked) or (self._notify_value_changed(), on_changed()) or None)
        row.addWidget(cb)
        row.addStretch()

        return container


class ColorParam:
    """描述一个颜色参数，可通过屏幕取色、Hex 输入或 RGB 滑动条设置。"""

    def __init__(self, name, description, default_r=255, default_g=0, default_b=0):
        self.name = name
        self.description = description
        self._r = int(np.clip(default_r, 0, 255))
        self._g = int(np.clip(default_g, 0, 255))
        self._b = int(np.clip(default_b, 0, 255))
        self._listeners = []
        self._container = None
        self._opacity_effect = None

    @property
    def value(self):
        return (self._r, self._g, self._b)

    def on_value_changed(self, cb):
        self._listeners.append(cb)

    def _notify_value_changed(self):
        for cb in self._listeners:
            cb()

    def set_enabled(self, enabled):
        if self._container:
            if enabled:
                if self._opacity_effect:
                    self._container.setGraphicsEffect(None)
                    self._opacity_effect = None
            else:
                if self._opacity_effect is None:
                    self._opacity_effect = QGraphicsOpacityEffect()
                    self._opacity_effect.setOpacity(0.35)
                self._container.setGraphicsEffect(self._opacity_effect)
            self._container.setEnabled(enabled)

    def create_widget(self, on_changed):
        container = QWidget()
        self._container = container
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(self.name)
        lbl.setObjectName("paramName")
        lbl.setFixedWidth(72)
        lbl.setToolTip(self.description)
        row.addWidget(lbl)

        swatch = QPushButton()
        swatch.setFixedSize(22, 22)
        swatch.setCursor(Qt.PointingHandCursor)
        swatch.setStyleSheet(f"""
            QPushButton {{ background-color: rgb({self._r},{self._g},{self._b});
                border: 1px solid #666; border-radius: 2px; }}
            QPushButton:hover {{ border: 1px solid #aaa; }}
        """)

        hex_edit = QLineEdit()
        hex_edit.setMaxLength(7)
        hex_edit.setText(f"#{self._r:02X}{self._g:02X}{self._b:02X}")
        hex_edit.setFixedWidth(64)
        hex_edit.setPlaceholderText("#RRGGBB")
        hex_edit.setStyleSheet("QLineEdit { background: #3a3a3a; color: white; border: 1px solid #555; border-radius: 3px; padding: 1px 4px; font-size: 11px; }")

        def sync(r, g, b):
            self._r, self._g, self._b = r, g, b
            swatch.setStyleSheet(f"""
                QPushButton {{ background-color: rgb({r},{g},{b});
                    border: 1px solid #666; border-radius: 2px; }}
                QPushButton:hover {{ border: 1px solid #aaa; }}
            """)
            hex_edit.blockSignals(True); hex_edit.setText(f"#{r:02X}{g:02X}{b:02X}"); hex_edit.blockSignals(False)
            self._notify_value_changed()
            on_changed()

        def open_dialog():
            parent = self._container.parent()
            dialog = ColorPickerDialog(parent, initial_color=(self._r, self._g, self._b), model_name="HSV")
            if dialog.exec() == ColorPickerDialog.Accepted:
                r, g, b = dialog.get_color()
                sync(r, g, b)

        swatch.clicked.connect(open_dialog)
        row.addWidget(swatch)
        row.addWidget(hex_edit)
        row.addStretch()

        def on_hex():
            text = hex_edit.text()
            if len(text) == 7 and text[0] == '#':
                try:
                    sync(int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
                    return
                except ValueError:
                    pass
            hex_edit.blockSignals(True); hex_edit.setText(f"#{self._r:02X}{self._g:02X}{self._b:02X}"); hex_edit.blockSignals(False)
        hex_edit.editingFinished.connect(on_hex)

        return container


# ============================================================
# 依赖系统
# ============================================================

def add_dependency(target_param, source_param, condition_fn):
    """建立参数依赖：source_param 的值变化时重新评估 condition_fn(source_value)，
    结果为 True 时 target_param 可用，否则禁用。"""
    def evaluator():
        target_param.set_enabled(condition_fn(source_param.value))
    source_param.on_value_changed(evaluator)
    evaluator()


# ============================================================
# 滤镜基类
# ============================================================

class ImageFilter(ABC):
    """滤镜基类。子类自动注册，无需手动添加。"""

    @staticmethod
    def all_filters() -> List[type]:
        return ImageFilter.__subclasses__()

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @abstractmethod
    def process(self, img: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def exposed_parameters(self) -> List[FilterParam]:
        return []


# ============================================================
# 内置滤镜
# ============================================================

class LabGrayFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "Lab灰度"
    def process(self, img: np.ndarray) -> np.ndarray:
        lch = bgr_to_cielch(img)
        L = lch[:,:,0]
        return np.clip(L * 2.55, 0, 255).astype(np.uint8)

class LCHSaturationFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "LCH色度"
    def process(self, img: np.ndarray) -> np.ndarray:
        lch = bgr_to_cielch(img)
        C = lch[:,:,1]
        return np.clip(C * 1.7, 0, 255).astype(np.uint8)


class RGBGrayFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "RGB灰度"
    def process(self, img: np.ndarray) -> np.ndarray:
        return bgr_to_gray(img)


class HSVSaturationFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "HSV饱和度"
    def process(self, img: np.ndarray) -> np.ndarray:
        return (bgr_hsv_s_channel(img) * 255).astype(np.uint8)


class HLSLightnessFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "HLS亮度"
    def process(self, img: np.ndarray) -> np.ndarray:
        return (bgr_hls_l_channel(img) * 255).astype(np.uint8)


class EdgeDetectFilter(ImageFilter):
    def __init__(self):
        self._params = [
            RangeParam("阈值区间", "边缘检测的阈值区间，低于低阈值的梯度忽略，高于高阈值的为强边缘",
                       0, 255, 50, 150, 1),
        ]

    @classmethod
    def name(cls) -> str:
        return "边缘检测"
    def exposed_parameters(self) -> List:
        return self._params
    def process(self, img: np.ndarray) -> np.ndarray:
        p = self._params[0]
        return edge_detect(bgr_to_gray(img), int(p.low), int(p.high))


class DetailAnalyzeFilter(ImageFilter):
    """信息量分析：分别计算 Lab 灰度边缘与 LCH 色度边缘，各自染色后相加合并。"""

    def __init__(self):
        self._p_en_lab = BoolParam("启用Lab灰度", "是否将Lab亮度边缘纳入信息量分析", True)
        self._p_en_chroma = BoolParam("启用LCH色度", "是否将LCH色度边缘纳入信息量分析", True)
        self._p_lab_thresh = RangeParam("亮度", "Lab灰度图的边缘检测阈值区间", 0, 255, 0, 255, 1)
        self._p_chroma_thresh = RangeParam("色度", "LCH色度图的边缘检测阈值区间", 0, 255, 0, 255, 1)
        self._p_lab_weight = FilterParam("亮度权重", "Lab边缘灰度图的整体权重", 0, 1, 1.0, 0.01)
        self._p_chroma_weight = FilterParam("色度权重", "LCH色度边缘灰度图的整体权重", 0, 1, 0.5, 0.01)
        self._p_lab_color = ColorParam("亮度边缘颜色", "信息量分析中亮度边缘的染色颜色（乘法叠加）", 255, 0, 0)
        self._p_chroma_color = ColorParam("色度边缘颜色", "信息量分析中色度边缘的染色颜色（乘法叠加）", 0, 255, 0)
        self._params = [
            self._p_en_lab, self._p_lab_thresh, self._p_lab_weight, self._p_lab_color,
            self._p_en_chroma, self._p_chroma_thresh, self._p_chroma_weight, self._p_chroma_color,
        ]

        add_dependency(self._p_lab_thresh, self._p_en_lab, lambda v: v)
        add_dependency(self._p_lab_weight, self._p_en_lab, lambda v: v)
        add_dependency(self._p_lab_color, self._p_en_lab, lambda v: v)
        add_dependency(self._p_chroma_thresh, self._p_en_chroma, lambda v: v)
        add_dependency(self._p_chroma_weight, self._p_en_chroma, lambda v: v)
        add_dependency(self._p_chroma_color, self._p_en_chroma, lambda v: v)

    @classmethod
    def name(cls) -> str:
        return "信息量分析"
    def exposed_parameters(self) -> List:
        return self._params

    @staticmethod
    def _tint(edge: np.ndarray, r: int, g: int, b: int) -> np.ndarray:
        """将灰度边缘图与颜色相乘染色，返回 (H,W,3) BGR。"""
        edge_u16 = edge.astype(np.uint16)
        result = np.empty((*edge.shape, 3), dtype=np.uint8)
        result[..., 0] = (edge_u16 * np.uint16(b) // 255).astype(np.uint8)
        result[..., 1] = (edge_u16 * np.uint16(g) // 255).astype(np.uint8)
        result[..., 2] = (edge_u16 * np.uint16(r) // 255).astype(np.uint8)
        return result

    def process(self, img: np.ndarray) -> np.ndarray:
        if not self._p_en_lab.value and not self._p_en_chroma.value:
            return np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)

        r_lab, g_lab, b_lab = self._p_lab_color.value
        r_chroma, g_chroma, b_chroma = self._p_chroma_color.value

        e_lab = None

        lch = bgr_to_cielch(img)

        if self._p_en_lab.value:
            L = lch[:,:,0]
            L_uint8 = np.clip(L * 2.55, 0, 255).astype(np.uint8)
            e_lab = edge_detect(L_uint8, int(self._p_lab_thresh.low), int(self._p_lab_thresh.high))
            e_lab = (e_lab.astype(np.float32) * self._p_lab_weight.value).astype(np.uint8)

        e_chroma = None
        if self._p_en_chroma.value:
            C = lch[:,:,1]
            C_uint8 = np.clip(C * 1.7, 0, 255).astype(np.uint8)
            e_chroma = edge_detect(C_uint8, int(self._p_chroma_thresh.low), int(self._p_chroma_thresh.high))
            e_chroma = (e_chroma.astype(np.float32) * self._p_chroma_weight.value).astype(np.uint8)

        if e_lab is None:
            return self._tint(e_chroma, r_chroma, g_chroma, b_chroma)
        if e_chroma is None:
            return self._tint(e_lab, r_lab, g_lab, b_lab)

        tinted_lab = self._tint(e_lab, r_lab, g_lab, b_lab).astype(np.uint16)
        tinted_chroma = self._tint(e_chroma, r_chroma, g_chroma, b_chroma).astype(np.uint16)
        return (tinted_lab + tinted_chroma).clip(0, 255).astype(np.uint8)


class InvertFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "颜色反转"
    def process(self, img: np.ndarray) -> np.ndarray:
        return invert(img)


class SepiaFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "怀旧棕褐色"
    def process(self, img: np.ndarray) -> np.ndarray:
        return sepia(img)


class MultiplyFilter(ImageFilter):
    """正片叠底：使用指定颜色与图像逐像素相乘，结果始终更暗。"""

    def __init__(self):
        self._params = [
            ColorParam("叠加颜色", "正片叠底使用的颜色，越暗则叠底效果越强", 128, 128, 128),
        ]

    @classmethod
    def name(cls) -> str:
        return "正片叠底"
    def exposed_parameters(self) -> List:
        return self._params
    def process(self, img: np.ndarray) -> np.ndarray:
        r, g, b = self._params[0].value
        result = img.astype(np.uint16)
        result[..., 0] = result[..., 0] * b // 255
        result[..., 1] = result[..., 1] * g // 255
        result[..., 2] = result[..., 2] * r // 255
        return result.astype(np.uint8)


# ============================================================
# 图像转换工具
# ============================================================

class ImageConvert:
    @staticmethod
    def numpy_to_pixmap(img: np.ndarray) -> QPixmap:
        img = np.ascontiguousarray(img)
        if len(img.shape) == 2:
            h, w = img.shape
            qi = QImage(img.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w, ch = img.shape
            qi = QImage(img.data, w, h, ch * w, QImage.Format_BGR888)
        return QPixmap.fromImage(qi)

    @staticmethod
    def pixmap_to_numpy(pm: QPixmap) -> np.ndarray:
        qi = pm.toImage()
        if qi.format() != QImage.Format_ARGB32:
            qi = qi.convertToFormat(QImage.Format_ARGB32)
        ptr = qi.constBits()
        ptr.setsize(qi.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(qi.height(), qi.width(), 4)
        return bgra_to_bgr(arr)


# ============================================================
# _RangeSlider (RangeParam 使用的双滑块控件)
# ============================================================

class _RangeSlider(QWidget):
    """双滑块范围选择器，一个控件展示和交互范围值"""

    rangeChanged = Signal(float, float)
    HANDLE_R = 7

    def __init__(self, param, parent=None):
        super().__init__(parent)
        self._param = param
        self._dragging = -1
        self.setMinimumHeight(28)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def _x_from_val(self, val):
        m = self.HANDLE_R * 2
        w = self.width() - m * 2
        if w <= 0:
            return m
        rng = self._param.absolute_max - self._param.absolute_min
        ratio = (val - self._param.absolute_min) / rng if rng > 0 else 0
        return int(m + ratio * w)

    def _val_from_x(self, x):
        m = self.HANDLE_R * 2
        w = self.width() - m * 2
        if w <= 0:
            return self._param.absolute_min
        ratio = (x - m) / w
        val = self._param.absolute_min + ratio * (self._param.absolute_max - self._param.absolute_min)
        if self._param.step >= 1:
            val = round(val / self._param.step) * self._param.step
        return float(np.clip(val, self._param.absolute_min, self._param.absolute_max))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        yc = h / 2
        lo = self._x_from_val(self._param.low)
        hi = self._x_from_val(self._param.high)
        hr = self.HANDLE_R

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#555"))
        p.drawRoundedRect(hr * 2, yc - 2, w - hr * 4, 4, 2, 2)

        if hi > lo:
            p.setBrush(QColor(0, 120, 215))
            p.drawRoundedRect(lo, yc - 2, hi - lo, 4, 2, 2)

        for cx, active in [(lo, self._dragging == 0), (hi, self._dragging == 1)]:
            color = QColor("#ccc") if active else QColor("#999")
            border = QColor("#666")
            p.setBrush(color)
            p.setPen(QPen(border, 1.2))
            p.drawRoundedRect(cx - hr, yc - hr, hr * 2, hr * 2, 3, 3)

    def mousePressEvent(self, e):
        x = e.position().x()
        lo = self._x_from_val(self._param.low)
        hi = self._x_from_val(self._param.high)
        dlo, dhi = abs(x - lo), abs(x - hi)
        self._dragging = 0 if dlo < dhi else 1
        self._on_drag(x)

    def mouseMoveEvent(self, e):
        if self._dragging >= 0:
            self._on_drag(e.position().x())

    def mouseReleaseEvent(self, e):
        self._dragging = -1
        self.update()

    def _on_drag(self, x):
        val = self._val_from_x(x)
        if self._dragging == 0:
            self._param.low = val
        else:
            self._param.high = val
        self.update()
        self.rangeChanged.emit(self._param.low, self._param.high)
