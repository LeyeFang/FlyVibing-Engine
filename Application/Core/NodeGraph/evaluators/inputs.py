"""节点图输入读取 — 按 `PinDef.data_type` 转换的唯一入口。

设计约定（2026-10-31）:
  - **类型契约的权威是节点类型声明**（`PinDef.data_type`）；求值器只消费，不改写；
  - 每次读取都按声明类型转换：
      string          → str
      bool            → bool（字符串 "0"/"false"/"no"/"off"/"" 视为 False）
      int             → int（先 float 再截断，兼容 "1.5" 这类上游输出）
      float/number    → float
      entity_ref / entity_list / variant / vec3 / device / 其他 → 原样返回
  - 数值转换失败属于**节点级数据错误**: 告警一次（每个节点+引脚+类型），
    返回 default 继续执行，不抛异常、不中断 exec 链。

为什么需要这层:
  旧实现 `evaluators.math._read_data_input` 无条件 `float(val)`，却被 10+ 个模块
  当作公共读取 API 使用 → 字符串 / 实体引用 / variant / vec3 引脚一接就抛
  `ValueError: could not convert string to float`（ENGINE_GAPS O5 即此）。
  这层把「声明类型 → 转换」收敛到一处，避免每个模块各自造绕过助手。
"""

from __future__ import annotations

from typing import Any

from ..evaluator_engine import ExecutionContext, GraphEvaluator

# ── 类型分组 ────────────────────────────────────────────────
_STRING_TYPES = frozenset({"string", "text", "str"})
_BOOL_TYPES = frozenset({"bool", "boolean"})
_INT_TYPES = frozenset({"int", "integer"})
_FLOAT_TYPES = frozenset({"float", "number", "double", "scalar"})

# 未列出的类型一律原样透传（entity_ref / entity_list / variant / vec3 / device / …）

# 告警去重表: (node_id, pin_name, data_type) → 已告警次数
_WARNED: set[tuple[int, str, str]] = set()
_MAX_WARN = 512


def _warn_once(node_id: int, node_type: str, pin_name: str,
               data_type: str, value: Any, default: Any) -> None:
    key = (int(node_id), str(pin_name), str(data_type))
    if key in _WARNED:
        return
    if len(_WARNED) >= _MAX_WARN:
        _WARNED.clear()
    _WARNED.add(key)
    print(
        f"[GraphInput] #{node_id}<{node_type}>{pin_name}: "
        f"{value!r} is not {data_type}; using default {default!r}"
    )


def _coerce(value: Any, data_type: str, default: Any, *,
            node_id: int, node_type: str, pin_name: str) -> Any:
    """按声明类型转换单个值。转换失败 → default（告警一次）。"""
    dt = str(data_type or "").strip().lower()

    # 实体引用 → 数值引脚: 历史图常把 EntityGet.Entity 直接接到 int 引脚，
    # EntityRef 带 .eid，这里先解包再转（不依赖 EntityRef 类型，避免循环 import）。
    if dt in _INT_TYPES or dt in _FLOAT_TYPES:
        eid = getattr(value, "eid", None)
        if isinstance(eid, (int, float)) and not isinstance(eid, bool):
            value = eid

    if dt in _STRING_TYPES:
        return str(value)

    if dt in _BOOL_TYPES:
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "off", "none", "null")
        return bool(value)

    if dt in _INT_TYPES:
        try:
            return int(value) if isinstance(value, bool) else int(float(value))
        except (TypeError, ValueError):
            _warn_once(node_id, node_type, pin_name, data_type, value, default)
            return default

    if dt in _FLOAT_TYPES:
        try:
            return float(value)
        except (TypeError, ValueError):
            _warn_once(node_id, node_type, pin_name, data_type, value, default)
            return default

    return value


def _pin_entry(node_id: int, pin_name: str,
               g: GraphEvaluator) -> tuple[Any, Any]:
    """返回 (节点实例, 输入引脚定义)；任一项缺失返回 None。"""
    inst = g._canvas.nodes.get(node_id)
    if inst is None:
        return None, None
    nd = g._types.get(inst.node_type)
    if nd is None:
        return inst, None
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            return inst, p
    return inst, None


def read_pin(node_id: int, pin_name: str, ctx: ExecutionContext,
             g: GraphEvaluator, default: Any = None) -> Any:
    """读取输入引脚的值（未连接 / 上游为 None → default）。

    转换规则见模块文档；**不抛异常**。
    """
    inst, pin = _pin_entry(node_id, pin_name, g)
    if pin is None:
        return default
    inst_pin_id = inst.pin_ids.get(pin_name)
    if inst_pin_id is None:
        return default
    value = g._read_input(inst_pin_id, ctx)
    if value is None:
        return default
    return _coerce(value, getattr(pin, "data_type", ""), default,
                   node_id=node_id, node_type=inst.node_type, pin_name=pin_name)


def read_raw(node_id: int, pin_name: str, ctx: ExecutionContext,
             g: GraphEvaluator, default: Any = None) -> Any:
    """不做类型转换的原始读取（迁移期兼容用；新代码用 `read_pin`）。"""
    inst, pin = _pin_entry(node_id, pin_name, g)
    if pin is None:
        return default
    inst_pin_id = inst.pin_ids.get(pin_name)
    if inst_pin_id is None:
        return default
    value = g._read_input(inst_pin_id, ctx)
    return default if value is None else value


# ── 便利包装（调用方已明确期望类型时使用）───────────────

def read_float(node_id: int, pin_name: str, ctx: ExecutionContext,
               g: GraphEvaluator, default: float = 0.0) -> float:
    value = read_pin(node_id, pin_name, ctx, g, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_int(node_id: int, pin_name: str, ctx: ExecutionContext,
             g: GraphEvaluator, default: int = 0) -> int:
    value = read_pin(node_id, pin_name, ctx, g, default)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_bool(node_id: int, pin_name: str, ctx: ExecutionContext,
              g: GraphEvaluator, default: bool = False) -> bool:
    value = read_pin(node_id, pin_name, ctx, g, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off", "none", "null")
    return bool(value)


def read_str(node_id: int, pin_name: str, ctx: ExecutionContext,
             g: GraphEvaluator, default: str = "") -> str:
    value = read_pin(node_id, pin_name, ctx, g, default)
    return default if value is None else str(value)
