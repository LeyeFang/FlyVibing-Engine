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
DEBUG_COLOR     = (0.600, 0.600, 0.600)


# ═══════════════════════════════════════════════════════════════
# Runtime 生命周期节点 (Event)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "OnGameStart", "On Game Start", "Event",
    _SUCCESS_GREEN,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "Started by Engine",
))

_reg(NodeTypeDef(
    "OnGameStop", "On Game Stop", "Event",
    _ERROR_RED,
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "Triggered on Stop",
))

_reg(NodeTypeDef(
    "OnFrameUpdate", "On Frame Update", "Event",
    _COLOR_EVENT,
    [
        PinDef(_gen_id(), "exec", "exec", "output"),
        PinDef(_gen_id(), "delta", "data", "output", "float"),
    ],
    "Fires every frame",
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
    "Title: Game\nSize:  1280x720\nMode: Windowed",
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
    "Execute in order",
))


# ═══════════════════════════════════════════════════════════════
# 数学节点 (Math) — 纯函数，无 exec 引脚
# ═══════════════════════════════════════════════════════════════

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
    "A ÷ B\nDiv by 0 → 0",
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
    "Uniform / Gaussian",
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
    "Engine elapsed (s)",
))

_reg(NodeTypeDef(
    "TimeGetDelta", "Get Delta Time", "Time", TIME_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Delta", "data", "output", "float"),
    ],
    "Frame delta (s)",
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
    "Fire at engine time T",
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
    "Spawn new entity",
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
    "EntitySetTransform", "Set Transform", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "Position", "data", "input", "vec3"),
        PinDef(_gen_id(), "Rotation", "data", "input", "vec3"),
        PinDef(_gen_id(), "Scale", "data", "input", "vec3"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "pos / rot / scale",
))

_reg(NodeTypeDef(
    "EntityGetTransform", "Get Transform", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Position", "data", "output", "vec3"),
        PinDef(_gen_id(), "Rotation", "data", "output", "vec3"),
        PinDef(_gen_id(), "Scale", "data", "output", "vec3"),
    ],
    "Read pos / rot / scale",
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
    "Attach MeshRenderer",
))

_reg(NodeTypeDef(
    "EntityAddCamera", "Add Camera Component", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Attach Camera",
))

_reg(NodeTypeDef(
    "EntityFindByName", "Find Entity By Name", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "EntityID", "data", "output", "int"),
    ],
    "Search scene",
))

_reg(NodeTypeDef(
    "EntitySetVisibility", "Set Visibility", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "Visible", "data", "input", "bool"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show / Hide",
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
    "Store value by name",
))

_reg(NodeTypeDef(
    "VarGet", "Get Variable", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Value", "data", "output", "variant"),
    ],
    "Read value by name",
))

_reg(NodeTypeDef(
    "Constant", "Constant", "Variable", VAR_COLOR,
    [
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "Fixed float value",
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
    "Print to console",
))

_reg(NodeTypeDef(
    "PrintString", "Print String", "Debug", DEBUG_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Print custom message",
))
