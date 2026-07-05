"""
Evaluators: 数学节点 (Add, Subtract, Multiply, Divide, RandomUniform, RandomGaussian)。

纯函数节点 — 无 exec 引脚，通过 data 连线自动求值。
执行时从上游 data 连线读取 input pin 的值，计算后写入 output pin。
"""

import random

from ..evaluator_engine import ExecutionContext, GraphEvaluator, register_evaluator


# ── 辅助：读取 data input pin 的值 ────────────────────────────

def _read_data_input(node_id: int, pin_name: str, ctx: ExecutionContext,
                     g: GraphEvaluator, default: float = 0.0) -> float:
    """读取指定 data input pin 的值，若未连接则返回 default。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "input":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                val = g._read_input(inst_pin_id, ctx)
                if val is not None:
                    return float(val)
    return default


def _write_data_output(node_id: int, pin_name: str, value: float,
                       ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """将值写入指定 data output pin。"""
    inst = g._canvas.nodes[node_id]
    nd = g._types[inst.node_type]
    for p in nd.pins:
        if p.name == pin_name and p.direction == "output":
            inst_pin_id = inst.pin_ids.get(p.name)
            if inst_pin_id is not None:
                ctx.set_pin(inst_pin_id, value)


# ── 四则运算 ─────────────────────────────────────────────────

def _eval_add(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    a = _read_data_input(node_id, "A", ctx, g)
    b = _read_data_input(node_id, "B", ctx, g)
    _write_data_output(node_id, "Result", a + b, ctx, g)

register_evaluator("MathAdd", _eval_add)


def _eval_subtract(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    a = _read_data_input(node_id, "A", ctx, g)
    b = _read_data_input(node_id, "B", ctx, g)
    _write_data_output(node_id, "Result", a - b, ctx, g)

register_evaluator("MathSubtract", _eval_subtract)


def _eval_multiply(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    a = _read_data_input(node_id, "A", ctx, g)
    b = _read_data_input(node_id, "B", ctx, g)
    _write_data_output(node_id, "Result", a * b, ctx, g)

register_evaluator("MathMultiply", _eval_multiply)


def _eval_divide(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    a = _read_data_input(node_id, "A", ctx, g)
    b = _read_data_input(node_id, "B", ctx, g)
    result = a / b if b != 0.0 else 0.0
    _write_data_output(node_id, "Result", result, ctx, g)

register_evaluator("MathDivide", _eval_divide)


# ── 随机 ─────────────────────────────────────────────────────

def _eval_random_uniform(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    lo = _read_data_input(node_id, "Min", ctx, g, 0.0)
    hi = _read_data_input(node_id, "Max", ctx, g, 1.0)
    _write_data_output(node_id, "Result", random.uniform(lo, hi), ctx, g)

register_evaluator("MathRandomUniform", _eval_random_uniform)


def _eval_random_gaussian(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    mean = _read_data_input(node_id, "Mean", ctx, g, 0.0)
    std = _read_data_input(node_id, "StdDev", ctx, g, 1.0)
    _write_data_output(node_id, "Result", random.gauss(mean, std), ctx, g)

register_evaluator("MathRandomGaussian", _eval_random_gaussian)
