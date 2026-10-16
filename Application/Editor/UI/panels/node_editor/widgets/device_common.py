"""设备节点共用 widget 助手（SigGen 等设备节点共享） — widgets 包（注册表见 core.py）。"""

from __future__ import annotations

from imgui_bundle import imgui
from .core import _ne_combo

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
