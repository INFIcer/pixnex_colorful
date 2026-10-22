"""列表查看器：多项内容的「重叠对比 / 横向对比」容器。

布局说明（本次重构重点）：
    * 横向模式不再手算 ``setGeometry``：``_HorizontalContainer`` 用一个
      ``QHBoxLayout`` 排列 :class:`ListItemWidget`，每项的最小宽度 = 视口宽度
      平分（``viewport / n``），窗口缩放时由布局自动重排，同时保持各项等宽；
    * 重叠模式继续用 ``QStackedWidget``，顶部导航按钮负责悬停预览 / 单击切换；
    * 导航按钮的选中态由动态属性 ``variant`` + ``theme.repolish`` 驱动，不再
      给单个控件写样式表；
    * 每个列表项都是 ``Card`` 组合出来的：标题 ``ElidedLabel`` + 删除
      ``IconButton`` 的标题行，正文放调用方传入的内容控件。
"""

from enum import Enum
from typing import Optional

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .ui.components import (
    Card, Divider, ElidedLabel, GhostButton, IconButton, SecondaryButton,
    ScrollArea, flow, hbox,
)
from .ui.theme import set_variant
from .ui.tokens import SPACE, Role, Variant

# Qt 的超大尺寸上限（等价 QWIDGETSIZE_MAX），用于取消最大宽度限制。
_UNLIMITED = 16777215


class _NavButton(GhostButton):
    """导航按钮：鼠标进入时把序号发出去（悬停预览用）。"""

    hovered = Signal(int)

    def __init__(self, text: str, index: int, parent=None):
        super().__init__(text, parent)
        self._nav_index = index

    def enterEvent(self, event):
        self.hovered.emit(self._nav_index)
        super().enterEvent(event)


class ListItemWidget(Card):
    """一个列表项：标题行（可省略标题 + 删除按钮）+ 内容控件。"""

    deleteRequested = Signal()

    def __init__(self, content_widget: QWidget, title: str = "", parent=None):
        super().__init__("", parent, padding=SPACE.sm, spacing=SPACE.xs)
        self._content_widget = content_widget
        content_widget.setParent(self)

        self._title_label = ElidedLabel(title, role=Role.SECTION)
        self._delete_btn = IconButton("close", tooltip="移除", danger=True)
        self._delete_btn.clicked.connect(self.deleteRequested)
        self.add_layout(hbox(self._title_label, self._delete_btn,
                             spacing=SPACE.xs))
        self.add(content_widget, 1)

        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                           QSizePolicy.Policy.MinimumExpanding)
        self.setMinimumHeight(80)

    @property
    def content_widget(self) -> QWidget:
        return self._content_widget

    @property
    def title(self) -> str:
        return self._title_label.full_text()

    @title.setter
    def title(self, text: str):
        self._title_label.setText(text)


class _HorizontalContainer(QWidget):
    """横向对比容器：等宽排列列表项，宽度由 :class:`ListViewer` 统一下发。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.xs)
        self.row.setSpacing(SPACE.sm)


class ListViewer(QWidget):
    """多个内容控件的对比容器（重叠 / 横向两种视图模式）。"""

    class ViewMode(Enum):
        HORIZONTAL = "horizontal"
        OVERLAP = "overlap"

    itemSwitching = Signal(ListItemWidget)
    itemSwitched = Signal(ListItemWidget)
    itemRemove = Signal(ListItemWidget)
    rebuilding = Signal()
    rebuilded = Signal()
    viewModeChanging = Signal(object)
    viewModeChanged = Signal(object)
    closed = Signal()

    def __init__(self, items: Optional[list] = None,
                 view_mode: ViewMode = ViewMode.OVERLAP, parent=None,
                 item_width_fn=None):
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._item_widgets: list[ListItemWidget] = []
        self._view_mode = view_mode
        self._active_index = 0 if items else -1
        self._hover_index = -1
        self._nav_buttons: list[_NavButton] = []
        # 兼容旧调用：横向模式改由布局等分宽度，这个回调不再参与排版。
        self._item_width_fn = item_width_fn
        self._updating_widths = False

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)
        self.closed.connect(self._on_close)

        self._build_ui()

        if items:
            for w in items:
                self._add_item_internal(w)
            self._rebuild_current_view()
            self._rebuild_nav_buttons()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        actions = QWidget()
        actions_layout = hbox(
            spacing=SPACE.sm,
            margins=(SPACE.sm, SPACE.xs, SPACE.sm, SPACE.xs))
        self._btn_add = SecondaryButton("添加", icon_name="add",
                                        tooltip="添加对比项")
        self._btn_add.clicked.connect(self._on_add_clicked)
        actions_layout.addWidget(self._btn_add)

        self._btn_toggle = GhostButton(
            "重叠对比" if self._view_mode == ListViewer.ViewMode.HORIZONTAL
            else "横向对比")
        self._btn_toggle.clicked.connect(self._toggle_view_mode)
        actions_layout.addWidget(self._btn_toggle)
        actions_layout.addStretch(1)
        actions.setLayout(actions_layout)
        main_layout.addWidget(actions)

        # 导航按钮单独一行：项目多时自动换行，不会把工具栏挤出窗口。
        self._nav_container = QWidget()
        self._nav_layout = flow(
            spacing=SPACE.xs,
            margins=(SPACE.sm, 0, SPACE.sm, SPACE.xs),
            parent=self._nav_container)
        self._nav_container.setVisible(
            self._view_mode == ListViewer.ViewMode.OVERLAP)
        self._nav_container.installEventFilter(self)
        main_layout.addWidget(self._nav_container)

        main_layout.addWidget(Divider())

        self._mode_stack = QStackedWidget()

        self._h_container = _HorizontalContainer()
        self._h_container.installEventFilter(self)
        self._h_scroll = ScrollArea(self._h_container, horizontal=True)
        self._mode_stack.addWidget(self._h_scroll)

        self._overlap_stack = QStackedWidget()
        self._mode_stack.addWidget(self._overlap_stack)

        self._mode_stack.setCurrentIndex(
            0 if self._view_mode == ListViewer.ViewMode.HORIZONTAL else 1
        )
        main_layout.addWidget(self._mode_stack, 1)

    def _add_item_internal(self, content_widget: QWidget):
        title = (content_widget.windowTitle() or content_widget.objectName()
                 or "")
        liw = ListItemWidget(content_widget, title)
        liw.deleteRequested.connect(
            lambda liw=liw: self._on_item_delete_requested(liw)
        )
        self._items.append(content_widget)
        self._item_widgets.append(liw)
        return liw

    # ------------------------------------------------------------------
    # 增删
    # ------------------------------------------------------------------
    def _on_close(self):
        print('close')
        for liw in self._item_widgets:
            self.itemRemove.emit(liw)

    def _on_item_delete_requested(self, liw: ListItemWidget):
        try:
            self.itemRemove.emit(liw)
            index = self._item_widgets.index(liw)
            self.remove_item(index)
        except ValueError:
            pass

    def _on_add_clicked(self):
        pass

    def add_item(self, content_widget: QWidget):
        liw = self._add_item_internal(content_widget)
        if self._active_index == -1:
            self._active_index = 0
        self._rebuild_current_view()
        self._rebuild_nav_buttons()
        if self._view_mode == ListViewer.ViewMode.OVERLAP and self._active_index >= 0:
            self._overlap_stack.setCurrentIndex(self._active_index)
        return liw

    def remove_item(self, index: int):
        n = len(self._items)
        if n == 0 or index < 0 or index >= n:
            return
        print('开始移除')
        itemChange = (self._view_mode == ListViewer.ViewMode.OVERLAP
                      and index == self._active_index)
        if itemChange:
            self.itemSwitching.emit(self._current_item_widget())
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

        if itemChange:
            self.itemSwitched.emit(self._current_item_widget())
        print('完成移除')
        if len(self._items) == 0:
            self.closed.emit()

    def remove_current_item(self):
        if self._active_index >= 0:
            self.remove_item(self._active_index)

    # ------------------------------------------------------------------
    # 视图重建
    # ------------------------------------------------------------------
    def _rebuild_current_view(self):
        self.rebuilding.emit()
        if self._view_mode == ListViewer.ViewMode.HORIZONTAL:
            self._rebuild_horizontal_view()
        else:
            self._rebuild_overlap_view()
        self.rebuilded.emit()

    def _clear_horizontal_row(self) -> None:
        while self._h_container.row.count():
            item = self._h_container.row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget not in self._item_widgets:
                widget.hide()

    def _rebuild_horizontal_view(self):
        self._clear_horizontal_row()
        if not self._item_widgets:
            return
        for liw in self._item_widgets:
            self._h_container.row.addWidget(liw, 1)
            liw.show()
        self._update_horizontal_widths()

    def _rebuild_overlap_view(self):
        self._clear_horizontal_row()
        while self._overlap_stack.count():
            w = self._overlap_stack.widget(0)
            self._overlap_stack.removeWidget(w)
        for liw in self._item_widgets:
            self._overlap_stack.addWidget(liw)

        if self._active_index >= 0 and self._overlap_stack.count() > 0:
            self._overlap_stack.setCurrentIndex(
                min(self._active_index, self._overlap_stack.count() - 1)
            )

    def _update_horizontal_widths(self):
        """每项最小宽度 = 视口宽度平分，保证各视图等宽且不横向溢出。"""
        if self._updating_widths:
            return
        self._updating_widths = True
        try:
            count = len(self._item_widgets)
            scroll = getattr(self, "_h_scroll", None)
            if (count == 0 or scroll is None
                    or self._view_mode != ListViewer.ViewMode.HORIZONTAL):
                for liw in self._item_widgets:
                    liw.setMinimumWidth(0)
                    liw.setMaximumWidth(_UNLIMITED)
                return
            viewport = scroll.viewport()
            margins = self._h_container.row.contentsMargins()
            spacing = self._h_container.row.spacing() * (count - 1)
            available = (viewport.width() - margins.left() - margins.right()
                         - spacing)
            share = max(0, available // count)
            for liw in self._item_widgets:
                liw.setMinimumWidth(share)
                liw.setMaximumWidth(_UNLIMITED)
        finally:
            self._updating_widths = False

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def _rebuild_nav_buttons(self):
        while self._nav_layout.count():
            item = self._nav_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._nav_buttons.clear()

        for i, liw in enumerate(self._item_widgets):
            title = liw.title or f"项 {i + 1}"
            btn = _NavButton(title, i, self._nav_container)
            btn.clicked.connect(
                lambda checked=False, idx=i: self._on_nav_button_clicked(idx)
            )
            btn.hovered.connect(self._on_nav_button_hovered)
            self._nav_buttons.append(btn)
            self._nav_layout.addWidget(btn)

        self._nav_container.setVisible(
            self._view_mode == ListViewer.ViewMode.OVERLAP)
        self._update_nav_button_styles()

    def _update_nav_button_styles(self):
        for i, btn in enumerate(self._nav_buttons):
            set_variant(btn, Variant.PRIMARY if i == self._active_index
                        else Variant.GHOST)

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
            self._perform_item_switch(old_liw, idx)

    def _on_nav_hover_leave(self):
        self._hover_index = -1
        self._hover_timer.stop()

        if (self._view_mode == ListViewer.ViewMode.OVERLAP
                and self._active_index >= 0):
            cur = self._overlap_stack.currentIndex()
            if (cur != self._active_index
                    and self._active_index < self._overlap_stack.count()):
                old_liw = self._item_widgets[cur] if cur < len(self._items) else None
                self._perform_item_switch(old_liw, self._active_index)

    def eventFilter(self, obj, event):
        # 注意：导航容器的过滤器在 _h_container 创建之前就装好了，构造期间也可能
        # 收到事件，所以这里必须容忍属性还没就绪。
        if obj is self._nav_container and event.type() == QEvent.Type.Leave:
            self._on_nav_hover_leave()
            return False
        if (getattr(self, "_h_container", None) is obj
                and event.type() == QEvent.Type.Resize
                and self._view_mode == ListViewer.ViewMode.HORIZONTAL):
            self._update_horizontal_widths()
        return super().eventFilter(obj, event)

    def _perform_item_switch(self, old_liw: Optional[ListItemWidget],
                             new_index: int):
        if old_liw is not None:
            self.itemSwitching.emit(old_liw)
        if self._view_mode == ListViewer.ViewMode.OVERLAP:
            self._overlap_stack.setCurrentIndex(new_index)
        if 0 <= new_index < len(self._item_widgets):
            self.itemSwitched.emit(self._item_widgets[new_index])

    def _switch_to_item(self, index: int):
        if index < 0 or index >= len(self._items) or index == self._active_index:
            return
        old_liw = self._current_item_widget()
        self._active_index = index
        self._perform_item_switch(old_liw, index)
        self._update_nav_button_styles()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def _current_widget(self):
        if 0 <= self._active_index < len(self._items):
            return self._items[self._active_index]
        return None

    def _current_item_widget(self):
        if 0 <= self._active_index < len(self._item_widgets):
            return self._item_widgets[self._active_index]
        return None

    @property
    def items(self) -> list:
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
        self._nav_container.setVisible(
            mode == ListViewer.ViewMode.OVERLAP)
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


def run_demo():
    import sys

    from PySide6.QtWidgets import QApplication

    from .ui.components import SubtitleLabel, TitleLabel
    from .ui.theme import ensure_theme

    app = QApplication.instance() or QApplication(sys.argv)
    ensure_theme(app)

    items = []
    for i in range(3):
        w = QWidget()
        w.setObjectName(f"内容项 {i + 1}")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        layout.addWidget(TitleLabel(f"内容项 {i + 1}"))
        layout.addWidget(SubtitleLabel("用布局排版的示例内容。"))
        layout.addStretch(1)
        items.append(w)

    viewer = ListViewer(items, view_mode=ListViewer.ViewMode.OVERLAP)
    viewer.setWindowTitle("列表查看器演示")
    viewer.resize(600, 400)

    def on_switched(old_liw, new_liw):
        old_name = old_liw.title if old_liw else "None"
        new_name = new_liw.title if new_liw else "None"
        print(f"切换: {old_name} -> {new_name}")

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
        layout.setContentsMargins(SPACE.sm, SPACE.sm, SPACE.sm, SPACE.sm)
        layout.addWidget(TitleLabel(f"新内容项 {i}"))
        layout.addWidget(SubtitleLabel("用布局排版的示例内容。"))
        layout.addStretch(1)
        viewer.add_item(w)

    viewer._btn_add.clicked.connect(make_item)

    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
