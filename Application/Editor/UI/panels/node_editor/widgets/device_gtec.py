"""IO▸Gtec 设备节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from .core import register, _ne_combo
from .device_common import _device_name_field

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


