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

# 全局随机种子（由 RandomSetSeed 节点设置）
_global_rng: random.Random | None = None
_global_rng_seed: int = 0


def _get_global_rng() -> random.Random:
    """获取全局 RNG 实例。若未通过 SetSeed 设置则使用默认模块级 random。"""
    if _global_rng is not None:
        return _global_rng
    return random  # type: ignore[return-value]


def seed_global_rng(seed: int) -> None:
    """公开辅助 — 以确定种子重置全局 RNG（干跑 / 测试 / 校验服务用）。

    与 RandomSetSeed 节点的差异: 本函数对 seed=0 也安装独立 Random 实例，
    保证干跑可复现（RandomSetSeed 的 seed=0 语义 = 回退模块级 random）。
    """
    global _global_rng, _global_rng_seed
    _global_rng_seed = int(seed)
    _global_rng = random.Random(int(seed))


def _eval_random_set_seed(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """RandomSetSeed — 设置全局随机种子。

    Source 选项:
      - manual:   手输整数种子 (可复现)
      - pin:      从上游连线读取 Seed pin (可复现)
      - hardware: 使用 os.urandom(8) 生成不可复现的真随机种子

    向后兼容: 若 source 不存在则 fallback 到 mode 属性。
    """
    global _global_rng, _global_rng_seed
    import os

    inst = g._canvas.nodes[node_id]
    source = inst.props.get("source")
    if source is None:
        mode = inst.props.get("mode", "manual")
        source = mode  # "manual" or "pin"

    if source == "manual":
        seed = int(inst.props.get("seed", 0))
    elif source == "pin":
        seed = int(_read_data_input(node_id, "Seed", ctx, g, 0))
    elif source == "hardware":
        # 限制在 32-bit signed int 范围内 (imgui input_int 的 C++ 绑定上限)
        seed = int.from_bytes(os.urandom(4), "big", signed=True)
        inst.props["seed"] = seed  # 回写供 widget 只读显示
    else:
        seed = int(inst.props.get("seed", 0))

    _global_rng_seed = seed
    _global_rng = random.Random(seed) if seed != 0 else None
    ctx.set_var("_global_random_seed", seed)

register_evaluator("RandomSetSeed", _eval_random_set_seed)


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


# ── Compare 比较节点 ─────────────────────────────────────────

def _eval_compare(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Compare — 根据 operation 属性比较 A 和 B，输出 bool。"""
    a = _read_data_input(node_id, "A", ctx, g, 0.0)
    b = _read_data_input(node_id, "B", ctx, g, 0.0)
    inst = g._canvas.nodes[node_id]
    op = inst.props.get("operation", "gt")

    ops = {
        "gt":  lambda: a > b,
        "lt":  lambda: a < b,
        "eq":  lambda: abs(a - b) < 1e-9,
        "neq": lambda: abs(a - b) >= 1e-9,
        "gte": lambda: a >= b,
        "lte": lambda: a <= b,
    }
    result = ops.get(op, ops["gt"])()
    _write_data_output(node_id, "Result", float(result), ctx, g)

register_evaluator("Compare", _eval_compare)


# ── 统一 Random 节点 (Manual / Pin 双模式, 服从全局 Set Seed) ──

def _eval_random(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    """Random — 支持 Uniform / Gaussian / Discrete 分布，Manual / Pin 双输入模式。

    种子服从全局 RandomSetSeed 节点（若未设置则使用默认随机）。
    """
    inst = g._canvas.nodes[node_id]
    dist = inst.props.get("distribution", "uniform")
    mode = inst.props.get("mode", "manual")

    # 使用全局 RNG（由 RandomSetSeed 设置）
    rng = _get_global_rng()

    if dist == "uniform":
        if mode == "manual":
            lo = inst.props.get("min", 0.0)
            hi = inst.props.get("max", 1.0)
        else:
            lo = _read_data_input(node_id, "Min", ctx, g, 0.0)
            hi = _read_data_input(node_id, "Max", ctx, g, 1.0)
        result = rng.uniform(float(lo), float(hi))
    elif dist == "gaussian":
        if mode == "manual":
            mean = inst.props.get("mean", 0.0)
            std = inst.props.get("stddev", 1.0)
        else:
            mean = _read_data_input(node_id, "Mean", ctx, g, 0.0)
            std = _read_data_input(node_id, "StdDev", ctx, g, 1.0)
        result = rng.gauss(float(mean), float(std))
    else:  # discrete — 范围内整数均匀多项分布
        if mode == "manual":
            lo = int(inst.props.get("min", 0))
            hi = int(inst.props.get("max", 10))
        else:
            lo = int(_read_data_input(node_id, "Min", ctx, g, 0))
            hi = int(_read_data_input(node_id, "Max", ctx, g, 10))
        if lo > hi:
            lo, hi = hi, lo
        result = float(rng.randint(lo, hi))

    _write_data_output(node_id, "Result", result, ctx, g)

register_evaluator("Random", _eval_random)


# ═══════════════════════════════════════════════════════════════
# ScalarMath — 统一下拉 + 自增输入 (Sum / Sub / Mul / Div)
# ═══════════════════════════════════════════════════════════════

def _eval_scalar_math(node_id: int, ctx: ExecutionContext, g: GraphEvaluator) -> None:
    inst = g._canvas.nodes[node_id]
    op = inst.props.get("operation", "sum")
    nd = g._types[inst.node_type]

    # 收集所有已连接的输入值
    values = []
    for i in range(8):
        pin_name = f"In_{i}"
        for p in nd.pins:
            if p.name == pin_name:
                pid = inst.pin_ids.get(p.name)
                if pid is not None:
                    val = g._read_input(pid, ctx)
                    if val is not None:
                        values.append(float(val))

    if not values:
        _write_data_output(node_id, "Result", 0.0, ctx, g)
        return

    if op == "sum":
        result = sum(values)
    elif op == "subtract":
        result = values[0]
        for v in values[1:]:
            result -= v
    elif op == "multiply":
        result = values[0]
        for v in values[1:]:
            result *= v
    elif op == "divide":
        result = values[0]
        for v in values[1:]:
            result = result / v if v != 0.0 else 0.0
    else:
        result = sum(values)

    _write_data_output(node_id, "Result", result, ctx, g)

register_evaluator("ScalarMath", _eval_scalar_math)
