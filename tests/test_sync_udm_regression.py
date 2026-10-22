"""Regression tests for the UDM colour-sync wiring (plain asserts, stdlib).

The UDM backend is sensitive: importing psutil anywhere before opening the
UDM process makes UDM's protection deny the memory handle, and constructing
the Photoshop backend eagerly used to do exactly that.  These tests keep the
lazy-import/lazy-backend contract from regressing.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_python(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
        env=None,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_sync_import_does_not_load_psutil():
    """导入同步控制器时不得 import psutil（会触发 UDM 进程保护）。"""
    output = _run_python(
        "import sys; import colorPickerPro.sync.controller; "
        "print('psutil' in sys.modules)")
    assert output == "False", f"psutil was imported eagerly: {output!r}"


def test_sync_controller_constructs_backends_lazily():
    from colorPickerPro.sync.controller import SyncController

    controller = SyncController()
    try:
        assert controller._udm is None, "UDMSync 不应在构造时创建"
        assert controller._ps is None, "PhotoshopSync 不应在构造时创建"

        fake_udm = object()
        fake_ps = object()
        controller.udm = fake_udm
        controller.ps = fake_ps
        assert controller.udm is fake_udm
        assert controller.ps is fake_ps
    finally:
        controller.stop_thread()


def test_udm_window_pid_lookup_does_not_open_target_handles():
    """PID 解析只枚举窗口，不应对目标进程调用 OpenProcess。"""
    source = (ROOT / "colorPickerPro" / "sync" / "window_focus.py").read_text(
        encoding="utf-8")
    start = source.index("def _window_pids_for_names")
    end = source.index("def activate_window", start)
    body = source[start:end]
    assert "_kernel32.OpenProcess(" not in body, (
        "窗口 PID 解析不应 OpenProcess 目标进程（会阻断 UDM 内存访问）")


def _main() -> int:
    tests = [
        test_sync_import_does_not_load_psutil,
        test_sync_controller_constructs_backends_lazily,
        test_udm_window_pid_lookup_does_not_open_target_handles,
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
