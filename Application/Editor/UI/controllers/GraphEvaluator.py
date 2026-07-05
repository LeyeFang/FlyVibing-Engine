"""
GraphEvaluator — 节点图执行引擎。

职责:
  - 从事件入口节点出发，沿 exec 连线 DFS 遍历
  - 调用 _EVALUATORS 中注册的节点求值函数
  - 管理 ExecutionContext（deltaTime, elapsedTime, pin 值传递）
  - 管理 NodeState（有状态节点的持久数据，如 Delay 剩余时间）

架构:
  Event 节点 (OnFrameUpdate) → exec 链遍历 → Action/Pure 节点
  每个节点的 data input pin 值来自上游 data 连线（output pin 的值）
  每个节点求值后将结果写入自己的 data output pin
"""

from __future__ import annotations

from typing import Any, Optional
from Application.Core.Timer.Timer import GetRunTime


# ═══════════════════════════════════════════════════════════════
# ExecutionContext
# ═══════════════════════════════════════════════════════════════

class ExecutionContext:
    """单帧内共享的执行上下文。"""

    def __init__(self) -> None:
        self.delta_time: float = 0.0
        self.elapsed_time: float = 0.0
        self._pin_values: dict[int, Any] = {}   # output_pin_id → value

    def set_pin(self, pin_id: int, value: Any) -> None:
        self._pin_values[pin_id] = value

    def get_pin(self, pin_id: int) -> Any:
        return self._pin_values.get(pin_id)


# ═══════════════════════════════════════════════════════════════
# GraphEvaluator
# ═══════════════════════════════════════════════════════════════

class GraphEvaluator:
    """节点图解释器 — 遍历 exec 链，调用求值函数。"""

    def __init__(self, canvas, _TYPES: dict):
        self._canvas = canvas          # NodeCanvas 实例
        self._types = _TYPES           # 节点类型注册表
        self._node_state: dict[int, dict] = {}  # node_id → state dict

    # ── 入口 ───────────────────────────────────────────────

    def trigger(self, event_type: str, ctx: ExecutionContext) -> None:
        """触发指定类型的事件节点，遍历其 exec 链。

        event_type: "OnGameStart" | "OnFrameUpdate" | "OnGameStop"
        """
        for nid, inst in self._canvas.nodes.items():
            nd = self._types.get(inst.node_type)
            if nd and nd.category == "Event" and inst.node_type == event_type:
                self._walk_exec(nid, ctx)

    # ── exec 链遍历 ────────────────────────────────────────

    def _walk_exec(self, node_id: int, ctx: ExecutionContext) -> None:
        """从给定节点出发，执行它，然后跟随 exec output pin 走向下游。"""
        inst = self._canvas.nodes.get(node_id)
        if inst is None:
            return
        nd = self._types.get(inst.node_type)
        if nd is None:
            return

        # ── 求值当前节点 ──
        fn = _EVALUATORS.get(inst.node_type)
        if fn:
            try:
                fn(node_id, ctx, self)
            except Exception as e:
                print(f"[GraphEvaluator] ERROR in node #{node_id} ({inst.node_type}): {e}")

        # ── 检查 blocked 状态（如 Delay 未到期） ──
        if self.get_state(node_id, "_blocked", False):
            return

        # ── 跟随 exec output 引脚（使用实例级 pin ID） ──
        for pin in nd.pins:
            if pin.kind == "exec" and pin.direction == "output":
                inst_pin_id = inst.pin_ids.get(pin.name)
                if inst_pin_id is not None:
                    next_ids = self._downstream_nodes(inst_pin_id)
                    for nid in next_ids:
                        self._walk_exec(nid, ctx)

    # ── 连线查询 ───────────────────────────────────────────

    def _downstream_nodes(self, output_pin_id: int) -> list[int]:
        """返回连接到给定 output pin 的所有节点 ID。"""
        result = []
        for link in self._canvas.links.values():
            if link.from_pin == output_pin_id:
                nid = self._canvas.find_pin_node(link.to_pin)
                if nid is not None and nid not in result:
                    result.append(nid)
        return result

    def _read_input(self, input_pin_id: int, ctx: ExecutionContext) -> Any:
        """读取某个 input pin 的值 — 沿 data 连线向上游查找 output pin 的值。"""
        for link in self._canvas.links.values():
            if link.to_pin == input_pin_id:
                return ctx.get_pin(link.from_pin)
        return None

    # ── 节点状态（有状态节点如 Delay） ─────────────────────

    def get_state(self, node_id: int, key: str, default: Any = None) -> Any:
        if node_id not in self._node_state:
            self._node_state[node_id] = {}
        return self._node_state[node_id].get(key, default)

    def set_state(self, node_id: int, key: str, value: Any) -> None:
        if node_id not in self._node_state:
            self._node_state[node_id] = {}
        self._node_state[node_id][key] = value


# ═══════════════════════════════════════════════════════════════
# 求值函数注册表
# ═══════════════════════════════════════════════════════════════

_EVALUATORS: dict[str, callable] = {}


def register_evaluator(type_name: str, fn: callable) -> None:
    """注册一个节点类型的求值函数。"""
    _EVALUATORS[type_name] = fn


# ═══════════════════════════════════════════════════════════════
# 内置求值函数
# ═══════════════════════════════════════════════════════════════

# ── 事件节点（空函数，仅作为入口标记） ──

def _eval_event(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    pass  # 事件节点不执行逻辑，仅作为遍历起点

register_evaluator("OnGameStart", _eval_event)
register_evaluator("OnFrameUpdate", _eval_event)
register_evaluator("OnGameStop", _eval_event)


# ── 时间节点 ──

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

    # 检查是否到期
    elapsed = ctx.elapsed_time - g.get_state(node_id, "start_time", 0.0)
    if elapsed < g.get_state(node_id, "delay_seconds", 0.0):
        # 未到期 — 标记为 blocked，由外部跳过 exec_out 遍历
        g.set_state(node_id, "_blocked", True)
    else:
        g.set_state(node_id, "_blocked", False)
        g.set_state(node_id, "started", False)  # 重置，允许下次重新计时

register_evaluator("TimeDelay", _eval_delay)


# ── Print 节点 ──

def _eval_print(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Print — 读取 Value input pin，打印到控制台。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    val_pin = next((p for p in nd.pins if p.name == "Value"), None)
    if val_pin is None:
        return
    inst_pin_id = inst.pin_ids.get(val_pin.name)
    if inst_pin_id is None:
        return
    value = g._read_input(inst_pin_id, ctx)
    print(f"[Node:Print] {value}")

register_evaluator("Print", _eval_print)


# ── PrintString 节点 ──

def _eval_print_string(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """PrintString — 打印节点内自定义文本框的内容。"""
    inst = g._canvas.nodes.get(node_id)
    if inst is None:
        return
    message = inst.props.get("message", "")
    print(f"[PrintString] {message}")

register_evaluator("PrintString", _eval_print_string)
