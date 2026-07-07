"""
Evaluators: Entity 节点 — 实体生命周期 + 类型安全引用 (EntityRef)。

原有节点 (v1, 裸 int EntityID):
  EntityCreate, EntityDestroy, EntitySetTransform, EntityGetTransform,
  EntityAddMesh, EntityAddCamera, EntityFindByName, EntitySetVisibility

新节点 (v2, EntityRef):
  EntitySpawn — 按模板创建实体，返回类型安全的 EntityRef
"""

import esper

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input, _write_data_output


# ── 辅助 ──────────────────────────────────────────────────────

def _get_scene_manager():
    """延迟导入，避免循环依赖。"""
    from Application.Core.Scene.SceneManager import SceneManager
    return SceneManager


# ═══════════════════════════════════════════════════════════════
# v1: 裸 int EntityID 节点 (保持向后兼容)
# ═══════════════════════════════════════════════════════════════

# ── EntityCreate ──────────────────────────────────────────────

def _eval_entity_create(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    sm = _get_scene_manager()
    eid = sm.AddEntity()
    if name:
        sm.SetEntityName(eid, str(name))
    _write_data_output(node_id, "EntityID", float(eid), ctx, g)

register_evaluator("EntityCreate", _eval_entity_create)


# ── EntityDestroy ─────────────────────────────────────────────

def _eval_entity_destroy(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    eid = int(eid_val)
    if eid >= 0 and esper.entity_exists(eid):
        esper.delete_entity(eid)
        print(f"[Node:EntityDestroy] Entity #{eid} destroyed")

register_evaluator("EntityDestroy", _eval_entity_destroy)


# ── EntityAddMesh ─────────────────────────────────────────────

def _eval_entity_add_mesh(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    mesh_val = _read_data_input(node_id, "MeshID", ctx, g, -1)
    mat_val = _read_data_input(node_id, "MaterialID", ctx, g, -1)
    eid, mid, matid = int(eid_val), int(mesh_val), int(mat_val)

    if eid < 0 or not esper.entity_exists(eid):
        print(f"[Node:EntityAddMesh] Invalid entity #{eid}")
        return

    from Application.Core.Scene.BasicComponents import MeshRenderer
    sm = _get_scene_manager()
    comp = MeshRenderer()
    comp.mesh_id = mid if mid >= 0 else 0
    comp.material_id = matid if matid >= 0 else 0
    sm.AddComponentToEntity(eid, comp)
    print(f"[Node:EntityAddMesh] Added MeshRenderer to entity #{eid}")

register_evaluator("EntityAddMesh", _eval_entity_add_mesh)


# ── EntityAddCamera ───────────────────────────────────────────

def _eval_entity_add_camera(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    eid = int(eid_val)
    if eid < 0 or not esper.entity_exists(eid):
        return

    from Application.Core.Scene.BasicComponents import Camera as CamComp
    sm = _get_scene_manager()
    sm.AddComponentToEntity(eid, CamComp(is_primary=False))

register_evaluator("EntityAddCamera", _eval_entity_add_camera)


# ── EntitySetVisibility ───────────────────────────────────────

def _eval_entity_set_visibility(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    visible_val = _read_data_input(node_id, "Visible", ctx, g, 1)
    eid = int(eid_val)
    visible = bool(int(visible_val))
    if eid < 0 or not esper.entity_exists(eid):
        return

    from Application.Core.Scene.BasicComponents import MeshRenderer
    try:
        mr = esper.component_for_entity(eid, MeshRenderer)
        mr.visible = visible
    except Exception:
        pass

register_evaluator("EntitySetVisibility", _eval_entity_set_visibility)


# ═══════════════════════════════════════════════════════════════
# v2: EntityRef 节点
# ═══════════════════════════════════════════════════════════════

from . import lifecycle  # noqa: E402, F401 — EntitySpawn
