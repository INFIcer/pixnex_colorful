"""UDM 颜色槽地址解析：必须始终跟随锚点指针。

回归背景：旧实现在锚点指针发生变化、但新颜色槽内容为全 0（纯黑）时，会继续
使用缓存下来的旧绝对地址。UDM 重启或重建颜色对象后，同步就会对着一段已经
失效的内存读写——状态显示已连接，实际完全不生效。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from colorPickerPro.sync import brush_color_spaces as spaces
from colorPickerPro.sync.udm_brush_link import UDMSync

_BASE = 0x1000
_BASE_OFFSET = 0x10
_ANCHOR = _BASE + _BASE_OFFSET


class _FakePymem:
    """pymem 的最小替身：一块 u32 内存 + 锚点处的 qword 指针。"""

    def __init__(self) -> None:
        self.u32: dict[int, int] = {}
        self.qwords: dict[int, int] = {}

    def read_longlong(self, address: int) -> int:
        return int(self.qwords.get(int(address), 0))

    def read_int(self, address: int) -> int:
        return int(self.u32.get(int(address), 0))

    def write_int(self, address: int, value: int) -> None:
        self.u32[int(address)] = int(value) & 0xFFFFFFFF

    def close_process(self) -> None:
        pass


def _make_sync() -> tuple[UDMSync, _FakePymem]:
    sync = UDMSync()
    fake = _FakePymem()
    sync.pm = fake
    sync.pid = 4242
    sync.module_base = _BASE
    sync.base_offset = _BASE_OFFSET
    sync.target = None
    return sync, fake


def _write_rgb_slot(fake: _FakePymem, slot: int, rgb: dict[str, int]) -> None:
    values = spaces.rgb_to_space_values("rgb", rgb)
    encoded = spaces.encode_space_values("rgb", values)
    for offset, raw in zip((0x20, 0x24, 0x28), encoded):
        fake.write_int(slot + offset, raw)


def test_first_access_resolves_anchor_pointer():
    sync, fake = _make_sync()
    fake.qwords[_ANCHOR] = 0x2000
    _write_rgb_slot(fake, 0x2000, {"r": 200, "g": 100, "b": 50})

    assert sync.get_color() == {"r": 200, "g": 100, "b": 50}
    assert sync.target == 0x2000


def test_anchor_change_is_followed_even_when_new_slot_is_black():
    """锚点指向新的全 0 槽（纯黑）时必须换用新地址，不能守着旧绝对地址。"""
    sync, fake = _make_sync()
    fake.qwords[_ANCHOR] = 0x2000
    _write_rgb_slot(fake, 0x2000, {"r": 200, "g": 100, "b": 50})
    assert sync.get_color() == {"r": 200, "g": 100, "b": 50}
    assert sync.target == 0x2000

    # UDM 重建了颜色对象：新槽 B 初始为纯黑（所有通道为 0）。
    fake.qwords[_ANCHOR] = 0x3000
    assert sync.get_color() == {"r": 0, "g": 0, "b": 0}
    assert sync.target == 0x3000, "锚点变化后必须跟随新指针"

    # 之后的写入必须落到新槽，而不是旧的绝对地址。
    assert sync.set_color(10, 20, 30) is True
    assert sync.get_color() == {"r": 10, "g": 20, "b": 30}
    old_raw_r = spaces.encode_space_values("rgb", {"r": 200, "g": 100, "b": 50})[0]
    new_raw_r = spaces.encode_space_values("rgb", {"r": 10, "g": 20, "b": 30})[0]
    assert fake.u32[0x2000 + 0x20] == old_raw_r, "旧槽不应再被写入"
    assert fake.u32[0x3000 + 0x20] == new_raw_r, "新槽应收到写入"


def test_zero_anchor_keeps_last_known_slot():
    """锚点瞬时读到 0 时保留上一个已知颜色槽，避免闪断。"""
    sync, fake = _make_sync()
    fake.qwords[_ANCHOR] = 0x2000
    _write_rgb_slot(fake, 0x2000, {"r": 1, "g": 2, "b": 3})
    assert sync.get_color() == {"r": 1, "g": 2, "b": 3}

    fake.qwords[_ANCHOR] = 0
    assert sync.get_color() == {"r": 1, "g": 2, "b": 3}
    assert sync.target == 0x2000


def _main() -> int:
    tests = [
        test_first_access_resolves_anchor_pointer,
        test_anchor_change_is_followed_even_when_new_slot_is_black,
        test_zero_anchor_keeps_last_known_slot,
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
