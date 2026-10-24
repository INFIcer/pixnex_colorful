"""pixnex_colorful UI 布局 / 主题自动化巡检（无窗口、可独立运行，不依赖 pytest）。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe tests\\ui_layout_check.py
    .venv\\Scripts\\python.exe tests\\ui_layout_check.py --only dialog --verbose
    .venv\\Scripts\\python.exe tests\\ui_layout_check.py --dpi-pass        # 主通道 + 1.5x DPI 通道
    .venv\\Scripts\\python.exe tests\\ui_layout_check.py --scale 1.5      # 只跑 1.5x 单通道
    .venv\\Scripts\\python.exe tests\\ui_layout_check.py --list

巡检内容（Phase 1 + Phase 2）：
1. 在同一个 QApplication 上构建所有界面（主窗口 / 各对话框 / 各控件 / 屏幕滤镜
   窗口 / 标准消息与输入对话框），每个界面在多个尺寸下 grab() 出 PNG 到
   build/ui-shots/；
2. Phase 2：每个产品顶层窗口必须无边框（FramelessWindowHint）且带自绘 TitleBar
   （objectName="TitleBar"）；标题栏按钮必须是已加载的 SVG 图标；
3. 断言构建/渲染无异常、UIHarness.bounds_problems() 为空、隐藏窗口补充扫描为空、
   配置的最小尺寸不小于 minimumSizeHint、顶层窗口可缩放；
4. 静态扫描：setStyleSheet=0、emoji=0、UI 文案无图标字符、IconButton/ set_icon
   引用的 SVG 资源齐全、QSS url() 资源存在且不再引用 PNG；
5. 功能冒烟：模型切换 / 参数区重建 / 查看器变换 / 弹窗确认 / 方案保存 /
   屏幕滤镜定时器 / sync 状态 / 标题栏按钮 / 关闭按钮 / 最大化切换 /
   主窗口与屏幕滤镜窗口自动折叠 / 屏幕滤镜左键取色 / 复用窗口重新显示后缩放；
6. 打印一行一个界面的 PASS/FAIL 报告并汇总，有 FAIL 时退出码为 1。

刻意不设置 QT_QPA_PLATFORM=offscreen：offscreen 插件没有系统字体，截图会变成
豆腐块；这里使用真实 Windows 平台插件，UIHarness 通过 WA_DontShowOnScreen 让窗口
完成真实布局但不会真的显示出来。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# 直接运行 `python tests/ui_layout_check.py` 时，tests/ 已在 sys.path 里；
# 从别处 import 时兜底把 tests/ 加进去。
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from ui_helpers import (  # noqa: E402
    ROOT as HELPERS_ROOT,
    SHOTS_DIR,
    SurfaceResult,
    SurfaceSpec,
    format_size_changes,
    rel,
    run_surface,
    scan_emoji,
    scan_icon_refs,
    scan_qss_assets,
    scan_setstylesheet,
    scan_ui_glyphs,
)

REPORT_LINES: list[str] = []


# ---------------------------------------------------------------------------
# 输出 / 报告
# ---------------------------------------------------------------------------

def emit(line: str = "") -> None:
    print(line, flush=True)
    REPORT_LINES.append(line)


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


def _surface_line(result: SurfaceResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    if result.error and not result.sizes:
        size_text = "构建失败"
    else:
        size_text = format_size_changes(result)
    shots = " ".join(rel(p) for p in result.shots) or "无截图"
    return f"{status}  {result.name:<24s} 尺寸 {size_text or '-':<38s} 截图 {shots}"


def _emit_surface_details(result: SurfaceResult, verbose: bool) -> None:
    shown = result.problems if verbose else result.problems[:8]
    for problem in shown:
        emit(f"      - {problem}")
    if not verbose and len(result.problems) > len(shown):
        emit(f"      ... 其余 {len(result.problems) - len(shown)} 条（--verbose 查看）")
    if result.error and (not result.problems or verbose):
        emit(f"      - {result.error}")
    for warning in result.warnings:
        emit(f"      ! {warning}")
    for note in result.info:
        emit(f"      · {note}")
    if verbose and result.traceback_text:
        for line in result.traceback_text.rstrip().splitlines():
            emit(f"        {line}")
    if verbose and result.captured_output:
        lines = result.captured_output.rstrip().splitlines()
        if lines:
            emit(f"      · 控件输出（{len(lines)} 行）:")
            for line in lines[:80]:
                emit(f"        {line}")
            if len(lines) > 80:
                emit(f"        ... 省略 {len(lines) - 80} 行")


def _emit_static_report(violations, counts, verbose: bool) -> bool:
    """输出静态扫描结果；返回是否通过。"""
    if not violations:
        emit(f"PASS  {'static:setStyleSheet':<24s} 0 处调用（期望 0；"
             f"仅允许 ui/theme.py 的全局 QSS 安装）")
        return True
    emit(f"FAIL  {'static:setStyleSheet':<24s} {len(violations)} 处调用 / "
         f"{len(counts)} 个文件（期望 0）")
    for file in sorted(counts):
        lines = [str(lineno) for relpath, lineno, _ in violations if relpath == file]
        emit(f"      - {file}: {counts[file]} 处 → 行 {', '.join(lines)}")
    if verbose:
        for relpath, lineno, source in violations:
            emit(f"        {relpath}:{lineno}: {source}")
    return False


def _emit_emoji_report(violations, counts, verbose: bool) -> bool:
    """输出 emoji 静态扫描结果；返回是否通过。"""
    if not violations:
        emit(f"PASS  {'static:emoji':<24s} 0 处 emoji（彩色象形符号，期望 0）")
        return True
    emit(f"FAIL  {'static:emoji':<24s} {len(violations)} 个 emoji 字符 / "
         f"{len(counts)} 个文件（期望 0）")
    for file in sorted(counts):
        entries = [(lineno, ch, source) for relpath, lineno, ch, source
                   in violations if relpath == file]
        line_info = ", ".join(
            f"行 {lineno} {ch!r} U+{ord(ch):04X}" for lineno, ch, _ in entries)
        emit(f"      - {file}: {counts[file]} 处 → {line_info}")
    if verbose:
        for relpath, lineno, ch, source in violations:
            emit(f"        {relpath}:{lineno}: {ch!r} U+{ord(ch):04X}  {source}")
    return False


def _emit_ui_glyph_report(violations, counts, verbose: bool) -> bool:
    """Phase 2：UI 文案里的图标字符 / '+ ' 前缀检查结果。"""
    if not violations:
        emit(f"PASS  {'static:ui-glyphs':<24s} 0 处禁用图标字符（✕ ─ ▶ ⏸ ❚ ⚙ "
             f"↔ ↕ ↻ ＋ / '+ ' 开头文案）")
        return True
    emit(f"FAIL  {'static:ui-glyphs':<24s} {len(violations)} 处 / "
         f"{len(counts)} 个文件（期望 0，图标必须走 SVG 资源）")
    for file in sorted(counts):
        emit(f"      - {file}: {counts[file]} 处")
    for violation in (violations if verbose else violations[:20]):
        emit(f"        {violation}")
    if not verbose and len(violations) > 20:
        emit(f"        ... 其余 {len(violations) - 20} 处（--verbose 查看）")
    return False


def _emit_icon_report(violations, referenced_count: int, verbose: bool) -> bool:
    """Phase 2：IconButton/set_icon 引用的 SVG 资源检查结果。"""
    if not violations:
        emit(f"PASS  {'static:icons':<24s} {referenced_count} 个图标引用全部命中 "
             f"assets/icons/*.svg，SVG 均可解析")
        return True
    emit(f"FAIL  {'static:icons':<24s} {len(violations)} 处问题 / "
         f"{referenced_count} 个图标引用（期望 0）")
    for violation in (violations if verbose else violations[:20]):
        emit(f"      - {violation}")
    if not verbose and len(violations) > 20:
        emit(f"      ... 其余 {len(violations) - 20} 处（--verbose 查看）")
    return False


def _emit_qss_report(violations, checked: int, verbose: bool) -> bool:
    """Phase 2：QSS url() 资源检查结果（禁止位图、文件必须存在）。"""
    if not violations:
        emit(f"PASS  {'static:qss-assets':<24s} {checked} 个 QSS url() 资源全部存在"
             f"（无 PNG 位图引用）")
        return True
    emit(f"FAIL  {'static:qss-assets':<24s} {len(violations)} 处问题 / "
         f"{checked} 个 url() 引用（期望 0）")
    for violation in violations:
        emit(f"      - {violation}")
    return False


# ---------------------------------------------------------------------------
# 测试夹具：临时滤镜方案仓库 / 示例像素图 / 参数列表
# ---------------------------------------------------------------------------

class Fixtures:
    """按需构建、缓存巡检夹具；产品模块全部延迟导入，避免重构期间互相拖累。"""

    FILTER_NAMES = ("颜色反转", "RGB灰度", "正片叠底", "边缘检测", "信息量分析")

    def __init__(self, tmpdir: Path):
        self.tmpdir = Path(tmpdir)
        self._cache: dict[str, object] = {}

    def _cached(self, key: str, builder):
        if key not in self._cache:
            self._cache[key] = builder()
        return self._cache[key]

    # ---- 滤镜 / 方案 ---------------------------------------------------
    def _filter_classes(self, count: int) -> list:
        from colorPickerPro.filter_lib import ImageFilter
        from colorPickerPro.filter_scheme import filter_class_by_name

        classes: list = []
        for name in self.FILTER_NAMES:
            cls = filter_class_by_name(name)
            if cls is not None and cls not in classes:
                classes.append(cls)
        if len(classes) < count:
            for cls in ImageFilter.all_filters():
                if cls not in classes:
                    classes.append(cls)
                if len(classes) >= count:
                    break
        if len(classes) < count:
            raise RuntimeError(f"滤镜库不足 {count} 个可用滤镜（只有 {len(classes)} 个）")
        return classes[:count]

    def scheme(self, depth: int = 1, name: str = "巡检方案"):
        from colorPickerPro.filter_scheme import FilterLayer, FilterScheme

        key = f"scheme:{depth}:{name}"

        def build():
            classes = self._filter_classes(depth)
            return FilterScheme(name, [FilterLayer.create(c) for c in classes])

        return self._cached(key, build)

    def scheme_named(self, name: str, filter_names):
        """按显示名精确构造方案（用于功能冒烟：需要特定参数个数的图层）。"""
        from colorPickerPro.filter_scheme import (
            FilterLayer, FilterScheme, filter_class_by_name,
        )

        key = f"scheme_named:{name}:{tuple(filter_names)}"

        def build():
            classes = []
            for filter_name in filter_names:
                cls = filter_class_by_name(filter_name)
                if cls is None:
                    raise RuntimeError(f"找不到滤镜: {filter_name}")
                classes.append(cls)
            return FilterScheme(name, [FilterLayer.create(c) for c in classes])

        return self._cached(key, build)

    def store(self, label: str = "ui"):
        """临时方案仓库（绝不读写用户主目录里的真实方案文件）。"""
        from colorPickerPro.filter_scheme import FilterSchemeStore

        key = f"store:{label}"

        def build():
            path = self.tmpdir / f"schemes_{label}.json"
            store = FilterSchemeStore(str(path))
            store.add(self.scheme(1, f"{label}-单滤镜方案"))
            store.add(self.scheme(2, f"{label}-双滤镜方案"))
            if not store.save():
                raise RuntimeError(
                    f"临时方案仓库写入失败: {path}（{store.last_error or '未知错误'}）")
            return store

        return self._cached(key, build)

    # ---- 像素图 / 控件数据 ---------------------------------------------
    def pixmap(self):
        def build():
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

            image = QImage(240, 180, QImage.Format.Format_RGB32)
            image.fill(QColor("#1B2A3A"))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for i in range(6):
                painter.fillRect(
                    QRect(i * 38, 12 + i * 8, 30, 150 - i * 16),
                    QColor.fromHsv((i * 47) % 360, 200, 230))
            painter.setPen(QColor("#E9EDF3"))
            painter.drawText(20, 36, "pixnex 布局巡检")
            painter.end()
            return QPixmap.fromImage(image)

        return self._cached("pixmap", build)

    def params(self) -> list:
        """覆盖 filter_lib 的全部 8 种参数类型。"""
        def build():
            from colorPickerPro.filter_lib import (
                BoolParam, ColorParam, FileParam, FilterParam, InfoParam,
                RangeParam, TextParam, Vec2Param,
            )

            return [
                FilterParam("数值", "0~100 的数值参数", 0.0, 100.0, 42.0, 0.5),
                RangeParam("范围", "阈值区间（下限不能越过上限）", 0, 255, 32, 200, 1),
                BoolParam("开关", "布尔开关参数", True),
                ColorParam("颜色", "颜色参数（数据颜色由 ColorSwatch 绘制）", 255, 120, 0),
                TextParam("文本", "单行文本参数", "示例文本"),
                FileParam("文件", "文件路径参数", "", "图像 (*.png *.jpg)"),
                Vec2Param("坐标", "二维坐标参数", -100.0, 100.0, 0.0, 0.0, 0.1),
                InfoParam("信息", "只读信息参数",
                          "信息量 12.3 KB；平均亮度 128；耗时 4.2 ms", True),
            ]

        return self._cached("params", build)

    def dummy_item(self, title: str):
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        from colorPickerPro.ui.components import SubtitleLabel, TitleLabel
        from colorPickerPro.ui.tokens import SPACE

        widget = QWidget()
        widget.setObjectName(title)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(SPACE.md, SPACE.md, SPACE.md, SPACE.md)
        layout.setSpacing(SPACE.xs)
        layout.addWidget(TitleLabel(title))
        layout.addWidget(SubtitleLabel("用于布局巡检的示例内容。"))
        layout.addStretch(1)
        return widget


# ---------------------------------------------------------------------------
# 巡检项定义
# ---------------------------------------------------------------------------

LIST_ITEMS = ["红色通道", "绿色通道", "蓝色通道", "Alpha 通道",
              "亮度", "饱和度", "对比度", "色相"]


def teardown_main_window(win):
    """MainWindow 会启动 SyncController(QThread)：先停线程，再关窗口，
    否则进程退出时线程还在跑（崩溃/卡住的典型来源）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        try:
            app.removeEventFilter(win)
        except Exception:
            pass
    for attr in ("_sync", "sync_controller", "_controller"):
        controller = getattr(win, attr, None)
        if controller is not None and hasattr(controller, "stop_thread"):
            try:
                controller.stop_thread()
            except Exception:
                pass
            break
    win.close()


def build_specs(fixtures: Fixtures) -> list[SurfaceSpec]:
    specs: list[SurfaceSpec] = []

    # ---- 1. 主窗口（同步线程必须收尾） ----------------------------------
    def build_main_window():
        from colorPickerPro.main import MainWindow
        return MainWindow()

    specs.append(SurfaceSpec(
        "main_window", build_main_window,
        [(360, 600), (420, 760), (700, 900)],
        kind="window", frameless=True, teardown=teardown_main_window,
        description="主窗口 MainWindow（无边框 + 自绘标题栏，含同步线程）"))

    # ---- 2. 取色对话框 ---------------------------------------------------
    def build_color_picker_dialog():
        from colorPickerPro.color_picker_dialog import ColorPickerDialog
        return ColorPickerDialog()

    specs.append(SurfaceSpec(
        "color_picker_dialog", build_color_picker_dialog,
        [(360, 560), (420, 700), (520, 800)],
        kind="dialog", frameless=True, description="独立取色对话框（无边框）"))

    # ---- 3. 滤镜 / 方案选择对话框 ---------------------------------------
    def build_selector_dialog():
        from colorPickerPro.filter_scheme_selector import FilterSchemeSelectorDialog
        return FilterSchemeSelectorDialog(
            None, "选择滤镜 / 滤镜方案", store=fixtures.store("selector"))

    specs.append(SurfaceSpec(
        "filter_scheme_selector", build_selector_dialog,
        [(560, 400), (700, 520)],
        kind="dialog", frameless=True,
        description="滤镜库 + 已保存方案选择弹窗（无边框）"))

    # ---- 4. 滤镜方案管理面板（3 个滤镜图层，首层带参数便于看参数区） ---
    def build_scheme_panel():
        from colorPickerPro.filter_scheme_panel import FilterSchemePanel
        return FilterSchemePanel(
            fixtures.scheme_named("面板方案", ["信息量分析", "边缘检测", "颜色反转"]),
            store=fixtures.store("panel"))

    specs.append(SurfaceSpec(
        "filter_scheme_panel", build_scheme_panel,
        [(620, 420), (800, 560)],
        kind="window", frameless=True,
        description="滤镜方案管理面板（无边框 + 图层 + 参数）"))

    # ---- 5. 列表选择对话框（单选 / 多选） -------------------------------
    def build_list_single():
        from colorPickerPro.list_selection_dialog import ListSelectionDialog
        return ListSelectionDialog(
            None, "选择", LIST_ITEMS,
            selection_mode="single", current_index=2)

    def build_list_multi():
        from colorPickerPro.list_selection_dialog import ListSelectionDialog
        return ListSelectionDialog(
            None, "选择（多选）", LIST_ITEMS,
            selection_mode="multiple", checked_indices=[0, 3, 5])

    specs.append(SurfaceSpec(
        "list_selection_single", build_list_single,
        [(360, 420), (520, 600)],
        kind="dialog", frameless=True, description="列表选择弹窗（单选，无边框）"))
    specs.append(SurfaceSpec(
        "list_selection_multi", build_list_multi,
        [(360, 420), (520, 600)],
        kind="dialog", frameless=True, description="列表选择弹窗（多选，无边框）"))

    # ---- 6. 图像查看器 ---------------------------------------------------
    def build_image_viewer():
        from colorPickerPro.image_viewer import ImageViewer
        return ImageViewer(fixtures.pixmap())

    specs.append(SurfaceSpec(
        "image_viewer", build_image_viewer,
        [(360, 300), (900, 600)],
        kind="widget", description="图像查看器（缩放/旋转工具栏）"))

    # ---- 7. 滤镜对比窗口 -------------------------------------------------
    def build_compare_window():
        from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
        return ImageFilterCompareWindow(
            fixtures.pixmap(),
            [fixtures.scheme(1, "对比方案 A"), fixtures.scheme(2, "对比方案 B")])

    specs.append(SurfaceSpec(
        "image_filter_compare", build_compare_window,
        [(520, 400), (1000, 650)],
        kind="window", frameless=True,
        description="图像滤镜对比窗口（无边框 + 最大化按钮）"))

    # ---- 8. 列表查看器（两种视图模式） ----------------------------------
    def build_list_viewer_overlap():
        from colorPickerPro.list_viewer import ListViewer
        items = [fixtures.dummy_item(f"对比项 {i + 1}") for i in range(3)]
        return ListViewer(items, view_mode=ListViewer.ViewMode.OVERLAP)

    def build_list_viewer_horizontal():
        from colorPickerPro.list_viewer import ListViewer
        items = [fixtures.dummy_item(f"对比项 {i + 1}") for i in range(3)]
        return ListViewer(items, view_mode=ListViewer.ViewMode.HORIZONTAL)

    specs.append(SurfaceSpec(
        "list_viewer_overlap", build_list_viewer_overlap,
        [(360, 300), (720, 500)],
        kind="widget", description="列表查看器（重叠对比模式）"))
    specs.append(SurfaceSpec(
        "list_viewer_horizontal", build_list_viewer_horizontal,
        [(360, 300), (720, 500)],
        kind="widget", description="列表查看器（横向对比模式）"))

    # ---- 9. 图像拖放控件 -------------------------------------------------
    def build_image_drop():
        from colorPickerPro.image_drop_widget import ImageDropWidget
        return ImageDropWidget(placeholder_text="拖入图像进行滤镜对比",
                               drop_hint="释放以对比滤镜")

    specs.append(SurfaceSpec(
        "image_drop_widget", build_image_drop,
        [(200, 60), (500, 200)],
        kind="widget", resizable=False,
        description="图像拖放控件"))

    # ---- 10. 屏幕滤镜窗口（只构建，绝不 start()/启动定时器） -------------
    def build_screen_filter_window():
        from colorPickerPro.screenFilter import ScreenFilterWindow
        return ScreenFilterWindow(fixtures.scheme(2, "屏幕滤镜方案"))

    def teardown_screen_filter(win):
        for attr in ("_timer", "_debounce_timer"):
            timer = getattr(win, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        stop = getattr(win, "stop", None)
        if callable(stop):
            stop()          # 只停定时器 + hide，绝不 start()
        win.close()

    specs.append(SurfaceSpec(
        "screen_filter_window", build_screen_filter_window,
        [(480, 360), (300, 220)],
        kind="window", frameless=True, teardown=teardown_screen_filter,
        description="屏幕滤镜窗口（无边框 + 自绘标题栏，构建后立即停表）"))

    # ---- 11. 滤镜参数编辑区（覆盖 8 种参数类型） ------------------------
    def build_filter_params_dialog():
        from colorPickerPro.filter_scheme_panel import FilterParamsWidget
        from colorPickerPro.ui.components import HintLabel, ThemedDialog

        dialog = ThemedDialog(
            "滤镜参数预览",
            "FilterParam / RangeParam / BoolParam / ColorParam / "
            "TextParam / FileParam / Vec2Param / InfoParam")
        dialog.make_body_scrollable()
        dialog.add_content(FilterParamsWidget(
            fixtures.params(), None, "全部参数类型"))
        dialog.add_content(HintLabel("仅展示控件外观，不触发任何模态对话框。"))
        dialog.add_reject_button()
        dialog.add_accept_button()
        dialog.resize(420, 800)
        return dialog

    specs.append(SurfaceSpec(
        "filter_params_widget", build_filter_params_dialog,
        [(320, 600), (420, 800)],
        kind="dialog", frameless=True,
        description="FilterParamsWidget（全部参数类型，ThemedDialog 外壳）"))

    # ---- 12. 标准消息 / 文本输入对话框（Phase 2 无边框） ----------------
    def build_message_dialog():
        from colorPickerPro.ui.components import MessageDialog
        return MessageDialog(
            None, "删除滤镜方案",
            "确定删除方案「示例方案」吗？此操作无法撤销，"
            "已应用该方案的屏幕滤镜窗口不会自动关闭。",
            confirm_text="确定", cancel_text="取消")

    specs.append(SurfaceSpec(
        "message_dialog", build_message_dialog,
        [(440, 180), (560, 240)],
        kind="dialog", frameless=True,
        description="标准消息对话框 MessageDialog（只构建/渲染，不 exec）"))

    def build_text_input_dialog():
        from colorPickerPro.ui.components import TextInputDialog
        return TextInputDialog(
            None, "保存滤镜方案", "方案名称：", "示例方案")

    specs.append(SurfaceSpec(
        "text_input_dialog", build_text_input_dialog,
        [(420, 200), (520, 260)],
        kind="dialog", frameless=True,
        description="标准文本输入对话框 TextInputDialog（只构建/渲染，不 exec）"))

    return specs


# ---------------------------------------------------------------------------
# 功能冒烟：模型切换 / 参数区重建 / 查看器变换 / 对比模式 / 弹窗确认取消 / 保存方案
# ---------------------------------------------------------------------------

def _run_functional_checks(fixtures: Fixtures,
                           harness) -> list[tuple[str, bool, str, str]]:
    """不弹窗、不 show() 的功能冒烟；返回 [(名称, 是否通过, 失败摘要, traceback)]。"""
    from PySide6.QtWidgets import QApplication, QDialog

    checks: list[tuple[str, bool, str, str]] = []

    def record(name, fn) -> None:
        try:
            fn()
        except Exception as exc:
            checks.append((name, False, f"{type(exc).__name__}: {exc}",
                           traceback.format_exc()))
        else:
            checks.append((name, True, "", ""))

    def _assert_child_models(owner, label: str) -> None:
        for attr in ("_graph", "_slider_widget", "_info_panel"):
            child = getattr(owner, attr, None)
            if child is None:
                continue
            bound = getattr(child, "_model", None)
            assert bound is owner._model, (
                f"{label}: {attr} 仍绑定旧模型 {type(bound).__name__}，"
                f"应为 {type(owner._model).__name__}")

    # ---- 1. ColorPickerDialog 五种颜色模型原地切换 ----------------------
    def check_color_picker_models() -> None:
        from colorPickerPro.color_picker_dialog import ColorPickerDialog
        from colorPickerPro.color_picker_widgets import ALL_MODELS

        dlg = ColorPickerDialog()
        try:
            names = list(ALL_MODELS.keys())
            assert len(names) == 5, f"期望 5 个颜色模型，实际 {len(names)}: {names}"
            for index, name in enumerate(names):
                dlg._combo.setCurrentIndex(index)
                QApplication.processEvents()
                assert type(dlg._model) is ALL_MODELS[name], (
                    f"切换到 {name} 后 _model 是 {type(dlg._model).__name__}")
                _assert_child_models(dlg, f"ColorPickerDialog/{name}")
            color = dlg.get_color()
            assert abs(color[0] - 255) <= 1 and color[1] <= 1 and color[2] <= 1, (
                f"切换模型后颜色未保留（期望红色）: {color}")
        finally:
            dlg.reject()
            dlg.deleteLater()
            QApplication.processEvents()

    # ---- 2. MainWindow 五种颜色模型原地切换 -----------------------------
    def check_main_window_models() -> None:
        from colorPickerPro.color_picker_widgets import ALL_MODELS
        from colorPickerPro.main import MainWindow

        win = MainWindow()
        try:
            names = list(ALL_MODELS.keys())
            for index, name in enumerate(names):
                win._combo.setCurrentIndex(index)
                QApplication.processEvents()
                assert type(win._model) is ALL_MODELS[name], (
                    f"主窗口切换到 {name} 后 _model 是 {type(win._model).__name__}")
                _assert_child_models(win, f"MainWindow/{name}")
            r, g, b = win._model.to_srgb_tuple()
            assert abs(r - 1.0) < 0.02 and g < 0.02 and b < 0.02, (
                f"主窗口切换模型后颜色未保留（期望红色）: {(r, g, b)}")
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            sync = getattr(win, "_sync", None)
            assert sync is None or sync.isRunning() is False, (
                "关闭主窗口后 SyncController 线程仍在运行")
            win.deleteLater()
            QApplication.processEvents()

    # ---- 2b. MainWindow 同步状态标签可见且长消息不撑宽窗口 --------------
    def check_main_sync_status() -> None:
        from colorPickerPro.main import MainWindow
        from colorPickerPro.ui.tokens import State

        win = MainWindow()
        try:
            harness.prepare(win)          # WA_DontShowOnScreen：真实布局但不弹出
            harness.settle(win)
            status = win._sync_status
            assert status.isVisible(), "主窗口「颜色同步」状态标签不可见"
            # 停掉后台轮询，否则同步线程可能在我们设置长消息后立刻覆盖它；
            # 停线程后再排空一次事件队列，处理线程退出前已投递的状态更新。
            sync = getattr(win, "_sync", None)
            if sync is not None:
                sync.stop_thread()
            harness.settle(win)
            harness.settle(win)
            before_width = win.centralWidget().minimumSizeHint().width()
            long_message = (
                "同步失败：无法连接 Photoshop（错误代码 0x80004005，"
                "请检查首选项中的远程连接设置）" * 4)
            status.set_message(long_message, State.WARNING)
            harness.settle(win)
            assert status.text() == long_message, "状态标签未显示完整消息"
            assert status.toolTip(), "长状态消息应设置 tooltip 以便查看全文"
            content_min = win.centralWidget().minimumSizeHint().width()
            window_min = win.minimumSizeHint().width()
            assert content_min <= 360, (
                f"长状态消息把窗口内容最小宽度撑到 {content_min}px（要求 ≤360）")
            assert window_min <= 360 + 1, (
                f"长状态消息把窗口最小宽度撑到 {window_min}px（要求 ≤360）")
            assert before_width <= content_min + 1, (
                "状态标签宽度统计异常（设置消息后内容最小宽度反而变小）")
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            win.deleteLater()
            QApplication.processEvents()

    # ---- 3. FilterSchemePanel 切换图层后参数区重建 ----------------------
    def check_filter_params_rebuild() -> None:
        from colorPickerPro.filter_scheme_panel import FilterSchemePanel

        panel = FilterSchemePanel(
            fixtures.scheme_named("参数重建", ["信息量分析", "颜色反转"]),
            store=fixtures.store("functional"))
        try:
            assert panel._layer_list.count() == 2, (
                f"图层列表应有 2 项，实际 {panel._layer_list.count()}")
            count_params = len(panel._params_widget.params())
            assert count_params == 8, f"信息量分析应有 8 个参数，实际 {count_params}"
            panel._layer_list.setCurrentRow(1)
            QApplication.processEvents()
            count_params = len(panel._params_widget.params())
            assert count_params == 0, (
                f"颜色反转应无参数，切换后仍有 {count_params} 个（参数区未重建）")
            panel._layer_list.setCurrentRow(0)
            QApplication.processEvents()
            count_params = len(panel._params_widget.params())
            assert count_params == 8, f"切回信息量分析后参数未重建: {count_params}"
        finally:
            panel.close()
            panel.deleteLater()
            QApplication.processEvents()

    # ---- 4. ImageViewer 缩放 / 旋转 / 翻转 / 适应 -----------------------
    def check_image_viewer_transforms() -> None:
        from colorPickerPro.image_viewer import ImageViewer

        viewer = ImageViewer(fixtures.pixmap())
        try:
            viewer.resize(640, 480)
            viewer.ensurePolished()
            assert viewer.export_view_transform().zoom > 0, "初始 zoom 无效"
            viewer._view.set_zoom(2.0)
            QApplication.processEvents()
            assert abs(viewer.export_view_transform().zoom - 2.0) < 1e-6, (
                "set_zoom(2.0) 未生效")
            viewer._view.rotate_90()
            QApplication.processEvents()
            assert abs(viewer.export_view_transform().rotation - 90.0) < 1e-6, (
                "rotate_90() 未生效")
            viewer._view.flip_horizontal()
            viewer._view.flip_vertical()
            QApplication.processEvents()
            transform = viewer.export_view_transform()
            assert transform.flip_h and transform.flip_v, "水平/垂直翻转未生效"
            viewer._view.fit_in_view()
            QApplication.processEvents()
            assert viewer.export_view_transform().zoom > 0, "fit_in_view() 后 zoom 无效"
        finally:
            viewer.close()
            viewer.deleteLater()
            QApplication.processEvents()

    # ---- 5. ImageFilterCompareWindow 重叠 / 横向模式切换 ----------------
    def check_compare_view_modes() -> None:
        from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
        from colorPickerPro.list_viewer import ListViewer

        win = ImageFilterCompareWindow(
            fixtures.pixmap(),
            [fixtures.scheme(1, "功能方案 A"), fixtures.scheme(2, "功能方案 B")])
        try:
            list_viewer = win._list_viewer
            assert list_viewer.view_mode == ListViewer.ViewMode.OVERLAP, (
                "对比窗口初始应为重叠模式")
            assert len(list_viewer._item_widgets) == 3, (
                f"对比项应为 3 个（无滤镜 + 2 方案），实际 {len(list_viewer._item_widgets)}")
            list_viewer.set_view_mode(ListViewer.ViewMode.HORIZONTAL)
            QApplication.processEvents()
            assert list_viewer.view_mode == ListViewer.ViewMode.HORIZONTAL, (
                "切换到横向模式失败")
            list_viewer._btn_toggle.click()
            QApplication.processEvents()
            assert list_viewer.view_mode == ListViewer.ViewMode.OVERLAP, (
                "点击「重叠对比」未切回重叠模式")
        finally:
            win.close()
            win.deleteLater()
            QApplication.processEvents()

    # ---- 6. 弹窗「确定 / 取消」行为 -------------------------------------
    def check_dialogs_accept_reject() -> None:
        from colorPickerPro.color_picker_dialog import ColorPickerDialog
        from colorPickerPro.filter_scheme_selector import FilterSchemeSelectorDialog
        from colorPickerPro.list_selection_dialog import ListSelectionDialog

        picker = ColorPickerDialog()
        emitted: list = []
        picker.colorSelected.connect(lambda r, g, b: emitted.append((r, g, b)))
        try:
            picker._ok_btn.click()
            assert picker.result() == QDialog.DialogCode.Accepted, "取色对话框「确定」未接受"
            assert emitted, "取色对话框「确定」未发出 colorSelected"
        finally:
            picker.deleteLater()
            QApplication.processEvents()

        selector = FilterSchemeSelectorDialog(
            None, "功能测试", store=fixtures.store("functional"))
        try:
            assert selector.current_scheme() is not None, "选择器默认没有选中项"
            selector._btn_ok.click()
            assert selector.result() == QDialog.DialogCode.Accepted, (
                "滤镜选择弹窗「确定」未接受")
        finally:
            selector.deleteLater()
            QApplication.processEvents()

        selector2 = FilterSchemeSelectorDialog(
            None, "功能测试", store=fixtures.store("functional"))
        try:
            selector2._btn_cancel.click()
            assert selector2.result() == QDialog.DialogCode.Rejected, (
                "滤镜选择弹窗「取消」未拒绝")
        finally:
            selector2.deleteLater()
            QApplication.processEvents()

        listing = ListSelectionDialog(
            None, "功能测试", LIST_ITEMS,
            selection_mode="multiple", checked_indices=[0, 2])
        chosen: list = []
        listing.selectedIndices.connect(lambda indices: chosen.append(list(indices)))
        try:
            listing._on_item_clicked(4)
            listing.accept()
            assert chosen, "列表选择弹窗未发出 selectedIndices"
            assert 0 in chosen[-1] and 2 in chosen[-1] and 4 in chosen[-1], (
                f"多选结果不正确: {chosen[-1]}")
        finally:
            listing.deleteLater()
            QApplication.processEvents()

    # ---- 7. 滤镜方案保存（不弹输入/确认对话框） -------------------------
    def check_filter_scheme_save() -> None:
        import colorPickerPro.filter_scheme_panel as panel_mod
        from colorPickerPro.filter_scheme import filter_class_by_name

        store = fixtures.store("functional-save")
        panel = panel_mod.FilterSchemePanel(
            fixtures.scheme_named("待保存方案", ["颜色反转"]), store=store)
        real_prompt_text = panel_mod.prompt_text

        def _fake_prompt_text(*args, **kwargs):
            return ("功能测试方案", True)

        panel_mod.prompt_text = _fake_prompt_text
        try:
            assert panel.is_dirty() is False, "新面板不应处于未保存状态"
            extra = filter_class_by_name("RGB灰度")
            assert extra is not None, "找不到 RGB灰度 滤镜"
            panel._add_filter(extra)
            assert len(panel.scheme.layers) == 2, "添加图层失败"
            assert panel.is_dirty() is True, "修改后应出现未保存标记"
            panel._on_save()
            assert "功能测试方案" in store.names(), (
                f"保存后方案仓库缺少新方案: {store.names()}")
            assert panel.is_dirty() is False, "保存后仍显示未保存标记"
            saved = store.get("功能测试方案")
            assert saved is not None and len(saved.layers) == 2, (
                "保存的方案图层数不正确")
        finally:
            panel_mod.prompt_text = real_prompt_text
            panel.close()
            panel.deleteLater()
            QApplication.processEvents()

    # ---- 8. 屏幕滤镜窗口：只构建，定时器不得处于运行状态 ----------------
    def check_screen_filter_timers() -> None:
        from colorPickerPro.screenFilter import ScreenFilterWindow

        win = ScreenFilterWindow(fixtures.scheme(1, "功能定时器"))
        try:
            assert win._timer.isActive() is False, "ScreenFilterWindow 构造后 _timer 已在跑"
            assert win._debounce_timer.isActive() is False, (
                "ScreenFilterWindow 构造后 _debounce_timer 已在跑")
            assert win._auto_collapse_timer.isActive() is False, (
                "ScreenFilterWindow 构造后自动折叠轮询已在跑")
        finally:
            win.stop()
            win.close()
            win.deleteLater()
            QApplication.processEvents()

    # ---- 8b. 屏幕滤镜窗口自动折叠：离开收起 / 进入展开 / 手动关闭开关 ----
    def check_screen_filter_auto_collapse() -> None:
        from PySide6.QtCore import QPoint
        from colorPickerPro import screenFilter as screen_filter_module
        from colorPickerPro.screenFilter import ScreenFilterWindow
        from colorPickerPro.ui.tokens import SIZE

        # 真机鼠标按键状态会让「拖拽中不折叠」的保护生效；冒烟测试要确定性，
        # 临时替换物理按键判断（该保护由 test_window_state 单独覆盖）。
        original_mouse_guard = screen_filter_module.mouse_button_pressed
        screen_filter_module.mouse_button_pressed = lambda: False
        win = ScreenFilterWindow(fixtures.scheme(1, "自动折叠滤镜"))
        try:
            harness.prepare(win)
            harness.settle(win)
            assert win.is_collapsed() is False, "屏幕滤镜窗口初始不应折叠"
            button = win._btn_auto_collapse
            button.setChecked(True)
            QApplication.processEvents()
            win._auto_collapse_timer.stop()   # 手动驱动，避免真实光标干扰
            win._auto_collapse_step(QPoint(-99999, -99999))
            QApplication.processEvents()
            harness.settle(win)
            assert win.is_collapsed(), "鼠标离开后屏幕滤镜窗口没有折叠"
            assert win.height() == SIZE.title_bar_height + 2, (
                f"折叠后应只剩标题栏，实际高度 {win.height()}")

            win._auto_collapse_step(win.geometry().center())
            QApplication.processEvents()
            harness.settle(win)
            assert not win.is_collapsed(), "鼠标进入标题栏后屏幕滤镜窗口没有展开"

            # 手动折叠（双击标题栏）必须同时关闭自动折叠。
            button.setChecked(True)
            QApplication.processEvents()
            win._auto_collapse_timer.stop()
            win.title_bar.collapseRequested.emit()
            QApplication.processEvents()
            assert win.is_collapsed(), "屏幕滤镜窗口手动折叠没有生效"
            assert win._auto_collapse_enabled is False, (
                "手动折叠应同时关闭自动折叠")
            assert win._btn_auto_collapse.isChecked() is False
        finally:
            win.stop()
            win._auto_collapse_timer.stop()
            win.close()
            win.deleteLater()
            screen_filter_module.mouse_button_pressed = original_mouse_guard
            QApplication.processEvents()

    # ---- 8c. 屏幕滤镜窗口：图像区域左键取色 ---------------------------
    def check_screen_filter_pick_color() -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPixmap
        from PySide6.QtTest import QTest
        from colorPickerPro.screenFilter import ScreenFilterWindow

        win = ScreenFilterWindow(fixtures.scheme(1, "取色滤镜"))
        try:
            harness.prepare(win)
            harness.settle(win)
            image = QImage(8, 8, QImage.Format.Format_ARGB32)
            image.fill(QColor("#336699"))
            win._content.setPixmap(QPixmap.fromImage(image))
            picked = []
            win.colorPicked.connect(lambda r, g, b: picked.append((r, g, b)))
            QTest.mouseClick(win._content, Qt.MouseButton.LeftButton,
                             pos=win._content.rect().center())
            QApplication.processEvents()
            assert picked == [(0x33, 0x66, 0x99)], (
                f"屏幕滤镜左键取色结果不正确: {picked}")
            assert "#336699" in win.title_bar.subtitle_label.full_text(), (
                f"取色后标题栏没有显示 HEX: "
                f"{win.title_bar.subtitle_label.full_text()!r}")
            win._clear_pick_hint()
            assert win.title_bar.subtitle_label.full_text() == ""
        finally:
            win._pick_hint_timer.stop()
            win.stop()
            win.close()
            win.deleteLater()
            QApplication.processEvents()

    # ---- 9. Phase 2：自绘标题栏按钮齐全且 SVG 图标已加载 ---------------
    def check_titlebar_buttons() -> None:
        from PySide6.QtCore import Qt
        from colorPickerPro.color_picker_dialog import ColorPickerDialog
        from colorPickerPro.filter_lib import ImageFilter
        from colorPickerPro.filter_scheme import FilterScheme
        from colorPickerPro.filter_scheme_panel import FilterSchemePanel
        from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
        from colorPickerPro.main import MainWindow
        from colorPickerPro.screenFilter import ScreenFilterWindow
        from colorPickerPro.ui.components import MessageDialog, TextInputDialog

        def verify_buttons(widget, label: str,
                           expect_min: bool, expect_max: bool) -> None:
            title_bar = getattr(widget, "title_bar", None)
            assert title_bar is not None, f"{label}: 缺少自绘标题栏"
            assert title_bar.objectName() == "TitleBar", (
                f"{label}: 标题栏 objectName={title_bar.objectName()!r}")
            for expected_present, attr, expected_icon in (
                    (expect_min, "_btn_min", "minimize"),
                    (expect_max, "_btn_max", "maximize"),
                    (True, "_btn_close", "close")):
                button = getattr(title_bar, attr, None)
                if not expected_present:
                    assert button is None, f"{label}: 不应存在 {attr}"
                    continue
                assert button is not None, f"{label}: 缺少 {attr}"
                assert button.icon_name() == expected_icon, (
                    f"{label}: {attr} 图标应为 {expected_icon!r}，"
                    f"实际 {button.icon_name()!r}")
                assert not button.icon().isNull(), f"{label}: {attr} 的 SVG 图标为空"

        picker = ColorPickerDialog()
        try:
            harness.prepare(picker)
            harness.settle(picker)
            verify_buttons(picker, "ColorPickerDialog", False, False)
            assert picker.title_bar.isVisible(), "ColorPickerDialog 标题栏不可见"
        finally:
            # 必须 close：ColorPickerDialog 是 WindowModal，只 deleteLater
            # 会让它保持可见并继续充当 activeModalWidget，影响后续检查。
            picker.close()
            picker.deleteLater()
            QApplication.processEvents()

        win = MainWindow()
        try:
            harness.prepare(win)
            harness.settle(win)
            verify_buttons(win, "MainWindow", True, False)
            assert win.title_bar.isVisible(), "MainWindow 标题栏不可见"
            pin = getattr(win, "_pin_btn", None)
            assert pin is not None, "MainWindow 缺少置顶按钮"
            assert pin.icon_name() == "pin", (
                f"置顶按钮图标应为 'pin'，实际 {pin.icon_name()!r}")
            assert pin.isCheckable(), "置顶按钮应为可切换状态"
            assert not pin.icon().isNull(), "置顶按钮 SVG 图标为空"
            auto = getattr(win, "_auto_collapse_btn", None)
            assert auto is not None, "MainWindow 缺少自动折叠按钮"
            assert auto.icon_name() == "collapse", (
                f"自动折叠按钮图标应为 'collapse'，实际 {auto.icon_name()!r}")
            assert auto.isCheckable(), "自动折叠按钮应为可切换状态"
            assert not auto.icon().isNull(), "自动折叠按钮 SVG 图标为空"
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            win.deleteLater()
            QApplication.processEvents()

        compare = ImageFilterCompareWindow(
            fixtures.pixmap(), [fixtures.scheme(1, "标题栏方案")])
        try:
            harness.prepare(compare)
            harness.settle(compare)
            verify_buttons(compare, "ImageFilterCompareWindow", True, True)
        finally:
            compare.close()
            compare.deleteLater()
            QApplication.processEvents()

        screen = ScreenFilterWindow(fixtures.scheme(1, "标题栏滤镜"))
        try:
            harness.prepare(screen)
            harness.settle(screen)
            verify_buttons(screen, "ScreenFilterWindow", True, False)
            auto = getattr(screen, "_btn_auto_collapse", None)
            assert auto is not None, "屏幕滤镜窗口缺少自动折叠按钮"
            assert auto.icon_name() == "collapse", (
                f"屏幕滤镜自动折叠按钮图标应为 'collapse'，"
                f"实际 {auto.icon_name()!r}")
            assert auto.isCheckable(), "屏幕滤镜自动折叠按钮应为可切换状态"
            assert not auto.icon().isNull(), "屏幕滤镜自动折叠按钮 SVG 图标为空"
            for button, expected_icon in ((screen._btn_pause, "pause"),
                                          (screen._btn_params, "settings")):
                assert button.icon_name() == expected_icon, (
                    f"屏幕滤镜标题栏按钮图标应为 {expected_icon!r}，"
                    f"实际 {button.icon_name()!r}")
                assert not button.icon().isNull(), (
                    f"屏幕滤镜标题栏按钮 {expected_icon!r} 图标为空")
        finally:
            screen.stop()
            screen.close()
            screen.deleteLater()
            QApplication.processEvents()

        for dialog, label in (
                (MessageDialog(None, "标题栏测试", "消息内容。",
                               confirm_text="确定"), "MessageDialog"),
                (TextInputDialog(None, "标题栏测试", "名称：", "默认值"),
                 "TextInputDialog")):
            try:
                verify_buttons(dialog, label, False, False)
            finally:
                dialog.close()
                dialog.deleteLater()
                QApplication.processEvents()

        # 无按钮的对话框不能保留覆盖标题栏的 footer（否则标题文字无法拖动）。
        panel = FilterSchemePanel(
            FilterScheme.single(ImageFilter.all_filters()[0]))
        try:
            harness.prepare(panel)
            harness.settle(panel)
            assert panel.footer.isHidden(), (
                "无按钮的对话框 footer 应隐藏，避免遮住标题栏拖动区域")
            assert panel.title_bar.title_label.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        finally:
            panel.close()
            panel.deleteLater()
            QApplication.processEvents()

    # ---- 10. 标题栏关闭按钮关闭一次性窗口 -------------------------------
    def check_titlebar_close() -> None:
        from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
        from colorPickerPro.ui.components import MessageDialog

        dialog = MessageDialog(None, "关闭测试",
                               "点击标题栏关闭按钮应关闭本对话框。",
                               confirm_text="确定")
        try:
            harness.prepare(dialog)
            harness.settle(dialog)
            assert dialog.isVisible(), "准备后对话框应处于可见状态"
            dialog.title_bar._btn_close.click()
            QApplication.processEvents()
            harness.settle(dialog)
            assert not dialog.isVisible(), "点标题栏关闭按钮后对话框仍可见"
            assert dialog.result() == QDialog.DialogCode.Rejected, (
                f"关闭后 result={dialog.result()}（应为 Rejected）")
        finally:
            dialog.close()
            dialog.deleteLater()
            QApplication.processEvents()

        compare = ImageFilterCompareWindow(
            fixtures.pixmap(), [fixtures.scheme(1, "关闭测试")])
        try:
            harness.prepare(compare)
            harness.settle(compare)
            assert compare.isVisible(), "准备后对比窗口应处于可见状态"
            compare.title_bar._btn_close.click()
            QApplication.processEvents()
            harness.settle(compare)
            assert not compare.isVisible(), "点标题栏关闭按钮后对比窗口仍可见"
        finally:
            compare.close()
            compare.deleteLater()
            QApplication.processEvents()

    # ---- 11. 对比窗口最大化 + 主窗口置顶按钮 ---------------------------
    def check_titlebar_maximize() -> None:
        from PySide6.QtCore import Qt
        from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
        from colorPickerPro.main import MainWindow

        win = MainWindow()
        try:
            harness.prepare(win)
            harness.settle(win)
            assert win.title_bar._btn_max is None, (
                "主窗口不应再有最大化按钮")
            pin = win._pin_btn
            hwnd_before = int(win.winId())

            def _topmost() -> bool:
                if sys.platform != "win32":
                    return bool(win.windowFlags()
                                & Qt.WindowType.WindowStaysOnTopHint)
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                get_style = getattr(user32, "GetWindowLongPtrW",
                                    user32.GetWindowLongW)
                get_style.argtypes = (wintypes.HWND, ctypes.c_int)
                get_style.restype = ctypes.c_ssize_t
                return bool(int(get_style(int(win.winId()), -20)) & 0x8)

            assert not _topmost(), "主窗口初始不应置顶"
            pin.setChecked(True)
            QApplication.processEvents()
            harness.settle(win)
            assert _topmost(), "点击置顶后主窗口没有进入置顶状态"
            assert int(win.winId()) == hwnd_before, (
                "置顶切换不应销毁/重建原生窗口（会造成闪烁）")
            assert win.is_frameless(), "置顶切换后丢失无边框标志"
            pin.setChecked(False)
            QApplication.processEvents()
            harness.settle(win)
            assert not _topmost(), "取消置顶后主窗口仍置顶"
            assert int(win.winId()) == hwnd_before, (
                "取消置顶不应销毁/重建原生窗口")
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            win.deleteLater()
            QApplication.processEvents()

        compare = ImageFilterCompareWindow(
            fixtures.pixmap(), [fixtures.scheme(1, "最大化测试")])
        try:
            harness.prepare(compare)
            harness.settle(compare)
            button = compare.title_bar._btn_max
            button.click()
            QApplication.processEvents()
            harness.settle(compare)
            assert compare.isMaximized(), "对比窗口点最大化后 isMaximized() 为 False"
            button.click()
            QApplication.processEvents()
            harness.settle(compare)
            assert not compare.isMaximized(), "对比窗口点还原后仍处于最大化状态"
        finally:
            compare.close()
            compare.deleteLater()
            QApplication.processEvents()

    # ---- 11b. 主窗口自动折叠：离开折叠为标题栏 / 进入展开 ---------------
    def check_auto_collapse() -> None:
        from PySide6.QtCore import QPoint
        from colorPickerPro import main as main_module
        from colorPickerPro.ui.tokens import SIZE

        # 真机鼠标按键状态会让「拖拽中不折叠」的保护生效；冒烟测试要确定性，
        # 临时替换物理按键判断（该保护由 test_window_state 单独覆盖）。
        original_mouse_guard = main_module.mouse_button_pressed
        main_module.mouse_button_pressed = lambda: False
        win = main_module.MainWindow()
        try:
            harness.prepare(win)
            harness.settle(win)
            button = getattr(win, "_auto_collapse_btn", None)
            assert button is not None, "主窗口缺少自动折叠按钮"
            assert button.icon_name() == "collapse", (
                f"自动折叠按钮图标应为 'collapse'，实际 {button.icon_name()!r}")
            assert button.isCheckable(), "自动折叠按钮应为可切换状态"
            assert not button.icon().isNull(), "自动折叠按钮 SVG 图标为空"
            assert win.is_collapsed() is False, "主窗口初始不应折叠"

            button.setChecked(True)
            QApplication.processEvents()
            win._auto_collapse_timer.stop()   # 手动驱动，避免真实光标干扰
            win._auto_collapse_step(QPoint(-99999, -99999))
            QApplication.processEvents()
            harness.settle(win)
            assert win.is_collapsed(), "鼠标离开后主窗口没有折叠"
            assert win.height() == SIZE.title_bar_height + 2, (
                f"折叠后应只剩标题栏，实际高度 {win.height()}")
            assert win._body.isHidden(), "折叠后内容区应隐藏"

            win._auto_collapse_step(win.geometry().center())
            QApplication.processEvents()
            harness.settle(win)
            assert not win.is_collapsed(), "鼠标进入标题栏后主窗口没有展开"
            assert win._body.isVisible(), "展开后内容区应恢复显示"

            button.setChecked(False)
            QApplication.processEvents()
            assert win._auto_collapse_enabled is False
            assert not win._auto_collapse_timer.isActive(), (
                "关闭自动折叠后轮询定时器应停止")
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            win.deleteLater()
            QApplication.processEvents()
            main_module.mouse_button_pressed = original_mouse_guard

    # ---- 12. 手动边缘缩放（应用级事件过滤器）+ 1px 边框 ---------------
    def check_frameless_resize_and_rounding() -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from colorPickerPro.main import MainWindow
        from colorPickerPro.ui.tokens import qcolor

        win = MainWindow()
        try:
            harness.prepare(win)
            harness.settle(win)
            assert win.is_frameless(), "主窗口不是无边框窗口"
            before = win.width()

            def _send(kind, local: QPoint, global_pos: QPoint,
                      button, buttons, target=None) -> None:
                event = QMouseEvent(
                    kind, QPointF(local), QPointF(global_pos), button,
                    buttons, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(target or win, event)

            edge = QPoint(win.width() - 2, win.height() // 2)
            global_edge = win.mapToGlobal(edge)
            _send(QEvent.Type.MouseButtonPress, edge, global_edge,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
            target = QPoint(global_edge.x() - 60, global_edge.y())
            _send(QEvent.Type.MouseMove,
                  QPoint(edge.x() - 60, edge.y()), target,
                  Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
            _send(QEvent.Type.MouseButtonRelease,
                  QPoint(edge.x() - 60, edge.y()), target,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
            harness.settle(win)
            assert win.width() <= before - 55, (
                f"从右边缘拖动后宽度未变化：{before} -> {win.width()}")
            win.resize(before, win.height())
            harness.settle(win)

            # 单方向拖过最小宽度时，另一方向仍必须继续响应。
            before_h = win.height()
            corner = QPoint(win.width() - 2, win.height() - 2)
            corner_global = win.mapToGlobal(corner)
            _send(QEvent.Type.MouseButtonPress, corner, corner_global,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
            far = QPoint(corner_global.x() - 2000, corner_global.y() - 120)
            _send(QEvent.Type.MouseMove,
                  QPoint(corner.x() - 2000, corner.y() - 120), far,
                  Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
            _send(QEvent.Type.MouseButtonRelease,
                  QPoint(corner.x() - 2000, corner.y() - 120), far,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
            harness.settle(win)
            assert win.width() == win.minimumWidth(), (
                f"宽度应夹紧到最小值 {win.minimumWidth()}，实际 {win.width()}")
            assert win.height() <= before_h - 100, (
                f"宽度到极限后高度未继续缩放：{before_h} -> {win.height()}")
            win.resize(before, before_h)
            harness.settle(win)

            # 右下角 QSizeGrip：创建时偶发未激活，也必须能拖动缩放。
            grip = win._frameless_grip
            grip_size = win.size()
            grip_center = grip.rect().center()
            grip_global = grip.mapToGlobal(grip_center)
            _send(QEvent.Type.MouseButtonPress, grip_center, grip_global,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                  target=grip)
            grip_target = QPoint(grip_global.x() + 30, grip_global.y() + 20)
            _send(QEvent.Type.MouseMove,
                  grip_center + QPoint(30, 20), grip_target,
                  Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                  target=grip)
            _send(QEvent.Type.MouseButtonRelease,
                  grip_center + QPoint(30, 20), grip_target,
                  Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                  target=grip)
            harness.settle(win)
            assert (win.width() >= grip_size.width() + 25
                    and win.height() >= grip_size.height() + 15), (
                f"右下角手柄未能缩放：{grip_size} -> {win.size()}")
            win.resize(before, before_h)
            harness.settle(win)

            # 主窗口必须真的有 1px 边框（此前 central widget 会把边框盖住）。
            image = win.grab().toImage()
            border = qcolor("border_strong")
            iw, ih = image.width(), image.height()

            def _close(color) -> bool:
                return (abs(color.red() - border.red()) <= 40
                        and abs(color.green() - border.green()) <= 40
                        and abs(color.blue() - border.blue()) <= 40)

            bands = {
                "left": [(x, ih // 2) for x in range(0, 4)],
                "right": [(x, ih // 2) for x in range(iw - 4, iw)],
                "top": [(iw // 2, y) for y in range(0, 4)],
                "bottom": [(iw // 2, y) for y in range(ih - 4, ih)],
            }
            for name, points in bands.items():
                assert any(_close(image.pixelColor(x, y))
                           for x, y in points), (
                    f"主窗口 {name} 边框缺失（采样点均非边框色）")
        finally:
            teardown_main_window(win)
            QApplication.processEvents()
            win.deleteLater()
            QApplication.processEvents()

    # ---- 12b. 复用窗口 close() 后重新 show() 仍可边缘缩放 ---------------
    def check_frameless_resize_after_reopen() -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from colorPickerPro.filter_scheme_panel import FilterSchemePanel

        panel = FilterSchemePanel(fixtures.scheme(1, "缩放复用"))
        try:
            harness.prepare(panel)
            harness.settle(panel)

            def _drag_right_edge() -> bool:
                before = panel.width()
                height = panel.height() // 2
                edge = QPoint(panel.width() - 2, height)
                for kind, pos, button, buttons in (
                        (QEvent.Type.MouseButtonPress, edge,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
                        (QEvent.Type.MouseMove,
                         QPoint(edge.x() + 60, height),
                         Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
                        (QEvent.Type.MouseButtonRelease,
                         QPoint(edge.x() + 60, height),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)):
                    event = QMouseEvent(
                        kind, QPointF(pos), QPointF(panel.mapToGlobal(pos)),
                        button, buttons, Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(panel, event)
                    QApplication.processEvents()
                return panel.width() >= before + 40

            assert _drag_right_edge(), "滤镜方案面板首次显示时边缘缩放不可用"
            panel.close()
            QApplication.processEvents()
            panel.show()                 # 复用窗口再次显示（不再经过 prepare）
            QApplication.processEvents()
            harness.settle(panel)
            assert _drag_right_edge(), (
                "滤镜方案面板关闭后重新打开，边缘缩放失效"
                "（应用级事件过滤器未在 showEvent 重装）")
        finally:
            panel.close()
            panel.deleteLater()
            QApplication.processEvents()

    record("color_picker_models", check_color_picker_models)
    record("main_window_models", check_main_window_models)
    record("main_sync_status", check_main_sync_status)
    record("filter_params_rebuild", check_filter_params_rebuild)
    record("image_viewer_transforms", check_image_viewer_transforms)
    record("compare_view_modes", check_compare_view_modes)
    record("dialogs_accept_reject", check_dialogs_accept_reject)
    record("filter_scheme_save", check_filter_scheme_save)
    record("screen_filter_timers", check_screen_filter_timers)
    record("screen_filter_auto_collapse", check_screen_filter_auto_collapse)
    record("screen_filter_pick_color", check_screen_filter_pick_color)
    record("titlebar_buttons", check_titlebar_buttons)
    record("titlebar_close", check_titlebar_close)
    record("titlebar_maximize", check_titlebar_maximize)
    record("auto_collapse", check_auto_collapse)
    record("frameless_resize_round", check_frameless_resize_and_rounding)
    record("frameless_resize_reopen", check_frameless_resize_after_reopen)
    return checks


# ---------------------------------------------------------------------------
# 启动 / 主流程
# ---------------------------------------------------------------------------

def _apply_scale(arg_scale: float | None) -> float:
    """在创建 QApplication 之前设置 QT_SCALE_FACTOR，返回本次实际缩放。"""
    if arg_scale is not None:
        os.environ["QT_SCALE_FACTOR"] = str(arg_scale)
        return float(arg_scale)
    env_value = os.environ.get("QT_SCALE_FACTOR")
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            return 1.0
    return 1.0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="pixnex_colorful 全窗口多尺寸截图 + 布局/主题体检（无窗口弹出）")
    parser.add_argument("--only", metavar="SUBSTR",
                        help="只运行名称包含该子串（不区分大小写）的巡检项；"
                             "子串含 'static' 时只跑静态检查")
    parser.add_argument("--verbose", action="store_true",
                        help="输出所有明细、控件 stdout/stderr 与 traceback")
    parser.add_argument("--scale", type=float, metavar="FACTOR",
                        help="设置 QT_SCALE_FACTOR 后单通道运行（如 1.5）；"
                             "截图文件名带 _dpiNNN 后缀")
    parser.add_argument("--dpi-pass", nargs="?", const=1.5, type=float,
                        default=None, metavar="FACTOR",
                        help="主通道跑完后，用子进程再跑一次高 DPI 通道（默认 1.5）")
    parser.add_argument("--clean", action="store_true",
                        help="运行前清掉 build/ui-shots/ 里旧的 PNG 截图")
    parser.add_argument("--skip-functional", action="store_true",
                        help="跳过功能冒烟（模型切换 / 参数重建 / 变换 / 弹窗）")
    parser.add_argument("--list", action="store_true", help="列出巡检项后退出")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    args = _parse_args(argv)
    started = time.perf_counter()

    scale = _apply_scale(args.scale)
    suffix = "" if abs(scale - 1.0) < 1e-6 else f"_dpi{int(round(scale * 100))}"

    # ---- 启动 QApplication（必须在任何产品窗口创建之前） ----------------
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication

        from colorPickerPro.ui import apply_theme, configure_application
        from tools.render_widget import UIHarness
    except Exception as exc:
        print(f"启动失败：导入产品 UI 组件或渲染工具失败（可能正在重构中）:\n"
              f"  {type(exc).__name__}: {exc}")
        return 2

    configure_application()
    app = QApplication([])
    apply_theme(app)

    platform_name = app.platformName()
    if (platform_name == "offscreen"
            or os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen")):
        print("错误：检测到 Qt offscreen 平台。offscreen 插件没有系统字体，"
              "截图会变成豆腐块，无法做视觉巡检。\n"
              "请去掉 QT_QPA_PLATFORM=offscreen 后重试（本脚本不需要它）。")
        return 2
    if not app.styleSheet():
        print("错误：apply_theme() 之后 QApplication 仍没有样式表，主题未生效。")
        return 2

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        removed = 0
        for png in SHOTS_DIR.glob("*.png"):
            try:
                png.unlink()
                removed += 1
            except OSError:
                pass
        print(f"已清理旧截图 {removed} 张")
    report_path = SHOTS_DIR / f"latest_report{suffix}.txt"

    emit("=" * 100)
    emit("pixnex UI 布局 / 主题巡检  (tests/ui_layout_check.py)")
    emit(f"Python {sys.version.split()[0]} | PySide6 {pyside_version} | "
         f"Qt {qVersion()} | 平台 {platform_name} | 缩放 {scale:g}x | "
         f"DPR {app.primaryScreen().devicePixelRatio():g} | "
         f"字体 {app.font().family()}")
    emit(f"截图目录: {rel(SHOTS_DIR)} | 时间: "
         f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    emit("说明: 所有产品顶层窗口必须无边框（FramelessWindowHint）+ 自绘 TitleBar；"
         "grab() 触发真实布局与字体渲染。")
    emit("      几何体检: UIHarness.bounds_problems()（isVisible）+ isVisibleTo() 补充扫描，"
         "两层都必须为空。")
    emit("      静态检查: setStyleSheet=0、emoji=0、UI 文案无图标字符、"
         "SVG 图标资源齐全、QSS url() 无缺失/无 PNG。")
    emit("      功能冒烟: 模型切换/参数重建/查看器变换/弹窗/标题栏按钮/关闭/最大化/"
         "自动折叠/屏幕滤镜取色/复用窗口缩放。")
    if args.only:
        emit(f"筛选: --only {args.only!r}")
    emit("=" * 100)

    tmpdir = Path(tempfile.mkdtemp(
        prefix="pixnex-ui-check-", dir=str(ROOT / "build")))
    fixtures = Fixtures(tmpdir)
    harness = None
    results: list[SurfaceResult] = []
    static_ok = True
    exit_code = 0

    try:
        harness = UIHarness(output_dir=SHOTS_DIR)
        specs = build_specs(fixtures)
        selected = specs
        if args.only:
            needle = args.only.lower()
            selected = [s for s in specs if needle in s.name.lower()]
            if not selected and "static" not in needle:
                emit(f"错误：没有巡检项匹配 --only {args.only!r}。可用项：")
                for spec in specs:
                    emit(f"  - {spec.name}")
                emit("  - static:setStyleSheet")
                return 2

        if args.list:
            for spec in specs:
                print(f"{spec.name:<24s} {spec.description}")
            print(f"{'static:setStyleSheet':<24s} 产品代码 setStyleSheet 调用扫描（期望 0）")
            print(f"{'static:emoji':<24s} UI 文案 emoji 扫描（期望 0）")
            print(f"{'static:ui-glyphs':<24s} UI 文案禁用图标字符扫描（期望 0）")
            print(f"{'static:icons':<24s} IconButton/set_icon SVG 资源扫描")
            print(f"{'static:qss-assets':<24s} QSS url() 资源扫描（禁止 PNG）")
            print(f"{'functional':<24s} 功能冒烟：模型切换 / 参数重建 / 变换 / 弹窗 / 标题栏")
            return 0

        for spec in selected:
            result = run_surface(harness, spec, suffix=suffix)
            results.append(result)
            emit(_surface_line(result))
            if (not result.ok or result.problems or result.warnings
                    or result.info):
                _emit_surface_details(result, args.verbose)

        # ---- 静态检查：样式 / emoji / 图标字符 / SVG 资源 / QSS 资源 ----
        violations, counts = scan_setstylesheet()
        stylesheet_ok = _emit_static_report(violations, counts, args.verbose)
        emoji_violations, emoji_counts = scan_emoji()
        emoji_ok = _emit_emoji_report(emoji_violations, emoji_counts, args.verbose)
        glyph_violations, glyph_counts = scan_ui_glyphs()
        glyph_ok = _emit_ui_glyph_report(glyph_violations, glyph_counts, args.verbose)
        icon_violations, icon_refs = scan_icon_refs()
        icons_ok = _emit_icon_report(icon_violations, icon_refs, args.verbose)
        qss_violations, qss_checked = scan_qss_assets()
        qss_ok = _emit_qss_report(qss_violations, qss_checked, args.verbose)
        static_ok = (stylesheet_ok and emoji_ok and glyph_ok
                     and icons_ok and qss_ok)

        # ---- 功能冒烟（模型切换 / 参数重建 / 变换 / 模式 / 弹窗） -------
        functional: list[tuple[str, bool, str, str]] = []
        functional_ok = True
        run_functional = not args.skip_functional and not args.only
        if run_functional:
            emit("")
            emit("功能冒烟（--skip-functional 可跳过；不弹窗、不 show()）")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), \
                    contextlib.redirect_stderr(captured):
                functional = _run_functional_checks(fixtures, harness)
            for name, passed, detail, tb in functional:
                emit(f"{'PASS' if passed else 'FAIL'}  {'func:' + name:<24s}")
                if not passed:
                    emit(f"      - {detail}")
                    if args.verbose:
                        for line in tb.rstrip().splitlines():
                            emit(f"        {line}")
            functional_ok = all(passed for _, passed, _, _ in functional)
            if args.verbose and captured.getvalue().strip():
                lines = captured.getvalue().rstrip().splitlines()
                emit(f"      · 功能冒烟控件输出（{len(lines)} 行）:")
                for line in lines[:80]:
                    emit(f"        {line}")
                if len(lines) > 80:
                    emit(f"        ... 省略 {len(lines) - 80} 行")

        # ---- 汇总 -------------------------------------------------------
        failed = [r for r in results if not r.ok]
        func_failed = [name for name, passed, _, _ in functional if not passed]
        total = len(results)
        shot_count = sum(len(r.shots) for r in results)
        main_ok = not failed and static_ok and functional_ok
        main_exit = 0 if main_ok else 1
        elapsed = time.perf_counter() - started
        emit("-" * 100)
        func_text = (f"{len(functional) - len(func_failed)}/{len(functional)}"
                     if run_functional else "跳过")
        emit(f"汇总: 界面 {total - len(failed)}/{total} 通过，失败 {len(failed)}；"
             f"静态检查 {'PASS' if static_ok else 'FAIL'}；功能冒烟 {func_text}；"
             f"截图 {shot_count} 张；耗时 {elapsed:.1f}s")
        failure_parts = [r.name for r in failed]
        if not stylesheet_ok:
            failure_parts.append("static:setStyleSheet")
        if not emoji_ok:
            failure_parts.append("static:emoji")
        if not glyph_ok:
            failure_parts.append("static:ui-glyphs")
        if not icons_ok:
            failure_parts.append("static:icons")
        if not qss_ok:
            failure_parts.append("static:qss-assets")
        failure_parts += [f"func:{name}" for name in func_failed]
        if failure_parts:
            emit("失败项: " + ", ".join(failure_parts))
        emit(f"截图目录: {rel(SHOTS_DIR)}")
        emit(f"DPI 通道（手动）: .venv\\Scripts\\python.exe tests\\ui_layout_check.py "
             f"--scale 1.5")
        emit(f"报告: {rel(report_path)}")

        # ---- 可选：高 DPI 第二通道（子进程，QApplication 必须重建） ----
        dpi_exit = 0
        if args.dpi_pass is not None:
            emit("")
            emit(f"[DPI] 启动第二通道: QT_SCALE_FACTOR={args.dpi_pass:g} "
                 f"（子进程，重建 QApplication）")
            child_cmd = [sys.executable, str(Path(__file__).resolve()),
                         "--scale", str(args.dpi_pass)]
            if args.only:
                child_cmd += ["--only", args.only]
            if args.verbose:
                child_cmd += ["--verbose"]
            env = os.environ.copy()
            env["QT_SCALE_FACTOR"] = str(args.dpi_pass)
            proc = subprocess.run(
                child_cmd, cwd=str(HELPERS_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            if proc.stdout:
                # 子通道报告原样转发到当前控制台（不进主报告文件）。
                print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n",
                      flush=True)
            dpi_exit = proc.returncode
            emit(f"[DPI] 第二通道退出码 {dpi_exit}")

        final_exit = 1 if (main_exit or dpi_exit) else 0
        exit_code = final_exit
        emit(f"结果: {'PASS' if final_exit == 0 else 'FAIL'}（退出码 {final_exit}）")
        if final_exit:
            emit("提示: FAIL 明细见上方各界面下的 ' - ' 行；"
                 "加 --verbose 可看 traceback 与控件输出。")
        emit("=" * 100)

    except Exception as exc:  # 巡检框架自身出错：打印完整 traceback 便于定位
        traceback.print_exc()
        emit("")
        emit(f"巡检框架异常: {type(exc).__name__}: {exc}")
        exit_code = 2
    finally:
        if harness is not None:
            try:
                harness.close()
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            report_path.write_text("\n".join(REPORT_LINES) + "\n", encoding="utf-8")
        except OSError:
            pass

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
