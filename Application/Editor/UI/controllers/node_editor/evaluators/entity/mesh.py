"""Evaluators: EntityAddMesh 节点。"""

from __future__ import annotations

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input


def _eval_entity_add_mesh(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    mesh_val = _read_data_input(node_id, "MeshID", ctx, g, -1)
    mat_val = _read_data_input(node_id, "MaterialID", ctx, g, -1)
    eid, mid, matid = int(eid_val), int(mesh_val), int(mat_val)

    if ctx.dry_run:
        ctx.emit_log(node_id, "EntityAddMesh", "add_component",
                     f"eid={eid}, mesh={mid}, mat={matid}")
        return

    if eid < 0 or not ctx.scene.EntityExists(eid):
        print(f"[Node:EntityAddMesh] Invalid entity #{eid}")
        return

    from Application.Core.Scene.BasicComponents import MeshRenderer
    comp = MeshRenderer()
    comp.mesh_id = mid if mid >= 0 else 0
    comp.material_id = matid if matid >= 0 else 0
    ctx.scene.AddComponentToEntity(eid, comp)
    print(f"[Node:EntityAddMesh] Added MeshRenderer to entity #{eid}")


register_evaluator("EntityAddMesh", _eval_entity_add_mesh)
