"""
屏幕滤镜程序 - Screen Filter
===========================
功能：
1. 屏幕滤镜窗口：无边框可移动缩放的置顶窗口，实时捕获下层画面
2. 零闪烁：利用 Windows WDA_EXCLUDEFROMCAPTURE 透明排除 + mss DXGI 捕获
3. 封装库接口与 PySide6 演示 GUI

滤镜库定义见 filter_lib.py；滤镜方案（滤镜的图层化堆叠）定义见 filter_scheme.py。
屏幕滤镜窗口承载的是一个「滤镜方案」而不是单个滤镜：创建滤镜即创建一个只含
该滤镜的方案，后续可以在方案管理面板里继续叠加、删除、排序滤镜。

界面部分全部由 ``colorPickerPro.ui`` 设计系统组合：标题栏按钮是 ``IconButton``，
边框颜色取自设计令牌（捕获中=强调色，暂停=弱化色），演示窗口用卡片 / 标题 /
状态标签拼装。捕获区域由 ``CustomFramelessWindow.content_rect_global()`` 得出，
不再手算标题栏与边框的偏移。
"""

import sys
import time
import ctypes
import hashlib
from typing import List

import numpy as np
import mss

from PySide6.QtGui import QAction, QCursor
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QMenu,
)
if __name__ == "__main__" and (__package__ is None or __package__ == ''):
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.auto_collapse import (
        AUTO_COLLAPSE_POLL_MS, CollapseDelay, modal_or_popup_open,
        mouse_button_pressed,
    )
    from colorPickerPro.filter_lib import ImageFilter, ImageConvert
    from colorPickerPro.customFrame import CustomFramelessWindow, PixmapWidget
    from colorPickerPro.filter_scheme import FilterScheme, to_scheme
    from colorPickerPro.filter_scheme_panel import FilterParamsWidget, FilterSchemePanel
    from colorPickerPro.filter_scheme_selector import FilterSchemeSelectorWidget
    from colorPickerPro.ui import apply_theme, configure_application
    from colorPickerPro.ui.components import (
        Card, DangerButton, FlowLayout, FramelessWindowMixin, IconButton,
        PrimaryButton, SecondaryButton, StatusLabel, SubtitleLabel,
        ThemedDialog, TitleLabel, alert, get_save_file_name, vbox,
    )
    from colorPickerPro.ui.tokens import SPACE, State, qcolor
else:
    from .auto_collapse import (
        AUTO_COLLAPSE_POLL_MS, CollapseDelay, modal_or_popup_open,
        mouse_button_pressed,
    )
    from .filter_lib import ImageFilter, ImageConvert
    from .customFrame import CustomFramelessWindow, PixmapWidget
    from .filter_scheme import FilterScheme, to_scheme
    from .filter_scheme_panel import FilterParamsWidget, FilterSchemePanel
    from .filter_scheme_selector import FilterSchemeSelectorWidget
    from .ui import apply_theme, configure_application
    from .ui.components import (
        Card, DangerButton, FlowLayout, FramelessWindowMixin, IconButton,
        PrimaryButton, SecondaryButton, StatusLabel, SubtitleLabel,
        ThemedDialog, TitleLabel, alert, get_save_file_name, vbox,
    )
    from .ui.tokens import SPACE, State, qcolor


# ============================================================
# 第一部分：屏幕滤镜窗口（核心）
# ============================================================


class _FilterParamsPanel(ThemedDialog):
    """滤镜参数调节面板（弹出式，保留给单个滤镜参数使用）。

    参数控件本身由 FilterParamsWidget 提供，这里只负责弹窗外壳；
    滤镜方案的管理界面请用 FilterSchemePanel。
    """

    def __init__(self, params, on_changed, parent=None):
        super().__init__("参数调节", "", parent)
        # 保留原先“点窗口外自动关闭”的弹出行为；窗口外壳仍是自绘样式
        self.setWindowFlag(Qt.Popup, True)
        self._on_changed = on_changed

        self._params_widget = FilterParamsWidget(params, on_changed,
                                                 title="", parent=self)
        # 参数多时放进滚动 body：弹窗高度不会长到超出屏幕
        content = self.make_body_scrollable()
        content.addWidget(self._params_widget)

        # 宽度按内容决定（有上下限），不再写死 360
        self.setMinimumWidth(260)
        self.setMaximumWidth(560)
        hint = self._params_widget.sizeHint()
        self.resize(min(560, max(300, hint.width() + 2 * SPACE.lg)),
                    min(560, max(240, hint.height() + 120)))

    def closeEvent(self, event):
        # 解绑参数与控件，避免控件销毁后参数仍持有失效引用
        self._params_widget.detach_params()
        super().closeEvent(event)


class ScreenFilterWindow(CustomFramelessWindow):
    """
    屏幕滤镜窗口

    特性：
    - 无边框置顶，始终显示滤镜方案处理后的画面
    - 标题栏拖动，边缘/角缩放（交给窗口系统处理）
    - 自动折叠按钮：鼠标离开窗口自动收起为标题栏，移入标题栏展开；
      双击标题栏 / 空格键手动折叠或展开时同时关闭自动折叠
    - 图像区域左键单击 / 按住拖动连续取色：发出 ``colorPicked(r, g, b)``，
      标题栏按当前颜色模型短暂显示提示（如 ``L-0.61 C-0.25 H-321.7``）
    - 暂停/继续捕获按钮（暂停时画面冻结，禁止缩放）
    - 可见的边框：捕获中为强调色，暂停时变暗
    - 设置按钮打开滤镜方案管理面板（图层化增删/排序滤镜并编辑参数）
    """

    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    # 图像区域左键取色（sRGB 0-255）。
    colorPicked = Signal(int, int, int)

    def __init__(self, scheme):
        """scheme 可以是 FilterScheme、ImageFilter 实例或 ImageFilter 子类。"""
        scheme = to_scheme(scheme)
        super().__init__(scheme.display_name())
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._capturing = True
        # 边框颜色取自设计令牌：捕获中=强调色，暂停=弱化色
        self._border_color_active = qcolor("accent")
        self._border_color_paused = qcolor("text_faint")
        self._scheme = scheme
        self._sct = mss.mss()
        self._scheme_panel = None
        self._last_process_time = 0.0
        self._frozen_raw = None
        self._raw_hash = None
        self._affinity_set = False

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._reprocess)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setTimerType(Qt.PreciseTimer)

        # 自动折叠：鼠标离开窗口 → 收起为标题栏，移入标题栏 → 展开。
        self._auto_collapse_enabled = False
        self._btn_auto_collapse: IconButton | None = None
        self._auto_collapse_timer = QTimer(self)
        self._auto_collapse_timer.setInterval(AUTO_COLLAPSE_POLL_MS)
        self._auto_collapse_timer.timeout.connect(self._on_auto_collapse_tick)
        # 鼠标离开后等待约 1 秒才折叠；期间回到窗口则取消等待（展开不延迟）。
        self._collapse_delay = CollapseDelay()

        # 左键取色的反馈：标题栏副标题短暂显示颜色提示，随后自动清除。
        self._pick_hint_timer = QTimer(self)
        self._pick_hint_timer.setSingleShot(True)
        self._pick_hint_timer.timeout.connect(self._clear_pick_hint)
        # 按住左键拖动连续取色时的状态 / 更新节流（秒）与提示格式化回调。
        self._picking = False
        self._last_pick_at = 0.0
        self._continuous_pick_interval = 0.03
        self._color_formatter = None

        self._build_filter_ui()

    def _setup_affinity(self):
        if self._affinity_set:
            return
        try:
            hwnd = int(self.winId())
            if ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, self.WDA_EXCLUDEFROMCAPTURE):
                self._affinity_set = True
        except Exception:
            pass

    def _build_filter_ui(self):
        # 标题栏按钮：自动折叠 / 暂停捕获 / 滤镜方案。
        self._btn_auto_collapse = IconButton(
            "collapse", tooltip="鼠标离开后折叠为标题栏", checkable=True)
        self._btn_auto_collapse.toggled.connect(self._on_auto_collapse_toggled)
        self.add_title_bar_button(self._btn_auto_collapse)

        self._btn_pause = IconButton("pause", tooltip="暂停捕获")
        self._btn_pause.clicked.connect(self._toggle_capture)
        self.add_title_bar_button(self._btn_pause)

        self._btn_params = IconButton("settings", tooltip="滤镜方案")
        self._btn_params.clicked.connect(self._toggle_scheme_panel)
        self.add_title_bar_button(self._btn_params)

        self.set_content_widget(PixmapWidget())

    # ------------------------------------------------------------------
    # 自动折叠
    # ------------------------------------------------------------------
    def toggle_collapse(self):
        """手动折叠 / 展开（双击标题栏、空格键）：同时关闭自动折叠。"""
        self._disable_auto_collapse_silently()
        super().toggle_collapse()

    def _on_auto_collapse_toggled(self, enabled: bool):
        self._auto_collapse_enabled = bool(enabled)
        self._collapse_delay.reset()
        self._sync_auto_collapse_timer()
        if not self._auto_collapse_enabled and self._collapsed:
            super().toggle_collapse()   # 关掉开关立即展开，不能留在折叠状态

    def _disable_auto_collapse_silently(self):
        """手动折叠 / 展开时关闭自动折叠。

        必须先关掉开关再执行手动动作；这里不触发"关闭开关就展开"的逻辑，
        否则手动"展开"会先被它展开、再被 ``super().toggle_collapse()`` 收起。
        """
        if not self._auto_collapse_enabled:
            return
        self._auto_collapse_enabled = False
        self._collapse_delay.reset()
        self._sync_auto_collapse_timer()
        button = self._btn_auto_collapse
        if button is not None:
            button.blockSignals(True)
            try:
                button.setChecked(False)
            finally:
                button.blockSignals(False)

    def _sync_auto_collapse_timer(self):
        running = self._auto_collapse_enabled and self.isVisible()
        if running and not self._auto_collapse_timer.isActive():
            self._auto_collapse_timer.start()
        elif not running and self._auto_collapse_timer.isActive():
            self._auto_collapse_timer.stop()

    def _on_auto_collapse_tick(self):
        self._auto_collapse_step(QCursor.pos())

    def _auto_collapse_step(self, cursor_pos: QPoint,
                            now: float | None = None):
        """按光标位置折叠 / 展开：折叠有约 1 秒离开延迟，展开立即执行。

        ``cursor_pos`` / ``now`` 显式传入便于测试（``now`` 为
        ``time.monotonic()`` 秒数）。
        """
        if not self._auto_collapse_enabled or not self.isVisible():
            self._collapse_delay.reset()
            return
        if self.isMinimized() or self.isMaximized():
            self._collapse_delay.reset()
            return
        if mouse_button_pressed() or modal_or_popup_open():
            self._collapse_delay.reset()   # 正在交互：重新计时
            return
        if self._scheme_panel is not None and self._scheme_panel.isVisible():
            self._collapse_delay.reset()   # 正在编辑方案：面板在窗口外不算离开
            return
        inside = self.geometry().contains(cursor_pos)
        if self._collapsed:
            self._collapse_delay.reset()
            if inside:
                super().toggle_collapse()  # 展开不延迟
            return
        if self._collapse_delay.should_collapse(inside, now):
            super().toggle_collapse()

    # ---- 窗口显示 / 隐藏 -------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._collapse_delay.reset()
        self._sync_auto_collapse_timer()

    def hideEvent(self, event):
        self._auto_collapse_timer.stop()
        self._collapse_delay.reset()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # 图像区域左键取色（单击 / 按住拖动连续取色）
    # ------------------------------------------------------------------
    def set_color_formatter(self, formatter):
        """设置取色提示的格式化回调 ``formatter(r, g, b) -> str``。

        主窗口会传入「当前颜色模型」的格式化方法（如 ``L-0.61 C-0.25 H-321.7``）；
        未设置时退回显示 HEX。回调在每次取色时调用，切换颜色模型后立即生效。
        """
        self._color_formatter = formatter

    def mousePressEvent(self, event):
        # 内容控件 PixmapWidget 不消费鼠标事件，点击会冒泡到窗口；标题栏按钮
        # 自己 accept，不会走到这里。
        if event.button() == Qt.MouseButton.LeftButton:
            self._picking = True
            self._last_pick_at = 0.0
            self._pick_color_from_image(
                event.globalPosition().toPoint(), force=True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 按住左键拖动：光标扫过的每个位置都取色（节流见 _pick_color_from_image）。
        if self._picking and event.buttons() & Qt.MouseButton.LeftButton:
            self._pick_color_from_image(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._picking = False
        super().mouseReleaseEvent(event)

    def _pick_color_from_image(self, global_pos: QPoint,
                               *, force: bool = False) -> bool:
        """取该处「显示图像」的颜色并发出 ``colorPicked``。

        返回是否落在图像上（留白 / 无图像时为 False）。
        """
        color = self._color_at(global_pos)
        if color is None:
            return False
        now = time.perf_counter()
        if not force and now - self._last_pick_at < self._continuous_pick_interval:
            return True                 # 拖动时节流，避免高频刷颜色同步
        self._last_pick_at = now
        self.colorPicked.emit(color.red(), color.green(), color.blue())
        self._show_pick_hint(color)
        return True

    def _color_at(self, global_pos: QPoint):
        """把全局坐标映射到显示图像像素，返回 ``QColor``；不在图像上返回 None。

        显示区保持等比缩放并居中（见 ``PixmapWidget.paintEvent``），这里用同一
        套换算把点击位置映射回 pixmap 像素；点在留白区域则忽略。
        """
        pixmap = self._content.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        local = self._content.mapFromGlobal(global_pos)
        inner = self._content.rect()
        if not inner.contains(local):
            return None
        scaled = pixmap.scaled(
            inner.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if scaled.isNull():
            return None
        left = (inner.width() - scaled.width()) // 2
        top = (inner.height() - scaled.height()) // 2
        if not (left <= local.x() < left + scaled.width()
                and top <= local.y() < top + scaled.height()):
            return None                 # 点在等比缩放后的留白区域

        image = pixmap.toImage()
        px = int((local.x() - left) * image.width() / scaled.width())
        py = int((local.y() - top) * image.height() / scaled.height())
        px = max(0, min(image.width() - 1, px))
        py = max(0, min(image.height() - 1, py))
        return image.pixelColor(px, py)

    def _show_pick_hint(self, color):
        self.set_subtitle(self._pick_hint_text(color))
        self._pick_hint_timer.start(1600)

    def _pick_hint_text(self, color) -> str:
        """取色提示文案：优先用当前颜色模型的样式（如 L-0.61 C-0.25 H-321.7）。"""
        if self._color_formatter is not None:
            try:
                text = self._color_formatter(
                    color.red(), color.green(), color.blue())
            except Exception:
                text = ""
            if text:
                return text
        return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"

    def _clear_pick_hint(self):
        self.set_subtitle("")

    def _toggle_capture(self):
        self._capturing = not self._capturing
        if self._capturing:
            self._btn_pause.set_icon("pause")
            self._btn_pause.setToolTip("暂停捕获")
            self._timer.start()
            self._frozen_raw = None
            self._raw_hash = None
            self.set_border_color(self._border_color_active)
        else:
            self._btn_pause.set_icon("play")
            self._btn_pause.setToolTip("继续捕获")
            self._timer.stop()
            self._tick()
            self.set_border_color(self._border_color_paused)

    def _toggle_scheme_panel(self):
        if self._scheme_panel is not None and self._scheme_panel.isVisible():
            self._scheme_panel.hide()
            self._flush_pending_process()
            return
        if self._scheme_panel is None:
            self._scheme_panel = FilterSchemePanel(self._scheme, parent=self)
            self._scheme_panel.schemeChanged.connect(self._request_debounce_process)
            self._scheme_panel.schemeReplaced.connect(self._on_scheme_replaced)
            self._scheme_panel.schemesChanged.connect(self._refresh_title)
        else:
            # 复用同一个面板：方案对象没换就不要重绑（否则会清掉未保存标记）
            self._scheme_panel.sync_scheme(self._scheme)
        btn_pos = self._btn_params.mapToGlobal(QPoint(0, self._btn_params.height()))
        self._scheme_panel.move(btn_pos)
        self._scheme_panel.show()
        self._scheme_panel.raise_()
        self._scheme_panel.activateWindow()

    def _on_scheme_replaced(self, scheme):
        """面板换掉了方案对象（加载方案），窗口必须改用新对象渲染。"""
        self._scheme = to_scheme(scheme)
        self._refresh_title()
        self._raw_hash = None
        self._request_debounce_process()

    def _refresh_title(self):
        self.set_title(self._scheme.display_name())

    def set_scheme(self, scheme):
        """替换当前滤镜方案（接受 FilterScheme / ImageFilter 实例 / 滤镜类）。"""
        self._scheme = to_scheme(scheme)
        if self._scheme_panel is not None:
            self._scheme_panel.sync_scheme(self._scheme)
        self._refresh_title()
        self._raw_hash = None
        self._request_debounce_process()

    def set_filter(self, fi):
        """兼容旧接口：等价于 set_scheme。"""
        self.set_scheme(fi)

    def _should_allow_resize(self) -> bool:
        return self._capturing

    @property
    def current_scheme(self) -> FilterScheme:
        return self._scheme

    @property
    def current_filter(self):
        """兼容旧接口：返回方案第一层的滤镜（方案为空时返回 None）。"""
        if self._scheme.layers:
            return self._scheme.layers[0].filter
        return None

    def _request_debounce_process(self):
        self._debounce_timer.start(80)

    def _flush_pending_process(self):
        """把还在防抖等待中的改动立刻渲染，避免关掉面板就丢掉最后一次修改。"""
        if self._debounce_timer.isActive():
            self._reprocess()

    def _reprocess(self):
        self._debounce_timer.stop()
        if self._frozen_raw is None or not self.isVisible() or self._collapsed:
            return
        print(f"[ScreenFilter] params changed, reprocessing")
        try:
            t0 = time.perf_counter()
            result = self._scheme.process(self._frozen_raw)
            elapsed = (time.perf_counter() - t0) * 1000
            self._content.setPixmap(ImageConvert.numpy_to_pixmap(result))
        except Exception as ex:
            print(f"[ScreenFilter] {ex}")

    def _capture_region(self):
        """内容区在屏幕上的像素区域（已裁剪到所在屏幕内）。

        返回 (left, top, width, height)，都相对于 mss 的虚拟桌面；
        内容区完全在屏幕外时返回 None。
        """
        content = self.content_rect_global()
        screen = QApplication.screenAt(content.center())
        if screen is None:
            return None
        sg = screen.geometry()
        visible = content.intersected(sg)
        if visible.isEmpty():
            return None
        screens = QApplication.screens()
        index = screens.index(screen)
        monitors = self._sct.monitors
        monitor = monitors[index + 1] if index + 1 < len(monitors) else monitors[0]
        dpr = screen.devicePixelRatio()
        return (
            monitor["left"] + int((visible.x() - sg.x()) * dpr),
            monitor["top"] + int((visible.y() - sg.y()) * dpr),
            max(1, int(visible.width() * dpr)),
            max(1, int(visible.height() * dpr)),
        )

    def _tick(self):
        if not self.isVisible() or self._collapsed:
            return

        if self._capturing:
            try:
                region = self._capture_region()
                if region is None:
                    return
                left, top, width, height = region
                sct_img = self._sct.grab({
                    "left": left, "top": top, "width": width, "height": height,
                })
                raw = np.array(sct_img, dtype=np.uint8)
                frozen_raw = raw[:, :, :3].copy()
            except Exception as ex:
                print(f"[ScreenFilter] {ex}")
                return

            new_hash = hashlib.sha256(frozen_raw).digest()
            if new_hash == self._raw_hash:
                return
            self._frozen_raw = frozen_raw
            self._raw_hash = new_hash
            print(f"[ScreenFilter] frame changed, reprocessing ({frozen_raw.shape})")
        elif self._frozen_raw is None:
            return

        try:
            t0 = time.perf_counter()
            result = self._scheme.process(self._frozen_raw)
            elapsed = (time.perf_counter() - t0) * 1000
            self._content.setPixmap(ImageConvert.numpy_to_pixmap(result))
        except Exception as ex:
            print(f"[ScreenFilter] {ex}")
            return

        self._last_process_time = self._last_process_time * 0.7 + elapsed * 0.3
        interval = max(16, min(250, int(self._last_process_time * 3)))
        self._timer.setInterval(interval)

    def start(self):
        self._capturing = True
        self._last_process_time = 0.0
        self._timer.start(16)
        self.show()
        self.raise_()
        QApplication.processEvents()
        self._setup_affinity()

    def stop(self):
        self._timer.stop()
        self.hide()

    def contextMenuEvent(self, event):
        pm = self._content.pixmap()
        if pm is None or pm.isNull():
            return
        menu = QMenu(self)
        act_save = QAction("保存图像", self)
        act_save.triggered.connect(self._save_image)
        menu.addAction(act_save)
        act_copy = QAction("复制图像", self)
        act_copy.triggered.connect(self._copy_image)
        menu.addAction(act_copy)
        menu.exec(event.globalPos())

    def _save_image(self):
        pm = self._content.pixmap()
        if pm is None or pm.isNull():
            return
        # 无边框文件选择对话框（与主界面同款自绘外壳）
        path, _ = get_save_file_name(
            self, "保存图像", "",
            "PNG 图像 (*.png);;JPEG 图像 (*.jpg *.jpeg);;BMP 图像 (*.bmp)"
        )
        if path:
            pm.save(path)

    def _copy_image(self):
        pm = self._content.pixmap()
        if pm is None or pm.isNull():
            return
        QApplication.clipboard().setPixmap(pm)

    def closeEvent(self, e):
        self._timer.stop()
        self._auto_collapse_timer.stop()
        if self._scheme_panel is not None:
            self._scheme_panel.close()
            self._scheme_panel = None
        super().closeEvent(e)


# ============================================================
# 第二部分：演示 GUI
# ============================================================

class ScreenFilterDemo(FramelessWindowMixin, QMainWindow):
    """屏幕滤镜演示程序（无边框 + 自绘标题栏）。"""

    def __init__(self):
        super().__init__()
        self._windows: List[ScreenFilterWindow] = []
        self._manager = None
        self._build_ui()

    def _build_ui(self):
        self.setMinimumSize(420, 520)
        self.resize(440, 620)

        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.init_frameless("屏幕滤镜演示", layout=outer,
                            show_minimize=True, show_maximize=True,
                            show_close=True, resizable=True,
                            double_click="maximize")
        self.setWindowTitle("屏幕滤镜演示")

        body = QWidget()
        body.setObjectName("FramelessBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(SPACE.md, SPACE.md, SPACE.md, SPACE.md)
        layout.setSpacing(SPACE.md)
        outer.addWidget(body, 1)

        # 标题 + 说明
        layout.addLayout(vbox(
            TitleLabel("屏幕滤镜"),
            SubtitleLabel("选择滤镜或方案，创建置顶窗口"),
            spacing=SPACE.xxs))

        # 滤镜库 / 已保存方案
        selector_card = Card("滤镜库 / 已保存方案", padding=SPACE.sm)
        self._selector = FilterSchemeSelectorWidget(parent=selector_card)
        self._selector.schemesChanged.connect(self._on_schemes_changed)
        selector_card.add(self._selector, 1)
        layout.addWidget(selector_card, 1)

        # 操作区：窗口变窄时自动换行
        actions = QWidget(central)
        flow = FlowLayout(actions, margin=0,
                          h_spacing=SPACE.sm, v_spacing=SPACE.sm)
        self._btn_create = PrimaryButton("创建屏幕滤镜", tooltip="以当前选择创建窗口")
        self._btn_create.clicked.connect(self._on_create)
        flow.addWidget(self._btn_create)

        self._btn_manage = SecondaryButton("方案管理", tooltip="编辑并保存方案")
        self._btn_manage.clicked.connect(self._on_manage_scheme)
        flow.addWidget(self._btn_manage)

        self._btn_close_all = DangerButton("关闭所有", tooltip="关闭全部滤镜窗口")
        self._btn_close_all.clicked.connect(self._on_close_all)
        flow.addWidget(self._btn_close_all)
        layout.addWidget(actions)

        self._status = StatusLabel("就绪")
        layout.addWidget(self._status)

    def _on_schemes_changed(self):
        self._selector.refresh()
        self._status.set_message("列表已更新")

    def _on_manage_scheme(self):
        """打开方案管理面板：从当前选择开始，或继续编辑已有的未保存方案。"""
        if self._manager is not None and self._manager.is_dirty():
            # 面板里还有没保存的改动：直接复用，别把工作丢掉
            self._manager.show()
            self._manager.raise_()
            self._status.set_message("面板已打开（有未保存修改）")
            return

        scheme = self._selector.current_scheme()
        scheme = scheme.clone() if scheme is not None else FilterScheme()
        scheme.name = ""
        if self._manager is None:
            self._manager = FilterSchemePanel(scheme)
            self._manager.schemesChanged.connect(self._on_schemes_changed)
            self._manager.move(self.x() + 40, self.y() + 60)
        else:
            self._manager.set_scheme(scheme, notify=False)
        self._manager.show()
        self._manager.raise_()
        self._status.set_message("面板已打开")

    def _on_create(self):
        scheme = self._selector.current_scheme()
        if scheme is None:
            alert(self, "提示", "请选择滤镜或方案")
            return

        win = ScreenFilterWindow(scheme)
        win.colorPicked.connect(self._on_filter_color_picked)
        self._windows.append(win)
        off = 30 * (len(self._windows) % 6)
        win.move(80 + off, 80 + off)
        win.start()
        win.destroyed.connect(lambda: self._on_closed(win))
        self._status.set_message(f"创建：{scheme.display_name()}", State.ACCENT)

    def _on_filter_color_picked(self, r, g, b):
        self._status.set_message(f"取色 #{r:02X}{g:02X}{b:02X}", State.ACCENT)

    def _on_closed(self, win: ScreenFilterWindow):
        if win in self._windows:
            self._windows.remove(win)

    def _on_close_all(self):
        for win in self._windows[:]:
            win.stop()
            win.close()
        self._windows.clear()

    def closeEvent(self, e):
        self._on_close_all()
        if self._manager is not None:
            self._manager.close()
            self._manager = None
        super().closeEvent(e)


# ============================================================
# 第三部分：库接口
# ============================================================

def create_screen_filter(
    filter_or_scheme,
    x: int = 200, y: int = 200,
    width: int = 480, height: int = 360,
) -> ScreenFilterWindow:
    """创建屏幕滤镜窗口。

    filter_or_scheme 可以是 FilterScheme、ImageFilter 实例或 ImageFilter 子类；
    传入滤镜时会自动包装成只含该滤镜的方案。
    """
    if not (isinstance(filter_or_scheme, FilterScheme)
            or isinstance(filter_or_scheme, ImageFilter)
            or (isinstance(filter_or_scheme, type)
                and issubclass(filter_or_scheme, ImageFilter))):
        raise TypeError(f"{filter_or_scheme!r} 必须是 FilterScheme、ImageFilter 实例或子类")
    win = ScreenFilterWindow(filter_or_scheme)
    win.setGeometry(x, y, width, height)
    win.start()
    return win


def run_demo():
    configure_application()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    demo = ScreenFilterDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
