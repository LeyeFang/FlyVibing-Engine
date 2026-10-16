"""ExtensionGraph — 宿主提供给扩展的**受限图访问**（`ctx.graph`）。

为什么需要它: 扩展代码位于 `Application/Functions/**`（扩展区），**不允许 import Editor 层**; 但
"面板 ↔ 场景节点"是官方示范的核心体验（例: 设备别名绑定后，把场景里的裸 `COMx`
一键迁到 `@别名`）。本桥接是唯一合法途径，且刻意保持**最小面**:

  - 只读: `nodes()` / `find(...)`（props 深拷贝，扩展不能改到内部对象）;
  - 只写: `set_props(node_id, {...})` —— 与 agent 侧 `graph.set_props` op **同一实现**
    （`props.update` 合并; 不做节点增删/连线/删除）;
  - 取画布路径复用 `LiveCommandServer._node_canvas()`（单一事实源，不新增第二套逻辑）。

启用条件: manifest `capabilities` 含 `"graph"`（显式声明 → 宿主才注入 `ctx.graph`）。
协议: `Doc/Dev/device_io_protocol.md` §12（用法）· `Doc/ExtDev/extension_dev_protocol.md` §6。
"""

from __future__ import annotations


class ExtensionGraph:
    """受限图访问门面（全部为 staticmethod —— 无状态, 每次调用取当前活跃画布）。"""

    @staticmethod
    def available() -> bool:
        """当前是否有可用画布（无 UI/未建面板 → False）。"""
        try:
            _canvas()
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def nodes() -> list:
        """全部节点快照: `[{id, type, props}]`（props 为副本）。"""
        return [
            {"id": int(nid), "type": inst.node_type, "props": dict(inst.props)}
            for nid, inst in _canvas().nodes.items()
        ]

    @staticmethod
    def find(prop: str, equals=None, prefix: str | None = None) -> list:
        """按 props 过滤节点 → `[{id, type, props}]`。

        `equals` 精确匹配; `prefix` 前缀匹配（例: `find("port", prefix="@")` 找别名引用）。
        """
        out = []
        for item in ExtensionGraph.nodes():
            value = item["props"].get(prop)
            if equals is not None and value != equals:
                continue
            if prefix is not None and not (isinstance(value, str) and value.startswith(prefix)):
                continue
            out.append(item)
        return out

    @staticmethod
    def set_props(node_id: int, fields: dict) -> dict:
        """合并写入节点 props（与 `graph.set_props` op 同路径）。返回写入后的 props。"""
        canvas = _canvas()
        inst = canvas.nodes.get(int(node_id))
        if inst is None:
            raise ValueError(f"node {node_id} not found")
        inst.props.update(dict(fields or {}))
        return dict(inst.props)


def _canvas():
    """与 agent 侧 ops 同一取画布路径（单一事实源）。"""
    from Application.Editor.Services.LiveCommandServer import _node_canvas
    return _node_canvas()
