"""
Evaluators: Action 节点。

CreateWindow / DestroyWindow 已移除 — 窗口管理由 Engine / SimulationController 负责。
ExitGame — 发出运行时中立的停止请求 (ctx.request_stop)。

宿主处理: PIE 由 SimulationController.stop 注册为 ctx.on_stop_request;
独立运行时无回调 → RuntimeNodeLayer 帧末以中性方式结束 GameRuntime。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_exit_game(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """ExitGame — 请求停止当前运行（不直接依赖任何编辑器组件）。"""
    if ctx.dry_run:
        ctx.emit_log(node_id, "ExitGame", "stop", "game exit requested (skipped in dry-run)")
        return

    ctx.request_stop()
    print("[ExitGame] Stop requested — runtime will exit next frame")

register_evaluator("ExitGame", _eval_exit_game)
