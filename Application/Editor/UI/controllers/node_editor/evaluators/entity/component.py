"""
Evaluators: Component 节点 — 通用组件 CRUD。

  ComponentAdd         — 按名称给实体添加组件
  ComponentRemove      — 按名称从实体移除组件
  ComponentSetProperty — 设置组件属性值
"""

from Application.Core.Scene.SceneManager import SceneManager

from ...evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from ..math import _read_data_input

# ── 复用 camera.py 中的 entity_ref 读取 ──
from .camera import _read_entity_ref


# ═══════════════════════════════════════════════════════════════
# ComponentAdd — 给实体添加组件
# ═══════════════════════════════════════════════════════════════

def _eval_component_add(node_id: int, ctx: ExecutionContext,
                        g: GraphEvaluator) -> None:
    """按组件名称给实体添加组件。

    组件类型由节点属性下拉选择 (如 Camera / MeshRenderer)。
    """
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not SceneManager.EntityExists(eid):
        print("[ComponentAdd] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")

    if not comp_name:
        print("[ComponentAdd] No component type selected")
        return

    from Application.Core.Scene.SceneManager import SceneManager

    # 检查是否已存在同类型组件
    registered = SceneManager.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)
    if comp_cls is not None and SceneManager.HasComponent(eid, comp_cls):
        print(f"[ComponentAdd] Entity #{eid} already has '{comp_name}' — skipped")
        return

    ok = SceneManager.AddComponentToEntityByName(eid, comp_name)
    if ok:
        print(f"[ComponentAdd] Added '{comp_name}' to entity #{eid}")
    else:
        print(f"[ComponentAdd] Failed to add '{comp_name}' — unknown component")


register_evaluator("ComponentAdd", _eval_component_add)


# ═══════════════════════════════════════════════════════════════
# ComponentRemove — 从实体移除组件
# ═══════════════════════════════════════════════════════════════

def _eval_component_remove(node_id: int, ctx: ExecutionContext,
                           g: GraphEvaluator) -> None:
    """按组件名称从实体移除组件。"""
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not SceneManager.EntityExists(eid):
        print("[ComponentRemove] Invalid entity — skipped")
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")

    if not comp_name:
        print("[ComponentRemove] No component type selected")
        return

    from Application.Core.Scene.SceneManager import SceneManager
    registered = SceneManager.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)

    if comp_cls is None:
        print(f"[ComponentRemove] Unknown component '{comp_name}'")
        return

    if not SceneManager.HasComponent(eid, comp_cls):
        print(f"[ComponentRemove] Entity #{eid} has no '{comp_name}'")
        return

    try:
        SceneManager.RemoveComponent(eid, comp_cls)
        print(f"[ComponentRemove] Removed '{comp_name}' from entity #{eid}")
    except Exception as e:
        print(f"[ComponentRemove] Failed: {e}")


register_evaluator("ComponentRemove", _eval_component_remove)


# ═══════════════════════════════════════════════════════════════
# ComponentSetProperty — 设置组件属性值
# ═══════════════════════════════════════════════════════════════

def _eval_component_set_property(node_id: int, ctx: ExecutionContext,
                                 g: GraphEvaluator) -> None:
    """设置实体上指定组件的属性值。

    节点属性:
      component: 组件类型名 (如 "MeshRenderer")
      property:  属性名 (如 "visible")
    Value pin:   新值 (variant)
    """
    eid = _read_entity_ref(node_id, "Entity", ctx, g)
    if eid < 0 or not SceneManager.EntityExists(eid):
        return

    inst = g._canvas.nodes[node_id]
    comp_name = inst.props.get("component", "")
    prop_name = inst.props.get("property", "")

    if not comp_name or not prop_name:
        return

    # ── 读取 Value pin ──
    value = _read_data_input(node_id, "Value", ctx, g, None)
    if value is None:
        return  # pin 未连线且无默认值 → 不操作

    from Application.Core.Scene.SceneManager import SceneManager
    registered = SceneManager.GetRegisteredComponents()
    comp_cls = registered.get(comp_name)

    if comp_cls is None or not SceneManager.HasComponent(eid, comp_cls):
        print(f"[ComponentSetProperty] Entity #{eid}: no '{comp_name}'")
        return

    try:
        comp = SceneManager.GetComponent(eid, comp_cls)
        if hasattr(comp, prop_name):
            setattr(comp, prop_name, value)
            print(f"[ComponentSetProperty] #{eid}.{comp_name}.{prop_name} = {value}")
        else:
            print(f"[ComponentSetProperty] '{comp_name}' has no property '{prop_name}'")
    except Exception as e:
        print(f"[ComponentSetProperty] Failed: {e}")


register_evaluator("ComponentSetProperty", _eval_component_set_property)
