"""
Evaluators: 向量节点 — Make Vec3 / Break Vec3 / Vec Math。
"""

import math as _math

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


# ── 辅助 ──────────────────────────────────────────────────────

def _read_vec3(node_id: int, pin_name: str, ctx: ExecutionContext,
               g: GraphEvaluator, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    """读取 vec3 input pin，兼容 float → 三通道广播。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            pid = inst.pin_ids.get(p.name)
            if pid is not None:
                val = g._read_input(pid, ctx)
                if val is None:
                    return default
                if isinstance(val, (tuple, list)) and len(val) >= 3:
                    return (float(val[0]), float(val[1]), float(val[2]))
                if isinstance(val, (int, float)):
                    return (float(val), float(val), float(val))
    return default


def _write_vec3(node_id: int, pin_name: str, value: tuple[float, float, float],
                ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """把 (x, y, z) 写入 output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            pid = inst.pin_ids.get(p.name)
            if pid is not None:
                ctx.set_pin(pid, value)


def _write_float(node_id: int, pin_name: str, value: float,
                 ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """把标量写入 output pin。"""
    from .math import _write_data_output
    _write_data_output(node_id, pin_name, value, ctx, g)


# ═══════════════════════════════════════════════════════════════
# Make Vec3
# ═══════════════════════════════════════════════════════════════

def _eval_make_vec3(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Make Vec3 — 把 X/Y/Z 三个 float 打包成 vec3。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]

    def _read_scalar(pin_name: str, d: float) -> float:
        for p in nd.pins:
            if p.name == pin_name:
                pid = inst.pin_ids.get(p.name)
                if pid is not None:
                    val = g._read_input(pid, ctx)
                    if val is not None:
                        return float(val)
        return d

    x = _read_scalar("X", 0.0)
    y = _read_scalar("Y", 0.0)
    z = _read_scalar("Z", 0.0)
    _write_vec3(node_id, "Vec3", (x, y, z), ctx, g)

register_evaluator("MakeVec3", _eval_make_vec3)


# ═══════════════════════════════════════════════════════════════
# Break Vec3
# ═══════════════════════════════════════════════════════════════

def _eval_break_vec3(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    v = _read_vec3(node_id, "Vec3", ctx, g)
    _write_float(node_id, "X", v[0], ctx, g)
    _write_float(node_id, "Y", v[1], ctx, g)
    _write_float(node_id, "Z", v[2], ctx, g)

register_evaluator("BreakVec3", _eval_break_vec3)


# ═══════════════════════════════════════════════════════════════
# Vec Math — 统一向量运算（下拉选操作）
# ═══════════════════════════════════════════════════════════════

_UNARY_OPS = frozenset({"normalize", "length"})


def _eval_vec_math(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    op = inst.props.get("operation", "add")
    is_unary = op in _UNARY_OPS

    a = _read_vec3(node_id, "A", ctx, g)
    b = (0.0, 0.0, 0.0)
    if not is_unary:
        b = _read_vec3(node_id, "B", ctx, g)

    if op == "normalize":
        length = _math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
        r = (a[0] / length, a[1] / length, a[2] / length) if length > 0.0001 else (0.0, 0.0, 0.0)
        _write_vec3(node_id, "Result", r, ctx, g)

    elif op == "length":
        _write_float(node_id, "Result", _math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2), ctx, g)

    elif op == "add":
        _write_vec3(node_id, "Result", (a[0] + b[0], a[1] + b[1], a[2] + b[2]), ctx, g)

    elif op == "subtract":
        _write_vec3(node_id, "Result", (a[0] - b[0], a[1] - b[1], a[2] - b[2]), ctx, g)

    elif op == "multiply":
        _write_vec3(node_id, "Result", (a[0] * b[0], a[1] * b[1], a[2] * b[2]), ctx, g)

    elif op == "divide":
        _write_vec3(node_id, "Result", (
            a[0] / b[0] if b[0] != 0 else 0.0,
            a[1] / b[1] if b[1] != 0 else 0.0,
            a[2] / b[2] if b[2] != 0 else 0.0,
        ), ctx, g)

    elif op == "dot":
        _write_float(node_id, "Result", a[0] * b[0] + a[1] * b[1] + a[2] * b[2], ctx, g)

    elif op == "cross":
        _write_vec3(node_id, "Result", (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ), ctx, g)

register_evaluator("VecMath", _eval_vec_math)
