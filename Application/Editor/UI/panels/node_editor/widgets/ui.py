"""UI 节点 widget —— 目标实体名下拉 + 过滤/开关/数值字段。

- `SetUIVisible`：目标（场景实体名）+ 可见开关
- `SetUIText`：目标（场景实体名）+ 文本
- `OnUIClick`：`action` / `name` 过滤（空 = 不过滤）
- `GetUIValue`：目标（场景实体名）
"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Editor.I18n import t
from .core import register, _ne_combo, _get_scene_template_names


def _draw_target_combo(nid: int, inst, prop_key: str, combo_id: str) -> None:
    """场景实体名下拉 + 自定义输入（UI 实体也在场景里，所以直接复用）。"""
    labels = _get_scene_template_names()
    current = str(inst.props.get(prop_key, "") or "")
    items = labels + [t("widget.entity.custom")] if labels else [t("widget.entity.custom")]
    try:
        idx = labels.index(current) if current in labels else len(items) - 1
    except ValueError:
        idx = len(items) - 1
    changed, new_idx = _ne_combo(f"##{combo_id}_{nid}", idx, items)
    if changed and new_idx < len(labels):
        inst.props[prop_key] = labels[new_idx]
    if idx >= len(labels) or not labels:
        # 隐藏标签（"##" 前缀）—— 拼接而非 f-string，i18n 扫描器只认整串常量/JoinedStr
        changed, text = imgui.input_text("##" + combo_id + "_txt_" + str(nid), current)
        if changed:
            inst.props[prop_key] = text


@register("SetUIVisible")
def _draw_set_ui_visible(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    _draw_target_combo(nid, inst, "target", "suiv_tgt")
    imgui.same_line()
    visible = bool(inst.props.get("visible", True))
    changed, visible = imgui.checkbox(t("widget.ui.visible") + f"##suiv_vis_{nid}", visible)
    if changed:
        inst.props["visible"] = bool(visible)
    imgui.pop_item_width()


@register("SetUIText")
def _draw_set_ui_text(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    _draw_target_combo(nid, inst, "target", "suit_tgt")
    imgui.same_line()
    current = str(inst.props.get("text", "") or "")
    changed, text = imgui.input_text(t("widget.ui.text") + "##suit_txt_" + str(nid), current)
    if changed:
        inst.props["text"] = text
    imgui.pop_item_width()


@register("OnUIClick")
def _draw_on_ui_click(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)

    current = str(inst.props.get("action", "") or "")
    changed, text = imgui.input_text(f"##ouc_act_{nid}", current)
    if changed:
        inst.props["action"] = text.strip()
    imgui.same_line()
    imgui.text_disabled(t("widget.ui.action"))

    current = str(inst.props.get("name", "") or "")
    changed, text = imgui.input_text(f"##ouc_name_{nid}", current)
    if changed:
        inst.props["name"] = text.strip()
    imgui.same_line()
    imgui.text_disabled(t("widget.ui.name"))

    imgui.pop_item_width()


@register("GetUIValue")
def _draw_get_ui_value(nid: int, inst, _canvas) -> None:
    imgui.dummy(imgui.ImVec2(0, 2))
    imgui.push_item_width(130)
    _draw_target_combo(nid, inst, "target", "guv_tgt")
    imgui.pop_item_width()
