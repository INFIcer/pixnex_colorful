import numpy as np
from abc import ABC, abstractmethod
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QDoubleSpinBox, QFrame, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QLinearGradient, QConicalGradient, QPen, QBrush,
    QPixmap, QImage
)

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
    def description(self) -> str: ...
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

    def _notify(self, source=None):
        for cb in self._listeners:
            cb(self, source)


class OKLCHModel(BaseColorModel):
    name = "OKLCH"
    description = "基于感知均匀的 OKLab 色彩空间，L(明度) 0-1，C(彩度) 0-0.4，H(色相) 0-360°。\n比传统 HSV/HSL 更符合人眼感知，但部分颜色超出 sRGB 色域。"
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
    description = "色相 H 0-360°，饱和度 S 0-1，明度 V 0-1。最常用的颜色模型，直观且完全在 sRGB 色域内。\n但感知上不线性——明度变化时色相和饱和度感知也会偏移。"
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
    description = "以 CIE Lab 为基础的极坐标形式，L(明度) 0-100，C(彩度) 0-150，H(色相) 0-360°。\n国际照明委员会(CIE)标准色彩空间，感知均匀，常作为颜色科学参考标准。"
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
    description = "L(明度) 0-100，a(绿到红) -128~127，b(蓝到黄) -128~127。\nCIE 标准绝对色彩空间，设备无关，色域覆盖人眼可视范围。a×b 平面展示色度分布。"
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
    description = "色相 H 0-360°，饱和度 S 0-1，强度 I 0-1。I = (R+G+B)/3。\n标准 HSI 定义，饱和度基于最小分量与亮度和之比，色相用三角法计算。在图像分割中更稳定。"
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
# PreviewStrip
# =============================================================================
class PreviewStrip(QWidget):
    posChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batch_builder = None
        self._current_pos = 0.0
        self._cache = None
        self._cache_width = -1
        self._dragging = False

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
        if self._cache is None or self._cache_width != w:
            self._cache = self._batch_builder(w, h)
            self._cache_width = w
        painter.drawPixmap(0, 0, self._cache)
        if self._current_pos >= 0:
            x = int(self._current_pos * (w - 1))
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
    valueChanged = Signal(float)

    def __init__(self, label, vmin, vmax, default, decimals=3, step=0.001, parent=None):
        super().__init__(parent)
        self._vmin, self._vmax, self._vrange = vmin, vmax, vmax - vmin
        self._decimals = decimals
        self._step = step
        self._batch_builder = None
        self._fixed_idx = 0
        self._block = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._label = QLabel(label)
        self._label.setFixedWidth(22)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(self._label)

        self._preview = PreviewStrip(self)
        self._preview.setFixedHeight(24)
        self._preview.setCursor(Qt.PointingHandCursor)
        self._preview.posChanged.connect(self._on_preview)
        layout.addWidget(self._preview, 1)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(vmin, vmax)
        self._spin.setDecimals(decimals)
        self._spin.setSingleStep(step)
        self._spin.setValue(default)
        self._spin.setFixedWidth(80)
        self._spin.valueChanged.connect(self._on_spin)
        layout.addWidget(self._spin)

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
    colorChanged = Signal(object)

    def __init__(self, model: BaseColorModel, size=240, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._size = size
        self._ring_outer_r = size // 2
        self._ring_inner_r = int(size * 0.35)
        self._square_size = int(self._ring_inner_r * 1.3)
        self._square_size = min(self._square_size, size - 20)
        self._strip_width = 20
        self._strip_gap = 8
        self._has_side_strip = (model.strip_index >= 0 and not model.has_hue)
        self._cache_ring = None
        self._cache_sq = None
        self._cache_sq_hue = -999
        self._cache_strip = None
        self._active_region = None
        self.setMouseTracking(True)

        if self._has_side_strip:
            avail = size - self._strip_width - self._strip_gap - 24
            new_sq = min(avail, size - 20)
            if new_sq > self._square_size:
                self._square_size = int(new_sq)
            self.setFixedSize(self._square_size + self._strip_width + self._strip_gap + 12, size)
        else:
            self.setFixedSize(size, size)

    def _square_rect(self):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        if self._has_side_strip:
            aw = w - (self._strip_width + self._strip_gap)
            cx, cy = aw / 2, h / 2
        hs = self._square_size / 2
        return cx, cy, cx - hs, cy - hs, cx + hs, cy + hs

    def _strip_rect(self):
        w, h = self.width(), self.height()
        aw = w - (self._strip_width + self._strip_gap)
        sx = aw + self._strip_gap
        sy = 4
        sh = h - 8
        return sx, sy, self._strip_width, sh

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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        cx, cy, _, _, _, _ = self._square_rect()

        if self._model.has_hue:
            self._draw_ring(painter, cx, cy)
        self._draw_square(painter, cx, cy)

        si = self._model.strip_index
        if si >= 0:
            self._draw_strip(painter)

        p = self._model.get_params()

        if self._model.has_hue:
            hi = self._model.hue_index
            angle_rad = np.radians(p[hi] - 90)
            r1, r2 = self._ring_inner_r, self._ring_outer_r
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(QPointF(cx + r1*np.cos(angle_rad), cy + r1*np.sin(angle_rad)),
                             QPointF(cx + r2*np.cos(angle_rad), cy + r2*np.sin(angle_rad)))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawLine(QPointF(cx + r1*np.cos(angle_rad) + 2, cy + r1*np.sin(angle_rad)+2),
                             QPointF(cx + r2*np.cos(angle_rad) + 2, cy + r2*np.sin(angle_rad)+2))

        xi, yi = self._model.square_x_index, self._model.square_y_index
        if xi >= 0 and yi >= 0:
            rng = self._model.param_ranges
            nx = (p[xi] - rng[xi][0]) / (rng[xi][1] - rng[xi][0])
            ny = 1 - (p[yi] - rng[yi][0]) / (rng[yi][1] - rng[yi][0])
            hs = self._square_size / 2
            dx = cx - hs + nx * self._square_size
            dy = cy - hs + ny * self._square_size
            painter.setPen(QPen(Qt.white, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(dx, dy), 6, 6)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(QPointF(dx, dy), 7, 7)

        if si >= 0 and self._has_side_strip and self._cache_strip is not None:
            sx, sy, sw, sh = self._strip_rect()
            vy = self._strip_pos_from_val(p[si], sy, sh)
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(int(sx), int(vy), int(sx + sw), int(vy))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawLine(int(sx), int(vy+1), int(sx + sw), int(vy+1))
        elif si >= 0 and not self._has_side_strip and self._cache_strip is not None:
            sx, sy, sw, sh = self._strip_rect()
            vy = self._strip_pos_from_val(p[si], sy, sh)
            painter.setPen(QPen(Qt.white, 2))
            painter.drawLine(int(sx), int(vy), int(sx + sw), int(vy))

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

    def _draw_ring(self, painter, cx, cy):
        if self._cache_ring is None:
            pm = QPixmap(self._size, self._size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            grad = QConicalGradient(QPointF(cx, cy), 90)
            colors = self._build_ring_colors(180)
            for i, c in enumerate(colors):
                grad.setColorAt(1.0 - i / len(colors), c)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawPie(QRectF(cx - self._ring_outer_r, cy - self._ring_outer_r,
                             2*self._ring_outer_r, 2*self._ring_outer_r), 0, 360*16)
            ir = QRectF(cx - self._ring_inner_r, cy - self._ring_inner_r,
                         2*self._ring_inner_r, 2*self._ring_inner_r)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.drawEllipse(ir)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(80, 80, 80, 160), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(ir)
            p.end()
            self._cache_ring = pm
        painter.drawPixmap(0, 0, self._cache_ring)

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
        rebuild = self._cache_sq is None
        if self._model.has_hue:
            hi = self._model.hue_index
            rebuild = rebuild or abs(self._cache_sq_hue - p[hi]) > 0.5
        if rebuild:
            self._build_square_image()
        hs = self._square_size / 2
        painter.drawPixmap(int(cx - hs), int(cy - hs), self._cache_sq)

    def _build_strip(self):
        sx, sy, sw, sh = self._strip_rect()
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
        if self._cache_strip is None:
            self._build_strip()
        sx, sy, sw, sh = self._strip_rect()
        painter.drawPixmap(int(sx), int(sy), self._cache_strip)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
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
        if self._model.has_hue:
            cx, cy, _, _, _, _ = self._square_rect()
            dx, dy = pos.x() - cx, pos.y() - cy
            dist = np.sqrt(dx*dx + dy*dy)
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
            cx, cy, _, _, _, _ = self._square_rect()
            dx, dy = pos.x() - cx, pos.y() - cy
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
        self._cache_ring = None
        self._cache_sq = None
        self._cache_strip = None
        self.update()


# =============================================================================
# ColorInfoPanel
# =============================================================================
class ColorInfoPanel(QWidget):
    pickStart = Signal()
    constrainRequested = Signal()

    def __init__(self, model: BaseColorModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._init_ui()
        self._sync_display()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._preview = QFrame()
        self._preview.setFixedHeight(50)
        self._preview.setFrameShape(QFrame.StyledPanel)
        layout.addWidget(self._preview)

        gamut_layout = QHBoxLayout()
        self._gamut_label = QLabel("sRGB 色域内")
        self._gamut_label.setAlignment(Qt.AlignCenter)
        gamut_layout.addWidget(self._gamut_label, 1)

        self._constrain_btn = QPushButton("约束至 sRGB")
        self._constrain_btn.setStyleSheet("""
            QPushButton { padding: 2px 10px; font-size: 10px;
                background-color: #EF5350; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #D32F2F; }
            QPushButton:pressed { background-color: #B71C1C; }
        """)
        self._constrain_btn.setCursor(Qt.PointingHandCursor)
        self._constrain_btn.clicked.connect(self.constrainRequested.emit)
        self._constrain_btn.setVisible(False)
        gamut_layout.addWidget(self._constrain_btn)
        layout.addLayout(gamut_layout)

        self._rgb_label = QLabel("")
        self._rgb_label.setAlignment(Qt.AlignCenter)
        self._rgb_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self._rgb_label)

        self._hex_label = QLabel("")
        self._hex_label.setAlignment(Qt.AlignCenter)
        self._hex_label.setStyleSheet("color: #555; font-size: 11px; font-family: Consolas, monospace;")
        layout.addWidget(self._hex_label)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_pick = QPushButton("🎯 屏幕取色")
        btn_pick.setStyleSheet("""
            QPushButton { padding: 6px 16px; font-size: 12px;
                background-color: #5C6BC0; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #3F51B5; }
            QPushButton:pressed { background-color: #303F9F; }
        """)
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.clicked.connect(self.pickStart.emit)
        hl.addWidget(btn_pick)

        self._copy_btn = QPushButton("📋 复制 HEX")
        self._copy_btn.setStyleSheet("""
            QPushButton { padding: 6px 16px; font-size: 12px;
                background-color: #5C6BC0; color: white;
                border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #00897B; }
            QPushButton:pressed { background-color: #00695C; }
        """)
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy_hex)
        hl.addWidget(self._copy_btn)
        hl.addStretch()
        layout.addLayout(hl)

    def _sync_display(self):
        self._copy_btn.setText("📋 复制 HEX")
        qc = self._model.to_qcolor()
        gamut = self._model.is_in_gamut()
        self._preview.setStyleSheet(
            f"background-color: {qc.name()}; border: 2px solid; border-radius: 4px;"
        )
        if gamut:
            self._gamut_label.setText("✓ sRGB 色域内")
            self._gamut_label.setStyleSheet("color: #4CAF50; font-size: 11px; margin: 2px 0px 2px 0px;")
            self._constrain_btn.setVisible(False)
        else:
            self._gamut_label.setText("✗ 超出 sRGB 色域")
            self._gamut_label.setStyleSheet("color: #f44336; font-size: 11px; margin: 2px 0px 2px 0px;")
            self._constrain_btn.setVisible(True)
        r, g, b = self._model.to_srgb_tuple()
        ri = round(r * 255)
        gi = round(g * 255)
        bi = round(b * 255)
        self._rgb_label.setText(f"R: {ri:3d}  G: {gi:3d}  B: {bi:3d}")
        self._hex_label.setText(f"#{ri:02X}{gi:02X}{bi:02X}")

    def _copy_hex(self):
        r, g, b = self._model.to_srgb_tuple()
        ri = round(r * 255)
        gi = round(g * 255)
        bi = round(b * 255)
        hex_str = f"#{ri:02X}{gi:02X}{bi:02X}"
        QApplication.clipboard().setText(hex_str)
        self._copy_btn.setText("✅ 已复制")

    def _on_model_changed(self, model, source):
        self._sync_display()

    def refresh(self):
        self._sync_display()


# =============================================================================
# DynamicSlidersWidget
# =============================================================================
class DynamicSlidersWidget(QWidget):
    colorChanged = Signal(object)

    def __init__(self, model: BaseColorModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.add_listener(self._on_model_changed)
        self._updating = False
        self._sliders = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._sliders = []
        for i, name in enumerate(self._model.param_names):
            vmin, vmax = self._model.param_ranges[i]
            default = self._model.get_params()[i]
            dec = self._model.param_decimals[i]
            step = self._model.param_steps[i]
            sl = ColorSlider(name, vmin, vmax, default, dec, step)
            sl.valueChanged.connect(lambda v, idx=i: self._on_slider_changed(idx, v))
            layout.addWidget(sl)
            self._sliders.append(sl)

        self._update_gradients()

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
        for i, sl in enumerate(self._sliders):
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
            sl.set_batch_builder(builder, fixed_idx=i)
            sl.refresh_gradient()

    def _sync_from_model(self):
        p = self._model.get_params()
        self._updating = True
        for i, sl in enumerate(self._sliders):
            sl.set_value(p[i], block=True)
        self._updating = False
        self._update_gradients()

    def _on_model_changed(self, model, source):
        if source is self:
            return
        self._sync_from_model()
