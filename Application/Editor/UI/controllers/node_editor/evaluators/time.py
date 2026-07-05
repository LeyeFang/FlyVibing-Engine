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
