"""
Evaluators: Action 节点 (CreateWindow, DestroyWindow)。

当前为 stubs — 窗口管理涉及 GLFW 多窗口上下文切换，复杂度高。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_create_window(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    print("[Node:CreateWindow] Not yet implemented")

register_evaluator("CreateWindow", _eval_create_window)


def _eval_destroy_window(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    print("[Node:DestroyWindow] Not yet implemented")

register_evaluator("DestroyWindow", _eval_destroy_window)
