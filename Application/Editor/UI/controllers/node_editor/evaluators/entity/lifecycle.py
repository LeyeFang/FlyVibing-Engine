"""
Evaluators: 实体生命周期 v2 — EntitySpawn (类型安全 EntityRef)。
"""

import esper

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ...data_model import EntityRef
from ..math import _read_data_input, _write_data_output

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Camera


# ── EntitySpawn ───────────────────────────────────────────────

def _eval_entity_spawn(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Spawn Entity — 按模板创建实体，返回类型安全的 EntityRef。

    Template 选项:
      - "Empty"  →  仅 Transform
      - "Cube"   →  Transform + MeshRenderer (默认立方体)
      - "Camera" →  Transform + Camera
    """
    inst = g._canvas.nodes[node_id]

    template = inst.props.get("template", "Empty")
    name = _read_data_input(node_id, "Name", ctx, g, "")

    # ── 创建实体 ──
    eid = SceneManager.AddEntity(name=str(name) if name else "")

    # ── 按模板添加组件 ──
    if template == "Cube":
        from Application.Resource.ResourceManager import ResourceManager
        cube_mesh_id = ResourceManager.GetDefaultMesh('Cube')
        comp = MeshRenderer(mesh_id=cube_mesh_id)
        SceneManager.AddComponentToEntity(eid, comp)

    elif template == "Camera":
        comp = Camera(is_primary=False)
        SceneManager.AddComponentToEntity(eid, comp)

    # "Empty" → 无额外组件

    # ── 输出 EntityRef ──
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.name == "Entity" and pin.direction == "output":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                # 将 EntityRef 存入 ExecutionContext 的 _variables（跨帧引用）
                ctx.set_pin(inst_pin_id, EntityRef(eid=eid))

    if name:
        print(f"[EntitySpawn] '{name}' (eid={eid}, template={template})")
    else:
        print(f"[EntitySpawn] Entity #{eid} (template={template})")


register_evaluator("EntitySpawn", _eval_entity_spawn)
