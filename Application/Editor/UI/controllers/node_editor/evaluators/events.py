"""
Evaluators: 事件节点（空函数，仅作为遍历入口标记）。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_event(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    pass  # 事件节点不执行逻辑，仅作为遍历起点


register_evaluator("OnGameStart", _eval_event)
register_evaluator("OnFrameUpdate", _eval_event)
register_evaluator("OnGameStop", _eval_event)
