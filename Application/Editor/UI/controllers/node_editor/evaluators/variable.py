"""
Evaluators: 变量节点 (VarSet, VarGet)。

利用 ExecutionContext._variables 在单次执行中存储/读取变量。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .math import _read_data_input, _write_data_output


def _eval_var_set(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    value = _read_data_input(node_id, "Value", ctx, g, 0)
    if name:
        ctx.set_var(str(name), value)

register_evaluator("VarSet", _eval_var_set)


def _eval_var_get(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    value = ctx.get_var(str(name)) if name else None
    if value is not None:
        _write_data_output(node_id, "Value", float(value), ctx, g)

register_evaluator("VarGet", _eval_var_get)
