from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QPixmap

from .list_viewer import ListViewer
from .filter_image_viewer import FilterImageViewer
from .image_viewer import ViewTransform


class ImageFilterCompareWindow(QWidget):
    def __init__(self, pixmap: QPixmap, filter_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("图像滤镜对比")
        self.setMinimumSize(800, 500)
        self.resize(1000, 650)
        self._input_pixmap = pixmap

        self._aspect_ratio = 1.0
        if pixmap and not pixmap.isNull():
            self._aspect_ratio = pixmap.width() / pixmap.height()

        self._overlap_transform: ViewTransform = None
        self._horizontal_transform: ViewTransform = None
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        items = []

        viewer_no_filter = FilterImageViewer(QPixmap(pixmap))
        viewer_no_filter.setObjectName("(无滤镜)")
        items.append(viewer_no_filter)

        for name in filter_names:
            viewer = FilterImageViewer(QPixmap(pixmap), name)
            viewer.setObjectName(name)
            items.append(viewer)

        self._list_viewer = ListViewer(
            items, view_mode=ListViewer.ViewMode.OVERLAP,
            item_width_fn=self._calc_item_width
        )
        self._list_viewer.viewModeChanging.connect(self._on_view_mode_changing)
        self._list_viewer.viewModeChanged.connect(self._on_view_mode_changed)
        self._list_viewer.itemSwitching.connect(self._on_item_changing)
        self._list_viewer.itemSwitched.connect(self._on_item_changed)

        self._list_viewer._btn_add.clicked.disconnect()
        self._list_viewer._btn_add.clicked.connect(self._on_add_item)

        self._list_viewer.closed.connect(self.close)

        layout.addWidget(self._list_viewer, 1)

        for liw in self._list_viewer._item_widgets:
            self._hook_item(liw)

        self._list_viewer.updateGeometry()

        self._list_viewer.layout().activate()
        self._init_mode_transform()

    def _init_mode_transform(self, mode=None):
        if mode is None:
            mode = self._list_viewer.view_mode
        self._syncing = True
        for liw in self._list_viewer._item_widgets:
            viewer = liw.content_widget
            if isinstance(viewer, FilterImageViewer):
                viewer.image_viewer._view.fit_in_view()
        first_vt = None
        for liw in self._list_viewer._item_widgets:
            viewer = liw.content_widget
            if isinstance(viewer, FilterImageViewer):
                if first_vt is None:
                    first_vt = viewer.image_viewer.export_view_transform()
                else:
                    viewer.image_viewer.import_view_transform(first_vt)
        if mode == ListViewer.ViewMode.OVERLAP:
            self._overlap_transform = first_vt
        else:
            self._horizontal_transform = first_vt
        self._syncing = False
        

    def _hook_item(self, liw):
        viewer = liw.content_widget
        if isinstance(viewer, FilterImageViewer):
            viewer.transformChanged.connect(
                lambda v=viewer: self._on_transform_changed(v)
            )

    def _calc_item_width(self, liw, item_h):
        overhead = 80
        content_h = item_h - overhead
        if content_h < 50:
            content_h = 50
        return int(content_h * self._aspect_ratio) + 8
    
    def _on_item_changing(self,liw):
        print('切换项开始，保存ViewMode.OVERLAP')
        self._overlap_transform = liw.content_widget.image_viewer.export_view_transform()
        pass

    def _on_item_changed(self,liw):
        print('切换项完成，读取ViewMode.OVERLAP')
        if liw is not None:
            liw.content_widget.image_viewer.import_view_transform(self._overlap_transform)
        pass

    def _on_view_mode_changing(self, mode):
        self._syncing=True
        print('模式切换开始',mode)
        if mode == ListViewer.ViewMode.OVERLAP:
            print('保存ViewMode.HORIZONTAL')
            self._horizontal_transform=self._list_viewer.current_item.content_widget.image_viewer.export_view_transform()
        else:
            print('保存ViewMode.OVERLAP')
            self._overlap_transform =self._list_viewer.current_item.content_widget.image_viewer.export_view_transform()

    def _on_view_mode_changed(self, mode):
        self._syncing = False
        print('模式切换完成',mode)
        self._restore_mode_transform()

    def _restore_mode_transform(self):
        mode = self._list_viewer.view_mode
        print('读取变换',mode)
        vt = self._overlap_transform if mode == ListViewer.ViewMode.OVERLAP else self._horizontal_transform
        if vt is None:
            self._init_mode_transform()
            return
        cur = self._list_viewer.current_item
        if cur is None:
            return
        viewer = cur.content_widget
        if not isinstance(viewer, FilterImageViewer):
            return
        
        print('同步变换到所有控件',self._list_viewer.view_mode)
        self._sync_all_to(vt)

    def _on_transform_changed(self, viewer):
        if self._syncing or self._list_viewer.view_mode == ListViewer.ViewMode.OVERLAP:
            return
        vt = viewer.image_viewer.export_view_transform()
        print('保存变换',self._list_viewer.view_mode)
        if self._list_viewer.view_mode == ListViewer.ViewMode.OVERLAP:
            self._overlap_transform = vt
        else:
            self._horizontal_transform = vt

        print('同步变换到其他控件',self._list_viewer.view_mode)
        self._sync_all_to(vt, exclude=viewer)

    def _sync_all_to(self, vt: ViewTransform, exclude=None):
        self._syncing = True
        for liw in self._list_viewer._item_widgets:
            v = liw.content_widget
            if isinstance(v, FilterImageViewer) and v is not exclude:
                v.image_viewer.import_view_transform(vt)
        self._syncing = False

    def _on_add_item(self):
        viewer = FilterImageViewer(QPixmap(self._input_pixmap))
        self._list_viewer.add_item(viewer)
        for liw in self._list_viewer._item_widgets:
            if liw.content_widget is viewer:
                self._hook_item(liw)
                break
        if self._list_viewer.view_mode == ListViewer.ViewMode.OVERLAP:
            if self._overlap_transform is not None:
                self._syncing = True
                viewer.image_viewer.import_view_transform(self._overlap_transform)
                self._syncing = False
        elif self._horizontal_transform is not None:
            self._syncing = True
            viewer.image_viewer.import_view_transform(self._horizontal_transform)
            self._syncing = False
