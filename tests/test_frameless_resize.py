"""Regression tests for frameless window edge resizing after close/reopen.

The resize implementation is an application-level event filter installed by
``FramelessWindowMixin``.  ``closeEvent()`` removes that filter, but windows
can be shown again (the "滤镜方案" panel is reused between openings).  Without
re-installing on show, edge resizing and the resize cursor silently stop
working for the rest of that window's life.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_frameless_resize.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from colorPickerPro.ui.components import FramelessWindowMixin  # noqa: E402

_APP = None


def _app() -> QApplication:
    global _APP
    if _APP is None:
        from colorPickerPro.ui import apply_theme, configure_application

        configure_application()
        _APP = QApplication.instance() or QApplication([])
        apply_theme(_APP)
    return _APP


class _TestWindow(FramelessWindowMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(1, 1, 1, 1)
        self.init_frameless("缩放测试", layout=self._root,
                            show_close=True, resizable=True)
        self.setMinimumSize(300, 200)
        self.resize(400, 300)


def _show_hidden(win) -> None:
    _app()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    _app().processEvents()


def _send(kind, widget, local: QPoint, button, buttons) -> None:
    global_pos = widget.mapToGlobal(local)
    event = QMouseEvent(
        kind, QPointF(local), QPointF(global_pos), button, buttons,
        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    _app().processEvents()


def _drag_right_edge(win, dx: int = 60) -> None:
    """抓住右边缘拖动，模拟真实的窗口缩放手势。"""
    height = win.height() // 2
    edge = QPoint(win.width() - 2, height)
    _send(QEvent.Type.MouseButtonPress, win, edge,
          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    target = QPoint(edge.x() + dx, height)
    _send(QEvent.Type.MouseMove, win, target,
          Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _send(QEvent.Type.MouseButtonRelease, win, target,
          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def _assert_resizable(win, label: str) -> None:
    before = win.width()
    _drag_right_edge(win)
    assert win.width() >= before + 40, (
        f"{label}: 右边缘拖拽没有缩放窗口（{before} -> {win.width()}）")


def test_resize_works_on_first_show():
    _app()
    win = _TestWindow()
    try:
        _show_hidden(win)
        assert win._frameless_filter_installed is True
        _assert_resizable(win, "首次显示")
    finally:
        win.close()
        win.deleteLater()
        _app().processEvents()


def test_resize_works_after_hide_and_show():
    _app()
    win = _TestWindow()
    try:
        _show_hidden(win)
        win.hide()
        _app().processEvents()
        _show_hidden(win)
        _assert_resizable(win, "隐藏后再次显示")
    finally:
        win.close()
        win.deleteLater()
        _app().processEvents()


def test_resize_works_after_close_and_reopen():
    _app()
    win = _TestWindow()
    try:
        _show_hidden(win)
        _assert_resizable(win, "首次显示")
        win.close()
        _app().processEvents()
        assert win._frameless_filter_installed is False, (
            "close 后应移除应用级事件过滤器")
        _show_hidden(win)
        assert win._frameless_filter_installed is True, (
            "再次 show 应重新安装应用级事件过滤器")
        _assert_resizable(win, "关闭后再次显示")
    finally:
        win.close()
        win.deleteLater()
        _app().processEvents()


def test_filter_scheme_panel_resize_after_reopen():
    """用户实际场景：滤镜方案面板关掉后再次打开仍能缩放。"""
    from colorPickerPro.filter_lib import ImageFilter
    from colorPickerPro.filter_scheme import FilterScheme
    from colorPickerPro.filter_scheme_panel import FilterSchemePanel

    _app()
    panel = FilterSchemePanel(
        FilterScheme.single(ImageFilter.all_filters()[0]))
    try:
        _show_hidden(panel)
        _assert_resizable(panel, "滤镜方案面板首次打开")
        panel.close()
        _app().processEvents()
        _show_hidden(panel)
        _assert_resizable(panel, "滤镜方案面板关闭后再次打开")
    finally:
        panel.close()
        panel.deleteLater()
        _app().processEvents()


# ---------------------------------------------------------------------------
# runner (stdlib only)
# ---------------------------------------------------------------------------

def _main() -> int:
    tests = [
        test_resize_works_on_first_show,
        test_resize_works_after_hide_and_show,
        test_resize_works_after_close_and_reopen,
        test_filter_scheme_panel_resize_after_reopen,
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
