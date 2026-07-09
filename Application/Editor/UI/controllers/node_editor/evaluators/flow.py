"""
Evaluators: Flow 节点 (Sequence, Branch)。

Sequence: 按顺序逐个执行下游，由 _walk_exec 的 for-loop 自动遍历。
Branch:   条件分支 — 根据 Condition pin 的值只走 True 或 False 一路。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .math import _read_data_input


def _eval_sequence(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    pass  # 遍历逻辑由 _walk_exec 的 for pin in nd.pins 自动完成

register_evaluator("Sequence", _eval_sequence)


def _eval_branch(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Branch — 读 Condition pin，只走匹配的 exec 分支。

    关键: _walk_exec 默认遍历所有 exec output pin。
    Branch 需要拦截此行为 — evaluator 内部手动调用 _walk_exec
    只对匹配的输出执行，然后通过 set_state 标记阻断默认遍历。
    """
    condition = bool(_read_data_input(node_id, "Condition", ctx, g, 0.0))
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]

    # 找到匹配方向的 exec output pin name
    target_pin = "True" if condition else "False"

    for pin in nd.pins:
        if pin.name == target_pin and pin.kind == "exec" and pin.direction == "output":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                next_ids = g._downstream_nodes(inst_pin_id)
                for nid in next_ids:
                    g._walk_exec(nid, ctx)

    # 标记阻断 — 阻止 _walk_exec 在返回后再遍历所有 output pin
    g.set_state(node_id, "_blocked", True)

register_evaluator("Branch", _eval_branch)
