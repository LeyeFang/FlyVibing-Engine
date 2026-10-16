"""Evaluators: Media 节点 — ShowMedia（运行时驱动 MediaPlayer 播放）。

- 非干跑: ctx.scene（运行时 SceneManager; PIE=GameRuntime 注入）→ engine（=scene.app）
  → MediaSystem.advance（懒解码 + 动态纹理 + 逐帧上传到该引擎的渲染器）。
- 干跑: 只记日志, 零副作用（校验服务安全）。
"""

from __future__ import annotations

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .entity.camera import _read_entity_ref


def _eval_show_media(node_id: int, ctx: ExecutionContext,
                     g: GraphEvaluator) -> None:
    eid = _read_entity_ref(node_id, "Entity", ctx, g)

    if ctx.dry_run:
        ctx.emit_log(node_id, "ShowMedia", "media_advance",
                     f"eid={eid}, dt={float(getattr(ctx, 'delta_time', 0.0)):.4f}")
        return

    if ctx.scene is None or eid < 0 or not ctx.scene.EntityExists(eid):
        print(f"[Node:ShowMedia] invalid target entity — skipped (eid={eid})")
        return

    engine = getattr(ctx.scene, "app", None)
    if engine is None:
        return

    from Application.Core.Media import MediaSystem
    MediaSystem.advance(engine, eid, float(getattr(ctx, "delta_time", 0.0)))


register_evaluator("ShowMedia", _eval_show_media)
