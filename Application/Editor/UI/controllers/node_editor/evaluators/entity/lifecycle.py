"""
Evaluators: 实体生命周期 v2 — EntitySpawn (类型安全 EntityRef)。

从 Scene.entities 注册表中读取实体模板定义，在 ECS World 中实例化。
"""

import copy
import numpy as np

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ...data_model import EntityRef
from ..math import _read_data_input



# ── EntitySpawn ───────────────────────────────────────────────

def _eval_entity_spawn(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Spawn Entity — 从 Scene.entities 模板实例化实体。

    Template:
      节点属性 dropdown，列出 Scene.entities 中所有定义名称。
      选中名称后从 Scene.entities 读取 EntityData 作为默认值。

    Position / Rotation pin:
      可选覆盖。若未连线，使用 Scene 模板中的 Transform 默认值。

    Returns:
      EntityRef — 类型安全的实例引用。
    """
    inst = g._canvas.nodes[node_id]

    template_name = inst.props.get("template", "")
    name_override = _read_data_input(node_id, "Name", ctx, g, "")

    # ── 1. 从 Scene.entities 查找模板定义 ──
    from Application.Core.Scene.Scene import Scene
    scene = _get_active_scene()
    entity_def = None
    if scene is not None and template_name:
        result = scene.get_entity_by_name(template_name)
        if result is not None:
            _, entity_def = result

    # ── 2. 在 ECS World 中一步创建实体（含所有模板组件，原子操作）──
    instance_name = str(name_override) if name_override else template_name
    final_name = instance_name if instance_name else ""
    if entity_def is not None:
        template_comps = list(entity_def.components.values())
        eid = ctx.scene.AddEntity(final_name, *template_comps)
    else:
        eid = ctx.scene.AddEntity(final_name)

    # ── 3. 覆盖 Position / Rotation (pin 值优先于模板默认值 ── 已移除 pin)
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.name == "Entity" and pin.direction == "output":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, EntityRef(eid=eid))

    tpl_info = f"template='{template_name}'" if template_name else "no template"
    print(f"[EntitySpawn] '{instance_name}' (eid={eid}, {tpl_info})")


def _get_active_scene():
    """获取当前活跃的 Scene 对象。

    优先级:
      1. RuntimeNodeLayer._scene (PIE / 导出模式注入)
      2. EditorHost.get_active_scene() (编辑器侧回退)
    """
    # ── Runtime 注入 ──
    try:
        from Application.Runtime.RuntimeNodeLayer import RuntimeNodeLayer
        if RuntimeNodeLayer._scene is not None:
            return RuntimeNodeLayer._scene
    except Exception:
        pass

    # ── Editor 回退 ──
    try:
        from Application.Editor.EditorHost import EditorHost
        return EditorHost.get_active_scene()
    except Exception:
        return None


def _instantiate_components(eid: int, entity_def, ctx: ExecutionContext) -> None:
    """将 EntityData 中的组件实例化到 ECS World 的实体上。

    对每个组件进行深拷贝后添加，确保实例与模板独立。
    """
    from Application.Core.Scene.BasicComponents import Transform

    for comp_type_name, comp_instance in entity_def.components.items():
        # Transform 已在 AddEntity 中创建 → 用模板值覆盖 (模板存 GL 坐标)
        if comp_type_name == "Transform":
            tmpl = comp_instance
            ctx.scene.SetEntityTransform(
                eid,
                position_xyz=(tmpl.position_x, tmpl.position_y, tmpl.position_z),
                rotation_xyz=(tmpl.rotation_x, tmpl.rotation_y, tmpl.rotation_z),
                scale_xyz=(
                    getattr(tmpl, 'scale_x', 1.0),
                    getattr(tmpl, 'scale_y', 1.0),
                    getattr(tmpl, 'scale_z', 1.0),
                ),
            )
        else:
            # 其他组件: 深拷贝后添加
            copied = copy.deepcopy(comp_instance)
            ctx.scene.AddComponentToEntity(eid, copied)


def _read_vec3_input(node_id: int, pin_name: str, ctx: ExecutionContext,
                     g: GraphEvaluator):
    """读取 vec3 类型的 data input pin，返回 np.ndarray 或 None。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    if isinstance(val, np.ndarray):
                        return val.astype(np.float32)
                    if isinstance(val, (list, tuple)):
                        return np.array(val, dtype=np.float32)
    return None


register_evaluator("EntitySpawn", _eval_entity_spawn)
