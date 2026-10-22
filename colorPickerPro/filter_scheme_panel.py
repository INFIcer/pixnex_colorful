"""
滤镜方案的界面组件
==================

- FilterParamsWidget ：参数编辑区（原先 _FilterParamsPanel 里的参数控件，可嵌入任意面板）
- FilterSchemePanel  ：滤镜方案管理面板（添加 / 删除 / 复制 / 选择 / 排序滤镜，
                       编辑被选滤镜的参数，保存 / 加载方案）

方案管理面板把滤镜当作图层来操作：图层列表在左右分栏的左侧（可拖动排序、勾选启用），
被选图层的参数编辑区在右侧（复用原先已实现的参数编辑控件）。
删除“方案”的功能不在这里，而在选择列表（filter_scheme_selector.py）中。

面板使用 ``colorPickerPro.ui`` 设计系统：``ThemedDialog`` 外壳（无边框 + 自绘标题栏）、
工具栏用 ``FlowLayout`` 自动换行，主体用 ``QSplitter`` 分栏，所以窗口变窄时不会出界或重叠。
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QSplitter,
    QMenu, QAbstractItemView,
)

from .filter_lib import ImageFilter
from .filter_scheme import FilterScheme, get_scheme_store
from .list_selection_dialog import ListSelectionDialog
from .ui.components import (
    CaptionLabel, FlowLayout, HintLabel, IconButton,
    ScrollArea, SectionTitle, ThemedDialog,
    alert, confirm, get_save_file_name, prompt_text,
)
from .ui.tokens import SPACE


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
        layout.setSpacing(SPACE.md)

        if title:
            layout.addWidget(SectionTitle(title))

        self._rows = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(SPACE.md)
        layout.addWidget(self._rows)

        self._empty_lbl = HintLabel("该滤镜没有可调参数")
        layout.addWidget(self._empty_lbl)

        layout.addStretch()

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
        # 参数区整体换页：关闭重绘，避免控件销毁/重建时中间态被画出来
        # （表现为参数区或面板闪一下）。
        self.setUpdatesEnabled(False)
        try:
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
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _emit_changed(self):
        self.paramsChanged.emit()
        if self._on_changed is not None:
            self._on_changed()


# ============================================================
# 滤镜方案管理面板
# ============================================================

class FilterSchemePanel(ThemedDialog):
    """滤镜方案管理面板（无边框工具窗口）。

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
        super().__init__("滤镜方案", "", parent)
        # 无边框工具窗口：标题栏 / 关闭按钮 / 尺寸手柄都由 FramelessWindowMixin
        # 提供，这里只需保留 Tool 语义（跟随父窗口、不占任务栏）。
        self.setWindowFlag(Qt.Tool, True)
        self.setModal(False)

        self._store = store if store is not None else get_scheme_store()
        self._scheme = scheme if isinstance(scheme, FilterScheme) else FilterScheme()
        self._suspend = False
        self._param_layer = None
        # 最近一次保存/加载时的内容签名：与当前内容不同即视为“有未保存修改”
        self._saved_state = self._scheme.state_signature()

        # 动态方案名显示在标题栏下方的副标题里（带 * 表示有未保存修改）。
        # 兼容旧属性名（测试/宿主会读它），但写入统一走 set_subtitle()。
        self._name_lbl = self.subtitle_label

        self.setMinimumSize(560, 360)
        self.resize(640, 440)

        self._build_ui()
        self._reload_layers()

    # ---------- 界面 ----------

    def _build_ui(self):
        # 工具栏：图层操作 + 文件操作。窗口变窄时 FlowLayout 自动换行，不会顶出窗口
        toolbar = QWidget(self)
        flow = FlowLayout(toolbar, margin=0,
                          h_spacing=SPACE.xs, v_spacing=SPACE.xs)

        self._btn_add = IconButton("add", tooltip="添加滤镜")
        self._btn_add.setMenu(self._make_add_menu())
        flow.addWidget(self._btn_add)

        self._btn_copy = IconButton("copy", tooltip="复制图层")
        self._btn_copy.clicked.connect(self._on_duplicate)
        flow.addWidget(self._btn_copy)

        self._btn_del = IconButton("trash", tooltip="删除图层", danger=True)
        self._btn_del.clicked.connect(self._on_remove)
        flow.addWidget(self._btn_del)

        self._btn_up = IconButton("chevron-up", tooltip="上移一层")
        self._btn_up.clicked.connect(lambda: self._on_move(-1))
        flow.addWidget(self._btn_up)

        self._btn_down = IconButton("chevron-down", tooltip="下移一层")
        self._btn_down.clicked.connect(lambda: self._on_move(1))
        flow.addWidget(self._btn_down)

        self._btn_save = IconButton("save", tooltip="保存方案")
        self._btn_save.clicked.connect(self._on_save)
        flow.addWidget(self._btn_save)

        self._btn_load = IconButton("open", tooltip="加载方案")
        self._btn_load.clicked.connect(self._on_load)
        flow.addWidget(self._btn_load)

        self.add_body(toolbar)

        # 主体：左图层列表 / 右参数（可拖动分栏，各自有最小宽度）
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(SPACE.sm)

        left_host = QWidget(splitter)
        cap_l = CaptionLabel("滤镜图层", word_wrap=True)
        self._layer_list = QListWidget(left_host)
        self._layer_list.setToolTip("从上到下依次处理，可拖动调整顺序")
        self._layer_list.setMinimumWidth(180)
        self._layer_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._layer_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._layer_list.setDefaultDropAction(Qt.MoveAction)
        self._layer_list.currentRowChanged.connect(self._on_current_changed)
        self._layer_list.itemChanged.connect(self._on_item_changed)
        self._layer_list.model().rowsMoved.connect(self._on_rows_moved)
        left_layout = QVBoxLayout(left_host)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(SPACE.xs)
        left_layout.addWidget(cap_l)
        left_layout.addWidget(self._layer_list, 1)

        right_host = QWidget(splitter)
        self._param_caption = CaptionLabel("参数", word_wrap=True)
        self._params_widget = FilterParamsWidget(None, None, "")
        self._params_widget.paramsChanged.connect(self._on_params_changed)
        param_scroll = ScrollArea(self._params_widget, right_host)
        param_scroll.setMinimumWidth(240)
        right_layout = QVBoxLayout(right_host)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(SPACE.xs)
        right_layout.addWidget(self._param_caption)
        right_layout.addWidget(param_scroll, 1)

        splitter.addWidget(left_host)
        splitter.addWidget(right_host)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        self.add_body(splitter, 1)

        self._update_title()

    def _make_add_menu(self) -> QMenu:
        menu = QMenu(self)
        for cls in ImageFilter.all_filters():
            act = menu.addAction(cls.name())
            act.triggered.connect(lambda checked=False, c=cls: self._add_filter(c))
        return menu

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
        name = self._scheme.display_name()
        if name and self.is_dirty():
            name = f"{name}*"   # 有未保存修改
        # 标题栏只放固定标题，方案名放在副标题：写入统一走 ThemedDialog 接口
        self.set_title("滤镜方案")
        self.set_subtitle(f"[{name}]" if name else "")

    # ---------- 图层列表 ----------

    def _reload_layers(self, select: Optional[int] = None):
        # 列表与参数区一起重建：冻结重绘并只在最后重建一次参数区，
        # 避免 clear()/setCurrentRow() 触发的中间帧造成闪屏。
        self.setUpdatesEnabled(False)
        self._suspend = True
        try:
            self._layer_list.clear()
            for layer in self._scheme.layers:
                item = QListWidgetItem(layer.name)
                item.setData(Qt.UserRole, layer)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                              | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if layer.enabled else Qt.Unchecked)
                self._layer_list.addItem(item)

            count = self._layer_list.count()
            if count > 0:
                row = self._layer_list.currentRow() if select is None else select
                if row is None or row < 0 or row >= count:
                    row = 0
                # 仍处于 _suspend 状态，setCurrentRow 不会触发参数区重建。
                self._layer_list.setCurrentRow(row)
        finally:
            self._suspend = False
            self.setUpdatesEnabled(True)

        if count == 0:
            self._rebuild_params()
            return
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

    def _rebuild_params(self, force: bool = False):
        layer = self.current_layer()
        if not force and layer is self._param_layer:
            # 上移/下移只是换顺序，选中图层对象没变，参数区无需重建。
            return
        self._param_layer = layer
        if layer is None:
            self._param_caption.setText("参数")
            self._params_widget.set_params([])
            return
        self._param_caption.setText(f"参数 · {layer.name}")
        self._params_widget.set_params(layer.filter.exposed_parameters())

    def _on_params_changed(self):
        self._notify()

    def _notify(self):
        self._update_title()
        self.schemeChanged.emit()

    # ---------- 保存 / 加载 ----------

    def _on_save(self):
        default_name = self._scheme.name or ""
        # 无边框文本输入对话框（ui.components.prompt_text），返回 (text, ok)
        name, ok = prompt_text(self, "保存滤镜方案", "方案名称", default_name)
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            alert(self, "保存滤镜方案", "方案名称不能为空")
            return
        if self._store.has(name):
            if not confirm(self, "保存滤镜方案", f"方案「{name}」已存在，是否覆盖？"):
                return
        if not self._store.add(self._scheme.clone(name=name), overwrite=True):
            alert(self, "保存滤镜方案", "保存失败")
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
            return True
        detail = self._store.last_error or "未知错误"
        alert(self, "保存滤镜方案",
              f"写入方案文件失败：\n{self._store.path}\n\n原因：{detail}")
        if not confirm(self, "保存滤镜方案", "是否另选一个保存位置？"):
            return False
        # 无边框文件选择对话框（ui.components.get_save_file_name）
        path, _ = get_save_file_name(
            self, "选择滤镜方案文件", self._store.path, "方案文件 (*.json)")
        if not path:
            return False
        if self._store.save_as(path):
            return True
        alert(self, "保存滤镜方案",
              f"仍然写入失败：\n{path}\n\n原因：{self._store.last_error}")
        return False

    def _on_load(self):
        names = self._store.names()
        if not names:
            alert(self, "加载滤镜方案", "还没有已保存的方案")
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


__all__ = ["FilterParamsWidget", "FilterSchemePanel"]
