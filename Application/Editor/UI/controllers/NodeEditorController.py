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
        """添加一个节点实例，返回其 ID"""
        if type_name not in _TYPES:
            return -1
        nid = _gen_id()
        self._nodes[nid] = NodeInstance(nid, type_name, pos)
        return nid

    def remove_node(self, nid: int) -> None:
        """删除节点及其关联的连线"""
        if nid not in self._nodes:
            return
        nd = _TYPES.get(self._nodes[nid].node_type)
        if nd:
            node_pins = {p.id for p in nd.pins}
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
        """查找 Pin 的方向 ("input" / "output")"""
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if p.id == pin_id:
                        return p.direction
        return None

    def find_pin_node(self, pin_id: int) -> Optional[int]:
        """查找 Pin 所属的节点 ID"""
        for nid, inst in self._nodes.items():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if p.id == pin_id:
                        return nid
        return None

    # ── 默认节点 ───────────────────────────────────────────

    def create_default_nodes(self) -> None:
        """创建一组默认的 Runime 生命周期节点（用于演示/初始状态）"""
        types = [
            "OnGameStart", "OnFrameUpdate", "Sequence",
            "CreateWindow", "DestroyWindow", "OnGameStop",
        ]
        for i, tn in enumerate(types):
            if tn in _TYPES:
                nid = _gen_id()
                self._nodes[nid] = NodeInstance(nid, tn, (60, 60 + i * 190))
