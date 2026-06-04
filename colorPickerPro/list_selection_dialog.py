from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QWidget,
)
from PySide6.QtCore import Qt, Signal


_STYLE_ACTIVE = """
    QPushButton {
        text-align: left; padding: 0 16px; font-size: 14px;
        background-color: #26A69A; color: white;
        border: none; border-radius: 8px;
    }
    QPushButton:hover { background-color: #00897B; }
"""
_STYLE_INACTIVE = """
    QPushButton {
        text-align: left; padding: 0 16px; font-size: 14px;
        background-color: #2a2a2a; color: #ddd;
        border: none; border-radius: 8px;
    }
    QPushButton:hover { background-color: #353535; }
"""


class ListSelectionDialog(QDialog):
    selectedIndices = Signal(list)

    def __init__(self, parent=None, title="选择", items=None,
                 selection_mode="single", checked_indices=None,
                 current_index=0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(340, 420)
        self.setWindowModality(Qt.WindowModal)

        self._selection_mode = selection_mode
        self._selected_indices = []
        self._active = []

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 16, 16, 16)
        self.setStyleSheet("background-color: #1e1e1e;")

        self._item_widgets = []
        self._build_items(items or [], checked_indices or [], current_index)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._ok_btn = QPushButton("确定")
        self._ok_btn.setStyleSheet("""
            QPushButton {
                padding: 9px 28px; font-size: 13px; font-weight: bold;
                background-color: #26A69A; color: white;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #00897B; }
            QPushButton:pressed { background-color: #00695C; }
        """)
        self._ok_btn.setCursor(Qt.PointingHandCursor)
        self._ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                padding: 9px 28px; font-size: 13px;
                background-color: #424242; color: #ccc;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #555; color: white; }
            QPushButton:pressed { background-color: #333; }
        """)
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    def _build_items(self, items, checked_indices, current_index):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: #1a1a1a; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #444; border-radius: 4px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #555; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

        for i, text in enumerate(items):
            active_initial = False
            if self._selection_mode == "multiple":
                active_initial = i in checked_indices
                if active_initial:
                    self._selected_indices.append(i)
            else:
                active_initial = i == current_index
                if active_initial:
                    self._selected_indices = [i]

            self._active.append(active_initial)

            btn = QPushButton(text)
            btn.setFixedHeight(48)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_STYLE_ACTIVE if active_initial else _STYLE_INACTIVE)
            btn.clicked.connect(lambda checked=False, idx=i: self._on_item_clicked(idx))
            layout.addWidget(btn)
            self._item_widgets.append(btn)

        layout.addStretch()
        scroll.setWidget(container)
        self.layout().insertWidget(0, scroll)

    def _on_item_clicked(self, index):
        if self._selection_mode == "multiple":
            self._active[index] = not self._active[index]
            self._item_widgets[index].setStyleSheet(
                _STYLE_ACTIVE if self._active[index] else _STYLE_INACTIVE
            )
        else:
            for i in range(len(self._item_widgets)):
                active = i == index
                self._active[i] = active
                self._item_widgets[i].setStyleSheet(
                    _STYLE_ACTIVE if active else _STYLE_INACTIVE
                )

    def _collect_checked_indices(self):
        return [i for i, active in enumerate(self._active) if active]

    def _on_accept(self):
        self._selected_indices = self._collect_checked_indices()
        self.selectedIndices.emit(self._selected_indices)
        self.accept()

    def get_selected_indices(self):
        return self._selected_indices


def run_demo():
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QLabel, QMessageBox,
    )
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    items = [
        "颜色模型 - RGB", "颜色模型 - HSV", "颜色模型 - OKLab",
        "颜色模型 - OKLCH", "颜色模型 - CIE Lab", "颜色模型 - CIE LCH",
    ]

    win = QWidget()
    win.setWindowTitle("ListSelectionDialog 演示")
    win.setFixedSize(380, 280)
    win.setStyleSheet("background-color: #1a1a1a; color: #ddd; font-size: 14px;")
    layout = QVBoxLayout(win)
    layout.setSpacing(12)
    layout.setContentsMargins(24, 24, 24, 24)

    title = QLabel("ListSelectionDialog 演示")
    title.setStyleSheet("font-size: 18px; font-weight: bold; color: white; padding-bottom: 4px;")
    title.setAlignment(Qt.AlignCenter)
    layout.addWidget(title)

    desc = QLabel("点击下方按钮打开不同模式的列表弹窗")
    desc.setAlignment(Qt.AlignCenter)
    desc.setStyleSheet("color: #888; font-size: 12px;")
    layout.addWidget(desc)
    layout.addStretch()

    def on_single():
        dlg = ListSelectionDialog(win, "选择颜色模型（单选）", items,
                                  selection_mode="single", current_index=2)
        if dlg.exec() == ListSelectionDialog.Accepted:
            idx = dlg.get_selected_indices()[0]
            QMessageBox.information(win, "选中结果", f"选中了：{items[idx]}")

    def on_multiple():
        dlg = ListSelectionDialog(win, "选择颜色模型（复选）", items,
                                  selection_mode="multiple", checked_indices=[0, 3, 5])
        if dlg.exec() == ListSelectionDialog.Accepted:
            idxs = dlg.get_selected_indices()
            names = "\n".join(f"  {i}. {items[i]}" for i in idxs)
            QMessageBox.information(win, "选中结果", f"选中了 {len(idxs)} 项：\n{names}")

    btn_single = QPushButton("单选模式")
    btn_single.setStyleSheet("""
        QPushButton { padding: 10px; font-size: 15px; font-weight: bold;
            background-color: #26A69A; color: white;
            border: none; border-radius: 6px; }
        QPushButton:hover { background-color: #00897B; }
        QPushButton:pressed { background-color: #00695C; }
    """)
    btn_single.setCursor(Qt.PointingHandCursor)
    btn_single.clicked.connect(on_single)
    layout.addWidget(btn_single)

    btn_multiple = QPushButton("复选模式")
    btn_multiple.setStyleSheet("""
        QPushButton { padding: 10px; font-size: 15px; font-weight: bold;
            background-color: #5C6BC0; color: white;
            border: none; border-radius: 6px; }
        QPushButton:hover { background-color: #3F51B5; }
        QPushButton:pressed { background-color: #303F9F; }
    """)
    btn_multiple.setCursor(Qt.PointingHandCursor)
    btn_multiple.clicked.connect(on_multiple)
    layout.addWidget(btn_multiple)

    layout.addStretch()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()
