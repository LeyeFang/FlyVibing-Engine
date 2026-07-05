"""
GraphEvaluator — 向后兼容 shim。

实际代码已迁移至:
  Application.Editor.UI.controllers.node_editor.evaluator_engine
  Application.Editor.UI.controllers.node_editor.evaluators.*

本文件保留所有原有导出，避免破坏现有导入。
"""

from Application.Editor.UI.controllers.node_editor.evaluator_engine import (
    ExecutionContext,
    GraphEvaluator,
    register_evaluator,
    _EVALUATORS,
)

# 触发所有 evaluator 模块的注册
from Application.Editor.UI.controllers.node_editor.evaluators import (  # noqa: F401
    events,
    time,
    debug,
    math,
    entity,
    variable,
    flow,
    action,
)

__all__ = [
    "ExecutionContext",
    "GraphEvaluator",
    "register_evaluator",
    "_EVALUATORS",
]

