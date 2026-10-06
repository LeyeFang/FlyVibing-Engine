"""
节点编辑器 — 各节点类型的内联控件 (Widget)。

采用注册表模式：每个节点类型的 widget 函数通过 @register 装饰器注册，
panel.py 只需调用 draw_node_widgets(nid, inst, canvas) 即可自动分发。
新增节点类型只需在此文件添加一个 @register 函数，无需修改 panel.py。
"""

from __future__ import annotations

from typing import Callable

from imgui_bundle import imgui

from Application.Core.NodeGraph.component_registry import (
    get_properties,
    get_registered_component_names,
)
# ═══════════════════════════════════════════════════════════════
# Widget 注册表
# ═══════════════════════════════════════════════════════════════

_WIDGET_REGISTRY: dict[str, Callable] = {}


def register(node_type: str):
    """装饰器：将函数注册为指定 node_type 的 widget 绘制函数。

    使用方式:
        @register("SerialSend")
        def _draw_serial_send_widgets(nid, inst, canvas): ...
    """
    def decorator(fn: Callable) -> Callable:
        _WIDGET_REGISTRY[node_type] = fn
        return fn
    return decorator


def draw_node_widgets(nid: int, inst, canvas) -> None:
    """根据节点类型分发到对应的 widget 绘制函数。"""
    fn = _WIDGET_REGISTRY.get(inst.node_type)
    if fn:
        fn(nid, inst, canvas)


# ═══════════════════════════════════════════════════════════════
# 辅助: combo 弹窗
# ═══════════════════════════════════════════════════════════════

def _ne_combo(label: str, idx: int, items: list[str]) -> tuple[bool, int]:
    """node editor 内 combo — 用 BeginCombo/EndCombo 避免 popup 定位偏移。"""
    preview = items[idx] if 0 <= idx < len(items) else ""
    changed = False
    new_idx = idx
    if imgui.begin_combo(label, preview):
        for i, item in enumerate(items):
            selected = (i == idx)
            clicked, _ = imgui.selectable(item, selected)
            if clicked:
                changed = True
                new_idx = i
            if selected:
                imgui.set_item_default_focus()
        imgui.end_combo()
    return changed, new_idx


# ═══════════════════════════════════════════════════════════════
# 静态辅助函数
# ═══════════════════════════════════════════════════════════════

def _list_com_ports() -> list[str]:
    """枚举可用串口。失败时返回空列表。"""
    try:
        import serial.tools.list_ports
        return sorted([p.device for p in serial.tools.list_ports.comports()])
    except Exception:
        return []


def _get_scene_template_names() -> list[str]:
    """从 EditorHost 获取当前 Scene 的实体模板名列表。"""
    from Application.Editor.EditorHost import EditorHost
    scene = EditorHost.get_active_scene()
    if scene is None:
        return []
    return scene.get_entity_names()


def _get_component_type_names() -> list[str]:
    """获取已注册的组件类型名列表。"""
    return get_registered_component_names()


def _collect_var_names(canvas, exclude_nid: int | None = None) -> list[str]:
    """收集画布上所有 VarSet/VarGet 已使用的变量名，去重排序。"""
    names: set[str] = set()
    for nid, inst in canvas.nodes.items():
        if nid == exclude_nid:
            continue
        if inst.node_type in ("VarSet", "VarGet"):
            n = inst.props.get("var_name", "")
            if n:
                names.add(n)
    return sorted(names)


def _draw_var_name_combo(label: str, nid: int, inst, canvas) -> None:
    """绘制变量名选择下拉框：已有名称列表 + 可自定义输入。"""
    existing = _collect_var_names(canvas, nid)
    current = inst.props.get("var_name", "")

    items = existing + ["+ New..."]
    try:
        idx = existing.index(current)
    except ValueError:
        idx = len(existing)

    changed, new_idx = _ne_combo(f"##var_{label}_{nid}", idx, items)
    if changed:
        if new_idx < len(existing):
            inst.props["var_name"] = existing[new_idx]

    if idx >= len(existing) or not existing:
        imgui.push_item_width(90)
        changed, txt = imgui.input_text(
            f"##var_{label}_txt_{nid}", current,
        )
        if changed:
            inst.props["var_name"] = txt
        imgui.pop_item_width()


# ── Timer 名称收集 (用于 TimeTrigger / GetTime 下拉框) ──

def _collect_timer_names(canvas) -> list[str]:
    """收集画布上所有 NewTimer 节点创建的 Timer 名称，去重排序。"""
    names: set[str] = set()
    for nid, inst in canvas.nodes.items():
        if inst.node_type == "NewTimer":
            n = inst.props.get("timer_name", "")
            if n:
                names.add(n)
    return sorted(names)


def _draw_timer_name_combo(label: str, nid: int, inst, canvas) -> None:
    """绘制 Timer 选择下拉框：global + 已有 Timer 列表。丢失则自动回退 global。"""
    existing = _collect_timer_names(canvas)
    current = inst.props.get("timer", "")

    items = ["global"] + existing
    try:
        idx = existing.index(current) + 1 if current else 0
    except ValueError:
        idx = 0  # 未找到 → 回退 global

    changed, new_idx = _ne_combo(f"##timer_{label}_{nid}", idx, items)
    if changed:
        if new_idx == 0:
            inst.props["timer"] = ""  # global
        else:
            inst.props["timer"] = existing[new_idx - 1]


