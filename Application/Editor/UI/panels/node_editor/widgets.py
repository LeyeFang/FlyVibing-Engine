"""
节点编辑器 — 各节点类型的内联控件 (Widget)。

采用注册表模式：每个节点类型的 widget 函数通过 @register 装饰器注册，
panel.py 只需调用 draw_node_widgets(nid, inst, canvas) 即可自动分发。
新增节点类型只需在此文件添加一个 @register 函数，无需修改 panel.py。
"""

from __future__ import annotations

from typing import Callable

from imgui_bundle import imgui

from Application.Editor.UI.controllers.node_editor.component_registry import (
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


# ═══════════════════════════════════════════════════════════════
# Widget 函数 — 每个节点类型一个
# ═══════════════════════════════════════════════════════════════

# ── PrintString ────────────────────────────────────────────

@register("PrintString")
def _draw_print_string_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    msg = inst.props.get("message", "")
    changed, new_msg = imgui.input_text(f"##print_msg_{nid}", msg)
    if changed:
        inst.props["message"] = new_msg
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


# ── Random ─────────────────────────────────────────────────

@register("Random")
def _draw_random_widgets(nid: int, inst, _canvas) -> None:
    """分布选择、模式切换和参数输入框。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    dist = inst.props.get("distribution", "uniform")
    dist_labels = ["Uniform", "Gaussian", "Discrete"]
    dist_keys = ["uniform", "gaussian", "discrete"]
    try:
        dist_idx = dist_keys.index(dist)
    except ValueError:
        dist_idx = 0
    changed, new_idx = _ne_combo(f"##rand_dist_{nid}", dist_idx, dist_labels)
    if changed:
        inst.props["distribution"] = dist_keys[new_idx]

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##rand_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##rand_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        if dist == "uniform":
            v = inst.props.get("min", 0.0)
            changed, nv = imgui.input_float(f"Min##rand_min_{nid}", v)
            if changed:
                inst.props["min"] = nv
            v = inst.props.get("max", 1.0)
            changed, nv = imgui.input_float(f"Max##rand_max_{nid}", v)
            if changed:
                inst.props["max"] = nv
        elif dist == "gaussian":
            v = inst.props.get("mean", 0.0)
            changed, nv = imgui.input_float(f"Mean##rand_mean_{nid}", v)
            if changed:
                inst.props["mean"] = nv
            v = inst.props.get("stddev", 1.0)
            changed, nv = imgui.input_float(f"StdDev##rand_std_{nid}", v)
            if changed:
                inst.props["stddev"] = nv
        else:  # discrete
            v = int(inst.props.get("min", 0))
            changed, nv = imgui.input_int(f"Min##rand_min_{nid}", v)
            if changed:
                inst.props["min"] = nv
            v = int(inst.props.get("max", 10))
            changed, nv = imgui.input_int(f"Max##rand_max_{nid}", v)
            if changed:
                inst.props["max"] = nv

    imgui.pop_item_width()


# ── RandomSetSeed ──────────────────────────────────────────

@register("RandomSetSeed")
def _draw_random_set_seed_widgets(nid: int, inst, _canvas) -> None:
    """Source 下拉: Manual / Pin / Hardware Random。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)

    # ── 向后兼容 ──
    source = inst.props.get("source")
    if source is None:
        source = inst.props.get("mode", "manual")
        inst.props["source"] = source

    source_labels = ["Manual", "Pin", "Hardware Random"]
    source_keys   = ["manual", "pin", "hardware"]
    try:
        src_idx = source_keys.index(source)
    except ValueError:
        src_idx = 0

    changed, new_idx = _ne_combo(f"Source##rss_src_{nid}", src_idx, source_labels)
    if changed:
        inst.props["source"] = source_keys[new_idx]
        source = source_keys[new_idx]

    if source == "manual":
        seed = int(inst.props.get("seed", 0))
        changed, new_seed = imgui.input_int(f"Seed##rss_seed_{nid}", seed)
        if changed:
            inst.props["seed"] = new_seed
    elif source == "hardware":
        # 只读显示上一次生成的种子 (首次为 0，执行后才会更新)
        imgui.begin_disabled(True)
        seed = inst.props.get("seed", 0)
        imgui.input_int(f"Last Seed##rss_seed_{nid}", seed)
        imgui.end_disabled()

    imgui.pop_item_width()


# ── SerialSend ─────────────────────────────────────────────

@register("SerialSend")
def _draw_serial_send_widgets(nid: int, inst, _canvas) -> None:
    """Manual 模式: 端口 + 波特率 + 值 + 格式；Pin 模式: 全部从上游连线。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##ser_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##ser_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        port = str(inst.props.get("port", "COM1"))
        ports = _list_com_ports()
        if ports:
            try:
                idx = ports.index(port)
            except ValueError:
                idx = -1
            if idx < 0:
                ports.append(port)
                idx = len(ports) - 1
            changed, new_idx = _ne_combo(f"Port##ser_port_{nid}", idx, ports)
            if changed:
                inst.props["port"] = ports[new_idx]
        else:
            changed, new_port = imgui.input_text(f"Port##ser_port_{nid}", port)
            if changed:
                inst.props["port"] = new_port

        baud = int(inst.props.get("baud_rate", 9600))
        changed, new_baud = imgui.input_int(f"Baud##ser_baud_{nid}", baud)
        if changed:
            inst.props["baud_rate"] = new_baud

        v = inst.props.get("value", 0.0)
        changed, nv = imgui.input_float(f"Value##ser_val_{nid}", v, format="%.4f")
        if changed:
            inst.props["value"] = nv

        fmt = inst.props.get("format", "bytes")
        fmt_labels = ["Bytes (float32 LE)", "String (UTF-8)"]
        fmt_keys = ["bytes", "string"]
        try:
            fmt_idx = fmt_keys.index(fmt)
        except ValueError:
            fmt_idx = 0
        changed, new_fmt_idx = _ne_combo(f"Format##ser_fmt_{nid}", fmt_idx, fmt_labels)
        if changed:
            inst.props["format"] = fmt_keys[new_fmt_idx]

    imgui.pop_item_width()


# ── ParallelSend ───────────────────────────────────────────

@register("ParallelSend")
def _draw_parallel_send_widgets(nid: int, inst, _canvas) -> None:
    """Address 始终以 combo 展示；Value 受 mode 影响。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    address = int(inst.props.get("address", 0x3FF8))
    addr_labels = ["0x3FF8 (LPT1)", "0x3FF0 (LPT2)", "0x3FE8 (LPT3)"]
    addr_values = [0x3FF8, 0x3FF0, 0x3FE8]
    try:
        idx = addr_values.index(address)
    except ValueError:
        idx = -1
    changed, new_idx = _ne_combo(f"Address##par_addr_{nid}", idx, addr_labels)
    if changed and 0 <= new_idx < len(addr_values):
        inst.props["address"] = addr_values[new_idx]

    mode = inst.props.get("mode", "manual")
    imgui.dummy(imgui.ImVec2(0, 1))
    if imgui.radio_button(f"Manual##par_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##par_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = int(inst.props.get("value", 1))
        changed, nv = imgui.input_int(f"Value (1-255)##par_val_{nid}", v)
        if changed:
            inst.props["value"] = max(1, min(255, nv))

    imgui.pop_item_width()


# ── PathVar ────────────────────────────────────────────────

@register("PathVar")
def _draw_path_var_widgets(nid: int, inst, _canvas) -> None:
    """BrowseMode 切换 (Dir/File) + Browse 按钮 + 路径文本。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)

    browse_mode = inst.props.get("browse_mode", "directory")
    if imgui.radio_button(f"Dir##pv_dir_{nid}", browse_mode == "directory"):
        inst.props["browse_mode"] = "directory"
    imgui.same_line()
    if imgui.radio_button(f"File##pv_file_{nid}", browse_mode == "file"):
        inst.props["browse_mode"] = "file"

    if imgui.button(f"Browse...##pv_btn_{nid}"):
        from Application.Editor.UI.FileDialog import FileDialog
        if browse_mode == "directory":
            FileDialog.open_directory(
                lambda p, i=inst: i.props.__setitem__("path", p),
                start_dir=inst.props.get("path", ""),
            )
        else:
            FileDialog.open_text(
                lambda p, i=inst: i.props.__setitem__("path", p),
                start_dir=inst.props.get("path", ""),
            )

    imgui.same_line()
    current = str(inst.props.get("path", ""))
    if current:
        display = current if len(current) <= 40 else "..." + current[-37:]
        imgui.text_disabled(display)
    else:
        imgui.text_disabled("(no path)")

    imgui.pop_item_width()


# ── TextFileWrite ──────────────────────────────────────────

@register("TextFileWrite")
def _draw_text_file_write_widgets(nid: int, inst, _canvas) -> None:
    """WriteMode + Delimiter 始终显示; FilePath Browse 始终显示;
    Mode 影响 FileName + Value。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)

    # 写模式
    write_mode = inst.props.get("write_mode", "w")
    if imgui.radio_button(f"w (new)##tfw_w_{nid}", write_mode == "w"):
        inst.props["write_mode"] = "w"
    imgui.same_line()
    if imgui.radio_button(f"a (append)##tfw_a_{nid}", write_mode == "a"):
        inst.props["write_mode"] = "a"

    # 间隔符
    delim = inst.props.get("delimiter", "none")
    delim_labels = ["None", "Space", "Newline", "Tab", "Comma"]
    delim_keys = ["none", "space", "newline", "tab", "comma"]
    try:
        delim_idx = delim_keys.index(delim)
    except ValueError:
        delim_idx = 0
    changed, new_idx = _ne_combo(f"Delimiter##tfw_delim_{nid}", delim_idx, delim_labels)
    if changed:
        inst.props["delimiter"] = delim_keys[new_idx]

    imgui.dummy(imgui.ImVec2(0, 2))

    # FilePath Browse
    if imgui.button(f"Browse Dir...##tfw_btn_{nid}"):
        from Application.Editor.UI.FileDialog import FileDialog
        FileDialog.open_directory(
            lambda p, i=inst: i.props.__setitem__("file_path", p),
            start_dir=inst.props.get("file_path", ""),
        )
    imgui.same_line()
    fp = str(inst.props.get("file_path", ""))
    if fp:
        display_fp = fp if len(fp) <= 35 else "..." + fp[-32:]
        imgui.text_disabled(display_fp)
    else:
        imgui.text_disabled("(no dir)")

    imgui.dummy(imgui.ImVec2(0, 2))

    # 模式切换
    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##tfw_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##tfw_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        fname = str(inst.props.get("file_name", "output"))
        changed, nf = imgui.input_text(f"File Name##tfw_fn_{nid}", fname)
        if changed:
            inst.props["file_name"] = nf
        imgui.same_line()
        imgui.text_disabled(".txt")

        v = str(inst.props.get("value", ""))
        changed, nv = imgui.input_text(f"Value##tfw_val_{nid}", v)
        if changed:
            inst.props["value"] = nv

    imgui.pop_item_width()


# ── ScalarMath ─────────────────────────────────────────────

@register("ScalarMath")
def _draw_scalar_math_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(100)

    op = inst.props.get("operation", "sum")
    ops = ["Sum", "Subtract", "Multiply", "Divide"]
    try:
        idx = next(i for i, o in enumerate(ops) if o.lower() == op)
    except StopIteration:
        idx = 0
    changed, new_idx = _ne_combo(f"##scalar_op_{nid}", idx, ops)
    if changed:
        inst.props["operation"] = ops[new_idx].lower()

    imgui.same_line()
    imgui.text_disabled("Op")
    imgui.pop_item_width()


# ── Compare ────────────────────────────────────────────────

@register("Compare")
def _draw_compare_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(80)

    op = inst.props.get("operation", "gt")
    labels = [">", "<", "==", "!=", ">=", "<="]
    keys = ["gt", "lt", "eq", "neq", "gte", "lte"]
    try:
        idx = keys.index(op)
    except ValueError:
        idx = 0
    changed, new_idx = _ne_combo(f"##cmp_op_{nid}", idx, labels)
    if changed:
        inst.props["operation"] = keys[new_idx]

    imgui.same_line()
    imgui.text_disabled("Op")
    imgui.pop_item_width()


# ── TimeTrigger ────────────────────────────────────────────

@register("TimeTrigger")
def _draw_time_trigger_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(90)

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##tt_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##tt_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = inst.props.get("time", 0.0)
        changed, nv = imgui.input_float(f"Time (s)##tt_time_{nid}", v, format="%.2f")
        if changed:
            inst.props["time"] = nv

    imgui.pop_item_width()


# ── VarSet ─────────────────────────────────────────────────

@register("VarSet")
def _draw_var_set_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(90)

    _draw_var_name_combo("vs", nid, inst, canvas)

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##vs_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##vs_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = inst.props.get("value", 0.0)
        changed, nv = imgui.input_float(f"Value##vs_val_{nid}", v, format="%.4f")
        if changed:
            inst.props["value"] = nv

    imgui.pop_item_width()


# ── VarGet ─────────────────────────────────────────────────

@register("VarGet")
def _draw_var_get_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(90)
    _draw_var_name_combo("vg", nid, inst, canvas)
    imgui.pop_item_width()


# ── Constant (Scale) ───────────────────────────────────────

@register("Constant")
def _draw_constant_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(90)
    v = inst.props.get("value", 0.0)
    changed, nv = imgui.input_float(f"Value##const_val_{nid}", v, format="%.4f")
    if changed:
        inst.props["value"] = nv
    imgui.pop_item_width()


# ── StringConst ────────────────────────────────────────────

@register("StringConst")
def _draw_string_constant_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)
    v = inst.props.get("value", "")
    changed, nv = imgui.input_text(f"Value##strconst_val_{nid}", v)
    if changed:
        inst.props["value"] = nv
    imgui.pop_item_width()


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
