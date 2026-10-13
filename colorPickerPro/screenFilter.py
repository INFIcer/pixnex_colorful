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
"""

import sys
import time
import ctypes
import hashlib
import numpy as np
import mss
from typing import List

from PySide6.QtGui import QColor, QAction, QClipboard
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QPushButton,
    QVBoxLayout, QGroupBox, QMessageBox, QDialog, QMenu, QFileDialog,
)
if __name__ == "__main__" and (__package__ is None or __package__ == ''):
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.filter_lib import ImageFilter, ImageConvert
    from colorPickerPro.customFrame import CustomFramelessWindow, PixmapWidget
    from colorPickerPro.filter_scheme import FilterScheme, to_scheme
    from colorPickerPro.filter_scheme_panel import FilterParamsWidget, FilterSchemePanel
    from colorPickerPro.filter_scheme_selector import FilterSchemeSelectorWidget
else:
    from .filter_lib import ImageFilter, ImageConvert
    from .customFrame import CustomFramelessWindow, PixmapWidget
    from .filter_scheme import FilterScheme, to_scheme
    from .filter_scheme_panel import FilterParamsWidget, FilterSchemePanel
    from .filter_scheme_selector import FilterSchemeSelectorWidget


# ============================================================
# 第一部分：屏幕滤镜窗口（核心）
# ============================================================

class _FilterParamsPanel(QDialog):
    """滤镜参数调节面板（弹出式，保留给单个滤镜参数使用）。

    参数控件本身由 FilterParamsWidget 提供，这里只负责弹窗外壳；
    滤镜方案的管理界面请用 FilterSchemePanel。
    """

    def __init__(self, params, on_changed, parent=None):
        super().__init__(parent)
        self._on_changed = on_changed

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("""
            _FilterParamsPanel { background-color: #2a2a2a; border: 1px solid #555; }
            QLabel#paramTitle { font-weight: bold; font-size: 13px; color: #ddd; }
            QLabel#paramName { color: #bbb; font-size: 12px; }
            QDoubleSpinBox { background: #3a3a3a; color: white; border: 1px solid #555;
                             border-radius: 3px; padding: 2px 4px; font-size: 11px; }
            QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; }
            QSlider::handle:horizontal { background: #999; width: 14px; margin: -5px 0;
                                         border-radius: 7px; }
            QSlider::handle:horizontal:hover { background: #bbb; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._params_widget = FilterParamsWidget(params, on_changed,
                                                 title="参数调节", parent=self)
        layout.addWidget(self._params_widget)

        self.setFixedWidth(360)

    def closeEvent(self, event):
        # 解绑参数与控件，避免控件销毁后参数仍持有失效引用
        self._params_widget.detach_params()
        super().closeEvent(event)


class ScreenFilterWindow(CustomFramelessWindow):
    """
    屏幕滤镜窗口

    特性：
    - 无边框置顶，始终显示滤镜方案处理后的画面
    - 标题栏拖动，边缘/角缩放
    - 暂停/继续捕获按钮（暂停时画面冻结，禁止缩放）
    - 可见的 2px 蓝色边框
    - 「⚙」打开滤镜方案管理面板（图层化增删/排序滤镜并编辑参数）
    """

    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    def __init__(self, scheme):
        """scheme 可以是 FilterScheme、ImageFilter 实例或 ImageFilter 子类。"""
        scheme = to_scheme(scheme)
        super().__init__(scheme.display_name())
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._capturing = True
        self._border_color_active = self._border_color
        self._border_color_paused = QColor(0, 60, 120)
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
        self._btn_pause = QPushButton("\u23f8")
        self._btn_pause.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._btn_pause.setStyleSheet(self._btn_style("#555"))
        self._btn_pause.setToolTip("暂停捕获")
        self.add_title_bar_button(self._btn_pause)
        self._btn_pause.clicked.connect(self._toggle_capture)

        self._btn_params = QPushButton("\u2699")
        self._btn_params.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self._btn_params.setStyleSheet(self._btn_style("#555"))
        self._btn_params.setToolTip("滤镜方案（图层管理 / 参数）")
        self.add_title_bar_button(self._btn_params)
        self._btn_params.clicked.connect(self._toggle_scheme_panel)

        self.set_content_widget(PixmapWidget())

    def _toggle_capture(self):
        self._capturing = not self._capturing
        if self._capturing:
            self._btn_pause.setText("\u23f8")
            self._btn_pause.setToolTip("暂停捕获")
            self._timer.start()
            self._frozen_raw = None
            self._raw_hash = None
            self._resize_active = False
            self._resize_edge = 0
            self.set_border_color(self._border_color_active)
        else:
            self._btn_pause.setText("\u25b6")
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

    def _tick(self):
        if not self.isVisible() or self._collapsed:
            return

        if self._capturing:
            try:
                geo = self.geometry()
                screen = QApplication.screenAt(geo.center())
                if not screen:
                    return
                sg = screen.geometry()
                dpr = screen.devicePixelRatio()
                screens = QApplication.screens()
                idx = screens.index(screen)
                mon = self._sct.monitors[idx + 1]
                cx = int((geo.x() - sg.x() + 4) * dpr)
                cy = int((geo.y() - sg.y() + 36) * dpr)
                cw = max(1, int((geo.width() - 8) * dpr))
                ch = max(1, int((geo.height() - 40) * dpr))
                sct_img = self._sct.grab({
                    "left": mon["left"] + cx, "top": mon["top"] + cy,
                    "width": cw, "height": ch,
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
        path, _ = QFileDialog.getSaveFileName(
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
        if self._scheme_panel is not None:
            self._scheme_panel.close()
            self._scheme_panel = None
        super().closeEvent(e)


# ============================================================
# 第二部分：演示 GUI
# ============================================================

class ScreenFilterDemo(QMainWindow):
    """屏幕滤镜演示程序"""

    def __init__(self):
        super().__init__()
        self._windows: List[ScreenFilterWindow] = []
        self._manager = None
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("屏幕滤镜演示")
        self.setMinimumSize(420, 520)
        self.resize(420, 560)

        c = QWidget()
        self.setCentralWidget(c)
        lo = QVBoxLayout(c)
        lo.setSpacing(12)

        t = QLabel("\U0001f5bc 屏幕滤镜系统")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:20px;font-weight:bold;padding:12px 0 4px 0;")
        lo.addWidget(t)

        d = QLabel("选择滤镜或已保存方案 \u2192 点击「创建屏幕滤镜」生成置顶滤镜窗口")
        d.setAlignment(Qt.AlignCenter)
        d.setStyleSheet("color:#888;font-size:12px;padding-bottom:8px;")
        d.setWordWrap(True)
        lo.addWidget(d)

        g = QGroupBox("滤镜库 / 已保存方案")
        g.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        gl = QVBoxLayout(g)

        self._selector = FilterSchemeSelectorWidget()
        self._selector.schemesChanged.connect(self._on_schemes_changed)
        gl.addWidget(self._selector)
        lo.addWidget(g, 1)

        b = QPushButton("✨ 创建屏幕滤镜")
        b.clicked.connect(self._on_create)
        b.setStyleSheet("QPushButton{background:#4CAF50;color:white;padding:10px;"
                        "font-size:15px;border:none;border-radius:6px;font-weight:bold;}"
                        "QPushButton:hover{background:#43A047;}"
                        "QPushButton:pressed{background:#388E3C;}")
        lo.addWidget(b)

        b2 = QPushButton("\U0001f5d1 关闭所有")
        b2.clicked.connect(self._on_close_all)
        b2.setStyleSheet("QPushButton{background:#E53935;color:white;padding:8px;"
                         "font-size:13px;border:none;border-radius:6px;}"
                         "QPushButton:hover{background:#D32F2F;}"
                         "QPushButton:pressed{background:#C62828;}")
        lo.addWidget(b2)

        b3 = QPushButton("\U0001f9e9 方案管理（新建 / 编辑 / 保存方案）")
        b3.clicked.connect(self._on_manage_scheme)
        b3.setStyleSheet("QPushButton{background:#5C6BC0;color:white;padding:8px;"
                         "font-size:13px;border:none;border-radius:6px;}"
                         "QPushButton:hover{background:#3F51B5;}"
                         "QPushButton:pressed{background:#303F9F;}")
        lo.addWidget(b3)

        self._status = QLabel("就绪")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#999;font-size:12px;padding:4px;")
        lo.addWidget(self._status)

    def _on_schemes_changed(self):
        self._selector.refresh()
        self._status.setText("方案列表已更新")

    def _on_manage_scheme(self):
        """打开方案管理面板：从当前选择开始，或继续编辑已有的未保存方案。"""
        if self._manager is not None and self._manager.is_dirty():
            # 面板里还有没保存的改动：直接复用，别把工作丢掉
            self._manager.show()
            self._manager.raise_()
            self._status.setText("方案管理面板已打开（有未保存修改）")
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
        self._status.setText("方案管理面板已打开")

    def _on_create(self):
        scheme = self._selector.current_scheme()
        if scheme is None:
            QMessageBox.warning(self, "提示", "请选择一个滤镜或已保存方案")
            return

        win = ScreenFilterWindow(scheme)
        self._windows.append(win)
        off = 30 * (len(self._windows) % 6)
        win.move(80 + off, 80 + off)
        win.start()
        win.destroyed.connect(lambda: self._on_closed(win))
        self._status.setText(f"\u2705 创建: {scheme.display_name()}")

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
    app = QApplication.instance() or QApplication(sys.argv)
    demo = ScreenFilterDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
