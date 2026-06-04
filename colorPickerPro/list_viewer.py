from enum import Enum
from typing import Optional

from PySide6.QtCore import Qt, QEvent, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QSizePolicy, QStackedWidget,
)


class _NavButton(QPushButton):
    hovered = Signal(int)

    def __init__(self, text: str, index: int, parent=None):
        super().__init__(text, parent)
        self._nav_index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)

    def enterEvent(self, event):
        self.hovered.emit(self._nav_index)
        super().enterEvent(event)


class ListItemWidget(QWidget):
    deleteRequested = Signal()

    def __init__(self, content_widget: QWidget, title: str = "", parent=None):
        super().__init__(parent)
        self._content_widget = content_widget
        content_widget.setParent(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            "color: #ddd; font-size: 12px; font-weight: bold; background: transparent;"
        )
        top_row.addWidget(self._title_label)
        top_row.addStretch()

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #E53935; color: white;
                border: none; border-radius: 3px; font-size: 12px;
            }
            QPushButton:hover { background-color: #C62828; }
        """)
        self._delete_btn.setCursor(Qt.PointingHandCursor)
        self._delete_btn.clicked.connect(self.deleteRequested)
        top_row.addWidget(self._delete_btn)

        layout.addLayout(top_row)
        layout.addWidget(content_widget, 1)

        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.setMinimumSize(120, 80)
        self.setStyleSheet(
            "ListItemWidget { background-color: #2a2a2a; border-radius: 4px; }"
        )

    @property
    def content_widget(self) -> QWidget:
        return self._content_widget

    @property
    def title(self) -> str:
        return self._title_label.text()

    @title.setter
    def title(self, text: str):
        self._title_label.setText(text)


class ListViewer(QWidget):

    class ViewMode(Enum):
        HORIZONTAL = "horizontal"
        OVERLAP = "overlap"

    itemSwitching = Signal(ListItemWidget)
    itemSwitched = Signal(ListItemWidget)
    viewModeChanging = Signal(object)
    viewModeChanged = Signal(object)
    closed = Signal()

    def __init__(self, items: Optional[list[QWidget]] = None,
                 view_mode: ViewMode = ViewMode.OVERLAP, parent=None,
                 item_width_fn=None):
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._item_widgets: list[ListItemWidget] = []
        self._view_mode = view_mode
        self._active_index = 0 if items else -1
        self._hover_index = -1
        self._nav_buttons: list[_NavButton] = []
        self._item_width_fn = item_width_fn

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

        self._build_ui()

        if items:
            for w in items:
                self._add_item_internal(w)
            self._rebuild_current_view()
            self._rebuild_nav_buttons()

    def _build_ui(self):
        self.setStyleSheet("ListViewer { background-color: #1e1e1e; }")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        tb = QWidget()
        tb.setStyleSheet("background-color: #2a2a2a;")
        t_layout = QHBoxLayout(tb)
        t_layout.setContentsMargins(8, 4, 8, 4)
        t_layout.setSpacing(6)

        self._btn_add = QPushButton("+ 添加")
        self._btn_add.setStyleSheet(self._btn_style("#26A69A"))
        self._btn_add.setCursor(Qt.PointingHandCursor)
        self._btn_add.clicked.connect(self._on_add_clicked)
        t_layout.addWidget(self._btn_add)

        self._btn_toggle = QPushButton(
            "重叠对比" if self._view_mode == ListViewer.ViewMode.HORIZONTAL
            else "横向对比"
        )
        self._btn_toggle.setStyleSheet(self._btn_style("#5C6BC0"))
        self._btn_toggle.setCursor(Qt.PointingHandCursor)
        self._btn_toggle.clicked.connect(self._toggle_view_mode)
        t_layout.addWidget(self._btn_toggle)

        t_layout.addStretch()

        self._nav_container = QWidget()
        self._nav_container.setStyleSheet("background: transparent;")
        self._nav_layout = QHBoxLayout(self._nav_container)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(4)
        self._nav_container.setVisible(self._view_mode == ListViewer.ViewMode.OVERLAP)
        self._nav_container.installEventFilter(self)
        t_layout.addWidget(self._nav_container)

        main_layout.addWidget(tb)

        self._mode_stack = QStackedWidget()

        self._h_scroll = QScrollArea()
        self._h_scroll.setWidgetResizable(True)
        self._h_scroll.setFrameShape(QScrollArea.NoFrame)
        self._h_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:horizontal {
                background: #1a1a1a; height: 8px; border-radius: 4px;
            }
            QScrollBar::handle:horizontal {
                background: #444; border-radius: 4px; min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover { background: #555; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)
        self._h_scroll.installEventFilter(self)
        self._h_container = QWidget()
        self._h_container.setStyleSheet("background: transparent;")
        self._h_scroll.setWidget(self._h_container)
        self._mode_stack.addWidget(self._h_scroll)
        self._H_MARGIN_LR = 8
        self._H_MARGIN_TB = 4
        self._H_SPACING = 8

        self._overlap_stack = QStackedWidget()
        self._overlap_stack.setStyleSheet("background: transparent;")
        self._mode_stack.addWidget(self._overlap_stack)

        self._mode_stack.setCurrentIndex(
            0 if self._view_mode == ListViewer.ViewMode.HORIZONTAL else 1
        )
        main_layout.addWidget(self._mode_stack, 1)

    def _add_item_internal(self, content_widget: QWidget):
        title = content_widget.windowTitle() or content_widget.objectName() or ""
        liw = ListItemWidget(content_widget, title)
        liw.deleteRequested.connect(
            lambda liw=liw: self._on_item_delete_requested(liw)
        )
        self._items.append(content_widget)
        self._item_widgets.append(liw)

    def _on_item_delete_requested(self, liw: ListItemWidget):
        try:
            index = self._item_widgets.index(liw)
            self.remove_item(index)
        except ValueError:
            pass

    def _on_add_clicked(self):
        pass

    def add_item(self, content_widget: QWidget):
        self._add_item_internal(content_widget)
        if self._active_index == -1:
            self._active_index = 0
        self._rebuild_current_view()
        self._rebuild_nav_buttons()
        if self._view_mode == ListViewer.ViewMode.OVERLAP and self._active_index >= 0:
            self._overlap_stack.setCurrentIndex(self._active_index)

    def remove_item(self, index: int):
        n = len(self._items)
        if n == 0 or index < 0 or index >= n:
            return
        self.itemSwitching.emit(self._current_item_widget())
        
        if self._view_mode == ListViewer.ViewMode.OVERLAP and index == self._active_index:
            if n == 1:
                self._active_index = -1
            elif index == n - 1:
                new_idx = index - 1
                self._active_index = new_idx
                self._update_nav_button_styles()
            else:
                self._active_index = index
                self._update_nav_button_styles()
        else:
            if self._active_index > index:
                self._active_index -= 1
            elif self._active_index == index and n > 1:
                if index == n - 1:
                    self._active_index = index - 1

        liw = self._item_widgets.pop(index)
        self._items.pop(index)
        liw.deleteLater()

        if self._active_index >= len(self._items):
            self._active_index = len(self._items) - 1

        self._rebuild_current_view()
        self._rebuild_nav_buttons()

        if self._active_index >= 0 and self._view_mode == ListViewer.ViewMode.OVERLAP:
            if self._overlap_stack.count() > 0:
                self._overlap_stack.setCurrentIndex(
                    min(self._active_index, self._overlap_stack.count() - 1)
                )

        self.itemSwitched.emit(self._current_item_widget())

        if len(self._items) == 0:
            self.closed.emit()

    def remove_current_item(self):
        if self._active_index >= 0:
            self.remove_item(self._active_index)

    def _rebuild_current_view(self):
        if self._view_mode == ListViewer.ViewMode.HORIZONTAL:
            self._rebuild_horizontal_view()
        else:
            self._rebuild_overlap_view()

    def _rebuild_horizontal_view(self):
        self._h_container.setMinimumSize(0, 0)

        if not self._item_widgets:
            return

        vp = self._h_scroll.viewport()
        vp_h = vp.height() if vp else 100

        x = self._H_MARGIN_LR
        item_h = vp_h - self._H_MARGIN_TB * 2

        for liw in self._item_widgets:
            liw.setParent(self._h_container)
            if self._item_width_fn is not None:
                w = self._item_width_fn(liw, item_h)
            else:
                sh = liw.sizeHint()
                w = sh.width()
            liw.setGeometry(x, self._H_MARGIN_TB, w, item_h)
            liw.show()
            x += w + self._H_SPACING

        total_w = x - self._H_SPACING + self._H_MARGIN_LR
        self._h_container.setMinimumSize(total_w, vp_h)

    def _rebuild_overlap_view(self):
        while self._overlap_stack.count():
            w = self._overlap_stack.widget(0)
            self._overlap_stack.removeWidget(w)

        for liw in self._item_widgets:
            liw.setParent(self._overlap_stack)
            self._overlap_stack.addWidget(liw)

        if self._active_index >= 0 and self._overlap_stack.count() > 0:
            self._overlap_stack.setCurrentIndex(
                min(self._active_index, self._overlap_stack.count() - 1)
            )

    def _rebuild_nav_buttons(self):
        for btn in self._nav_buttons:
            btn.deleteLater()
        self._nav_buttons.clear()

        for i in reversed(range(self._nav_layout.count())):
            item = self._nav_layout.takeAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        for i, liw in enumerate(self._item_widgets):
            title = liw.title or f"项 {i + 1}"
            btn = _NavButton(title, i, self._nav_container)
            btn.clicked.connect(
                lambda checked=False, idx=i: self._on_nav_button_clicked(idx)
            )
            btn.hovered.connect(self._on_nav_button_hovered)
            self._nav_buttons.append(btn)
            self._nav_layout.addWidget(btn)

        self._nav_layout.addStretch()
        self._update_nav_button_styles()

    def _update_nav_button_styles(self):
        for i, btn in enumerate(self._nav_buttons):
            if i == self._active_index:
                btn.setStyleSheet(self._btn_style_active())
            else:
                btn.setStyleSheet(self._btn_style_inactive())

    def _on_nav_button_clicked(self, index: int):
        if index != self._active_index:
            self._switch_to_item(index)

    def _on_nav_button_hovered(self, index: int):
        self._hover_index = index
        self._hover_timer.stop()
        self._hover_timer.start(80)

    def _on_hover_timeout(self):
        if self._hover_index < 0 or self._hover_index >= len(self._items):
            return
        idx = self._hover_index
        if self._view_mode == ListViewer.ViewMode.OVERLAP:
            cur = self._overlap_stack.currentIndex()
            if cur == idx:
                return
            old_liw = self._item_widgets[cur] if cur < len(self._items) else None
            new_liw = self._item_widgets[idx]
            if old_liw is not None:
                self.itemSwitching.emit(old_liw)
            self._overlap_stack.setCurrentIndex(idx)
            self.itemSwitched.emit(new_liw)

    def _on_nav_hover_leave(self):
        self._hover_index = -1
        self._hover_timer.stop()

        if self._view_mode == ListViewer.ViewMode.OVERLAP and self._active_index >= 0:
            cur = self._overlap_stack.currentIndex()
            if cur != self._active_index and self._active_index < self._overlap_stack.count():
                old_liw = self._item_widgets[cur] if cur < len(self._items) else None
                new_liw = self._item_widgets[self._active_index]
                if old_liw is not None:
                    self.itemSwitching.emit(old_liw)
                self._overlap_stack.setCurrentIndex(self._active_index)
                self.itemSwitched.emit(new_liw)

    def eventFilter(self, obj, event):
        if obj == self._nav_container and event.type() == QEvent.Leave:
            self._on_nav_hover_leave()
            return False
        if (hasattr(self, '_h_scroll') and obj == self._h_scroll
                and event.type() == QEvent.Resize
                and self._view_mode == ListViewer.ViewMode.HORIZONTAL
                and self._item_widgets):
            vp = self._h_scroll.viewport()
            if vp:
                item_h = vp.height() - self._H_MARGIN_TB * 2
                x = self._H_MARGIN_LR
                for liw in self._item_widgets:
                    if self._item_width_fn is not None:
                        w = self._item_width_fn(liw, item_h)
                    else:
                        w = liw.width()
                    liw.setGeometry(x, self._H_MARGIN_TB, w, item_h)
                    x += w + self._H_SPACING
        return super().eventFilter(obj, event)

    def _switch_to_item(self, index: int):
        if index < 0 or index >= len(self._items) or index == self._active_index:
            return
        old_liw = self._current_item_widget()
        self.itemSwitching.emit(old_liw)
        new_liw = self._item_widgets[index]
        self._active_index = index
        if self._view_mode == ListViewer.ViewMode.OVERLAP:
            self._overlap_stack.setCurrentIndex(index)
        self._update_nav_button_styles()
        self.itemSwitched.emit(new_liw)

    def _current_widget(self):
        if 0 <= self._active_index < len(self._items):
            return self._items[self._active_index]
        return None

    def _current_item_widget(self):
        if 0 <= self._active_index < len(self._item_widgets):
            return self._item_widgets[self._active_index]
        return None

    @property
    def items(self) -> list[QWidget]:
        return list(self._items)

    @property
    def current_item(self):
        return self._current_item_widget()

    @property
    def current_index(self) -> int:
        return self._active_index

    @property
    def view_mode(self) -> ViewMode:
        return self._view_mode

    def set_view_mode(self, mode: ViewMode):
        if mode == self._view_mode:
            return
        self.viewModeChanging.emit(mode)
        self._view_mode = mode
        self._btn_toggle.setText(
            "横向对比" if mode == ListViewer.ViewMode.HORIZONTAL
            else "重叠对比"
        )
        self._nav_container.setVisible(mode == ListViewer.ViewMode.OVERLAP)
        self._mode_stack.setCurrentIndex(
            0 if mode == ListViewer.ViewMode.HORIZONTAL else 1
        )
        self._rebuild_current_view()
        self._rebuild_nav_buttons()
        self.viewModeChanged.emit(mode)

    def _toggle_view_mode(self):
        self.set_view_mode(
            ListViewer.ViewMode.HORIZONTAL
            if self._view_mode == ListViewer.ViewMode.OVERLAP
            else ListViewer.ViewMode.OVERLAP
        )

    @staticmethod
    def _btn_style(color: str) -> str:
        return f"""
            QPushButton {{ padding: 4px 12px; font-size: 11px;
                background-color: {color}; color: white;
                border: none; border-radius: 3px; }}
            QPushButton:hover {{ background-color: {color}; }}
        """

    @staticmethod
    def _btn_style_active() -> str:
        return """
            QPushButton { padding: 4px 12px; font-size: 11px;
                background-color: #26A69A; color: white;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #00897B; }
        """

    @staticmethod
    def _btn_style_inactive() -> str:
        return """
            QPushButton { padding: 4px 12px; font-size: 11px;
                background-color: #3a3a3a; color: #aaa;
                border: none; border-radius: 3px; }
            QPushButton:hover { background-color: #555; color: white; }
        """


def run_demo():
    import sys
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    items = []
    for i in range(3):
        w = QWidget()
        w.setObjectName(f"内容项 {i + 1}")
        layout = QVBoxLayout(w)
        label = QLabel(f"内容项 {i + 1}")
        label.setStyleSheet(
            "color: white; font-size: 24px; font-weight: bold;"
        )
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        w.setStyleSheet("background-color: #333; border-radius: 8px;")
        items.append(w)

    viewer = ListViewer(items, view_mode=ListViewer.ViewMode.OVERLAP)
    viewer.setWindowTitle("列表查看器演示")
    viewer.resize(600, 400)

    def on_switched(old_liw, new_liw):
        old_name = old_liw.title if old_liw else "None"
        new_name = new_liw.title if new_liw else "None"
        print(f"切换: {old_name} → {new_name}")

    def on_closed():
        print("所有项已删除，关闭查看器")
        viewer.close()

    def on_mode_changed(mode):
        print(f"模式切换: {mode.value}")

    viewer.itemSwitched.connect(on_switched)
    viewer.viewModeChanged.connect(on_mode_changed)
    viewer.closed.connect(on_closed)

    counter = [3]

    def make_item():
        counter[0] += 1
        i = counter[0]
        w = QWidget()
        w.setObjectName(f"新内容项 {i}")
        layout = QVBoxLayout(w)
        label = QLabel(f"新内容项 {i}")
        label.setStyleSheet(
            "color: white; font-size: 24px; font-weight: bold;"
        )
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        w.setStyleSheet("background-color: #444; border-radius: 8px;")
        viewer.add_item(w)

    viewer._btn_add.clicked.connect(make_item)

    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
