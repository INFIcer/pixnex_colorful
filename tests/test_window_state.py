"""Regression tests for the main window's auto-collapse + state persistence.

Covered behaviour:

- ``WindowStateStore`` round-trips auto-collapse / always-on-top / geometry,
  and never shares memory between stores;
- restored geometry is clamped onto an existing screen (multi-monitor safety);
- ``MainWindow`` restores its saved state and saves it again on close, also
  when the window is collapsed (it must save the *expanded* size);
- auto-collapse folds the window to the title bar when the cursor leaves and
  expands it again when the cursor enters, and never folds while disabled.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_window_state.py
"""

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from colorPickerPro.ui.tokens import SIZE  # noqa: E402
from colorPickerPro.window_state import (  # noqa: E402
    WindowState,
    WindowStateStore,
    clamp_geometry,
    screen_available_rects,
)

_APP = None


def _app() -> QApplication:
    """Create the single QApplication on first use (Windows platform plugin)."""
    global _APP
    if _APP is None:
        from colorPickerPro.ui import apply_theme, configure_application

        configure_application()
        _APP = QApplication.instance() or QApplication([])
        apply_theme(_APP)
    return _APP


def _temp_store() -> WindowStateStore:
    """File-backed store in a throw-away INI file."""
    path = Path(tempfile.mkdtemp(prefix="pixnex-state-")) / "state.ini"
    return WindowStateStore(QSettings(str(path), QSettings.Format.IniFormat))


@contextmanager
def _shown_window(store: WindowStateStore | None = None,
                  stop_auto_timer: bool = True,
                  stub_mouse_guard: bool = True):
    """Build a never-visible MainWindow (WA_DontShowOnScreen) and clean it up.

    ``stub_mouse_guard`` 把物理鼠标按键判断替换为「未按下」：测试机上的真实
    鼠标点击/自动化输入不应让自动折叠断言变成偶发失败。物理按键兜底逻辑由
    ``test_mouse_button_pressed_falls_back_to_qt_state`` 单独验证。
    """
    app = _app()
    from colorPickerPro import main as main_module

    original_guard = main_module.mouse_button_pressed
    if stub_mouse_guard:
        main_module.mouse_button_pressed = lambda: False
    win = None
    try:
        win = main_module.MainWindow(store)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.show()
        app.processEvents()
        if stop_auto_timer:
            # 测试里手动调用 _auto_collapse_step，避免真实光标/定时器引入抖动。
            win._auto_collapse_timer.stop()
        yield win
    finally:
        if win is not None:
            win._auto_collapse_timer.stop()
            win._sync.stop_thread()
            win.close()
            win.deleteLater()
            app.processEvents()
        main_module.mouse_button_pressed = original_guard


_OUTSIDE = QPoint(-99999, -99999)


def _fold_now(win) -> None:
    """驱动自动折叠：先记录「离开窗口」，再跨过 1 秒延迟。"""
    win._auto_collapse_step(_OUTSIDE, now=0.0)
    win._auto_collapse_step(_OUTSIDE, now=2.0)


# ---------------------------------------------------------------------------
# WindowStateStore
# ---------------------------------------------------------------------------

def test_memory_store_defaults():
    state = WindowStateStore().load()
    assert state == WindowState(), state


def test_memory_store_roundtrip():
    store = WindowStateStore()
    saved = WindowState(auto_collapse=True, always_on_top=True,
                        geometry=(10, 20, 430, 710))
    store.save(saved)
    assert store.load() == saved


def test_memory_stores_are_isolated():
    first, second = WindowStateStore(), WindowStateStore()
    first.save(WindowState(True, True, (1, 2, 3, 4)))
    assert second.load() == WindowState()
    assert first.load() == WindowState(True, True, (1, 2, 3, 4))


def test_ini_store_roundtrip():
    path = Path(tempfile.mkdtemp(prefix="pixnex-state-")) / "state.ini"
    first = WindowStateStore(QSettings(str(path), QSettings.Format.IniFormat))
    assert first.load() == WindowState()
    saved = WindowState(auto_collapse=True, always_on_top=False,
                        geometry=(140, 160, 420, 700))
    first.save(saved)
    # 用新的 QSettings 实例重新读磁盘：确认真的落盘而不是留在缓存里。
    second = WindowStateStore(QSettings(str(path), QSettings.Format.IniFormat))
    assert second.load() == saved
    assert path.exists(), f"QSettings 没有写出 INI: {path}"


def test_ini_store_ignores_broken_geometry():
    store = _temp_store()
    store._settings.setValue("main_window/x", 100)
    store._settings.setValue("main_window/y", 200)
    store._settings.setValue("main_window/width", 0)
    store._settings.setValue("main_window/height", -20)
    assert store.load().geometry is None


def test_geometry_none_clears_saved_position():
    store = _temp_store()
    store.save(WindowState(geometry=(10, 20, 430, 710)))
    store.save(WindowState())
    assert store.load() == WindowState()


# ---------------------------------------------------------------------------
# clamp_geometry
# ---------------------------------------------------------------------------

def test_clamp_geometry_keeps_inside_rect_untouched():
    screen = QRect(0, 0, 1920, 1040)
    rect = QRect(100, 120, 430, 710)
    assert clamp_geometry(rect, [screen], QSize(320, 460)) == rect


def test_clamp_geometry_moves_offscreen_window_back():
    screen = QRect(0, 0, 1920, 1040)
    rect = QRect(-5000, -5000, 430, 710)
    fitted = clamp_geometry(rect, [screen], QSize(320, 460))
    assert screen.contains(fitted), fitted
    assert fitted.size() == QSize(430, 710), fitted


def test_clamp_geometry_shrinks_oversized_window():
    screen = QRect(0, 0, 1920, 1040)
    fitted = clamp_geometry(QRect(0, 0, 99999, 99999), [screen],
                            QSize(320, 460))
    assert fitted == screen, fitted


def test_clamp_geometry_respects_second_screen():
    screens = [QRect(0, 0, 1920, 1040), QRect(1920, 0, 1920, 1040)]
    fitted = clamp_geometry(QRect(2000, 100, 430, 710), screens,
                            QSize(320, 460))
    assert screens[1].contains(fitted), fitted


def test_clamp_geometry_requires_min_size():
    screen = QRect(0, 0, 1920, 1040)
    fitted = clamp_geometry(QRect(10, 10, 100, 100), [screen],
                            QSize(320, 460))
    assert fitted.size() == QSize(320, 460), fitted


# ---------------------------------------------------------------------------
# MainWindow: restore / save
# ---------------------------------------------------------------------------

def test_main_window_restores_saved_state():
    store = _temp_store()
    store.save(WindowState(auto_collapse=True, always_on_top=True,
                           geometry=(200, 150, 430, 700)))
    with _shown_window(store) as win:
        expected = clamp_geometry(
            QRect(200, 150, 430, 700), screen_available_rects(),
            QSize(win.minimumWidth(), win.minimumHeight()))
        assert win.geometry() == expected, (win.geometry(), expected)
        assert win._auto_collapse_btn.isChecked()
        assert win._auto_collapse_enabled is True
        assert win._pin_btn.isChecked()
        assert win._always_on_top is True
        assert win.is_collapsed() is False
        # 可见 + 开关打开 → 轮询定时器应能启动（showEvent 里也走同一逻辑）。
        win._update_auto_collapse_timer()
        assert win._auto_collapse_timer.isActive(), (
            "开启自动折叠后窗口可见时轮询应已启动")
        win._auto_collapse_timer.stop()


def test_main_window_defaults_without_saved_state():
    with _shown_window() as win:
        assert win.size() == QSize(380, 640), win.size()
        assert win._auto_collapse_btn.isChecked() is False
        assert win._pin_btn.isChecked() is False
        assert win._auto_collapse_timer.isActive() is False


def test_main_window_restores_clamped_geometry():
    store = _temp_store()
    store.save(WindowState(geometry=(-5000, -5000, 430, 710)))
    screens = screen_available_rects()
    with _shown_window(store) as win:
        expected = clamp_geometry(
            QRect(-5000, -5000, 430, 710), screens,
            QSize(win.minimumWidth(), win.minimumHeight()))
        assert any(screen.contains(win.geometry()) for screen in screens), (
            f"恢复的窗口不在任何屏幕内: {win.geometry()} / {screens}")
        assert win.size() == expected.size(), (win.size(), expected.size())


def test_close_saves_geometry_and_toggles():
    store = _temp_store()
    with _shown_window(store) as win:
        win.resize(430, 710)
        win.move(140, 160)
        win._auto_collapse_btn.setChecked(True)
        win._auto_collapse_timer.stop()
        win._pin_btn.setChecked(True)
        _app().processEvents()
        # 开关状态应当立即保存，而不是等退出。
        immediate = store.load()
        assert immediate.auto_collapse is True, immediate
        assert immediate.always_on_top is True, immediate
    saved = store.load()
    assert saved.auto_collapse is True, saved
    assert saved.always_on_top is True, saved
    assert saved.geometry == (140, 160, 430, 710), saved.geometry


def test_close_while_collapsed_saves_expanded_geometry():
    store = _temp_store()
    with _shown_window(store) as win:
        win.resize(430, 710)
        win.move(140, 160)
        win._auto_collapse_btn.setChecked(True)
        win._auto_collapse_timer.stop()
        _fold_now(win)
        assert win.is_collapsed()
        assert win.height() == SIZE.title_bar_height + 2
        # 退出时窗口仍处于折叠状态：保存的必须是展开后的尺寸。
    saved = store.load()
    assert saved.geometry is not None, saved
    assert saved.geometry[2:] == (430, 710), saved.geometry
    assert saved.auto_collapse is True, saved


def test_auto_collapse_folds_and_restores():
    store = _temp_store()
    store.save(WindowState(auto_collapse=True, geometry=(150, 150, 400, 660)))
    with _shown_window(store) as win:
        expected = clamp_geometry(
            QRect(150, 150, 400, 660), screen_available_rects(),
            QSize(win.minimumWidth(), win.minimumHeight()))
        assert not win.is_collapsed()
        _fold_now(win)
        assert win.is_collapsed(), "鼠标离开后主窗口没有折叠"
        assert win.height() == SIZE.title_bar_height + 2, win.height()
        assert win._body.isHidden()
        assert win.width() == expected.width(), (win.width(), expected)

        win._auto_collapse_step(win.geometry().center())
        assert not win.is_collapsed(), "鼠标进入标题栏后主窗口没有展开"
        assert win._body.isVisible()
        assert win.size() == expected.size(), (win.size(), expected)
        assert not win._auto_collapse_timer.isActive(), (
            "_shown_window 已停掉定时器，测试里不应重新启动")


def test_auto_collapse_waits_one_second_before_folding():
    store = _temp_store()
    store.save(WindowState(auto_collapse=True, geometry=(150, 150, 400, 660)))
    with _shown_window(store) as win:
        inside = win.geometry().center()
        win._auto_collapse_step(_OUTSIDE, now=100.0)
        assert not win.is_collapsed(), "刚离开窗口不应立即折叠"
        win._auto_collapse_step(_OUTSIDE, now=100.9)
        assert not win.is_collapsed(), "离开不足 1 秒不应折叠"

        # 1 秒内回到窗口：取消等待，不折叠
        win._auto_collapse_step(inside, now=100.95)
        assert not win.is_collapsed()

        # 再次离开：重新从这一刻开始计时
        win._auto_collapse_step(_OUTSIDE, now=101.0)
        win._auto_collapse_step(_OUTSIDE, now=101.9)
        assert not win.is_collapsed(), "重新离开后不足 1 秒不应折叠"
        win._auto_collapse_step(_OUTSIDE, now=102.01)
        assert win.is_collapsed(), "离开超过 1 秒应折叠"

        # 展开不延迟：回到窗口立即展开
        win._auto_collapse_step(win.geometry().center(), now=102.02)
        assert not win.is_collapsed(), "展开应立即生效"


def test_auto_collapse_disabled_never_folds():
    with _shown_window() as win:
        win._auto_collapse_step(QPoint(-99999, -99999))
        assert not win.is_collapsed(), "自动折叠关闭时窗口不应折叠"


def test_turning_auto_collapse_off_expands():
    store = _temp_store()
    store.save(WindowState(auto_collapse=True, geometry=(150, 150, 400, 660)))
    with _shown_window(store) as win:
        expected = clamp_geometry(
            QRect(150, 150, 400, 660), screen_available_rects(),
            QSize(win.minimumWidth(), win.minimumHeight()))
        _fold_now(win)
        assert win.is_collapsed()
        win._auto_collapse_btn.setChecked(False)
        _app().processEvents()
        assert not win.is_collapsed(), "关闭自动折叠后窗口应恢复展开"
        assert win.height() == expected.height(), (win.height(), expected)


def test_manual_toggle_collapse_keeps_position():
    with _shown_window() as win:
        win.resize(400, 660)
        win.move(120, 130)
        _app().processEvents()
        win.toggle_collapse()
        assert win.is_collapsed()
        assert (win.x(), win.y()) == (120, 130), (win.x(), win.y())
        # 折叠状态下拖动标题栏后展开：使用新位置、原尺寸。
        win.move(220, 260)
        _app().processEvents()
        win.toggle_collapse()
        expected = clamp_geometry(
            QRect(220, 260, 400, 660), screen_available_rects(),
            QSize(win.minimumWidth(), win.minimumHeight()))
        assert not win.is_collapsed()
        assert (win.x(), win.y()) == (expected.x(), expected.y()), (
            win.geometry(), expected)
        assert win.size() == expected.size(), (win.size(), expected.size())


def test_screen_picker_cancel_resets_mouse_button_state():
    with _shown_window() as win:
        win._mouse_down = True
        win._screen_picker.cancelled.emit()
        assert win._mouse_down is False, (
            "取色器取消后 _mouse_down 应被复位，否则交互状态机卡住")


def test_auto_collapse_survives_stale_qt_mouse_state():
    if sys.platform != "win32":
        return
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    store = _temp_store()
    store.save(WindowState(auto_collapse=True, geometry=(150, 150, 400, 660)))
    app = _app()
    # 屏幕取色器场景：鼠标按下后覆盖层立即隐藏，松键事件不再进入本进程，
    # Qt 的 QApplication.mouseButtons() 会一直停在 LeftButton。
    grabber = QWidget()
    grabber.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    grabber.resize(100, 100)
    grabber.show()
    app.processEvents()
    try:
        with _shown_window(store) as win:
            QTest.mousePress(grabber, Qt.MouseButton.LeftButton,
                             pos=QPoint(50, 50))
            grabber.hide()
            app.processEvents()
            assert QApplication.mouseButtons() != Qt.MouseButton.NoButton, (
                "没能造出 Qt 按键状态残留，测试前提不成立")
            _fold_now(win)
            assert win.is_collapsed(), (
                "Qt 按键状态残留导致自动折叠失效（屏幕取色后无法折叠）")
            win._auto_collapse_step(win.geometry().center())
            assert not win.is_collapsed(), (
                "Qt 按键状态残留导致自动折叠后无法悬停展开")
    finally:
        grabber.show()
        app.processEvents()
        QTest.mouseRelease(grabber, Qt.MouseButton.LeftButton,
                           pos=QPoint(50, 50))
        grabber.close()
        grabber.deleteLater()
        app.processEvents()


def test_mouse_button_pressed_falls_back_to_qt_state():
    """非 Windows 分支（这里强制走回退）应读取 Qt 的按键状态。"""
    import colorPickerPro.auto_collapse as auto_module
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    app = _app()
    grabber = QWidget()
    grabber.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    grabber.resize(80, 80)
    grabber.show()
    app.processEvents()
    original_platform = auto_module.sys.platform
    try:
        QTest.mousePress(grabber, Qt.MouseButton.LeftButton,
                         pos=QPoint(40, 40))
        grabber.hide()
        app.processEvents()
        auto_module.sys.platform = "linux"   # 强制走 QApplication.mouseButtons()
        try:
            assert auto_module.mouse_button_pressed() is True, (
                "Qt 按键状态残留时，回退分支应返回 True")
        finally:
            auto_module.sys.platform = original_platform
    finally:
        grabber.show()
        app.processEvents()
        QTest.mouseRelease(grabber, Qt.MouseButton.LeftButton,
                           pos=QPoint(40, 40))
        grabber.close()
        grabber.deleteLater()
        app.processEvents()


def test_auto_collapse_ignores_maximized_window():
    store = _temp_store()
    store.save(WindowState(auto_collapse=True, geometry=(150, 150, 400, 660)))
    with _shown_window(store) as win:
        win.showMaximized()
        _app().processEvents()
        win._auto_collapse_timer.stop()
        assert win.isMaximized(), "测试前提不成立：窗口没有最大化"
        win._auto_collapse_step(QPoint(-99999, -99999))
        assert not win.is_collapsed(), "最大化窗口不应被折叠"
        assert win.isMaximized(), "自动折叠检查不应破坏最大化状态"
        win.showNormal()
        _app().processEvents()


def test_topmost_on_non_windows_keeps_window_visible():
    import colorPickerPro.main as main_module

    with _shown_window() as win:
        original = main_module.sys.platform
        try:
            main_module.sys.platform = "linux"   # 强制走 setWindowFlag 分支
            win._apply_topmost(True)
            _app().processEvents()
            assert win.isVisible(), "非 Windows 下切换置顶后窗口被隐藏"
            win._apply_topmost(False)
            _app().processEvents()
            assert win.isVisible(), "非 Windows 下取消置顶后窗口被隐藏"
        finally:
            main_module.sys.platform = original


def test_collapse_disables_edge_resizing():
    with _shown_window() as win:
        assert win._can_resize()
        win.toggle_collapse()
        assert not win._can_resize(), "折叠成标题栏后不应还能拖边缩放"
        win.toggle_collapse()
        assert win._can_resize()


def test_auto_collapse_button_is_in_title_bar():
    with _shown_window() as win:
        names = [
            getattr(win.title_bar.layout().itemAt(index).widget(),
                    "icon_name", lambda: "")()
            for index in range(win.title_bar.layout().count())
        ]
        assert "collapse" in names, names
        assert "pin" in names, names
        assert win._auto_collapse_btn.icon_name() == "collapse"
        assert win._auto_collapse_btn.isCheckable()
        assert not win._auto_collapse_btn.icon().isNull()


# ---------------------------------------------------------------------------
# runner (stdlib only)
# ---------------------------------------------------------------------------

def _main() -> int:
    tests = [
        test_memory_store_defaults,
        test_memory_store_roundtrip,
        test_memory_stores_are_isolated,
        test_ini_store_roundtrip,
        test_ini_store_ignores_broken_geometry,
        test_geometry_none_clears_saved_position,
        test_clamp_geometry_keeps_inside_rect_untouched,
        test_clamp_geometry_moves_offscreen_window_back,
        test_clamp_geometry_shrinks_oversized_window,
        test_clamp_geometry_respects_second_screen,
        test_clamp_geometry_requires_min_size,
        test_main_window_restores_saved_state,
        test_main_window_defaults_without_saved_state,
        test_main_window_restores_clamped_geometry,
        test_close_saves_geometry_and_toggles,
        test_close_while_collapsed_saves_expanded_geometry,
        test_auto_collapse_folds_and_restores,
        test_auto_collapse_waits_one_second_before_folding,
        test_auto_collapse_disabled_never_folds,
        test_turning_auto_collapse_off_expands,
        test_manual_toggle_collapse_keeps_position,
        test_collapse_disables_edge_resizing,
        test_auto_collapse_button_is_in_title_bar,
        test_screen_picker_cancel_resets_mouse_button_state,
        test_auto_collapse_survives_stale_qt_mouse_state,
        test_mouse_button_pressed_falls_back_to_qt_state,
        test_auto_collapse_ignores_maximized_window,
        test_topmost_on_non_windows_keeps_window_visible,
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
