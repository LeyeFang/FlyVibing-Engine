"""
Evaluators: 变量节点 (VarSet, VarGet, Constant)。

VarSet:  Manual/Pin 双模式写入变量。
VarGet:  读取变量。
Constant: 固定浮点值输出。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .math import _read_data_input, _write_data_output


# ── VarSet (Manual / Pin 双模式) ────────────────────────────

def _eval_var_set(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    mode = inst.props.get("mode", "manual")

    # Name: 优先从 pin 读取，否则用文本框
    name = _read_data_input(node_id, "Name", ctx, g, "")
    if not name:
        name = inst.props.get("var_name", "")
    if not name:
        return

    if mode == "manual":
        value = inst.props.get("value", 0.0)
    else:
        value = _read_data_input(node_id, "Value", ctx, g, 0)

    ctx.set_var(str(name), float(value))

register_evaluator("VarSet", _eval_var_set)


# ── VarGet ──────────────────────────────────────────────────

def _eval_var_get(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    if not name:
        inst = g._canvas.nodes[node_id]
        name = inst.props.get("var_name", "")
    if not name:
        return
    value = ctx.get_var(str(name))
    if value is not None:
        _write_data_output(node_id, "Value", float(value), ctx, g)

register_evaluator("VarGet", _eval_var_get)


# ── Constant ────────────────────────────────────────────────

def _eval_constant(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    value = float(inst.props.get("value", 0.0))
    _write_data_output(node_id, "Result", value, ctx, g)

register_evaluator("Constant", _eval_constant)
