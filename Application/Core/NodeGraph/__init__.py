"""
Application.Core.NodeGraph — 节点图运行时（图结构 + 语义 + 执行器）。

与编辑器 UI 完全解耦（无 imgui / 无 Application.Editor 依赖，由
Test/Application/Core/test_node_graph_boundary.py 守卫）:
  - 图数据格式: NodeCanvas / NodeInstance / LinkInstance (序列化契约不变)
  - 类型注册表: node_types (图长什么样)
  - 执行器:     evaluator_engine (GraphEvaluator / ExecutionContext)
  - 节点语义:   evaluators (图怎么跑; ctx.dry_run 空跑契约)
  - 图语义规则: graph_constraints / graph_rules

编辑器交互层 (画布控件 / Add 菜单 / 级联删除交互 / 导入导出 UI)
位于 Application/Editor/UI/panels/node_editor/。
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
    io,
    gtec,
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
