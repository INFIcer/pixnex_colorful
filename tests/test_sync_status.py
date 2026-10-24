"""Regression tests for the colour-sync status pill (未启动 / 未连接).

Historically the sync card stayed on 「连接中…」 forever when the drawing app was
not running: the controller only reported "connected = False" with an empty
error string, and the message de-duplication swallowed the next report after a
re-enable.  These tests pin the status vocabulary, the re-emit behaviour and the
UDM "is the target running?" probe.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_sync_status.py
"""

import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from colorPickerPro.sync import controller as ctl  # noqa: E402
from colorPickerPro.sync import udm_brush_link  # noqa: E402


def _ensure_app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


@contextmanager
def _patched(module, name, value):
    """Temporarily replace ``module.name`` (pytest's monkeypatch, stdlib-only)."""
    old = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, old)


class _FakeBackend:
    """Stand-in for UDMSync/PhotoshopSync with a canned status dict."""

    def __init__(self, status: dict, color: dict | None = None,
                 write_ok: bool = True, last_error: str = ""):
        self._status = dict(status)
        self._color = color
        self.write_ok = write_ok
        self.last_error = last_error
        self.target_pid = None

    def get_color(self):
        return self._color

    def set_color(self, *args, **kwargs):
        return self.write_ok

    def status(self):
        return dict(self._status)

    def focus_process_names(self):
        return ()


def _capture(controller):
    messages = []
    statuses = []
    controller.messageChanged.connect(
        lambda text, detail: messages.append((text, detail)))
    controller.statusChanged.connect(
        lambda mode, connected: statuses.append((mode, connected)))
    return messages, statuses


# ----- status_text: the pure decision ---------------------------------------
def test_status_text_idle():
    label, detail = ctl.status_text(False, False, {})
    assert label == ctl.STATUS_IDLE, label
    assert detail, "未同步也需要说明如何开始"


def test_status_text_connected():
    label, detail = ctl.status_text(True, True, {"connected": True})
    assert label == ctl.STATUS_SYNCED and detail == ""


def test_status_text_not_running_uses_backend_detail():
    label, detail = ctl.status_text(
        False, True,
        {"connected": False, "running": False,
         "lastError": "未检测到 UDM Paint 进程，请先启动 UDM Paint 再开启同步"},
        target="UDM Paint")
    assert label == ctl.STATUS_NOT_RUNNING, label
    assert "UDM Paint" in detail


def test_status_text_not_running_falls_back_without_detail():
    label, detail = ctl.status_text(
        False, True, {"running": False}, target="UDM Paint")
    assert label == ctl.STATUS_NOT_RUNNING
    assert "请先启动 UDM Paint" in detail


def test_status_text_running_but_unattached_is_not_not_running():
    label, detail = ctl.status_text(
        False, True, {"running": True, "lastError": "版本不匹配"},
        target="UDM Paint")
    assert label == ctl.STATUS_DISCONNECTED, label
    assert detail == "版本不匹配"


def test_status_text_unknown_running_state_is_not_not_running():
    """进程列表读不到时不能武断地说「未启动」。"""
    label, _detail = ctl.status_text(
        False, True, {"running": None}, target="UDM Paint")
    assert label == ctl.STATUS_DISCONNECTED, label


def test_status_text_write_failed():
    label, detail = ctl.status_text(
        True, True, {"connected": True}, target="Photoshop",
        write_error="写入 Photoshop 颜色失败：boom")
    assert label == ctl.STATUS_WRITE_FAILED, label
    assert "boom" in detail


# ----- controller wiring ----------------------------------------------------
def test_tick_reports_not_running():
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.udm = _FakeBackend({
            "connected": False, "running": False,
            "lastError": "未检测到 UDM Paint 进程，请先启动 UDM Paint 再开启同步",
        })
        messages, statuses = _capture(controller)
        controller.set_mode("udm")
        controller.set_enabled(True)
        controller._tick()

        assert statuses == [("udm", False)], statuses
        assert messages and messages[-1][0] == ctl.STATUS_NOT_RUNNING, messages
        assert "请先启动" in messages[-1][1]
    finally:
        controller.stop_thread()


def test_tick_reports_running_but_disconnected():
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.udm = _FakeBackend({
            "connected": False, "running": True, "lastError": "",
        })
        messages, _statuses = _capture(controller)
        controller.set_mode("udm")
        controller.set_enabled(True)
        controller._tick()
        assert messages[-1][0] == ctl.STATUS_DISCONNECTED, messages
        assert "权限" in messages[-1][1] or "版本" in messages[-1][1]
    finally:
        controller.stop_thread()


def test_tick_reports_synced():
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.udm = _FakeBackend(
            {"connected": True, "running": True},
            color={"r": 10, "g": 20, "b": 30})
        messages, statuses = _capture(controller)
        controller.set_mode("udm")
        controller.set_enabled(True)
        controller._tick()
        assert messages[-1] == (ctl.STATUS_SYNCED, ""), messages
        assert statuses[-1] == ("udm", True)
    finally:
        controller.stop_thread()


def test_same_status_is_re_emitted_after_reenable():
    """回归：重新点击「开启同步」后必须再次推送同一状态。

    主窗口会把标签先置为「连接中…」；如果控制器因为文案没变就不再发信号，
    标签就会永久停在「连接中…」——这正是本次修复要消除的迷惑性行为。
    """
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.udm = _FakeBackend({"connected": False, "running": False})
        messages, _statuses = _capture(controller)
        controller.set_mode("udm")
        controller.set_enabled(True)
        controller._tick()
        assert messages[-1][0] == ctl.STATUS_NOT_RUNNING

        messages.clear()
        controller.set_enabled(True)      # 用户再次点击「开启同步」
        controller._tick()                 # 主窗口此刻显示的是「连接中…」
        assert messages, "重新开启后控制器没有再次推送状态"
        assert messages[-1][0] == ctl.STATUS_NOT_RUNNING
    finally:
        controller.stop_thread()


def test_mode_switch_resets_status():
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.udm = _FakeBackend({"connected": False, "running": False})
        controller.ps = _FakeBackend({"connected": False, "running": False})
        messages, _statuses = _capture(controller)
        controller.set_mode("udm")
        controller.set_enabled(True)
        controller._tick()
        messages.clear()
        controller.set_mode("ps")
        controller._tick()
        assert messages and messages[-1][0] == ctl.STATUS_NOT_RUNNING, messages
    finally:
        controller.stop_thread()


def test_backend_claiming_connected_without_read_is_not_synced():
    """回归：后端自称 connected 但读不到颜色时，不能显示「已同步」。

    Photoshop 的 COM 对象存在、脚本桥也部署好了，都可能让 status() 返回
    connected=True，但那一刻其实读写都没通——用户看到的就是「显示已同步，
    但读写均未同步」。
    """
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.ps = _FakeBackend(
            {"connected": True, "running": True, "lastError": "没有打开的文档"},
            color=None)
        messages, statuses = _capture(controller)
        controller.set_mode("ps")
        controller.set_enabled(True)
        controller._tick()
        assert statuses == [("ps", False)], statuses
        assert messages[-1][0] == ctl.STATUS_DISCONNECTED, messages
        assert "没有打开的文档" in messages[-1][1]
    finally:
        controller.stop_thread()


def test_tick_reports_write_failure():
    _ensure_app()
    controller = ctl.SyncController()
    try:
        controller.ps = _FakeBackend(
            {"connected": True, "running": True},
            color={"r": 1, "g": 2, "b": 3},
            write_ok=False,
            last_error="写入 Photoshop 颜色失败：服务器忙碌")
        messages, statuses = _capture(controller)
        controller.set_mode("ps")
        controller.set_enabled(True)
        controller.write_color(9, 8, 7)
        controller._tick()
        assert statuses[-1] == ("ps", True)
        assert messages[-1][0] == ctl.STATUS_WRITE_FAILED, messages
        assert "服务器忙碌" in messages[-1][1]
    finally:
        controller.stop_thread()


def test_write_forces_a_fresh_read():
    """写完必须立刻重读：否则会用节流缓存把界面颜色弹回旧值。"""
    _ensure_app()
    controller = ctl.SyncController()
    try:
        backend = _FakeBackend(
            {"connected": True, "running": True}, color={"r": 1, "g": 2, "b": 3})
        reads = []
        original = backend.get_color
        backend.get_color = lambda: (reads.append(1), original())[1]
        controller.ps = backend
        controller.set_mode("ps")
        controller.set_enabled(True)

        controller._tick()
        assert len(reads) == 1
        controller._tick()                 # 还没到 0.4s，复用缓存
        assert len(reads) == 1

        controller.write_color(9, 8, 7)
        controller._tick()                 # 写入后必须重读
        assert len(reads) == 2, "写入后没有重新读取颜色"
    finally:
        controller.stop_thread()


# ----- UDM backend: running detection ---------------------------------------
def test_udm_status_reports_not_running():
    with _patched(udm_brush_link, "is_process_running", lambda names: False):
        sync = udm_brush_link.UDMSync()
        sync._running_ts = 0.0
        with _patched(sync, "connect", lambda: False):
            status = sync.status()
    assert status["connected"] is False
    assert status["running"] is False
    assert "请先启动" in str(status["lastError"])


def test_udm_status_reports_unknown_when_snapshot_fails():
    with _patched(udm_brush_link, "is_process_running", lambda names: None):
        sync = udm_brush_link.UDMSync()
        sync._running_ts = 0.0
        # 不真的去连本机正在跑的 UDM；只验证「进程状态未知」时的汇报。
        with _patched(sync, "connect", lambda: False):
            status = sync.status()
    assert status["running"] is None
    assert status["connected"] is False
    assert "无法确认" in str(status["lastError"])


def test_udm_does_not_attach_while_not_running():
    calls = []

    def fake_connect():
        calls.append(1)
        return True

    with _patched(udm_brush_link, "is_process_running", lambda names: False):
        sync = udm_brush_link.UDMSync()
        sync._running_ts = 0.0
        with _patched(sync, "connect", fake_connect):
            assert sync.get_color() is None
            assert sync.set_color(1, 2, 3) is False
    assert calls == [], "软件未启动时不应反复尝试附加进程"


# ----- Photoshop backend ----------------------------------------------------
def _fake_photoshop(scripts, read_result="12|34|56"):
    from colorPickerPro.sync import photoshop_color_sync as pcs
    from colorPickerPro.sync.photoshop_instances import COM_KIND

    ps = pcs.PhotoshopSync()
    ps._app = object()
    ps.backend = COM_KIND
    ps._is_process_alive = lambda: True

    def fake_js(script):
        scripts.append(script)
        return read_result if "Math.round(c.red)" in script else ""

    ps._invoke_js = fake_js
    return ps


def test_photoshop_reads_and_writes_through_dojavascript():
    """色值必须走 DoJavaScript：COM 属性在 PS CC 2018 上读到的是本地副本，
    直接改 rgb.Red 不会真正改到 Photoshop。"""
    scripts = []
    ps = _fake_photoshop(scripts)

    assert ps.get_color() == {"r": 12, "g": 34, "b": 56, "index": 0}
    assert "app.foregroundColor.rgb" in scripts[-1]

    assert ps.set_color(1, 2, 3) is True
    write_script = scripts[-1]
    assert "app.foregroundColor=c" in write_script
    assert "c.rgb.red=1" in write_script

    # 颜色已经一致时不需要再写一次
    before = len(scripts)
    assert ps.set_color(12, 34, 56) is True
    assert len(scripts) == before + 1, "同色时只应多一次读取，不应写入"


def test_photoshop_bridge_deployed_without_heartbeat_is_not_connected():
    """脚本桥「部署成功」不等于连接成功：没有心跳时不能报已同步。"""
    from colorPickerPro.sync import photoshop_color_sync as pcs
    from colorPickerPro.sync.photoshop_instances import (
        SCRIPT_BRIDGE_KIND, PhotoshopInstance,
    )

    class FakeBridge:
        def __init__(self, ps_dir):
            self.ps_dir = ps_dir

        def is_deployed(self):
            return True

        def deploy(self):
            return True

        def is_alive(self):
            return False

        def panel_version(self, max_age: float = 5.0):
            return pcs.PANEL_VERSION

    with _patched(pcs, "PhotoshopScriptBridge", FakeBridge):
        ps = pcs.PhotoshopSync()
        ps._is_process_alive = lambda: True
        ps._detect = lambda force=False: [PhotoshopInstance(
            kind=SCRIPT_BRIDGE_KIND, label="绿色版", exe_path=r"C:\PS\Photoshop.exe",
            pid=1)]
        assert ps.connect() is False
        assert ("重启" in ps.last_error or "心跳" in ps.last_error), ps.last_error
        assert ps.status()["connected"] is False


def _main() -> int:
    tests = [
        test_status_text_idle,
        test_status_text_connected,
        test_status_text_not_running_uses_backend_detail,
        test_status_text_not_running_falls_back_without_detail,
        test_status_text_running_but_unattached_is_not_not_running,
        test_status_text_unknown_running_state_is_not_not_running,
        test_tick_reports_not_running,
        test_tick_reports_running_but_disconnected,
        test_tick_reports_synced,
        test_same_status_is_re_emitted_after_reenable,
        test_mode_switch_resets_status,
        test_backend_claiming_connected_without_read_is_not_synced,
        test_tick_reports_write_failure,
        test_write_forces_a_fresh_read,
        test_status_text_write_failed,
        test_udm_status_reports_not_running,
        test_udm_status_reports_unknown_when_snapshot_fails,
        test_udm_does_not_attach_while_not_running,
        test_photoshop_reads_and_writes_through_dojavascript,
        test_photoshop_bridge_deployed_without_heartbeat_is_not_connected,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    print(f"\n共 {len(tests)} 项检查，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
