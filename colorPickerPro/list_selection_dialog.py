"""列表选择对话框（单选 / 多选）。

统一继承 :class:`ThemedDialog`：标题 / 副标题 / 可滚动列表 / 右下角按钮全部由
设计系统提供，不在本文件写任何样式表。

选择语义保持不变：
    * ``selection_mode="single"``   —— 单选，``current_index`` 为初始选中项；
    * ``selection_mode="multiple"`` —— 多选，点击可切换每一项（``MultiSelection``
      本身的行为），``checked_indices`` 为初始选中项；
    * ``get_selected_indices()``    —— 返回当前选中的行号列表；
    * ``selectedIndices``           —— 确认时发出一次。
"""

import sys

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QListWidget, QListWidgetItem, QWidget,
)

from .ui.components import ThemedDialog
from .ui.theme import ensure_theme

# 列表行高：比默认行高稍大，便于点选（不是控件固定尺寸，只是行数据）。
_ROW_HEIGHT = 40


class ListSelectionDialog(ThemedDialog):
    selectedIndices = Signal(list)

    def __init__(self, parent=None, title="选择", items=None,
                 selection_mode="single", checked_indices=None,
                 current_index=0):
        subtitle = "可多选" if selection_mode == "multiple" else ""
        super().__init__(title, subtitle, parent)
        self.setMinimumSize(360, 420)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self._selection_mode = selection_mode
        self._items = list(items or [])
        self._selected_indices = []

        self._list = QListWidget(self)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
            if selection_mode == "multiple"
            else QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._build_items(checked_indices or [], current_index)
        self.add_content(self._list, 1)

        self.add_reject_button("取消")
        self.add_accept_button("确定")

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_items(self, checked_indices, current_index):
        self._list.clear()
        for index, text in enumerate(self._items):
            item = QListWidgetItem(str(text))
            item.setSizeHint(QSize(0, _ROW_HEIGHT))
            self._list.addItem(item)

        if self._selection_mode == "multiple":
            for index in checked_indices:
                if 0 <= index < self._list.count():
                    self._list.item(index).setSelected(True)
        elif 0 <= current_index < self._list.count():
            self._list.setCurrentRow(current_index)

        self._selected_indices = self._collect_checked_indices()

    # ------------------------------------------------------------------
    # 选择状态
    # ------------------------------------------------------------------
    def _collect_checked_indices(self):
        if self._selection_mode == "multiple":
            return [index for index in range(self._list.count())
                    if self._list.item(index).isSelected()]
        row = self._list.currentRow()
        return [row] if row >= 0 else []

    def _on_item_clicked(self, index):
        """程序化地模拟点击某一行（与鼠标点击语义一致）。"""
        item = self._list.item(index)
        if item is None:
            return
        if self._selection_mode == "multiple":
            item.setSelected(not item.isSelected())
        else:
            self._list.setCurrentRow(index)

    def get_selected_indices(self):
        return self._collect_checked_indices()

    # ------------------------------------------------------------------
    # 确认
    # ------------------------------------------------------------------
    def accept(self):
        self._selected_indices = self._collect_checked_indices()
        self.selectedIndices.emit(self._selected_indices)
        super().accept()

    def _on_accept(self):
        """兼容旧接口：等同于点「确定」。"""
        self.accept()


def run_demo():
    from PySide6.QtWidgets import QVBoxLayout

    from .ui.components import (
        PrimaryButton, SecondaryButton, SubtitleLabel, TitleLabel, alert,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    ensure_theme(app)

    items = [
        "颜色模型 - RGB", "颜色模型 - HSV", "颜色模型 - OKLab",
        "颜色模型 - OKLCH", "颜色模型 - CIE Lab", "颜色模型 - CIE LCH",
    ]

    win = QWidget()
    win.setWindowTitle("列表选择弹窗演示")
    win.resize(380, 280)
    layout = QVBoxLayout(win)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(12)
    layout.addWidget(TitleLabel("列表选择弹窗"))
    layout.addWidget(SubtitleLabel("两种选择模式"))
    layout.addStretch(1)

    def on_single():
        dlg = ListSelectionDialog(win, "选择颜色模型", items,
                                  selection_mode="single", current_index=2)
        if dlg.exec() == ListSelectionDialog.Accepted:
            idx = dlg.get_selected_indices()[0]
            alert(win, "选中结果", f"选中：{items[idx]}")

    def on_multiple():
        dlg = ListSelectionDialog(win, "选择颜色模型", items,
                                  selection_mode="multiple",
                                  checked_indices=[0, 3, 5])
        if dlg.exec() == ListSelectionDialog.Accepted:
            idxs = dlg.get_selected_indices()
            names = "\n".join(f"  {i}. {items[i]}" for i in idxs)
            alert(win, "选中结果", f"已选 {len(idxs)} 项：\n{names}")

    btn_single = PrimaryButton("单选模式")
    btn_single.clicked.connect(on_single)
    layout.addWidget(btn_single)

    btn_multiple = SecondaryButton("多选模式")
    btn_multiple.clicked.connect(on_multiple)
    layout.addWidget(btn_multiple)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
