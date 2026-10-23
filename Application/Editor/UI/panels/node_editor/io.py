"""节点编辑器 — Import / Export 弹窗。

实现与 agent ops（LiveCommandServer graph.import/export）同源：
统一走 Application.Core.NodeGraph.graph_io。
"""

from __future__ import annotations

import json
import os

from imgui_bundle import imgui

from Application.Core.NodeGraph import NodeCanvas
from Application.Editor.I18n import t
from Application.Editor.UI.FileDialog import FileDialog
from Application.Editor.UI.PanelStyle import ERROR_RED


class IOMixin:
    """Import / Export 两个 modal 及相关动作。"""

    def _draw_import_popup(self, canvas: NodeCanvas) -> None:
        """绘制 Import Graph 弹出窗口。"""
        if not imgui.begin_popup_modal(t("node_editor.import_title") + "###import_graph", None, imgui.WindowFlags_.always_auto_resize)[0]:
            return

        imgui.text(t("node_editor.import_prompt"))
        imgui.spacing()

        imgui.push_item_width(400)
        changed, self._import_path = imgui.input_text(
            "##import_path", self._import_path,
        )
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.small_button(t("node_editor.browse") + "##import"):
            FileDialog.open_json(
                callback=lambda p: setattr(self, '_import_path', p),
                start_dir=self._last_io_dir,
            )

        imgui.spacing()
        if self._import_error:
            imgui.text_colored(imgui.ImVec4(*ERROR_RED, 1.00), self._import_error)

        _, self._import_validate_first = imgui.checkbox(
            t("node_editor.import_validate_first"), self._import_validate_first)

        imgui.spacing()
        if imgui.button(t("node_editor.import"), imgui.ImVec2(100, 0)):
            self._do_import(canvas)

        imgui.same_line()
        if imgui.button(t("node_editor.cancel"), imgui.ImVec2(100, 0)):
            self._import_path = ""
            self._import_error = ""
            imgui.close_current_popup()

        imgui.end_popup()

    def _draw_export_popup(self, canvas: NodeCanvas) -> None:
        """绘制 Export Graph 弹出窗口。"""
        if not imgui.begin_popup_modal(t("node_editor.export_title") + "###export_graph", None, imgui.WindowFlags_.always_auto_resize)[0]:
            return

        imgui.text(t("node_editor.export_prompt"))
        imgui.spacing()

        imgui.push_item_width(400)
        changed, self._export_path = imgui.input_text(
            "##export_path", self._export_path,
        )
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.small_button(t("node_editor.browse") + "##export"):
            FileDialog.save_json(
                callback=lambda p: setattr(self, '_export_path', p),
                start_dir=self._last_io_dir,
            )

        imgui.spacing()
        n_count = len(canvas.nodes)
        l_count = len(canvas.links)
        groups = getattr(canvas, "node_groups", None) or {}
        imgui.text_disabled(t("node_editor.export_count", nodes=n_count, links=l_count,
                              groups=len(groups)))

        imgui.spacing()
        if self._export_error:
            imgui.text_colored(imgui.ImVec4(*ERROR_RED, 1.00), self._export_error)

        imgui.spacing()
        if imgui.button(t("node_editor.export"), imgui.ImVec2(100, 0)):
            self._do_export(canvas)

        imgui.same_line()
        if imgui.button(t("node_editor.cancel"), imgui.ImVec2(100, 0)):
            self._export_path = ""
            self._export_error = ""
            imgui.close_current_popup()

        imgui.end_popup()

    def _do_import(self, canvas: NodeCanvas) -> None:
        """执行导入：读取 + （可选）静态检查 → 替换画布内容。"""
        fp = self._import_path.strip()
        if not fp:
            self._import_error = "Please select a file."
            return

        from Application.Core.NodeGraph import graph_io

        try:
            data, refused = graph_io.prepare_import(
                path=fp, validate_first=self._import_validate_first)
        except json.JSONDecodeError as e:
            self._import_error = f"Invalid JSON:\n{e}"
            return
        except ValueError as e:
            self._import_error = str(e)
            return

        if refused is not None:
            errs = refused.get("static_errors") or []
            first = errs[0].get("message", "") if errs else ""
            self._import_error = f"Static check failed ({len(errs)} error(s)): {first}"
            return

        try:
            result = graph_io.apply_to_canvas(canvas, data)
        except Exception as e:
            self._import_error = f"Failed to parse graph:\n{e}"
            return

        self._last_io_dir = os.path.dirname(fp)
        print(f"[Import] Loaded {result['nodes']} nodes, {result['links']} links from {fp}")
        self._import_path = ""
        self._import_error = ""
        # 导入是整体替换：立即把视图对准新内容，避免停在旧图/极小缩放。
        self._fit_requested = True
        imgui.close_current_popup()

    def _do_export(self, canvas: NodeCanvas) -> None:
        """执行导出：序列化画布（含 _rules）→ JSON 文件。"""
        fp = self._export_path.strip()
        if not fp:
            self._export_error = "Please specify a file path."
            return

        from Application.Core.NodeGraph import graph_io

        try:
            result = graph_io.export_graph(canvas, path=fp, include_rules=True, inline=False)
        except Exception as e:
            self._export_error = f"Failed to write file:\n{e}"
            return

        fp = result["saved_path"]
        self._last_io_dir = os.path.dirname(fp)
        print(f"[Export] Saved {result['nodes']} nodes, {result['links']} links to {fp}")
        self._export_path = ""
        self._export_error = ""
        imgui.close_current_popup()
