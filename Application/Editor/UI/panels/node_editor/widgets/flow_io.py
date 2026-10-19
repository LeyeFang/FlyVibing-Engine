"""通用/流程节点 widget（IO·逻辑·计时·变量·常量） — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from Application.Editor.I18n import t
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
    dist_labels = [t("widget.flow.uniform"), t("widget.flow.gaussian"), t("widget.flow.discrete")]
    dist_keys = ["uniform", "gaussian", "discrete"]
    try:
        dist_idx = dist_keys.index(dist)
    except ValueError:
        dist_idx = 0
    changed, new_idx = _ne_combo(f"##rand_dist_{nid}", dist_idx, dist_labels)
    if changed:
        inst.props["distribution"] = dist_keys[new_idx]

    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(t("common.manual") + f"##rand_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("common.pin") + f"##rand_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        if dist == "uniform":
            v = inst.props.get("min", 0.0)
            changed, nv = imgui.input_float(t("widget.flow.min") + f"##rand_min_{nid}", v)
            if changed:
                inst.props["min"] = nv
            v = inst.props.get("max", 1.0)
            changed, nv = imgui.input_float(t("widget.flow.max") + f"##rand_max_{nid}", v)
            if changed:
                inst.props["max"] = nv
        elif dist == "gaussian":
            v = inst.props.get("mean", 0.0)
            changed, nv = imgui.input_float(t("widget.flow.mean") + f"##rand_mean_{nid}", v)
            if changed:
                inst.props["mean"] = nv
            v = inst.props.get("stddev", 1.0)
            changed, nv = imgui.input_float(t("widget.flow.stddev") + f"##rand_std_{nid}", v)
            if changed:
                inst.props["stddev"] = nv
        else:  # discrete
            v = int(inst.props.get("min", 0))
            changed, nv = imgui.input_int(t("widget.flow.min") + f"##rand_min_{nid}", v)
            if changed:
                inst.props["min"] = nv
            v = int(inst.props.get("max", 10))
            changed, nv = imgui.input_int(t("widget.flow.max") + f"##rand_max_{nid}", v)
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

    source_labels = [t("common.manual"), t("common.pin"), t("widget.flow.hardware")]
    source_keys   = ["manual", "pin", "hardware"]
    try:
        src_idx = source_keys.index(source)
    except ValueError:
        src_idx = 0

    changed, new_idx = _ne_combo(t("widget.flow.source") + f"##rss_src_{nid}", src_idx, source_labels)
    if changed:
        inst.props["source"] = source_keys[new_idx]
        source = source_keys[new_idx]

    if source == "manual":
        seed = int(inst.props.get("seed", 0))
        changed, new_seed = imgui.input_int(t("widget.flow.seed") + f"##rss_seed_{nid}", seed)
        if changed:
            inst.props["seed"] = new_seed
    elif source == "hardware":
        # 只读显示上一次生成的种子 (首次为 0，执行后才会更新)
        imgui.begin_disabled(True)
        seed = inst.props.get("seed", 0)
        imgui.input_int(t("widget.flow.last_seed") + f"##rss_seed_{nid}", seed)
        imgui.end_disabled()

    imgui.pop_item_width()


# ── SerialSend ─────────────────────────────────────────────

@register("SerialSend")
def _draw_serial_send_widgets(nid: int, inst, _canvas) -> None:
    """Port / BaudRate / Format 始终在节点属性中配置；Value 从上游 pin 传入。

    Port 可为物理端口（`COM5`）或**逻辑设备名**（`@mibox` — 本机绑定, 协议
    `Doc/Dev/device_io_protocol.md` §12）: 换机器只需在面板里重绑别名, 场景不用改。
    """
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(105)

    # ── Port ──
    port = str(inst.props.get("port", ""))
    ports = _list_com_ports()
    try:                                    # 逻辑设备名（本机已绑定）也进候选
        from Application.Core.DeviceRegistry import all as _aliases
        ports = ports + ["@" + n for n in sorted(_aliases())]
    except Exception:                       # noqa: BLE001 — 无注册表环境降级
        pass
    if ports:
        try:
            idx = ports.index(port)
        except ValueError:
            idx = -1
        if idx < 0:
            ports.append(port)
            idx = len(ports) - 1
        changed, new_idx = _ne_combo(t("widget.flow.port") + f"##ser_port_{nid}", idx, ports)
        if changed:
            inst.props["port"] = ports[new_idx]
    else:
        changed, new_port = imgui.input_text(t("widget.flow.port") + f"##ser_port_{nid}", port)
        if changed:
            inst.props["port"] = new_port

    # ── Baud Rate ──
    baud = int(inst.props.get("baud_rate", 9600))
    changed, new_baud = imgui.input_int(t("widget.flow.baud") + f"##ser_baud_{nid}", baud)
    if changed:
        inst.props["baud_rate"] = new_baud

    # ── Format ──
    fmt = inst.props.get("format", "bytes")
    fmt_labels = [t("widget.flow.bytes"), t("widget.flow.string")]
    fmt_keys = ["bytes", "string"]
    try:
        fmt_idx = fmt_keys.index(fmt)
    except ValueError:
        fmt_idx = 0
    changed, new_fmt_idx = _ne_combo(t("widget.flow.format") + f"##ser_fmt_{nid}", fmt_idx, fmt_labels)
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
    addr_labels = [t("widget.flow.addr_lpt1"), t("widget.flow.addr_lpt2"), t("widget.flow.addr_lpt3")]
    addr_values = [0x3FF8, 0x3FF0, 0x3FE8]
    try:
        idx = addr_values.index(address)
    except ValueError:
        idx = -1
    changed, new_idx = _ne_combo(t("widget.flow.address") + f"##par_addr_{nid}", idx, addr_labels)
    if changed and 0 <= new_idx < len(addr_values):
        inst.props["address"] = addr_values[new_idx]

    mode = inst.props.get("mode", "manual")
    imgui.dummy(imgui.ImVec2(0, 1))
    if imgui.radio_button(t("common.manual") + f"##par_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("common.pin") + f"##par_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = int(inst.props.get("value", 1))
        changed, nv = imgui.input_int(t("widget.flow.value_1_255") + f"##par_val_{nid}", v)
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
    if imgui.radio_button(t("widget.flow.dir") + f"##pv_dir_{nid}", browse_mode == "directory"):
        inst.props["browse_mode"] = "directory"
    imgui.same_line()
    if imgui.radio_button(t("widget.flow.file") + f"##pv_file_{nid}", browse_mode == "file"):
        inst.props["browse_mode"] = "file"

    if imgui.button(t("widget.flow.browse") + f"##pv_btn_{nid}"):
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
        imgui.text_disabled(t("widget.flow.no_path"))

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
    if imgui.radio_button(t("widget.flow.write_new") + f"##tfw_w_{nid}", write_mode == "w"):
        inst.props["write_mode"] = "w"
    imgui.same_line()
    if imgui.radio_button(t("widget.flow.write_append") + f"##tfw_a_{nid}", write_mode == "a"):
        inst.props["write_mode"] = "a"

    # 间隔符
    delim = inst.props.get("delimiter", "none")
    delim_labels = [t("widget.flow.delim_none"), t("widget.flow.delim_space"),
                    t("widget.flow.delim_newline"), t("widget.flow.delim_tab"),
                    t("widget.flow.delim_comma")]
    delim_keys = ["none", "space", "newline", "tab", "comma"]
    try:
        delim_idx = delim_keys.index(delim)
    except ValueError:
        delim_idx = 0
    changed, new_idx = _ne_combo(t("widget.flow.delimiter") + f"##tfw_delim_{nid}", delim_idx, delim_labels)
    if changed:
        inst.props["delimiter"] = delim_keys[new_idx]

    imgui.dummy(imgui.ImVec2(0, 2))

    # FilePath Browse
    if imgui.button(t("widget.flow.browse_dir") + f"##tfw_btn_{nid}"):
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
        imgui.text_disabled(t("widget.flow.no_dir"))

    imgui.dummy(imgui.ImVec2(0, 2))

    # 模式切换
    mode = inst.props.get("mode", "manual")
    if imgui.radio_button(t("common.manual") + f"##tfw_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("common.pin") + f"##tfw_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        fname = str(inst.props.get("file_name", "output"))
        changed, nf = imgui.input_text(t("widget.flow.file_name") + f"##tfw_fn_{nid}", fname)
        if changed:
            inst.props["file_name"] = nf
        imgui.same_line()
        imgui.text_disabled(".txt")

        v = str(inst.props.get("value", ""))
        changed, nv = imgui.input_text(t("common.value") + f"##tfw_val_{nid}", v)
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
    imgui.text_disabled(t("widget.vec.op"))
    imgui.pop_item_width()


# ── Compare ────────────────────────────────────────────────

@register("Compare")
def _draw_compare_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(80)

    op = inst.props.get("operation", "gt")
    labels = [">", "<", "==", "!=", ">=", "<=",
              t("widget.compare.and"), t("widget.compare.or"),
              t("widget.compare.not"), t("widget.compare.xor"),
              t("widget.compare.in"), t("widget.compare.not_in"),
              t("widget.compare.between")]
    keys = ["gt", "lt", "eq", "neq", "gte", "lte",
            "and", "or", "not", "xor", "in", "not_in", "between"]
    try:
        idx = keys.index(op)
    except ValueError:
        idx = 0
    changed, new_idx = _ne_combo(f"##cmp_op_{nid}", idx, labels)
    if changed:
        inst.props["operation"] = keys[new_idx]
        op = keys[new_idx]

    if op == "between":
        imgui.same_line()
        include_end = bool(inst.props.get("include_end", False))
        changed, include_end = imgui.checkbox(
            t("widget.compare.include_end") + f"##cmp_end_{nid}", include_end)
        if changed:
            inst.props["include_end"] = bool(include_end)

    imgui.same_line()
    imgui.text_disabled(t("widget.vec.op"))
    imgui.pop_item_width()


# ── TimeTrigger ────────────────────────────────────────────

@register("TimeTrigger")
def _draw_time_trigger_widgets(nid: int, inst, _canvas) -> None:
    mode = inst.props.get("mode", "manual")
    imgui.push_item_width(50)

    # [M] [P] | T [____] | timer [____▼]  全都一行
    if imgui.radio_button(t("widget.flow.m_short") + f"##tt_m_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("widget.flow.p_short") + f"##tt_p_{nid}", mode == "pin"):
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
        imgui.text_disabled(t("widget.flow.pin_only"))

    imgui.same_line(0, 4)
    imgui.text_disabled("|")
    imgui.same_line(0, 4)

    # 紧凑 timer 列表
    existing = _collect_timer_names(_canvas)
    current = inst.props.get("timer", "")
    items = [t("widget.flow.global_timer")] + existing
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
    if imgui.radio_button(t("common.manual") + f"##nt_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("common.pin") + f"##nt_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = inst.props.get("timer_name", "timer")
        imgui.push_item_width(130)
        changed, nv = imgui.input_text(t("common.name") + f"##nt_name_{nid}", v, 64)
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
    changed, nv = imgui.input_text_with_hint(t("widget.flow.timer") + f"##st_name_{nid}",
                                             t("widget.flow.timer_name_hint"), v, 64)
    if changed:
        inst.props["timer_name"] = nv

    create_missing = bool(inst.props.get("create_if_missing", True))
    changed, create_missing = imgui.checkbox(
        t("widget.flow.create_if_missing") + f"##st_create_{nid}", create_missing)
    if changed:
        inst.props["create_if_missing"] = bool(create_missing)

    # Operate
    operate = inst.props.get("operate", "reset")
    if imgui.radio_button(t("widget.flow.reset") + f"##st_op_rst_{nid}", operate == "reset"):
        inst.props["operate"] = "reset"
    imgui.same_line()
    if imgui.radio_button(t("widget.flow.set_time") + f"##st_op_set_{nid}", operate == "set_time"):
        inst.props["operate"] = "set_time"

    if operate == "set_time":
        mode = inst.props.get("mode", "manual")
        if imgui.radio_button(t("common.manual") + f"##st_m_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(t("common.pin") + f"##st_m_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        if mode == "manual":
            val = inst.props.get("value", 0.0)
            changed, nv = imgui.input_float(t("common.value") + f"##st_val_{nid}", val, format="%.2f")
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
    if imgui.radio_button(t("common.manual") + f"##vs_mode_man_{nid}", mode == "manual"):
        inst.props["mode"] = "manual"
    imgui.same_line()
    if imgui.radio_button(t("common.pin") + f"##vs_mode_pin_{nid}", mode == "pin"):
        inst.props["mode"] = "pin"

    if mode == "manual":
        v = inst.props.get("value", 0.0)
        changed, nv = imgui.input_float(t("common.value") + f"##vs_val_{nid}", v, format="%.4f")
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
    changed, nv = imgui.input_float(t("common.value") + f"##const_val_{nid}", v, format="%.4f")
    if changed:
        inst.props["value"] = nv
    imgui.pop_item_width()


# ── StringConst ────────────────────────────────────────────

@register("StringConst")
def _draw_string_constant_widgets(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(120)
    v = inst.props.get("value", "")
    changed, nv = imgui.input_text(t("common.value") + f"##strconst_val_{nid}", v)
    if changed:
        inst.props["value"] = nv
    imgui.pop_item_width()


