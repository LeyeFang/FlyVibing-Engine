"""实体/组件节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from .core import register, _ne_combo, _get_scene_template_names, _get_component_type_names
from Application.Core.NodeGraph.component_registry import get_properties

# ── EntitySpawn ────────────────────────────────────────────

@register("EntitySpawn")
def _draw_entity_spawn_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)

    template = inst.props.get("template", "")
    labels = _get_scene_template_names()
    if not labels:
        labels = ["(no scene)"]

    if not template and labels and labels[0] != "(no scene)":
        inst.props["template"] = labels[0]
        template = labels[0]

    try:
        idx = labels.index(template) if template in labels else 0
    except ValueError:
        idx = 0

    changed, new_idx = _ne_combo(f"##spawn_tpl_{nid}", idx, labels)
    if changed:
        inst.props["template"] = labels[new_idx]

    imgui.same_line()
    imgui.text_disabled("Template")
    imgui.pop_item_width()


# ── EntityGet ──────────────────────────────────────────────

@register("EntityGet")
def _draw_entity_get_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)

    current = inst.props.get("entity_name", "")
    labels = _get_scene_template_names()
    if not labels:
        labels = []

    items = labels + ["+ Custom..."] if labels else ["+ Custom..."]
    try:
        idx = labels.index(current) if current in labels else len(items) - 1
    except ValueError:
        idx = len(items) - 1

    changed, new_idx = _ne_combo(f"##getent_{nid}", idx, items)
    if changed:
        if new_idx < len(labels):
            inst.props["entity_name"] = labels[new_idx]

    if idx >= len(labels) or not labels:
        changed, txt = imgui.input_text(f"##getent_txt_{nid}", current)
        if changed:
            inst.props["entity_name"] = txt

    imgui.same_line()
    imgui.text_disabled("Name")
    imgui.pop_item_width()


# ── ComponentRemove ────────────────────────────────────────

@register("ComponentRemove")
def _draw_component_remove_widgets(nid: int, inst, _canvas) -> None:
    """组件类型下拉选择。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)

    comp_name = inst.props.get("component", "")
    labels = _get_component_type_names()
    if not labels:
        labels = ["(none)"]
    try:
        idx = labels.index(comp_name) if comp_name in labels else 0
    except ValueError:
        idx = 0

    changed, new_idx = _ne_combo(f"##comp_type_{nid}", idx, labels)
    if changed:
        inst.props["component"] = labels[new_idx]

    imgui.same_line()
    imgui.text_disabled("Type")
    imgui.pop_item_width()


# ── GetComponent ───────────────────────────────────────────

@register("GetComponent")
def _draw_component_get_widgets(nid: int, inst, _canvas) -> None:
    """组件类型下拉（仅输出 pin，无 Manual/Pin 切换）。"""
    imgui.dummy(imgui.ImVec2(0, 2))

    comp_name = inst.props.get("component", "")
    labels = _get_component_type_names()
    if not labels:
        labels = ["(none)"]

    if not comp_name and labels and labels[0] != "(none)":
        inst.props["component"] = labels[0]
        comp_name = labels[0]

    try:
        idx = labels.index(comp_name) if comp_name in labels else 0
    except ValueError:
        idx = 0

    imgui.push_item_width(110)
    changed, new_idx = _ne_combo(f"##comp_type_{nid}", idx, labels)
    if changed:
        inst.props["component"] = labels[new_idx]
    imgui.pop_item_width()
    imgui.same_line()
    imgui.text_disabled("Type")


# ── ComponentAdd / SetComponent ────────────────────────────

@register("ComponentAdd")
def _draw_component_add_widgets(nid: int, inst, _canvas) -> None:
    _draw_component_add_or_set(nid, inst)

@register("SetComponent")
def _draw_component_set_widgets(nid: int, inst, _canvas) -> None:
    _draw_component_add_or_set(nid, inst)


def _draw_component_add_or_set(nid: int, inst) -> None:
    """ComponentAdd / SetComponent: 组件类型下拉 + Manual/Pin 切换 + 属性行。"""
    imgui.dummy(imgui.ImVec2(0, 2))

    comp_name = inst.props.get("component", "")
    labels = _get_component_type_names()
    if not labels:
        labels = ["(none)"]

    if not comp_name and labels and labels[0] != "(none)":
        inst.props["component"] = labels[0]
        comp_name = labels[0]

    try:
        idx = labels.index(comp_name) if comp_name in labels else 0
    except ValueError:
        idx = 0

    imgui.push_item_width(110)
    changed, new_idx = _ne_combo(f"##comp_type_{nid}", idx, labels)
    if changed:
        inst.props["component"] = labels[new_idx]
        comp_name = labels[new_idx]
    imgui.pop_item_width()
    imgui.same_line()
    imgui.text_disabled("Type")

    props = get_properties(comp_name) if comp_name else []
    if props:
        mode = inst.props.get("mode", "manual")
        imgui.spacing()
        if imgui.radio_button(f"Manual##ca_mode_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(f"Pin##ca_mode_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        if mode == "manual":
            _draw_component_property_rows(nid, inst, comp_name, props)


def _draw_component_property_rows(
    nid: int, inst, comp_name: str, props: list,
) -> None:
    """在 Manual 模式下绘制每个属性的内联控件 + [√] 启用勾选框。"""
    imgui.push_item_width(105)
    for prop in props:
        key = f"{comp_name}.{prop.name}"
        enabled_key = f"{key}.enabled"
        enabled = inst.props.get(enabled_key, True)
        default = list(prop.default) if isinstance(prop.default, tuple) else prop.default

        changed_en, enabled = imgui.checkbox(f"##en_{nid}_{prop.name}", enabled)
        if changed_en:
            inst.props[enabled_key] = enabled
        imgui.same_line()

        if not enabled:
            imgui.begin_disabled(True)

        if prop.widget == "drag_float3":
            val = list(inst.props.get(key, default))
            cfg = prop.widget_config
            changed, new_val = imgui.drag_float3(
                prop.label, val,
                v_speed=cfg.get("speed", 0.1),
                format=cfg.get("format", "%.2f"),
            )
            if changed:
                inst.props[key] = tuple(new_val)

        elif prop.widget == "drag_float":
            val = float(inst.props.get(key, default))
            cfg = prop.widget_config
            changed, new_val = imgui.drag_float(
                prop.label, val,
                v_speed=cfg.get("speed", 0.5),
                v_min=cfg.get("min", None) or 0.0,
                v_max=cfg.get("max", None) or 0.0,
                format=cfg.get("format", "%.2f"),
            )
            if changed:
                inst.props[key] = new_val

        elif prop.widget == "checkbox":
            val = bool(inst.props.get(key, default))
            changed, new_val = imgui.checkbox(prop.label, val)
            if changed:
                inst.props[key] = new_val

        elif prop.widget == "input_int":
            val = int(inst.props.get(key, default))
            cfg = prop.widget_config
            changed, new_val = imgui.input_int(prop.label, val)
            if changed:
                inst.props[key] = new_val

        elif prop.widget == "combo":
            options = prop.widget_config.get("options", [])
            if options:
                val = inst.props.get(key, default)
                try:
                    opt_idx = options.index(val) if val in options else 0
                except ValueError:
                    opt_idx = 0
                changed, new_opt_idx = imgui.combo(prop.label, opt_idx, options)
                if changed:
                    inst.props[key] = options[new_opt_idx]

        if not enabled:
            imgui.end_disabled()
    imgui.pop_item_width()


# ── VecMath ────────────────────────────────────────────────

@register("VecMath")
def _draw_vec_math_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    op = inst.props.get("operation", "add")
    ops = ["Add", "Subtract", "Multiply", "Divide",
           "Dot", "Cross", "Normalize", "Length"]
    try:
        idx = ops.index(op.capitalize()) if op.capitalize() in ops else ops.index(
            next(o for o in ops if o.lower() == op))
    except (ValueError, StopIteration):
        idx = 0
    changed, new_idx = _ne_combo(f"##vec_op_{nid}", idx, ops)
    if changed:
        inst.props["operation"] = ops[new_idx].lower()

    imgui.same_line()
    imgui.text_disabled("Op")
    imgui.pop_item_width()


