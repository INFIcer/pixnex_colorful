"""Generate the pixnex application icon.

``pixnex.ico`` is the single source of truth for the application identity:

- it is embedded into the packaged ``pixnex.exe`` (``pixnex.spec`` → ``icon=``);
- it is bundled into the executable as data so the window / task bar icon can
  be loaded at runtime (``colorPickerPro/ui/app_icon.py``);
- the main window draws it in its custom title bar.

The artwork is drawn here instead of being shipped as a binary blob, so it can
be regenerated, restyled or resized from code at any time::

    python tools/gen_app_icon.py            # rewrite pixnex.ico
    python tools/gen_app_icon.py --preview  # also dump build/icon-preview/*.png

Design: a dark rounded tile keeps the icon quiet next to the neutral dark
interface, the hue ring is the colourful element (it *is* the product: a colour
tool), and the white dot in the middle is the picked colour swatch.  Small
sizes (16–24 px) are rendered with a thicker ring and a slightly larger dot so
they stay legible in the title bar, task bar and Alt-Tab switcher.
"""

from __future__ import annotations

import argparse
import colorsys
import struct
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICO_PATH = ROOT / "pixnex.ico"
PREVIEW_DIR = ROOT / "build" / "icon-preview"

#: Icon sizes stored in the .ico.  The set covers every Windows DPI step
#: (100/125/150/175/200/250 % → 16/20/24/28/32/40 px device pixels).
ICO_SIZES: tuple[int, ...] = (16, 20, 24, 28, 32, 40, 48, 64, 128, 256)

#: Entries stored as PNG instead of BMP/DIB: 128 px and up are large enough
#: that compression matters and every Windows version supports PNG entries.
PNG_SIZES: frozenset[int] = frozenset({128, 256})

#: Supersampling factor used while drawing.  Pillow has no analytic
#: anti-aliasing for the shapes used here, so we draw big and downscale.
SUPERSAMPLE = 4

# ---------------------------------------------------------------------------
# Palette (kept close to colorPickerPro/ui/tokens.py: window/surface/accent)
# ---------------------------------------------------------------------------
TILE_TOP = np.array([0x31, 0x3D, 0x4F], dtype=np.float32) / 255.0   # 略亮于 surface
TILE_BOTTOM = np.array([0x11, 0x15, 0x1C], dtype=np.float32) / 255.0  # 略暗于 window
RIM_ALPHA = 0.10                    # 顶部 1px 高光
GLOW = np.array([0x4C, 0x8D, 0xFF], dtype=np.float32) / 255.0       # palette accent
GLOW_ALPHA = 0.16
RING_SAT = 0.82
RING_VAL = 1.0
DOT_TOP = np.array([0xFF, 0xFF, 0xFF], dtype=np.float32) / 255.0
DOT_BOTTOM = np.array([0xD9, 0xE2, 0xF2], dtype=np.float32) / 255.0


def _hue_table(steps: int = 4096) -> np.ndarray:
    """Pre-computed HSV(hue=0..1, sat, val) → RGB table (0..1 floats)."""
    return np.array(
        [colorsys.hsv_to_rgb(index / steps, RING_SAT, RING_VAL)
         for index in range(steps)],
        dtype=np.float32)


HUE_TABLE = _hue_table()


def _rounded_rect_sdf(x: np.ndarray, y: np.ndarray, half: float,
                      radius: float) -> np.ndarray:
    """Signed distance to a rounded square centred at the origin."""
    qx = np.abs(x) - (half - radius)
    qy = np.abs(y) - (half - radius)
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return outside + inside - radius


def _smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    t = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def render_icon(size: int) -> Image.Image:
    """Render one square icon frame at *size* pixels (RGBA)."""
    n = size * SUPERSAMPLE
    coords = (np.arange(n, dtype=np.float32) + 0.5) / n
    x, y = np.meshgrid(coords, coords)
    dx = x - 0.5
    dy = y - 0.5
    radius = np.hypot(dx, dy)

    # --- layout, tuned per size so small frames stay readable -------------
    tile_half = 0.5
    corner = 0.215
    if size <= 24:
        ring_outer, ring_inner, dot_r = 0.352, 0.176, 0.160
    elif size <= 32:
        ring_outer, ring_inner, dot_r = 0.336, 0.188, 0.148
    else:
        ring_outer, ring_inner, dot_r = 0.320, 0.204, 0.132

    # --- base tile --------------------------------------------------------
    tile = _rounded_rect_sdf(dx, dy, tile_half, corner) <= 0.0
    tile_alpha = tile.astype(np.float32)

    # vertical gradient + soft accent glow behind the mark
    t = np.clip(y / 0.98, 0.0, 1.0)[..., None]
    gradient = TILE_TOP * (1.0 - t) + TILE_BOTTOM * t
    glow = np.clip(1.0 - radius / 0.62, 0.0, 1.0)[..., None] ** 1.6
    base = gradient + (GLOW - gradient) * (glow * GLOW_ALPHA)

    rgb = base.copy()
    alpha = tile_alpha.copy()

    # --- hue ring ---------------------------------------------------------
    hue = (np.arctan2(dx, -dy) / (2.0 * np.pi)) % 1.0
    ring_rgb = HUE_TABLE[(hue * len(HUE_TABLE)).astype(np.int32) % len(HUE_TABLE)]
    ring_mask = (radius <= ring_outer) & (radius >= ring_inner) & tile
    # 内外边缘轻微压暗，让色环从暗底上“立”起来
    edge = np.clip(np.minimum(radius - ring_inner, ring_outer - radius) / 0.045, 0.0, 1.0)
    ring_rgb = ring_rgb * (0.86 + 0.14 * edge)[..., None]
    rgb = np.where(ring_mask[..., None], ring_rgb, rgb)

    # --- centre swatch (the picked colour) -------------------------------
    shadow_offset = 0.012
    shadow_r = np.hypot(dx, dy - shadow_offset)
    shadow = _smoothstep(dot_r * 1.30, dot_r * 0.92, shadow_r) * 0.45
    shadow_mask = tile & (shadow > 0.0)
    rgb = np.where(shadow_mask[..., None], rgb * (1.0 - shadow[..., None]), rgb)

    dot_mask = (radius <= dot_r) & tile
    dot_t = np.clip((dy + dot_r) / (2.0 * dot_r), 0.0, 1.0)[..., None]
    dot_rgb = DOT_TOP * (1.0 - dot_t) + DOT_BOTTOM * dot_t
    rgb = np.where(dot_mask[..., None], dot_rgb, rgb)

    # --- top rim highlight ------------------------------------------------
    if size >= 32:
        rim = tile & (np.abs(_rounded_rect_sdf(dx, dy, tile_half, corner)) < 0.008)
        rim_fade = np.clip((0.42 - y) / 0.42, 0.0, 1.0)[..., None]
        rgb = np.where(rim[..., None], rgb * (1.0 - RIM_ALPHA * rim_fade) + RIM_ALPHA * rim_fade,
                       rgb)

    frame = np.concatenate([np.clip(rgb, 0.0, 1.0), alpha[..., None]], axis=2)
    return _downsample(frame, size)


def _downsample(frame: np.ndarray, size: int) -> Image.Image:
    """Premultiplied Lanczos downscale of the supersampled frame."""
    premultiplied = frame.copy()
    premultiplied[..., :3] *= frame[..., 3:4]
    image = Image.fromarray((premultiplied * 255.0 + 0.5).astype(np.uint8), "RGBA")
    image = image.resize((size, size), Image.LANCZOS)
    data = np.asarray(image, dtype=np.float32) / 255.0
    alpha = data[..., 3:4]
    rgb = np.clip(data[..., :3] / np.maximum(alpha, 1e-4), 0.0, 1.0)
    return Image.fromarray((np.concatenate([rgb, alpha], axis=2) * 255.0 + 0.5)
                           .astype(np.uint8), "RGBA")


# ---------------------------------------------------------------------------
# .ico writer (BMP entries for small sizes, PNG entries for large ones)
# ---------------------------------------------------------------------------
def _bmp_frame(image: Image.Image) -> bytes:
    """32-bit BGRA DIB frame with the legacy 1-bit AND mask."""
    width, height = image.size
    pixels = np.asarray(image, dtype=np.uint8)
    bgra = pixels[::-1, :, [2, 1, 0, 3]]
    xor = bgra.tobytes()

    row_bytes = ((width + 31) // 32) * 4
    mask = np.zeros((height, row_bytes), dtype=np.uint8)
    transparent = pixels[..., 3] == 0
    for row in range(height):
        bits = mask[height - 1 - row]
        for col in np.nonzero(transparent[row])[0]:
            bits[col >> 3] |= 0x80 >> (col & 7)

    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0,
        len(xor) + mask.nbytes, 0, 0, 0, 0)
    return header + xor + mask.tobytes()


def _png_frame(image: Image.Image) -> bytes:
    from io import BytesIO
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def write_ico(path: Path, frames: dict[int, Image.Image]) -> None:
    """Write a multi-size .ico from already rendered frames."""
    entries: list[tuple[int, bytes]] = []
    for size in sorted(frames):
        image = frames[size]
        payload = (_png_frame(image) if size in PNG_SIZES
                   else _bmp_frame(image))
        entries.append((size, payload))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory = bytearray()
    payloads = bytearray()
    for size, payload in entries:
        directory += struct.pack(
            "<BBBBHHII", 0 if size >= 256 else size, 0 if size >= 256 else size,
            0, 0, 1, 32, len(payload), offset)
        payloads += payload
        offset += len(payload)
    path.write_bytes(bytes(header) + bytes(directory) + bytes(payloads))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def contact_sheet(frames: dict[int, Image.Image], scale: int = 8) -> Image.Image:
    """Zoomed contact sheet so the small sizes can be judged at a glance."""
    tiles = [frames[size].resize((size * scale, size * scale), Image.NEAREST)
             for size in (16, 20, 24, 32, 48, 256)]
    padding = 12
    width = sum(tile.width for tile in tiles) + padding * (len(tiles) + 1)
    height = max(tile.height for tile in tiles) + padding * 2
    sheet = Image.new("RGBA", (width, height), (0x20, 0x24, 0x2B, 255))
    x = padding
    for tile in tiles:
        sheet.paste(tile, (x, padding), tile)
        x += tile.width + padding
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true",
                        help="write PNG previews to build/icon-preview")
    args = parser.parse_args(argv)

    frames = {size: render_icon(size) for size in ICO_SIZES}
    write_ico(ICO_PATH, frames)
    print(f"wrote {ICO_PATH.relative_to(ROOT)} "
          f"({ICO_PATH.stat().st_size} bytes, sizes {sorted(frames)})")

    if args.preview:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        for size, image in frames.items():
            image.save(PREVIEW_DIR / f"icon_{size}.png")
        contact_sheet(frames).save(PREVIEW_DIR / "contact_sheet.png")
        print(f"wrote previews to {PREVIEW_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
