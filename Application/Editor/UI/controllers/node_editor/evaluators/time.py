"""
Evaluators: 时间节点 (TimeGetElapsed, TimeGetDelta, TimeDelay)。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_get_time(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Get Time — 将 elapsed_time 写入 Elapsed output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.direction == "output" and pin.name == "Elapsed":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, ctx.elapsed_time)

register_evaluator("TimeGetElapsed", _eval_get_time)


def _eval_get_delta(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Get Delta Time — 将 delta_time 写入 Delta output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.direction == "output" and pin.name == "Delta":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, ctx.delta_time)

register_evaluator("TimeGetDelta", _eval_get_delta)


def _eval_delay(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Delay — 等待 N 秒后触发 exec_out。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]

    started = g.get_state(node_id, "started", False)
    if not started:
        seconds_pin = next((p for p in nd.pins if p.name == "Seconds"), None)
        seconds = None
        if seconds_pin is not None:
            inst_pin_id = inst.pin_ids.get(seconds_pin.name)
            if inst_pin_id is not None:
                seconds = g._read_input(inst_pin_id, ctx)
        if seconds is None:
            seconds = 0.0
        g.set_state(node_id, "started", True)
        g.set_state(node_id, "start_time", ctx.elapsed_time)
        g.set_state(node_id, "delay_seconds", float(seconds))

    elapsed = ctx.elapsed_time - g.get_state(node_id, "start_time", 0.0)
    if elapsed < g.get_state(node_id, "delay_seconds", 0.0):
        g.set_state(node_id, "_blocked", True)
    else:
        g.set_state(node_id, "_blocked", False)
        g.set_state(node_id, "started", False)

register_evaluator("TimeDelay", _eval_delay)


# ── TimeTrigger ──────────────────────────────────────────────

def _eval_time_trigger(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Time Trigger — 当引擎时间越过阈值时触发 exec_out。

    反复触发: 阈值被更新（增大）后，可再次 fire。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    mode = inst.props.get("mode", "manual")

    # ── 读取阈值 ──
    if mode == "manual":
        threshold = float(inst.props.get("time", 0.0))
    else:
        time_pin = next((p for p in nd.pins if p.name == "Time"), None)
        threshold = 0.0
        if time_pin is not None:
            inst_pin_id = inst.pin_ids.get(time_pin.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    threshold = float(val)

    current = ctx.elapsed_time
    last_fired_at = g.get_state(node_id, "_last_fired_threshold", -1.0)

    # ── 触发条件: 越过阈值 OR 阈值更新到更大值且当前已到达 ──
    threshold_changed = (threshold > last_fired_at + 0.0001)
    fired = (current >= threshold > 0) and threshold_changed

    if fired:
        print(f"[TimeTrigger] t={current:.4f} thr={threshold:.4f}")

    if fired:
        g.set_state(node_id, "_last_fired_threshold", threshold)
        g.set_state(node_id, "_blocked", False)
    else:
        g.set_state(node_id, "_blocked", True)

    # ── 写入 Elapsed output pin ──
    for p in nd.pins:
        if p.name == "Elapsed" and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, current)

register_evaluator("TimeTrigger", _eval_time_trigger)
