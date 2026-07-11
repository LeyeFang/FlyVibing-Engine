"""
Evaluators: Component 节点 — 通用组件 CRUD。

  ComponentAdd    — 按名称给实体添加组件 + 设置属性值
  SetComponent    — 按名称修改实体已有组件的属性值
  ComponentRemove — 按名称从实体移除组件
"""

import numpy as np

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input

# ── 复用 camera.py 中的 entity_ref 读取 ──
from .camera import _read_entity_ref


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _read_component_prop(node_id: int, pin_name: str,
                         ctx: ExecutionContext, g: GraphEvaluator,
                         inst, comp_name: str, default):
    """读取组件属性值 — Pin 模式读连线，Manual 模式读 props。"""
    mode = inst.props.get("mode", "manual")
    if mode == "pin":
        nd = g._types.get(inst.node_type)
        if nd:
            for p in nd.pins:
                if p.name == pin_name and p.direction == "input":
                    pid = inst.pin_ids.get(p.name)
                    if pid is not None:
                        val = g._read_input(pid, ctx)
                        if val is not None:
                            return val
    key = f"{comp_name}.{pin_name}"
    return inst.props.get(key, default)


def _to_vec3_tuple(val) -> tuple[float, float, float]:
    """将各种 vec3 表示转换为 (x, y, z) 元组。"""
    if val is None:
        return (0.0, 0.0, 0.0)
    if isinstance(val, (tuple, list)):
        return (float(val[0]), float(val[1]), float(val[2]))
    if isinstance(val, np.ndarray):
        return (float(val[0]), float(val[1]), float(val[2]))
    return (float(val), float(val), float(val))


def _apply_component_properties(
    node_id: int, ctx: ExecutionContext, g: GraphEvaluator,
    inst, comp_name: str, comp,
) -> None:
    """从 Registry 读取属性定义并逐个 setattr 到组件实例。"""
    from ...component_registry import get_properties
    props = get_properties(comp_name)
    if not props:
        return
    for prop in props:
        val = _read_component_prop(
            node_id, prop.name, ctx, g, inst, comp_name, prop.default)
        if val is None:
            continue
        attr = prop.attr_name or prop.name
        if hasattr(comp, attr):
            try:
                setattr(comp, attr, val)
            except Exception as e:
                print(f"[{inst.node_type}] Failed to set {comp_name}.{attr}: {e}")


def _resolve_component(
    eid: int, comp_name: str, ctx, create_if_missing: bool,
) -> tuple[object | None, str]:
    """解析组件：获取或创建组件实例。返回 (comp_instance, error_msg)。

    create_if_missing=True  → ComponentAdd: 不存在则创建
    create_if_missing=False → SetComponent: 不存在则报错
    """
    from Application.Core.Scene.BasicComponents import Transform

    registered = ctx.scene.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)

    if comp_name == "Transform":
        try:
            return ctx.scene.GetComponent(eid, Transform), ""
        except Exception:
            return None, f"Entity #{eid} has no Transform"

    if comp_cls is None:
        return None, f"Unknown component '{comp_name}'"

    if ctx.scene.HasComponent(eid, comp_cls):
        return ctx.scene.GetComponent(eid, comp_cls), ""
    elif create_if_missing:
        ok = ctx.scene.AddComponentToEntityByName(eid, comp_name)
        if not ok:
            return None, f"Failed to add '{comp_name}'"
        return ctx.scene.GetComponent(eid, comp_cls), ""
    else:
        return None, f"Entity #{eid} has no '{comp_name}'"


# ═══════════════════════════════════════════════════════════════
# ComponentAdd — 给实体添加组件 + 设置属性值
# ═══════════════════════════════════════════════════════════════

def _eval_component_add(node_id: int, ctx: ExecutionContext,
                        g: GraphEvaluator) -> None:
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[ComponentAdd] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")
    if not comp_name:
        print("[ComponentAdd] No component type selected")
        return

    comp, err = _resolve_component(eid, comp_name, ctx, create_if_missing=True)
    if comp is None:
        print(f"[ComponentAdd] {err}")
        return

    # ── Transform 特殊处理 (vec3 分解) ──
    if comp_name == "Transform":
        from Application.Core.Scene.BasicComponents import Transform
        if isinstance(comp, Transform):
            pos = _to_vec3_tuple(_read_component_prop(
                node_id, "Position", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
            rot = _to_vec3_tuple(_read_component_prop(
                node_id, "Rotation", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
            scl = _to_vec3_tuple(_read_component_prop(
                node_id, "Scale", ctx, g, inst, comp_name, (1.0, 1.0, 1.0)))
            comp.position_x, comp.position_y, comp.position_z = pos
            comp.rotation_x, comp.rotation_y, comp.rotation_z = rot
            comp.scale_x, comp.scale_y, comp.scale_z = scl
            print(f"[ComponentAdd] Transform set on entity #{eid}: "
                  f"pos={pos}, rot={rot}, scl={scl}")
            return

    _apply_component_properties(node_id, ctx, g, inst, comp_name, comp)
    print(f"[ComponentAdd] '{comp_name}' properties set on entity #{eid}")

register_evaluator("ComponentAdd", _eval_component_add)


# ═══════════════════════════════════════════════════════════════
# SetComponent — 修改实体已有组件的属性值
# ═══════════════════════════════════════════════════════════════

def _eval_set_component(node_id: int, ctx: ExecutionContext,
                        g: GraphEvaluator) -> None:
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[SetComponent] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")
    if not comp_name:
        print("[SetComponent] No component type selected")
        return

    comp, err = _resolve_component(eid, comp_name, ctx, create_if_missing=False)
    if comp is None:
        print(f"[SetComponent] {err}")
        return

    # ── Transform 特殊处理 ──
    if comp_name == "Transform":
        from Application.Core.Scene.BasicComponents import Transform
        if isinstance(comp, Transform):
            pos = _to_vec3_tuple(_read_component_prop(
                node_id, "Position", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
            rot = _to_vec3_tuple(_read_component_prop(
                node_id, "Rotation", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
            scl = _to_vec3_tuple(_read_component_prop(
                node_id, "Scale", ctx, g, inst, comp_name, (1.0, 1.0, 1.0)))
            comp.position_x, comp.position_y, comp.position_z = pos
            comp.rotation_x, comp.rotation_y, comp.rotation_z = rot
            comp.scale_x, comp.scale_y, comp.scale_z = scl
            print(f"[SetComponent] Transform set on entity #{eid}: "
                  f"pos={pos}, rot={rot}, scl={scl}")
            return

    _apply_component_properties(node_id, ctx, g, inst, comp_name, comp)
    print(f"[SetComponent] '{comp_name}' properties set on entity #{eid}")

register_evaluator("SetComponent", _eval_set_component)


# ═══════════════════════════════════════════════════════════════
# ComponentRemove — 从实体移除组件
# ═══════════════════════════════════════════════════════════════

def _eval_component_remove(node_id: int, ctx: ExecutionContext,
                           g: GraphEvaluator) -> None:
    """按组件名称从实体移除组件。"""
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[ComponentRemove] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")

    if not comp_name:
        print("[ComponentRemove] No component type selected")
        return

    registered = ctx.scene.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)

    if comp_cls is None:
        print(f"[ComponentRemove] Unknown component '{comp_name}'")
        return

    if not ctx.scene.HasComponent(eid, comp_cls):
        print(f"[ComponentRemove] Entity #{eid} has no '{comp_name}'")
        return

    try:
        ctx.scene.RemoveComponent(eid, comp_cls)
        print(f"[ComponentRemove] Removed '{comp_name}' from entity #{eid}")
    except Exception as e:
        print(f"[ComponentRemove] Failed: {e}")


register_evaluator("ComponentRemove", _eval_component_remove)
