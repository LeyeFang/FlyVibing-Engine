"""节点编辑器 — Groups 窗口（嵌套树 / 重排 / Fit / Ungroup / Destroy）。"""

from __future__ import annotations

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Core.NodeGraph import NodeCanvas
from Application.Core.NodeGraph.group_nodes import all_io_node_ids
from Application.Core.NodeGraph.group_ops import (
    rename_group,
    set_group_description,
)
from Application.Editor.I18n import t
from Application.Editor.UI.PanelStyle import ERROR_RED
from .group_layout import group_depth, group_member_ids, group_order


class GroupsWindowMixin:
    """Groups 窗口；组创建不在工具栏，由画布右键 Merge 产生。"""

    def _draw_groups_window(self, canvas: NodeCanvas) -> None:
        if not self._groups_open:
            return
        imgui.set_next_window_size(imgui.ImVec2(400, 430), imgui.Cond_.first_use_ever)
        visible, still_open = imgui.begin(
            t("node_editor.groups_title") + "###node_groups", self._groups_open)
        if still_open is not None:
            self._groups_open = bool(still_open)
        if not visible:
            imgui.end()
            return
        try:
            groups = getattr(canvas, "node_groups", None) or {}
            if not groups:
                imgui.text_disabled(t("node_editor.groups_empty"))
            else:
                imgui.text_disabled(t("node_editor.groups_hint"))
                child_visible = imgui.begin_child(
                    "##node_group_tree", imgui.ImVec2(0, -196), True)
                try:
                    if child_visible:
                        for gid in group_order(canvas):
                            grp = groups.get(gid) or {}
                            depth = group_depth(canvas, gid)
                            alias = str(grp.get("alias") or gid)
                            gtype = str(grp.get("type") or "group")
                            io_ids = all_io_node_ids(canvas, gid)
                            count = len([nid for nid in group_member_ids(canvas, gid)
                                         if nid not in io_ids])
                            label = f"{'  ' * depth}{alias} [{gtype}] ({count})"
                            if imgui.selectable(
                                    f"{label}##group_{gid}",
                                    gid == self._active_group)[0]:
                                self._active_group = gid
                finally:
                    imgui.end_child()
                active = self._active_group
                valid = active in groups
                if valid:
                    grp = groups.get(active) or {}
                    current_alias = str(grp.get("alias") or active)
                    if self._group_alias_gid != active:
                        self._group_alias_gid = active
                        self._group_alias_buf = current_alias
                        self._group_alias_error = ""
                    imgui.text_disabled(t("node_editor.groups_name"))
                    imgui.same_line()
                    imgui.set_next_item_width(-1)
                    changed, value = imgui.input_text(
                        "##group_alias", self._group_alias_buf,
                        imgui.InputTextFlags_.enter_returns_true)
                    if changed:
                        self._group_alias_buf = value
                    apply = (imgui.is_item_deactivated_after_edit()
                             or (imgui.is_item_focused()
                                 and imgui.is_key_pressed(imgui.Key.enter)))
                    if apply:
                        result = rename_group(canvas, active,
                                              self._group_alias_buf)
                        if result.get("ok"):
                            self._group_alias_buf = str(result.get("alias") or "")
                            self._group_alias_error = ""
                        else:
                            self._group_alias_error = "; ".join(
                                result.get("errors") or ["rename failed"])
                    if self._group_alias_error:
                        imgui.text_colored(ERROR_RED, self._group_alias_error)
                    elif not imgui.is_item_active() \
                            and current_alias != self._group_alias_buf:
                        # 外部工具/其它入口重命名后，未聚焦的输入框跟随刷新。
                        self._group_alias_buf = current_alias
                    if imgui.is_item_hovered():
                        imgui.set_tooltip(t("node_editor.groups_name_tip"))
                    current_desc = str(grp.get("description") or "")
                    if self._group_desc_gid != active:
                        self._group_desc_gid = active
                        self._group_desc_buf = current_desc
                    imgui.text_disabled(t("node_editor.groups_description"))
                    imgui.set_next_item_width(-1)
                    changed, value = imgui.input_text_multiline(
                        "##group_desc", self._group_desc_buf,
                        imgui.ImVec2(-1, 54))
                    if changed:
                        self._group_desc_buf = value
                    if imgui.is_item_deactivated_after_edit():
                        set_group_description(canvas, active,
                                              self._group_desc_buf)
                    elif not imgui.is_item_active() \
                            and current_desc != self._group_desc_buf:
                        # 外部编辑/导入后，未聚焦时跟随刷新。
                        self._group_desc_buf = current_desc
                    if imgui.is_item_hovered():
                        imgui.set_tooltip(t("node_editor.groups_description_tip"))
                imgui.begin_disabled(not valid)
                if imgui.button(t("node_editor.groups_rearrange"),
                                imgui.ImVec2(180, 0)):
                    self._auto_layout_group(canvas, active)
                imgui.same_line()
                if imgui.button(t("node_editor.groups_fit"), imgui.ImVec2(150, 0)):
                    self._fit_group_pending = active
                imgui.end_disabled()
                imgui.begin_disabled(not valid)
                if imgui.button(t("node_editor.groups_ungroup"),
                                imgui.ImVec2(150, 0)):
                    self._ungroup_group_action(canvas, node_ed, active)
                imgui.same_line()
                if imgui.button(t("node_editor.groups_destroy"),
                                imgui.ImVec2(150, 0)):
                    self._destroy_group_action(canvas, node_ed, active)
                if imgui.is_item_hovered():
                    imgui.set_tooltip(t("node_editor.groups_destroy_tip"))
                imgui.end_disabled()
                if imgui.button(t("node_editor.groups_all"), imgui.ImVec2(0, 0)):
                    self._auto_layout(canvas)
        finally:
            imgui.end()
