"""
滤镜 / 方案选择界面
==================

- FilterSchemeSelectorWidget ：两个列表（滤镜库 + 已保存方案）的选择控件
- FilterSchemeSelectorDialog ：带确定/取消的弹窗版

左侧列出所有可用滤镜，右侧列出已保存的滤镜方案。选中左侧滤镜时，相当于
“用一个只含该滤镜的方案”（替换原先直接创建滤镜的行为）；选中右侧方案时，
直接使用该方案。删除方案的功能放在本列表中。
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView,
)

from .filter_lib import ImageFilter
from .filter_scheme import FilterScheme, get_scheme_store


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
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)

        # 左：滤镜库
        left = QVBoxLayout()
        left.setSpacing(2)
        cap_l = QLabel("滤镜库（选中即新建只含该滤镜的方案）")
        cap_l.setStyleSheet("color: #999; font-size: 11px;")
        left.addWidget(cap_l)

        self._filter_list = QListWidget()
        self._setup_list(self._filter_list)
        left.addWidget(self._filter_list, 1)
        row.addLayout(left, 1)

        # 右：已保存方案
        right = QVBoxLayout()
        right.setSpacing(2)
        cap_r = QLabel("已保存方案")
        cap_r.setStyleSheet("color: #999; font-size: 11px;")
        right.addWidget(cap_r)

        self._scheme_list = QListWidget()
        self._setup_list(self._scheme_list)
        right.addWidget(self._scheme_list, 1)

        btns = QHBoxLayout()
        btns.setSpacing(4)
        self._btn_delete = QPushButton("🗑 删除方案")
        self._btn_delete.setStyleSheet(self._btn_style("#E53935"))
        self._btn_delete.setCursor(Qt.PointingHandCursor)
        self._btn_delete.clicked.connect(self.delete_current_scheme)
        btns.addWidget(self._btn_delete)

        self._btn_refresh = QPushButton("↻ 刷新")
        self._btn_refresh.setStyleSheet(self._btn_style("#455A64"))
        self._btn_refresh.setCursor(Qt.PointingHandCursor)
        self._btn_refresh.clicked.connect(self.refresh)
        btns.addWidget(self._btn_refresh)
        btns.addStretch()
        right.addLayout(btns)
        row.addLayout(right, 1)

        root.addLayout(row)

        self.setStyleSheet("""
            QListWidget { background: #2a2a2a; color: #ddd; border: 1px solid #444;
                          border-radius: 3px; font-size: 12px; }
            QListWidget::item { padding: 4px 6px; }
            QListWidget::item:selected { background: #5C6BC0; color: white; }
        """)

    def _setup_list(self, widget: QListWidget):
        if self._multi:
            widget.setSelectionMode(QAbstractItemView.MultiSelection)
        else:
            widget.setSelectionMode(QAbstractItemView.SingleSelection)
        widget.itemClicked.connect(lambda item, w=widget: self._on_item_picked(w))
        widget.currentRowChanged.connect(lambda row, w=widget: self._on_row_changed(row, w))
        widget.itemDoubleClicked.connect(lambda item, w=widget: self._on_double_clicked(w))

    @staticmethod
    def _btn_style(color: str) -> str:
        return (f"QPushButton {{ padding: 4px 10px; font-size: 11px; background-color: {color};"
                " color: white; border: none; border-radius: 3px; }"
                "QPushButton:hover { background-color: #3a3a3a; }")

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
            QMessageBox.information(self.window(), "删除方案", "请先选择一个已保存方案")
            return False
        name = item.data(Qt.UserRole)
        ret = QMessageBox.question(self.window(), "删除方案",
                                   f"确定删除方案「{name}」？")
        if ret != QMessageBox.Yes:
            return False
        self._store.remove(name)
        if not self._store.save():
            QMessageBox.warning(self.window(), "删除方案",
                                f"写入方案文件失败：\n{self._store.path}\n\n"
                                f"原因：{self._store.last_error or '未知错误'}")
        self.refresh()
        self.schemesChanged.emit()
        return True

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class FilterSchemeSelectorDialog(QDialog):
    """滤镜 / 方案选择弹窗（两个列表）。"""

    def __init__(self, parent=None, title: str = "选择滤镜或滤镜方案",
                 multi_select: bool = False, store=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(620, 420)
        self.setModal(True)

        self._multi = bool(multi_select)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        tip_text = ("可同时选择多个滤镜与方案进行对比" if multi_select
                    else "左：滤镜库（选中即创建只含该滤镜的方案）　右：已保存方案（可删除）")
        tip = QLabel(tip_text)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._selector = FilterSchemeSelectorWidget(multi_select=multi_select,
                                                    store=store, parent=self)
        root.addWidget(self._selector, 1)

        btns = QHBoxLayout()
        btns.addStretch()

        ok = QPushButton("确定")
        ok.setStyleSheet("""
            QPushButton { padding: 8px 26px; font-size: 13px; font-weight: bold;
                background-color: #26A69A; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #00897B; }
        """)
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._on_accept)
        btns.addWidget(ok)

        cancel = QPushButton("取消")
        cancel.setStyleSheet("""
            QPushButton { padding: 8px 26px; font-size: 13px;
                background-color: #424242; color: #ccc; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #555; color: white; }
        """)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch()
        root.addLayout(btns)

        self.setStyleSheet("QDialog { background-color: #1e1e1e; }")

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
                QMessageBox.information(self, "提示", "请至少选择一个滤镜或方案")
                return
        elif self._selector.current_scheme() is None:
            QMessageBox.information(self, "提示", "请选择一个滤镜或已保存方案")
            return
        self.accept()


def run_demo():
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

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
