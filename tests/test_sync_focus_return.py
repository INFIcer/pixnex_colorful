"""选色后归还焦点：窗口选择逻辑与同步目标解析（不触碰真实桌面）。"""

from colorPickerPro.sync import window_focus as wf
from colorPickerPro.sync.controller import SyncController
from colorPickerPro.sync.window_focus import WindowInfo, WindowFocusReturner, pick_main_window


def _win(hwnd, *, pid=100, title="", visible=True, iconic=False,
         owned=False, tool=False, area=100):
    return WindowInfo(
        hwnd=hwnd, pid=pid, title=title, visible=visible, iconic=iconic,
        owned=owned, tool_window=tool, area=area,
    )


# ----- 窗口选择（纯逻辑） ----------------------------------------------------
def test_pick_main_window_without_windows():
    assert pick_main_window([]) == 0


def test_pick_main_window_prefers_largest_titled_frame():
    windows = [
        _win(1, title="Splash", area=500),
        _win(2, title="优动漫PAINT4.0", area=1200),
        _win(3, title="", area=5000),  # 无标题的隐藏辅助窗口不参与
    ]
    assert pick_main_window(windows) == 2


def test_pick_main_window_skips_tool_and_owned_windows():
    windows = [
        _win(1, title="浮动面板", area=9000, tool=True),
        _win(2, title="对话框", area=8000, owned=True),
        _win(3, title="Main", area=600),
    ]
    assert pick_main_window(windows) == 3


def test_pick_main_window_keeps_minimized_frame_usable():
    windows = [
        _win(1, title="Main", area=0, visible=False, iconic=True),
        _win(2, title="Hidden helper", area=0, visible=False),
    ]
    assert pick_main_window(windows) == 1


def test_pick_main_window_reuses_remembered_window():
    windows = [_win(1, title="Doc", area=100), _win(2, title="Main", area=900)]
    assert pick_main_window(windows, preferred=1) == 1


def test_pick_main_window_ignores_dead_preference():
    windows = [_win(2, title="Main", area=900)]
    assert pick_main_window(windows, preferred=99) == 2


# ----- 焦点归还器（注入假的窗口枚举 / 激活，不真正抢焦点） --------------------
class _Patch:
    """临时替换 window_focus 模块级函数。"""

    def __init__(self, **replacements):
        self._replacements = replacements
        self._originals = {}

    def __enter__(self):
        for name, value in self._replacements.items():
            self._originals[name] = getattr(wf, name)
            setattr(wf, name, value)
        return self

    def __exit__(self, *exc):
        for name, original in self._originals.items():
            setattr(wf, name, original)
        return False


def test_focus_returner_activates_window_of_backend_pid():
    windows = [_win(11, pid=7, title="Clip Studio Paint", area=800)]
    activated = []
    with _Patch(
        _enumerate_windows=lambda pid: windows if pid == 7 else [],
        _window_pid=lambda hwnd: 7,
        activate_window=lambda hwnd: activated.append(hwnd) or True,
    ):
        returner = WindowFocusReturner()
        assert returner.focus(pid=7, process_names=()) is True
        assert activated == [11]
        # 记住窗口：同一进程再次归还时优先复用。
        assert returner.focus(pid=7, process_names=()) is True
        assert activated == [11, 11]


def test_focus_returner_falls_back_to_process_name():
    windows = [_win(21, pid=9, title="Photoshop", area=700)]
    activated = []
    with _Patch(
        pids_for_process_names=lambda names: [9] if "Photoshop.exe" in names else [],
        _enumerate_windows=lambda pid: windows if pid == 9 else [],
        activate_window=lambda hwnd: activated.append(hwnd) or True,
    ):
        returner = WindowFocusReturner()
        assert returner.focus(pid=None, process_names=("Photoshop.exe",)) is True
        assert activated == [21]


def test_focus_returner_reports_failure_when_nothing_to_focus():
    with _Patch(
        _enumerate_windows=lambda pid: [],
        activate_window=lambda hwnd: True,
    ):
        assert WindowFocusReturner().focus(pid=1234, process_names=()) is False


def test_focus_returner_skips_process_scan_when_pid_works():
    scans = []
    with _Patch(
        pids_for_process_names=lambda names: scans.append(names) or [],
        _enumerate_windows=lambda pid: [_win(31, pid=5, title="CSP", area=300)],
        _window_pid=lambda hwnd: 5,
        activate_window=lambda hwnd: True,
    ):
        assert WindowFocusReturner().focus(pid=5, process_names=("CSP.exe",)) is True
        assert scans == []  # 后端已连上时不做全进程扫描


def test_focus_returner_uses_process_names_when_pid_is_stale():
    with _Patch(
        pids_for_process_names=lambda names: [77],
        _enumerate_windows=lambda pid: (
            [_win(41, pid=77, title="CSP", area=300)] if pid == 77 else []),
        activate_window=lambda hwnd: hwnd == 41,
    ):
        returner = WindowFocusReturner()
        assert returner.focus(pid=5, process_names=("CSP.exe",)) is True
        assert returner._hwnd == 41


# ----- SyncController：目标解析 -------------------------------------------------
class _FakeBackend:
    def __init__(self, pid=None, names=()):
        self.target_pid = pid
        self._names = tuple(names)

    def focus_process_names(self):
        return self._names


class _FakeReturner:
    def __init__(self):
        self.calls = []

    def focus(self, pid=None, process_names=()):
        self.calls.append((pid, tuple(process_names)))
        return True


def test_sync_target_needs_mode_and_enabled():
    controller = SyncController()
    controller.udm = _FakeBackend(4242, ("UDMPaintPRO.exe", "UDMPaintEX.exe"))
    assert controller.sync_target() is None          # 关闭
    controller.set_mode("udm")
    assert controller.sync_target() is None          # 选了模式但没开启同步
    controller.set_enabled(True)
    assert controller.sync_target() == (
        4242, ("UDMPaintPRO.exe", "UDMPaintEX.exe"))


def test_sync_target_keeps_process_names_without_pid():
    controller = SyncController()
    controller.udm = _FakeBackend(None, ("UDMPaintEX.exe",))
    controller.set_mode("udm")
    controller.set_enabled(True)
    assert controller.sync_target() == (None, ("UDMPaintEX.exe",))


def test_return_focus_forwards_active_target():
    controller = SyncController()
    controller.ps = _FakeBackend(555, ("Photoshop.exe",))
    fake = _FakeReturner()
    controller._focus = fake
    controller.set_mode("ps")
    controller.set_enabled(True)
    assert controller.return_focus() is True
    assert fake.calls == [(555, ("Photoshop.exe",))]


def test_return_focus_is_noop_while_disabled():
    controller = SyncController()
    fake = _FakeReturner()
    controller._focus = fake
    controller.set_mode("udm")
    assert controller.return_focus() is False
    assert fake.calls == []
