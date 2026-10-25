"""主窗口界面状态与用户设置的持久化。

主窗口需要记住用户偏好，重启后恢复到上次关闭时的样子：

- 自动折叠开关；
- 窗口置顶；
- 窗口位置与尺寸（窗口折叠时保存的是展开后的尺寸，否则重启后只会剩
  一条标题栏）；
- 颜色设置：当前色彩模型、当前颜色（sRGB）；
- 颜色同步设置：目标软件、是否开启同步、选色后是否归还焦点。

状态用 ``QSettings`` 保存（INI 文件，默认落在
``%APPDATA%\\pixnex_colorful\\pixnex.ini``）；测试或预览可以构造内存存储
（``WindowStateStore()``），不写磁盘。``main()`` 在启动时注入
:meth:`WindowStateStore.persistent` 得到的持久化存储。

这个模块不依赖任何界面代码，只提供「状态数据结构 + 读写 + 几何合法性」，
便于单独测试；颜色模型 / 同步软件名的合法性由主窗口在恢复时校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QRect, QSettings, QSize
from PySide6.QtGui import QGuiApplication

# QSettings 的章节前缀与组织/应用名（决定 INI 路径）。
_SECTION = "main_window"
_SETTINGS_SECTION = "settings"
SETTINGS_ORGANIZATION = "pixnex_colorful"
SETTINGS_APPLICATION = "pixnex"

# QSettings 里保存的几何字段。
_GEOMETRY_KEYS = ("x", "y", "width", "height")
_COLOR_KEYS = ("color_r", "color_g", "color_b")


def _int_value(settings, key: str) -> int | None:
    """读取整数键；键不存在返回 None。

    不能直接用 ``value(key, None, type=int)``：``QSettings`` 会把缺失键的
    ``None`` 默认值换算成 0，导致「没保存过」被误判成 0。
    """
    if hasattr(settings, "contains") and not settings.contains(key):
        return None
    raw = settings.value(key, None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class WindowState:
    """主窗口需要跨启动保留的状态。

    ``geometry`` 为空表示从没保存过，主窗口沿用默认尺寸；
    ``color`` 为空表示从没保存过，主窗口沿用默认颜色。
    """

    auto_collapse: bool = False
    always_on_top: bool = False
    geometry: tuple[int, int, int, int] | None = None
    model: str = "OKLCH"
    color: tuple[int, int, int] | None = None
    sync_mode: str = "off"
    sync_enabled: bool = False
    focus_return: bool = True


class _MemorySettings:
    """最小的 ``QSettings`` 替身：只存在进程内，供测试 / 预览使用。"""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def value(self, key: str, default=None, type=None):  # noqa: A002 (Qt 同名参数)
        value = self._values.get(key, default)
        if type is not None and value is not None:
            try:
                return type(value)
            except (TypeError, ValueError):
                return default
        return value

    def setValue(self, key: str, value) -> None:  # noqa: N802 (Qt API)
        self._values[key] = value

    def remove(self, key: str) -> None:
        self._values.pop(key, None)

    def sync(self) -> None:
        """内存存储不需要落盘，保留以兼容 ``QSettings`` 接口。"""


class WindowStateStore:
    """读写 :class:`WindowState`。

    不传 ``settings`` 时使用进程内内存（不落盘）：主窗口测试、预览等场景
    不会动用户真实配置。正式启动入口用 :meth:`persistent` 落盘。
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else _MemorySettings()

    @classmethod
    def persistent(cls) -> "WindowStateStore":
        """用户级持久化存储（INI 文件，Windows 下位于 ``%APPDATA%``）。"""
        return cls(QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope,
            SETTINGS_ORGANIZATION, SETTINGS_APPLICATION))

    # ---- 读写 ---------------------------------------------------------
    def load(self) -> WindowState:
        settings = self._settings
        geometry = None
        values = []
        for name in _GEOMETRY_KEYS:
            values.append(_int_value(settings, f"{_SECTION}/{name}"))
        if all(value is not None for value in values):
            x, y, width, height = values
            if width > 0 and height > 0:
                geometry = (int(x), int(y), int(width), int(height))

        color = None
        channels = [
            _int_value(settings, f"{_SETTINGS_SECTION}/{key}")
            for key in _COLOR_KEYS]
        if all(value is not None for value in channels):
            color = tuple(max(0, min(255, int(value))) for value in channels)

        return WindowState(
            auto_collapse=bool(settings.value(
                f"{_SECTION}/auto_collapse", False, type=bool)),
            always_on_top=bool(settings.value(
                f"{_SECTION}/always_on_top", False, type=bool)),
            geometry=geometry,
            model=str(settings.value(
                f"{_SETTINGS_SECTION}/model", "OKLCH", type=str) or "OKLCH"),
            color=color,
            sync_mode=str(settings.value(
                f"{_SETTINGS_SECTION}/sync_mode", "off", type=str) or "off"),
            sync_enabled=bool(settings.value(
                f"{_SETTINGS_SECTION}/sync_enabled", False, type=bool)),
            focus_return=bool(settings.value(
                f"{_SETTINGS_SECTION}/focus_return", True, type=bool)),
        )

    def save(self, state: WindowState) -> None:
        settings = self._settings
        settings.setValue(
            f"{_SECTION}/auto_collapse", bool(state.auto_collapse))
        settings.setValue(
            f"{_SECTION}/always_on_top", bool(state.always_on_top))
        if state.geometry is None:
            for name in _GEOMETRY_KEYS:
                settings.remove(f"{_SECTION}/{name}")
        else:
            x, y, width, height = (int(value) for value in state.geometry)
            for name, value in zip(_GEOMETRY_KEYS, (x, y, width, height)):
                settings.setValue(f"{_SECTION}/{name}", value)

        settings.setValue(f"{_SETTINGS_SECTION}/model", str(state.model))
        settings.setValue(
            f"{_SETTINGS_SECTION}/sync_mode", str(state.sync_mode))
        settings.setValue(
            f"{_SETTINGS_SECTION}/sync_enabled", bool(state.sync_enabled))
        settings.setValue(
            f"{_SETTINGS_SECTION}/focus_return", bool(state.focus_return))
        if state.color is None:
            for key in _COLOR_KEYS:
                settings.remove(f"{_SETTINGS_SECTION}/{key}")
        else:
            for key, value in zip(_COLOR_KEYS, state.color):
                settings.setValue(
                    f"{_SETTINGS_SECTION}/{key}",
                    max(0, min(255, int(value))))
        sync = getattr(settings, "sync", None)
        if callable(sync):
            sync()


# ---------------------------------------------------------------------------
# 几何合法性
# ---------------------------------------------------------------------------

def screen_available_rects() -> list[QRect]:
    """当前所有屏幕的可用区域（已扣除任务栏）。"""
    return [screen.availableGeometry() for screen in QGuiApplication.screens()]


def clamp_geometry(rect: QRect, screens: Sequence[QRect],
                   min_size: QSize = QSize(1, 1)) -> QRect:
    """把恢复的窗口矩形夹到某块屏幕内，避免窗口跑到屏幕外。

    规则：
    - 优先选包含窗口中心的屏幕；中心不在任何屏幕上时选重叠面积最大的屏幕；
    - 尺寸不小于 ``min_size``，也不超过该屏幕可用尺寸；
    - 位置整体夹进该屏幕，保证标题栏可抓取（例如上次把窗口拖到屏幕底部时，
      展开会先向上移动而不是伸出屏幕外）。
    """
    if not screens:
        return QRect(rect)

    available = QRect(screens[0])
    center = rect.center()
    if not any(screen.contains(center) for screen in screens):
        best_area = -1
        for screen in screens:
            overlap = rect.intersected(screen)
            area = max(0, overlap.width()) * max(0, overlap.height())
            if area > best_area:
                available, best_area = QRect(screen), area
    else:
        for screen in screens:
            if screen.contains(center):
                available = QRect(screen)
                break

    min_width = max(1, min_size.width())
    min_height = max(1, min_size.height())
    width = max(min_width, min(rect.width(), available.width()))
    height = max(min_height, min(rect.height(), available.height()))
    x = max(available.left(),
            min(rect.x(), available.right() - width + 1))
    y = max(available.top(),
            min(rect.y(), available.bottom() - height + 1))
    return QRect(x, y, width, height)


__all__ = [
    "WindowState",
    "WindowStateStore",
    "clamp_geometry",
    "screen_available_rects",
]
