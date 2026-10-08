"""Evaluators: SetText 节点 — 设置 TextDisplay.text 并立即光栅化。

语义:
  - Entity (entity_ref): 目标实体 (需持有 TextDisplay 组件 — 组件=状态载体);
  - Text (string): 新文本内容;
  - 非干跑: 写组件 + TextSystem.refresh → 同帧纹理热更 (帧级原子拍自动覆盖);
  - 干跑: 仅记日志 (set_text), 零副作用。

样式 (字号/粗斜体/颜色/底色) 在组件上, 不经本节点 — 用 SetComponent 节点或编辑器。
"""

from __future__ import annotations

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .entity.helpers import resolve_entity_id


def _read_string_input(node_id: int, pin_name: str,
                       ctx: ExecutionContext, g: GraphEvaluator,
                       default: str = "") -> str:
    """原始读取 string 输入 — 绕过 _read_data_input 的 float() 强转
    (与 entity.helpers.resolve_entity_id 同模式)。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is None:
                return default
            val = g._read_input(inst_pin_id, ctx)
            return default if val is None else str(val)
    return default


def _eval_set_text(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    eid = resolve_entity_id(node_id, "Entity", ctx, g)
    text = _read_string_input(node_id, "Text", ctx, g, "")

    if ctx.dry_run:
        ctx.emit_log(node_id, "SetText", "set_text", f"eid={eid}, text={text!r}")
        return

    if eid is None or eid < 0 or ctx.scene is None or not ctx.scene.EntityExists(eid):
        return

    import esper
    from Application.Core.Scene.BasicComponents import TextDisplay
    if not esper.has_component(eid, TextDisplay):
        ctx.emit_log(node_id, "SetText", "skip", f"entity {eid} has no TextDisplay")
        return

    display = esper.component_for_entity(eid, TextDisplay)
    display.text = text

    engine = getattr(ctx.scene, 'app', None)
    if engine is not None:
        from Application.Functions.Text import TextSystem
        TextSystem.refresh(engine, eid)


register_evaluator("SetText", _eval_set_text)
