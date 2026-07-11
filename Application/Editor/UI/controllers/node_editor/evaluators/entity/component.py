"""
Evaluators: Component 节点 — 通用组件 CRUD。

  ComponentAdd    — 按名称给实体添加组件 + 设置属性值
  ComponentRemove — 按名称从实体移除组件
"""

import numpy as np

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input

# ── 复用 camera.py 中的 entity_ref 读取 ──
from .camera import _read_entity_ref


# ═══════════════════════════════════════════════════════════════
# 辅助: 读取组件属性值 (优先 Pin 连线, 回退到 Manual 默认值)
# ═══════════════════════════════════════════════════════════════

def _read_component_prop(node_id: int, pin_name: str,
                         ctx: ExecutionContext, g: GraphEvaluator,
                         inst, comp_name: str, default):
    """读取组件属性值。

    Pin 模式: 从连线读取 pin 值
    Manual 模式: 从 inst.props 读取用户填入的默认值
    """
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
    # Manual 模式或 pin 无连线 → 读 props 默认值
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


# ═══════════════════════════════════════════════════════════════
# ComponentAdd — 给实体添加组件 + 设置属性值
# ═══════════════════════════════════════════════════════════════

def _eval_component_add(node_id: int, ctx: ExecutionContext,
                        g: GraphEvaluator) -> None:
    """按组件名称给实体添加组件，并根据 Manual/Pin 模式设置属性值。

    组件类型由节点属性下拉选择。
    属性值来源:
      Pin 模式 — 从连线读取 data input pin
      Manual 模式 — 从节点 props 读取用户手动填入的值
    """
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not ctx.scene.EntityExists(eid):
        print("[ComponentAdd] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")

    if not comp_name:
        print("[ComponentAdd] No component type selected")
        return

    registered = ctx.scene.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)

    # ── Transform 特殊处理: 每个实体自带，只更新属性 ──
    if comp_name == "Transform":
        from Application.Core.Scene.BasicComponents import Transform
        try:
            xform = ctx.scene.GetComponent(eid, Transform)
        except Exception:
            print(f"[ComponentAdd] Entity #{eid} has no Transform — skipped")
            return

        pos = _to_vec3_tuple(_read_component_prop(
            node_id, "Position", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
        rot = _to_vec3_tuple(_read_component_prop(
            node_id, "Rotation", ctx, g, inst, comp_name, (0.0, 0.0, 0.0)))
        scl = _to_vec3_tuple(_read_component_prop(
            node_id, "Scale", ctx, g, inst, comp_name, (1.0, 1.0, 1.0)))

        xform.position_x, xform.position_y, xform.position_z = pos
        xform.rotation_x, xform.rotation_y, xform.rotation_z = rot
        xform.scale_x, xform.scale_y, xform.scale_z = scl
        print(f"[ComponentAdd] Transform set on entity #{eid}: "
              f"pos={pos}, rot={rot}, scl={scl}")
        return

    # ── 通用组件: 先创建再设值 ──
    if comp_cls is None:
        print(f"[ComponentAdd] Unknown component '{comp_name}'")
        return

    if ctx.scene.HasComponent(eid, comp_cls):
        print(f"[ComponentAdd] Entity #{eid} already has '{comp_name}' — updating properties")
        comp = ctx.scene.GetComponent(eid, comp_cls)
    else:
        ok = ctx.scene.AddComponentToEntityByName(eid, comp_name)
        if not ok:
            print(f"[ComponentAdd] Failed to add '{comp_name}'")
            return
        comp = ctx.scene.GetComponent(eid, comp_cls)
        print(f"[ComponentAdd] Added '{comp_name}' to entity #{eid}")

    # ── 从 Registry 读取属性定义并逐个赋值 ──
    from ...component_registry import get_properties
    props = get_properties(comp_name)
    if props:
        for prop in props:
            val = _read_component_prop(
                node_id, prop.name, ctx, g, inst, comp_name, prop.default)
            if val is not None and hasattr(comp, prop.name):
                try:
                    setattr(comp, prop.name, val)
                except Exception as e:
                    print(f"[ComponentAdd] Failed to set {comp_name}.{prop.name}: {e}")


register_evaluator("ComponentAdd", _eval_component_add)


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
