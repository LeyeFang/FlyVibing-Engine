"""
Evaluators: 实体生命周期 v2 — EntitySpawn (类型安全 EntityRef)。

从 Scene.entities 注册表中读取实体模板定义，在 ECS World 中实例化。
"""

import copy

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ...data_model import EntityRef
from ..math import _read_data_input



# ── EntitySpawn ───────────────────────────────────────────────

# ★ 干跑模式用假实体 ID 计数器
_dry_run_eid_counter: int = 9000


def _eval_entity_spawn(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Spawn Entity — 从 Scene.entities 模板实例化实体。

    Template:
      节点属性 dropdown，列出 Scene.entities 中所有定义名称。
      选中名称后从 Scene.entities 读取 EntityData 作为默认值。

    Position / Rotation pin:
      可选覆盖。若未连线，使用 Scene 模板中的 Transform 默认值。

    Returns:
      EntityRef — 类型安全的实例引用。

    dry_run 模式:
      跳过 ECS 创建，输出假 EntityRef (eid=9000+) 以保持数据流连通。
    """
    global _dry_run_eid_counter
    inst = g._canvas.nodes[node_id]

    template_name = inst.props.get("template", "")
    name_override = _read_data_input(node_id, "Name", ctx, g, "")

    instance_name = str(name_override) if name_override else template_name
    final_name = instance_name if instance_name else ""

    # ── dry_run: 跳过 ECS 创建，输出假 EntityRef ──
    if ctx.dry_run:
        _dry_run_eid_counter += 1
        fake_eid = _dry_run_eid_counter
        ctx.emit_log(node_id, "EntitySpawn", "spawn",
                     f"name='{final_name}', template='{template_name}', "
                     f"dry_eid={fake_eid}")
        # 仍然输出 EntityRef，保持数据流连通
        nd = g._types[inst.node_type]
        for pin in nd.pins:
            if pin.name == "Entity" and pin.direction == "output":
                inst_pin_id = inst.pin_ids.get(pin.name)
                if inst_pin_id is not None:
                    ctx.set_pin(inst_pin_id, EntityRef(eid=fake_eid))
        return

    # ── 1. 从 Scene.entities 查找模板定义 (模板场景由宿主注入 ctx.template_scene) ──
    from Application.Core.Scene.Scene import Scene
    scene = _get_active_scene(ctx)
    if scene is None and template_name:
        print(f"[EntitySpawn] WARNING: no template scene injected — "
              f"cannot resolve template '{template_name}' "
              f"(host must set ctx.template_scene)")
    entity_def = None
    template_old_eid: int | None = None
    if scene is not None and template_name:
        result = scene.get_entity_by_name(template_name)
        if result is not None:
            template_old_eid, entity_def = result

    # ── 2. 在 ECS World 中一步创建实体（含所有模板组件，原子操作）──
    if entity_def is not None:
        template_comps = list(entity_def.components.values())
        eid = ctx.scene.AddEntity(final_name, *template_comps)
    else:
        eid = ctx.scene.AddEntity(final_name)

    # ── 3. 递归生成子 entity（从 Scene 模板读取层级关系）──
    if entity_def is not None and template_old_eid is not None:
        _spawn_entity_tree(
            template_old_eid=template_old_eid,
            parent_new_eid=eid,
            scene=scene,
            ctx=ctx,
        )

    # ── 4. 输出 EntityRef ──
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.name == "Entity" and pin.direction == "output":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, EntityRef(eid=eid))

    tpl_info = f"template='{template_name}'" if template_name else "no template"
    print(f"[EntitySpawn] '{instance_name}' (eid={eid}, {tpl_info})")


def _get_active_scene(ctx: ExecutionContext):
    """模板场景来源 — 由宿主注入 (ctx.template_scene)，运行时无反向依赖。

    PIE: SimulationController 经 RuntimeNodeLayer.set_scene 注入编辑器场景深拷贝；
    独立运行: player 注入游戏场景；未注入 → None (EntitySpawn 退化为无模板实体)。
    """
    return getattr(ctx, "template_scene", None)


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
    import numpy as np
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


def _spawn_entity_tree(
    template_old_eid: int,
    parent_new_eid: int,
    scene,
    ctx: ExecutionContext,
) -> None:
    """递归生成 entity 子树 — 从 Scene 模板读取 parent_id 关系。

    Args:
        template_old_eid: 当前 entity 在模板 (Scene.entities) 中的 ID
        parent_new_eid:   当前 entity 在 ECS 中的新 ID
        scene:            Scene 模板数据
        ctx:              执行上下文
    """
    # 找到所有 parent_id == template_old_eid 的子 entity 模板
    children: list[tuple[int, object]] = []
    for old_eid, ed in scene.entities.items():
        if ed.parent_id == template_old_eid:
            children.append((old_eid, ed))

    for child_old_eid, child_def in children:
        # 深拷贝组件避免模板污染
        child_comps = [copy.deepcopy(c) for c in child_def.components.values()]
        child_eid = ctx.scene.AddEntity(child_def.name, *child_comps)

        # 建立父子关系
        ctx.scene.SetEntityParent(child_eid, parent_new_eid)

        print(f"[EntitySpawn]   child '{child_def.name}' (eid={child_eid}) → parent {parent_new_eid}")

        # 递归生成孙节点
        _spawn_entity_tree(child_old_eid, child_eid, scene, ctx)


register_evaluator("EntitySpawn", _eval_entity_spawn)


# ── EntityGet ─────────────────────────────────────────────────

def _eval_entity_get(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Get Entity — 按名称查找已生成的 entity，输出 EntityRef。

    Name 来源:
      1. 优先从 Name input pin 读取（上游连线）
      2. 否则从节点内手动文本框读取

    Output:
      EntityRef — 若找到则 is_valid=True (eid>=0)，否则 is_valid=False (eid=-1)
    """
    inst = g._canvas.nodes[node_id]

    # ── 读取名称 ──
    name = _read_data_input(node_id, "Name", ctx, g, "")
    if not name:
        name = inst.props.get("entity_name", "")
    name = str(name).strip() if name else ""

    # ── 查找 entity ──
    eid = -1
    if name:
        try:
            eid = ctx.scene.GetEntityByName(name)
        except Exception:
            pass

    # ── 写入 output pin ──
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.name == "Entity" and pin.direction == "output":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, EntityRef(eid=eid))

    if eid >= 0:
        print(f"[EntityGet] '{name}' → eid={eid}")
    else:
        print(f"[EntityGet] '{name}' not found")

register_evaluator("EntityGet", _eval_entity_get)
