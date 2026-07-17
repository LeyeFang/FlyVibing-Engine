"""
节点编辑器 — 引脚可见性规则。

采用注册表模式：每个节点类型的可见性规则通过 @rule 装饰器注册，
panel.py 只需调用 get_visible_pins(inst, nd, canvas) 即可获取可见引脚列表。
"""

from __future__ import annotations

from typing import Callable

from Application.Editor.UI.controllers.node_editor.component_registry import (
    get_properties,
)


# ═══════════════════════════════════════════════════════════════
# 规则注册表
# ═══════════════════════════════════════════════════════════════

_PIN_RULES: dict[str, Callable] = {}


def rule(node_type: str):
    """装饰器：将函数注册为指定 node_type 的引脚可见性规则。

    使用方式:
        @rule("SerialSend")
        def _serial_send_pins(inst, nd, canvas): ...
    """
    def decorator(fn: Callable) -> Callable:
        _PIN_RULES[node_type] = fn
        return fn
    return decorator


def get_visible_pins(inst, nd, canvas=None) -> list:
    """返回当前节点实例应显示的引脚列表。

    如果该节点类型没有注册规则，则返回全部引脚。
    """
    fn = _PIN_RULES.get(inst.node_type)
    if fn:
        return fn(inst, nd, canvas)
    return list(nd.pins)


# ═══════════════════════════════════════════════════════════════
# 各节点类型的可见性规则
# ═══════════════════════════════════════════════════════════════

@rule("VarSet")
def _v_varset(inst, nd, canvas=None) -> list:
    """Manual 模式隐藏 Value pin；Name 始终用文本框。"""
    mode = inst.props.get("mode", "manual")
    return [p for p in nd.pins
            if p.name not in ("Name",)
            and not (p.name == "Value" and mode == "manual")]


@rule("VarGet")
def _v_varget(inst, nd, canvas=None) -> list:
    """Name 用文本框处理。"""
    return [p for p in nd.pins if p.name != "Name"]


@rule("EntityGet")
def _v_entity_get(inst, nd, canvas=None) -> list:
    """Name 由下拉框处理。"""
    return [p for p in nd.pins if p.name != "Name"]


@rule("VecMath")
def _v_vec_math(inst, nd, canvas=None) -> list:
    """一元操作 (normalize/length) 隐藏 B pin。"""
    op = inst.props.get("operation", "add")
    if op in ("normalize", "length"):
        return [p for p in nd.pins if p.name != "B"]
    return list(nd.pins)


@rule("ScalarMath")
def _v_scalar_math(inst, nd, canvas=None) -> list:
    """自增输入 pin：有连线才显示。"""
    if canvas is None:
        return list(nd.pins)
    max_connected = -1
    for i in range(8):
        pin_name = f"In_{i}"
        pid = inst.pin_ids.get(pin_name)
        if pid is not None:
            if any(lk.to_pin == pid for lk in canvas.links.values()):
                max_connected = i
    show_up_to = max(max_connected + 2, 2)
    visible = []
    for p in nd.pins:
        if p.name.startswith("In_"):
            idx = int(p.name.split("_")[1])
            if idx < show_up_to:
                visible.append(p)
        else:
            visible.append(p)
    return visible


@rule("Random")
def _v_random(inst, nd, canvas=None) -> list:
    """按 mode / distribution 过滤。"""
    mode = inst.props.get("mode", "manual")
    dist = inst.props.get("distribution", "uniform")
    visible = []
    for p in nd.pins:
        if p.name == "Result":
            visible.append(p)
        elif mode == "pin":
            if dist in ("uniform", "discrete") and p.name in ("Min", "Max"):
                visible.append(p)
            elif dist == "gaussian" and p.name in ("Mean", "StdDev"):
                visible.append(p)
    return visible


@rule("RandomSetSeed")
def _v_random_set_seed(inst, nd, canvas=None) -> list:
    """Manual 模式隐藏 Seed pin。"""
    mode = inst.props.get("mode", "manual")
    if mode == "manual":
        return [p for p in nd.pins if p.name != "Seed"]
    return list(nd.pins)


@rule("SerialSend")
def _v_serial_send(inst, nd, canvas=None) -> list:
    """Manual 模式隐藏 Port / BaudRate / Value pin。"""
    mode = inst.props.get("mode", "manual")
    if mode == "manual":
        return [p for p in nd.pins
                if p.name not in ("Port", "BaudRate", "Value")]
    return list(nd.pins)


@rule("ParallelSend")
def _v_parallel_send(inst, nd, canvas=None) -> list:
    """Address 始终由 widget 展示；Manual 模式额外隐藏 Value。"""
    mode = inst.props.get("mode", "manual")
    hidden = {"Address"}
    if mode == "manual":
        hidden.add("Value")
    return [p for p in nd.pins if p.name not in hidden]


@rule("TextFileWrite")
def _v_text_file_write(inst, nd, canvas=None) -> list:
    """FilePath 始终由 widget 展示；Manual 模式隐藏 FileName/Value。"""
    mode = inst.props.get("mode", "manual")
    hidden = {"FilePath"}
    if mode == "manual":
        hidden.update({"FileName", "Value"})
    return [p for p in nd.pins if p.name not in hidden]


@rule("TimeTrigger")
def _v_time_trigger(inst, nd, canvas=None) -> list:
    """动态 exec_out 引脚：有连线的全显示 + 一个空余。"""
    mode = inst.props.get("mode", "manual")
    visible = []

    for p in nd.pins:
        if p.name == "exec_in":
            visible.append(p)
        elif p.name == "Elapsed":
            visible.append(p)
        elif p.name == "Time" and mode == "pin":
            visible.append(p)

    if canvas is not None:
        max_connected = -1
        for i in range(8):
            pin_name = f"out_{i}"
            pin_id = inst.pin_ids.get(pin_name)
            if pin_id is not None:
                has_link = any(
                    lk.from_pin == pin_id
                    for lk in canvas.links.values()
                )
                if has_link:
                    max_connected = i
        show_up_to = max(max_connected + 2, 1)
        for p in nd.pins:
            if p.name.startswith("out_"):
                idx = int(p.name.split("_")[1])
                if idx < show_up_to:
                    visible.append(p)
    else:
        for p in nd.pins:
            if p.name == "out_0":
                visible.append(p)
                break
    return visible


@rule("ComponentAdd")
def _v_component_add(inst, nd, canvas=None) -> list:
    return _component_pins(inst, nd, "Add")


@rule("SetComponent")
def _v_set_component(inst, nd, canvas=None) -> list:
    return _component_pins(inst, nd, "Set")


@rule("GetComponent")
def _v_get_component(inst, nd, canvas=None) -> list:
    return _component_pins(inst, nd, "Get")


def _component_pins(inst, nd, kind: str) -> list:
    """ComponentAdd / SetComponent / GetComponent: 按组件类型过滤属性 Pin。"""
    comp_name = inst.props.get("component", "")
    props = get_properties(comp_name) if comp_name else []
    prop_names = {p.name for p in props}
    visible = []
    for p in nd.pins:
        if p.name in ("exec_in", "exec_out", "Entity"):
            visible.append(p)
        elif p.name in prop_names:
            if kind == "Get":
                visible.append(p)
            else:
                mode = inst.props.get("mode", "manual")
                if mode == "pin":
                    visible.append(p)
    return visible
