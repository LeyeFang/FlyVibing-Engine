"""
Math / Vector 节点 — ScalarMath, Compare, Random, MakeVec3, BreakVec3, VecMath。
"""

from . import _reg, _gen_id, MATH_COLOR
from ..data_model import NodeTypeDef, PinDef


# ── ScalarMath: 统一下拉 + 自增输入 ──────────────────────────

_reg(NodeTypeDef(
    "ScalarMath", "Scalar Math", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "In_0", "data", "input", "float"),
        PinDef(_gen_id(), "In_1", "data", "input", "float"),
    ] + [
        PinDef(_gen_id(), f"In_{i}", "data", "input", "float") for i in range(2, 8)
    ] + [
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "Sum / Sub / Mul / Div",
))

# ── Compare 比较节点 ──

_reg(NodeTypeDef(
    "Compare", "Compare", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "float"),
        PinDef(_gen_id(), "B", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "bool"),
    ],
    "A > < == != >= <= B",
))

# ── 旧版四则运算 (保留兼容，菜单中不再出现) ──

for _legacy_name, _legacy_label, _legacy_desc in [
    ("MathAdd", "Add", "A + B"),
    ("MathSubtract", "Subtract", "A - B"),
    ("MathMultiply", "Multiply", "A × B"),
    ("MathDivide", "Divide", "A / B"),
]:
    _reg(NodeTypeDef(
        _legacy_name, _legacy_label, "Math", MATH_COLOR,
        [
            PinDef(_gen_id(), "A", "data", "input", "float"),
            PinDef(_gen_id(), "B", "data", "input", "float"),
            PinDef(_gen_id(), "Result", "data", "output", "float"),
        ],
        _legacy_desc,
    ))

# ── Random: 全局 Set Seed ──

_reg(NodeTypeDef(
    "RandomSetSeed", "Set Seed", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Seed", "data", "input", "int"),
    ],
    "Set global random seed",
))

# ── 统一 Random 节点 ──

_reg(NodeTypeDef(
    "Random", "Random", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "Min", "data", "input", "float"),
        PinDef(_gen_id(), "Max", "data", "input", "float"),
        PinDef(_gen_id(), "Mean", "data", "input", "float"),
        PinDef(_gen_id(), "StdDev", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "Uniform / Gaussian / Discrete",
))

# ── 旧版 Random 节点 (保留兼容) ──

_reg(NodeTypeDef(
    "MathRandomUniform", "Random Uniform", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "Min", "data", "input", "float"),
        PinDef(_gen_id(), "Max", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "rand(Min, Max)",
))

_reg(NodeTypeDef(
    "MathRandomGaussian", "Random Gaussian", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "Mean", "data", "input", "float"),
        PinDef(_gen_id(), "StdDev", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "N(Mean, StdDev²)",
))


# ── 向量节点 ──

_reg(NodeTypeDef(
    "MakeVec3", "Make Vec3", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "X", "data", "input", "float"),
        PinDef(_gen_id(), "Y", "data", "input", "float"),
        PinDef(_gen_id(), "Z", "data", "input", "float"),
        PinDef(_gen_id(), "Vec3", "data", "output", "vec3"),
    ],
    "X, Y, Z to Vec3",
))

_reg(NodeTypeDef(
    "BreakVec3", "Break Vec3", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "Vec3", "data", "input", "vec3"),
        PinDef(_gen_id(), "X", "data", "output", "float"),
        PinDef(_gen_id(), "Y", "data", "output", "float"),
        PinDef(_gen_id(), "Z", "data", "output", "float"),
    ],
    "Vec3 to X, Y, Z",
))

_reg(NodeTypeDef(
    "VecMath", "Vec Math", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "vec3"),
        PinDef(_gen_id(), "B", "data", "input", "vec3"),
        PinDef(_gen_id(), "Result", "data", "output", "variant"),
    ],
    "Vector operations",
))
