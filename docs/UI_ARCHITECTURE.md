# pixnex UI 架构与改造规范

本文档是 GUI 开发的唯一约定。所有窗口、对话框、控件的写法必须与本文一致。

## 1. 目标

1. **统一外观**：所有顶层窗口都是自绘无边框窗口（自绘标题栏、1px 方角边框），不使用系统标题栏；一套设计令牌 + 一份全局 QSS。主窗口不提供最大化，改为「置顶」按钮。
   全局采用尖角（直角）外观：`RADIUS.sm/md/lg/xl` 全部为 0，卡片、按钮、输入框、菜单、标签、滚动条与自绘面板都不得出现圆角。
2. **图标资产化**：所有图标使用 SVG 资产，禁止字符图标/emoji。
3. **布局自适应**：只用 Qt 布局管理器；窗口缩放、DPI 缩放时不越界/重叠/裁切；间距保持紧凑（页边距 8、卡片间距 6）。
4. **单一职责 + 组合复用**：基础控件在 `colorPickerPro/ui/components/`，业务窗口只做组合。
5. **文案简洁**：界面文字短、正式，不使用口语化长句；不显示色彩模型说明。

## 2. 目录与分层

```
colorPickerPro/ui/
    tokens.py         设计令牌：Palette / SPACE / RADIUS / SIZE / TYPE / Role / State / Variant
    stylesheet.py     由令牌生成全局 QSS（唯一允许写选择器的地方）
    theme.py          apply_theme(app)：Fusion + 调色板 + 字体 + 中文翻译 + 全局 QSS
    icons.py          SVG 图标查找（icon/icon_names/icon_pixmap）
    app_icon.py       应用图标 QIcon（根目录 icon.svg 生成的 pixnex.ico，窗口/任务栏/标题栏共用）
    assets/icons/*.svg 全部界面图标（由 tools/gen_ui_assets.py 生成）
    components/      可复用控件
```

依赖单向：`ui` 不 import 业务模块；业务模块可以 import `ui`。

启动方式（`main.py::main()` 或任何 `run_demo()`）：

```python
from colorPickerPro.ui import configure_application, apply_theme

configure_application()          # 必须在 QApplication 创建前
app = QApplication(sys.argv)
apply_theme(app)                 # 必须在任何窗口创建前
```

## 3. 铁律

1. 禁止业务代码 `setStyleSheet`；样式只存在于 `ui/stylesheet.py`。数据颜色用 `ColorSwatch` / 自绘控件。
2. 禁止硬编码颜色/字号；使用 `tokens.qcolor(...)` 或组件。
3. 禁止字符图标：`✕ ─ ▶ ⏸ ⚙ ↔ ↕ ↻ ＋` 等一律改用 `IconButton("svg名")` / `set_icon("svg名")`；
   新增图标先加 SVG 到 `assets/icons/` 并在 `tools/gen_ui_assets.py` 登记。
4. 普通内容控件禁止 `setFixedSize/Width/Height`。允许的例外：图标按钮（28×28）、标题栏应用图标（16×16）、分隔线、标题栏高度、图形取色器高度。
5. 长文本必须可换行或省略（`SubtitleLabel(word_wrap=True)` / `ElidedLabel`）。
6. 内容超出高度用 `ScrollArea`，横向工具栏用 `FlowLayout` 自动换行，分栏用 `QSplitter`。
7. 所有顶层窗口必须 frameless：`FramelessWindowMixin` + `TitleBar`（见 §5），不得回到系统标题栏。
8. 标准文件选择必须用 `ui.components.get_open_file_name/get_save_file_name`；标准消息/输入框必须用
   `ui.components.confirm/alert/prompt_text`（都是自绘无框窗口）。
9. 文案保持简短、正式；一个说明不超过一行，tooltip 尽量 ≤ 14 个汉字；不要展示色彩模型说明。
10. 注释与 UI 文案使用中文；不保留行为之外的 emoji 或装饰字符。
11. 逻辑/信号/数据流保持原样：只改表现层与布局。
12. 每个改动文件必须可导入，并能用 `tools/render_widget.py` 多尺寸渲染无异常。

## 4. 组件速查

导入：`from colorPickerPro.ui.components import ...`

| 组件 | 用途 |
|---|---|
| `TitleLabel` / `DisplayLabel` | 页面内标题（窗口标题在 TitleBar 里） |
| `SubtitleLabel` / `CaptionLabel` / `HintLabel` | 说明文字（可换行） |
| `SectionTitle` / `FieldLabel` / `ValueLabel` / `MonoLabel` | 小节标题 / 表单标签 / 数值 / 等宽数值 |
| `StatusLabel` | 状态文字：`set_message(text, State.SUCCESS)`；长解释用 `set_message(短标签, state, detail=长说明)`（detail 进 tooltip，不撑宽标签） |
| `ElidedLabel` | 单行、自动省略号 |
| `PrimaryButton` / `SecondaryButton` | 主操作 / 次要操作 |
| `DangerButton` / `GhostButton` | 危险操作 / 轻量操作 |
| `IconButton("close")` | 28×28 SVG 图标按钮（close/minimize/maximize/restore/play/pause/settings/add/refresh/flip-h/flip-v） |
| `MenuButton` / `BaseButton.set_icon(name)` | 带菜单的按钮 / 文本按钮加图标 |
| `Card(title)` | 方角面板：`add` / `add_layout` / `add_header_widget` |
| `Divider` / `ColorSwatch` / `Badge` | 分隔线 / 颜色块 / 方角标签 |
| `hbox` / `vbox` / `flow` | 布局构造器（`None` 表示 stretch） |
| `ScrollArea` / `FlowLayout` | 滚动区 / 自动换行布局 |
| `ThemedDialog` | 无边框对话框外壳（标题栏 / body / footer / 可滚动 body） |
| `MessageDialog` / `TextInputDialog` / `confirm` / `alert` / `prompt_text` | 自绘消息框与输入框 |
| `FileDialog` / `get_open_file_name` / `get_save_file_name` | 自绘无边框文件选择（内嵌 QFileDialog） |
| `FramelessWindowMixin` / `TitleBar` | 任意顶层窗口的自绘标题栏、缩放、拖动、窗口按钮 |

示例：

```python
class MyDialog(ThemedDialog):
    def __init__(self, parent=None):
        super().__init__("标题", "说明", parent)
        self.make_body_scrollable()
        self.add_content(some_widget)
        self.add_reject_button()
        self.add_accept_button()
        self.resize(520, 420)
```

## 5. 自定义窗口（必读）

所有顶层窗口由 `FramelessWindowMixin` 提供：
- 自绘 `TitleBar`（拖动、双击最大化/折叠、最小化/最大化/关闭按钮，图标来自 SVG）；
- 1px 方角边框（不做圆角）；
- 四边/四角缩放：应用级事件过滤器统一处理按下/移动/释放，缩放期间 grabMouse，任意子控件上都可拖动；光标自动切换；
- 最大化窗口拖动：先 `showNormal()` 还原，再按光标在标题栏中的相对位置摆放窗口，避免还原后与光标错位；
- 置顶：Windows 下用原生 `SetWindowPos(HWND_TOPMOST)`，不使用会重建窗口的 `setWindowFlag`，避免闪烁；
- 右下角 `QSizeGrip`；
- 弹窗显示时前置（`raise + activate`）；父窗口置顶时弹窗自动继承置顶；
- 关闭时移除全局事件过滤器，`showEvent` 里按需重新安装：窗口关掉后再打开
  （例如复用的滤镜方案面板）仍可拖边缩放、缩放光标仍正常。

主窗口额外约定：标题栏有「自动折叠 / 置顶（图钉）/ 最小化 / 关闭」，没有最大化；
置顶切换 `WindowStaysOnTopHint`；自动折叠开启后，鼠标离开主窗口区域需持续约 1 秒
才折叠成一条标题栏（1 秒内回到窗口则不折叠），移入标题栏立即展开（折叠高度 =
标题栏 30 + 上下边框 2）。主窗口通过 `window_state.WindowStateStore` 保存自动折叠、
置顶与窗口位置尺寸：`main()` 注入 `WindowStateStore.persistent()`（INI 文件），
测试/预览用默认的内存存储。对话框标题栏只有关闭按钮。

屏幕滤镜窗口（`ScreenFilterWindow`）同样有「自动折叠」标题栏按钮：鼠标离开窗口
超过约 1 秒才收起为标题栏（1 秒内返回不折叠）、移入标题栏立即展开；双击标题栏 /
空格键等手动折叠或展开会同时关闭自动折叠（手动操作优先）。图像区域左键单击或
**按住拖动**会连续取「显示图像」在该处的像素颜色，通过 `colorPicked(r, g, b)` 信号
交给调用方（主窗口据此更新当前颜色）；标题栏副标题短暂显示提示，文案由
`set_color_formatter()` 注入（主窗口传入当前颜色模型的 `format_srgb()`，如
`L-0.61 C-0.25 H-321.7`；未注入时退回 HEX）。窗口级轮询、离开延迟与「是否在拖拽 /
是否有模态弹窗」的判断在 `auto_collapse.py`，主窗口和屏幕滤镜窗口共用。

主窗口标题栏最左侧显示应用图标（`init_frameless(..., icon=app_icon())`）：
- 图标来自 `colorPickerPro/ui/app_icon.py`，实际文件是项目根的 `pixnex.ico`（由
  `tools/gen_app_icon.py` 生成，16–256 px 多尺寸），同一份文件也用于窗口/任务栏
  图标和打包后的 EXE 图标；
- 标题栏里是一个 16×16 的 `QLabel`（`objectName="TitleBarIcon"`）并设置了
  `WA_TransparentForMouseEvents`，不会抢走标题栏的拖动响应；
- 只有主窗口传 `icon`，其余窗口标题栏保持纯文字。

用法：

```python
class MyWindow(FramelessWindowMixin, QMainWindow):   # 或 QDialog / QWidget
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)   # 给边框留 1px
        outer.setSpacing(0)
        self.init_frameless(
            "窗口标题", layout=outer, subtitle="可选副标题",
            show_minimize=True, show_maximize=True, show_close=True,
            resizable=True, double_click="maximize")   # 或 "collapse" / None
        # 内容放入一个 objectName="FramelessBody" 的容器，再套正常 margins=16 的布局
```

- `ThemedDialog` 已经内置上述外壳，业务对话框直接继承即可，不要设置窗口 flags（会覆盖 frameless，除非显式 `| Qt.FramelessWindowHint`）。
- 屏幕滤镜窗口（`CustomFramelessWindow`）额外有折叠和 `content_rect_global()`。
- `TitleBar` 也可以通过 `window.title_bar` 访问（`set_title/set_subtitle/set_maximized`）。

### 5.1 布局与尺寸

- 主窗口/对话框 body 使用 `margins=8`，卡片间距 6（`SPACE` 令牌：xs=2/sm=4/md=6/lg=8/xl=12）；
- 卡片内边距 8；控件高度约 26-28；标题栏 30；
- 图形取色器：`Expanding/Fixed`，高度固定（主窗口 220 / 对话框 180），按 `min(宽,高)` 居中绘制；
- 主窗口内容放进 `ScrollArea`；对话框长内容用 `make_body_scrollable()`；
- 左右分栏用 `QSplitter`（禁用折叠、设置最小宽度）；
- 最小尺寸必须 ≥ `minimumSizeHint()`，不要设置 `setMaximumSize`。

## 6. 跨文件 API

| 提供方 | API | 使用方 |
|---|---|---|
| `FramelessWindowMixin` | `init_frameless(...)`、`title_bar`、`set_window_title/subtitle`、`set_border_color`、`toggle_maximize` | 全部顶层窗口 |
| `ThemedDialog` | `set_title/set_subtitle`、`add_content`、`make_body_scrollable`、footer 按钮 | 全部业务对话框 |
| `IconButton` | `IconButton("svg名")`、`set_icon("svg名")` | 所有图标按钮 |
| `customFrame.CustomFramelessWindow` | `content_rect_global()`、`add_title_bar_button()`、`toggle_collapse()`、`is_collapsed()` | `screenFilter` |
| `main.MainWindow` | `is_collapsed()`、`toggle_collapse()`；`MainWindow(state_store=...)` 可注入状态存储 | `main.py` / 测试 |
| `screenFilter.ScreenFilterWindow` | 信号 `colorPicked(r, g, b)`（图像区域单击/拖动连续取色）、`set_color_formatter(callable)`（提示文案）；自动折叠开关与 `toggle_collapse()` | `main.py` / 演示程序 |
| `window_state.WindowStateStore` | `load()` / `save(WindowState)` / `persistent()`；`WindowState(auto_collapse, always_on_top, geometry)` | `main.py` |
| `window_state.clamp_geometry` | 把恢复的窗口矩形夹进屏幕可用区域 | `main.py` / 测试 |
| `auto_collapse` | `mouse_button_pressed()`、`modal_or_popup_open()`、`CollapseDelay`（离开约 1 秒才折叠、回到窗口取消）、`AUTO_COLLAPSE_POLL_MS` / `AUTO_COLLAPSE_DELAY_MS` | `main.py` / `screenFilter.py` |
| `color_picker_widgets` | `set_model()` / `remove_listener()`；`BaseColorModel.format_srgb(r, g, b)` 按当前模型格式化颜色文本 | `main.py` / 取色对话框 / 屏幕滤镜取色提示 |

## 7. 自带验证

```powershell
.venv\Scripts\python.exe tools\gen_ui_assets.py          # 重新生成 SVG 图标
.venv\Scripts\python.exe tools\ui_gallery.py             # 组件库预览（自绘窗口）
.venv\Scripts\python.exe tools\render_widget.py          # 任意窗口多尺寸截图
.venv\Scripts\python.exe tests\ui_layout_check.py --dpi-pass 1.5
.venv\Scripts\python.exe tests\test_sync_udm_regression.py
.venv\Scripts\python.exe tests\test_window_state.py      # 自动折叠 + 窗口状态持久化
.venv\Scripts\python.exe tests\test_screen_filter_auto_collapse.py  # 屏幕滤镜自动折叠
.venv\Scripts\python.exe tests\test_screen_filter_pick_color.py      # 屏幕滤镜单击/拖动连续取色
.venv\Scripts\python.exe tests\test_frameless_resize.py              # 无边框窗口缩放（含关闭后重开）
.venv\Scripts\python.exe tests\test_image_drop.py        # 图像拖放：是否显示拖入图像
```

巡检断言：窗口均 frameless 且有 TitleBar、边框可见、边缘拖动缩放正确、
无字符图标、SVG 引用存在、无越界/裁切、静态无 `setStyleSheet`；截图在 `build/ui-shots/`。
主窗口 / 屏幕滤镜窗口自动折叠、屏幕滤镜左键取色、复用窗口重新显示后的缩放
冒烟检查也包含在 `tests/ui_layout_check.py`（`func:auto_collapse`、
`func:screen_filter_auto_collapse`、`func:screen_filter_pick_color`、
`func:frameless_resize_reopen`）。
颜色同步回归测试保证 UDM 后端保持延迟导入/懒加载（提前 import psutil 会让 UDM 拒绝内存访问）。
