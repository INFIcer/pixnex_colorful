"""
滤镜方案（FilterScheme）：滤镜的图层化堆叠
==========================================

- FilterLayer      单个滤镜图层（滤镜实例 + 启用开关）
- FilterScheme     滤镜方案（名称 + 有序图层列表），按图层顺序依次处理图像
- FilterSchemeStore 方案仓库，负责方案的序列化保存与读取

一个方案就是把若干滤镜像图层一样堆叠起来，处理时从第一层到最后一层依次
作用于图像，最终结果即为方案效果。方案可以随时序列化（JSON）保存，也可以
从已保存的方案还原。

方案文件默认位于 ~/.pixnex_colorful/filter_schemes.json，可用环境变量
PIXNEX_DATA_DIR 覆盖数据目录。

新增滤镜无需改动本模块：方案按滤镜类名（type(instance).__name__）与参数值
序列化，参数值通过参数对象的 value / low / high 通用读写（InfoParam 之类
只读回显参数不参与序列化）。
"""

import json
import os
from typing import List, Optional

import numpy as np

from .filter_lib import ImageFilter, InfoParam

SCHEME_FILE_VERSION = 1
SCHEME_FILE_NAME = "filter_schemes.json"


# ============================================================
# 通用工具
# ============================================================

def _num(value):
    """把数值整理成 JSON 友好的形式（整数值不带小数点）。"""
    if isinstance(value, bool):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else f


def ensure_bgr(img: np.ndarray) -> np.ndarray:
    """把单通道灰度图补齐为三通道 BGR，保证堆叠时下游滤镜仍可使用。"""
    if img is None:
        return img
    if img.ndim == 2:
        return np.repeat(img[:, :, None], 3, axis=2)
    if img.ndim == 3 and img.shape[2] == 1:
        return np.repeat(img, 3, axis=2)
    return img


def filter_class_by_name(name: str):
    """按类名或显示名查找滤镜类，找不到返回 None。"""
    if not name:
        return None
    for cls in ImageFilter.all_filters():
        if cls.__name__ == name or cls.name() == name:
            return cls
    return None


# ============================================================
# 参数 / 滤镜的序列化
# ============================================================

def param_to_state(param):
    """把一个参数对象转成可 JSON 化的状态；只读参数返回 None。"""
    if isinstance(param, InfoParam):
        return None
    if hasattr(param, "low") and hasattr(param, "high"):
        return {"low": _num(param.low), "high": _num(param.high)}
    value = getattr(param, "value", None)
    if isinstance(value, (tuple, list)):
        return {"value": [_num(v) for v in value]}
    if isinstance(value, bool):
        return {"value": bool(value)}
    if isinstance(value, (int, float)):
        return {"value": _num(value)}
    return {"value": value}


def apply_param_state(param, state):
    """把 param_to_state 的结果写回参数对象。"""
    if not state:
        return
    if ("low" in state and "high" in state
            and hasattr(param, "low") and hasattr(param, "high")):
        param.low = state["low"]
        param.high = state["high"]
        return
    if "value" not in state:
        return
    value = state["value"]
    current = getattr(param, "value", None)
    if isinstance(current, tuple) and isinstance(value, (list, tuple)):
        param.value = tuple(value)
    else:
        param.value = value


def filter_to_dict(filter_instance: ImageFilter) -> dict:
    """序列化一个滤镜实例（类型 + 参数值）。"""
    return {
        "type": type(filter_instance).__name__,
        "name": filter_instance.name(),
        "params": [param_to_state(p) for p in filter_instance.exposed_parameters()],
    }


def filter_from_dict(data: dict,
                     instance: Optional[ImageFilter] = None) -> ImageFilter:
    """从序列化数据还原滤镜实例（instance 非空时把参数写入该实例）。"""
    cls = filter_class_by_name(data.get("type") or data.get("name"))
    if cls is None:
        raise ValueError(f"未知滤镜类型: {data.get('type')!r}")
    fi = instance if instance is not None else cls()
    params = fi.exposed_parameters()
    states = data.get("params") or []
    for param, state in zip(params, states):
        apply_param_state(param, state)
    return fi


# ============================================================
# 滤镜图层
# ============================================================

class FilterLayer:
    """滤镜方案中的一个图层：一个滤镜实例 + 是否启用。"""

    def __init__(self, filter_instance: ImageFilter, enabled: bool = True):
        self.filter = filter_instance
        self.enabled = bool(enabled)

    @staticmethod
    def create(filter_cls, enabled: bool = True) -> "FilterLayer":
        return FilterLayer(filter_cls(), enabled)

    @property
    def name(self) -> str:
        return self.filter.name()

    def clone(self) -> "FilterLayer":
        return FilterLayer.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {"enabled": bool(self.enabled),
                "filter": filter_to_dict(self.filter)}

    @staticmethod
    def from_dict(data: dict) -> "FilterLayer":
        data = data or {}
        return FilterLayer(filter_from_dict(data.get("filter") or {}),
                           data.get("enabled", True))


# ============================================================
# 滤镜方案
# ============================================================

class FilterScheme:
    """滤镜方案：若干滤镜图层按顺序堆叠，依次处理得到最终效果。"""

    def __init__(self, name: str = "", layers: Optional[List[FilterLayer]] = None):
        self.name = name or ""
        self.layers: List[FilterLayer] = list(layers) if layers else []

    # ---------- 构造 ----------

    @staticmethod
    def from_filter(filter_instance: ImageFilter, name: str = "") -> "FilterScheme":
        """用单个滤镜实例构造方案。"""
        return FilterScheme(name or filter_instance.name(),
                            [FilterLayer(filter_instance)])

    @staticmethod
    def single(filter_cls, name: str = "") -> "FilterScheme":
        """用单个滤镜类构造方案。"""
        return FilterScheme.from_filter(filter_cls(), name)

    def clone(self, name: Optional[str] = None) -> "FilterScheme":
        return FilterScheme(self.name if name is None else name,
                            [layer.clone() for layer in self.layers])

    # ---------- 查询 ----------

    def display_name(self) -> str:
        if self.name:
            return self.name
        names = [layer.name for layer in self.active_layers()]
        return " → ".join(names) if names else "(无滤镜)"

    def active_layers(self) -> List[FilterLayer]:
        return [layer for layer in self.layers if layer.enabled]

    def is_empty(self) -> bool:
        return not self.active_layers()

    def filter_names(self) -> List[str]:
        return [layer.name for layer in self.layers]

    def exposed_parameters(self) -> list:
        """方案中所有图层的参数（按图层顺序）。"""
        params = []
        for layer in self.layers:
            params.extend(layer.filter.exposed_parameters())
        return params

    def has_params(self) -> bool:
        return any(layer.filter.exposed_parameters() for layer in self.layers)

    # ---------- 编辑 ----------

    def add_filter(self, filter_cls_or_instance, index: Optional[int] = None) -> FilterLayer:
        """添加一个滤镜图层，index 为空时追加到末尾。"""
        if isinstance(filter_cls_or_instance, type):
            layer = FilterLayer(filter_cls_or_instance())
        else:
            layer = FilterLayer(filter_cls_or_instance)
        return self.add_layer(layer, index)

    def add_layer(self, layer: FilterLayer,
                  index: Optional[int] = None) -> FilterLayer:
        if index is None or index < 0 or index >= len(self.layers):
            self.layers.append(layer)
        else:
            self.layers.insert(index, layer)
        return layer

    def remove_layer(self, index: int) -> Optional[FilterLayer]:
        if 0 <= index < len(self.layers):
            return self.layers.pop(index)
        return None

    def move_layer(self, index: int, delta: int) -> int:
        """把图层移动 delta 位（负数上移），返回新位置。"""
        new_index = index + delta
        if 0 <= index < len(self.layers) and 0 <= new_index < len(self.layers):
            self.layers.insert(new_index, self.layers.pop(index))
            return new_index
        return index

    def duplicate_layer(self, index: int) -> Optional[FilterLayer]:
        if not 0 <= index < len(self.layers):
            return None
        copy = self.layers[index].clone()
        self.layers.insert(index + 1, copy)
        return copy

    def clear(self):
        self.layers = []

    # ---------- 处理 ----------

    def process(self, img: np.ndarray) -> np.ndarray:
        """按图层顺序依次处理，返回最终效果。"""
        result = img
        for layer in self.layers:
            if not layer.enabled or layer.filter is None:
                continue
            result = layer.filter.process(ensure_bgr(result))
        return result

    # ---------- 序列化 ----------

    def to_dict(self) -> dict:
        return {"name": self.name,
                "layers": [layer.to_dict() for layer in self.layers]}

    @staticmethod
    def from_dict(data) -> "FilterScheme":
        data = data or {}
        layers = []
        for layer_data in (data.get("layers") or []):
            layers.append(FilterLayer.from_dict(layer_data))
        return FilterScheme(data.get("name") or "", layers)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_json(text: str) -> "FilterScheme":
        return FilterScheme.from_dict(json.loads(text))

    def state_signature(self) -> str:
        """内容签名：用于判断方案相对上次保存/加载是否有改动。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def to_scheme(obj) -> FilterScheme:
    """把 ImageFilter 子类 / 实例 / FilterScheme 统一转成 FilterScheme。"""
    if isinstance(obj, FilterScheme):
        return obj
    if isinstance(obj, ImageFilter):
        return FilterScheme.from_filter(obj)
    if isinstance(obj, type) and issubclass(obj, ImageFilter):
        return FilterScheme.single(obj)
    raise TypeError(f"{obj!r} 无法转换为滤镜方案")


# ============================================================
# 方案仓库（保存 / 读取）
# ============================================================

def _writable_dir(path: str) -> bool:
    """探测目录是否真的可写（建目录 + 写一个临时文件）。"""
    if not path:
        return False
    probe = os.path.join(path, ".pixnex_write_test")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as fp:
            fp.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def candidate_scheme_dirs() -> List[str]:
    """按优先级给出方案文件候选目录。

    某些 Windows 环境不允许在用户主目录根下新建文件夹（WinError 5），
    所以优先使用 %APPDATA% 这类标准可写位置，并逐个探测。
    """
    dirs = []
    env_dir = os.environ.get("PIXNEX_DATA_DIR")
    if env_dir:
        dirs.append(env_dir)
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "pixnex_colorful"))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        dirs.append(os.path.join(local_appdata, "pixnex_colorful"))
    dirs.append(os.path.join(os.path.expanduser("~"), ".pixnex_colorful"))
    # 兜底：项目目录 / 当前工作目录
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(project_dir, ".pixnex_colorful"))
    dirs.append(os.path.join(os.getcwd(), ".pixnex_colorful"))

    unique = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def default_scheme_path() -> str:
    """返回第一个可写的方案文件路径。"""
    for folder in candidate_scheme_dirs():
        if _writable_dir(folder):
            return os.path.join(folder, SCHEME_FILE_NAME)
    # 全都不行时也给出一个明确的路径，交给上层报错提示
    return os.path.join(os.path.expanduser("~"), ".pixnex_colorful", SCHEME_FILE_NAME)


class FilterSchemeStore:
    """滤镜方案仓库：负责一个 JSON 文件中所有方案的读写。"""

    def __init__(self, path: Optional[str] = None):
        self._path = path or default_scheme_path()
        self._schemes: List[FilterScheme] = []
        self.last_error: Optional[str] = None
        self.load()

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str, load: bool = False):
        """切换方案文件位置（可选立即读取该文件）。"""
        self._path = path
        self.last_error = None
        if load:
            self.load()

    def save_as(self, path: str) -> bool:
        self.set_path(path)
        return self.save()

    # ---------- 读写 ----------

    def load(self) -> bool:
        self._schemes = []
        if not os.path.isfile(self._path):
            return True
        try:
            with open(self._path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception as ex:  # 文件损坏 / 无权限：保留空仓库，不打断程序
            print(f"[FilterSchemeStore] 读取方案文件失败: {ex}")
            return False
        for scheme_data in (data.get("schemes") or []):
            try:
                self._schemes.append(FilterScheme.from_dict(scheme_data))
            except Exception as ex:
                print(f"[FilterSchemeStore] 跳过无法还原的方案: {ex}")
        return True

    def save(self) -> bool:
        self.last_error = None
        try:
            data = {
                "version": SCHEME_FILE_VERSION,
                "schemes": [scheme.to_dict() for scheme in self._schemes],
            }
            folder = os.path.dirname(self._path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return True
        except Exception as ex:
            self.last_error = f"{type(ex).__name__}: {ex}"
            print(f"[FilterSchemeStore] 保存方案文件失败: {self.last_error}")
            return False

    # ---------- 查询 ----------

    def names(self) -> List[str]:
        return [scheme.name for scheme in self._schemes]

    def schemes(self) -> List[FilterScheme]:
        return list(self._schemes)

    def get(self, name: str) -> Optional[FilterScheme]:
        for scheme in self._schemes:
            if scheme.name == name:
                return scheme
        return None

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    # ---------- 修改 ----------

    def add(self, scheme: FilterScheme, overwrite: bool = True) -> bool:
        """加入一个方案（会保存副本，避免与调用方共享对象）。"""
        if not scheme.name:
            return False
        stored = self.get(scheme.name)
        if stored is not None:
            if not overwrite:
                return False
            self._schemes[self._schemes.index(stored)] = scheme.clone()
            return True
        self._schemes.append(scheme.clone())
        return True

    def remove(self, name: str) -> bool:
        scheme = self.get(name)
        if scheme is None:
            return False
        self._schemes.remove(scheme)
        return True

    def __len__(self) -> int:
        return len(self._schemes)

    def __iter__(self):
        return iter(self._schemes)


_STORE: Optional[FilterSchemeStore] = None


def get_scheme_store() -> FilterSchemeStore:
    """全局方案仓库（各处界面共用，保证保存/删除立即互相可见）。"""
    global _STORE
    if _STORE is None:
        _STORE = FilterSchemeStore()
    return _STORE


def set_scheme_store(store: Optional[FilterSchemeStore]):
    global _STORE
    _STORE = store
