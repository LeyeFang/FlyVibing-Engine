"""通用/流程节点 widget（IO·逻辑·计时·变量·常量） — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from .core import register, _ne_combo, _list_com_ports, _collect_timer_names, _draw_timer_name_combo, _draw_var_name_combo

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


