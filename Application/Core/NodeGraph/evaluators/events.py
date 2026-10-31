"""
Evaluators: 事件节点 + Input 数据节点。

事件节点 (OnGameStart/OnFrameUpdate/OnGameStop) 仅作为遍历入口；
OnKeyPressed / OnKeyReleased / OnMouseClicked 在 trigger() 时按
ExecutionContext.input_event 过滤，不匹配则 _blocked。

Input 数据节点 (IsKeyDown / IsMouseButtonDown / GetMousePosition) 懒求值，
读取 ExecutionContext.input（RuntimeInputFrame 快照）。
"""

from __future__ import annotations

from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from Application.Core.Events.Enum.InputEnum import KeyModifier
from Application.Core.Input.InputBinding import (
    resolve_key_code,
    resolve_mod_mask,
    resolve_mouse_button,
)


def _eval_event(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    pass  # 生命周期事件节点不执行逻辑，仅作为遍历起点


def _write(node_id: int, pin_name: str, value: Any,
           ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)


def _blocked(node_id: int, g: GraphEvaluator, value: bool) -> None:
    g.set_state(node_id, "_blocked", bool(value))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _mods_match(inst, event) -> bool:
    want = resolve_mod_mask(inst.props.get("mods", "any"))
    if want < 0:
        return True
    mask = KeyModifier.SHIFT | KeyModifier.CTRL | KeyModifier.ALT
    return (int(event.mods) & int(mask)) == want


def _eval_on_key_pressed(node_id: int, ctx: ExecutionContext,
                         g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    event = ctx.input_event
    if event is None or event.kind not in ("key_press", "key_repeat"):
        _blocked(node_id, g, True)
        return
    if event.kind == "key_repeat" and not _truthy(inst.props.get("repeat", False)):
        _blocked(node_id, g, True)
        return
    key = resolve_key_code(inst.props.get("key", "Space"))
    if int(event.key) != key or not _mods_match(inst, event):
        _blocked(node_id, g, True)
        return
    _blocked(node_id, g, False)
    _write(node_id, "Key", int(event.key), ctx, g)
    _write(node_id, "Mods", int(event.mods), ctx, g)


def _eval_on_key_released(node_id: int, ctx: ExecutionContext,
                          g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    event = ctx.input_event
    if event is None or event.kind != "key_release":
        _blocked(node_id, g, True)
        return
    key = resolve_key_code(inst.props.get("key", "Space"))
    if int(event.key) != key or not _mods_match(inst, event):
        _blocked(node_id, g, True)
        return
    _blocked(node_id, g, False)
    _write(node_id, "Key", int(event.key), ctx, g)
    _write(node_id, "Mods", int(event.mods), ctx, g)


def _eval_on_mouse_clicked(node_id: int, ctx: ExecutionContext,
                           g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    event = ctx.input_event
    if event is None or event.kind != "mouse_click":
        _blocked(node_id, g, True)
        return
    want = resolve_mouse_button(inst.props.get("button", "Left"))
    if want >= 0 and int(event.button) != want:
        _blocked(node_id, g, True)
        return
    if not _mods_match(inst, event):
        _blocked(node_id, g, True)
        return
    _blocked(node_id, g, False)
    _write(node_id, "Button", int(event.button), ctx, g)
    _write(node_id, "Mods", int(event.mods), ctx, g)
    _write(node_id, "X", int(event.x), ctx, g)
    _write(node_id, "Y", int(event.y), ctx, g)


def _eval_is_key_down(node_id: int, ctx: ExecutionContext,
                      g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    frame = getattr(ctx, "input", None)
    key = resolve_key_code(inst.props.get("key", "Space"))
    down = bool(frame.is_key_down(key)) if frame is not None else False
    _write(node_id, "Down", 1 if down else 0, ctx, g)


def _eval_is_mouse_button_down(node_id: int, ctx: ExecutionContext,
                               g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    frame = getattr(ctx, "input", None)
    want = resolve_mouse_button(inst.props.get("button", "Left"))
    if frame is None:
        down = False
    elif want < 0:
        down = bool(frame.mouse_buttons)
    else:
        down = frame.is_mouse_button_down(want)
    _write(node_id, "Down", 1 if down else 0, ctx, g)


def _eval_get_mouse_position(node_id: int, ctx: ExecutionContext,
                             g: GraphEvaluator) -> None:
    frame = getattr(ctx, "input", None)
    _write(node_id, "X", int(frame.mouse_x) if frame is not None else 0, ctx, g)
    _write(node_id, "Y", int(frame.mouse_y) if frame is not None else 0, ctx, g)


register_evaluator("OnGameStart", _eval_event)
register_evaluator("OnFrameUpdate", _eval_event)
register_evaluator("OnGameStop", _eval_event)
register_evaluator("OnKeyPressed", _eval_on_key_pressed)
register_evaluator("OnKeyReleased", _eval_on_key_released)
register_evaluator("OnMouseClicked", _eval_on_mouse_clicked)
register_evaluator("IsKeyDown", _eval_is_key_down)
register_evaluator("IsMouseButtonDown", _eval_is_mouse_button_down)
register_evaluator("GetMousePosition", _eval_get_mouse_position)
