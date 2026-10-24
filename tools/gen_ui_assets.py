"""Generate the monochrome SVG icon assets used by the UI theme.

All icons are 16x16 vector glyphs so they stay crisp at any DPI.  They are
plain files under ``colorPickerPro/ui/assets/icons/`` and are loaded through
``QIcon`` (buttons) or referenced by the global stylesheet (combo/spin arrows,
checkbox check mark).

Run after changing an icon:

    .venv\\Scripts\\python.exe tools\\gen_ui_assets.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "colorPickerPro" / "ui" / "assets"

STROKE = "#C9D2E0"      # palette.text 与 text_muted 之间的中性色
MUTED = "#9BA6B6"       # palette.text_muted（QSS 小箭头）
WHITE = "#FFFFFF"

_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
    'viewBox="0 0 16 16" fill="none" stroke="{color}" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
)

# 每个图标只写图形部分；外层属性统一由 _svg() 生成。
ICONS = {
    # 窗口控制
    "close": '<path d="M4.2 4.2 L11.8 11.8 M11.8 4.2 L4.2 11.8"/>',
    "minimize": '<path d="M4 8 L12 8"/>',
    "maximize": '<rect x="4" y="4" width="8" height="8" rx="1"/>',
    "restore": (
        '<rect x="3.2" y="5.8" width="7" height="7" rx="1"/>'
        '<path d="M5.8 3.2 H12.8 V10.2"/>'
    ),
    # 屏幕滤镜
    "play": '<path d="M5.2 3.4 L12.4 8 L5.2 12.6 Z" fill="{color}" stroke="none"/>',
    "pause": (
        '<rect x="4.8" y="3.8" width="2.2" height="8.4" rx="0.8" fill="{color}" stroke="none"/>'
        '<rect x="9.0" y="3.8" width="2.2" height="8.4" rx="0.8" fill="{color}" stroke="none"/>'
    ),
    "settings": (
        '<path d="M3 4.5 H13 M3 8 H13 M3 11.5 H13"/>'
        '<circle cx="6" cy="4.5" r="1.6" fill="{bg}" stroke="{color}"/>'
        '<circle cx="10.5" cy="8" r="1.6" fill="{bg}" stroke="{color}"/>'
        '<circle cx="7.2" cy="11.5" r="1.6" fill="{bg}" stroke="{color}"/>'
    ),
    # 列表 / 通用动作
    "add": '<path d="M8 3.4 V12.6 M3.4 8 H12.6"/>',
    "refresh": (
        '<path d="M12.4 8 A4.4 4.4 0 1 1 8 3.6"/>'
        '<path d="M8 1.8 L10.4 3.6 L8 5.4"/>'
    ),
    "copy": (
        '<rect x="5.5" y="5.5" width="7" height="7" rx="1.2"/>'
        '<path d="M3.5 10 V3.5 H10"/>'
    ),
    "trash": (
        '<path d="M3.5 4.5 H12.5"/>'
        '<path d="M6.5 4.5 V3 H9.5 V4.5"/>'
        '<path d="M5.2 4.5 L5.8 13 H10.2 L10.8 4.5"/>'
        '<path d="M7 7 V11 M9 7 V11"/>'
    ),
    "save": (
        '<path d="M3.5 3.5 H10.5 L12.5 5.5 V12.5 H3.5 Z"/>'
        '<path d="M5.5 3.5 V7 H10 V3.5"/>'
        '<path d="M5.5 12.5 V9 H10.5 V12.5"/>'
    ),
    "open": (
        '<path d="M2.5 4 H6 L7.5 5.5 H13.5 V12.5 H2.5 Z"/>'
        '<path d="M2.5 7.5 H13.5"/>'
    ),
    "zoom-reset": (
        '<circle cx="6.6" cy="6.6" r="3.4"/>'
        '<path d="M9.1 9.1 L13 13"/>'
        '<rect x="4.8" y="4.8" width="3.6" height="3.6" rx="0.6"/>'
    ),
    "fit": (
        '<rect x="2.6" y="3.6" width="10.8" height="8.8" rx="1"/>'
        '<path d="M6.4 6.2 L4.6 8 L6.4 9.8 M9.6 6.2 L11.4 8 L9.6 9.8"/>'
    ),
    "rotate-90": (
        '<rect x="2.6" y="6.8" width="5.8" height="5.8" rx="0.8"/>'
        '<path d="M6.2 2.8 H8.8 A4 4 0 0 1 12.8 6.8 V8.8"/>'
        '<path d="M11.2 7.4 L12.8 9.4 L14.4 7.4"/>'
    ),
    "pin": (
        '<path d="M5.4 2.6 H10.6 L9.5 5.2 V7.2 L11.2 9.4 H4.8 L6.5 7.2 V5.2 Z"/>'
        '<path d="M8 9.4 V13.4"/>'
    ),
    # 主窗口自动折叠：窗口连同标题栏，箭头指向标题栏（内容收进标题栏）。
    "collapse": (
        '<rect x="2.6" y="3.6" width="10.8" height="8.8" rx="1"/>'
        '<path d="M2.6 6.4 H13.4"/>'
        '<path d="M8 11.6 V7.8 M6.2 9.6 L8 7.8 L9.8 9.6"/>'
    ),
    "flip-h": (
        '<path d="M8 2.4 V13.6" stroke-dasharray="1.6 1.8"/>'
        '<path d="M5.4 5 L2.4 8 L5.4 11"/>'
        '<path d="M10.6 5 L13.6 8 L10.6 11"/>'
    ),
    "flip-v": (
        '<path d="M2.4 8 H13.6" stroke-dasharray="1.6 1.8"/>'
        '<path d="M5 5.4 L8 2.4 L11 5.4"/>'
        '<path d="M5 10.6 L8 13.6 L11 10.6"/>'
    ),
    # QSS 小图标
    "chevron-down": '<path d="M4.4 6.2 L8 9.8 L11.6 6.2"/>',
    "chevron-up": '<path d="M4.4 9.8 L8 6.2 L11.6 9.8"/>',
    "check": '<path d="M3.4 8.4 L6.6 11.4 L12.6 4.8"/>',
}


def _svg(name: str, body: str) -> str:
    if name == "check":
        color, background = WHITE, "#00000000"
    elif name in ("chevron-down", "chevron-up"):
        color, background = MUTED, "#00000000"
    else:
        color, background = STROKE, "#1B1F26"  # 齿轮镂空处填 surface 色
    body = body.replace("{color}", color).replace("{bg}", background)
    return _HEAD.format(color=color) + body + "</svg>\n"


def main() -> None:
    icons = ASSETS / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        path = icons / f"{name}.svg"
        # 固定 LF：素材文件在仓库里按 LF 存放，不受 Windows 换行设置影响。
        path.write_text(_svg(name, body), encoding="utf-8", newline="\n")
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
