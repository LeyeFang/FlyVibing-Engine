"""
Evaluators: 时间节点 (TimeGetElapsed, TimeGetDelta, TimeDelay)。
"""

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


def _eval_get_time(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Get Time — 读取指定 Timer 或全局 elapsed_time 写入 Elapsed output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    timer_name = inst.props.get("timer", "")  # 空串 = 全局引擎时间

    if timer_name:
        value = ctx.get_timer(timer_name)
        if value is None:
            value = ctx.elapsed_time  # fallback
    else:
        value = ctx.elapsed_time

    for pin in nd.pins:
        if pin.direction == "output" and pin.name == "Elapsed":
            inst_pin_id = inst.pin_ids.get(pin.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)

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
    """Time Trigger — 引擎时间或命名 Timer 越过阈值时触发 exec_out。

    timer 模式: 使用命名 Timer 的值替代全局 elapsed_time。
    当 timer 值回绕（reset 导致下降）时自动清除阈值记忆以重新 arm。
    """
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    mode = inst.props.get("mode", "manual")
    timer_name = inst.props.get("timer", "")  # 空串 = 全局引擎时间

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

    # ── 读取"当前时间" (timer 或全局) ──
    if timer_name:
        current = ctx.get_timer(timer_name)
        if current is None:
            current = ctx.elapsed_time
        # ★ 安全检查: 若 timer 从未被 SetTimer 显式设置过，不触发
        timer_data = ctx._timers.get(timer_name)
        if timer_data and timer_data.get("_set_count", 0) == 0:
            g.set_state(node_id, "_blocked", True)
            return
    else:
        current = ctx.elapsed_time

    last_fired_at = g.get_state(node_id, "_last_fired_threshold", -1.0)

    # ★ 回绕检测: timer 值下降 (比上次触发时小) → timer 被 reset，清除记忆
    if timer_name and current < last_fired_at and last_fired_at >= 0:
        g.set_state(node_id, "_last_fired_threshold", -1.0)
        last_fired_at = -1.0

    # ── 触发条件 ──
    threshold_changed = (threshold > last_fired_at + 0.0001)
    fired = (current >= threshold >= 0) and threshold_changed

    if fired:
        print(f"[TimeTrigger] t={current:.4f} thr={threshold:.4f}" + (f" timer={timer_name}" if timer_name else ""))

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


# ── Get Date ────────────────────────────────────────────────

def _eval_get_date(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Get Date — 输出当前日期时间字符串。

    Props:
      year, month, day, hour, minute:  bool — 是否包含该组件（默认全 True）
      format:  str — 自定义 strftime 格式串，非空时忽略布尔开关

    输出 pin:
      DateString (string) — 可直连 TextFileWrite.FileName 或 Value
    """
    import datetime

    inst = g._canvas.nodes[node_id]
    fmt = str(inst.props.get("format", "")).strip()

    if not fmt:
        # ── 从布尔开关构建格式串 ──
        show_year = inst.props.get("year", True)
        show_month = inst.props.get("month", True)
        show_day = inst.props.get("day", True)
        show_hour = inst.props.get("hour", True)
        show_minute = inst.props.get("minute", True)

        date_parts: list[str] = []
        time_parts: list[str] = []

        if show_year:
            date_parts.append("%Y")
        if show_month:
            date_parts.append("%m")
        if show_day:
            date_parts.append("%d")
        if show_hour:
            time_parts.append("%H")
        if show_minute:
            time_parts.append("%M")

        if date_parts and time_parts:
            fmt = "-".join(date_parts) + " " + ":".join(time_parts)
        elif date_parts:
            fmt = "-".join(date_parts)
        elif time_parts:
            fmt = ":".join(time_parts)
        else:
            fmt = "%Y-%m-%d %H:%M"  # 全默认

    now = datetime.datetime.now()
    date_str = now.strftime(fmt)

    # ── 写入 DateString output pin ──
    nd = g._types[inst.node_type]
    for pin in nd.pins:
        if pin.name == "DateString" and pin.direction == "output":
            pid = inst.pin_ids.get(pin.name)
            if pid is not None:
                ctx.set_pin(pid, date_str)


register_evaluator("TimeGetDate", _eval_get_date)


# ── NewTimer ────────────────────────────────────────────────

def _eval_new_timer(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """New Timer — 创建一个命名 Timer 并开始计时。

    mode=manual: timer_name 来自 props
    mode=pin:    timer_name 来自 Name input pin
    """
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    mode = inst.props.get("mode", "manual")

    if mode == "manual":
        name = str(inst.props.get("timer_name", "timer"))
    else:
        name_pin = next((p for p in nd.pins if p.name == "Name"), None)
        name = "timer"
        if name_pin is not None:
            inst_pin_id = inst.pin_ids.get(name_pin.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    name = str(val)

    ctx.create_timer(name)


register_evaluator("NewTimer", _eval_new_timer)


# ── SetTimer ────────────────────────────────────────────────

def _eval_set_timer(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Set Timer — 操作命名 Timer。

    operate=reset:   重置 timer 为 0
    operate=set_time: 设置 timer 为指定值 (pin 或 manual)
    """
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    operate = inst.props.get("operate", "reset")
    timer_name = str(inst.props.get("timer_name", ""))

    if not timer_name or not ctx.has_timer(timer_name):
        return

    if operate == "reset":
        ctx.reset_timer(timer_name)
    elif operate == "set_time":
        mode = inst.props.get("mode", "manual")
        if mode == "manual":
            value = float(inst.props.get("value", 0.0))
        else:
            value_pin = next((p for p in nd.pins if p.name == "Value"), None)
            value = 0.0
            if value_pin is not None:
                inst_pin_id = inst.pin_ids.get(value_pin.name)
                if inst_pin_id is not None:
                    val = g._read_input(inst_pin_id, ctx)
                    if val is not None:
                        value = float(val)
        ctx.set_timer(timer_name, value)


register_evaluator("SetTimer", _eval_set_timer)
