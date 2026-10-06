"""Media 节点 widget — widgets 包（注册表见 core.py）。

ShowMedia: 显示上游 Get Entity 的目标名 + 接线提示（编辑器侧无播放 — 仅声明）。
"""

from __future__ import annotations

from imgui_bundle import imgui

from .core import register


def _upstream_entity_get_name(inst, canvas) -> str:
    """沿 Entity 输入 pin 反向找上游 EntityGet 节点, 读其 entity_name prop。"""
    pid = (getattr(inst, "pin_ids", {}) or {}).get("Entity")
    if pid is None or canvas is None:
        return ""
    src_pid = None
    for lk in (getattr(canvas, "links", {}) or {}).values():
        try:
            if int(lk.to_pin) == int(pid):
                src_pid = int(lk.from_pin)
                break
        except (TypeError, ValueError):
            continue
    if src_pid is None:
        return ""
    for sn in (getattr(canvas, "nodes", {}) or {}).values():
        try:
            if sn.node_type == "EntityGet" and src_pid in (sn.pin_ids or {}).values():
                return str((sn.props or {}).get("entity_name", "")).strip()
        except AttributeError:
            continue
    return ""


@register("ShowMedia")
def _draw_show_media_widgets(nid: int, inst, canvas) -> None:
    """目标实体回显 + 运行说明（播放只发生在 PIE/独立运行, 由本节点驱动）。"""
    name = _upstream_entity_get_name(inst, canvas)
    imgui.dummy(imgui.ImVec2(0, 2))
    if name:
        imgui.text_disabled(f"  → {name}")
    else:
        imgui.text_disabled("  → (link Get Entity → Entity)")
    imgui.text_disabled("  plays in PIE · wire on OnFrameUpdate")
    imgui.dummy(imgui.ImVec2(0, 2))
