"""节点编辑器 — 画布右键菜单（Delete Node / Merge / Ungroup / Destroy Group）。"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Core.NodeGraph import NodeCanvas
from Application.Core.NodeGraph.group_nodes import (
    ensure_group_io_nodes,
    group_io_owner,
)
from Application.Core.NodeGraph.group_ops import (
    destroy_group,
    merge_nodes,
    ungroup,
)
from Application.Editor.I18n import t
from Application.Editor.UI.PanelStyle import ERROR_RED
from .group_layout import group_depth


class GroupContextMixin:
    """右键节点 → Delete；多选 → Merge；右键组框 → Ungroup / Destroy。"""

    @staticmethod
    def _group_hit_point(rect, mouse) -> bool:
        """组框命中：标题栏或边框附近；内部空白不算。

        imgui-node-editor 的组框中心是可框选的“洞”；若整块矩形都算
        组框，组内空白拖拽会被误判为拖组，无法框选成员。
        """
        if not (rect[0] <= mouse[0] <= rect[2]
                and rect[1] <= mouse[1] <= rect[3]):
            return False
        edge = 10.0
        header_h = 34.0
        return (mouse[1] <= rect[1] + header_h
                or mouse[0] <= rect[0] + edge
                or mouse[0] >= rect[2] - edge
                or mouse[1] >= rect[3] - edge)

    def _group_at_screen(self, canvas: NodeCanvas, ne) -> str:
        """组框命中测试（imgui-node-editor 对组框的 hovered 状态不可靠）。

        组框按 depth 从深到浅找，保证嵌套组点到最内层；点在节点上时由
        调用方优先按真实节点处理。
        """
        groups = getattr(canvas, "node_groups", None) or {}
        if not groups:
            return ""
        mouse = getattr(self, "_mouse_screen", None)
        if mouse is None:
            try:
                raw = imgui.get_mouse_pos()
                mouse = (float(raw.x), float(raw.y))
            except Exception:  # noqa: BLE001
                return ""
        hits: list[str] = []
        for gid in groups:
            # 只使用绘制帧内的屏幕矩形；end() 之后调用 canvas_to_screen
            # 会按当前 ImGui 窗口解析，可能命中错误的组框。
            rect = getattr(self, "_group_screen_rects", {}).get(str(gid))
            if rect is None:
                continue
            if self._group_hit_point(rect, mouse):
                hits.append(str(gid))
        if not hits:
            return ""
        return max(hits, key=lambda gid: group_depth(canvas, gid))

    def _open_group_context(self, canvas: NodeCanvas, ne) -> None:
        """右键画布：节点 → Delete；多选 → Merge；组框 → Ungroup/Destroy。"""
        self._group_action_error = ""
        hid = int(self._hovered_node_id)
        selected = set(self._selected_real_nodes(canvas, ne))
        io_owner = group_io_owner(canvas, hid) if hid in canvas.nodes else None
        if io_owner:
            # 组入口/出口锚点属于组框，右键应操作组而不是内部节点。
            kind = "group"
            gid = io_owner
            selected = set()
        elif hid in canvas.nodes:
            kind = "node"
            gid = ""
            if hid not in selected:
                selected = {hid}
                try:
                    ne.clear_selection()
                    ne.select_node(ne.NodeId(hid))
                except Exception:  # noqa: BLE001
                    pass
        else:
            # 组框 padding / 嵌套组区域 hovered 可能为 0，直接做矩形命中。
            gid = self._group_at_screen(canvas, ne)
            kind = "group" if gid else "background"
            hid = 0
        # 空白处右键也打开菜单：零选择时显示 no selected node，
        # 单选时提供 Delete Node，多选时提供 Merge。
        self._group_context_kind = kind
        self._group_context_gid = gid
        self._group_context_selection = selected
        imgui.open_popup("###node_group_context")

    def _merge_group_from_selection(self, canvas: NodeCanvas, ne) -> None:
        result = merge_nodes(canvas, sorted(self._group_context_selection))
        if not result.get("ok"):
            self._group_action_error = "; ".join(result.get("errors") or [])
            return
        self._active_group = str(result.get("gid") or "")
        self._group_action_error = ""
        # 组创建即获得自己的 GroupStart/GroupEnd（普通节点，可自由拖线）。
        ensure_group_io_nodes(canvas, self._active_group,
                              getattr(self, "_node_size_for_group", None))
        print(f"[Group] merged {result.get('nodes')} node(s) → "
              f"{result.get('gid')} (@{result.get('alias')})")
        try:
            ne.clear_selection()
            ne.select_node(ne.NodeId(self._group_editor_id(self._active_group)))
        except Exception:  # noqa: BLE001
            pass

    def _ungroup_group_action(self, canvas: NodeCanvas, ne, gid: str) -> None:
        result = ungroup(canvas, gid)
        if not result.get("ok"):
            self._group_action_error = "; ".join(result.get("errors") or [])
            return
        self._group_action_error = ""
        if self._active_group == gid:
            self._active_group = ""
        try:
            ne.deselect_node(ne.NodeId(self._group_editor_id(gid)))
        except Exception:  # noqa: BLE001
            pass
        print(f"[Group] ungrouped {gid}")

    def _destroy_group_action(self, canvas: NodeCanvas, ne, gid: str) -> None:
        """销毁组：组框、子组和全部成员节点一起删除（区别于 Ungroup）。"""
        result = destroy_group(canvas, gid)
        if not result.get("ok"):
            self._group_action_error = "; ".join(result.get("errors") or [])
            return
        self._group_action_error = ""
        if self._active_group == gid:
            self._active_group = ""
        self._group_context_selection = set()
        try:
            ne.clear_selection()
        except Exception:  # noqa: BLE001
            pass
        print(f"[Group] destroyed {gid} "
              f"({len(result.get('removed_groups') or [])} group frame(s), "
              f"{len(result.get('removed_nodes') or [])} node(s))")

    # 兼容旧调用名；语义已改为全删。
    def _delete_group_action(self, canvas: NodeCanvas, ne, gid: str) -> None:
        self._destroy_group_action(canvas, ne, gid)

    def _draw_group_context_menu(self, canvas: NodeCanvas, ne) -> None:
        if imgui.is_mouse_clicked(1):
            self._open_group_context(canvas, ne)
        if not imgui.begin_popup("###node_group_context"):
            return
        try:
            kind = self._group_context_kind
            if kind == "group":
                gid = self._group_context_gid
                grp = (getattr(canvas, "node_groups", None) or {}).get(gid) or {}
                alias = str(grp.get("alias") or gid)
                imgui.text_disabled(f"@{alias}   [{gid}]")
                imgui.separator()
                if imgui.menu_item(t("node_editor.groups_rename")
                                   + "###ctx_rename", "", False, True)[0]:
                    self._start_group_inline_edit(gid, "name", grp)
                    imgui.close_current_popup()
                if imgui.menu_item(t("node_editor.groups_edit_description")
                                   + "###ctx_desc", "", False, True)[0]:
                    self._start_group_inline_edit(gid, "description", grp)
                    imgui.close_current_popup()
                if imgui.menu_item(t("node_editor.groups_ungroup")
                                   + "###ctx_ungroup", "", False, True)[0]:
                    self._ungroup_group_action(canvas, ne, gid)
                    imgui.close_current_popup()
                if imgui.menu_item(t("node_editor.groups_destroy")
                                   + "###ctx_destroy", "", False, True)[0]:
                    self._destroy_group_action(canvas, ne, gid)
                    imgui.close_current_popup()
            elif kind in ("node", "background"):
                count = len([n for n in self._group_context_selection
                             if n in canvas.nodes])
                if count >= 1:
                    label = (t("node_editor.delete_node") if count == 1
                             else t("node_editor.delete_nodes", count=count))
                    if imgui.menu_item(label + "###ctx_delete_node",
                                       "", False, True)[0]:
                        self._delete_selected_nodes(canvas, ne)
                        imgui.close_current_popup()
                if count >= 2:
                    if imgui.menu_item(
                            t("node_editor.groups_merge", count=count)
                            + "###ctx_merge", "", False, True)[0]:
                        self._merge_group_from_selection(canvas, ne)
                        imgui.close_current_popup()
                elif kind == "background" and count == 0:
                    imgui.text_disabled(t("node_editor.no_selected_node"))
            if self._group_action_error:
                imgui.separator()
                imgui.text_colored(imgui.ImVec4(*ERROR_RED, 1.0),
                                   self._group_action_error)
        finally:
            imgui.end_popup()
