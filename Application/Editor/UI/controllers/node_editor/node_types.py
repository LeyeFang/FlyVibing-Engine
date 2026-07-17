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

_SUCCESS_GREEN   = (0.471, 0.714, 0.471)
_ERROR_RED       = (0.788, 0.471, 0.471)
_COLOR_EVENT     = (0.420, 0.650, 0.920)
_COLOR_FLOW      = (0.600, 0.600, 0.600)
_BLENDER_ORANGE  = (0.878, 0.416, 0.153)
MATH_COLOR       = (0.420, 0.550, 0.920)
TIME_COLOR       = (0.878, 0.753, 0.314)
ENTITY_COLOR     = (0.314, 0.784, 0.471)
VAR_COLOR        = (0.650, 0.420, 0.920)
VECTOR_COLOR     = (0.314, 0.710, 0.710)  # 保留兼容，新节点用 MATH_COLOR
DEBUG_COLOR      = (0.600, 0.600, 0.600)
SCENE_COLOR      = (0.878, 0.416, 0.153)  # 场景级操作 (同 Blender Orange)
CAMERA_COLOR     = (0.314, 0.650, 0.920)  # 摄像机操作
COMPONENT_COLOR  = (0.314, 0.710, 0.710)  # 组件操作
IO_COLOR         = (0.878, 0.620, 0.314)  # IO / 串口 / 外部设备
BASIC_COLOR      = (0.580, 0.580, 0.620)  # Basic / 基础值


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
# Flow 节点
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "Sequence", "Sequence", "Flow",
    _COLOR_FLOW,
    [PinDef(_gen_id(), "exec_in", "exec", "input")]
    + [PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(3)],
    "Chain in order",
))

_reg(NodeTypeDef(
    "Branch", "Branch", "Flow",
    _COLOR_FLOW,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Condition", "data", "input", "bool"),
        PinDef(_gen_id(), "True", "exec", "output"),
        PinDef(_gen_id(), "False", "exec", "output"),
    ],
    "If / Else",
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

# ── Compare 比较节点 (纯数据, 运算下拉) ──

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

# ── 统一 Random 节点 (服从全局 Set Seed) ──
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
# Entity 节点 (Entity) — 实体生命周期
# ═══════════════════════════════════════════════════════════════

# ── v2: 类型安全 EntityRef，从 Scene.entities 读取模板 ────────

_reg(NodeTypeDef(
    "EntitySpawn", "Spawn Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Entity", "data", "output", "entity_ref"),
    ],
    "Instantiate from Scene template",
))

_reg(NodeTypeDef(
    "EntityDestroy", "Destroy Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Remove entity instance",
))

# ── 按名称查找已生成 entity ──
_reg(NodeTypeDef(
    "EntityGet", "Get Entity", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Name", "data", "input", "string"),
        PinDef(_gen_id(), "Entity", "data", "output", "entity_ref"),
    ],
    "Find entity by name",
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
    "Add camera component to entity",
))

_reg(NodeTypeDef(
    "EntitySetRenderVisible", "Set Render Visible", "Entity", ENTITY_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "EntityID", "data", "input", "int"),
        PinDef(_gen_id(), "Visible", "data", "input", "bool"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Show or hide entity (MeshRenderer.visible)",
))


# ═══════════════════════════════════════════════════════════════
# Game 节点 (Game) — 游戏级操作 (摄像机 / 生命周期)
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "CameraSetMain", "Set Main Camera", "Game", CAMERA_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Set active render camera",
))

_reg(NodeTypeDef(
    "ExitGame", "Exit Game", "Game", CAMERA_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
    ],
    "Stop GameRuntime",
))


# ═══════════════════════════════════════════════════════════════
# Component 节点 — 通用组件 CRUD
# ═══════════════════════════════════════════════════════════════

# ── ComponentAdd / SetComponent 共用属性 Pin (input) ──
_COMPONENT_PROPERTY_PINS: list = [
    # Transform (默认)
    PinDef(_gen_id(), "Position", "data", "input", "vec3"),
    PinDef(_gen_id(), "Rotation", "data", "input", "vec3"),
    PinDef(_gen_id(), "Scale", "data", "input", "vec3"),
    # MeshRenderer
    PinDef(_gen_id(), "MeshID", "data", "input", "int"),
    PinDef(_gen_id(), "MaterialID", "data", "input", "int"),
    PinDef(_gen_id(), "Visible", "data", "input", "bool"),
]

# ── GetComponent 属性 Pin (output) ──
_COMPONENT_PROPERTY_OUT_PINS: list = [
    PinDef(_gen_id(), "Position", "data", "output", "vec3"),
    PinDef(_gen_id(), "Rotation", "data", "output", "vec3"),
    PinDef(_gen_id(), "Scale", "data", "output", "vec3"),
    PinDef(_gen_id(), "MeshID", "data", "output", "int"),
    PinDef(_gen_id(), "MaterialID", "data", "output", "int"),
    PinDef(_gen_id(), "Visible", "data", "output", "bool"),
]

_reg(NodeTypeDef(
    "ComponentAdd", "Add Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Add component to entity",
))

_reg(NodeTypeDef(
    "ComponentRemove", "Remove Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Remove component from entity",
))

_reg(NodeTypeDef(
    "SetComponent", "Set Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Modify existing component",
))

_reg(NodeTypeDef(
    "GetComponent", "Get Component", "Component", COMPONENT_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "Entity", "data", "input", "entity_ref"),
        *_COMPONENT_PROPERTY_OUT_PINS,
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Read component values",
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
    "Constant", "Scale", "Basic", BASIC_COLOR,
    [
        PinDef(_gen_id(), "Result", "data", "output", "float"),
    ],
    "A number value",
))

_reg(NodeTypeDef(
    "StringConst", "String Constant", "Basic", BASIC_COLOR,
    [
        PinDef(_gen_id(), "Value", "data", "output", "string"),
    ],
    "A string value",
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

# ═══════════════════════════════════════════════════════════════
# IO 节点 — 串口 / 外部设备通信
# ═══════════════════════════════════════════════════════════════

_reg(NodeTypeDef(
    "SerialSend", "Serial Send", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Port", "data", "input", "string"),
        PinDef(_gen_id(), "BaudRate", "data", "input", "int"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Send signal via serial port",
))

_reg(NodeTypeDef(
    "ParallelSend", "Parallel Send", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "Address", "data", "input", "int"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Send uint8 via LPT port",
))

_reg(NodeTypeDef(
    "PathVar", "Path", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "Path", "data", "output", "string"),
    ],
    "Directory or file path",
))

_reg(NodeTypeDef(
    "TextFileWrite", "Write Text File", "IO", IO_COLOR,
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
        PinDef(_gen_id(), "FilePath", "data", "input", "string"),
        PinDef(_gen_id(), "FileName", "data", "input", "string"),
        PinDef(_gen_id(), "Value", "data", "input", "variant"),
    ],
    "Write content to a text file",
))
