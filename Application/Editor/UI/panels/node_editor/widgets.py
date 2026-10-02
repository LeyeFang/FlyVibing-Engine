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


# ══════════════════════════════════════════════════════════════
# SigGen (虚拟信号发生器) — IO ▸ SigGen
# ══════════════════════════════════════════════════════════════

@register("InitSigGenDevice")
def _draw_init_siggen_widgets(nid: int, inst, _canvas) -> None:
    """虚拟正弦源配置: 名称/通道/采样率/基频/步进/幅度/噪声/种子/导出。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(140)
    p = inst.props

    changed, v = imgui.input_text(f"##sg_name_{nid}", str(p.get("device_name", "")))
    if changed:
        p["device_name"] = v
    imgui.same_line()
    imgui.text_disabled("Name")

    changed, nv = imgui.input_int(f"Ch##sg_ch_{nid}", int(p.get("channels", 8)))
    if changed:
        p["channels"] = max(1, min(256, nv))
    imgui.same_line()
    imgui.text_disabled("Ch")

    changed, nv = imgui.input_int(f"Fs##sg_fs_{nid}", int(p.get("sampling_rate", 512)))
    if changed:
        p["sampling_rate"] = max(1, min(38400, nv))
    imgui.same_line()
    imgui.text_disabled("Hz")

    changed, nv = imgui.input_float(f"F0##sg_f0_{nid}", float(p.get("frequency", 10.0)))
    if changed:
        p["frequency"] = nv
    imgui.same_line()
    imgui.text_disabled("Hz base")

    changed, nv = imgui.input_float(f"dF##sg_df_{nid}", float(p.get("freq_step", 2.0)))
    if changed:
        p["freq_step"] = max(0.0, nv)
    imgui.same_line()
    imgui.text_disabled("Hz/ch")

    changed, nv = imgui.input_float(f"Amp##sg_amp_{nid}", float(p.get("amplitude_uv", 50.0)))
    if changed:
        p["amplitude_uv"] = max(0.0, nv)
    imgui.same_line()
    imgui.text_disabled("uV")

    changed, nv = imgui.input_float(f"Noise##sg_noise_{nid}", float(p.get("noise_uv", 0.0)))
    if changed:
        p["noise_uv"] = max(0.0, nv)
    imgui.same_line()
    imgui.text_disabled("uV rms")

    changed, nv = imgui.input_int(f"Seed##sg_seed_{nid}", int(p.get("seed", 0)))
    if changed:
        p["seed"] = nv
    imgui.same_line()
    imgui.text_disabled("Seed")

    fmt_keys = ["npz", "csv"]
    fmt = str(p.get("export_format", "npz"))
    idx = fmt_keys.index(fmt) if fmt in fmt_keys else 0
    changed, new_idx = _ne_combo(f"##sg_fmt_{nid}", idx, ["NPZ", "CSV"])
    if changed:
        p["export_format"] = fmt_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Format")

    changed, v = imgui.input_text(f"##sg_dir_{nid}", str(p.get("save_dir", ".")))
    if changed:
        p["save_dir"] = v
    imgui.same_line()
    imgui.text_disabled("Save Dir")

    changed, nv = imgui.input_float(f"Buf##sg_buf_{nid}", float(p.get("buffer_seconds", 10.0)))
    if changed:
        p["buffer_seconds"] = max(0.1, min(600.0, nv))
    imgui.same_line()
    imgui.text_disabled("s window")

    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


def _device_name_field(nid: int, inst, key: str, canvas=None) -> None:
    """通用设备引用控件: 池下拉 + 设备动态下拉（Start/Stop/Kill/Get 设备节点共用）。

    设备列表 = 所选池在画布上的成员（Init 节点会话键, 与校验器同一套键规则）;
    "(Auto)" = 空名 → 运行时池内唯一设备自动绑定。
    当前值不在列表时保留一项 "(unlisted)", 避免静默丢失配置。
    """
    from Application.Core.NodeGraph.graph_constraints import device_inventory

    inv = device_inventory(canvas) if canvas is not None \
        else {"pools": {}, "global": [], "inits": {}, "assignments": {}}
    pool_names = ["global"] + sorted(inv["pools"].keys())
    cur_pool = str(inst.props.get("pool", "")).strip()
    if cur_pool and cur_pool not in pool_names:
        pool_names.append(cur_pool)
    cur_pool = cur_pool or "global"
    try:
        pool_idx = pool_names.index(cur_pool)
    except ValueError:
        pool_idx = 0

    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(92)
    changed, new_idx = _ne_combo(f"##pool_{key}_{nid}", pool_idx, pool_names)
    if changed:
        inst.props["pool"] = pool_names[new_idx]
        cur_pool = pool_names[new_idx]
    imgui.same_line()
    imgui.text_disabled("Pool")
    imgui.pop_item_width()

    if cur_pool == "global" or cur_pool not in inv["pools"]:
        members = list(inv.get("global", []))
    else:
        members = list(inv["pools"][cur_pool].get("members", []))
    members = sorted(members)

    cur = str(inst.props.get("device_name", "")).strip()
    values = [""] + members
    labels = ["(Auto)"] + members
    if cur and cur not in members:
        values.append(cur)
        labels.append(cur + " (unlisted)")

    imgui.push_item_width(120)
    changed, sel = _ne_combo(f"##dev_{key}_{nid}", values.index(cur), labels)
    if changed and sel < len(values):
        inst.props["device_name"] = values[sel]
    imgui.same_line()
    imgui.text_disabled("Device")
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


@register("StartSigGenRecord")
def _draw_start_siggen_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "sgstart", _canvas)


@register("StopSigGenRecord")
def _draw_stop_siggen_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "sgstop", _canvas)
    imgui.push_item_width(90)
    scope_keys = ["session", "buffer"]
    scope = str(inst.props.get("save_scope", "session"))
    idx = scope_keys.index(scope) if scope in scope_keys else 0
    changed, new_idx = _ne_combo(f"##sg_scope_{nid}", idx, ["Session", "Buffer"])
    if changed:
        inst.props["save_scope"] = scope_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Save")
    imgui.pop_item_width()


@register("KillSigGenDevice")
def _draw_kill_siggen_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "sgkill", _canvas)


@register("GetSigGenData")
def _draw_get_siggen_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "sgget", _canvas)


# ══════════════════════════════════════════════════════════════
# Gtec (g.HIamp) — 补齐内联控件 (IO ▸ Gtec)
# ══════════════════════════════════════════════════════════════

@register("InitGtecDevice")
def _draw_init_gtec_widgets(nid: int, inst, _canvas) -> None:
    """g.HIamp 配置: 名称/序列号/模板/采样率/陷波/滤波/导出。"""
    from Application.Functions.EEGDevice.Device import SUPPORTED_RATES, TEMPLATE_CHOICES

    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(140)
    p = inst.props

    changed, v = imgui.input_text(f"##gt_name_{nid}", str(p.get("device_name", "")))
    if changed:
        p["device_name"] = v
    imgui.same_line()
    imgui.text_disabled("Name")

    changed, v = imgui.input_text(f"##gt_serial_{nid}", str(p.get("serial", "")))
    if changed:
        p["serial"] = v
    imgui.same_line()
    imgui.text_disabled("Serial (''=auto)")

    tpl_keys = list(TEMPLATE_CHOICES.keys())
    tpl = str(p.get("template", tpl_keys[0]))
    idx = tpl_keys.index(tpl) if tpl in tpl_keys else 0
    changed, new_idx = _ne_combo(f"##gt_tpl_{nid}", idx, tpl_keys)
    if changed:
        p["template"] = tpl_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Template")

    rate_keys = [str(r) for r in SUPPORTED_RATES]
    rate = str(int(p.get("sampling_rate", 512)))
    idx = rate_keys.index(rate) if rate in rate_keys else rate_keys.index("512")
    changed, new_idx = _ne_combo(f"##gt_rate_{nid}", idx, rate_keys)
    if changed:
        p["sampling_rate"] = int(rate_keys[new_idx])
    imgui.same_line()
    imgui.text_disabled("Fs (Hz)")

    notch_keys = ["off", "50", "60"]
    notch = str(p.get("notch", "off"))
    idx = notch_keys.index(notch) if notch in notch_keys else 0
    changed, new_idx = _ne_combo(f"##gt_notch_{nid}", idx, ["Off", "50Hz", "60Hz"])
    if changed:
        p["notch"] = notch_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Notch")

    ft_keys = ["none", "highpass", "lowpass", "bandpass"]
    ft = str(p.get("filter_type", "none"))
    idx = ft_keys.index(ft) if ft in ft_keys else 0
    changed, new_idx = _ne_combo(f"##gt_ft_{nid}", idx,
                                 ["None", "Highpass", "Lowpass", "Bandpass"])
    if changed:
        p["filter_type"] = ft_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Filter")

    changed, nv = imgui.input_float(f"Lo##gt_lo_{nid}", float(p.get("low_cut", 0.0)))
    if changed:
        p["low_cut"] = nv
    imgui.same_line()
    imgui.text_disabled("low cut Hz (0=unset)")

    changed, nv = imgui.input_float(f"Hi##gt_hi_{nid}", float(p.get("high_cut", 0.0)))
    if changed:
        p["high_cut"] = nv
    imgui.same_line()
    imgui.text_disabled("high cut Hz (0=unset)")

    fmt_keys = ["npz", "csv"]
    fmt = str(p.get("export_format", "npz"))
    idx = fmt_keys.index(fmt) if fmt in fmt_keys else 0
    changed, new_idx = _ne_combo(f"##gt_fmt_{nid}", idx, ["NPZ", "CSV"])
    if changed:
        p["export_format"] = fmt_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Format")

    changed, v = imgui.input_text(f"##gt_dir_{nid}", str(p.get("save_dir", ".")))
    if changed:
        p["save_dir"] = v
    imgui.same_line()
    imgui.text_disabled("Save Dir")

    changed, nv = imgui.input_float(f"Buf##gt_buf_{nid}", float(p.get("buffer_seconds", 10.0)))
    if changed:
        p["buffer_seconds"] = max(0.1, min(600.0, nv))
    imgui.same_line()
    imgui.text_disabled("s window")

    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


@register("StartGtecRecord")
def _draw_start_gtec_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "gtstart", _canvas)


@register("StopGtecRecord")
def _draw_stop_gtec_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "gtstop", _canvas)
    imgui.push_item_width(90)
    scope_keys = ["session", "buffer"]
    scope = str(inst.props.get("save_scope", "session"))
    idx = scope_keys.index(scope) if scope in scope_keys else 0
    changed, new_idx = _ne_combo(f"##gt_scope_{nid}", idx, ["Session", "Buffer"])
    if changed:
        inst.props["save_scope"] = scope_keys[new_idx]
    imgui.same_line()
    imgui.text_disabled("Save")
    imgui.pop_item_width()


@register("KillGtecDevice")
def _draw_kill_gtec_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "gtkill", _canvas)


@register("GetGtecData")
def _draw_get_gtec_widgets(nid: int, inst, _canvas) -> None:
    _device_name_field(nid, inst, "gtget", _canvas)


# ══════════════════════════════════════════════════════════════
# Device Pool (IO ▸ Pool) — Create / Add / Kill
# ══════════════════════════════════════════════════════════════

@register("CreateDevicePool")
def _draw_create_pool_widgets(nid: int, inst, _canvas) -> None:
    """池名输入（空 → 回退池键 pool#<nid>, 与校验器一致）。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, v = imgui.input_text(f"##pool_name_{nid}",
                                  str(inst.props.get("pool_name", "")))
    if changed:
        inst.props["pool_name"] = v
    imgui.same_line()
    imgui.text_disabled("Pool Name")
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


def _draw_pool_picker(nid: int, inst, key: str, canvas, allow_auto: bool) -> None:
    """已注册(画布)池下拉; allow_auto → 首项 "(Auto)" (空名 + 唯一 Create 自动绑定)。"""
    from Application.Core.NodeGraph.graph_constraints import device_inventory

    inv = device_inventory(canvas)
    names = sorted(inv["pools"].keys())
    cur = str(inst.props.get("pool_name", "")).strip()
    values = ([""] if allow_auto else []) + names
    labels = (["(Auto)"] if allow_auto else []) + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(cur + " (unlisted)")
    if not values:
        values, labels = [""], ["(no pools)"]
    try:
        sel = values.index(cur)
    except ValueError:
        sel = 0
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, new_idx = _ne_combo(f"##pool_sel_{key}_{nid}", sel, labels)
    if changed:
        inst.props["pool_name"] = values[new_idx]
    imgui.same_line()
    imgui.text_disabled("Pool")
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


@register("AddToDevicePool")
def _draw_add_pool_widgets(nid: int, inst, _canvas) -> None:
    """池选择 + 来源设备展示（device pin 上游 Init 的会话键）。"""
    from Application.Core.NodeGraph.graph_constraints import device_inventory

    _draw_pool_picker(nid, inst, "add", _canvas, allow_auto=False)
    inv = device_inventory(_canvas)
    src_nid = next((k for k, a in inv["assignments"].items() if a["add"] == nid), None)
    src = inv["inits"].get(src_nid, "") if src_nid is not None else ""
    imgui.text_disabled(f"  ← {src}" if src else "  ← (device pin not linked)")


@register("KillDevicePool")
def _draw_kill_pool_widgets(nid: int, inst, _canvas) -> None:
    _draw_pool_picker(nid, inst, "kill", _canvas, allow_auto=True)


# ══════════════════════════════════════════════════════════════
# Epoch Dataset (epoch 数据集) — Append / Count / Clear / Save / Load
# ══════════════════════════════════════════════════════════════

def _draw_epochs_picker(nid: int, inst, key: str, canvas, allow_auto: bool,
                        prop: str = "epochs_name") -> None:
    """数据集下拉（画布 Append/Load 源）; allow_auto → 首项 "(Auto)"（唯一源自动绑定）。"""
    from Application.Core.NodeGraph.graph_constraints import epoch_source_keys

    sources = epoch_source_keys(canvas.nodes) if canvas is not None else {}
    names = sorted(sources.keys())
    cur = str(inst.props.get(prop, "")).strip()
    values = ([""] if allow_auto else []) + names
    labels = (["(Auto)"] if allow_auto else []) + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(cur + " (unlisted)")
    if not values:
        values, labels = [""], ["(no datasets)"]
    try:
        sel = values.index(cur)
    except ValueError:
        sel = 0
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, new_idx = _ne_combo(f"##epochs_sel_{key}_{nid}", sel, labels)
    if changed:
        inst.props[prop] = values[new_idx]
    imgui.same_line()
    imgui.text_disabled("Dataset")
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


@register("EpochAppend")
def _draw_epoch_append_widgets(nid: int, inst, _canvas) -> None:
    """名称输入 + 实时条数提示（注册表直读, 锁保护）。"""
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, v = imgui.input_text(f"##epochs_name_{nid}",
                                  str(inst.props.get("epochs_name", "")))
    if changed:
        inst.props["epochs_name"] = v
    imgui.same_line()
    imgui.text_disabled("Epochs")
    imgui.pop_item_width()
    name = str(inst.props.get("epochs_name", "")).strip()
    hint = "  (set a name to capture)"
    if name:
        try:
            from Application.Functions.BCIAlgorithm import epoch_stats

            stats, _why = epoch_stats(name)
            hint = (f"  {stats['count']} epoch(s), {stats['classes']} class(es)"
                    if stats else "  (not captured yet)")
        except Exception:  # noqa: BLE001
            pass
    imgui.text_disabled(hint)
    imgui.dummy(imgui.ImVec2(0, 2))


@register("EpochCount")
def _draw_epoch_count_widgets(nid: int, inst, _canvas) -> None:
    _draw_epochs_picker(nid, inst, "cnt", _canvas, allow_auto=True)


@register("EpochClear")
def _draw_epoch_clear_widgets(nid: int, inst, _canvas) -> None:
    _draw_epochs_picker(nid, inst, "clr", _canvas, allow_auto=True)


@register("EpochSave")
def _draw_epoch_save_widgets(nid: int, inst, _canvas) -> None:
    _draw_epochs_picker(nid, inst, "sav", _canvas, allow_auto=True)
    imgui.push_item_width(150)
    changed, v = imgui.input_text(f"##epochs_dir_{nid}",
                                  str(inst.props.get("save_dir", ".")))
    if changed:
        inst.props["save_dir"] = v
    imgui.same_line()
    imgui.text_disabled("Save Dir")
    imgui.pop_item_width()


@register("EpochLoad")
def _draw_epoch_load_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, v = imgui.input_text(f"##epochs_name_{nid}",
                                  str(inst.props.get("epochs_name", "")))
    if changed:
        inst.props["epochs_name"] = v
    imgui.same_line()
    imgui.text_disabled("Epochs")
    imgui.pop_item_width()
    imgui.push_item_width(220)
    changed, v = imgui.input_text(f"##epochs_file_{nid}",
                                  str(inst.props.get("file_path", "")))
    if changed:
        inst.props["file_path"] = v
    imgui.same_line()
    imgui.text_disabled("NPZ Path")
    imgui.pop_item_width()
    modes = ["replace", "append"]
    cur = str(inst.props.get("mode", "replace"))
    idx = modes.index(cur) if cur in modes else 0
    changed, ni = _ne_combo(f"##epochs_mode_{nid}", idx, ["Replace", "Append"])
    if changed:
        inst.props["mode"] = modes[ni]
    imgui.same_line()
    imgui.text_disabled("Mode")
    imgui.dummy(imgui.ImVec2(0, 2))


# ══════════════════════════════════════════════════════════════
# BCI Algorithm (FBCSP / CCA) — Init / Train / Test
# ══════════════════════════════════════════════════════════════

def _draw_band_editor(nid: int, inst) -> None:
    """bands 动态组编辑器（打包 props["bands"]: [[lo,hi], ...]; 空 = 普通 CSP）。"""
    bands = inst.props.get("bands")
    if not isinstance(bands, list):
        bands = [[4.0, 8.0], [8.0, 13.0], [13.0, 30.0]]
        inst.props["bands"] = bands
    imgui.text_disabled(f"  Bands ({len(bands)}) - 0 = plain CSP")
    remove_idx = None
    for i, band in enumerate(list(bands)):
        if not isinstance(band, list) or len(band) < 2:
            band = [4.0, 8.0]
            bands[i] = band
        try:
            lo, hi = float(band[0]), float(band[1])
        except (TypeError, ValueError):
            lo, hi = 4.0, 8.0
        imgui.push_item_width(58)
        changed, v = imgui.input_float(f"##bd_lo_{nid}_{i}", lo, format="%.1f")
        if changed and 0.1 <= v < 500.0:
            band[0] = round(float(v), 2)
        imgui.same_line()
        imgui.text_disabled("-")
        imgui.same_line()
        changed, v = imgui.input_float(f"##bd_hi_{nid}_{i}", hi, format="%.1f")
        if changed and 0.1 < v <= 500.0:
            band[1] = round(float(v), 2)
        imgui.same_line()
        if imgui.small_button(f"-##bd_rm_{nid}_{i}"):
            remove_idx = i
        imgui.pop_item_width()
    if remove_idx is not None and 0 <= remove_idx < len(bands):
        bands.pop(remove_idx)
    if len(bands) < 16 and imgui.small_button(f"+##bd_add_{nid}"):
        bands.append([8.0, 13.0])
    imgui.same_line()
    imgui.text_disabled("+ Add Band")


def _draw_freq_editor(nid: int, inst) -> None:
    """freqs 动态组编辑器（>= 2 不限上限; props["freqs"]: [f, ...]）。"""
    freqs = inst.props.get("freqs")
    if not isinstance(freqs, list):
        freqs = [10.0, 12.0, 15.0]
        inst.props["freqs"] = freqs
    imgui.text_disabled(f"  Frequencies ({len(freqs)}) - at least 2")
    remove_idx = None
    for i, f in enumerate(list(freqs)):
        try:
            v0 = float(f)
        except (TypeError, ValueError):
            v0 = 10.0
        imgui.push_item_width(70)
        changed, v = imgui.input_float(f"##fq_{nid}_{i}", v0, format="%.1f")
        if changed and 0.1 <= v <= 500.0:
            freqs[i] = round(float(v), 2)
        imgui.same_line()
        if imgui.small_button(f"-##fq_rm_{nid}_{i}"):
            remove_idx = i
        imgui.pop_item_width()
    if remove_idx is not None and len(freqs) > 2:
        freqs.pop(remove_idx)
    if imgui.small_button(f"+##fq_add_{nid}"):
        freqs.append(12.0)
    imgui.same_line()
    imgui.text_disabled("+ Add Freq")


def _draw_model_picker(nid: int, inst, key: str, canvas, kind: str) -> None:
    """模型下拉: kind="specs"（InitFBCSP 源） / "models"（TrainFBCSP 源）。"""
    from Application.Core.NodeGraph.graph_constraints import model_source_keys

    src: dict = {}
    if canvas is not None:
        adapted = {nid_: {"node_type": o.node_type, "props": o.props}
                   for nid_, o in canvas.nodes.items()}
        src = model_source_keys(adapted).get(kind, {})
    names = sorted(src.keys())
    cur = str(inst.props.get("model_name", "")).strip()
    values = [""] + names
    labels = ["(Auto)"] + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(cur + " (unlisted)")
    try:
        sel = values.index(cur)
    except ValueError:
        sel = 0
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    changed, ni = _ne_combo(f"##model_sel_{key}_{nid}", sel, labels)
    if changed:
        inst.props["model_name"] = values[ni]
    imgui.same_line()
    imgui.text_disabled("Model")
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


@register("InitFBCSP")
def _draw_init_fbcsp_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(110)
    changed, v = imgui.input_text(f"##fb_name_{nid}",
                                  str(inst.props.get("model_name", "")))
    if changed:
        inst.props["model_name"] = v
    imgui.same_line()
    imgui.text_disabled("Model")
    imgui.pop_item_width()
    imgui.push_item_width(60)
    changed, v = imgui.input_int(f"##fb_m_{nid}",
                                 int(inst.props.get("n_components", 2)))
    if changed:
        inst.props["n_components"] = max(1, min(8, int(v)))
    imgui.same_line()
    imgui.text_disabled("CSP pairs")
    imgui.pop_item_width()
    cls_keys = ["LDA", "SVM"]
    cur = str(inst.props.get("classifier", "LDA")).upper()
    idx = cls_keys.index(cur) if cur in cls_keys else 0
    changed, ni = _ne_combo(f"##fb_clf_{nid}", idx, cls_keys)
    if changed:
        inst.props["classifier"] = cls_keys[ni]
    imgui.same_line()
    imgui.text_disabled("Classifier")
    _draw_band_editor(nid, inst)


@register("TrainFBCSP")
def _draw_train_fbcsp_widgets(nid: int, inst, _canvas) -> None:
    _draw_model_picker(nid, inst, "tr", _canvas, "specs")
    _draw_epochs_picker(nid, inst, "trds", _canvas, allow_auto=True,
                        prop="dataset_name")
    modes = ["train", "load"]
    cur = str(inst.props.get("mode", "train")).lower()
    idx = modes.index(cur) if cur in modes else 0
    changed, ni = _ne_combo(f"##tr_mode_{nid}", idx, ["Train", "Load"])
    if changed:
        inst.props["mode"] = modes[ni]
    imgui.same_line()
    imgui.text_disabled("Mode")
    if modes[idx] == "load":
        imgui.push_item_width(200)
        changed, v = imgui.input_text(f"##tr_path_{nid}",
                                      str(inst.props.get("model_path", "")))
        if changed:
            inst.props["model_path"] = v
        imgui.same_line()
        imgui.text_disabled("Model NPZ")
        imgui.pop_item_width()
    else:
        imgui.push_item_width(150)
        changed, v = imgui.input_text(f"##tr_save_{nid}",
                                      str(inst.props.get("save_path", "")))
        if changed:
            inst.props["save_path"] = v
        imgui.same_line()
        imgui.text_disabled("Save NPZ (opt)")
        imgui.pop_item_width()
    imgui.text_disabled("  blocks exec until done - keep on a frame chain")


@register("TestFBCSP")
def _draw_test_fbcsp_widgets(nid: int, inst, _canvas) -> None:
    _draw_model_picker(nid, inst, "te", _canvas, "models")


@register("TestCCA")
def _draw_test_cca_widgets(nid: int, inst, _canvas) -> None:
    _draw_freq_editor(nid, inst)
    imgui.push_item_width(50)
    changed, v = imgui.input_int(f"##cca_h_{nid}",
                                 int(inst.props.get("n_harmonics", 3)))
    if changed:
        inst.props["n_harmonics"] = max(1, min(8, int(v)))
    imgui.same_line()
    imgui.text_disabled("Harmonics")
    imgui.pop_item_width()
