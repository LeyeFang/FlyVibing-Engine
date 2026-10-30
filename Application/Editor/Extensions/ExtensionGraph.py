"""ExtensionGraph — 宿主提供给扩展的受限图访问（`ctx.graph`）。

为什么需要它: 扩展代码位于 `Application/Functions/**`（扩展区），**不允许 import Editor 层**;
"面板 ↔ 场景节点"是官方示范的核心体验（例如设备别名绑定后，把场景里的裸 `COMx`
一键迁到 `@别名`）。本桥接是唯一合法途径：

  - 只读: `nodes(...)` / `find(...)`（props 深拷贝，扩展不能改到内部对象）；
  - 写入: `set_props` / `update_node`（props/alias/description）；
  - 节点生命周期: `add_node` / `remove_node`（默认仅限本扩展 owner 的节点）；
  - 连线: `add_link` / `remove_link`（至少一端属于本扩展）；
  - `request_redraw()`: 标记画布 revision + 请求 ImGui 下一帧重绘。

取画布路径复用 `LiveCommandServer._node_canvas()`（单一事实源，不新增第二套逻辑）。
启用条件: manifest `capabilities` 含 `"graph"`（显式声明 → 宿主才注入 `ctx.graph`）。
协议: `Doc/Dev/device_io_protocol.md` §10 · `Doc/ExtDev/extension_dev_protocol.md` §6。
"""

from __future__ import annotations

from typing import Any


class ExtensionGraph:
    """受限图访问门面（每个扩展一个实例，绑定 owner_id）。"""

    def __init__(self, owner_id: str = "") -> None:
        self.owner_id = str(owner_id or "").strip()

    # ── 只读 ────────────────────────────────────────────────────

    def available(self) -> bool:
        """当前是否有可用画布（无 UI/未建面板 → False）。"""
        try:
            _canvas()
            return True
        except Exception:  # noqa: BLE001
            return False

    @property
    def revision(self) -> int:
        """当前画布 revision（扩展可轮询；通常直接用 request_redraw）。"""
        return int(getattr(_canvas(), "revision", 0))

    def nodes(self, *, type_prefix: str | None = None,
              owner: str | None = None, owned_only: bool = False) -> list[dict]:
        """节点快照 `[{id, type, owner, signature, alias, description, props}]`。

        - `type_prefix`: 只看某前缀（例如 `"ext.<id>."`）；
        - `owner`: 只看某个 owner；
        - `owned_only=True`: 只看本扩展 owner 的节点。
        """
        out: list[dict] = []
        for nid, inst in _canvas().nodes.items():
            node_type = str(inst.node_type)
            type_owner = _owner_of(node_type)
            if type_prefix and not node_type.startswith(str(type_prefix)):
                continue
            if owner is not None and type_owner != owner:
                continue
            if owned_only and not self._is_own_owner(type_owner):
                continue
            out.append(_snapshot(nid, inst, type_owner))
        return out

    def find(self, prop: str, equals: Any = None, prefix: str | None = None,
             *, type_prefix: str | None = None, owned_only: bool = False) -> list[dict]:
        """按 props 过滤节点；可选类型前缀/仅本扩展。

        `equals` 精确匹配；`prefix` 前缀匹配（例如 `find("port", prefix="@")`）。
        """
        out = []
        for item in self.nodes(type_prefix=type_prefix, owned_only=owned_only):
            value = item["props"].get(prop)
            if equals is not None and value != equals:
                continue
            if prefix is not None and not (isinstance(value, str) and value.startswith(prefix)):
                continue
            out.append(item)
        return out

    def find_type(self, type_name: str | None = None,
                  prefix: str | None = None, owned_only: bool = False) -> list[dict]:
        """按节点类型精确名或前缀检索；`owned_only=True` 只看本扩展。"""
        items = self.nodes(owned_only=owned_only)
        if type_name is not None:
            items = [item for item in items if item["type"] == str(type_name)]
        if prefix is not None:
            items = [item for item in items if item["type"].startswith(str(prefix))]
        return items

    def owned_nodes(self) -> list[dict]:
        """本扩展拥有的节点（`find_type`/`nodes` 的便捷入口）。"""
        return self.nodes(owned_only=True)

    # ── 写入 ────────────────────────────────────────────────────

    def set_props(self, node_id: int, fields: dict) -> dict:
        """合并写入节点 props，返回写入后的 props。"""
        return self.update_node(node_id, props=fields)["props"]

    def replace_props(self, node_id: int, fields: dict) -> dict:
        """整体覆写节点 props（丢弃未出现在 fields 中的旧键）。"""
        if not isinstance(fields, dict):
            raise ValueError("props must be a dict")
        canvas = _canvas()
        inst = self._require_own(node_id)
        inst.props.clear()
        inst.props.update(dict(fields))
        canvas.mark_changed()
        self._request_repaint()
        return dict(inst.props)

    def update_node(self, node_id: int, props: dict | None = None,
                    alias: str | None = None,
                    description: str | None = None) -> dict:
        """更新本扩展节点（props 合并；alias/description 传入才覆盖）。"""
        canvas = _canvas()
        inst = self._require_own(node_id)
        if props is not None:
            if not isinstance(props, dict):
                raise ValueError("props must be a dict")
            inst.props.update(dict(props))
        if alias is not None:
            inst.alias = str(alias)
        if description is not None:
            inst.description = str(description)
        canvas.mark_changed()
        self._request_repaint()
        return _snapshot(node_id, inst, _owner_of(inst.node_type))

    def add_node(self, type_name: str, position=(80.0, 80.0),
                 props: dict | None = None, alias: str = "",
                 description: str | None = None) -> dict:
        """创建本扩展拥有的节点并返回快照。

        默认拒绝创建 core / 其他扩展的节点；这是避免扩展越权修改主图。
        """
        type_name = str(type_name or "").strip()
        type_owner = _owner_of(type_name)
        if not type_owner:
            raise ValueError(f"unknown node type: {type_name!r}")
        if not self._is_own_owner(type_owner):
            raise PermissionError(
                f"extension {self.owner_id!r} cannot create node type "
                f"{type_name!r} (owner={type_owner!r})"
            )
        if (not isinstance(position, (list, tuple))
                or len(position) < 2):
            raise ValueError("position must be [x, y]")
        if props is not None and not isinstance(props, dict):
            raise ValueError("props must be a dict")
        canvas = _canvas()
        nid = int(canvas.add_node(type_name, (float(position[0]), float(position[1]))))
        if nid < 0:
            raise ValueError(f"cannot add node type {type_name!r}")
        inst = canvas.nodes[nid]
        if props:
            inst.props.update(dict(props))
        if alias:
            inst.alias = str(alias)
        if description is not None:
            inst.description = str(description)
        canvas.mark_changed()
        self._request_repaint()
        return _snapshot(nid, inst, type_owner)

    def remove_node(self, node_id: int) -> bool:
        """删除本扩展拥有的节点（并清理连线）。"""
        canvas = _canvas()
        self._require_own(node_id)
        canvas.remove_node(int(node_id))
        self._request_repaint()
        return True

    # ── 连线 ────────────────────────────────────────────────────

    def add_link(self, from_node: int, from_pin: str,
                 to_node: int, to_pin: str) -> int:
        """连接两个引脚；至少一端必须属于本扩展。"""
        canvas = _canvas()
        from_inst = canvas.nodes.get(int(from_node))
        to_inst = canvas.nodes.get(int(to_node))
        if from_inst is None:
            raise ValueError(f"node {from_node} not found")
        if to_inst is None:
            raise ValueError(f"node {to_node} not found")
        if not (self._is_own_owner(_owner_of(from_inst.node_type))
                or self._is_own_owner(_owner_of(to_inst.node_type))):
            raise PermissionError(
                f"extension {self.owner_id!r} cannot link nodes it does not own"
            )
        from_pid = from_inst.pin_ids.get(str(from_pin))
        to_pid = to_inst.pin_ids.get(str(to_pin))
        if from_pid is None:
            raise ValueError(f"pin {from_pin!r} not found on node {from_node}")
        if to_pid is None:
            raise ValueError(f"pin {to_pin!r} not found on node {to_node}")
        lid = int(canvas.add_link(int(from_pid), int(to_pid)))
        if lid < 0:
            raise ValueError("link already exists")
        self._request_repaint()
        return lid

    def remove_link(self, link_id: int) -> bool:
        """删除至少一端属于本扩展的连线。"""
        canvas = _canvas()
        link = canvas.links.get(int(link_id))
        if link is None:
            return False
        from_nid = canvas.find_pin_node(link.from_pin)
        to_nid = canvas.find_pin_node(link.to_pin)
        owners = {
            _owner_of(canvas.nodes[nid].node_type)
            for nid in (from_nid, to_nid) if nid in canvas.nodes
        }
        if not any(self._is_own_owner(owner) for owner in owners):
            raise PermissionError(
                f"extension {self.owner_id!r} cannot remove a link it does not own"
            )
        canvas.remove_link(int(link_id))
        self._request_repaint()
        return True

    # ── UI 刷新 ─────────────────────────────────────────────────

    def request_redraw(self) -> int:
        """标记画布变更并请求 ImGui 立即重绘（返回新 revision）。"""
        canvas = _canvas()
        revision = canvas.mark_changed()
        self._request_repaint()
        return revision

    @staticmethod
    def _request_repaint() -> None:
        try:
            from imgui_bundle import imgui
            io = imgui.get_io()
            if io is not None:
                try:
                    io.want_repaint = True
                except Exception:  # noqa: BLE001 — 旧版绑定无该字段
                    pass
        except Exception:  # noqa: BLE001 — 无 ImGui 上下文（headless）
            pass

    # ── 内部 ────────────────────────────────────────────────────

    def _is_own_owner(self, owner: str) -> bool:
        return bool(self.owner_id) and str(owner) == self.owner_id

    def _require_own(self, node_id: int):
        canvas = _canvas()
        inst = canvas.nodes.get(int(node_id))
        if inst is None:
            raise ValueError(f"node {node_id} not found")
        owner = _owner_of(inst.node_type)
        if not self._is_own_owner(owner):
            raise PermissionError(
                f"node {node_id} belongs to {owner!r}, not extension {self.owner_id!r}"
            )
        return inst


def _owner_of(node_type: str) -> str:
    from Application.Core.NodeGraph.node_packs import NodePackRegistry
    return str(NodePackRegistry.owner_of(str(node_type)) or "")


def _snapshot(node_id: int, inst, owner: str) -> dict:
    from Application.Core.NodeGraph import _TYPES
    nd = _TYPES.get(inst.node_type)
    return {
        "id": int(node_id),
        "type": str(inst.node_type),
        "owner": owner,
        "signature": str(getattr(nd, "signature", "") or ""),
        "alias": str(getattr(inst, "alias", "") or ""),
        "description": str(getattr(inst, "description", "") or ""),
        "pins": {str(name): int(pid) for name, pid in (inst.pin_ids or {}).items()},
        "props": dict(inst.props),
    }


def _canvas():
    """与 agent 侧 ops 同一取画布路径（单一事实源）。"""
    from Application.Editor.Services.LiveCommandServer import _node_canvas
    return _node_canvas()

