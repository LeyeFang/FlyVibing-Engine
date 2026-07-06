"""
节点编辑器 — 图执行引擎。

职责:
  - ExecutionContext: 单帧内共享的 pin 值传递上下文
  - GraphEvaluator: 从事件入口出发，沿 exec 连线 DFS 遍历，调用求值函数
  - _EVALUATORS: 节点类型 → 求值函数的注册表
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════
# ExecutionContext
# ═══════════════════════════════════════════════════════════════

class ExecutionContext:
    """单帧内共享的执行上下文。"""

    def __init__(self) -> None:
        self.delta_time: float = 0.0
        self.elapsed_time: float = 0.0
        self._pin_values: dict[int, Any] = {}    # output_pin_id → value
        self._variables: dict[str, Any] = {}      # VarSet/VarGet 的变量存储

    def set_pin(self, pin_id: int, value: Any) -> None:
        self._pin_values[pin_id] = value

    def get_pin(self, pin_id: int) -> Any:
        return self._pin_values.get(pin_id)

    def set_var(self, name: str, value: Any) -> None:
        self._variables[name] = value

    def get_var(self, name: str) -> Any:
        return self._variables.get(name)


# ═══════════════════════════════════════════════════════════════
# 求值函数注册表
# ═══════════════════════════════════════════════════════════════

_EVALUATORS: dict[str, callable] = {}


def register_evaluator(type_name: str, fn: callable) -> None:
    """注册一个节点类型的求值函数。"""
    _EVALUATORS[type_name] = fn


# ═══════════════════════════════════════════════════════════════
# GraphEvaluator
# ═══════════════════════════════════════════════════════════════

class GraphEvaluator:
    """节点图解释器 — 遍历 exec 链，调用求值函数。"""

    def __init__(self, canvas, _TYPES: dict):
        self._canvas = canvas          # NodeCanvas 实例
        self._types = _TYPES           # 节点类型注册表
        self._node_state: dict[int, dict] = {}  # node_id → state dict
        self._eval_guard: set[int] = set()      # 数据节点懒求值环检测

    # ── 入口 ───────────────────────────────────────────────

    def trigger(self, event_type: str, ctx: ExecutionContext) -> None:
        """触发指定类型的事件节点，遍历其 exec 链。

        event_type: "OnGameStart" | "OnFrameUpdate" | "OnGameStop"
        """
        self._eval_guard.clear()  # 每帧重置环检测
        ctx._pin_values.clear()   # 每帧清除 data pin 缓存，强制重新求值
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
        """读取某个 input pin 的值 — 沿 data 连线向上游查找 output pin 的值。

        若上游 output pin 的值尚未被设置（纯数据节点未被求值），
        则自动触发该数据节点的懒求值（递归）。"""
        for link in self._canvas.links.values():
            if link.to_pin == input_pin_id:
                self._ensure_pin_evaluated(link.from_pin, ctx)
                return ctx.get_pin(link.from_pin)
        return None

    # ── 数据节点懒求值 ─────────────────────────────────────

    def _ensure_pin_evaluated(self, output_pin_id: int, ctx: ExecutionContext) -> None:
        """确保某个 output pin 的值已被求值。

        若该 pin 属于纯数据节点（无 exec 引脚）且值尚未计算，
        则递归求值该数据节点。带简单的环检测避免死循环。
        """
        if ctx.get_pin(output_pin_id) is not None:
            return  # 已有值，跳过

        owner_nid = self._canvas.find_pin_node(output_pin_id)
        if owner_nid is None:
            return

        inst = self._canvas.nodes.get(owner_nid)
        if inst is None:
            return

        nd = self._types.get(inst.node_type)
        if nd is None:
            return

        # 环检测：同一帧内同一节点不重复求值
        if owner_nid in self._eval_guard:
            return
        self._eval_guard.add(owner_nid)

        fn = _EVALUATORS.get(inst.node_type)
        if fn:
            try:
                fn(owner_nid, ctx, self)
            except Exception as e:
                print(
                    f"[GraphEvaluator] ERROR in data node "
                    f"#{owner_nid} ({inst.node_type}): {e}"
                )

        self._eval_guard.discard(owner_nid)

    # ── 节点状态（有状态节点如 Delay） ─────────────────────

    def get_state(self, node_id: int, key: str, default: Any = None) -> Any:
        if node_id not in self._node_state:
            self._node_state[node_id] = {}
        return self._node_state[node_id].get(key, default)

    def set_state(self, node_id: int, key: str, value: Any) -> None:
        if node_id not in self._node_state:
            self._node_state[node_id] = {}
        self._node_state[node_id][key] = value
