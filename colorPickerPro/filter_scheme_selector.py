"""
滤镜 / 方案选择界面
==================

- FilterSchemeSelectorWidget ：两个列表（滤镜库 + 已保存方案）的选择控件
- FilterSchemeSelectorDialog ：带确定/取消的弹窗版

左侧列出所有可用滤镜，右侧列出已保存的滤镜方案。选中左侧滤镜时，相当于
“用一个只含该滤镜的方案”（替换原先直接创建滤镜的行为）；选中右侧方案时，
直接使用该方案。删除方案的功能放在本列表中。

界面全部由 ``colorPickerPro.ui`` 设计系统组合而成：两列放在 ``QSplitter``
里（各自有最小宽度，窄窗口也能拖动分配），说明文字用 ``CaptionLabel``，
删除 / 刷新用 ``DangerButton`` / ``GhostButton``，弹窗外壳是 ``ThemedDialog``。
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QSplitter,
    QAbstractItemView, QDialog,
)

from .filter_lib import ImageFilter
from .filter_scheme import FilterScheme, get_scheme_store
from .ui.components import (
    CaptionLabel, DangerButton, GhostButton, PrimaryButton, ThemedDialog,
    alert, confirm, hbox, vbox,
)
from .ui.tokens import SPACE

# 两列列表的最小宽度：再窄就放不下滤镜名/方案名，由分栏保证可读性
_LIST_MIN_WIDTH = 176


class FilterSchemeSelectorWidget(QWidget):
    """滤镜库 + 已保存方案，两个列表的选择控件。"""

    selectionChanged = Signal()
    schemesChanged = Signal()
    filterActivated = Signal(object)   # 滤镜类
    schemeActivated = Signal(object)   # FilterScheme

    def __init__(self, multi_select: bool = False, store=None, parent=None):
        super().__init__(parent)
        self._store = store if store is not None else get_scheme_store()
        self._multi = bool(multi_select)
        self._active = "filter"
        self._suspend = False

        self._build_ui()
        self.refresh()

    # ---------- 界面 ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE.xs)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(SPACE.sm)

        # 左：滤镜库
        left_host = QWidget(splitter)
        cap_l = CaptionLabel("滤镜库", word_wrap=True)
        self._filter_list = QListWidget(left_host)
        self._filter_list.setToolTip("选中滤镜即新建该滤镜的方案")
        self._filter_list.setMinimumWidth(_LIST_MIN_WIDTH)
        self._setup_list(self._filter_list)
        left_host.setLayout(vbox(cap_l, self._filter_list, spacing=SPACE.xs,
                                 stretch=1))

        # 右：已保存方案 + 删除 / 刷新
        right_host = QWidget(splitter)
        cap_r = CaptionLabel("已保存方案", word_wrap=True)
        self._scheme_list = QListWidget(right_host)
        self._scheme_list.setMinimumWidth(_LIST_MIN_WIDTH)
        self._setup_list(self._scheme_list)

        self._btn_delete = DangerButton("删除方案", tooltip="删除选中方案")
        self._btn_delete.clicked.connect(self.delete_current_scheme)
        self._btn_refresh = GhostButton("刷新", tooltip="重新读取列表")
        self._btn_refresh.clicked.connect(self.refresh)
        buttons = hbox(self._btn_delete, self._btn_refresh, None, spacing=SPACE.xs)

        right_layout = vbox(cap_r, self._scheme_list, buttons, spacing=SPACE.xs,
                            stretch=1)
        right_host.setLayout(right_layout)

        splitter.addWidget(left_host)
        splitter.addWidget(right_host)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _setup_list(self, widget: QListWidget):
        if self._multi:
            widget.setSelectionMode(QAbstractItemView.MultiSelection)
        else:
            widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.itemClicked.connect(lambda item, w=widget: self._on_item_picked(w))
        widget.currentRowChanged.connect(lambda row, w=widget: self._on_row_changed(row, w))
        widget.itemDoubleClicked.connect(lambda item, w=widget: self._on_double_clicked(w))

    # ---------- 数据 ----------

    def refresh(self):
        """重新读取滤镜库与已保存方案列表。"""
        keep_scheme = self.current_scheme_name()
        keep_filter = self.current_filter_class()

        self._suspend = True
        self._filter_list.clear()
        for cls in ImageFilter.all_filters():
            item = QListWidgetItem(f"  {cls.name()}")
            item.setData(Qt.UserRole, cls)
            self._filter_list.addItem(item)

        self._scheme_list.clear()
        for scheme in self._store.schemes():
            item = QListWidgetItem(f"  {scheme.display_name()}")
            item.setData(Qt.UserRole, scheme.name)
            self._scheme_list.addItem(item)

        if keep_scheme is not None:
            for i in range(self._scheme_list.count()):
                if self._scheme_list.item(i).data(Qt.UserRole) == keep_scheme:
                    self._scheme_list.setCurrentRow(i)
                    break
        elif keep_filter is not None:
            for i in range(self._filter_list.count()):
                if self._filter_list.item(i).data(Qt.UserRole) is keep_filter:
                    self._filter_list.setCurrentRow(i)
                    break
        elif self._filter_list.count():
            self._filter_list.setCurrentRow(0)
        if self._scheme_list.currentItem() is None:
            self._active = "filter"
        self._suspend = False
        self.selectionChanged.emit()

    def store(self):
        return self._store

    def count_schemes(self) -> int:
        return self._scheme_list.count()

    # ---------- 选择 ----------

    def _on_item_picked(self, widget: QListWidget):
        if self._suspend:
            return
        self._active = "filter" if widget is self._filter_list else "scheme"
        if not self._multi:
            other = self._scheme_list if widget is self._filter_list else self._filter_list
            self._suspend = True
            other.clearSelection()
            self._suspend = False
        self.selectionChanged.emit()

    def _on_row_changed(self, row: int, widget: QListWidget):
        if self._suspend or row < 0:
            return
        self._active = "filter" if widget is self._filter_list else "scheme"
        self.selectionChanged.emit()

    def _on_double_clicked(self, widget: QListWidget):
        if widget is self._filter_list:
            cls = self.current_filter_class()
            if cls is not None:
                self.filterActivated.emit(cls)
        else:
            scheme = self.current_scheme()
            if scheme is not None:
                self.schemeActivated.emit(scheme)

    def current_filter_class(self):
        item = self._filter_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def current_scheme_name(self) -> Optional[str]:
        item = self._scheme_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def current_scheme(self) -> Optional[FilterScheme]:
        """当前选择对应的方案（滤镜 → 只含该滤镜的新方案）。"""
        if self._active == "scheme":
            name = self.current_scheme_name()
            stored = self._store.get(name) if name else None
            if stored is not None:
                return stored.clone()
        cls = self.current_filter_class()
        if cls is None and self._active == "filter":
            return None
        if cls is not None:
            return FilterScheme.single(cls)
        name = self.current_scheme_name()
        stored = self._store.get(name) if name else None
        return stored.clone() if stored is not None else None

    def selected_schemes(self) -> List[FilterScheme]:
        """多选模式：返回所有被选中的滤镜/方案。"""
        schemes = []
        if self._multi:
            for item in self._filter_list.selectedItems():
                cls = item.data(Qt.UserRole)
                if cls is not None:
                    schemes.append(FilterScheme.single(cls))
            for item in self._scheme_list.selectedItems():
                stored = self._store.get(item.data(Qt.UserRole))
                if stored is not None:
                    schemes.append(stored.clone())
        else:
            scheme = self.current_scheme()
            if scheme is not None:
                schemes.append(scheme)
        return schemes

    # ---------- 删除方案 ----------

    def delete_current_scheme(self) -> bool:
        item = self._scheme_list.currentItem()
        if item is None:
            alert(self.window(), "删除方案", "请先选择方案")
            return False
        name = item.data(Qt.UserRole)
        if not confirm(self.window(), "删除方案", f"确定删除方案「{name}」？"):
            return False
        self._store.remove(name)
        if not self._store.save():
            alert(self.window(), "删除方案",
                  f"写入方案文件失败：\n{self._store.path}\n\n"
                  f"原因：{self._store.last_error or '未知错误'}")
        self.refresh()
        self.schemesChanged.emit()
        return True

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class FilterSchemeSelectorDialog(ThemedDialog):
    """滤镜 / 方案选择弹窗（两个列表）。"""

    def __init__(self, parent=None, title: str = "选择滤镜或滤镜方案",
                 multi_select: bool = False, store=None):
        # 单选的说明已在标题与列标题里，副标题只给多选模式补充一句
        subtitle = "可多选，用于对比" if multi_select else ""
        super().__init__(title, subtitle, parent)
        self.setModal(True)
        self.setMinimumSize(560, 400)
        self.resize(640, 470)

        self._multi = bool(multi_select)

        self._selector = FilterSchemeSelectorWidget(multi_select=multi_select,
                                                    store=store, parent=self)
        self.add_content(self._selector, 1)

        self._btn_cancel = self.add_reject_button("取消")
        self._btn_ok = PrimaryButton("确定", self)
        self._btn_ok.setDefault(True)
        self._btn_ok.setAutoDefault(True)
        self._btn_ok.clicked.connect(self._on_accept)
        self.footer.add(self._btn_ok)

    @property
    def selector(self) -> FilterSchemeSelectorWidget:
        return self._selector

    def current_scheme(self) -> Optional[FilterScheme]:
        return self._selector.current_scheme()

    def selected_schemes(self) -> List[FilterScheme]:
        return self._selector.selected_schemes()

    def _on_accept(self):
        if self._multi:
            if not self._selector.selected_schemes():
                alert(self, "提示", "请至少选择一项")
                return
        elif self._selector.current_scheme() is None:
            alert(self, "提示", "请选择滤镜或方案")
            return
        self.accept()


def run_demo():
    import sys
    from PySide6.QtWidgets import QApplication

    from .ui import apply_theme, configure_application

    configure_application()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)

    dlg = FilterSchemeSelectorDialog(None, "滤镜 / 方案选择演示")
    if dlg.exec() == QDialog.Accepted:
        for scheme in dlg.selected_schemes():
            print("选中方案:", scheme.display_name(), scheme.filter_names())

    dlg2 = FilterSchemeSelectorDialog(None, "多选演示", multi_select=True)
    if dlg2.exec() == QDialog.Accepted:
        for scheme in dlg2.selected_schemes():
            print("对比项:", scheme.display_name(), scheme.filter_names())


if __name__ == "__main__":
    run_demo()
