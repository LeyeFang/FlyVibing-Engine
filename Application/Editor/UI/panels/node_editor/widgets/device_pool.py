"""IO▸Pool 设备池节点 widget — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from Application.Editor.I18n import t
from .core import register, _ne_combo

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
    imgui.text_disabled(t("device.pool_name"))
    imgui.pop_item_width()
    imgui.dummy(imgui.ImVec2(0, 2))


def _draw_pool_picker(nid: int, inst, key: str, canvas, allow_auto: bool) -> None:
    """已注册(画布)池下拉; allow_auto → 首项 "(Auto)" (空名 + 唯一 Create 自动绑定)。"""
    from Application.Core.NodeGraph.graph_constraints import device_inventory

    inv = device_inventory(canvas)
    names = sorted(inv["pools"].keys())
    cur = str(inst.props.get("pool_name", "")).strip()
    values = ([""] if allow_auto else []) + names
    labels = ([t("common.auto")] if allow_auto else []) + names
    if cur and cur not in names:
        values.append(cur)
        labels.append(t("common.unlisted", name=cur))
    if not values:
        values, labels = [""], [t("common.no_pools")]
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
    imgui.text_disabled(t("common.pool"))
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
    imgui.text_disabled(t("device.pin_unlinked") if not src else f"  <- {src}")


@register("KillDevicePool")
def _draw_kill_pool_widgets(nid: int, inst, _canvas) -> None:
    _draw_pool_picker(nid, inst, "kill", _canvas, allow_auto=True)


