"""Tests for picking a colour by left-clicking the screen filter image.

Behaviour under test:

- a left click on the displayed image samples the *displayed* (filtered) pixel
  and emits ``ScreenFilterWindow.colorPicked(r, g, b)``;
- clicks in the letterbox area around an aspect-fit image are ignored;
- the title bar briefly shows the picked HEX as feedback;
- the main window turns that picked colour into its current colour.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_screen_filter_pick_color.py
"""

import re
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from colorPickerPro.filter_lib import ImageFilter  # noqa: E402
from colorPickerPro.filter_scheme import FilterScheme  # noqa: E402

_APP = None


def _app() -> QApplication:
    global _APP
    if _APP is None:
        from colorPickerPro.ui import apply_theme, configure_application

        configure_application()
        _APP = QApplication.instance() or QApplication([])
        apply_theme(_APP)
    return _APP


def _scheme() -> FilterScheme:
    return FilterScheme.single(ImageFilter.all_filters()[0])


def _solid_pixmap(width: int, height: int, color: str) -> QPixmap:
    _app()
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return QPixmap.fromImage(image)


@contextmanager
def _filter_window(pixmap: QPixmap | None = None):
    from colorPickerPro.screenFilter import ScreenFilterWindow

    _app()
    win = ScreenFilterWindow(_scheme())
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    _app().processEvents()
    win._auto_collapse_timer.stop()
    if pixmap is not None:
        win._content.setPixmap(pixmap)
        _app().processEvents()
    try:
        yield win
    finally:
        win._pick_hint_timer.stop()
        win.stop()
        win.close()
        win.deleteLater()
        _app().processEvents()


def _collect(win):
    picked = []
    win.colorPicked.connect(lambda r, g, b: picked.append((r, g, b)))
    return picked


def _click_content(win, pos: QPoint) -> None:
    QTest.mouseClick(win._content, Qt.MouseButton.LeftButton, pos=pos)
    _app().processEvents()


def _send_mouse(win, kind, pos: QPoint, button, buttons) -> None:
    """向内容控件发鼠标事件（会冒泡到窗口，模拟真实点击/拖动路径）。"""
    target = win._content
    global_pos = target.mapToGlobal(pos)
    event = QMouseEvent(
        kind, QPointF(pos), QPointF(global_pos), button, buttons,
        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, event)
    _app().processEvents()


def _quadrant_pixmap() -> QPixmap:
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    for y in range(4):
        for x in range(4):
            image.setPixelColor(x, y, QColor("#FF0000") if x < 2
                                else QColor("#0000FF"))
    return QPixmap.fromImage(image)


def _quadrant_click_points(win, pixmap):
    """返回 (左半边点, 右半边点) 的内容控件坐标。"""
    inner = win._content.rect()
    scaled = pixmap.scaled(
        inner.size(), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    left = (inner.width() - scaled.width()) // 2
    top = (inner.height() - scaled.height()) // 2
    y = top + scaled.height() // 2
    red_point = QPoint(left + max(1, scaled.width() // 8), y)
    blue_point = QPoint(
        left + scaled.width() - max(1, scaled.width() // 8), y)
    return red_point, blue_point


def test_left_click_emits_picked_color_and_hex_hint():
    with _filter_window(_solid_pixmap(40, 30, "#0A141E")) as win:
        picked = _collect(win)
        _click_content(win, win._content.rect().center())
        assert picked == [(10, 20, 30)], picked
        assert "#0A141E" in win.title_bar.subtitle_label.full_text(), (
            win.title_bar.subtitle_label.full_text())
        assert win._pick_hint_timer.isActive(), "取色后应短暂显示 HEX 提示"


def test_pick_hint_clears():
    with _filter_window(_solid_pixmap(20, 20, "#336699")) as win:
        picked = _collect(win)
        _click_content(win, win._content.rect().center())
        assert picked
        win._clear_pick_hint()
        assert win.title_bar.subtitle_label.full_text() == ""


def test_letterbox_click_is_ignored():
    # 很宽的长条图放进近方形的内容区：上下会留白，点留白不应取色。
    with _filter_window(_solid_pixmap(200, 10, "#FFFFFF")) as win:
        picked = _collect(win)
        rect = win._content.rect()
        _click_content(win, QRect(rect).topLeft() + QPoint(2, 2))
        assert picked == [], f"点在留白区域不应取色: {picked}"


def test_click_without_image_does_nothing():
    with _filter_window() as win:
        picked = _collect(win)
        _click_content(win, win._content.rect().center())
        assert picked == [], picked
        assert win.title_bar.subtitle_label.full_text() == ""


def test_pixel_mapping_uses_source_pixels():
    _app()
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    for y in range(4):
        for x in range(4):
            image.setPixelColor(x, y, QColor("#FF0000") if x < 2
                                else QColor("#0000FF"))
    pixmap = QPixmap.fromImage(image)
    with _filter_window(pixmap) as win:
        picked = _collect(win)
        inner = win._content.rect()
        scaled = pixmap.scaled(
            inner.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        left = (inner.width() - scaled.width()) // 2
        top = (inner.height() - scaled.height()) // 2

        # 左半边（缩放后约 1/8 处）应映射到源图 x=0，红色。
        _click_content(win, QPoint(left + max(1, scaled.width() // 8),
                                   top + scaled.height() // 2))
        # 右半边（约 7/8 处）应映射到源图 x=3，蓝色。
        _click_content(win, QPoint(left + scaled.width()
                                   - max(1, scaled.width() // 8),
                                   top + scaled.height() // 2))
        assert len(picked) == 2, picked
        assert picked[0] == (255, 0, 0), picked
        assert picked[1] == (0, 0, 255), picked


def test_main_window_applies_picked_color():
    import colorPickerPro.main as main_module

    class _NoStartScreenFilter(main_module.ScreenFilterWindow):
        """只验证信号接线：不要在测试里真的开始屏幕捕获。"""

        def start(self):
            pass

    _app()
    original = main_module.ScreenFilterWindow
    main_module.ScreenFilterWindow = _NoStartScreenFilter
    win = main_module.MainWindow()
    try:
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.show()
        _app().processEvents()
        win._auto_collapse_timer.stop()
        win._create_screen_filter(_scheme())
        assert len(win._filter_windows) == 1
        filter_win = win._filter_windows[0]
        assert filter_win._color_formatter is not None, (
            "主窗口应把颜色提示格式化方法注入滤镜窗口")
        filter_win.colorPicked.emit(10, 20, 30)
        _app().processEvents()
        r, g, b = win._model.to_srgb_tuple()
        assert abs(r * 255 - 10) <= 1, (r, g, b)
        assert abs(g * 255 - 20) <= 1, (r, g, b)
        assert abs(b * 255 - 30) <= 1, (r, g, b)
    finally:
        main_module.ScreenFilterWindow = original
        win._auto_collapse_timer.stop()
        win._sync.stop_thread()
        win.close()
        win.deleteLater()
        _app().processEvents()


def test_model_format_srgb_all_models():
    from colorPickerPro.color_picker_widgets import ALL_MODELS

    for name, model_cls in ALL_MODELS.items():
        model = model_cls()
        text = model.format_srgb(0.2, 0.5, 0.8)
        assert text and "nan" not in text.lower(), (name, text)
        parts = text.split(" ")
        assert len(parts) == 3, (name, text)
        for part, param_name, decimals in zip(
                parts, model.param_names, model.param_decimals):
            pattern = rf"^{re.escape(param_name)}-(-?\d+\.\d{{{decimals}}})$"
            assert re.match(pattern, part), (name, part, pattern)


def test_continuous_pick_while_dragging():
    pixmap = _quadrant_pixmap()
    with _filter_window(pixmap) as win:
        win._continuous_pick_interval = 0.0    # 测试里不节流
        picked = _collect(win)
        red_point, blue_point = _quadrant_click_points(win, pixmap)

        _send_mouse(win, QEvent.Type.MouseButtonPress, red_point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        middle = QPoint((red_point.x() + blue_point.x()) // 2,
                        red_point.y())
        _send_mouse(win, QEvent.Type.MouseMove, middle,
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        _send_mouse(win, QEvent.Type.MouseMove, blue_point,
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        _send_mouse(win, QEvent.Type.MouseButtonRelease, blue_point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)

        assert len(picked) >= 3, (
            f"按住左键拖动应连续取色，实际只发出 {len(picked)} 次: {picked}")
        assert picked[0] == (255, 0, 0), picked
        assert picked[-1] == (0, 0, 255), picked
        assert win.title_bar.subtitle_label.full_text().startswith("#")


def test_continuous_pick_is_throttled():
    pixmap = _quadrant_pixmap()
    with _filter_window(pixmap) as win:
        win._continuous_pick_interval = 10.0   # 模拟节流窗口很大
        picked = _collect(win)
        red_point, blue_point = _quadrant_click_points(win, pixmap)
        _send_mouse(win, QEvent.Type.MouseButtonPress, red_point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        _send_mouse(win, QEvent.Type.MouseMove, blue_point,
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        assert len(picked) == 1, f"节流期间不应重复发取色: {picked}"
        _send_mouse(win, QEvent.Type.MouseButtonRelease, blue_point,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        assert len(picked) == 1, picked


def test_hint_uses_current_color_model_style():
    import colorPickerPro.main as main_module

    class _NoStartScreenFilter(main_module.ScreenFilterWindow):
        def start(self):
            pass

    _app()
    original = main_module.ScreenFilterWindow
    main_module.ScreenFilterWindow = _NoStartScreenFilter
    win = main_module.MainWindow()
    try:
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.show()
        _app().processEvents()
        win._auto_collapse_timer.stop()
        win._create_screen_filter(_scheme())
        filter_win = win._filter_windows[0]
        assert filter_win._color_formatter is not None, (
            "主窗口应把当前颜色模型的格式化方法注入滤镜窗口")

        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("#336699"))
        filter_win._content.setPixmap(QPixmap.fromImage(image))
        _app().processEvents()

        filter_win._pick_color_from_image(
            filter_win._content.mapToGlobal(filter_win._content.rect().center()),
            force=True)
        assert filter_win.title_bar.subtitle_label.full_text() == (
            win._format_picked_color(0x33, 0x66, 0x99)), (
            filter_win.title_bar.subtitle_label.full_text())
        assert "L-" in filter_win.title_bar.subtitle_label.full_text() or (
            "H-" in filter_win.title_bar.subtitle_label.full_text())

        # 切换主窗口颜色模型后，同一滤镜窗口的提示样式应立即跟着变。
        win._combo.setCurrentText("HSV")
        _app().processEvents()
        expected = win._format_picked_color(0x33, 0x66, 0x99)
        assert expected.startswith("H-"), expected
        filter_win._pick_color_from_image(
            filter_win._content.mapToGlobal(filter_win._content.rect().center()),
            force=True)
        assert filter_win.title_bar.subtitle_label.full_text() == expected, (
            filter_win.title_bar.subtitle_label.full_text(), expected)
    finally:
        main_module.ScreenFilterWindow = original
        win._auto_collapse_timer.stop()
        win._sync.stop_thread()
        win.close()
        win.deleteLater()
        _app().processEvents()


def test_custom_color_formatter_is_used():
    with _filter_window(_solid_pixmap(20, 20, "#336699")) as win:
        win.set_color_formatter(
            lambda r, g, b: f"R{r} G{g} B{b}")
        _click_content(win, win._content.rect().center())
        assert win.title_bar.subtitle_label.full_text() == "R51 G102 B153", (
            win.title_bar.subtitle_label.full_text())


# ---------------------------------------------------------------------------
# runner (stdlib only)
# ---------------------------------------------------------------------------

def _main() -> int:
    tests = [
        test_left_click_emits_picked_color_and_hex_hint,
        test_pick_hint_clears,
        test_letterbox_click_is_ignored,
        test_click_without_image_does_nothing,
        test_pixel_mapping_uses_source_pixels,
        test_main_window_applies_picked_color,
        test_model_format_srgb_all_models,
        test_continuous_pick_while_dragging,
        test_continuous_pick_is_throttled,
        test_hint_uses_current_color_model_style,
        test_custom_color_formatter_is_used,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    print(f"\n共 {len(tests)} 项检查，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
