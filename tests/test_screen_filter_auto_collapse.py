"""Tests for the screen filter window's auto-collapse button.

Behaviour under test:

- the title bar has a checkable auto-collapse button (defaults off);
- when enabled, the window folds to its title bar when the cursor leaves and
  expands again when the cursor enters;
- any *manual* collapse / expand (double-click title bar, space key) turns the
  auto-collapse switch off, and the manual action itself still applies.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_screen_filter_auto_collapse.py
"""

import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from colorPickerPro.filter_lib import ImageFilter  # noqa: E402
from colorPickerPro.filter_scheme import FilterScheme  # noqa: E402
from colorPickerPro.ui.tokens import SIZE  # noqa: E402

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


def _hidden(widget: QWidget) -> QWidget:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    _app().processEvents()
    return widget


@contextmanager
def _filter_window():
    from colorPickerPro import screenFilter as screen_filter_module
    from colorPickerPro.screenFilter import ScreenFilterWindow

    _app()
    # 测试机上的真实鼠标点击不应干扰自动折叠断言：固定「未按鼠标」。
    original_guard = screen_filter_module.mouse_button_pressed
    screen_filter_module.mouse_button_pressed = lambda: False
    win = ScreenFilterWindow(_scheme())
    _hidden(win)
    win._auto_collapse_timer.stop()   # 测试里手动驱动，避免真实光标干扰
    try:
        yield win
    finally:
        win.stop()
        win._auto_collapse_timer.stop()
        win.close()
        win.deleteLater()
        screen_filter_module.mouse_button_pressed = original_guard
        _app().processEvents()


def _enable_auto_collapse(win) -> None:
    win._btn_auto_collapse.setChecked(True)
    _app().processEvents()
    win._auto_collapse_timer.stop()


def _outside() -> QPoint:
    return QPoint(-99999, -99999)


def _fold_now(win) -> None:
    """驱动自动折叠：先记录「离开窗口」，再跨过 1 秒延迟。"""
    win._auto_collapse_step(_outside(), now=0.0)
    win._auto_collapse_step(_outside(), now=2.0)


def test_button_defaults_off():
    with _filter_window() as win:
        button = getattr(win, "_btn_auto_collapse", None)
        assert button is not None, "屏幕滤镜窗口缺少自动折叠按钮"
        assert button.icon_name() == "collapse", button.icon_name()
        assert button.isCheckable()
        assert not button.icon().isNull()
        assert button.isChecked() is False
        assert win._auto_collapse_enabled is False
        assert win._auto_collapse_timer.isActive() is False


def test_auto_collapse_folds_and_restores():
    with _filter_window() as win:
        size_before = win.size()
        _enable_auto_collapse(win)
        assert win._auto_collapse_enabled is True

        win._auto_collapse_step(_outside(), now=0.0)
        assert not win.is_collapsed(), "刚离开不应立即折叠"
        win._auto_collapse_step(_outside(), now=0.5)
        assert not win.is_collapsed(), "离开不足 1 秒不应折叠"

        # 1 秒内回到窗口：取消等待
        win._auto_collapse_step(win.geometry().center(), now=0.6)
        assert not win.is_collapsed()

        # 再次离开并超过 1 秒：折叠
        win._auto_collapse_step(_outside(), now=1.0)
        win._auto_collapse_step(_outside(), now=2.01)
        assert win.is_collapsed(), "鼠标离开超过 1 秒后屏幕滤镜窗口没有折叠"
        assert win.height() == SIZE.title_bar_height + 2, win.height()
        assert win._content_host.isHidden()

        # 展开仍立即生效
        win._auto_collapse_step(win.geometry().center(), now=2.02)
        assert not win.is_collapsed(), "鼠标进入标题栏后屏幕滤镜窗口没有立即展开"
        assert win._content_host.isVisible()
        assert win.size() == size_before, (win.size(), size_before)


def test_manual_collapse_disables_auto_collapse():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        win.toggle_collapse()   # 模拟双击标题栏 / 空格键
        assert win.is_collapsed(), "手动折叠没有生效"
        assert win._auto_collapse_enabled is False, "手动折叠应同时关闭自动折叠"
        assert win._btn_auto_collapse.isChecked() is False
        assert win._auto_collapse_timer.isActive() is False
        # 自动折叠已关闭：鼠标离开不应再收起（此时已折叠，先手动展开）。
        win.toggle_collapse()
        assert not win.is_collapsed()
        assert win._auto_collapse_enabled is False
        win._auto_collapse_step(_outside())
        assert not win.is_collapsed(), "自动折叠已关闭后不应再折叠"


def test_titlebar_double_click_disables_auto_collapse():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        win.title_bar.collapseRequested.emit()   # 双击标题栏走的就是这个信号
        assert win.is_collapsed()
        assert win._auto_collapse_enabled is False
        assert win._btn_auto_collapse.isChecked() is False
        win.title_bar.collapseRequested.emit()
        assert not win.is_collapsed(), "再次手动操作应正常展开"
        assert win._auto_collapse_enabled is False, "手动展开后自动折叠仍应关闭"


def test_manual_expand_of_auto_collapsed_window_disables_auto():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        _fold_now(win)
        assert win.is_collapsed()
        win.toggle_collapse()   # 手动展开
        assert not win.is_collapsed(), "手动展开没有生效"
        assert win._auto_collapse_enabled is False, (
            "手动展开应同时关闭自动折叠")


def test_turning_switch_off_expands_collapsed_window():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        _fold_now(win)
        assert win.is_collapsed()
        win._btn_auto_collapse.setChecked(False)
        _app().processEvents()
        assert not win.is_collapsed(), "关闭自动折叠开关后窗口应恢复展开"
        assert win._auto_collapse_timer.isActive() is False


def test_visible_scheme_panel_blocks_auto_collapse():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        panel = QWidget()
        panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        panel.show()
        _app().processEvents()
        win._scheme_panel = panel
        try:
            win._auto_collapse_step(_outside())
            assert not win.is_collapsed(), (
                "方案面板打开时（鼠标在窗口外属正常）不应自动折叠")
        finally:
            win._scheme_panel = None
            panel.close()
            panel.deleteLater()
            _app().processEvents()


def test_hide_stops_auto_collapse_timer():
    with _filter_window() as win:
        _enable_auto_collapse(win)
        win._sync_auto_collapse_timer()
        assert win._auto_collapse_timer.isActive()
        win.hide()
        _app().processEvents()
        assert win._auto_collapse_timer.isActive() is False
        _hidden(win)
        assert win._auto_collapse_timer.isActive(), "重新显示后轮询应恢复"


# ---------------------------------------------------------------------------
# runner (stdlib only)
# ---------------------------------------------------------------------------

def _main() -> int:
    tests = [
        test_button_defaults_off,
        test_auto_collapse_folds_and_restores,
        test_manual_collapse_disables_auto_collapse,
        test_titlebar_double_click_disables_auto_collapse,
        test_manual_expand_of_auto_collapsed_window_disables_auto,
        test_turning_switch_off_expands_collapsed_window,
        test_visible_scheme_panel_blocks_auto_collapse,
        test_hide_stops_auto_collapse_timer,
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
