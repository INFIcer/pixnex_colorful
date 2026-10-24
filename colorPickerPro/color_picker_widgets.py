import numpy as np
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QApplication, QWidget, QDoubleSpinBox, QSizePolicy
from PySide6.QtCore import QRectF, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QPainter, QConicalGradient, QPen, QPixmap, QImage
)

from .ui.components import (
    ColorSwatch,
    FieldLabel,
    MonoLabel,
    PrimaryButton,
    SecondaryButton,
    StatusLabel,
    ValueLabel,
    flow,
    hbox,
    vbox,
)
from .ui.tokens import SPACE, State, qcolor

from .colorMath import (
    srgb_gamma_inv, linear_to_srgb_clamped,
    _M1, _M1_inv, _M2, _M2_inv, OKLCH_C_MAX,
    oklch_from_lab, oklch_to_lab_vec,
    hsv_to_srgb, srgb_to_hsv,
    cielab_to_linrgb, linrgb_to_cielab,
    cielch_to_lab_vec, cielch_from_lab, CIE_LCH_C_MAX,
    hsi_to_srgb, srgb_to_hsi,
)

# =============================================================================
# 辅助工具
# =============================================================================
def make_argb_image(w, h, r_arr, g_arr, b_arr, mask):
    r = np.clip(r_arr, 0, 255).astype(np.uint32)
    g = np.clip(g_arr, 0, 255).astype(np.uint32)
    b = np.clip(b_arr, 0, 255).astype(np.uint32)
    if mask is not None:
        r[~mask] = 0; g[~mask] = 0; b[~mask] = 0
    argb = (0xFF << 24) | (r << 16) | (g << 8) | b
    argb_img = argb.astype(np.uint32).reshape(h, w)
    return QImage(argb_img.tobytes(), w, h, QImage.Format_ARGB32).copy()


# =============================================================================
# 颜色模型抽象基类 + 具体实现
# =============================================================================
class BaseColorModel(ABC):
    def __init__(self):
        self._params = np.zeros(3, dtype=float)
        self._listeners = []

    @property
    @abstractmethod
    def name(self) -> str: ...
    @property
    @abstractmethod
    def param_names(self) -> list: ...
    @property
    @abstractmethod
    def param_ranges(self) -> list: ...
    @property
    @abstractmethod
    def param_decimals(self) -> list: ...
    @property
    @abstractmethod
    def param_steps(self) -> list: ...
    @abstractmethod
    def _params_to_srgb(self, params) -> tuple: ...
    @abstractmethod
    def _srgb_to_params(self, r, g, b) -> np.ndarray: ...

    @property
    def has_hue(self) -> bool: return False
    @property
    def hue_index(self) -> int: return -1
    @property
    def square_x_index(self) -> int: return -1
    @property
    def square_y_index(self) -> int: return -1
    @property
    def strip_index(self) -> int: return -1

    def set_params(self, p0, p1, p2, source=None):
        ranges = self.param_ranges
        vals = [p0, p1, p2]
        for i in range(3):
            lo, hi = ranges[i]
            val = vals[i]
            if self.has_hue and i == self.hue_index:
                val = val % hi
            self._params[i] = np.clip(val, lo, hi)
        self._notify(source)

    def get_params(self) -> np.ndarray:
        return self._params.copy()

    def _to_srgb_1d(self, p_1d):
        srgb_2d, mask_2d = self._params_to_srgb(p_1d.reshape(1, 3))
        return srgb_2d.reshape(-1), bool(mask_2d.reshape(-1)[0])

    def to_qcolor(self) -> QColor:
        srgb, _ = self._to_srgb_1d(self._params)
        return QColor.fromRgbF(
            float(np.clip(srgb[0], 0, 1)),
            float(np.clip(srgb[1], 0, 1)),
            float(np.clip(srgb[2], 0, 1)),
        )

    def is_in_gamut(self) -> bool:
        _, ok = self._to_srgb_1d(self._params)
        return ok

    def to_srgb_tuple(self) -> tuple:
        srgb, _ = self._to_srgb_1d(self._params)
        return (float(np.clip(srgb[0], 0, 1)),
                float(np.clip(srgb[1], 0, 1)),
                float(np.clip(srgb[2], 0, 1)))

    def format_srgb(self, r: float, g: float, b: float) -> str:
        """把 sRGB (0-1) 格式化成当前模型样式的文本，如 ``L-0.61 C-0.25 H-321.7``。

        只做数值换算，不修改模型自身参数、也不触发监听器（供屏幕滤镜窗口的
        取色提示等「只读展示」场景使用）。参数精度与滑块输入框保持一致。
        """
        params = np.asarray(
            self._srgb_to_params(r, g, b), dtype=float).reshape(-1)
        parts = []
        for name, value, decimals in zip(
                self.param_names, params, self.param_decimals):
            number = float(value) if np.isfinite(value) else 0.0
            parts.append(f"{name}-{number:.{int(decimals)}f}")
        return " ".join(parts)

    def set_from_srgb(self, r, g, b):
        r = round(r * 255) / 255.0
        g = round(g * 255) / 255.0
        b = round(b * 255) / 255.0
        self._params = self._srgb_to_params(r, g, b)
        self._notify()

    def constrain_to_gamut(self):
        r, g, b = self.to_srgb_tuple()
        self._params = self._srgb_to_params(r, g, b)
        self._notify()

    def add_listener(self, callback):
        self._listeners.append(callback)

    def remove_listener(self, callback) -> bool:
        """摘除一个监听回调；回调不在列表里时安全返回 False。"""
        try:
            self._listeners.remove(callback)
            return True
        except ValueError:
            return False

    def _notify(self, source=None):
        for cb in self._listeners:
            cb(self, source)


class OKLCHModel(BaseColorModel):
    name = "OKLCH"
    param_names = ["L", "C", "H"]
    param_ranges = [(0, 1), (0, OKLCH_C_MAX), (0, 360)]
    param_decimals = [3, 3, 1]
    param_steps = [0.01, 0.005, 1.0]
    has_hue = True; hue_index = 2
    square_x_index = 1; square_y_index = 0

    def __init__(self):
        super().__init__()
        self._params = np.array([0.5, 0.15, 0.0])

    def _params_to_srgb(self, p):
        L, C, H = p[:, 0], p[:, 1], p[:, 2]
        lab = oklch_to_lab_vec(L, C, H)
        rgb_lin = (lab @ _M2_inv.T) ** 3 @ _M1_inv.T
        return linear_to_srgb_clamped(rgb_lin)

    def _srgb_to_params(self, r, g, b):
        rgb = np.array([r, g, b])
        lms = srgb_gamma_inv(rgb) @ _M1.T
        lab = np.cbrt(lms) @ _M2.T
        return oklch_from_lab(lab)


class HSVModel(BaseColorModel):
    name = "HSV"
    param_names = ["H", "S", "V"]
    param_ranges = [(0, 360), (0, 1), (0, 1)]
    param_decimals = [1, 3, 3]
    param_steps = [1.0, 0.01, 0.01]
    has_hue = True; hue_index = 0
    square_x_index = 1; square_y_index = 2

    def __init__(self):
        super().__init__()
        self._params = np.array([0.0, 1.0, 1.0])

    def _params_to_srgb(self, p):
        rgb = hsv_to_srgb(p)
        mask = np.all((rgb >= -1e-9) & (rgb <= 1 + 1e-9), axis=-1)
        return np.clip(rgb, 0, 1), mask

    def _srgb_to_params(self, r, g, b):
        return srgb_to_hsv(np.array([r, g, b])).flatten()


class CIELCHModel(BaseColorModel):
    name = "CIE LCH"
    param_names = ["L", "C", "H"]
    param_ranges = [(0, 100), (0, CIE_LCH_C_MAX), (0, 360)]
    param_decimals = [1, 1, 1]
    param_steps = [0.5, 0.5, 1.0]
    has_hue = True; hue_index = 2
    square_x_index = 1; square_y_index = 0

    def __init__(self):
        super().__init__()
        self._params = np.array([50.0, 50.0, 0.0])

    def _params_to_srgb(self, p):
        lab = cielch_to_lab_vec(p[:, 0], p[:, 1], p[:, 2])
        return linear_to_srgb_clamped(cielab_to_linrgb(lab))

    def _srgb_to_params(self, r, g, b):
        rgb_lin = srgb_gamma_inv(np.array([r, g, b]))
        lab = linrgb_to_cielab(rgb_lin.reshape(1, 3))
        return cielch_from_lab(lab.flatten())


class CIELabModel(BaseColorModel):
    name = "CIE Lab"
    param_names = ["L", "a", "b"]
    param_ranges = [(0, 100), (-128, 127), (-128, 127)]
    param_decimals = [1, 1, 1]
    param_steps = [0.5, 1.0, 1.0]
    has_hue = False
    square_x_index = 1; square_y_index = 2
    strip_index = 0

    def __init__(self):
        super().__init__()
        self._params = np.array([50.0, 0.0, 0.0])

    def _params_to_srgb(self, p):
        return linear_to_srgb_clamped(cielab_to_linrgb(p))

    def _srgb_to_params(self, r, g, b):
        rgb_lin = srgb_gamma_inv(np.array([r, g, b]))
        return linrgb_to_cielab(rgb_lin.reshape(1, 3)).flatten()


class HSIModel(BaseColorModel):
    name = "HSI"
    param_names = ["H", "S", "I"]
    param_ranges = [(0, 360), (0, 1), (0, 1)]
    param_decimals = [1, 3, 3]
    param_steps = [1.0, 0.01, 0.01]
    has_hue = True; hue_index = 0
    square_x_index = 1; square_y_index = 2

    def __init__(self):
        super().__init__()
        self._params = np.array([0.0, 1.0, 0.333])

    def _params_to_srgb(self, p):
        return hsi_to_srgb(p)

    def _srgb_to_params(self, r, g, b):
        return srgb_to_hsi(np.array([r, g, b])).flatten()


ALL_MODELS = {
    "OKLCH": OKLCHModel,
    "CIE LCH": CIELCHModel, "CIE Lab": CIELabModel,
    "HSV": HSVModel, "HSI": HSIModel,
}


# =============================================================================
# 表现层尺寸常量
# =============================================================================
# 渐变色条是「数据即颜色」的小型可视化控件，固定高度属于设计规范 §3.3 的例外。
STRIP_HEIGHT = 24
STRIP_MIN_WIDTH = 60
# 数值输入框本身就是小尺寸控件，保留较小的固定宽度（设计规范 §5.4）。
# 96px 足够容纳最长数值（如 CIE Lab 的 -128.0）且不会裁切文字。
SPIN_WIDTH = 96
# 参数名标签只给最小宽度，绝不定死宽度，窄窗口时才不会被裁切。
LABEL_MIN_WIDTH = 24


# =============================================================================
# PreviewStrip
# =============================================================================
class PreviewStrip(QWidget):
    """一维渐变色条 + 当前位置标记（点击/拖拽发出归一化位置）。"""

    posChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batch_builder = None
        self._current_pos = 0.0
        self._cache = None
        self._cache_width = -1
        self._cache_height = -1
        self._dragging = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumSize(STRIP_MIN_WIDTH, STRIP_HEIGHT)
        self.setMaximumHeight(STRIP_HEIGHT)

    def sizeHint(self):
        return QSize(180, STRIP_HEIGHT)

    def minimumSizeHint(self):
        return QSize(STRIP_MIN_WIDTH, STRIP_HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def set_batch_builder(self, builder):
        self._batch_builder = builder
        self._cache = None
        self.update()

    def set_current_pos(self, pos: float):
        self._current_pos = np.clip(pos, 0.0, 1.0)
        self.update()

    def refresh(self):
        self._cache = None
        self.update()

    def paintEvent(self, event):
        if self._batch_builder is None:
            return
        painter = QPainter(self)
        w, h = self.width(), self.height()
        if (self._cache is None or self._cache_width != w
                or self._cache_height != h):
            self._cache = self._batch_builder(w, h)
            self._cache_width = w
            self._cache_height = h
        painter.drawPixmap(0, 0, self._cache)
        if self._current_pos >= 0:
            x = int(self._current_pos * (w - 1))
            # 位置标记叠在任意渐变之上，黑白双线保证对比度，不跟随主题色。
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(x, 0, x, h)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawLine(x + 1, 0, x + 1, h)

    def _pos_from_event(self, e):
        w = self.width()
        return np.clip(e.position().x() / w if w > 0 else 0, 0.0, 1.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self.grabMouse()
            p = self._pos_from_event(e)
            self._current_pos = p
            self.update()
            self.posChanged.emit(p)

    def mouseMoveEvent(self, e):
        if self._dragging:
            p = self._pos_from_event(e)
            self._current_pos = p
            self.update()
            self.posChanged.emit(p)

    def mouseReleaseEvent(self, e):
        if self._dragging and e.button() == Qt.LeftButton:
            self._dragging = False
            self.releaseMouse()
            p = self._pos_from_event(e)
            self._current_pos = p
            self.update()
            self.posChanged.emit(p)


# =============================================================================
# ColorSlider
# =============================================================================
class ColorSlider(QWidget):
    """参数滑块行：参数名 + 渐变色条 + 数值输入框。"""

    valueChanged = Signal(float)

    def __init__(self, label, vmin, vmax, default, decimals=3, step=0.001, parent=None):
        super().__init__(parent)
        self._vmin, self._vmax, self._vrange = vmin, vmax, vmax - vmin
        self._decimals = decimals
        self._step = step
        self._batch_builder = None
        self._fixed_idx = 0
        self._block = False

        self._label = FieldLabel(str(label))
        self._label.setMinimumWidth(LABEL_MIN_WIDTH)
        self._label.setAlignment(Qt.AlignCenter)

        self._preview = PreviewStrip(self)
        self._preview.setCursor(Qt.PointingHandCursor)
        self._preview.posChanged.connect(self._on_preview)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(vmin, vmax)
        self._spin.setDecimals(decimals)
        self._spin.setSingleStep(step)
        self._spin.setValue(default)
        self._spin.setFixedWidth(SPIN_WIDTH)
        self._spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._spin.valueChanged.connect(self._on_spin)

        layout = hbox(self._label, self._preview, self._spin,
                      spacing=SPACE.sm, stretch=1)
        self.setLayout(layout)

    def set_batch_builder(self, builder, fixed_idx=0):
        self._batch_builder = builder
        self._fixed_idx = fixed_idx
        self._preview.set_batch_builder(builder)

    def set_value(self, v, block=False):
        v = np.clip(v, self._vmin, self._vmax)
        self._block = block
        self._spin.setValue(v)
        self._block = False
        self._preview.set_current_pos((v - self._vmin) / self._vrange)

    def value(self):
        return self._spin.value()

    def refresh_gradient(self):
        self._preview.refresh()
        self._preview.set_current_pos((self.value() - self._vmin) / self._vrange)

    def _on_preview(self, norm_pos):
        v = self._vmin + norm_pos * self._vrange
        self._spin.blockSignals(True)
        self._spin.setValue(v)
        self._spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _on_spin(self, v):
        if self._block:
            return
        self._preview.set_current_pos((v - self._vmin) / self._vrange)
        self.valueChanged.emit(v)


# =============================================================================
# GraphicalPicker
# =============================================================================
class GraphicalPicker(QWidget):
    """圆环（色相）+ 方块（二维色度）+ 可选侧边条 的图形取色器。

    尺寸交给布局决定：高度由构造参数 *size* 固定（设计规范 §5.1 允许的例外，
    主窗口约 260、对话框约 220，最小 180），宽度随容器变化。绘制时始终以
    ``min(宽, 高)`` 计算圆环与方块并居中，因此窗口缩放时不会顶出布局。
    """

    colorChanged = Signal(object)

    MIN_RENDER_HEIGHT = 180
    # 绘制留白：保证方块边缘的圆点标记不被裁切。
    RENDER_PADDING = SPACE.sm
    # 绘制比例与原实现一致：内环 = 0.70 外环，方块边长 = 1.30 倍内环。
    _RING_INNER_RATIO = 0.70
    _SQUARE_TO_INNER = 1.30

    def __init__(self, model: BaseColorModel, size=240, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._has_side_strip = model.strip_index >= 0 and not model.has_hue
        self._preferred_height = max(int(size), self.MIN_RENDER_HEIGHT)

        # 只固定高度，宽度 Expanding（设计规范 §5.1）。
        self.setFixedHeight(self._preferred_height)
        self.setMinimumWidth(self.MIN_RENDER_HEIGHT // 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._metrics_size = QSize(-1, -1)
        self._active_region = None
        self._cache_ring = None
        self._cache_sq = None
        self._cache_sq_hue = -999.0
        self._cache_strip = None
        self._strip_qrect = QRectF()
        self._update_metrics()
        self.setMouseTracking(True)

    # -- 尺寸 ------------------------------------------------------------
    def sizeHint(self):
        return QSize(self._preferred_height, self._preferred_height)

    def minimumSizeHint(self):
        return QSize(self.MIN_RENDER_HEIGHT // 2, self._preferred_height)

    def _update_metrics(self):
        """按当前控件尺寸重算圆环/方块/色条几何，绘制与命中共用同一份数据。"""
        w = max(1, self.width())
        h = max(1, self.height())
        pad = self.RENDER_PADDING
        avail_w = max(1.0, w - 2 * pad)
        avail_h = max(1.0, h - 2 * pad)
        self._metrics_size = QSize(w, h)
        self._strip_gap = float(SPACE.sm)
        self._cx = w / 2.0
        self._cy = h / 2.0
        self._ring_outer_r = 0.0
        self._ring_inner_r = 0.0
        self._strip_width = 0
        self._square_size = 16
        self._strip_qrect = QRectF()

        if self._has_side_strip:
            self._strip_width = max(10, int(min(avail_w, avail_h) * 0.08))
            avail_for_square = avail_w - self._strip_width - self._strip_gap
            self._square_size = max(16, int(min(avail_h, avail_for_square)))
            total_w = self._square_size + self._strip_width + self._strip_gap
            left = pad + (avail_w - total_w) / 2.0
            top = pad + (avail_h - self._square_size) / 2.0
            self._cx = left + self._square_size / 2.0
            self._cy = top + self._square_size / 2.0
            self._strip_qrect = QRectF(
                left + self._square_size + self._strip_gap, top,
                float(self._strip_width), float(self._square_size))
            return

        ref = min(avail_w, avail_h)
        if self._model.has_hue:
            self._ring_outer_r = ref / 2.0
            self._ring_inner_r = self._ring_outer_r * self._RING_INNER_RATIO
            self._square_size = max(
                16, int(self._ring_inner_r * self._SQUARE_TO_INNER))
        else:
            self._square_size = max(16, int(ref * 0.92))

    def _ensure_metrics(self):
        if self._metrics_size != self.size():
            self._update_metrics()
            self._invalidate_caches()

    def _invalidate_caches(self):
        self._cache_ring = None
        self._cache_sq = None
        self._cache_sq_hue = -999.0
        self._cache_strip = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_metrics()
        self._invalidate_caches()
        self.update()

    # -- 模型切换 --------------------------------------------------------
    def set_model(self, model: BaseColorModel):
        """换模型：摘旧监听 → 重绑 → 重算几何并失效缓存 → 重绘。"""
        if model is self._model:
            self._invalidate_caches()
            self.update()
            return
        self._model.remove_listener(self._on_model_changed)
        self._model = model
        model.add_listener(self._on_model_changed)
        self._has_side_strip = model.strip_index >= 0 and not model.has_hue
        self._update_metrics()
        self._invalidate_caches()
        self.update()

    # -- 几何 ------------------------------------------------------------
    def _square_rect(self):
        hs = self._square_size / 2.0
        return (self._cx, self._cy,
                self._cx - hs, self._cy - hs,
                self._cx + hs, self._cy + hs)

    def _strip_rect(self):
        rect = self._strip_qrect
        return rect.x(), rect.y(), rect.width(), rect.height()

    def _strip_val_from_pos(self, p, sy, sh):
        rng = self._model.param_ranges
        si = self._model.strip_index
        ny = 1 - (p - sy) / sh
        return np.clip(rng[si][0] + ny * (rng[si][1] - rng[si][0]), rng[si][0], rng[si][1])

    def _strip_pos_from_val(self, v, sy, sh):
        rng = self._model.param_ranges
        si = self._model.strip_index
        ny = (v - rng[si][0]) / (rng[si][1] - rng[si][0])
        return sy + (1 - ny) * sh

    # -- 绘制 ------------------------------------------------------------
    def paintEvent(self, event):
        self._ensure_metrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        cx, cy, _, _, _, _ = self._square_rect()

        if self._model.has_hue:
            self._draw_ring(painter)
        self._draw_square(painter, cx, cy)
        if self._model.strip_index >= 0:
            self._draw_strip(painter)
        self._draw_markers(painter, cx, cy)

    def _draw_markers(self, painter, cx, cy):
        model = self._model
        p = model.get_params()

        if model.has_hue and self._ring_outer_r > 0:
            hi = model.hue_index
            angle_rad = np.radians(p[hi] - 90)
            r1, r2 = self._ring_inner_r, self._ring_outer_r
            # 标记画在任意颜色之上，黑白双线保证对比度，不跟随主题色。
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(
                QPointF(cx + r1 * np.cos(angle_rad), cy + r1 * np.sin(angle_rad)),
                QPointF(cx + r2 * np.cos(angle_rad), cy + r2 * np.sin(angle_rad)))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawLine(
                QPointF(cx + r1 * np.cos(angle_rad) + 2,
                        cy + r1 * np.sin(angle_rad) + 2),
                QPointF(cx + r2 * np.cos(angle_rad) + 2,
                        cy + r2 * np.sin(angle_rad) + 2))

        xi, yi = model.square_x_index, model.square_y_index
        if xi >= 0 and yi >= 0:
            rng = model.param_ranges
            nx = (p[xi] - rng[xi][0]) / (rng[xi][1] - rng[xi][0])
            ny = 1 - (p[yi] - rng[yi][0]) / (rng[yi][1] - rng[yi][0])
            hs = self._square_size / 2.0
            dx = cx - hs + nx * self._square_size
            dy = cy - hs + ny * self._square_size
            painter.setPen(QPen(Qt.white, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(dx, dy), 6, 6)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(QPointF(dx, dy), 7, 7)

        si = model.strip_index
        if si >= 0 and self._cache_strip is not None:
            sx, sy, sw, sh = self._strip_rect()
            vy = self._strip_pos_from_val(p[si], sy, sh)
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(int(sx), int(vy), int(sx + sw), int(vy))
            if self._has_side_strip:
                painter.setPen(QPen(Qt.black, 1))
                painter.drawLine(int(sx), int(vy + 1), int(sx + sw), int(vy + 1))

    def _build_ring_colors(self, n=180):
        p = self._model.get_params()
        hi = self._model.hue_index
        h_vals = np.linspace(0, 360, n, endpoint=False)
        ps = np.tile(p, (n, 1))
        ps[:, hi] = h_vals
        srgb, mask = self._model._params_to_srgb(ps)
        colors = []
        for i in range(n):
            if mask[i]:
                colors.append(QColor.fromRgbF(float(srgb[i, 0]), float(srgb[i, 1]), float(srgb[i, 2])))
            else:
                colors.append(QColor(0, 0, 0))
        return colors

    def _build_ring_pixmap(self):
        outer = self._ring_outer_r
        if outer <= 1.0:
            return
        size = max(2, int(round(outer * 2.0)))
        r_out = size / 2.0
        r_in = self._ring_inner_r * (r_out / outer)
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        center = QPointF(r_out, r_out)
        grad = QConicalGradient(center, 90)
        colors = self._build_ring_colors(180)
        for i, c in enumerate(colors):
            grad.setColorAt(1.0 - i / len(colors), c)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPie(QRectF(center.x() - r_out, center.y() - r_out,
                         r_out * 2.0, r_out * 2.0), 0, 360 * 16)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(center, r_in, r_in)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(QPen(qcolor("border_strong"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, r_in, r_in)
        p.end()
        self._cache_ring = pm

    def _draw_ring(self, painter):
        if self._ring_outer_r <= 1.0:
            return
        size = max(2, int(round(self._ring_outer_r * 2.0)))
        if self._cache_ring is None or self._cache_ring.width() != size:
            self._build_ring_pixmap()
        if self._cache_ring is None:
            return
        x = int(round(self._cx - self._cache_ring.width() / 2.0))
        y = int(round(self._cy - self._cache_ring.height() / 2.0))
        painter.drawPixmap(x, y, self._cache_ring)

    def _build_square_image(self):
        sq = self._square_size
        p = self._model.get_params()
        xi, yi = self._model.square_x_index, self._model.square_y_index
        rng = self._model.param_ranges
        ps = np.tile(p, (sq * sq, 1))
        xv = np.arange(sq) / sq
        yv = 1 - np.arange(sq) / sq
        xx, yy = np.meshgrid(xv, yv)
        ps[:, xi] = rng[xi][0] + xx.flatten() * (rng[xi][1] - rng[xi][0])
        ps[:, yi] = rng[yi][0] + yy.flatten() * (rng[yi][1] - rng[yi][0])
        srgb, mask = self._model._params_to_srgb(ps)
        self._cache_sq = QPixmap.fromImage(
            make_argb_image(sq, sq, srgb[:, 0]*255, srgb[:, 1]*255, srgb[:, 2]*255, mask)
        )
        if self._model.has_hue:
            self._cache_sq_hue = p[self._model.hue_index]

    def _draw_square(self, painter, cx, cy):
        p = self._model.get_params()
        rebuild = (self._cache_sq is None
                   or self._cache_sq.width() != self._square_size)
        if self._model.has_hue and not rebuild:
            hi = self._model.hue_index
            rebuild = abs(self._cache_sq_hue - p[hi]) > 0.5
        if rebuild:
            self._build_square_image()
        hs = self._square_size / 2.0
        painter.drawPixmap(int(round(cx - hs)), int(round(cy - hs)), self._cache_sq)

    def _build_strip(self):
        sx, sy, sw, sh = self._strip_rect()
        sw, sh = int(round(sw)), int(round(sh))
        if sw <= 0 or sh <= 0:
            return
        n = sh
        si = self._model.strip_index
        rng = self._model.param_ranges
        p = self._model.get_params()
        ps = np.tile(p, (n, 1))
        ys = np.linspace(1, 0, n)
        ps[:, si] = rng[si][0] + ys * (rng[si][1] - rng[si][0])
        srgb, mask = self._model._params_to_srgb(ps)
        r = np.tile(srgb[:, 0:1], (1, sw)).flatten() * 255
        g = np.tile(srgb[:, 1:2], (1, sw)).flatten() * 255
        b = np.tile(srgb[:, 2:3], (1, sw)).flatten() * 255
        m = np.tile(mask.reshape(-1, 1), (1, sw)).flatten()
        self._cache_strip = QPixmap.fromImage(
            make_argb_image(sw, sh, r, g, b, m)
        )

    def _draw_strip(self, painter):
        if not self._has_side_strip:
            return
        sh = int(round(self._strip_qrect.height()))
        if self._cache_strip is None or self._cache_strip.height() != sh:
            self._build_strip()
        if self._cache_strip is None:
            return
        sx, sy, _, _ = self._strip_rect()
        painter.drawPixmap(int(round(sx)), int(round(sy)), self._cache_strip)

    # -- 交互 ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._ensure_metrics()
            region = self._hit_test(event.position())
            if region is not None:
                self._active_region = region
                self.grabMouse()
                self._process_mouse_region(region, event.position())

    def mouseMoveEvent(self, event):
        if self._active_region is not None:
            self._process_mouse_region(self._active_region, event.position())

    def mouseReleaseEvent(self, event):
        if self._active_region is not None:
            self._active_region = None
            self.releaseMouse()

    def _hit_test(self, pos):
        if self._model.has_hue and self._ring_outer_r > 0:
            dx, dy = pos.x() - self._cx, pos.y() - self._cy
            dist = np.hypot(dx, dy)
            if self._ring_inner_r <= dist <= self._ring_outer_r:
                return 'ring'
        si = self._model.strip_index
        if si >= 0 and self._has_side_strip:
            sx, sy, sw, sh = self._strip_rect()
            if sx <= pos.x() <= sx + sw and sy <= pos.y() <= sy + sh:
                return 'strip'
        xi, yi = self._model.square_x_index, self._model.square_y_index
        if xi >= 0 and yi >= 0:
            _, _, l, t, r_, b = self._square_rect()
            if l <= pos.x() <= r_ and t <= pos.y() <= b:
                return 'square'
        return None

    def _process_mouse_region(self, region, pos):
        p = self._model.get_params()
        rng = self._model.param_ranges

        if region == 'ring':
            dx, dy = pos.x() - self._cx, pos.y() - self._cy
            angle = np.degrees(np.arctan2(dy, dx)) + 90
            new_h = angle % 360
            p[self._model.hue_index] = new_h
            self._model.set_params(p[0], p[1], p[2])
            self.colorChanged.emit(self._model)
            self._cache_sq = None
            self._cache_ring = None
            self.update()
            return

        if region == 'square':
            xi, yi = self._model.square_x_index, self._model.square_y_index
            _, _, l, t, r_, b = self._square_rect()
            nx = np.clip((pos.x() - l) / self._square_size, 0, 1)
            ny = np.clip(1 - (pos.y() - t) / self._square_size, 0, 1)
            p[xi] = rng[xi][0] + nx * (rng[xi][1] - rng[xi][0])
            p[yi] = rng[yi][0] + ny * (rng[yi][1] - rng[yi][0])
            self._model.set_params(p[0], p[1], p[2])
            self.colorChanged.emit(self._model)
            self._cache_ring = None
            self.update()
            return

        if region == 'strip':
            si = self._model.strip_index
            sx, sy, sw, sh = self._strip_rect()
            val = self._strip_val_from_pos(
                np.clip(pos.y(), sy, sy + sh), sy, sh)
            p[si] = val
            self._model.set_params(p[0], p[1], p[2])
            self.colorChanged.emit(self._model)
            self._cache_sq = None
            self.update()

    def _on_model_changed(self, model, source):
        if source is self:
            return
        self._invalidate_caches()
        self.update()


# =============================================================================
# ColorInfoPanel
# =============================================================================
class ColorInfoPanel(QWidget):
    """颜色信息面板：色块预览、色域状态、RGB/HEX 数值与两个操作按钮。"""

    pickStart = Signal()
    constrainRequested = Signal()

    COPY_TEXT = "复制 HEX"
    COPIED_TEXT = "已复制"
    COPY_FEEDBACK_MS = 1200

    def __init__(self, model: BaseColorModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._init_ui()
        self._sync_display()

    def _init_ui(self):
        layout = vbox(spacing=SPACE.sm)
        self.setLayout(layout)

        self._swatch = ColorSwatch(self._model.to_qcolor())
        layout.addWidget(self._swatch)

        self._gamut_label = StatusLabel("", State.SUCCESS)
        self._gamut_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 状态文字很短：显式使用 Preferred 宽策略，避免在窄面板里被压成 0 宽。
        self._gamut_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._constrain_btn = SecondaryButton(
            "约束至 sRGB", tooltip="映射回 sRGB 色域")
        self._constrain_btn.clicked.connect(self.constrainRequested.emit)
        self._constrain_btn.setVisible(False)
        layout.addLayout(hbox(self._gamut_label, self._constrain_btn, None,
                              spacing=SPACE.sm))

        self._rgb_label = ValueLabel("")
        self._hex_label = MonoLabel("")
        values_row = hbox(self._rgb_label, self._hex_label, spacing=SPACE.md)
        # 两段数值并排一行，居中显示，省出对话框高度。
        layout.addLayout(hbox(None, values_row, None))

        self._pick_btn = PrimaryButton("屏幕取色", tooltip="在屏幕上取色")
        self._pick_btn.clicked.connect(self.pickStart.emit)
        self._copy_btn = SecondaryButton(self.COPY_TEXT, tooltip="复制十六进制值")
        self._copy_btn.clicked.connect(self._copy_hex)
        # 按钮放在换行布局里：窄窗口下自动折到第二行，不会挤爆面板。
        layout.addLayout(flow(self._pick_btn, self._copy_btn, spacing=SPACE.sm))

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(self.COPY_FEEDBACK_MS)
        self._copy_timer.timeout.connect(self._restore_copy_text)

        # 面板被放进更高的容器时内容保持顶部对齐，不被均匀拉开。
        layout.addStretch(1)

    # -- 模型绑定 --------------------------------------------------------
    def set_model(self, model: BaseColorModel):
        """换模型：摘掉旧监听、重绑新模型并刷新显示。"""
        if model is self._model:
            self.refresh()
            return
        self._model.remove_listener(self._on_model_changed)
        self._model = model
        model.add_listener(self._on_model_changed)
        self.refresh()

    # -- 显示 ------------------------------------------------------------
    def _sync_display(self):
        self._swatch.set_color(self._model.to_qcolor())
        in_gamut = self._model.is_in_gamut()
        if in_gamut:
            self._gamut_label.set_message("sRGB 色域内", State.SUCCESS)
        else:
            self._gamut_label.set_message("超出 sRGB 色域", State.DANGER)
        self._constrain_btn.setVisible(not in_gamut)

        r, g, b = self._model.to_srgb_tuple()
        ri = round(r * 255)
        gi = round(g * 255)
        bi = round(b * 255)
        self._rgb_label.setText(f"R: {ri:3d}  G: {gi:3d}  B: {bi:3d}")
        self._hex_label.setText(f"#{ri:02X}{gi:02X}{bi:02X}")

    def _copy_hex(self):
        QApplication.clipboard().setText(self._hex_label.text())
        self._copy_btn.setText(self.COPIED_TEXT)
        self._copy_timer.start()

    def _restore_copy_text(self):
        self._copy_btn.setText(self.COPY_TEXT)

    def _on_model_changed(self, model, source):
        self._sync_display()

    def refresh(self):
        self._sync_display()


# =============================================================================
# DynamicSlidersWidget
# =============================================================================
class DynamicSlidersWidget(QWidget):
    """按模型参数动态生成滑块行；切模型时原地重建行而不重建整个控件。"""

    colorChanged = Signal(object)

    def __init__(self, model: BaseColorModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._updating = False
        self._sliders = []
        self._layout = vbox(spacing=SPACE.sm)
        self.setLayout(self._layout)
        self._rebuild_sliders()

    # -- 构建 / 重建 -----------------------------------------------------
    def _rebuild_sliders(self):
        for slider in self._sliders:
            self._layout.removeWidget(slider)
            slider.setParent(None)
            slider.deleteLater()
        self._sliders = []

        params = self._model.get_params()
        for i, name in enumerate(self._model.param_names):
            vmin, vmax = self._model.param_ranges[i]
            dec = self._model.param_decimals[i]
            step = self._model.param_steps[i]
            slider = ColorSlider(name, vmin, vmax, params[i], dec, step)
            slider.valueChanged.connect(
                lambda v, idx=i: self._on_slider_changed(idx, v))
            self._layout.addWidget(slider)
            self._sliders.append(slider)

        self._update_gradients()

    def set_model(self, model: BaseColorModel):
        """换模型：摘旧监听 → 重绑 → 按新参数重建滑块行并刷新渐变。"""
        if model is self._model:
            self._sync_from_model()
            return
        self._model.remove_listener(self._on_model_changed)
        self._model = model
        model.add_listener(self._on_model_changed)
        self._rebuild_sliders()

    # -- 交互 ------------------------------------------------------------
    def _on_slider_changed(self, idx, value):
        if self._updating:
            return
        p = self._model.get_params()
        p[idx] = value
        self._model.set_params(p[0], p[1], p[2])
        self._update_gradients()
        self.colorChanged.emit(self._model)

    def _update_gradients(self):
        rng = self._model.param_ranges
        for i, slider in enumerate(self._sliders):
            def builder(w, h, idx=i, self_ref=self):
                p_base = self_ref._model.get_params()
                ps = np.tile(p_base, (w, 1))
                vals = np.linspace(rng[idx][0], rng[idx][1], w)
                ps[:, idx] = vals
                srgb, mask = self_ref._model._params_to_srgb(ps)
                r = np.tile(srgb[:, 0:1], (h, 1)).flatten() * 255
                g = np.tile(srgb[:, 1:2], (h, 1)).flatten() * 255
                b = np.tile(srgb[:, 2:3], (h, 1)).flatten() * 255
                m = np.tile(mask.reshape(-1, 1), (h, 1)).flatten()
                px = QPixmap.fromImage(
                    make_argb_image(w, h, r, g, b, m)
                )
                return px
            slider.set_batch_builder(builder, fixed_idx=i)
            slider.refresh_gradient()

    def _sync_from_model(self):
        p = self._model.get_params()
        self._updating = True
        for i, slider in enumerate(self._sliders):
            slider.set_value(p[i], block=True)
        self._updating = False
        self._update_gradients()

    def _on_model_changed(self, model, source):
        if source is self:
            return
        self._sync_from_model()
