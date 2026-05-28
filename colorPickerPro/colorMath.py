# colorMath.py
# Pure NumPy color science and image processing utilities
# No external dependencies beyond NumPy

import numpy as np

# =============================================================================
# sRGB gamma
# =============================================================================

def srgb_gamma(c):
    c_safe = np.clip(c, 0.0, 1.0)
    mask = c_safe <= 0.0031308
    return np.where(mask, 12.92 * c_safe, 1.055 * np.power(c_safe, 1.0 / 2.4) - 0.055)

def srgb_gamma_inv(c):
    mask = c <= 0.04045
    return np.where(mask, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))

_GAMUT_EPS = 1e-4

def linear_to_srgb_clamped(rgb_lin):
    """线性光 -> sRGB + 检测色域 返回 (srgb, in_gamut_mask)"""
    mask = np.all((rgb_lin >= -_GAMUT_EPS) & (rgb_lin <= 1 + _GAMUT_EPS), axis=-1)
    return srgb_gamma(np.clip(rgb_lin, 0, 1)), mask

# =============================================================================
# OKLab / OKLCH
# =============================================================================

_M1 = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
])
_M1_inv = np.linalg.inv(_M1)
_M2 = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
])
_M2_inv = np.linalg.inv(_M2)
OKLCH_C_MAX = 0.40

def oklch_from_lab(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.sqrt(a**2 + b**2)
    H = np.degrees(np.arctan2(b, a)) % 360
    return np.array([L, C, H])

def oklch_to_lab_vec(L, C, H):
    Hr = np.radians(H)
    return np.stack([L, C * np.cos(Hr), C * np.sin(Hr)], axis=-1)

# =============================================================================
# HSV
# =============================================================================

def hsv_to_srgb(hsv):
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    H_norm = (H % 360) / 60.0
    i = np.floor(H_norm).astype(int) % 6
    f = H_norm - np.floor(H_norm)
    p = V * (1 - S)
    q = V * (1 - S * f)
    t = V * (1 - S * (1 - f))
    r, g, b = np.zeros_like(V), np.zeros_like(V), np.zeros_like(V)
    for idx, (ri, gi, bi) in enumerate([
        (V, t, p), (q, V, p), (p, V, t),
        (p, q, V), (t, p, V), (V, p, q)
    ]):
        m = (i == idx)
        r, g, b = np.where(m, ri, r), np.where(m, gi, g), np.where(m, bi, b)
    return np.stack([r, g, b], axis=-1)

def srgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    df = mx - mn
    V = mx
    with np.errstate(invalid='ignore'):
        S = np.where(mx > 0, df / mx, 0)
        mask = df > 1e-10
        H = np.zeros_like(r)
        H = np.where(mask & (mx == r), (60 * ((g - b) / df + 0)) % 360, H)
        H = np.where(mask & (mx == g), (60 * ((b - r) / df + 2)) % 360, H)
        H = np.where(mask & (mx == b), (60 * ((r - g) / df + 4)) % 360, H)
    return np.stack([H, S, V], axis=-1)

# =============================================================================
# HLS
# =============================================================================

def srgb_to_hls(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    L = (mx + mn) / 2.0
    df = mx - mn
    with np.errstate(invalid='ignore'):
        S = np.where(df < 1e-10, 0,
                     np.where(L > 0.5, df / (2.0 - mx - mn), df / (mx + mn)))
        S = np.clip(S, 0, 1)
        H = np.zeros_like(r)
        mask = df > 1e-10
        H = np.where(mask & (mx == r), (60 * ((g - b) / df + 0)) % 360, H)
        H = np.where(mask & (mx == g), (60 * ((b - r) / df + 2)) % 360, H)
        H = np.where(mask & (mx == b), (60 * ((r - g) / df + 4)) % 360, H)
    return np.stack([H, L, S], axis=-1)

# =============================================================================
# CIE Lab / LCH (D65)
# =============================================================================

_XYZ_to_linRGB = np.array([
    [3.2404542, -1.5371385, -0.4985314],
    [-0.9692660, 1.8760108, 0.0415560],
    [0.0556434, -0.2040259, 1.0572252],
])
_linRGB_to_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_D65 = np.array([0.95047, 1.0, 1.08883])

def _lab_f(t):
    delta = 6/29
    return np.where(t > delta**3, np.cbrt(t), t / (3 * delta**2) + 4/29)

def _lab_f_inv(t):
    delta = 6/29
    return np.where(t > delta, t**3, 3 * delta**2 * (t - 4/29))

def cielab_to_linrgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200
    X = _XYZ_D65[0] * _lab_f_inv(fx)
    Y = _XYZ_D65[1] * _lab_f_inv(fy)
    Z = _XYZ_D65[2] * _lab_f_inv(fz)
    return np.stack([X, Y, Z], axis=-1) @ _XYZ_to_linRGB.T

def linrgb_to_cielab(rgb_lin):
    xyz = rgb_lin @ _linRGB_to_XYZ.T
    X, Y, Z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    fx = _lab_f(X / _XYZ_D65[0])
    fy = _lab_f(Y / _XYZ_D65[1])
    fz = _lab_f(Z / _XYZ_D65[2])
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return np.stack([L, a, b], axis=-1)

def cielch_to_lab_vec(L, C, H):
    Hr = np.radians(H)
    return np.stack([L, C * np.cos(Hr), C * np.sin(Hr)], axis=-1)

def cielch_from_lab(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.sqrt(a**2 + b**2)
    H = np.degrees(np.arctan2(b, a)) % 360
    return np.stack([L, C, H], axis=-1)

CIE_LCH_C_MAX = 150.0

# =============================================================================
# HSI
# =============================================================================

def hsi_to_srgb(hsi):
    H, S, I_ = hsi[..., 0], hsi[..., 1], hsi[..., 2]
    Hr = np.radians(H % 360)
    S_safe = np.clip(S, 0, 1)
    I_safe = np.clip(I_, 0, 1)
    sector = np.floor(Hr / (np.pi * 2 / 3)).astype(int) % 3
    H_adj = Hr - sector.astype(float) * (np.pi * 2 / 3)
    cos_val = np.cos(H_adj)
    denom = np.cos(np.pi / 3 - H_adj)
    denom_safe = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    base = I_safe * (1 + S_safe * cos_val / denom_safe)
    C2 = I_safe * (1 - S_safe)
    C3 = 3 * I_safe - base - C2
    r, g, b = np.zeros_like(I_safe), np.zeros_like(I_safe), np.zeros_like(I_safe)
    for idx, (ri, gi, bi) in enumerate([(base, C3, C2), (C2, base, C3), (C3, C2, base)]):
        m = (sector == idx)
        r, g, b = np.where(m, ri, r), np.where(m, gi, g), np.where(m, bi, b)
    rgb = np.clip(np.stack([r, g, b], axis=-1), 0, 1)
    mask = np.all((rgb >= -1e-9) & (rgb <= 1 + 1e-9), axis=-1)
    return rgb, mask

def srgb_to_hsi(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    I_ = (r + g + b) / 3.0
    mn = np.minimum(np.minimum(r, g), b)
    with np.errstate(invalid='ignore'):
        denom = r + g + b
        denom_safe = np.where(denom > 0, denom, 1e-12)
        S = np.where(denom > 0, 1 - 3 * mn / denom_safe, 0)
        S = np.clip(S, 0, 1)
        num = 0.5 * ((r - g) + (r - b))
        d_sq = (r - g) ** 2 + (r - b) * (g - b)
        denom_h = np.sqrt(np.maximum(d_sq, 1e-12))
        theta = np.arccos(np.clip(num / denom_h, -1, 1))
        H = np.degrees(theta)
        H = np.where(b > g, 360 - H, H)
    return np.stack([H, S, I_], axis=-1)

# =============================================================================
# LUT for fast gamma inverse (uint8 -> linear float32)
# =============================================================================

_GAMMA_INV_LUT = np.array(
    [srgb_gamma_inv(x / 255.0) for x in range(256)],
    dtype=np.float32
)

def _bgr_to_linrgb(bgr):
    """BGR uint8 (H,W,3) -> linear RGB float32 (H,W,3) via LUT"""
    return np.stack([
        _GAMMA_INV_LUT[bgr[:,:,2]],
        _GAMMA_INV_LUT[bgr[:,:,1]],
        _GAMMA_INV_LUT[bgr[:,:,0]],
    ], axis=-1)

# Float32 matrices for fast Lab path
_fast_linRGB_to_XYZ = _linRGB_to_XYZ.astype(np.float32)
_fast_XYZ_D65 = _XYZ_D65.astype(np.float32)

# =============================================================================
# BGR uint8 utility conversions (for screen filter, no cv2 needed)
# =============================================================================

def bgr_to_gray(bgr):
    """BGR uint8 (H,W,3) -> grayscale uint8 (H,W)"""
    return (0.299 * bgr[:,:,2] + 0.587 * bgr[:,:,1] + 0.114 * bgr[:,:,0]).astype(np.uint8)

def bgr_to_lab(bgr):
    """BGR uint8 (H,W,3) -> CIELAB float32 (H,W,3), L:0-100, a:-128..127, b:-128..127"""
    rgb_lin = _bgr_to_linrgb(bgr)
    return linrgb_to_cielab(rgb_lin)

def bgr_to_cielch(bgr):
    rgb_lin = _bgr_to_linrgb(bgr)
    lab=linrgb_to_cielab(rgb_lin)
    return cielch_from_lab(lab)

def bgr_to_hsv(bgr):
    """BGR uint8 (H,W,3) -> HSV float32 (H,W,3), H:0-360, S:0-1, V:0-1"""
    rgb = bgr[:,:, [2, 1, 0]].astype(np.float32) / 255.0
    return srgb_to_hsv(rgb)

def bgr_hsv_s_channel(bgr):
    """Compute just the S (saturation) from HSV for uint8 BGR (float32 output)"""
    r = bgr[:,:,2].astype(np.float32) / 255.0
    g = bgr[:,:,1].astype(np.float32) / 255.0
    b = bgr[:,:,0].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    df = mx - mn
    with np.errstate(invalid='ignore'):
        S = np.where(mx > 0, df / mx, 0)
    return S

def bgr_to_hls(bgr):
    """BGR uint8 (H,W,3) -> HLS float32 (H,W,3), H:0-360, L:0-1, S:0-1"""
    rgb = bgr[:,:, [2, 1, 0]].astype(np.float32) / 255.0
    return srgb_to_hls(rgb)

def bgr_hls_l_channel(bgr):
    """Compute just the L (lightness) from HLS for uint8 BGR (float32 output)"""
    r = bgr[:,:,2].astype(np.float32) / 255.0
    g = bgr[:,:,1].astype(np.float32) / 255.0
    b = bgr[:,:,0].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return (mx + mn) / 2.0

def bgra_to_bgr(bgra):
    """BGRA uint8 (H,W,4) -> BGR uint8 (H,W,3)"""
    return bgra[:, :, :3].copy()

# =============================================================================
# Image processing filters (pure numpy)
# =============================================================================

def invert(img):
    """颜色反转"""
    return 255 - img

def sepia(img):
    """怀旧棕褐色"""
    k = np.array([[0.272, 0.534, 0.131],
                  [0.349, 0.686, 0.168],
                  [0.393, 0.769, 0.189]], dtype=np.float32)
    return np.clip(img @ k.T, 0, 255).astype(np.uint8)

def edge_detect(gray, low=50, high=150):
    """边缘检测：梯度幅度 + 双阈值
    - mag > high: 强边缘（显示为白色 255）
    - low < mag <= high: 弱边缘（显示原始梯度强度）
    - mag <= low: 非边缘（黑色）
    """
    gray_f = gray.astype(np.float32)
    gy = np.zeros_like(gray_f)
    gx = np.zeros_like(gray_f)
    gy[1:-1, :] = gray_f[2:, :] - gray_f[:-2, :]
    gx[:, 1:-1] = gray_f[:, 2:] - gray_f[:, :-2]
    mag = np.sqrt(gx**2 + gy**2)
    strong = mag > high
    weak = (mag > low) & (mag <= high)
    result = np.zeros_like(mag, dtype=np.uint8)
    result[strong] = 255
    result[weak] = np.clip(mag[weak], 0, 255).astype(np.uint8)
    return result
