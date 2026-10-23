"""节点编辑器 — Validate 任务 / 报告窗口 / 节点聚焦。"""

from __future__ import annotations

import json
import os

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Core.NodeGraph import NodeCanvas
from Application.Editor.I18n import t
from Application.Editor.UI.FileDialog import FileDialog
from Application.Editor.UI.PanelStyle import ERROR_RED


class ValidateMixin:
    """Validate 选项、任务轮询、报告窗口。"""

    _VALIDATE_MENU = [
        ("node_editor.validate.static", {"frames": 0}),
        ("node_editor.validate.dry360", {"frames": 360}),
        ("node_editor.validate.dry600", {"frames": 600}),
    ]

    def _validate_service(self):
        """引擎内校验服务单例（与 MCP 共享任务与报告）。"""
        from Application.Core.NodeGraph.validation import get_service

        return get_service()

    def _draw_validate_button(self) -> None:
        """工具栏 Validate 按钮（运行中显示进度; 完成后显示结果徽标 + Report 入口）。"""
        state = self._validate_service().state()
        if state.get("state") == "running":
            pct = int(float(state.get("progress", 0.0)) * 100)
            imgui.small_button(t("node_editor.validate.running", pct=pct))
            return
        if imgui.small_button(t("node_editor.validate.button")):
            imgui.open_popup("###validate_options")
        if self._report is not None:
            counts = self._report.get("counts") or {}
            errs = int(counts.get("errors", 0) or 0)
            warns = int(counts.get("warnings", 0) or 0)
            imgui.same_line()
            if self._report.get("ok"):
                imgui.text_colored(imgui.ImVec4(0.35, 0.85, 0.45, 1.0),
                                   t("node_editor.validate.ok", warnings=warns))
            else:
                imgui.text_colored(imgui.ImVec4(*ERROR_RED, 1.0),
                                   t("node_editor.validate.errors", errors=errs, warnings=warns))
            imgui.same_line()
            if imgui.small_button(t("node_editor.validate.report")):
                self._report_open = True

    def _draw_validate_popup(self, canvas: NodeCanvas) -> None:
        """Validate 选项菜单 + 每帧轮询任务完成（自动取回报告并弹窗）。"""
        self._poll_validate()

        if not imgui.begin_popup(t("node_editor.validate.options") + "###validate_options"):
            return
        imgui.text(t("node_editor.validate.prompt"))
        imgui.separator()
        validate_labels = [t("node_editor.validate.static"), t("node_editor.validate.dry360"),
                           t("node_editor.validate.dry600")]
        for label, (_key, preset) in zip(validate_labels, self._VALIDATE_MENU):
            if imgui.menu_item(label, "", False, True)[0]:
                opts = dict(self._validate_opts)
                opts.update(preset)
                self._start_validate(canvas, opts)
        imgui.separator()
        running = self._validate_service().state().get("state") == "running"
        if imgui.menu_item(t("node_editor.validate.cancel_running"), "", False, running)[0]:
            self._validate_service().cancel()
        imgui.end_popup()

    def _poll_validate(self) -> None:
        """任务完成后取回报告（UI 与 MCP 启动的任务都会被捕获）。"""
        svc = self._validate_service()
        state = svc.state()
        tid = state.get("task_id")
        if tid is None or state.get("state") == "running":
            return
        if self._validate_seen_report == tid:
            return
        report = svc.report(tid)
        if report is None:
            return
        self._validate_seen_report = int(tid)
        self._report = report
        self._report_open = True
        counts = report.get("counts") or {}
        tag = "OK" if report.get("ok") else f"{counts.get('errors', 0)} errors"
        print(f"[Validate] task#{tid} → {tag} ({counts})")

    def _start_validate(self, canvas: NodeCanvas, opts: dict) -> None:
        """发起校验（当前画布快照 → 服务 worker）。"""
        svc = self._validate_service()
        graph = canvas.to_dict()
        result = svc.start(graph, opts)
        if result.get("started"):
            self._validate_task_id = int(result.get("task_id"))
            self._validate_opts = dict(opts)
            self._report_note = ""
            print(f"[Validate] started task#{self._validate_task_id} opts={opts} "
                  f"({len(canvas.nodes)} nodes, {len(canvas.links)} links)")
        else:
            self._report_note = str(result.get("note")
                                   or t("node_editor.validate.already_running"))
            print(f"[Validate] start rejected: {self._report_note}")

    def _focus_node(self, nid: int) -> None:
        """报告/查询窗口 → 选中并居中到对应节点（API 缺失时静默降级）。"""
        if self._editor_context is None:
            return
        self._last_focused_node = int(nid)
        ne = node_ed
        try:
            ne.set_current_editor(self._editor_context)
            node_id = ne.NodeId(nid)
            ne.select_node(node_id)
            try:
                ne.center_node_on_screen(node_id)
            except Exception:  # noqa: BLE001
                try:
                    ne.navigate_to_selection()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            print(f"[Validate] focus node {nid} failed: {e}")

    def _report_text(self) -> str:
        """报告 → 纯文本（剪贴板 / 导出用）。"""
        r = self._report or {}
        lines = [f"Validation task#{r.get('task_id')} state={r.get('state')} ok={r.get('ok')}"]
        for ent in (r.get("static") or {}).get("errors") or []:
            lines.append(f"  [static][error] {ent.get('message')}")
        for ent in (r.get("static") or {}).get("warnings") or []:
            lines.append(f"  [static][warn]  {ent.get('message')}")
        for err in (r.get("runtime") or {}).get("errors") or []:
            lines.append(f"  [runtime][error] {err}")
        for ent in r.get("log") or []:
            lines.append(
                f"  f{ent.get('frame')} #{ent.get('node_id')}<{ent.get('node_type')}> "
                f"{ent.get('action')} | {ent.get('detail')}"
            )
        return "\n".join(lines)

    def _save_report(self, path: str) -> None:
        """报告落盘（.json）。"""
        if not path or self._report is None:
            return
        try:
            if not path.lower().endswith(".json"):
                path += ".json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._report, fh, indent=2, ensure_ascii=False)
            self._last_io_dir = os.path.dirname(path)
            print(f"[Validate] report exported: {path}")
        except Exception as e:  # noqa: BLE001
            print(f"[Validate] report export failed: {e}")

    def _draw_report_window(self) -> None:
        """验证报告窗口（非 modal; 条目可点击跳转节点）。"""
        if not self._report_open or self._report is None:
            return
        report = self._report
        imgui.set_next_window_size(imgui.ImVec2(560, 430), imgui.Cond_.first_use_ever)
        visible, still_open = imgui.begin(t("node_editor.report.title"), self._report_open)
        if still_open is not None:
            self._report_open = bool(still_open)
        if visible:
            graph = report.get("graph") or {}
            timing = report.get("timing") or {}
            counts = report.get("counts") or {}
            runtime = report.get("runtime") or {}
            state = report.get("state")
            if report.get("ok"):
                imgui.text_colored(
                    imgui.ImVec4(0.35, 0.85, 0.45, 1.0),
                    t("node_editor.report.passed", nodes=graph.get('nodes'),
                      links=graph.get('links'), ms=timing.get('duration_ms')),
                )
            else:
                label = t("node_editor.report.cancelled") if state == "cancelled" else t("node_editor.report.failed")
                imgui.text_colored(
                    imgui.ImVec4(*ERROR_RED, 1.0),
                    t("node_editor.report.failed_detail", label=label,
                      errors=counts.get('errors', 0), warnings=counts.get('warnings', 0)),
                )
            imgui.text_disabled(
                t("node_editor.report.meta", task=report.get('task_id'),
                  hash=graph.get('hash'), frames=runtime.get('frames_simulated'),
                  events=runtime.get('total_events'))
            )
            if self._report_note:
                imgui.text_colored(imgui.ImVec4(0.90, 0.70, 0.30, 1.00), self._report_note)

            imgui.separator()

            def _section(title: str, entries: list, color) -> None:
                if not entries:
                    return
                imgui.text_colored(color, f"{title} ({len(entries)})")
                for idx, ent in enumerate(entries):
                    if isinstance(ent, dict):
                        msg = str(ent.get("message", ent))
                        nid = ent.get("node_id")
                    else:
                        msg, nid = str(ent), None
                    label = f"  [{nid}] {msg}" if nid is not None else f"  {msg}"
                    # Stable id even when two report entries have identical text.
                    if imgui.selectable(f"{label}##report_{idx}", False)[0] and nid is not None:
                        self._focus_node(int(nid))
                imgui.spacing()

            _red = imgui.ImVec4(*ERROR_RED, 1.00)
            _yellow = imgui.ImVec4(0.90, 0.75, 0.30, 1.00)
            _section(t("node_editor.report.static_errors"), (report.get("static") or {}).get("errors") or [], _red)
            _section(t("node_editor.report.static_warnings"), (report.get("static") or {}).get("warnings") or [], _yellow)
            _section(t("node_editor.report.runtime_errors"), runtime.get("errors") or [], _red)

            log = report.get("log") or []
            if log and imgui.collapsing_header(t("node_editor.report.event_log", count=len(log))):
                shown = log[:300]
                for ent in shown:
                    imgui.text_disabled(
                        f"f{ent.get('frame'):>4} #{ent.get('node_id')}<{ent.get('node_type')}> "
                        f"{ent.get('action')} | {ent.get('detail')}"
                    )
                if len(log) > len(shown):
                    imgui.text_disabled(t("node_editor.report.more", count=len(log) - len(shown)))

            imgui.separator()
            if imgui.button(t("node_editor.report.copy")):
                imgui.set_clipboard_text(self._report_text())
            imgui.same_line()
            if imgui.button(t("node_editor.report.export")):
                FileDialog.save_json(
                    callback=self._save_report,
                    default_name=f"validation_report_task{report.get('task_id')}.json",
                    start_dir=self._last_io_dir,
                )
            imgui.same_line()
            if imgui.button(t("node_editor.report.close")):
                self._report_open = False
        imgui.end()
