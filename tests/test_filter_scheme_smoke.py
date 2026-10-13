"""滤镜方案（FilterScheme）冒烟测试。

不依赖真实显示器：Qt 使用 offscreen 平台。
用法（项目根目录下）：

    .venv\\Scripts\\python.exe tests\\test_filter_scheme_smoke.py

覆盖：滤镜注册与查找、参数序列化往返、多图层顺序处理、灰度→三通道归一化、
图层增删改排序、方案 JSON 保存/读取、以及各界面控件的构建与交互回调。
"""

import os
import sys
import atexit
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from colorPickerPro.filter_lib import (
    ImageFilter, ImageConvert, BoolParam, ColorParam, FilterParam,
)
from colorPickerPro.filter_scheme import (
    FilterScheme, FilterLayer, FilterSchemeStore,
    filter_class_by_name, get_scheme_store, set_scheme_store,
)

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name)


def main():
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841

    # ---------- 1. 滤镜注册 ----------
    classes = ImageFilter.all_filters()
    check("滤镜已注册", len(classes) >= 5)

    edge = filter_class_by_name("边缘检测")
    check("按显示名查找滤镜", edge is not None and edge.__name__ == "EdgeDetectFilter")
    check("按类名查找滤镜", filter_class_by_name("EdgeDetectFilter") is edge)
    check("未知名称返回 None", filter_class_by_name("不存在的滤镜") is None)

    # ---------- 2. 用单个滤镜构造方案 ----------
    scheme = FilterScheme.single(edge)
    check("单滤镜方案名称", scheme.name == "边缘检测")
    check("单滤镜方案图层数", len(scheme.layers) == 1)
    check("方案展示名", scheme.display_name() == "边缘检测")
    check("空方案展示名", FilterScheme().display_name() == "(无滤镜)")

    # ---------- 3. RangeParam 往返 ----------
    param = scheme.layers[0].filter.exposed_parameters()[0]
    param.low, param.high = 11, 222
    restored = FilterScheme.from_dict(scheme.to_dict())
    p2 = restored.layers[0].filter.exposed_parameters()[0]
    check("范围参数序列化往返", p2.low == 11 and p2.high == 222)

    # ---------- 4. 布尔 / 颜色 / 数值参数往返 ----------
    detail = FilterScheme.single(filter_class_by_name("信息量分析"))
    params = detail.layers[0].filter.exposed_parameters()
    b_param = [p for p in params if isinstance(p, BoolParam)][0]
    c_param = [p for p in params if isinstance(p, ColorParam)][0]
    f_param = [p for p in params if isinstance(p, FilterParam)][0]
    b_param.value = False
    c_param.value = (9, 8, 7)
    f_param.value = 0.25

    detail2 = FilterScheme.from_dict(detail.to_dict())
    params2 = detail2.layers[0].filter.exposed_parameters()
    check("布尔参数序列化往返",
          [p for p in params2 if isinstance(p, BoolParam)][0].value is False)
    check("颜色参数序列化往返",
          tuple([p for p in params2 if isinstance(p, ColorParam)][0].value) == (9, 8, 7))
    check("数值参数序列化往返",
          abs([p for p in params2 if isinstance(p, FilterParam)][0].value - 0.25) < 1e-6)

    # ---------- 5. 图层堆叠处理 ----------
    rng = np.random.default_rng(1234)
    img = rng.integers(0, 256, (32, 48, 3), dtype=np.uint8)

    gray_cls = filter_class_by_name("RGB灰度")
    mult_cls = filter_class_by_name("正片叠底")
    inv_cls = filter_class_by_name("颜色反转")

    check("单灰度滤镜输出 2D",
          FilterScheme.single(gray_cls).process(img).shape == (32, 48))

    stack = FilterScheme("堆叠", [FilterLayer.create(gray_cls),
                                  FilterLayer.create(mult_cls)])
    out = stack.process(img)
    check("灰度→彩色堆叠后仍为 3 通道",
          out.shape == (32, 48, 3) and out.dtype == np.uint8)

    check("空方案原样返回", FilterScheme().process(img).shape == (32, 48, 3))

    disabled = FilterScheme("禁用", [FilterLayer.create(inv_cls, False)])
    check("禁用图层被跳过", np.array_equal(disabled.process(img), img))

    a = FilterScheme("a", [FilterLayer.create(inv_cls), FilterLayer.create(mult_cls)])
    b = FilterScheme("b", [FilterLayer.create(mult_cls), FilterLayer.create(inv_cls)])
    check("图层顺序影响结果", not np.array_equal(a.process(img), b.process(img)))

    # ---------- 6. 图层编辑 ----------
    edit = FilterScheme("编辑")
    edit.add_filter(inv_cls)
    edit.add_filter(gray_cls)
    edit.add_filter(edge, 0)
    check("指定位置插入",
          [l.name for l in edit.layers] == ["边缘检测", "颜色反转", "RGB灰度"])
    check("上移/下移", edit.move_layer(0, 1) == 1
          and [l.name for l in edit.layers][0] == "颜色反转")
    check("边界外移动不变", edit.move_layer(0, -1) == 0)
    check("复制图层", edit.duplicate_layer(0) is not None and len(edit.layers) == 4)
    check("删除图层", edit.remove_layer(0) is not None and len(edit.layers) == 3)

    clone = edit.clone()
    check("克隆是深拷贝", clone.layers[0].filter is not edit.layers[0].filter
          and clone.layers[0].name == edit.layers[0].name)
    clone.layers[0].enabled = False
    check("克隆修改不影响原方案", edit.layers[0].enabled is True)

    # ---------- 7. 方案仓库 ----------
    tmp = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)  # 中途异常也不留垃圾
    path = os.path.join(tmp, "sub", "schemes.json")
    store = FilterSchemeStore(path)
    check("新仓库为空", len(store) == 0)
    check("加入方案", store.add(edit) is True and store.names() == ["编辑"])
    check("保存到文件", store.save() and os.path.isfile(path))
    check("无名字方案拒绝保存", store.add(FilterScheme("")) is False)

    store2 = FilterSchemeStore(path)
    check("重新读取方案名", store2.names() == ["编辑"])
    check("重新读取图层", [l.name for l in store2.get("编辑").layers]
          == [l.name for l in edit.layers])
    check("覆盖保存", store2.add(FilterScheme("编辑", [FilterLayer.create(inv_cls)]))
          and len(store2.get("编辑").layers) == 1)
    check("删除方案", store2.remove("编辑") is True and len(store2) == 0)

    bad_path = os.path.join(tmp, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as fp:
        fp.write("not a json")
    check("损坏文件不崩溃", len(FilterSchemeStore(bad_path)) == 0)

    saved_global = get_scheme_store()
    set_scheme_store(store)
    check("全局仓库可替换", get_scheme_store() is store)
    set_scheme_store(saved_global)

    # 默认存储位置必须真实可写（回归：WinError 5 无法在用户主目录建目录）
    from colorPickerPro.filter_scheme import (
        _writable_dir, candidate_scheme_dirs, default_scheme_path,
    )
    check("候选存储目录非空", len(candidate_scheme_dirs()) >= 2)
    check("默认存储目录可写", _writable_dir(os.path.dirname(default_scheme_path())))

    blocker = os.path.join(tmp, "blocker")
    with open(blocker, "w", encoding="utf-8") as fp:
        fp.write("x")
    failing = FilterSchemeStore(os.path.join(tmp, "ok.json"))
    failing.add(FilterScheme("测试", [FilterLayer.create(inv_cls)]))
    failing.set_path(os.path.join(blocker, "sub", "schemes.json"))
    check("不可写路径返回 False 并记录原因",
          failing.save() is False and bool(failing.last_error))
    check("save_as 可切换到可写位置",
          failing.save_as(os.path.join(tmp, "sub2", "s.json")) is True)

    # ---------- 8. 界面控件 ----------
    ui_store = FilterSchemeStore(os.path.join(tmp, "ui.json"))
    ui_store.add(FilterScheme("测试方案", [FilterLayer.create(inv_cls)]))
    ui_store.save()

    from colorPickerPro.filter_scheme_panel import FilterSchemePanel
    from colorPickerPro.filter_scheme_selector import (
        FilterSchemeSelectorWidget, FilterSchemeSelectorDialog,
    )
    from colorPickerPro.filter_image_viewer import FilterImageViewer

    panel = FilterSchemePanel(FilterScheme.single(filter_class_by_name("信息量分析")),
                              store=ui_store)
    check("管理面板构建", panel.scheme is not None and panel._layer_list.count() == 1)
    check("参数区已生成", len(panel._params_widget.params()) == 8)

    panel._add_filter(inv_cls)
    check("面板添加滤镜", [l.name for l in panel.scheme.layers] == ["信息量分析", "颜色反转"])
    panel._on_move(-1)
    check("面板上移", panel.scheme.layers[0].name == "颜色反转")
    panel._on_duplicate()
    check("面板复制图层", len(panel.scheme.layers) == 3)
    panel._on_remove()
    check("面板删除图层", len(panel.scheme.layers) == 2)

    panel._layer_list.setCurrentRow(1)
    check("选中图层切换参数区",
          panel._params_widget.params() == panel.scheme.layers[1].filter.exposed_parameters()
          and len(panel._params_widget.params()) == 8)
    panel._layer_list.item(0).setCheckState(Qt.Unchecked)
    check("勾选框同步启用状态", panel.scheme.layers[0].enabled is False)

    # ---------- 8b. 方案名“未保存修改”标记 ----------
    lp = FilterSchemePanel(FilterScheme.single(filter_class_by_name("正片叠底")),
                           store=ui_store)
    check("初始无修改标记", lp.is_dirty() is False and lp._name_lbl.text() == "[正片叠底]")
    lp._add_filter(inv_cls)
    check("添加图层后显示 *", lp.is_dirty() is True and lp._name_lbl.text() == "[正片叠底*]")
    lp._on_remove()
    check("撤销修改后 * 消失", lp.is_dirty() is False and lp._name_lbl.text() == "[正片叠底]")
    lp._params_widget.params()[0].value = (10, 20, 30)
    lp._params_widget._emit_changed()
    check("参数变化后显示 *", lp.is_dirty() is True and lp._name_lbl.text() == "[正片叠底*]")
    lp._layer_list.item(0).setCheckState(Qt.Unchecked)
    check("停用图层后仍显示 *", lp.is_dirty() is True and "*" in lp._name_lbl.text())

    save_store = FilterSchemeStore(os.path.join(tmp, "panel_save.json"))
    sp = FilterSchemePanel(FilterScheme("待保存方案", [FilterLayer.create(inv_cls)]),
                           store=save_store)
    sp._add_filter(gray_cls)
    check("保存前有 *", sp.is_dirty() is True and sp._name_lbl.text() == "[待保存方案*]")

    import colorPickerPro.filter_scheme_panel as panel_mod

    real_input_dialog = panel_mod.QInputDialog

    class _FakeInputDialog:
        @staticmethod
        def getText(*args, **kwargs):
            return ("自动保存方案", True)

    panel_mod.QInputDialog = _FakeInputDialog
    try:
        sp._on_save()
    finally:
        panel_mod.QInputDialog = real_input_dialog
    check("保存后 * 消失", sp.is_dirty() is False and sp._name_lbl.text() == "[自动保存方案]")
    check("保存后可读回", save_store.names() == ["自动保存方案"]
          and len(save_store.get("自动保存方案").layers) == 2)
    sp.set_scheme(FilterScheme("换一个", [FilterLayer.create(inv_cls)]))
    check("set_scheme 重置修改标记", sp.is_dirty() is False and sp._name_lbl.text() == "[换一个]")

    # ---------- 8c. 加载方案后宿主必须改用新方案渲染 ----------
    import colorPickerPro.filter_scheme_panel as panel_mod
    from colorPickerPro.screenFilter import ScreenFilterWindow

    load_store = FilterSchemeStore(os.path.join(tmp, "load.json"))
    load_store.add(FilterScheme("反色方案", [FilterLayer.create(inv_cls)]))
    load_store.add(FilterScheme("灰度方案", [FilterLayer.create(gray_cls)]))
    load_store.save()

    class _FakeListDialog:
        Accepted = 1

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1

        def get_selected_indices(self):
            return [0]

    real_list_dialog = panel_mod.ListSelectionDialog

    def pixmap_array(pm):
        if pm is None or pm.isNull():
            return None
        return ImageConvert.pixmap_to_numpy(pm)

    frame = rng.integers(40, 200, (24, 32, 3), dtype=np.uint8)
    small = QPixmap(24, 16)
    small.fill()

    saved_global_store = get_scheme_store()
    set_scheme_store(load_store)
    panel_mod.ListSelectionDialog = _FakeListDialog
    try:
        # 屏幕滤镜窗口
        win = ScreenFilterWindow(FilterScheme.single(mult_cls))
        win.show()
        win._frozen_raw = frame.copy()
        win._reprocess()
        before = pixmap_array(win._content.pixmap())

        win._toggle_scheme_panel()
        win_panel = win._scheme_panel
        win_panel._on_load()

        check("面板换成了加载的方案", win_panel.scheme.name == "反色方案")
        check("窗口改用加载后的方案",
              win.current_scheme is win_panel.scheme
              and win.current_filter is not None
              and win.current_filter.name() == "颜色反转")
        win._reprocess()
        after = pixmap_array(win._content.pixmap())
        check("窗口渲染结果随加载方案改变",
              before is not None and after is not None
              and not np.array_equal(before, after))
        check("窗口渲染结果就是加载方案的效果",
              after is not None
              and np.array_equal(after.astype(int), 255 - frame.astype(int)))

        # 灰度结果也必须能正常显示（不能变成黑屏）
        win.set_scheme(FilterScheme("灰度链", [FilterLayer.create(gray_cls)]))
        win._reprocess()
        gray_pm = pixmap_array(win._content.pixmap())
        check("屏幕滤镜窗口能显示灰度结果",
              gray_pm is not None and float(gray_pm.mean()) > 1.0)

        # 空方案/全禁用：应回退为原始画面，而不是黑屏
        win.set_scheme(FilterScheme("全禁用", [FilterLayer.create(inv_cls, False)]))
        win._reprocess()
        raw_pm = pixmap_array(win._content.pixmap())
        check("图层全禁用时显示原始画面",
              raw_pm is not None
              and np.array_equal(raw_pm.astype(int), frame.astype(int)))

        win._toggle_scheme_panel()
        win.close()

        # 图像查看器
        viewer2 = FilterImageViewer(small)
        viewer2.set_scheme(FilterScheme.single(mult_cls))
        viewer2._reprocess()
        view_before = pixmap_array(viewer2.image_viewer._pixmap)
        viewer2._toggle_params_panel()
        vpanel = viewer2._param_panel
        vpanel._on_load()

        check("查看器改用加载后的方案",
              viewer2.current_scheme() is vpanel.scheme
              and viewer2.current_scheme().name == "反色方案")
        viewer2._reprocess()
        view_after = pixmap_array(viewer2.image_viewer._pixmap)
        check("查看器渲染结果随加载方案改变",
              view_before is not None and view_after is not None
              and not np.array_equal(view_before, view_after))

        # ---------- 8d. 关掉面板不能丢掉最后一次修改 ----------
        viewer2.set_scheme(FilterScheme.single(mult_cls))
        viewer2._reprocess()
        viewer2._toggle_params_panel()
        mult_before = pixmap_array(viewer2.image_viewer._pixmap).astype(int)
        viewer2._param_panel._params_widget.params()[0].value = (16, 16, 16)
        viewer2._param_panel._params_widget._emit_changed()
        viewer2._toggle_params_panel()   # 防抖还没到就关掉面板
        mult_after = pixmap_array(viewer2.image_viewer._pixmap).astype(int)
        check("关闭面板时立即补渲染最后一次修改",
              not np.array_equal(mult_before, mult_after))
    finally:
        panel_mod.ListSelectionDialog = real_list_dialog
        set_scheme_store(saved_global_store)

    # ---------- 8e. 反复开关面板不能丢掉未保存标记 ----------
    win2 = ScreenFilterWindow(FilterScheme.single(mult_cls))
    win2._toggle_scheme_panel()
    win_panel2 = win2._scheme_panel
    win_panel2._add_filter(inv_cls)
    check("编辑后出现未保存标记",
          win_panel2.is_dirty() is True and "*" in win_panel2._name_lbl.text())
    win_panel2._layer_list.setCurrentRow(0)
    picked_row = win_panel2._layer_list.currentRow()

    win2._toggle_scheme_panel()          # 关
    win2._toggle_scheme_panel()          # 再开
    check("重开还是同一个面板与同一个方案",
          win2._scheme_panel is win_panel2 and win_panel2.scheme is win2.current_scheme)
    check("重开后保留未保存标记",
          win_panel2.is_dirty() is True and "*" in win_panel2._name_lbl.text())
    check("重开后保留选中的图层", win_panel2._layer_list.currentRow() == picked_row)
    check("重开后保留已编辑的内容",
          [l.name for l in win_panel2.scheme.layers] == ["正片叠底", "颜色反转"])
    win2.close()

    small2 = QPixmap(24, 16)
    small2.fill()
    viewer3 = FilterImageViewer(small2)
    viewer3.set_scheme(FilterScheme.single(mult_cls))
    viewer3._toggle_params_panel()
    vpanel3 = viewer3._param_panel
    vpanel3._add_filter(inv_cls)
    viewer3._toggle_params_panel()
    viewer3._toggle_params_panel()
    check("查看器重开面板保留未保存标记",
          viewer3._param_panel is vpanel3 and vpanel3.is_dirty() is True
          and "*" in vpanel3._name_lbl.text())

    selector = FilterSchemeSelectorWidget(store=ui_store)
    check("选择器列出滤镜", selector._filter_list.count() == len(ImageFilter.all_filters()))
    check("选择器列出方案", selector._scheme_list.count() == 1)
    check("默认选中第一个滤镜", selector.current_scheme() is not None
          and selector.current_scheme().name == ImageFilter.all_filters()[0].name())
    selector._scheme_list.setCurrentRow(0)
    check("方案列表当前行信号生效", selector._active == "scheme")
    selector._on_item_picked(selector._scheme_list)
    check("选中已保存方案", selector.current_scheme() is not None
          and selector.current_scheme().name == "测试方案")
    selector._filter_list.setCurrentRow(1)
    check("滤镜列表当前行信号生效", selector._active == "filter")

    selector_multi = FilterSchemeSelectorWidget(multi_select=True, store=ui_store)
    selector_multi._filter_list.item(0).setSelected(True)
    selector_multi._scheme_list.item(0).setSelected(True)
    check("多选返回滤镜+方案", len(selector_multi.selected_schemes()) == 2)

    dlg = FilterSchemeSelectorDialog(None, "测试", store=ui_store)
    check("选择弹窗构建", dlg.current_scheme() is not None)

    pm = QPixmap(24, 16)
    pm.fill()
    viewer = FilterImageViewer(pm)
    viewer.refresh_schemes()
    check("查看器方案下拉框", viewer._scheme_combo.count() == 1 + len(get_scheme_store().names()))
    viewer.set_filter_by_name("边缘检测")
    check("查看器滤镜→方案", viewer.current_scheme() is not None
          and viewer.current_scheme().name == "边缘检测")
    viewer._reprocess()
    check("查看器处理无异常", not viewer.image_viewer._pixmap.isNull())

    viewer.set_scheme(FilterScheme("两图层", [FilterLayer.create(inv_cls),
                                              FilterLayer.create(gray_cls)]))
    viewer._reprocess()
    check("查看器多图层处理无异常", not viewer.image_viewer._pixmap.isNull())

    viewer.set_scheme(None)
    check("查看器清空方案", viewer.current_scheme() is None)

    # 对比窗口（构建即可，不做真实显示）
    from colorPickerPro.image_filter_compare import ImageFilterCompareWindow
    try:
        cmp_win = ImageFilterCompareWindow(pm, [FilterScheme.single(inv_cls), "边缘检测"])
        check("对比窗口构建", cmp_win._list_viewer.current_index >= 0)
        cmp_win.close()
    except Exception as ex:  # pragma: no cover - 仅作信息提示
        print("INFO  对比窗口构建未通过:", ex)

    shutil.rmtree(tmp, ignore_errors=True)

    fails = [name for name, ok in RESULTS if not ok]
    print("\n共 %d 项检查，失败 %d 项" % (len(RESULTS), len(fails)))
    for name in fails:
        print("FAILED:", name)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
