"""
Evaluators: Entity 节点 (Create, Destroy, SetTransform, GetTransform,
AddMesh, AddCamera, FindByName, SetVisibility)。

对接 SceneManager (ECS) 实现实体生命周期管理。
"""

import esper

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .math import _read_data_input, _write_data_output


# ── 辅助 ──────────────────────────────────────────────────────

def _get_scene_manager():
    """延迟导入，避免循环依赖。"""
    from Application.Core.Scene.SceneManager import SceneManager
    return SceneManager


# ── EntityCreate ──────────────────────────────────────────────

def _eval_entity_create(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    sm = _get_scene_manager()
    eid = sm.AddEntity()
    if name:
        # 通过 Transform 或自定义组件暂存名称（简化处理）
        pass
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


# ── EntitySetTransform ────────────────────────────────────────

def _eval_entity_set_transform(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    eid = int(eid_val)
    if eid < 0 or not esper.entity_exists(eid):
        return

    from Application.Core.Scene.BasicComponents import Transform
    try:
        t = esper.component_for_entity(eid, Transform)
    except Exception:
        return

    px = _read_data_input(node_id, "Position", ctx, g, 0)
    py = _read_data_input(node_id, "Position", ctx, g, 0)  # vec3 后续扩展
    pz = _read_data_input(node_id, "Position", ctx, g, 0)
    # 当前仅标量 Position — 后续 vec3 拆分为 X/Y/Z pin 或复合值
    # 这里先做简单处理
    t.position.x = _read_data_input(node_id, "Position", ctx, g, t.position.x)

register_evaluator("EntitySetTransform", _eval_entity_set_transform)


# ── EntityGetTransform ────────────────────────────────────────

def _eval_entity_get_transform(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid_val = _read_data_input(node_id, "EntityID", ctx, g, -1)
    eid = int(eid_val)
    if eid < 0 or not esper.entity_exists(eid):
        return

    from Application.Core.Scene.BasicComponents import Transform
    try:
        t = esper.component_for_entity(eid, Transform)
    except Exception:
        return

    _write_data_output(node_id, "Position", t.position.x, ctx, g)
    # Rotation / Scale 同理 — 后续扩展

register_evaluator("EntityGetTransform", _eval_entity_get_transform)


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
    sm.AddComponentToEntity(eid, CamComp(primary=False))

register_evaluator("EntityAddCamera", _eval_entity_add_camera)


# ── EntityFindByName ──────────────────────────────────────────

def _eval_entity_find_by_name(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    name = _read_data_input(node_id, "Name", ctx, g, "")
    # 简化：遍历所有实体查找 NameComponent（如有）
    found = -1
    if name:
        for eid, _ in esper.get_components():
            # 目前无 NameComponent，先返回 -1
            pass
    _write_data_output(node_id, "EntityID", float(found), ctx, g)

register_evaluator("EntityFindByName", _eval_entity_find_by_name)


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
