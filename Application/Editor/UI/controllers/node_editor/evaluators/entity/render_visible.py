"""Evaluators: EntitySetRenderVisible 节点。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input
from .helpers import resolve_entity_id


def _eval_entity_set_render_visible(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid = resolve_entity_id(node_id, "EntityID", ctx, g)
    visible_val = _read_data_input(node_id, "Visible", ctx, g, 1)
    visible = bool(int(visible_val))

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntitySetRenderVisible", "set_visible",
                     f"eid={eid}, visible={visible}")
        return

    if eid is None or eid < 0 or not ctx.scene.EntityExists(eid):
        return

    ctx.scene.SetEntityRenderVisible(eid, visible=visible)


register_evaluator("EntitySetRenderVisible", _eval_entity_set_render_visible)
