"""
Evaluators: Entity 节点 — 实体生命周期 + 类型安全引用 (EntityRef)。

原有节点 (v1, 裸 int EntityID):
  EntityDestroy, EntitySetTransform, EntityGetTransform,
  EntityAddMesh, EntityAddCamera, EntityFindByName, EntitySetRenderVisible

新节点 (v2, EntityRef):
  EntitySpawn — 按模板创建实体，返回类型安全的 EntityRef
"""

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input


# ═══════════════════════════════════════════════════════════════
# v1: 裸 int EntityID 节点 (保持向后兼容)
# ═══════════════════════════════════════════════════════════════

# ── EntityDestroy ─────────────────────────────────────────────

def _eval_entity_destroy(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """销毁实体 — 通过 SceneManager 完整清理 ECS + 追踪 + 渲染器。"""
    
    eid = _resolve_entity_id(node_id, "EntityID", ctx, g)
    if eid is not None and eid > 0:
        if ctx.dry_run:
            ctx.emit_log(node_id, "EntityDestroy", "delete", f"eid={eid}")
            return
        ok = ctx.scene.DeleteEntity(eid)
        if ok:
            print(f"[EntityDestroy] Entity #{eid} destroyed")
        else:
            print(f"[EntityDestroy] Entity #{eid} not found")


def _resolve_entity_id(node_id: int, pin_name: str,
                       ctx: ExecutionContext, g: GraphEvaluator) -> int | None:
    """从 data input pin 解析实体 ID — 支持 int / float / EntityRef 三种类型。

    直接使用 g._read_input 绕过 _read_data_input 的 float() 强转，
    避免 EntityRef → float 的 TypeError。
    """
    from .lifecycle import EntityRef  # noqa: F811
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is None:
                    return None
                if isinstance(val, EntityRef):
                    return val.eid
                if isinstance(val, (int, float)):
                    return int(val)
                return None
    return None


register_evaluator("EntityDestroy", _eval_entity_destroy)


# ── EntityAddMesh ─────────────────────────────────────────────

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


# ── EntityAddCamera ───────────────────────────────────────────

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


# ── EntitySetRenderVisible ───────────────────────────────────

def _eval_entity_set_render_visible(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid = _resolve_entity_id(node_id, "EntityID", ctx, g)
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


# ═══════════════════════════════════════════════════════════════
# v2: EntityRef 节点
# ═══════════════════════════════════════════════════════════════

from . import lifecycle  # noqa: E402, F401 — EntitySpawn
from . import camera     # noqa: E402, F401 — CameraSetMain
from . import component  # noqa: E402, F401 — ComponentAdd, SetComponent, GetComponent, ComponentRemove
