"""
node_editor — 节点编辑器控制器层。

导出所有数据模型、类型注册表、画布、执行引擎。
"""

from .data_model import (
    PinDef,
    NodeTypeDef,
    NodeInstance,
    LinkInstance,
    _gen_id,
)
from .node_types import _TYPES
from .canvas import NodeCanvas
from .evaluator_engine import (
    ExecutionContext,
    GraphEvaluator,
    register_evaluator,
    _EVALUATORS,
)

# 导入所有 evaluator 模块以触发 register_evaluator() 注册
from .evaluators import (  # noqa: F401
    events,
    time,
    debug,
    math,
    entity,
    vector,
    variable,
    flow,
    action,
)

__all__ = [
    "PinDef",
    "NodeTypeDef",
    "NodeInstance",
    "LinkInstance",
    "_gen_id",
    "_TYPES",
    "NodeCanvas",
    "ExecutionContext",
    "GraphEvaluator",
    "register_evaluator",
    "_EVALUATORS",
]
