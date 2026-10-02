"""
节点编辑器 — 画布状态管理 (NodeCanvas)。

管理节点实例与连线的 CRUD、pin 查找、默认节点创建。
"""

from __future__ import annotations

from typing import Optional

from .data_model import NodeInstance, LinkInstance, _gen_id
from .node_types import _TYPES
from .graph_rules import _NODE_GRAPH_RULES
from . import data_model  # 用于访问 _next_id
from Application.Core.Scene.DataContract import DataContract, register_contract


class NodeCanvas(DataContract):
    """节点画布 — 管理节点实例与连线"""

    def __init__(self):
        self._nodes: dict[int, NodeInstance] = {}
        self._links: dict[int, LinkInstance] = {}

    # ── 属性 ──────────────────────────────────────────────

    @property
    def nodes(self) -> dict[int, NodeInstance]:
        return self._nodes

    @property
    def links(self) -> dict[int, LinkInstance]:
        return self._links

    # ── 节点 CRUD ──────────────────────────────────────────

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

    def find_pin_data_type(self, pin_id: int) -> str:
        """查找实例级 Pin 的 data_type (如 "float", "exec", "vec3")。

        用于连线着色——根据 pin 的数据类型决定连线颜色。
        找不到时返回 "exec"（默认为执行流样式）。
        """
        for inst in self._nodes.values():
            nd = _TYPES.get(inst.node_type)
            if nd:
                for p in nd.pins:
                    if inst.pin_ids.get(p.name) == pin_id:
                        return p.data_type
        return "exec"

    # ── 默认节点 ───────────────────────────────────────────

    def create_default_nodes(self) -> None:
        """创建必要的初始节点 — 仅 3 个事件入口。

        OnGameStart  → 图执行入口
        OnFrameUpdate → 逐帧入口
        OnGameStop   → 清理入口

        其余所有节点通过 Add 菜单按需创建。
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

    # ── 序列化 ───────────────────────────────────────────

    def serialize(self) -> dict:
        """实现 Serializable 协议 — 序列化为纯 dict。"""
        return self.to_dict()

    @classmethod
    def deserialize(cls, data: dict) -> 'NodeCanvas':
        """实现 Serializable 协议 — 从 dict 反序列化。"""
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        """序列化画布状态为纯 dict（可 JSON 导出）。

        Returns:
            {
                "version": "0.1.0",
                "nodes": {str(nid): {...}, ...},
                "links": {str(lid): {...}, ...},
                "next_id": int,
            }
        """
        import dataclasses

        # 收集所有已分配的 ID，确定 next_id 下界
        max_id = 1
        nodes_dict: dict[str, dict] = {}
        for nid, inst in self._nodes.items():
            nd = dataclasses.asdict(inst)
            nodes_dict[str(nid)] = nd
            max_id = max(max_id, nid)
            for pid in inst.pin_ids.values():
                max_id = max(max_id, pid)

        links_dict: dict[str, dict] = {}
        for lid, lk in self._links.items():
            links_dict[str(lid)] = dataclasses.asdict(lk)
            max_id = max(max_id, lid, lk.from_pin, lk.to_pin)

        return {
            "version": "0.1.0",
            "nodes": nodes_dict,
            "links": links_dict,
            "next_id": max_id + 1,
            "_rules": _NODE_GRAPH_RULES,
        }

    @staticmethod
    def from_dict(data: dict) -> 'NodeCanvas':
        """从 dict 恢复画布状态。

        Args:
            data: to_dict() 的输出

        Returns:
            新的 NodeCanvas 实例
        """
        global _next_id
        canvas = NodeCanvas()

        # ── 先恢复 ID 生成器下界（版本兼容补 pin 时生成的 ID 不得与文件内 ID 冲突）──
        data_model._next_id = max(data_model._next_id, int(data.get("next_id", 1)))

        # ── 恢复节点 ──
        for nid_str, nd in data.get("nodes", {}).items():
            nid = int(nid_str)
            ntype = nd["node_type"]
            pins = {k: int(v) for k, v in nd.get("pin_ids", {}).items()}
            tdef = _TYPES.get(ntype)
            if tdef is not None:
                # 向后兼容: 为新版节点类型新增的 pin 补生成实例 ID (如 Init*.device)
                for p in tdef.pins:
                    if p.name not in pins:
                        pins[p.name] = _gen_id()
            canvas._nodes[nid] = NodeInstance(
                id=nid,
                node_type=ntype,
                pos=tuple(nd.get("pos", (0.0, 0.0))),
                props=nd.get("props", {}),
                pin_ids=pins,
            )

        # ── 恢复连线 ──
        for lid_str, ld in data.get("links", {}).items():
            lid = int(lid_str)
            canvas._links[lid] = LinkInstance(
                id=lid,
                from_pin=int(ld["from_pin"]),
                to_pin=int(ld["to_pin"]),
            )

        # ── 恢复 ID 生成器: 已在开头完成（须先于补 pin 生成）──

        return canvas

    def clear(self) -> None:
        """清空画布（保留 _next_id 不重置）。"""
        self._nodes.clear()
        self._links.clear()


# ── 注册到 Serializable 注册表 ──
register_contract("NodeCanvas", NodeCanvas)
