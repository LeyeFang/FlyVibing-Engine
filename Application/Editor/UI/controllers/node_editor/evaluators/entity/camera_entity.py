"""Evaluators: EntityAddCamera 节点。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input


def _eval_entity_add_camera(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    eid = int(eid_val)

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntityAddCamera", "add_component", f"eid={eid}")
        return

    if eid < 0 or not ctx.scene.EntityExists(eid):
        return

    from Application.Core.Scene.BasicComponents import Camera as CamComp
    ctx.scene.AddComponentToEntity(eid, CamComp(is_primary=False))


register_evaluator("EntityAddCamera", _eval_entity_add_camera)
