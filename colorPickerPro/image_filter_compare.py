import sys
from functools import partial
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QPixmap

if __name__ == "__main__" and (__package__ is None or __package__ == ''):
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from colorPickerPro.list_viewer import ListViewer
    from colorPickerPro.filter_image_viewer import FilterImageViewer
    from colorPickerPro.image_viewer import ViewTransform
else:
    from .list_viewer import ListViewer
    from .filter_image_viewer import FilterImageViewer
    from .image_viewer import ViewTransform


class ImageFilterCompareWindow(QWidget):
    def __init__(self, pixmap: QPixmap, filter_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("图像滤镜对比")
        self.resize(1000, 650)
        self._input_pixmap = pixmap

        self._aspect_ratio = 1.0
        if pixmap and not pixmap.isNull():
            self._aspect_ratio = pixmap.width() / pixmap.height()

        self._overlap_transform: ViewTransform = None
        self._horizontal_transform: ViewTransform = None

        self.__syncing = True 
        '当实时同步开启时为True'
        
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
        self._list_viewer.rebuilding.connect(self._on_rebuilding)
        self._list_viewer.rebuilded.connect(self._on_rebuilded)
        self._list_viewer.viewModeChanging.connect(self._on_view_mode_changing)
        self._list_viewer.viewModeChanged.connect(self._on_view_mode_changed)
        self._list_viewer.itemSwitching.connect(self._on_item_changing)
        self._list_viewer.itemSwitched.connect(self._on_item_changed)
        self._list_viewer.itemRemove.connect(self._unhook_item)

        self._list_viewer._btn_add.clicked.disconnect()
        self._list_viewer._btn_add.clicked.connect(self._on_add_item)

        self._close_event=False
        self._list_viewer.closed.connect(self._close)

        layout.addWidget(self._list_viewer, 1)

        for liw in self._list_viewer._item_widgets:
            self._hook_item(liw)

        self._list_viewer.updateGeometry()

        self._list_viewer.layout().activate()
        self._init_mode_transform()

    def _close(self):
        self._close_event=True
        self.close()

    def closeEvent(self, event):
        if not self._close_event:
            self._list_viewer.closed.emit()

    def _begin_sync(self):
        if self.__syncing:
            raise RuntimeError('已开始同步？')
        self.__syncing = True
        print('开始同步')
    def _end_sync(self):
        if not self.__syncing:
            raise RuntimeError('已停止同步？')
        self.__syncing = False
        print('停止同步')
    def _is_syncing(self):
        return self.__syncing

    def _init_mode_transform(self, mode=None):
        if mode is None:
            mode = self._list_viewer.view_mode
        self._end_sync()
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
        print('<-设置初始变换',mode)
        if mode == ListViewer.ViewMode.OVERLAP:
            self._overlap_transform = first_vt
        else:
            self._horizontal_transform = first_vt
        self._begin_sync()
        

    def _hook_item(self, liw):
        viewer = liw.content_widget
        if isinstance(viewer, FilterImageViewer):
            slot = partial(self._on_transform_changed, viewer)
            viewer._transform_slot = slot
            viewer.transformChanged.connect(slot)
    def _unhook_item(self, liw):
        print('脱钩',liw)
        viewer = liw.content_widget
        if isinstance(viewer, FilterImageViewer):
            slot = getattr(viewer, '_transform_slot', None)
            if slot is not None:
                viewer.transformChanged.disconnect(slot)
                del viewer._transform_slot

    def _calc_item_width(self, liw, item_h):
        overhead = 80
        content_h = item_h - overhead
        if content_h < 50:
            content_h = 50
        return int(content_h * self._aspect_ratio) + 8
    
    def _on_rebuilding(self):
        print("正在重建GUI，停止同步")
        self._end_sync()
    def _on_rebuilded(self):
        print("重建GUI完成，恢复同步")
        self._begin_sync()

    def _on_item_changing(self,liw):
        print('<-切换项开始，保存ViewMode.OVERLAP')
        self._overlap_transform = liw.content_widget.image_viewer.export_view_transform()
        pass

    def _on_item_changed(self,liw):
        print('->切换项完成，读取ViewMode.OVERLAP')
        if liw is not None:
            liw.content_widget.image_viewer.import_view_transform(self._overlap_transform)
        pass

    def _on_view_mode_changing(self, mode):
        print('模式切换开始',mode)
        if mode == ListViewer.ViewMode.OVERLAP:
            print('<-保存ViewMode.HORIZONTAL')
            self._horizontal_transform=self._list_viewer.current_item.content_widget.image_viewer.export_view_transform()
        else:
            print('<-保存ViewMode.OVERLAP')
            self._overlap_transform =self._list_viewer.current_item.content_widget.image_viewer.export_view_transform()

    def _on_view_mode_changed(self, mode):
        print('模式切换完成',mode)
        self._restore_mode_transform()

    def _restore_mode_transform(self):
        mode = self._list_viewer.view_mode
        print('->读取变换',mode)
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
        
        
        self._sync_all_to(vt)
        
    def _on_transform_changed(self, viewer):
        if not self._is_syncing():
            return
        if self._list_viewer.view_mode == ListViewer.ViewMode.OVERLAP:
            #实时同步仅在横向模式启用
            return
        vt = viewer.image_viewer.export_view_transform()
        print('<-保存变换',self._list_viewer.view_mode,viewer)
        self._horizontal_transform = vt

        self._sync_all_to(vt, exclude=viewer)

    def _sync_all_to(self, vt: ViewTransform, exclude=None):
        self._end_sync()
        print('->同步变换到其他控件',self._list_viewer.view_mode)
        for liw in self._list_viewer._item_widgets:
            v = liw.content_widget
            if isinstance(v, FilterImageViewer) and v is not exclude:
                v.image_viewer.import_view_transform(vt)
        self._begin_sync()


    def _on_add_item(self):
        print('开始添加元素')
        viewer = FilterImageViewer(QPixmap(self._input_pixmap))
        liw = self._list_viewer.add_item(viewer)
        self._hook_item(liw)
        self._end_sync()
        if self._list_viewer.view_mode == ListViewer.ViewMode.OVERLAP:
            if self._overlap_transform is not None:
                viewer.image_viewer.import_view_transform(self._overlap_transform)
        elif self._horizontal_transform is not None:
            viewer.image_viewer.import_view_transform(self._horizontal_transform)
        self._begin_sync()

def run_demo():
    import sys
    import os
    from pathlib import Path

    if __package__ is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap
    from colorPickerPro.filter_lib import ImageFilter

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(script_dir, os.pardir, "示例图.png"),
        os.path.join(script_dir, os.pardir, "示例图2.png"),
    ]
    pixmaps = []
    for p in paths:
        if os.path.exists(p):
            pixmaps.append(QPixmap(p))

    if not pixmaps:
        print("警告：未找到示例图片，使用空画布")
        pixmaps.append(QPixmap())

    filter_names = ['正片叠底']

    window = ImageFilterCompareWindow(pixmaps[0], filter_names)
    window.setWindowTitle("图像滤镜对比演示")
    window.resize(1100, 700)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_demo()

