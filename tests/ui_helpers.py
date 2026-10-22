"""tests/ui_layout_check.py 的共享工具（独立运行、只用标准库 + PySide6）。

设计要点（为什么不用 show()）
------------------------------
任务要求巡检时不得弹出任何窗口，因此这里从不调用 ``show()``。
隐藏的顶层窗口在 Qt 里不会真正执行布局，直到 ``grab()``/``render()`` 时才
会布局，所以截图仍然正确。

但这也带来一个坑：``UIHarness.bounds_problems()`` 只统计 ``isVisible()`` 的
子控件，而隐藏窗口的所有子控件都 ``isVisible() == False``，于是它永远返回
空列表，失去体检意义。因此这里再用 ``isVisibleTo(top)`` 补一个等价扫描
（语义：如果窗口显示出来，这些控件会不会露出来），两者都必须为空。

所有几何问题都输出「控件类名#objectName geometry=(x,y,w,h) 越界 / 父控件」
这样的可直接定位的文本。
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractScrollArea, QWidget  # noqa: E402

SHOTS_DIR = ROOT / "build" / "ui-shots"
ICON_DIR = ROOT / "colorPickerPro" / "ui" / "assets" / "icons"

# 设计系统唯一允许应用 QSS 的地方：全局主题安装（UI_ARCHITECTURE §2）。
# 其余任何业务/组件代码里的 setStyleSheet 调用都算违规。
QSS_ALLOWED_FILES = {"colorPickerPro/ui/theme.py"}

_SET_STYLESHEET_CALL = re.compile(r"\.\s*setStyleSheet\s*\(")

_QT_SIZE_UNLIMITED = 16777215

# Phase 2：图标全改为 SVG 资源，UI 文案（非 docstring/注释）里不允许再出现这些字符。
FORBIDDEN_UI_GLYPHS = "✕─▶⏸❚⚙↔↕↻＋"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SurfaceSpec:
    """一个待巡检界面：构建函数 + 多个渲染尺寸。"""

    name: str
    factory: Callable[[], QWidget]
    sizes: Sequence[tuple[int, int]]
    kind: str = "window"          # window | dialog | widget
    resizable: bool = True        # 顶层 window/dialog 是否应可缩放
    frameless: bool = False       # 是否要求无边框 + 自绘 TitleBar
    teardown: Callable[[QWidget], None] | None = None
    description: str = ""


@dataclass
class SurfaceResult:
    """一个界面的巡检结果（一条 PASS/FAIL 行 + 明细）。"""

    name: str
    kind: str = "window"
    ok: bool = True
    error: str = ""
    traceback_text: str = ""
    shots: list[Path] = field(default_factory=list)
    # (请求尺寸, 实际尺寸)
    sizes: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    captured_output: str = ""

    def fail(self, message: str) -> None:
        self.ok = False
        if message not in self.problems:
            self.problems.append(message)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def note(self, message: str) -> None:
        if message not in self.info:
            self.info.append(message)


# ---------------------------------------------------------------------------
# 几何体检
# ---------------------------------------------------------------------------

def _describe(widget: QWidget) -> str:
    name = widget.objectName()
    cls = type(widget).__name__
    return f"{cls}#{name}" if name else cls


def _is_scroll_content(parent: QWidget) -> bool:
    """父控件是不是滚动区的视口？滚动内容允许比视口大（负偏移也是正常的）。"""
    grand = parent.parentWidget()
    return (isinstance(grand, QAbstractScrollArea)
            and grand.viewport() is parent)


def hidden_bounds_problems(widget: QWidget, *, tolerance: int = 1) -> list[str]:
    """隐藏窗口版 ``bounds_problems``：用 isVisibleTo() 代替 isVisible()。

    只报告「如果窗口显示出来就会露馅」的情况：
    - 子控件几何超出父控件矩形；
    - 有布局的子控件小于自己的 minimumSizeHint（会被裁切）。
    """
    problems: list[str] = []
    for child in _inspectable_children(widget):
        parent = child.parentWidget()
        if parent is None:  # pragma: no cover - _inspectable_children 已过滤
            continue
        geometry = child.geometry()
        parent_rect = parent.rect()
        if (geometry.left() < -tolerance
                or geometry.top() < -tolerance
                or geometry.right() > parent_rect.width() + tolerance
                or geometry.bottom() > parent_rect.height() + tolerance):
            problems.append(
                f"{_describe(child)} geometry={geometry.getRect()} 越界，"
                f"父控件 {_describe(parent)} {parent_rect.width()}x{parent_rect.height()}")
        hint = child.minimumSizeHint()
        if (child.layout() is not None and hint.isValid()
                and (child.width() + tolerance < hint.width()
                     or child.height() + tolerance < hint.height())):
            problems.append(
                f"{_describe(child)} size={child.width()}x{child.height()} 小于 "
                f"minimumSizeHint={hint.width()}x{hint.height()}")
    return problems


def _inspectable_children(widget: QWidget) -> list[QWidget]:
    """按 hidden_bounds_problems 的口径列出会被体检的子控件（用于报告覆盖数）。"""
    top = widget
    children: list[QWidget] = []
    for child in top.findChildren(QWidget):
        if child.isWindow() or not child.isVisibleTo(top):
            continue
        parent = child.parentWidget()
        if parent is None or _is_scroll_content(parent):
            continue
        children.append(child)
    return children


# ---------------------------------------------------------------------------
# Phase 2：无边框窗口 + 自绘标题栏
# ---------------------------------------------------------------------------

def frameless_problems(widget: QWidget) -> list[str]:
    """检查顶层窗口是否真的无边框，并且挂了统一的 ``TitleBar``。

    覆盖：FramelessWindowHint、``title_bar`` 属性或 objectName="TitleBar"
    的子控件、标题栏可见性、关闭按钮存在且 SVG 图标已加载。
    """
    problems: list[str] = []
    if not widget.isWindow():
        problems.append(f"{type(widget).__name__} 不是顶层窗口，无法检查无边框")
        return problems
    if not (widget.windowFlags() & Qt.WindowType.FramelessWindowHint):
        problems.append(
            f"{type(widget).__name__} 缺少 Qt.FramelessWindowHint"
            f"（原生标题栏/边框仍在）")

    title_bar = getattr(widget, "title_bar", None)
    if not isinstance(title_bar, QWidget):
        title_bar = widget.findChild(QWidget, "TitleBar")
    if title_bar is None:
        problems.append(
            f"{type(widget).__name__} 找不到自绘标题栏"
            f"（objectName='TitleBar' 或 .title_bar 属性）")
        return problems

    if title_bar.objectName() != "TitleBar":
        problems.append(
            f"{type(widget).__name__} 的标题栏 objectName="
            f"{title_bar.objectName()!r}（应为 'TitleBar'）")
    if title_bar.window() is not widget:
        problems.append(
            f"{type(widget).__name__} 的 TitleBar 不属于该窗口"
            f"（window={type(title_bar.window()).__name__}）")
    if not title_bar.isVisibleTo(widget):
        problems.append(f"{type(widget).__name__} 的 TitleBar 不可见（未加入布局？）")

    close_button = getattr(title_bar, "_btn_close", None)
    if close_button is None:
        problems.append(f"{type(widget).__name__} 标题栏缺少关闭按钮")
    elif close_button.icon_name() != "close":
        problems.append(
            f"{type(widget).__name__} 关闭按钮图标应为 'close'，"
            f"实际 {close_button.icon_name()!r}")
    elif close_button.icon().isNull():
        problems.append(
            f"{type(widget).__name__} 关闭按钮 SVG 图标为空"
            f"（资源缺失或无法渲染）")

    # 标题栏里所有图标按钮都必须有可渲染的 SVG 图标。
    from colorPickerPro.ui.components import IconButton

    for button in title_bar.findChildren(IconButton):
        if button.icon().isNull():
            problems.append(
                f"{type(widget).__name__} 标题栏图标按钮 "
                f"{button.icon_name()!r} 的图标为空")
    return problems


# ---------------------------------------------------------------------------
# 单个界面的构建 / 渲染 / 体检 / 清理
# ---------------------------------------------------------------------------

def _default_teardown(widget: QWidget) -> None:
    if widget.isWindow():
        widget.close()
    else:
        widget.hide()


def run_surface(harness, spec: SurfaceSpec, *, suffix: str = "",
                tolerance: int = 1) -> SurfaceResult:
    """构建界面并渲染到每个尺寸，返回巡检结果。不调用 show()。"""
    result = SurfaceResult(spec.name, spec.kind)
    captured = io.StringIO()
    widget: QWidget | None = None

    # 先删掉本界面本轮要生成的旧截图：如果构建失败，目录里不会残留上一轮的
    # 过期图片，避免人工目检时被旧图误导（只删精确的 <name>_<w>x<h>.png）。
    for width, height in spec.sizes:
        stale = SHOTS_DIR / f"{spec.name}{suffix}_{width}x{height}.png"
        try:
            stale.unlink()
        except OSError:
            pass

    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            widget = spec.factory()
        except Exception as exc:  # 构建失败（重构中的产品代码常见）
            result.error = f"构建失败: {type(exc).__name__}: {exc}"
            result.traceback_text = traceback.format_exc()
            result.captured_output = captured.getvalue()
            result.ok = False
            return result

        try:
            widget.ensurePolished()
            # 「配置的最小尺寸」必须在布局激活前记录：Qt 的布局激活可能回写
            # 控件 minimumSize，之后再比较就永远相等了。
            configured_min = (widget.minimumWidth(), widget.minimumHeight())
            configured_max = (widget.maximumWidth(), widget.maximumHeight())

            # Phase 2：所有产品窗口都必须无边框 + 自绘标题栏。
            if spec.frameless:
                frameless_issues = frameless_problems(widget)
                for problem in frameless_issues:
                    result.fail(problem)
                if not frameless_issues:
                    title_bar = getattr(widget, "title_bar", None)
                    button_names = [
                        getattr(title_bar, attr).icon_name()
                        for attr in ("_btn_min", "_btn_max", "_btn_close")
                        if title_bar is not None
                        and getattr(title_bar, attr, None) is not None
                    ]
                    result.note(
                        f"无边框: FramelessWindowHint=True, TitleBar 按钮="
                        f"{button_names}")

            if widget.isWindow():
                if spec.resizable and (configured_min[0] == configured_max[0]
                                       and configured_min[1] == configured_max[1]):
                    result.fail(
                        f"{type(widget).__name__} 固定尺寸窗口：min==max=="
                        f"{configured_min[0]}x{configured_min[1]}，"
                        f"不满足「窗口应可缩放」的要求")
                if (configured_max[0] < _QT_SIZE_UNLIMITED
                        or configured_max[1] < _QT_SIZE_UNLIMITED):
                    result.warn(
                        f"{type(widget).__name__} 设置了最大尺寸 maximumSize="
                        f"{configured_max[0]}x{configured_max[1]}"
                        f"（UI_ARCHITECTURE §5.2 建议不要 setMaximumSize，"
                        f"否则大窗口/高 DPI 下无法铺满）")

            hint_checked = False
            for width, height in spec.sizes:
                try:
                    paths = harness.render(
                        widget, f"{spec.name}{suffix}", [(width, height)])
                    shot = paths[0] if paths else None
                except Exception as exc:
                    result.fail(
                        f"[{width}x{height}] 渲染/截图异常: "
                        f"{type(exc).__name__}: {exc}")
                    result.traceback_text += traceback.format_exc()
                    continue

                if shot is None or not shot.exists() or shot.stat().st_size == 0:
                    result.fail(f"[{width}x{height}] 截图写入失败: {shot}")
                else:
                    result.shots.append(shot)

                actual = (widget.width(), widget.height())
                result.sizes.append(((width, height), actual))
                if actual != (width, height):
                    outside_limits = (
                        width < configured_min[0] or height < configured_min[1]
                        or width > configured_max[0] or height > configured_max[1])
                    if outside_limits:
                        result.note(
                            f"请求 {width}x{height} 被限制为 {actual[0]}x"
                            f"{actual[1]}（窗口最小/最大尺寸）")
                    else:
                        result.fail(
                            f"{type(widget).__name__} 请求 {width}x{height}，"
                            f"实际 {actual[0]}x{actual[1]}："
                            f"布局最小尺寸大于请求尺寸，窄窗口/高 DPI 下会被撑大"
                            f"（考虑 FlowLayout / ScrollArea）")

                # minimumSizeHint 不大于配置的最小尺寸（有配置时）
                if not hint_checked:
                    hint_checked = True
                    hint = widget.minimumSizeHint()
                    if hint.isValid():
                        if widget.isWindow():
                            result.note(
                                f"最小尺寸: 配置 {configured_min[0]}x"
                                f"{configured_min[1]}，minimumSizeHint "
                                f"{hint.width()}x{hint.height()}")
                        if (configured_min[0] > 0
                                and hint.width() > configured_min[0] + tolerance):
                            result.fail(
                                f"{type(widget).__name__}.minimumSizeHint().width()="
                                f"{hint.width()} 大于配置的最小宽度 "
                                f"{configured_min[0]}（缩到最小尺寸会裁切内容）")
                        if (configured_min[1] > 0
                                and hint.height() > configured_min[1] + tolerance):
                            result.fail(
                                f"{type(widget).__name__}.minimumSizeHint().height()="
                                f"{hint.height()} 大于配置的最小高度 "
                                f"{configured_min[1]}（缩到最小尺寸会裁切内容）")

                # UIHarness 官方检查（隐藏窗口下为空，仍按要求断言）
                for problem in harness.bounds_problems(widget):
                    result.fail(f"[{width}x{height}] {problem}")
                # 补充：隐藏窗口下 isVisibleTo() 版检查（真正有意义的几何体检）
                for problem in hidden_bounds_problems(widget, tolerance=tolerance):
                    result.fail(f"[{width}x{height}] {problem}")
                if len(result.sizes) == 1:
                    result.note(
                        f"几何体检覆盖 {len(_inspectable_children(widget))} 个"
                        f"可见子控件（isVisibleTo 扫描）")

        except Exception as exc:
            result.fail(f"巡检过程异常: {type(exc).__name__}: {exc}")
            result.traceback_text += traceback.format_exc()
        finally:
            try:
                (spec.teardown or _default_teardown)(widget)
            except Exception as exc:
                result.fail(f"关闭/清理失败: {type(exc).__name__}: {exc}")
                result.traceback_text += traceback.format_exc()
            try:
                widget.deleteLater()
                harness.app.processEvents()
            except Exception:
                pass

    result.captured_output = captured.getvalue()
    return result


# ---------------------------------------------------------------------------
# 静态检查：业务代码里不允许再出现 setStyleSheet
# ---------------------------------------------------------------------------

def scan_setstylesheet(scan_root: Path | None = None) -> tuple[list[tuple[str, int, str]], dict[str, int]]:
    """扫描产品代码里的 ``setStyleSheet`` 调用。

    返回 ``(违规列表, 每个文件的违规数)``；违规项为
    ``(相对路径, 行号, 该行源码)``。``ui/theme.py`` 的全局 QSS 安装被允许。
    """
    scan_root = scan_root or (ROOT / "colorPickerPro")
    violations: list[tuple[str, int, str]] = []
    counts: dict[str, int] = {}
    for path in sorted(scan_root.rglob("*.py")):
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        if relative in QSS_ALLOWED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # 纯注释行
            if _SET_STYLESHEET_CALL.search(line):
                violations.append((relative, lineno, stripped[:120]))
                counts[relative] = counts.get(relative, 0) + 1
    return violations, counts


# ---------------------------------------------------------------------------
# 静态检查：UI 文案里不允许残留 emoji（设计系统只使用单色图标字符）
# ---------------------------------------------------------------------------

# 设计系统文档里明确允许的图标/排版字符：✕ ─ ▶ ⏸ ⚙ 以及箭头、标点。
_EMOJI_ALLOWED_CODEPOINTS = {
    0x2713, 0x2715, 0x2716,            # ✓ ✕ ✖（图标 / 状态）
    0x2699, 0x23F8,                    # ⚙ ⏸（图标按钮）
    0x25B6, 0x25B2, 0x25BC,            # ▶ ▲ ▼（图标按钮）
    0x2192, 0x2194, 0x2195, 0x21BB,    # → ↔ ↕ ↻
    0x2500, 0x00D7,                    # ─ ×
    0x2013, 0x2014, 0x2026,            # – — …（排版符号）
}


def _is_emoji_codepoint(codepoint: int) -> bool:
    """判断一个码点是否属于「emoji / 彩色象形符号」范围。"""
    if 0x1F000 <= codepoint <= 0x1FAFF:     # Emoticons / Pictographs / Symbols
        return True
    if 0x1F1E6 <= codepoint <= 0x1F1FF:     # Regional indicator（旗帜）
        return True
    if codepoint in (0xFE0F, 0x200D):       # emoji 变体选择符 / 零宽连接符
        return True
    if 0x2B00 <= codepoint <= 0x2BFF:       # 补充箭头 / 星形（常作 emoji）
        return codepoint not in _EMOJI_ALLOWED_CODEPOINTS
    if 0x2700 <= codepoint <= 0x27BF:       # Dingbats（✨✅✂🗑…）
        return codepoint not in _EMOJI_ALLOWED_CODEPOINTS
    if 0x2600 <= codepoint <= 0x26FF:       # Misc symbols（⚙ 除外）
        return codepoint not in _EMOJI_ALLOWED_CODEPOINTS
    return False


def scan_emoji(scan_root: Path | None = None) -> tuple[list[tuple[str, int, str, str]], dict[str, int]]:
    """扫描产品代码 UI 文案中的 emoji 字符。

    返回 ``(违规列表, 每个文件的违规数)``；违规项为
    ``(相对路径, 行号, 字符, 该行源码)``。注释和 docstring 里的箭头/标点允许，
    但任何 emoji 码点都算违规（设计系统使用单色符号方向键，不使用彩色 emoji）。
    """
    scan_root = scan_root or (ROOT / "colorPickerPro")
    violations: list[tuple[str, int, str, str]] = []
    counts: dict[str, int] = {}
    for path in sorted(scan_root.rglob("*.py")):
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            found = [ch for ch in line if _is_emoji_codepoint(ord(ch))]
            if not found:
                continue
            for ch in found:
                violations.append((relative, lineno, ch, line.strip()[:120]))
                counts[relative] = counts.get(relative, 0) + 1
    return violations, counts


# ---------------------------------------------------------------------------
# Phase 2 静态检查：UI 文案禁用图标字符 / SVG 图标资源 / QSS 位图引用
# ---------------------------------------------------------------------------

def _py_files(scan_root: Path | None) -> list[tuple[Path, str]]:
    scan_root = scan_root or (ROOT / "colorPickerPro")
    files: list[tuple[Path, str]] = []
    for path in sorted(scan_root.rglob("*.py")):
        try:
            relative = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        files.append((path, relative))
    return files


def _load_ast(path: Path) -> tuple[ast.AST | None, str, str]:
    """返回 ``(tree, source, error)``；产品代码重构中的语法错误会作为 error 上报。"""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "", f"读取失败: {exc}"
    try:
        return ast.parse(source, filename=str(path)), source, ""
    except SyntaxError as exc:
        return None, source, f"语法错误: {exc.msg} (line {exc.lineno})"


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """收集模块/类/函数 docstring 的 Constant 节点 id（它们不算 UI 文案）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def scan_ui_glyphs(scan_root: Path | None = None) -> tuple[list[str], dict[str, int]]:
    """扫描 UI 字符串字面量里的禁用图标字符与以 ``"+ "`` 开头的文案。

    只检查非 docstring 的字符串字面量（注释本来就不在 AST 里）；docstring 中的
    箭头/图示允许保留。返回 ``(违规描述列表, 每文件违规数)``。
    """
    violations: list[str] = []
    counts: dict[str, int] = {}
    for path, relative in _py_files(scan_root):
        tree, source, error = _load_ast(path)
        if tree is None:
            violations.append(f"{relative}:0: {error}")
            counts[relative] = counts.get(relative, 0) + 1
            continue
        lines = source.splitlines()
        docstrings = _docstring_constant_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            if id(node) in docstrings:
                continue
            value = node.value
            line = node.lineno or 0
            snippet = (lines[line - 1].strip()[:120]
                       if 0 < line <= len(lines) else "")
            for char in FORBIDDEN_UI_GLYPHS:
                if char in value:
                    violations.append(
                        f"{relative}:{line}: UI 文案含禁用图标字符 "
                        f"{char!r}（U+{ord(char):04X}）| {snippet}")
                    counts[relative] = counts.get(relative, 0) + 1
            if value.lstrip().startswith("+ "):
                violations.append(
                    f"{relative}:{line}: 文案以 '+ ' 开头（应改用 add 图标）"
                    f" | {snippet}")
                counts[relative] = counts.get(relative, 0) + 1
    return violations, counts


_ICON_NAME_CALLS = {"IconButton"}                  # 第一个参数就是图标名
_ICON_KW_CALLS = {"BaseButton", "SecondaryButton", "PrimaryButton",
                  "DangerButton", "GhostButton", "MenuButton", "IconButton"}
_ICON_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _string_constants(node: ast.AST) -> list[ast.Constant]:
    return [sub for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]


def scan_icon_refs(scan_root: Path | None = None) -> tuple[list[str], int]:
    """校验 IconButton("name") / set_icon("name") / icon_name="name" 的 SVG 资源。

    返回 ``(违规描述列表, 图标引用总数)``；同时验证 assets/icons 下每个 SVG
    都能被 XML 解析且根节点是 ``<svg>``。
    """
    violations: list[str] = []
    referenced: dict[str, list[tuple[str, int]]] = {}

    for path, relative in _py_files(scan_root):
        tree, source, error = _load_ast(path)
        if tree is None:
            violations.append(f"{relative}:0: {error}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            expressions: list[ast.AST] = []
            if name in _ICON_NAME_CALLS and node.args:
                expressions.append(node.args[0])
            if name == "set_icon" and node.args:
                expressions.append(node.args[0])
            if name in _ICON_KW_CALLS:
                for keyword in node.keywords:
                    if keyword.arg == "icon_name":
                        expressions.append(keyword.value)
            for expression in expressions:
                for constant in _string_constants(expression):
                    referenced.setdefault(constant.value, []).append(
                        (relative, node.lineno or 0))

    for icon_name, places in sorted(referenced.items()):
        if not _ICON_NAME_RE.fullmatch(icon_name):
            for relative, line in places:
                violations.append(
                    f"{relative}:{line}: 图标名不是合法 SVG 名: {icon_name!r}")
            continue
        icon_file = ICON_DIR / f"{icon_name}.svg"
        if not icon_file.is_file():
            for relative, line in places:
                violations.append(
                    f"{relative}:{line}: 图标资源缺失 "
                    f"colorPickerPro/ui/assets/icons/{icon_name}.svg")
        elif icon_file.stat().st_size < 50:
            violations.append(
                f"colorPickerPro/ui/assets/icons/{icon_name}.svg: "
                f"文件过小（{icon_file.stat().st_size} B），疑似空图标")

    for icon_file in sorted(ICON_DIR.glob("*.svg")):
        try:
            root = ET.parse(icon_file).getroot()
        except (ET.ParseError, OSError) as exc:
            violations.append(
                f"colorPickerPro/ui/assets/icons/{icon_file.name}: "
                f"SVG 解析失败: {exc}")
            continue
        tag = root.tag.split("}")[-1].lower() if isinstance(root.tag, str) else ""
        if tag != "svg":
            violations.append(
                f"colorPickerPro/ui/assets/icons/{icon_file.name}: "
                f"根节点不是 <svg>（{root.tag!r}）")
    return violations, len(referenced)


def scan_qss_assets() -> tuple[list[str], int]:
    """解析 build_stylesheet() 生成的全部 ``url(...)``，验证资源存在且没有 PNG。"""
    from colorPickerPro.ui.stylesheet import build_stylesheet

    qss = build_stylesheet()
    references = re.findall(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", qss)
    violations: list[str] = []
    checked = 0
    seen: set[str] = set()
    for _quote, reference in references:
        reference = reference.strip()
        if not reference or reference in seen:
            continue
        seen.add(reference)
        if reference.startswith((":/", "data:")):
            continue
        checked += 1
        path = Path(reference)
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
            violations.append(f"QSS 仍引用位图资源: {reference}")
        if not path.is_file():
            violations.append(f"QSS url() 资源不存在: {reference}")
    if ".png" in qss:
        violations.append("QSS 文本中仍出现 .png 引用")
    return violations, checked


# ---------------------------------------------------------------------------
# 报告格式化小工具
# ---------------------------------------------------------------------------

def rel(path: Path | str) -> str:
    """转成相对仓库根的 POSIX 路径（报告里短一些）。"""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def format_size_changes(result: SurfaceResult) -> str:
    parts: list[str] = []
    for (width, height), (actual_w, actual_h) in result.sizes:
        if (width, height) == (actual_w, actual_h):
            parts.append(f"{width}x{height}")
        else:
            parts.append(f"{width}x{height}→{actual_w}x{actual_h}")
    return " ".join(parts)


__all__ = [
    "ROOT",
    "SHOTS_DIR",
    "ICON_DIR",
    "FORBIDDEN_UI_GLYPHS",
    "SurfaceSpec",
    "SurfaceResult",
    "run_surface",
    "hidden_bounds_problems",
    "frameless_problems",
    "scan_setstylesheet",
    "scan_emoji",
    "scan_ui_glyphs",
    "scan_icon_refs",
    "scan_qss_assets",
    "rel",
    "format_size_changes",
]
