"""Evaluators: EntityDestroy 节点。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .helpers import resolve_entity_id


def _eval_entity_destroy(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """销毁实体 — 通过 SceneManager 完整清理 ECS + 追踪 + 渲染器。"""
    eid = resolve_entity_id(node_id, "EntityID", ctx, g)
    if eid is not None and eid > 0:
        if ctx.dry_run:
            ctx.emit_log(node_id, "EntityDestroy", "delete", f"eid={eid}")
            return
        ok = ctx.scene.DeleteEntity(eid)
        if ok:
            print(f"[EntityDestroy] Entity #{eid} destroyed")
        else:
            print(f"[EntityDestroy] Entity #{eid} not found")


register_evaluator("EntityDestroy", _eval_entity_destroy)
