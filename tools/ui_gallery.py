"""Render a gallery of the shared UI components to PNG (design-system check)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from colorPickerPro.ui import configure_application, apply_theme  # noqa: E402
from colorPickerPro.ui.components import (  # noqa: E402
    Badge, Card, ColorSwatch, DangerButton, Divider, FramelessWindowMixin,
    GhostButton, IconButton, MonoLabel, PrimaryButton, ScrollArea,
    SecondaryButton, StatusLabel, SubtitleLabel, ThemedDialog, TitleLabel,
    flow, hbox, vbox,
)
from colorPickerPro.ui.tokens import SPACE, State  # noqa: E402

configure_application()
app = QApplication(sys.argv)
apply_theme(app)

OUT = ROOT / "build" / "ui-gallery"
OUT.mkdir(parents=True, exist_ok=True)


class GalleryWindow(FramelessWindowMixin, QMainWindow):
    """Design-system preview window with the shared custom chrome."""


def build_window() -> GalleryWindow:
    win = GalleryWindow()
    win.setWindowTitle("pixnex 组件库")
    root = QWidget()
    root.setObjectName("AppRoot")
    outer = QVBoxLayout(root)
    outer.setContentsMargins(1, 1, 1, 1)
    outer.setSpacing(0)
    win.init_frameless("pixnex · 组件库", layout=outer, subtitle="组件预览",
                       show_minimize=True, show_maximize=True, show_close=True)
    win.setCentralWidget(root)

    body = QWidget()
    body.setObjectName("FramelessBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(
        SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
    body_layout.setSpacing(SPACE.md)
    outer.addWidget(body, 1)

    header = hbox(None)
    header.addWidget(TitleLabel("色彩工具"))
    header.addStretch(1)
    header.addWidget(Badge("v0.1"))
    body_layout.addLayout(header)
    body_layout.addWidget(SubtitleLabel("现代扁平组件预览", word_wrap=False))

    scroll = ScrollArea()
    inner = QWidget()
    inner.setObjectName("AppRoot")
    content = QVBoxLayout(inner)
    content.setContentsMargins(0, 0, 0, 0)
    content.setSpacing(SPACE.md)
    scroll.setWidget(inner)
    body_layout.addWidget(scroll, 1)

    card = Card("选色模型")
    row = hbox(QLabel("颜色模型"))
    combo = QComboBox()
    combo.addItems(["OKLCH", "HSV", "CIE LCH", "CIE Lab", "HSI"])
    row.addWidget(combo, 1)
    row.addWidget(PrimaryButton("应用"))
    card.add_layout(row)
    content.addWidget(card)

    card2 = Card("滑块")
    for name in ("L", "C", "H"):
        row = hbox(QLabel(name))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(45)
        row.addWidget(slider, 1)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(45)
        row.addWidget(spin)
        card2.add_layout(row)
    card2.add_layout(hbox(QCheckBox("启用"), QCheckBox("显示预览")))

    swatch_row = hbox(QLabel("颜色"), None)
    row2 = hbox()
    swatch_row.addStretch(1)
    swatch_row.addWidget(ColorSwatch(QColor("#4C8DFF")))
    card2.add_layout(swatch_row)
    content.addWidget(card2)

    card3 = Card("状态与操作")
    status_row = hbox(StatusLabel("已同步", State.SUCCESS), None)
    status_row.addStretch(1)
    status_row.addWidget(StatusLabel("未连接", State.DANGER))
    card3.add_layout(status_row)
    card3.add_layout(hbox(
        PrimaryButton("确定"), SecondaryButton("取消"),
        DangerButton("删除"), GhostButton("更多")))
    buttons = flow(
        IconButton("close", tooltip="关闭"),
        IconButton("minimize", tooltip="最小化"),
        IconButton("play", tooltip="继续"),
        IconButton("settings", tooltip="设置"),
        GhostButton("适应"), GhostButton("旋转"), GhostButton("翻转"),
        GhostButton("复位"), GhostButton("导出"), GhostButton("导入"),
    )
    holder = QWidget()
    holder.setLayout(buttons)
    card3.add(holder)
    card3.add_layout(hbox(QLineEdit(placeholderText="搜索滤镜…"), MonoLabel("#4C8DFF")))

    lst = QListWidget()
    for name in ("边缘检测", "反相", "棕褐", "Lab 灰度"):
        lst.addItem(name)
    lst.setCurrentRow(0)
    lst.setMaximumHeight(150)
    card3.add(lst)
    content.addWidget(card3)

    content.addWidget(Divider())
    content.addWidget(SubtitleLabel("底部说明文字", word_wrap=True))
    content.addStretch(1)

    win.setCentralWidget(root)
    return win


def build_dialog() -> ThemedDialog:
    dialog = ThemedDialog("滤镜方案", "管理应用顺序与参数")
    dialog.make_body_scrollable()
    form = Card("图层")
    form.add_layout(hbox(QComboBox(), PrimaryButton("添加")))
    for name in ("边缘检测", "反相", "棕褐"):
        form.add_layout(hbox(QLabel(name), None, IconButton("✕", danger=True)))
    dialog.add_content(form)
    dialog.add_content(Divider())
    dialog.add_content(SubtitleLabel(
        "这是一段较长的说明文字，用来检查换行与间距是否符合预期。"))
    dialog.add_reject_button()
    dialog.add_accept_button()
    dialog.resize(520, 420)
    return dialog


win = build_window()
win.resize(420, 900)
win.grab().save(str(OUT / "gallery_420x900.png"))
win.resize(760, 620)
win.grab().save(str(OUT / "gallery_760x620.png"))

dlg = build_dialog()
dlg.grab().save(str(OUT / "dialog_520x420.png"))
print("saved to", OUT)
