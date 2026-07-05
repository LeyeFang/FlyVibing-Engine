"""
Evaluators: Flow 节点 (Sequence)。

按顺序逐个执行下游，天然被 _walk_exec 的 for-loop 支持。
空求值函数即可，exec 链遍历会自动处理多输出。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_sequence(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    pass  # 遍历逻辑由 _walk_exec 的 for pin in nd.pins 自动完成

register_evaluator("Sequence", _eval_sequence)
