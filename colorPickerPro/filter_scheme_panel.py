"""
滤镜方案的界面组件
==================

- FilterParamsWidget ：参数编辑区（原先 _FilterParamsPanel 里的参数控件，可嵌入任意面板）
- FilterSchemePanel  ：滤镜方案管理面板（添加 / 删除 / 复制 / 选择 / 排序滤镜，
                       编辑被选滤镜的参数，保存 / 加载方案）

方案管理面板把滤镜当作图层来操作：图层列表在左侧（可拖动排序、勾选启用），
被选图层的参数编辑区在右侧（复用原先已实现的参数编辑控件）。
删除“方案”的功能不在这里，而在选择列表（filter_scheme_selector.py）中。
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QScrollArea, QMenu, QInputDialog,
    QMessageBox, QAbstractItemView, QFileDialog,
)

from .filter_lib import ImageFilter
from .filter_scheme import FilterScheme, get_scheme_store
from .list_selection_dialog import ListSelectionDialog


# ============================================================
# 参数编辑区
# ============================================================

class FilterParamsWidget(QWidget):
    """参数编辑区：为每个参数生成一行编辑控件。"""

    paramsChanged = Signal()

    def __init__(self, params: Optional[list] = None, on_changed=None,
                 title: str = "", parent=None):
        super().__init__(parent)
        self._params: List = []
        self._param_widgets: List[QWidget] = []
        self._on_changed = on_changed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if title:
            title_lbl = QLabel(title)
            title_lbl.setObjectName("paramTitle")
            layout.addWidget(title_lbl)

        self._rows = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        layout.addWidget(self._rows)

        self._empty_lbl = QLabel("该滤镜没有可调参数")
        self._empty_lbl.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._empty_lbl)

        layout.addStretch()

        self.setStyleSheet("""
            QLabel#paramTitle { font-weight: bold; font-size: 13px; color: #ddd; }
            QLabel#paramName { color: #bbb; font-size: 12px; }
            QDoubleSpinBox { background: #3a3a3a; color: white; border: 1px solid #555;
                             border-radius: 3px; padding: 2px 4px; font-size: 11px; }
            QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; }
            QSlider::handle:horizontal { background: #999; width: 14px; margin: -5px 0;
                                         border-radius: 7px; }
            QSlider::handle:horizontal:hover { background: #bbb; }
        """)

        if params:
            self.set_params(params)

    def params(self) -> List:
        return list(self._params)

    def detach_params(self):
        """解除参数与控件的绑定，避免控件销毁后参数再访问它。"""
        for p in self._params:
            p._container = None
            p._opacity_effect = None
        self._params = []

    def set_params(self, params: Optional[list]):
        self.detach_params()
        for w in self._param_widgets:
            self._rows_layout.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._param_widgets = []

        self._params = list(params or [])
        for p in self._params:
            w = p.create_widget(self._emit_changed)
            self._rows_layout.addWidget(w)
            self._param_widgets.append(w)

        self._empty_lbl.setVisible(not self._params)

    def _emit_changed(self):
        self.paramsChanged.emit()
        if self._on_changed is not None:
            self._on_changed()


# ============================================================
# 面板标题栏（无边框窗口拖动）
# ============================================================

class _DragBar(QWidget):
    def __init__(self, target: QWidget, parent=None):
        super().__init__(parent)
        self._target = target
        self._drag_offset = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self._target.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            self._target.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        e.accept()


# ============================================================
# 滤镜方案管理面板
# ============================================================

class FilterSchemePanel(QDialog):
    """滤镜方案管理面板。

    图层化地管理一个滤镜方案：
    - 添加滤镜、删除滤镜、复制滤镜
    - 选择（选中即编辑其参数）
    - 排序（上移 / 下移，或直接拖动列表项）
    - 保存方案 / 加载方案

    面板直接修改传入的 FilterScheme 对象，内容变化时发出 schemeChanged。
    如果面板换掉了方案对象本身（例如“加载方案”），会发出 schemeReplaced(new_scheme)，
    宿主必须据此改用自己的引用，否则会继续用旧配置渲染。
    """

    schemeChanged = Signal()          # 方案内容变化（图层/参数），需要重新处理图像
    schemeReplaced = Signal(object)   # 方案对象被整体替换（加载方案），参数是新方案
    schemesChanged = Signal()         # 已保存的方案列表变化（保存成功时）

    def __init__(self, scheme: Optional[FilterScheme] = None, store=None, parent=None):
        super().__init__(parent)
        self._store = store if store is not None else get_scheme_store()
        self._scheme = scheme if isinstance(scheme, FilterScheme) else FilterScheme()
        self._suspend = False
        # 最近一次保存/加载时的内容签名：与当前内容不同即视为“有未保存修改”
        self._saved_state = self._scheme.state_signature()

        self.setWindowTitle("滤镜方案")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setModal(False)
        self.setMinimumSize(560, 360)
        self.resize(640, 420)

        self._build_ui()
        self._reload_layers()

    # ---------- 界面 ----------

    def _build_ui(self):
        self.setStyleSheet("""
            FilterSchemePanel { background-color: #242424; border: 1px solid #555; }
            QLabel#schemeTitle { font-weight: bold; font-size: 13px; color: #ddd;
                                 background: transparent; }
            QLabel#listCaption { color: #999; font-size: 11px; }
            QListWidget { background: #2a2a2a; color: #ddd; border: 1px solid #444;
                          border-radius: 3px; font-size: 12px; }
            QListWidget::item { padding: 4px 6px; }
            QListWidget::item:selected { background: #5C6BC0; color: white; }
            QScrollArea { border: none; background: transparent; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # 标题栏
        bar = _DragBar(self, self)
        bar.setFixedHeight(28)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(4, 0, 0, 0)
        bar_lay.setSpacing(6)

        icon = QLabel("🧩")
        icon.setStyleSheet("background: transparent;")
        bar_lay.addWidget(icon)

        self._title_lbl = QLabel("滤镜方案")
        self._title_lbl.setObjectName("schemeTitle")
        bar_lay.addWidget(self._title_lbl)

        self._name_lbl = QLabel("")
        self._name_lbl.setStyleSheet("color: #8bc34a; font-size: 12px; background: transparent;")
        bar_lay.addWidget(self._name_lbl)
        bar_lay.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet("""
            QPushButton { background-color: #E53935; color: white; border: none;
                          border-radius: 3px; font-size: 12px; }
            QPushButton:hover { background-color: #C62828; }
        """)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        bar_lay.addWidget(btn_close)
        root.addWidget(bar)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self._btn_add = QPushButton("＋ 添加滤镜")
        self._btn_add.setStyleSheet(self._btn_style("#26A69A"))
        self._btn_add.setCursor(Qt.PointingHandCursor)
        self._btn_add.setMenu(self._make_add_menu())
        toolbar.addWidget(self._btn_add)

        self._btn_copy = QPushButton("⧉ 复制图层")
        self._btn_copy.setStyleSheet(self._btn_style("#5C6BC0"))
        self._btn_copy.setCursor(Qt.PointingHandCursor)
        self._btn_copy.clicked.connect(self._on_duplicate)
        toolbar.addWidget(self._btn_copy)

        self._btn_del = QPushButton("✕ 删除图层")
        self._btn_del.setStyleSheet(self._btn_style("#E53935"))
        self._btn_del.setCursor(Qt.PointingHandCursor)
        self._btn_del.clicked.connect(self._on_remove)
        toolbar.addWidget(self._btn_del)

        self._btn_up = QPushButton("▲ 上移")
        self._btn_up.setStyleSheet(self._btn_style("#455A64"))
        self._btn_up.setCursor(Qt.PointingHandCursor)
        self._btn_up.clicked.connect(lambda: self._on_move(-1))
        toolbar.addWidget(self._btn_up)

        self._btn_down = QPushButton("▼ 下移")
        self._btn_down.setStyleSheet(self._btn_style("#455A64"))
        self._btn_down.setCursor(Qt.PointingHandCursor)
        self._btn_down.clicked.connect(lambda: self._on_move(1))
        toolbar.addWidget(self._btn_down)

        toolbar.addStretch()

        self._btn_save = QPushButton("💾 保存方案")
        self._btn_save.setStyleSheet(self._btn_style("#FF8F00"))
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setToolTip(f"保存到：{self._store.path}")
        self._btn_save.clicked.connect(self._on_save)
        toolbar.addWidget(self._btn_save)

        self._btn_load = QPushButton("📂 加载方案")
        self._btn_load.setStyleSheet(self._btn_style("#00897B"))
        self._btn_load.setCursor(Qt.PointingHandCursor)
        self._btn_load.clicked.connect(self._on_load)
        toolbar.addWidget(self._btn_load)

        root.addLayout(toolbar)

        # 主体：左图层列表 / 右参数
        body = QHBoxLayout()
        body.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(4)
        cap_l = QLabel("滤镜图层（从上到下依次处理，可拖动排序）")
        cap_l.setObjectName("listCaption")
        left.addWidget(cap_l)

        self._layer_list = QListWidget()
        self._layer_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._layer_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._layer_list.setDefaultDropAction(Qt.MoveAction)
        self._layer_list.currentRowChanged.connect(self._on_current_changed)
        self._layer_list.itemChanged.connect(self._on_item_changed)
        self._layer_list.model().rowsMoved.connect(self._on_rows_moved)
        left.addWidget(self._layer_list, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self._param_caption = QLabel("参数")
        self._param_caption.setObjectName("listCaption")
        right.addWidget(self._param_caption)

        self._params_widget = FilterParamsWidget(None, None, "")
        self._params_widget.paramsChanged.connect(self._on_params_changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self._params_widget)
        right.addWidget(scroll, 1)
        body.addLayout(right, 2)

        root.addLayout(body, 1)

        self._update_title()

    def _make_add_menu(self) -> QMenu:
        menu = QMenu(self)
        for cls in ImageFilter.all_filters():
            act = menu.addAction(cls.name())
            act.triggered.connect(lambda checked=False, c=cls: self._add_filter(c))
        return menu

    @staticmethod
    def _btn_style(color: str) -> str:
        return (f"QPushButton {{ padding: 4px 10px; font-size: 11px; background-color: {color};"
                " color: white; border: none; border-radius: 3px; }"
                "QPushButton:hover { background-color: #3a3a3a; }")

    # ---------- 方案存取 ----------

    @property
    def scheme(self) -> FilterScheme:
        return self._scheme

    def set_scheme(self, scheme: FilterScheme, notify: bool = True):
        self._scheme = scheme if isinstance(scheme, FilterScheme) else FilterScheme()
        self._saved_state = self._scheme.state_signature()
        self._update_title()
        self._reload_layers()
        if notify:
            self.schemeChanged.emit()

    def replace_scheme(self, scheme: FilterScheme):
        """整体替换方案对象并通知宿主（宿主必须更新自己的引用）。"""
        self.set_scheme(scheme, notify=False)
        self.schemeReplaced.emit(self._scheme)

    def sync_scheme(self, scheme: FilterScheme):
        """宿主复用面板时重新对账：方案对象没换就什么也不做。

        直接调 set_scheme 会把“未保存修改”的基线一起重置（星号丢失），
        所以只有对象真的换了才重新绑定。
        """
        if scheme is not self._scheme:
            self.set_scheme(scheme, notify=False)

    def is_dirty(self) -> bool:
        """方案相对最近一次保存/加载是否已被修改。"""
        return self._scheme.state_signature() != self._saved_state

    def _reset_dirty(self):
        self._saved_state = self._scheme.state_signature()
        self._update_title()

    def _update_title(self):
        self._title_lbl.setText("滤镜方案")
        name = self._scheme.display_name()
        if name and self.is_dirty():
            name = f"{name}*"   # 有未保存修改
        text = f"[{name}]" if name else ""
        if text != self._name_lbl.text():
            self._name_lbl.setText(text)

    # ---------- 图层列表 ----------

    def _reload_layers(self, select: Optional[int] = None):
        self._suspend = True
        self._layer_list.clear()
        for layer in self._scheme.layers:
            item = QListWidgetItem(layer.name)
            item.setData(Qt.UserRole, layer)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                          | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if layer.enabled else Qt.Unchecked)
            self._layer_list.addItem(item)
        self._suspend = False

        count = self._layer_list.count()
        if count == 0:
            self._rebuild_params()
            return

        row = self._layer_list.currentRow() if select is None else select
        if row is None or row < 0 or row >= count:
            row = 0
        self._layer_list.setCurrentRow(row)
        self._rebuild_params()

    def current_layer(self):
        row = self._layer_list.currentRow()
        if 0 <= row < len(self._scheme.layers):
            return self._scheme.layers[row]
        return None

    def _current_row(self) -> int:
        return self._layer_list.currentRow()

    def _on_current_changed(self, row: int):
        if self._suspend:
            return
        self._rebuild_params()

    def _on_item_changed(self, item: QListWidgetItem):
        if self._suspend:
            return
        layer = item.data(Qt.UserRole)
        if layer is None:
            return
        enabled = item.checkState() == Qt.Checked
        if layer.enabled != enabled:
            layer.enabled = enabled
            self._notify()

    def _on_rows_moved(self, *args):
        if self._suspend:
            return
        order = []
        for i in range(self._layer_list.count()):
            layer = self._layer_list.item(i).data(Qt.UserRole)
            if layer is None:
                return  # 列表项数据丢失：放弃这次重排，保留原顺序
            order.append(layer)
        if len(order) != len(self._scheme.layers):
            return
        self._scheme.layers = order
        self._update_title()
        self._notify()

    # ---------- 图层操作 ----------

    def _add_filter(self, filter_cls):
        row = self._current_row()
        index = row + 1 if row >= 0 else None
        layer = self._scheme.add_filter(filter_cls, index)
        self._reload_layers(select=self._scheme.layers.index(layer))
        self._notify()

    def _on_duplicate(self):
        row = self._current_row()
        if row < 0:
            return
        layer = self._scheme.duplicate_layer(row)
        if layer is None:
            return
        self._reload_layers(select=row + 1)
        self._notify()

    def _on_remove(self):
        row = self._current_row()
        if row < 0:
            return
        self._scheme.remove_layer(row)
        self._reload_layers(select=min(row, len(self._scheme.layers) - 1))
        self._notify()

    def _on_move(self, delta: int):
        row = self._current_row()
        new_row = self._scheme.move_layer(row, delta)
        if new_row == row:
            return
        self._reload_layers(select=new_row)
        self._notify()

    # ---------- 参数 ----------

    def _rebuild_params(self):
        layer = self.current_layer()
        if layer is None:
            self._param_caption.setText("参数（未选择滤镜）")
            self._params_widget.set_params([])
            return
        self._param_caption.setText(f"参数 - {layer.name}")
        self._params_widget.set_params(layer.filter.exposed_parameters())

    def _on_params_changed(self):
        self._notify()

    def _notify(self):
        self._update_title()
        self.schemeChanged.emit()

    # ---------- 保存 / 加载 ----------

    def _on_save(self):
        default_name = self._scheme.name or ""
        name, ok = QInputDialog.getText(self, "保存滤镜方案", "方案名称：",
                                        text=default_name)
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "保存滤镜方案", "方案名称不能为空")
            return
        if self._store.has(name):
            ret = QMessageBox.question(self, "保存滤镜方案",
                                       f"方案「{name}」已存在，是否覆盖？")
            if ret != QMessageBox.Yes:
                return
        if not self._store.add(self._scheme.clone(name=name), overwrite=True):
            QMessageBox.warning(self, "保存滤镜方案", "保存失败")
            return
        if not self._save_store():
            return
        self._scheme.name = name
        self._reset_dirty()
        self.schemeChanged.emit()
        self.schemesChanged.emit()

    def _save_store(self) -> bool:
        """写入方案文件；失败时说明原因并允许另选保存位置。"""
        if self._store.save():
            self._btn_save.setToolTip(f"保存到：{self._store.path}")
            return True
        detail = self._store.last_error or "未知错误"
        QMessageBox.warning(self, "保存滤镜方案",
                            f"写入方案文件失败：\n{self._store.path}\n\n原因：{detail}")
        ret = QMessageBox.question(self, "保存滤镜方案", "是否另选一个保存位置？")
        if ret != QMessageBox.Yes:
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, "选择滤镜方案文件", self._store.path, "方案文件 (*.json)")
        if not path:
            return False
        if self._store.save_as(path):
            return True
        QMessageBox.warning(self, "保存滤镜方案",
                            f"仍然写入失败：\n{path}\n\n原因：{self._store.last_error}")
        return False

    def _on_load(self):
        names = self._store.names()
        if not names:
            QMessageBox.information(self, "加载滤镜方案", "还没有已保存的方案")
            return
        current = self._scheme.name
        index = names.index(current) if current in names else 0
        dlg = ListSelectionDialog(self, "加载滤镜方案", names,
                                  selection_mode="single", current_index=index)
        if dlg.exec() != ListSelectionDialog.Accepted:
            return
        picked = dlg.get_selected_indices()
        if not picked:
            return
        stored = self._store.get(names[picked[0]])
        if stored is None:
            return
        self.replace_scheme(stored.clone())

    def closeEvent(self, event):
        self._params_widget.detach_params()
        super().closeEvent(event)
