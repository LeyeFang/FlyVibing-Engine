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
    """Port / BaudRate / Format 始终在节点属性中配置；Value 从上游 pin 传入。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    # ── Port ──
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

    # ── Baud Rate ──
    baud = int(inst.props.get("baud_rate", 9600))
    changed, new_baud = imgui.input_int(f"Baud##ser_baud_{nid}", baud)
    if changed:
        inst.props["baud_rate"] = new_baud

    # ── Format ──
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
    mode = inst.props.get("mode", "manual")
    imgui.push_item_width(50)

    # [M] [P] | T [____] | timer [____▼]  全都一行
    if imgui.radio_button(f"M##tt_m_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"P##tt_p_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"
    imgui.same_line(0, 4)
    imgui.text_disabled("|")
    imgui.same_line(0, 4)

    if mode == "manual":
        v = inst.props.get("time", 0.0)
        changed, nv = imgui.input_float(f"##tt_t_{nid}", v, format="%.1f")
        if changed:
            inst.props["time"] = nv
    else:
        imgui.text_disabled("(pin)")

    imgui.same_line(0, 4)
    imgui.text_disabled("|")
    imgui.same_line(0, 4)

    # 紧凑 timer 列表
    existing = _collect_timer_names(_canvas)
    current = inst.props.get("timer", "")
    items = ["global"] + existing
    try:
        idx = existing.index(current) + 1 if current else 0
    except ValueError:
        idx = 0
    imgui.push_item_width(70)
    changed, new_idx = imgui.combo(f"##tt_tmr_{nid}", idx, items, -1)
    if changed:
        inst.props["timer"] = "" if new_idx == 0 else existing[new_idx - 1]
    imgui.pop_item_width()

    imgui.pop_item_width()


# ── NewTimer ───────────────────────────────────────────────

@register("NewTimer")
def _draw_new_timer_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(90)

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(f"Manual##nt_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(f"Pin##nt_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = inst.props.get("timer_name", "timer")
        imgui.push_item_width(130)
        changed, nv = imgui.input_text(f"Name##nt_name_{nid}", v, 64)
        if changed:
            inst.props["timer_name"] = nv
        imgui.pop_item_width()

    imgui.pop_item_width()


# ── SetTimer ───────────────────────────────────────────────

@register("SetTimer")
def _draw_set_timer_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)

    # Timer name
    v = inst.props.get("timer_name", "")
    changed, nv = imgui.input_text_with_hint(f"Timer##st_name_{nid}", "timer_name", v, 64)
    if changed:
        inst.props["timer_name"] = nv

    # Operate
    operate = inst.props.get("operate", "reset")
    if imgui.radio_button(f"Reset##st_op_rst_{nid}", operate == "reset"):
        inst.props["operate"] = "reset"
    imgui.same_line()
    if imgui.radio_button(f"Set Time##st_op_set_{nid}", operate == "set_time"):
        inst.props["operate"] = "set_time"

    if operate == "set_time":
        mode = inst.props.get("mode", "manual")
        if imgui.radio_button(f"Manual##st_m_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(f"Pin##st_m_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        if mode == "manual":
            val = inst.props.get("value", 0.0)
            changed, nv = imgui.input_float(f"Value##st_val_{nid}", val, format="%.2f")
            if changed:
                inst.props["value"] = nv

    imgui.pop_item_width()


# ── GetTime (TimeGetElapsed) ───────────────────────────────

@register("TimeGetElapsed")
def _draw_get_time_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    _draw_timer_name_combo("gt", nid, inst, canvas)


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


# ── Constant (Number) ──────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════
# Gtec 节点 (IO ▸ Gtec)
# ═══════════════════════════════════════════════════════════════

def _collect_gtec_device_names(canvas, exclude_nid: int | None = None) -> list[str]:
    """收集画布上所有 InitGtecDevice 会话名（device_name 或 gtec#<nid> 回退），去重排序。"""
    names: set[str] = set()
    for nid, inst in canvas.nodes.items():
        if nid == exclude_nid or inst.node_type != "InitGtecDevice":
            continue
        n = str(inst.props.get("device_name", "")).strip() or f"gtec#{nid}"
        names.add(n)
    return sorted(names)


def _default_gtec_device_name(canvas, nid: int) -> str:
    """首个 Init 默认 HIAMP，其后 HIAMP2、HIAMP3…（保证画布内唯一）。"""
    used = {
        str(inst.props.get("device_name", "")).strip()
        for n2, inst in canvas.nodes.items()
        if n2 != nid and inst.node_type == "InitGtecDevice"
    }
    base = "HIAMP"
    if base not in used:
        return base
    k = 2
    while f"{base}{k}" in used:
        k += 1
    return f"{base}{k}"


def _draw_gtec_device_combo(label: str, nid: int, inst, canvas) -> None:
    """设备会话选择下拉框 — 列出 InitGtecDevice 注册的会话。

    空名称 + 唯一会话 → 自动绑定；已绑定但未注册时给出提示。
    """
    existing = _collect_gtec_device_names(canvas, exclude_nid=nid)
    current = str(inst.props.get("device_name", "")).strip()
    if not current and len(existing) == 1:
        inst.props["device_name"] = existing[0]
        current = existing[0]

    items = existing if existing else ["(no Init Gtec Device)"]
    idx = existing.index(current) if current in existing else 0
    changed, new_idx = _ne_combo(f"##gtec_dev_{label}_{nid}", idx, items)
    if changed and existing:
        inst.props["device_name"] = existing[new_idx]

    if current and current not in existing:
        imgui.same_line()
        imgui.text_disabled("(not registered)")


@register("InitGtecDevice")
def _draw_init_gtec_widgets(nid: int, inst, canvas) -> None:
    """InitGtecDevice — 设备 / 模板 / 滤波 / 采样率 / 导出 / 缓冲配置。"""
    from Application.Functions.EEGDevice import DEVICE_CHOICES, SUPPORTED_RATES, TEMPLATE_CHOICES

    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(100)

    # ── 会话名（默认唯一） ──
    if not str(inst.props.get("device_name", "")).strip():
        inst.props["device_name"] = _default_gtec_device_name(canvas, nid)
    name = str(inst.props.get("device_name", ""))
    changed, new_name = imgui.input_text(f"Name##gtec_name_{nid}", name)
    if changed:
        inst.props["device_name"] = new_name.strip()

    # ── 设备族 + 序列号 ──
    dev = inst.props.get("device", "HIAMP")
    dev_idx = DEVICE_CHOICES.index(dev) if dev in DEVICE_CHOICES else 0
    changed, new_idx = _ne_combo(f"##gtec_dev_{nid}", dev_idx, list(DEVICE_CHOICES))
    if changed:
        inst.props["device"] = DEVICE_CHOICES[new_idx]
    imgui.same_line()
    imgui.text_disabled("Device")

    serial = str(inst.props.get("serial", ""))
    changed, new_serial = imgui.input_text(
        f"##gtec_serial_{nid}", serial,
    )
    if changed:
        inst.props["serial"] = new_serial.strip()
    if not serial:
        imgui.same_line()
        imgui.text_disabled("(serial: auto)")

    # ── 模板 + 采样率 ──
    templates = list(TEMPLATE_CHOICES)
    tpl = inst.props.get("template", "64ch")
    tpl_idx = templates.index(tpl) if tpl in templates else 0
    changed, new_idx = _ne_combo(f"##gtec_tpl_{nid}", tpl_idx, templates)
    if changed:
        inst.props["template"] = templates[new_idx]
    imgui.same_line()
    imgui.text_disabled("Template")

    rates = [str(r) for r in SUPPORTED_RATES]
    rate = str(int(inst.props.get("sampling_rate", 512)))
    rate_idx = rates.index(rate) if rate in rates else rates.index("512")
    changed, new_idx = _ne_combo(f"##gtec_rate_{nid}", rate_idx, [f"{r} Hz" for r in rates])
    if changed:
        inst.props["sampling_rate"] = int(rates[new_idx])
    imgui.same_line()
    imgui.text_disabled("Rate")

    # ── 在线滤波: 陷波 + 类型 + 截止频率 ──
    notch_labels = ["Notch Off", "Notch 50Hz", "Notch 60Hz"]
    notch_keys = ["off", "50", "60"]
    notch = str(inst.props.get("notch", "off"))
    notch_idx = notch_keys.index(notch) if notch in notch_keys else 0
    changed, new_idx = _ne_combo(f"##gtec_notch_{nid}", notch_idx, notch_labels)
    if changed:
        inst.props["notch"] = notch_keys[new_idx]

    ftype_labels = ["Filter None", "High-pass", "Low-pass", "Band-pass"]
    ftype_keys = ["none", "highpass", "lowpass", "bandpass"]
    ftype = str(inst.props.get("filter_type", "none"))
    ftype_idx = ftype_keys.index(ftype) if ftype in ftype_keys else 0
    changed, new_idx = _ne_combo(f"##gtec_ftype_{nid}", ftype_idx, ftype_labels)
    if changed:
        inst.props["filter_type"] = ftype_keys[new_idx]

    # 截止频率: 0 = 未填(不生效); 按滤波器类型灰显不适用的输入
    low_enabled = ftype in ("highpass", "bandpass")
    high_enabled = ftype in ("lowpass", "bandpass")
    low = float(inst.props.get("low_cut", 0.0))
    high = float(inst.props.get("high_cut", 0.0))

    imgui.push_item_width(62)
    if not low_enabled:
        imgui.begin_disabled()
    changed, nv = imgui.input_float(f"Low##gtec_low_{nid}", low, format="%.3f")
    if changed:
        inst.props["low_cut"] = max(0.0, nv)
    if not low_enabled:
        imgui.end_disabled()
    imgui.same_line()
    if not high_enabled:
        imgui.begin_disabled()
    changed, nv = imgui.input_float(f"High##gtec_high_{nid}", high, format="%.3f")
    if changed:
        inst.props["high_cut"] = max(0.0, nv)
    if not high_enabled:
        imgui.end_disabled()
    imgui.same_line()
    imgui.text_disabled("Hz (0=off)")
    imgui.pop_item_width()

    # ── Trigger: 固定开启 + combine（只读展示） ──
    imgui.text_disabled("Trigger: ON (16 lines combined)")

    # ── 导出格式 + 保存目录 ──
    fmt_labels = ["NPZ (.npz + .json)", "CSV (.csv + .json)"]
    fmt_keys = ["npz", "csv"]
    fmt = str(inst.props.get("export_format", "npz"))
    fmt_idx = fmt_keys.index(fmt) if fmt in fmt_keys else 0
    changed, new_idx = _ne_combo(f"##gtec_fmt_{nid}", fmt_idx, fmt_labels)
    if changed:
        inst.props["export_format"] = fmt_keys[new_idx]

    if imgui.button(f"Browse Dir...##gtec_dir_btn_{nid}"):
        from Application.Editor.UI.FileDialog import FileDialog
        FileDialog.open_directory(
            lambda p, i=inst: i.props.__setitem__("save_dir", p),
            start_dir=str(inst.props.get("save_dir", "")),
        )
    imgui.same_line()
    sd = str(inst.props.get("save_dir", "")).strip()
    if sd:
        display = sd if len(sd) <= 30 else "..." + sd[-27:]
        imgui.text_disabled(display)
    else:
        imgui.text_disabled("(default: .)")

    # ── 窗口缓冲秒数 ──
    imgui.push_item_width(62)
    buf = float(inst.props.get("buffer_seconds", 10.0))
    changed, nv = imgui.input_float(f"Buffer##gtec_buf_{nid}", buf, format="%.1f")
    if changed:
        inst.props["buffer_seconds"] = max(0.1, min(600.0, nv))
    imgui.pop_item_width()
    imgui.same_line()
    try:
        tpl_key = str(inst.props.get("template", "64ch"))
        ch = TEMPLATE_CHOICES.get(tpl_key, 64)
        r = int(inst.props.get("sampling_rate", 512))
        cap = int(round(float(inst.props.get("buffer_seconds", 10.0)) * r))
        imgui.text_disabled(f"s = {cap} x {ch}ch")
    except Exception:
        imgui.text_disabled("s")

    imgui.pop_item_width()


@register("StartGtecRecord")
def _draw_start_gtec_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_gtec_device_combo("start", nid, inst, canvas)
    imgui.same_line()
    imgui.text_disabled("Device")
    imgui.pop_item_width()


@register("StopGtecRecord")
def _draw_stop_gtec_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_gtec_device_combo("stop", nid, inst, canvas)
    imgui.same_line()
    imgui.text_disabled("Device")

    scope_labels = ["Save: Session", "Save: Window"]
    scope_keys = ["session", "buffer"]
    scope = str(inst.props.get("save_scope", "session"))
    scope_idx = scope_keys.index(scope) if scope in scope_keys else 0
    changed, new_idx = _ne_combo(f"##gtec_scope_{nid}", scope_idx, scope_labels)
    if changed:
        inst.props["save_scope"] = scope_keys[new_idx]
    imgui.pop_item_width()


@register("KillGtecDevice")
def _draw_kill_gtec_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_gtec_device_combo("kill", nid, inst, canvas)
    imgui.same_line()
    imgui.text_disabled("Device")
    imgui.pop_item_width()


@register("GetGtecData")
def _draw_get_gtec_widgets(nid: int, inst, canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    _draw_gtec_device_combo("get", nid, inst, canvas)
    imgui.same_line()
    imgui.text_disabled("Device")
    imgui.pop_item_width()

