"""IO▸SigGen 设备节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from .core import register, _ne_combo
from .device_common import _device_name_field

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


