"""Evaluators: UI 节点（SetUIVisible / SetUIText / OnUIClick / GetUIValue）。

语义:
  - `SetUIVisible`：写 `RuntimeUILayer` 的运行期显隐覆盖（不碰 `.scene`）；
    目标优先用 `Entity` 连线，其次用 `props.target`（实体名）。
  - `SetUIText`：写标签的运行期文本覆盖（不碰 `.scene`）；`Text` 引脚优先，
    其次 `props.text`；空串 = 清除覆盖，回落到 `UILabel.text`。
  - `OnUIClick`：图入口；`RuntimeNodeLayer` 把 `RuntimeUILayer.drain_events()` 的每条
    事件作为 `ctx.input_event`（kind=`ui_event`）触发本节点，按 `props.action` / `props.name`
    过滤（空 = 不过滤）。
  - `GetUIValue`：读控件当前值（开关 0/1、滑条数值、选择下标），纯数据节点。
  - 干跑：只记日志（`set_ui_visible` / `set_ui_text` / `ui_click` / `get_ui_value`），零副作用。
"""

from __future__ import annotations

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator
from .entity.helpers import resolve_entity_id
from .inputs import read_pin


def _layer():
    """延迟导入（节点求值器不常驻 Runtime 依赖）。"""
    from Application.Runtime.RuntimeUILayer import RuntimeUILayer
    return RuntimeUILayer


def _read_bool(node_id: int, pin_name: str, ctx: ExecutionContext,
               g: GraphEvaluator, default: bool) -> bool:
    val = read_pin(node_id, pin_name, ctx, g, None)
    if val is None:
        return bool(default)
    if isinstance(val, str):
        return val.strip().lower() not in ("", "0", "false", "no", "off")
    try:
        return bool(int(val))
    except (TypeError, ValueError):
        return bool(val)


def _target(node_id: int, pin_name: str, ctx: ExecutionContext,
            g: GraphEvaluator, default_name: str) -> int | str:
    """连线优先（eid），否则用 props 里的实体名。"""
    eid = resolve_entity_id(node_id, pin_name, ctx, g)
    if eid is not None and eid >= 0:
        return int(eid)
    return str(default_name or "").strip()


def _eval_set_ui_visible(node_id: int, ctx: ExecutionContext,
                         g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    target = _target(node_id, "Entity", ctx, g, inst.props.get("target", ""))
    visible = _read_bool(node_id, "Visible", ctx, g,
                         bool(inst.props.get("visible", True)))

    if ctx.dry_run:
        ctx.emit_log(node_id, "SetUIVisible", "set_ui_visible",
                     f"target={target!r}, visible={visible}")
        return

    if not target:
        ctx.emit_log(node_id, "SetUIVisible", "skip", "no target (wire Entity or set props.target)")
        return
    try:
        ok = _layer().set_visible(target, visible)
    except Exception as e:  # noqa: BLE001 — 无 UI 层（纯逻辑测试）
        ctx.emit_log(node_id, "SetUIVisible", "skip", f"no UI layer: {e!r}")
        return
    if not ok:
        ctx.emit_log(node_id, "SetUIVisible", "skip", f"UI element not found: {target!r}")


def _truthy_text(text) -> bool:
    return str(text or "").strip().lower() not in ("", "any", "*")


def _eval_set_ui_text(node_id: int, ctx: ExecutionContext,
                      g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    target = _target(node_id, "Entity", ctx, g, inst.props.get("target", ""))
    raw = read_pin(node_id, "Text", ctx, g, None)
    text = str(raw) if raw is not None else str(inst.props.get("text", "") or "")

    if ctx.dry_run:
        ctx.emit_log(node_id, "SetUIText", "set_ui_text",
                     f"target={target!r}, text={text!r}")
        return

    if not target:
        ctx.emit_log(node_id, "SetUIText", "skip",
                     "no target (wire Entity or set props.target)")
        return
    try:
        ok = _layer().set_text(target, text)
    except Exception as e:  # noqa: BLE001 — 无 UI 层（纯逻辑测试）
        ctx.emit_log(node_id, "SetUIText", "skip", f"no UI layer: {e!r}")
        return
    if not ok:
        ctx.emit_log(node_id, "SetUIText", "skip",
                     f"UI element not found: {target!r}")


def _eval_on_ui_click(node_id: int, ctx: ExecutionContext,
                      g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    event = getattr(ctx, "input_event", None)
    if event is None or getattr(event, "kind", "") != "ui_event":
        g.set_state(node_id, "_blocked", True)
        return
    want_action = str(inst.props.get("action", "") or "").strip()
    want_name = str(inst.props.get("name", "") or "").strip()
    if _truthy_text(want_action) and str(getattr(event, "action", "")) != want_action:
        g.set_state(node_id, "_blocked", True)
        return
    if _truthy_text(want_name) and str(getattr(event, "name", "")) != want_name:
        g.set_state(node_id, "_blocked", True)
        return
    g.set_state(node_id, "_blocked", False)
    if ctx.dry_run:
        ctx.emit_log(node_id, "OnUIClick", "ui_click",
                     f"name={getattr(event, 'name', '')!r}, "
                     f"action={getattr(event, 'action', '')!r}")
    _write(node_id, "Action", str(getattr(event, "action", "")), ctx, g)
    _write(node_id, "Name", str(getattr(event, "name", "")), ctx, g)
    _write(node_id, "Value", float(getattr(event, "value", 0.0)), ctx, g)
    _write(node_id, "Index", int(getattr(event, "index", 0)), ctx, g)


def _eval_get_ui_value(node_id: int, ctx: ExecutionContext,
                       g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    target = _target(node_id, "Entity", ctx, g, inst.props.get("target", ""))
    value, index = 0.0, 0
    if target:
        try:
            value, index = _layer().read_value(target)
        except Exception:  # noqa: BLE001 — 无 UI 层 → 0
            value, index = 0.0, 0
    _write(node_id, "Value", float(value), ctx, g)
    _write(node_id, "Index", int(index), ctx, g)


def _write(node_id: int, pin_name: str, value, ctx: ExecutionContext,
           g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)


register_evaluator("SetUIVisible", _eval_set_ui_visible)
register_evaluator("SetUIText", _eval_set_ui_text)
register_evaluator("OnUIClick", _eval_on_ui_click)
register_evaluator("GetUIValue", _eval_get_ui_value)
