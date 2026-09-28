"""
[DEPRECATED / 搬迁 shim] 节点图运行时已迁至 `Application.Core.NodeGraph`。

本文件仅为向后兼容的 re-export（包级名称）:
    from Application.Core.NodeGraph import NodeCanvas, _TYPES, ...   ← 新代码请用新路径

深路径导入（canvas / evaluator_engine / node_types / evaluators /
graph_constraints / component_registry）请直接改用 `Application.Core.NodeGraph.<模块>`。
"""

from Application.Core.NodeGraph import *  # noqa: F401,F403
from Application.Core.NodeGraph import __all__ as _new_all  # noqa: F401

__all__ = list(_new_all)
