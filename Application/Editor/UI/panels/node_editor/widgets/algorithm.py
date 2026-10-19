"""BCI Algorithm（FBCSP/CCA）节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from Application.Editor.I18n import t
from .core import register, _ne_combo
from .epoch import _draw_epochs_picker

# ══════════════════════════════════════════════════════════════
# BCI Algorithm (FBCSP / CCA) — Init / Train / Test
# ══════════════════════════════════════════════════════════════

def _draw_band_editor(nid: int, inst) -> None:
    """bands 动态组编辑器（打包 props["bands"]: [[lo,hi], ...]; 空 = 普通 CSP）。"""
    bands = inst.props.get("bands")
    if not isinstance(bands, list):
        bands = [[4.0, 8.0], [8.0, 13.0], [13.0, 30.0]]
        inst.props["bands"] = bands
    imgui.text_disabled(t("widget.algorithm.bands", count=len(bands)))
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
    imgui.text_disabled(t("widget.algorithm.add_band"))


def _draw_freq_editor(nid: int, inst) -> None:
    """freqs 动态组编辑器（>= 2 不限上限; props["freqs"]: [f, ...]）。"""
    freqs = inst.props.get("freqs")
    if not isinstance(freqs, list):
        freqs = [10.0, 12.0, 15.0]
        inst.props["freqs"] = freqs
    imgui.text_disabled(t("widget.algorithm.freqs", count=len(freqs)))
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
    imgui.text_disabled(t("widget.algorithm.add_freq"))


def _draw_model_picker(nid: int, inst, key: str, canvas, kind: str) -> None:
    """模型下拉: kind="specs"（InitFBCSP 源） / "models"（TrainFBCSP 源）。"""
    from Application.Core.NodeGraph.graph_constraints import (
        model_source_keys, nodes_as_dicts,
    )

    src: dict = {}
    if canvas is not None:
        src = model_source_keys(nodes_as_dicts(canvas)).get(kind, {})
    names = sorted(src.keys())
    cur = str(inst.props.get("model_name", "")).strip()
    values = [""] + names
    labels = [t("common.auto")] + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(t("common.unlisted", name=cur))
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
    imgui.text_disabled(t("widget.algorithm.model"))
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
    imgui.text_disabled(t("widget.algorithm.model"))
    imgui.pop_item_width()
    imgui.push_item_width(60)
    changed, v = imgui.input_int(f"##fb_m_{nid}",
                                 int(inst.props.get("n_components", 2)))
    if changed:
        inst.props["n_components"] = max(1, min(8, int(v)))
    imgui.same_line()
    imgui.text_disabled(t("widget.algorithm.csp_pairs"))
    imgui.pop_item_width()
    cls_keys = ["LDA", "SVM"]
    cur = str(inst.props.get("classifier", "LDA")).upper()
    idx = cls_keys.index(cur) if cur in cls_keys else 0
    changed, ni = _ne_combo(f"##fb_clf_{nid}", idx, cls_keys)
    if changed:
        inst.props["classifier"] = cls_keys[ni]
    imgui.same_line()
    imgui.text_disabled(t("widget.algorithm.classifier"))
    _draw_band_editor(nid, inst)


@register("TrainFBCSP")
def _draw_train_fbcsp_widgets(nid: int, inst, _canvas) -> None:
    _draw_model_picker(nid, inst, "tr", _canvas, "specs")
    _draw_epochs_picker(nid, inst, "trds", _canvas, allow_auto=True,
                        prop="dataset_name")
    modes = ["train", "load"]
    cur = str(inst.props.get("mode", "train")).lower()
    idx = modes.index(cur) if cur in modes else 0
    changed, ni = _ne_combo(f"##tr_mode_{nid}", idx, [t("widget.algorithm.train"), t("widget.algorithm.load")])
    if changed:
        inst.props["mode"] = modes[ni]
    imgui.same_line()
    imgui.text_disabled(t("widget.algorithm.mode"))
    if modes[idx] == "load":
        imgui.push_item_width(200)
        changed, v = imgui.input_text(f"##tr_path_{nid}",
                                      str(inst.props.get("model_path", "")))
        if changed:
            inst.props["model_path"] = v
        imgui.same_line()
        imgui.text_disabled(t("widget.algorithm.model_npz"))
        imgui.pop_item_width()
    else:
        imgui.push_item_width(150)
        changed, v = imgui.input_text(f"##tr_save_{nid}",
                                      str(inst.props.get("save_path", "")))
        if changed:
            inst.props["save_path"] = v
        imgui.same_line()
        imgui.text_disabled(t("widget.algorithm.save_npz"))
        imgui.pop_item_width()
    imgui.text_disabled(t("widget.algorithm.blocks_exec"))


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
    imgui.text_disabled(t("widget.algorithm.harmonics"))
    imgui.pop_item_width()
