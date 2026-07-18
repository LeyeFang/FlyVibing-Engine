"""
Evaluators: Action 节点。

CreateWindow / DestroyWindow 已移除 — 窗口管理由 Engine / SimulationController 负责。
ExitGame — 请求停止 GameRuntime。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_exit_game(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """ExitGame — 设置 _pending_stop 标记，主线程下帧消费并停止 PIE。"""
    if ctx.dry_run:
        ctx.emit_log(node_id, "ExitGame", "stop", "game exit requested (skipped in dry-run)")
        return

    try:
        from Application.Editor.UI.controllers.SimulationController import SimulationController
        SimulationController.stop()
        print("[ExitGame] Stop requested — runtime will exit next frame")
    except Exception as e:
        # 非 PIE 环境 (独立运行/测试): 直接设置 Engine run_state
        print(f"[ExitGame] SimulationController unavailable: {e}")
        try:
            from Application.Runtime.GameRuntime import GameRuntime
            GameRuntime.run_state = False
        except Exception:
            pass

register_evaluator("ExitGame", _eval_exit_game)
