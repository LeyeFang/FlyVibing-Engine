"""
节点编辑器 — 节点类型注册表。

所有可用节点类型在此定义并注册到 _TYPES。
新增节点类型只需在此文件中添加一个 _reg() 调用。
"""

from __future__ import annotations

from .data_model import NodeTypeDef, PinDef, _gen_id


# ═══════════════════════════════════════════════════════════════
# 全局注册表
# ═══════════════════════════════════════════════════════════════

_TYPES: dict[str, NodeTypeDef] = {}


def _reg(t: NodeTypeDef) -> NodeTypeDef:
    """注册一个节点类型到全局注册表"""
    _TYPES[t.type_name] = t
    return t


# ═══════════════════════════════════════════════════════════════
# 颜色常量
# ═══════════════════════════════════════════════════════════════

_SUCCESS_GREEN  = (0.471, 0.714, 0.471)
_ERROR_RED      = (0.788, 0.471, 0.471)
_COLOR_EVENT    = (0.420, 0.650, 0.920)
_COLOR_FLOW     = (0.600, 0.600, 0.600)
_BLENDER_ORANGE = (0.878, 0.416, 0.153)
MATH_COLOR      = (0.420, 0.550, 0.920)
TIME_COLOR      = (0.878, 0.753, 0.314)
ENTITY_COLOR    = (0.314, 0.784, 0.471)
VAR_COLOR       = (0.650, 0.420, 0.920)
VECTOR_COLOR    = (0.314, 0.710, 0.710)  # 保留兼容，新节点用 MATH_COLOR
DEBUG_COLOR     = (0.600, 0.600, 0.600)


# ═══════════════════════════════════════════════════════════════
# Runtime 生命周期节点 (Event)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "OnGameStart", "On Game Start", "Event",
    _SUCCESS_GREEN,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "When the game begins",
))

_reg(NodeTypeDef(
    "OnGameStop", "On Game Stop", "Event",
    _ERROR_RED,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "When the game ends",
))

_reg(NodeTypeDef(
    "OnFrameUpdate", "On Frame Update", "Event",
    _COLOR_EVENT,
    [
        PinDef(_gen_id(), "exec", "exec", "output"),
        PinDef(_gen_id(), "delta", "data", "output", "float"),
    ],
    "Every frame",
))


# ═══════════════════════════════════════════════════════════════
# Action 节点
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "CreateWindow", "Create Window", "Action",
    _BLENDER_ORANGE,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Open a game window",
))

_reg(NodeTypeDef(
    "DestroyWindow", "Destroy Window", "Action",
    _BLENDER_ORANGE,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "",
))


# ═══════════════════════════════════════════════════════════════
# Flow 节点
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "Sequence", "Sequence", "Flow",
    _COLOR_FLOW,
    [PinDef(_gen_id(), "exec_in", "exec", "input")]
    + [PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(3)],
    "Chain in order",
))


# ═══════════════════════════════════════════════════════════════
# 数学节点 (Math) — 纯数据，无 exec 引脚
# ═══════════════════════════════════════════════════════════════

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

# ── 旧版四则运算 (保留兼容，菜单中不再出现) ──

_reg(NodeTypeDef(
    "MathAdd", "Add", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "float"),
        PinDef(_gen_id(), "B", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A + B",
))

_reg(NodeTypeDef(
    "MathSubtract", "Subtract", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "float"),
        PinDef(_gen_id(), "B", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A - B",
))

_reg(NodeTypeDef(
    "MathMultiply", "Multiply", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "float"),
        PinDef(_gen_id(), "B", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A × B",
))

_reg(NodeTypeDef(
    "MathDivide", "Divide", "Math", MATH_COLOR,
    [
        PinDef(_gen_id(), "A", "data", "input", "float"),
        PinDef(_gen_id(), "B", "data", "input", "float"),
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A / B",
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
    "Uniform or Gaussian",
))

# ── 旧版 Random 节点 (保留兼容，不再出现在菜单) ──
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


# ═══════════════════════════════════════════════════════════════
# 时间节点 (Time)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "TimeGetElapsed", "Get Time", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Elapsed", "data", "output", "float"),
    ],
    "Time since start",
))

_reg(NodeTypeDef(
    "TimeGetDelta", "Get Delta Time", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Delta", "data", "output", "float"),
    ],
    "Frame time",
))

_reg(NodeTypeDef(
    "TimeDelay", "Delay", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Seconds", "data", "input", "float"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Wait N seconds",
))

_reg(NodeTypeDef(
    "TimeTrigger", "Time Trigger", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Time", "data", "input", "float"),
        PinDef(_gen_id(), "Elapsed", "data", "output", "float"),
    ] + [
        PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(8)
    ],
    "When time reaches T",
))


# ═══════════════════════════════════════════════════════════════
# Entity 节点 (Entity)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "EntityCreate", "Create Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "EntityID", "data", "output", "int"),
    ],
    "Create empty entity",
))

# ── v2: 类型安全 EntityRef ───────────────────────────────────

_reg(NodeTypeDef(
    "EntitySpawn", "Spawn Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Entity", "data", "output", "entity_ref"),
    ],
    "Cube / Camera / Empty",
))

_reg(NodeTypeDef(
    "EntityDestroy", "Destroy Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Remove entity",
))

_reg(NodeTypeDef(
    "EntityAddMesh", "Add Mesh Component", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "MeshID", "data", "input", "int"),
        PinDef(_gen_id(), "MaterialID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add visible mesh",
))

_reg(NodeTypeDef(
    "EntityAddCamera", "Add Camera Component", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add camera",
))

_reg(NodeTypeDef(
    "EntitySetVisibility", "Set Visibility", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "Visible", "data", "input", "bool"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show or hide entity",
))


# ═══════════════════════════════════════════════════════════════
# 向量节点 (Vector) — 纯数据，无 exec 引脚
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 变量节点 (Variable)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "VarSet", "Set Variable", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Write variable",
))

_reg(NodeTypeDef(
    "VarGet", "Get Variable", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Value", "data", "output", "variant"),
    ],
    "Read variable",
))

_reg(NodeTypeDef(
    "Constant", "Constant", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A number value",
))


# ═══════════════════════════════════════════════════════════════
# Debug 节点
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "Print", "Print", "Debug", DEBUG_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Print value",
))

_reg(NodeTypeDef(
    "PrintString", "Print String", "Debug", DEBUG_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Print message",
))
