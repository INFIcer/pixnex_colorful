"""
滤镜库：模块化设计，新增滤镜只需继承 ImageFilter
=============================================
包含：
- 参数类型：FilterParam, RangeParam, BoolParam, ColorParam
- 依赖系统：add_dependency()
- 滤镜基类：ImageFilter (自动注册子类)
- 处理接口：process 为统一调用入口，按存在性检测 process_cpu / process_gpu
  并优先执行 GPU 版本（着色器），否则回退 CPU 版本
- 内置滤镜：灰度、色度、边缘检测、反转、怀旧、正片叠底等
- 工具：ImageConvert, _RangeSlider
"""

import numpy as np
from abc import ABC
from typing import List

from .shader_engine import ShaderEngine, GLSL_COMMON

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
    """滤镜基类。子类自动注册，无需手动添加。

    子类实现 process_cpu（必需）作为 CPU 处理，可选实现 process_gpu
    作为 GPU 处理（着色器实现）。process 为统一调用接口，不应被子类重写。
    """

    @staticmethod
    def all_filters() -> List[type]:
        return ImageFilter.__subclasses__()

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    def process(self, img: np.ndarray) -> np.ndarray:
        """统一处理入口：优先执行 GPU 版本（process_gpu），否则回退 CPU 版本（process_cpu）。"""
        if self.supports_gpu():
            try:
                engine = ShaderEngine.instance()
            except Exception:
                engine = None
            if engine is not None and engine.available():
                try:
                    result = self.process_gpu(img)
                    print(f"[ImageFilter] {type(self).__name__} 使用 GPU 版本处理")
                    return result
                except Exception as ex:
                    print(f"[ImageFilter] {type(self).__name__} GPU 处理失败，回退 CPU: {ex}")
        if self.supports_cpu():
            print(f"[ImageFilter] {type(self).__name__} 使用 CPU 版本处理")
            return self.process_cpu(img)
        raise NotImplementedError(
            f"{type(self).__name__} 未实现 process_cpu 或 process_gpu"
        )

    @classmethod
    def supports_cpu(cls) -> bool:
        """是否存在 CPU 处理方法 process_cpu。"""
        return hasattr(cls, 'process_cpu')

    @classmethod
    def supports_gpu(cls) -> bool:
        """是否存在 GPU 处理方法 process_gpu。"""
        return hasattr(cls, 'process_gpu')

    def exposed_parameters(self) -> List[FilterParam]:
        return []


# ============================================================
# 内置滤镜
# ============================================================

# ---------- 滤镜着色器（GLSL 片段着色器，输入纹理为 RGB 0..1） ----------

_SHADER_RGB_GRAY = GLSL_COMMON + """\
void main() {
    float g = gray_of(v_uv) / 255.0;
    fragColor = vec4(vec3(g), 1.0);
}
"""

_SHADER_LAB_GRAY = GLSL_COMMON + """\
void main() {
    vec3 lab = rgb_to_lab(texture(u_tex, v_uv).rgb);
    float L = clamp(lab.r * 2.55, 0.0, 255.0) / 255.0;
    fragColor = vec4(vec3(L), 1.0);
}
"""

_SHADER_LCH_SATURATION = GLSL_COMMON + """\
void main() {
    vec3 lab = rgb_to_lab(texture(u_tex, v_uv).rgb);
    float C = clamp(sqrt(lab.g * lab.g + lab.b * lab.b) * 1.7, 0.0, 255.0) / 255.0;
    fragColor = vec4(vec3(C), 1.0);
}
"""

_SHADER_HSV_SATURATION = GLSL_COMMON + """\
void main() {
    float s = rgb_to_hsv_s(texture(u_tex, v_uv).rgb);
    fragColor = vec4(vec3(clamp(s * 255.0, 0.0, 255.0) / 255.0), 1.0);
}
"""

_SHADER_HLS_LIGHTNESS = GLSL_COMMON + """\
void main() {
    float l = rgb_to_hls_l(texture(u_tex, v_uv).rgb);
    fragColor = vec4(vec3(clamp(l * 255.0, 0.0, 255.0) / 255.0), 1.0);
}
"""

_SHADER_EDGE_DETECT = GLSL_COMMON + """\
uniform float u_low;
uniform float u_high;
void main() {
    vec2 t = 1.0 / u_resolution;
    vec2 pi = floor(v_uv * u_resolution);
    if (pi.x <= 0.0 || pi.x >= u_resolution.x - 1.0 ||
        pi.y <= 0.0 || pi.y >= u_resolution.y - 1.0) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    float rx = gray_of(v_uv + vec2(t.x, 0.0));
    float lx = gray_of(v_uv - vec2(t.x, 0.0));
    float dy = gray_of(v_uv + vec2(0.0, t.y));
    float uy = gray_of(v_uv - vec2(0.0, t.y));
    float gx = rx - lx;
    float gy = dy - uy;
    float mag = sqrt(gx * gx + gy * gy);
    float v;
    if (mag > u_high) v = 255.0;
    else if (mag > u_low) v = min(mag, 255.0);
    else v = 0.0;
    fragColor = vec4(vec3(v / 255.0), 1.0);
}
"""

_SHADER_INVERT = GLSL_COMMON + """\
void main() {
    fragColor = vec4(vec3(1.0) - texture(u_tex, v_uv).rgb, 1.0);
}
"""

_SHADER_SEPIA = GLSL_COMMON + """\
void main() {
    vec3 c = texture(u_tex, v_uv).rgb;
    vec3 o;
    o.r = 0.189 * c.r + 0.769 * c.g + 0.393 * c.b;
    o.g = 0.168 * c.r + 0.686 * c.g + 0.349 * c.b;
    o.b = 0.131 * c.r + 0.534 * c.g + 0.272 * c.b;
    fragColor = vec4(clamp(o, 0.0, 1.0), 1.0);
}
"""

_SHADER_MULTIPLY = GLSL_COMMON + """\
uniform vec3 u_color;
void main() {
    vec3 c = texture(u_tex, v_uv).rgb;
    fragColor = vec4(c * (u_color / 255.0), 1.0);
}
"""

_SHADER_RATE_OF_CHANGE = GLSL_COMMON + """\
uniform float u_min_freq;
uniform float u_max_freq;
uniform float u_angle;
float sample_freq(vec2 uv, float min_f, float max_f) {
    float g = gray_of(uv);
    return min_f + (g / 255.0) * (max_f - min_f);
}
void main() {
    float theta = radians(u_angle);
    float ct = cos(theta);
    float st = sin(theta);
    vec2 px = v_uv * u_resolution;
    float proj = floor(px.x) * ct + floor(px.y) * st;
    float max_proj = u_resolution.x * abs(ct) + u_resolution.y * abs(st);
    float proj_norm = max_proj > 1e-6 ? proj / max_proj : proj;
    float freq = 0.0;
    vec2 t = 1.0 / u_resolution;
    for (int dy = -2; dy <= 2; dy++) {
        for (int dx = -2; dx <= 2; dx++) {
            vec2 uv = v_uv + vec2(float(dx), float(dy)) * t;
            if (uv.x <= 0.0 || uv.x >= 1.0 || uv.y <= 0.0 || uv.y >= 1.0)
                continue;
            freq += sample_freq(uv, u_min_freq, u_max_freq);
        }
    }
    freq /= 25.0;
    float stripe = sin(6.283185307179586 * freq * proj_norm);
    float v = (stripe + 1.0) * 127.5;
    fragColor = vec4(vec3(clamp(v, 0.0, 255.0) / 255.0), 1.0);
}
"""

_SHADER_DETAIL_ANALYZE = GLSL_COMMON + """\
uniform float u_en_lab;
uniform float u_en_chroma;
uniform float u_lab_low;
uniform float u_lab_high;
uniform float u_chroma_low;
uniform float u_chroma_high;
uniform float u_lab_weight;
uniform float u_chroma_weight;
uniform vec3 u_lab_color;
uniform vec3 u_chroma_color;

vec2 lab_lc(vec2 uv) {
    vec3 lab = rgb_to_lab(texture(u_tex, uv).rgb);
    float L = clamp(lab.r * 2.55, 0.0, 255.0);
    float C = clamp(sqrt(lab.g * lab.g + lab.b * lab.b) * 1.7, 0.0, 255.0);
    return vec2(L, C);
}

float edge_value(float mag, float low, float high) {
    if (mag > high) return 255.0;
    else if (mag > low) return min(mag, 255.0);
    else return 0.0;
}

void main() {
    vec2 t = 1.0 / u_resolution;
    vec2 pi = floor(v_uv * u_resolution);
    bool border = pi.x <= 0.0 || pi.x >= u_resolution.x - 1.0 ||
                  pi.y <= 0.0 || pi.y >= u_resolution.y - 1.0;

    vec2 lc_c = lab_lc(v_uv);
    vec2 lc_r = lab_lc(v_uv + vec2(t.x, 0.0));
    vec2 lc_l = lab_lc(v_uv - vec2(t.x, 0.0));
    vec2 lc_d = lab_lc(v_uv + vec2(0.0, t.y));
    vec2 lc_u = lab_lc(v_uv - vec2(0.0, t.y));

    float gx = lc_r.x - lc_l.x;
    float gy = lc_d.x - lc_u.x;
    float e_lab = border ? 0.0
        : edge_value(sqrt(gx * gx + gy * gy), u_lab_low, u_lab_high) * u_lab_weight;

    gx = lc_r.y - lc_l.y;
    gy = lc_d.y - lc_u.y;
    float e_chroma = border ? 0.0
        : edge_value(sqrt(gx * gx + gy * gy), u_chroma_low, u_chroma_high) * u_chroma_weight;

    vec3 lab_rgb = u_lab_color / 255.0;
    vec3 chroma_rgb = u_chroma_color / 255.0;
    vec3 acc = vec3(0.0);
    if (u_en_lab > 0.5)
        acc += (e_lab / 255.0) * lab_rgb;
    if (u_en_chroma > 0.5)
        acc += (e_chroma / 255.0) * chroma_rgb;
    fragColor = vec4(clamp(acc, 0.0, 1.0), 1.0);
}
"""


class LabGrayFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "Lab灰度"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        lch = bgr_to_cielch(img)
        L = lch[:,:,0]
        return np.clip(L * 2.55, 0, 255).astype(np.uint8)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_LAB_GRAY, img, gray=True)

class LCHSaturationFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "LCH色度"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        lch = bgr_to_cielch(img)
        C = lch[:,:,1]
        return np.clip(C * 1.7, 0, 255).astype(np.uint8)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_LCH_SATURATION, img, gray=True)


class RGBGrayFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "RGB灰度"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        return bgr_to_gray(img)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_RGB_GRAY, img, gray=True)


class HSVSaturationFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "HSV饱和度"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        return (bgr_hsv_s_channel(img) * 255).astype(np.uint8)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_HSV_SATURATION, img, gray=True)


class HLSLightnessFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "HLS亮度"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        return (bgr_hls_l_channel(img) * 255).astype(np.uint8)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_HLS_LIGHTNESS, img, gray=True)


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
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        p = self._params[0]
        return edge_detect(bgr_to_gray(img), int(p.low), int(p.high))
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        p = self._params[0]
        return ShaderEngine.instance().apply(_SHADER_EDGE_DETECT, img, {
            "u_low": float(p.low),
            "u_high": float(p.high),
        }, gray=True)


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

    def process_cpu(self, img: np.ndarray) -> np.ndarray:
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

    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        if not self._p_en_lab.value and not self._p_en_chroma.value:
            return np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
        r_lab, g_lab, b_lab = self._p_lab_color.value
        r_chroma, g_chroma, b_chroma = self._p_chroma_color.value
        return ShaderEngine.instance().apply(_SHADER_DETAIL_ANALYZE, img, {
            "u_en_lab": 1.0 if self._p_en_lab.value else 0.0,
            "u_en_chroma": 1.0 if self._p_en_chroma.value else 0.0,
            "u_lab_low": float(self._p_lab_thresh.low),
            "u_lab_high": float(self._p_lab_thresh.high),
            "u_chroma_low": float(self._p_chroma_thresh.low),
            "u_chroma_high": float(self._p_chroma_thresh.high),
            "u_lab_weight": float(self._p_lab_weight.value),
            "u_chroma_weight": float(self._p_chroma_weight.value),
            "u_lab_color": (float(r_lab), float(g_lab), float(b_lab)),
            "u_chroma_color": (float(r_chroma), float(g_chroma), float(b_chroma)),
        })


class InvertFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "颜色反转"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        return invert(img)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_INVERT, img)


class SepiaFilter(ImageFilter):
    @classmethod
    def name(cls) -> str:
        return "怀旧棕褐色"
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        return sepia(img)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        return ShaderEngine.instance().apply(_SHADER_SEPIA, img)


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
    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        r, g, b = self._params[0].value
        result = img.astype(np.uint16)
        result[..., 0] = result[..., 0] * b // 255
        result[..., 1] = result[..., 1] * g // 255
        result[..., 2] = result[..., 2] * r // 255
        return result.astype(np.uint8)
    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        r, g, b = self._params[0].value
        return ShaderEngine.instance().apply(_SHADER_MULTIPLY, img, {
            "u_color": (float(r), float(g), float(b)),
        })


class RateOfChangeFilter(ImageFilter):
    def __init__(self):
        self._params = [
            RangeParam("频率范围", "灰度黑到白对应的条纹周期数范围", 0, 50, 1.0, 8.0, 0.1),
            FilterParam("方向(°)", "条纹延伸角度，0°为水平方向", 0, 360, 0, 1),
            BoolParam("反转", "反转频率映射：黑→最大频率，白→最小频率", False),
            FilterParam("相位(°)", "条纹相位偏移", 0, 360, 0, 1),
        ]

    @classmethod
    def name(cls) -> str:
        return "频率变化率"

    def exposed_parameters(self):
        return self._params

    def process_cpu(self, img: np.ndarray) -> np.ndarray:
        gray = bgr_to_gray(img)
        h, w = gray.shape

        min_freq = self._params[0].low
        max_freq = self._params[0].high
        angle = self._params[1].value

        theta = np.radians(angle)
        cos_t, sin_t = np.cos(theta), np.sin(theta)

        y_idx = np.arange(h, dtype=np.float32)
        x_idx = np.arange(w, dtype=np.float32)
        y_grid, x_grid = np.meshgrid(y_idx, x_idx, indexing='ij')

        proj = x_grid * cos_t + y_grid * sin_t
        max_proj = w * abs(cos_t) + h * abs(sin_t)
        proj_norm = proj / max_proj if max_proj > 0 else proj

        phase = np.radians(self._params[3].value)

        gray_f = gray.astype(np.float32) / 255.0
        if self._params[2].value:
            gray_f = 1.0 - gray_f
        freq = min_freq + gray_f * (max_freq - min_freq)

        box_r = 2
        kernel = np.ones(box_r * 2 + 1, dtype=np.float32) / (box_r * 2 + 1)
        for i in range(h):
            freq[i, :] = np.convolve(freq[i, :], kernel, mode='same')
        for j in range(w):
            freq[:, j] = np.convolve(freq[:, j], kernel, mode='same')

        stripe = np.sin(2 * np.pi * freq * proj_norm + phase)
        return ((stripe + 1) * 127.5).clip(0, 255).astype(np.uint8)

    def process_gpu(self, img: np.ndarray) -> np.ndarray:
        min_freq = self._params[0].low
        max_freq = self._params[0].high
        angle = self._params[1].value
        return ShaderEngine.instance().apply(_SHADER_RATE_OF_CHANGE, img, {
            "u_min_freq": float(min_freq),
            "u_max_freq": float(max_freq),
            "u_angle": float(angle),
        }, gray=True)


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
        if hasattr(ptr, 'setsize'):
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
