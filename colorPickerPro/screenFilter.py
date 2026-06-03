"""
屏幕滤镜程序 - Screen Filter
===========================
功能：
1. 屏幕滤镜窗口：无边框可移动缩放的置顶窗口，实时捕获下层画面
2. 零闪烁：利用 Windows WDA_EXCLUDEFROMCAPTURE 透明排除 + mss DXGI 捕获
3. 封装库接口与 PySide6 演示 GUI

滤镜库定义见 filter_lib.py
"""

import sys
import time
import ctypes
import hashlib
import numpy as np
import mss
import mss.tools
from typing import List

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QPushButton,
    QVBoxLayout, QListWidget, QListWidgetItem,
    QGroupBox, QMessageBox, QDialog,
)

from .filter_lib import ImageFilter, ImageConvert
from .customFrame import CustomFramelessWindow, PixmapWidget


# ============================================================
# 第一部分：屏幕滤镜窗口（核心）
# ============================================================

class _FilterParamsPanel(QDialog):
    """滤镜参数调节面板（弹出式）"""

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

        title = QLabel("参数调节")
        title.setObjectName("paramTitle")
        layout.addWidget(title)

        for p in params:
            layout.addWidget(p.create_widget(self._on_changed))

        self.setFixedWidth(360)


class ScreenFilterWindow(CustomFramelessWindow):
    """
    屏幕滤镜窗口

    特性：
    - 无边框置顶，始终显示滤镜处理后的画面
    - 标题栏拖动，边缘/角缩放
    - 暂停/继续捕获按钮（暂停时画面冻结，禁止缩放）
    - 可见的 2px 蓝色边框
    """

    WDA_EXCLUDEFROMCAPTURE = 0x00000011

    def __init__(self, filter_instance: ImageFilter):
        super().__init__(filter_instance.name())
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._capturing = True
        self._border_color_active = self._border_color
        self._border_color_paused = QColor(0, 60, 120)
        self._filter = filter_instance
        self._sct = mss.mss()
        self._param_panel = None
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
        self._btn_params.setToolTip("滤镜参数")
        self.add_title_bar_button(self._btn_params)
        self._btn_params.clicked.connect(self._toggle_params_panel)
        has_params = len(self._filter.exposed_parameters()) > 0
        self._btn_params.setVisible(has_params)

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

    def _toggle_params_panel(self):
        if self._param_panel and self._param_panel.isVisible():
            self._param_panel.close()
            self._param_panel = None
            self._debounce_timer.stop()
            return
        params = self._filter.exposed_parameters()
        if not params:
            return
        self._param_panel = _FilterParamsPanel(params, self._request_debounce_process, self)
        btn_pos = self._btn_params.mapToGlobal(QPoint(0, self._btn_params.height()))
        self._param_panel.move(btn_pos)
        self._param_panel.show()

    def set_filter(self, fi: ImageFilter):
        if self._param_panel:
            self._param_panel.close()
            self._param_panel = None
        self._filter = fi
        self.set_title(fi.name())
        self._btn_params.setVisible(len(fi.exposed_parameters()) > 0)
        self._raw_hash = None

    def _should_allow_resize(self) -> bool:
        return self._capturing

    @property
    def current_filter(self) -> ImageFilter:
        return self._filter

    def _request_debounce_process(self):
        self._debounce_timer.start(80)

    def _reprocess(self):
        self._debounce_timer.stop()
        if self._frozen_raw is None or not self.isVisible() or self._collapsed:
            return
        print(f"[ScreenFilter] params changed, reprocessing")
        try:
            t0 = time.perf_counter()
            result = self._filter.process(self._frozen_raw)
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
            result = self._filter.process(self._frozen_raw)
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

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)


# ============================================================
# 第二部分：演示 GUI
# ============================================================

class ScreenFilterDemo(QMainWindow):
    """屏幕滤镜演示程序"""

    def __init__(self):
        super().__init__()
        self._windows: List[ScreenFilterWindow] = []
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

        d = QLabel("选择滤镜 \u2192 点击「创建屏幕滤镜」生成置顶滤镜窗口")
        d.setAlignment(Qt.AlignCenter)
        d.setStyleSheet("color:#888;font-size:12px;padding-bottom:8px;")
        d.setWordWrap(True)
        lo.addWidget(d)

        g = QGroupBox("可用滤镜库")
        g.setStyleSheet("QGroupBox{font-weight:bold;font-size:13px;}")
        gl = QVBoxLayout(g)

        self._list = QListWidget()
        for cls in ImageFilter.all_filters():
            it = QListWidgetItem(f"  {cls.name()}")
            it.setData(Qt.UserRole, cls.__name__)
            self._list.addItem(it)
        if self._list.count():
            self._list.setCurrentRow(0)
        gl.addWidget(self._list)
        lo.addWidget(g)

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

        self._status = QLabel("就绪")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#999;font-size:12px;padding:4px;")
        lo.addWidget(self._status)

    def _sel_cls(self):
        cur = self._list.currentItem()
        if cur is None:
            return None
        n = cur.data(Qt.UserRole)
        for cls in ImageFilter.all_filters():
            if cls.__name__ == n:
                return cls
        return None

    def _on_create(self):
        cls = self._sel_cls()
        if cls is None:
            QMessageBox.warning(self, "提示", "请选择滤镜")
            return

        fi = cls()
        win = ScreenFilterWindow(fi)
        self._windows.append(win)
        off = 30 * (len(self._windows) % 6)
        win.move(80 + off, 80 + off)
        win.start()
        win.destroyed.connect(lambda: self._on_closed(win))
        self._status.setText(f"\u2705 创建: {fi.name()}")

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
        super().closeEvent(e)


# ============================================================
# 第三部分：库接口
# ============================================================

def create_screen_filter(
    filter_cls: type,
    x: int = 200, y: int = 200,
    width: int = 480, height: int = 360,
) -> ScreenFilterWindow:
    if not (isinstance(filter_cls, type) and issubclass(filter_cls, ImageFilter)):
        raise TypeError(f"{filter_cls} 必须是 ImageFilter 子类")
    win = ScreenFilterWindow(filter_cls())
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
