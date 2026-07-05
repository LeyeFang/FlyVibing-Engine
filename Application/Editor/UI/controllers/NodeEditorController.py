"""
NodeEditorController — 节点编辑器数据层（纯 Python，无 imgui 依赖）

职责:
  - 定义节点/引脚/连线的数据模型
  - 维护节点类型注册表 (_TYPES)
  - 管理画布状态 (NodeCanvas): 节点/连线的 CRUD

架构约束:
  ✅ 可引用: SceneManager, ResourceManager, Event
  ❌ 不可引用: imgui, imgui_bundle, Panel
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

_next_id: int = 1


def _gen_id() -> int:
    """生成全局唯一 ID（线程不安全，仅 UI 线程使用）"""
    global _next_id
    n = _next_id
    _next_id += 1
    return n


@dataclass
class PinDef:
    """引脚定义（类型模板用）"""
    id: int
    name: str
    kind: str          # "exec" | "data"
    direction: str     # "input" | "output"
    data_type: str = "exec"


@dataclass
class NodeTypeDef:
    """节点类型定义（注册表条目）"""
    type_name: str
    label: str
    category: str
    accent_color: tuple[float, float, float]
    pins: list[PinDef]
    props_text: str = ""


@dataclass
class NodeInstance:
    """画布上的节点实例"""
    id: int
    node_type: str
    pos: tuple[float, float] = (0.0, 0.0)
    props: dict = field(default_factory=dict)  # 节点实例自定义属性（如 PrintString 的 message）
    pin_ids: dict[str, int] = field(default_factory=dict)  # pin_name → 实例级唯一 Pin ID


@dataclass
class LinkInstance:
    """画布上的连线实例"""
    id: int
    from_pin: int
    to_pin: int


# ═══════════════════════════════════════════════════════════════
# 节点类型注册表
# ═══════════════════════════════════════════════════════════════

_TYPES: dict[str, NodeTypeDef] = {}


def _reg(t: NodeTypeDef) -> NodeTypeDef:
    """注册一个节点类型到全局注册表"""
    _TYPES[t.type_name] = t
    return t


# ── Runtime 生命周期节点 ──────────────────────────────────────

_reg(NodeTypeDef(
    "OnGameStart", "On Game Start", "Event",
    (0.471, 0.714, 0.471),  # SUCCESS_GREEN
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "Started by Engine",
))

_reg(NodeTypeDef(
    "OnGameStop", "On Game Stop", "Event",
    (0.788, 0.471, 0.471),  # ERROR_RED
    [PinDef(_gen_id(), "exec", "exec", "output")],
    "Triggered on Stop",
))

_reg(NodeTypeDef(
    "OnFrameUpdate", "On Frame Update", "Event",
    (0.420, 0.650, 0.920),  # COLOR_EVENT (淡蓝)
    [
        PinDef(_gen_id(), "exec", "exec", "output"),
        PinDef(_gen_id(), "delta", "data", "output", "float"),
    ],
    "Fires every frame",
))

_reg(NodeTypeDef(
    "CreateWindow", "Create Window", "Action",
    (0.878, 0.416, 0.153),  # BLENDER_ORANGE
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "Title: Game\nSize:  1280x720\nMode: Windowed",
))

_reg(NodeTypeDef(
    "DestroyWindow", "Destroy Window", "Action",
    (0.878, 0.416, 0.153),  # BLENDER_ORANGE
    [
        PinDef(_gen_id(), "exec_in", "exec", "input"),
        PinDef(_gen_id(), "exec_out", "exec", "output"),
    ],
    "",
))

_reg(NodeTypeDef(
    "Sequence", "Sequence", "Flow",
    (0.600, 0.600, 0.600),  # COLOR_FLOW (灰)
    [PinDef(_gen_id(), "exec_in", "exec", "input")]
    + [PinDef(_gen_id(), f"out_{i}", "exec", "output") for i in range(3)],
    "Execute in order",
))


# ── 数学节点 (Math) ──────────────────────────────────────────
# 纯函数节点，无 exec 引脚。输出随输入自动更新。
MATH_COLOR = (0.420, 0.550, 0.920)  # 柔蓝

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


# ── 时间节点 (Time) ──────────────────────────────────────────
TIME_COLOR = (0.878, 0.753, 0.314)  # 暖金

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


# ── Entity 生命周期节点 (Entity) ─────────────────────────────
ENTITY_COLOR = (0.314, 0.784, 0.471)  # 青绿

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


# ── 变量节点 (Variable) ──────────────────────────────────────
VAR_COLOR = (0.650, 0.420, 0.920)  # 淡紫

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


# ── Print 节点 (Debug) ───────────────────────────────────────
DEBUG_COLOR = (0.600, 0.600, 0.600)  # 灰色

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


# ═══════════════════════════════════════════════════════════════
# 画布状态
# ═══════════════════════════════════════════════════════════════

class NodeCanvas:
    """节点画布 — 管理节点实例与连线"""

    def __init__(self):
        self._nodes: dict[int, NodeInstance] = {}
        self._links: dict[int, LinkInstance] = {}

    # ── 节点 CRUD ──────────────────────────────────────────

    @property
    def nodes(self) -> dict[int, NodeInstance]:
        return self._nodes

    @property
    def links(self) -> dict[int, LinkInstance]:
        return self._links

    def add_node(self, type_name: str, pos: tuple[float, float]) -> int:
        """添加一个节点实例，返回其 ID。

        为每个 pin 生成实例级唯一 ID（存于 inst.pin_ids），
        避免同类型多节点时 PinId 冲突导致 imgui_node_editor 内部混乱。
        """
        if type_name not in _TYPES:
            return -1
        nid = _gen_id()
        nd = _TYPES[type_name]
        pin_ids = {p.name: _gen_id() for p in nd.pins}
        self._nodes[nid] = NodeInstance(nid, type_name, pos, pin_ids=pin_ids)
        return nid

    def remove_node(self, nid: int) -> None:
        """删除节点及其关联的连线"""
        if nid not in self._nodes:
            return
        inst = self._nodes[nid]
        node_pins = set(inst.pin_ids.values())
        to_del = [
            lid for lid, lk in self._links.items()
            if lk.from_pin in node_pins or lk.to_pin in node_pins
        ]
        for lid in to_del:
            del self._links[lid]
        del self._nodes[nid]

    def add_link(self, from_pin: int, to_pin: int) -> int:
        """添加一条连线，返回连线 ID（重复返回 -1）"""
        for lk in self._links.values():
            if (lk.from_pin == from_pin and lk.to_pin == to_pin) or \
               (lk.from_pin == to_pin and lk.to_pin == from_pin):
                return -1
        lid = _gen_id()
        self._links[lid] = LinkInstance(lid, from_pin, to_pin)
        return lid

    def remove_link(self, lid: int) -> None:
        self._links.pop(lid, None)

    # ── Pin 查找 ───────────────────────────────────────────

    def find_pin_dir(self, pin_id: int) -> Optional[str]:
        """查找实例级 Pin 的方向 ("input" / "output")"""
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return p.direction
        return None

    def find_pin_node(self, pin_id: int) -> Optional[int]:
        """查找实例级 Pin 所属的节点 ID"""
        for nid, inst in self._nodes.items():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return nid
        return None

    def find_pin_name(self, pin_id: int) -> Optional[str]:
        """查找实例级 Pin 的名称 (如 "Value", "exec_in")"""
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return p.name
        return None

    # ── 默认节点 ───────────────────────────────────────────

    def create_default_nodes(self) -> None:
        """创建必要的初始节点 — 仅 3 个事件入口。

        OnGameStart  → 图执行入口
        OnFrameUpdate → 逐帧入口
        OnGameStop   → 清理入口

        其余所有节点通过右键菜单按需创建。
        """
        essential = ["OnGameStart", "OnFrameUpdate", "OnGameStop"]
        for i, tn in enumerate(essential):
            if tn in _TYPES:
                nid = _gen_id()
                nd = _TYPES[tn]
                pin_ids = {p.name: _gen_id() for p in nd.pins}
                self._nodes[nid] = NodeInstance(
                    nid, tn, (80, 80 + i * 200), pin_ids=pin_ids,
                )
