"""Epoch 数据集节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from Application.Editor.I18n import t
from .core import register, _ne_combo

# ══════════════════════════════════════════════════════════════
# Epoch Dataset (epoch 数据集) — Append / Count / Clear / Save / Load
# ══════════════════════════════════════════════════════════════

def _draw_epochs_picker(nid: int, inst, key: str, canvas, allow_auto: bool,
                        prop: str = "epochs_name") -> None:
    """数据集下拉（画布 Append/Load 源）; allow_auto → 首项 "(Auto)"（唯一源自动绑定）。"""
    from Application.Core.NodeGraph.graph_constraints import (
        epoch_source_keys, nodes_as_dicts,
    )

    sources = epoch_source_keys(nodes_as_dicts(canvas)) if canvas is not None else {}
    names = sorted(sources.keys())
    cur = str(inst.props.get(prop, "")).strip()
    values = ([""] if allow_auto else []) + names
    labels = ([t("common.auto")] if allow_auto else []) + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(t("common.unlisted", name=cur))
    if not values:
        values, labels = [""], [t("common.no_datasets")]
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
    imgui.text_disabled(t("widget.epoch.dataset"))
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
    imgui.text_disabled(t("widget.epoch.epochs"))
    imgui.pop_item_width()
    name = str(inst.props.get("epochs_name", "")).strip()
    hint = t("widget.epoch.name_hint")
    if name:
        try:
            from Application.Functions.BCIAlgorithm import epoch_stats

            stats, _why = epoch_stats(name)
            hint = (t("widget.epoch.stats", count=stats['count'], classes=stats['classes'])
                    if stats else t("widget.epoch.not_captured"))
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
    imgui.text_disabled(t("widget.epoch.save_dir"))
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
    imgui.text_disabled(t("widget.epoch.epochs"))
    imgui.pop_item_width()
    imgui.push_item_width(220)
    changed, v = imgui.input_text(f"##epochs_file_{nid}",
                                  str(inst.props.get("file_path", "")))
    if changed:
        inst.props["file_path"] = v
    imgui.same_line()
    imgui.text_disabled(t("widget.epoch.npz_path"))
    imgui.pop_item_width()
    modes = ["replace", "append"]
    cur = str(inst.props.get("mode", "replace"))
    idx = modes.index(cur) if cur in modes else 0
    changed, ni = _ne_combo(f"##epochs_mode_{nid}", idx, [t("widget.epoch.replace"), t("widget.epoch.append")])
    if changed:
        inst.props["mode"] = modes[ni]
    imgui.same_line()
    imgui.text_disabled(t("widget.epoch.mode"))
    imgui.dummy(imgui.ImVec2(0, 2))


