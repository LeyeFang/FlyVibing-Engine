"""
Application.Editor.UI.controllers — 编辑器控制器层。

导出所有控制器和节点编辑器核心类型。

使用惰性导入: 仅 node_editor 子包在 import 时立即加载 (供验证器等轻量使用)，
其余控制器按需加载，避免在无 numpy/OpenGL 环境下导入失败。
"""

# ── 这些总是安全的 (纯 Python, 无渲染/硬件依赖) ──
from Application.Editor.UI.controllers.node_editor import NodeCanvas, _TYPES


def __getattr__(name: str):
    """惰性导入 — 仅在首次访问时加载重控制器。"""
    _LAZY = {
        "SimulationController":   "Application.Editor.UI.controllers.SimulationController",
        "SceneBrowserController":  "Application.Editor.UI.controllers.SceneBrowserController",
        "ResourceBrowserController": "Application.Editor.UI.controllers.ResourceBrowserController",
        "SelectionController":     "Application.Editor.UI.controllers.SelectionController",
    }
    if name in _LAZY:
        import importlib
        mod = importlib.import_module(_LAZY[name])
        attr = getattr(mod, name)
        # 缓存到模块全局，避免重复 import
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SimulationController",
    "SceneBrowserController",
    "ResourceBrowserController",
    "NodeCanvas",
    "_TYPES",
    "SelectionController",
]
