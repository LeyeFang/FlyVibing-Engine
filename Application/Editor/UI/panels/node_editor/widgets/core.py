"""
节点编辑器 — 各节点类型的内联控件 (Widget)。

采用注册表模式：核心节点类型的 widget 函数通过 @register 装饰器注册，
panel.py 只需调用 draw_node_widgets(nid, inst, canvas) 即可自动分发。
扩展节点优先使用 node_pack.py 的声明式 `fields`（由 _draw_declared_fields
通用渲染）；只有需要复杂交互时才在核心添加 @register 自定义控件。
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
    """根据节点类型分发到自定义 widget；扩展节点无自定义控件时渲染声明字段。"""
    fn = _WIDGET_REGISTRY.get(inst.node_type)
    if fn:
        fn(nid, inst, canvas)
        return
    from Application.Core.NodeGraph.node_packs import NodePackRegistry
    fields = NodePackRegistry.fields_for(inst.node_type)
    if fields:
        _draw_declared_fields(nid, inst, fields)


def _draw_declared_fields(nid: int, inst, fields: list[dict]) -> None:
    """渲染 node_pack 声明的通用字段（扩展无需 import Editor）。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)
    for spec in fields:
        if not isinstance(spec, dict):
            continue
        key = str(spec.get("key") or "").strip()
        if not key:
            continue
        label = str(spec.get("label") or key)
        kind = str(spec.get("kind") or "text")
        tag = f"##ext_{key}_{nid}"
        current = inst.props.get(key, spec.get("default"))
        if kind == "serial_port":
            ports = _list_com_ports()
            try:
                from Application.Core.DeviceRegistry import all as _aliases
                ports = ports + ["@" + n for n in sorted(_aliases())]
            except Exception:  # noqa: BLE001 — 无注册表环境降级
                pass
            if ports:
                try:
                    idx = ports.index(str(current or ""))
                except ValueError:
                    idx = -1
                if idx < 0:
                    ports.append(str(current or ""))
                    idx = len(ports) - 1
                changed, new_idx = _ne_combo(label + tag, idx, ports)
                if changed:
                    inst.props[key] = ports[new_idx]
            else:
                changed, text = imgui.input_text(label + tag, str(current or ""))
                if changed:
                    inst.props[key] = text
        elif kind == "int":
            changed, value = imgui.input_int(label + tag, int(current or 0))
            if changed:
                lo, hi = spec.get("min"), spec.get("max")
                if lo is not None:
                    value = max(int(lo), value)
                if hi is not None:
                    value = min(int(hi), value)
                inst.props[key] = value
        elif kind == "float":
            changed, value = imgui.input_float(label + tag, float(current or 0.0))
            if changed:
                inst.props[key] = value
        elif kind == "bool":
            changed, value = imgui.checkbox(label + tag, bool(current))
            if changed:
                inst.props[key] = bool(value)
        elif kind == "enum":
            choices = spec.get("choices") or []
            labels, values = [], []
            for choice in choices:
                if isinstance(choice, (list, tuple)) and len(choice) >= 2:
                    labels.append(str(choice[0]))
                    values.append(choice[1])
                else:
                    labels.append(str(choice))
                    values.append(choice)
            if labels:
                try:
                    idx = values.index(current)
                except ValueError:
                    idx = 0
                changed, new_idx = _ne_combo(label + tag, idx, labels)
                if changed:
                    inst.props[key] = values[new_idx]
        else:  # text
            changed, text = imgui.input_text(label + tag, str(current or ""))
            if changed:
                inst.props[key] = text
    imgui.pop_item_width()


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


