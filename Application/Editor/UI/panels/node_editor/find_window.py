"""节点编辑器 — Find Node 窗口（搜索 / Go To / Delete）。"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Core.NodeGraph import NodeCanvas, _TYPES
from Application.Editor.I18n import t


class FindWindowMixin:
    """按 alias / type / label / description 搜索节点。"""

    @staticmethod
    def _node_search_blob(inst) -> str:
        ndef = _TYPES.get(inst.node_type)
        label = ndef.label if ndef else inst.node_type
        parts = [
            str(getattr(inst, "alias", "") or ""),
            str(inst.node_type),
            str(label),
            str(getattr(inst, "description", "") or ""),
        ]
        parts.extend(str(v) for v in (inst.props or {}).values()
                     if isinstance(v, (str, int, float, bool)))
        return " ".join(parts).lower()

    def _find_results(self, canvas: NodeCanvas) -> list[int]:
        query = self._find_query.strip().lower()
        tokens = [part for part in query.split() if part]
        scored: list[tuple[int, str, int]] = []
        for nid, inst in canvas.nodes.items():
            blob = self._node_search_blob(inst)
            if tokens and not all(tok in blob for tok in tokens):
                continue
            alias = str(getattr(inst, "alias", "") or "").lower()
            ndef = _TYPES.get(inst.node_type)
            label = str(ndef.label if ndef else inst.node_type).lower()
            if not query:
                rank = 5
            elif alias.startswith(query):
                rank = 0
            elif query in alias:
                rank = 1
            elif inst.node_type.lower().startswith(query):
                rank = 2
            elif label.startswith(query):
                rank = 3
            else:
                rank = 4
            scored.append((rank, alias or inst.node_type.lower(), nid))
        scored.sort()
        return [nid for _rank, _name, nid in scored]

    def _delete_find_selected(self, canvas: NodeCanvas) -> bool:
        """Delete the current find result (query window button + tests)."""
        selected = self._find_selected
        if selected is None or selected not in canvas.nodes:
            return False
        inst = canvas.nodes.get(int(selected))
        canvas.remove_node(int(selected))
        print(f"[FindNode] deleted nid={selected} "
              f"type={getattr(inst, 'node_type', '?')}")
        self._find_selected = None
        return True

    def _draw_find_window(self, canvas: NodeCanvas) -> None:
        if not self._find_open:
            return
        imgui.set_next_window_size(imgui.ImVec2(460, 390), imgui.Cond_.first_use_ever)
        visible, still_open = imgui.begin(
            t("node_editor.find_title") + "###node_find", self._find_open)
        if still_open is not None:
            self._find_open = bool(still_open)
        if not visible:
            imgui.end()
            return
        try:
            imgui.text_disabled(t("node_editor.find_hint"))
            imgui.set_next_item_width(imgui.get_content_region_avail().x)
            if self._find_focus:
                imgui.set_keyboard_focus_here()
                self._find_focus = False
            changed, query = imgui.input_text(
                "##node_find_query", self._find_query,
                imgui.InputTextFlags_.auto_select_all)
            if changed:
                self._find_query = query
                self._find_selected = None

            results = self._find_results(canvas)
            imgui.text_disabled(t("node_editor.find_count", count=len(results)))
            list_h = max(80.0, float(imgui.get_content_region_avail().y) - 38.0)
            child_visible = imgui.begin_child(
                "##node_find_list", imgui.ImVec2(0, list_h), True)
            try:
                if child_visible:
                    if not results:
                        imgui.text_disabled(t("node_editor.find_none"))
                    for nid in results:
                        inst = canvas.nodes.get(nid)
                        if inst is None:
                            continue
                        alias = str(getattr(inst, "alias", "") or "")
                        ndef = _TYPES.get(inst.node_type)
                        label = ndef.label if ndef else inst.node_type
                        shown = f"@{alias}" if alias else t("node_editor.find_unnamed")
                        # Always expose the stable node id: unnamed nodes have
                        # identical display text by definition.
                        text = f"#{nid}  {shown}   [{inst.node_type}]   {label}"
                        if imgui.selectable(
                                f"{text}##find_{nid}",
                                nid == self._find_selected)[0]:
                            self._find_selected = nid
                            if imgui.is_mouse_double_clicked(0):
                                self._focus_node(nid)
            finally:
                imgui.end_child()

            selected = self._find_selected
            exists = selected is not None and selected in canvas.nodes
            imgui.begin_disabled(not exists)
            if imgui.button(t("node_editor.find_go"), imgui.ImVec2(150, 0)):
                if exists:
                    self._focus_node(int(selected))
            imgui.same_line()
            if imgui.button(t("node_editor.find_delete"), imgui.ImVec2(150, 0)):
                self._delete_find_selected(canvas)
            imgui.end_disabled()
        finally:
            imgui.end()
