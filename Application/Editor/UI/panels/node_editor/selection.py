"""节点编辑器 — 多选 / 框选交互。

从 NodeEditorPanel 拆出的 SelectionMixin；状态仍由面板 __init__ 持有，
这样面板依旧是 UI 生命周期的唯一入口。
"""

from __future__ import annotations

from imgui_bundle import imgui

from Application.Core.Input import IsShiftPressed
from Application.Core.NodeGraph import NodeCanvas


class SelectionMixin:
    """Shift+click 追加选择、框选命中与选择快照。"""

    @staticmethod
    def _selected_node_ids(ne) -> list[int]:
        try:
            return [int(n.id()) for n in ne.get_selected_nodes()]
        except Exception:  # noqa: BLE001 — editor not initialized yet
            return []

    def _selected_real_nodes(self, canvas: NodeCanvas, ne) -> list[int]:
        return sorted(nid for nid in self._selected_node_ids(ne)
                      if nid in canvas.nodes)

    def _selected_group_ids(self, canvas: NodeCanvas, ne) -> list[str]:
        out: list[str] = []
        for eid in self._selected_node_ids(ne):
            gid = self._group_for_editor_id(canvas, eid)
            if gid:
                out.append(gid)
        return out

    @staticmethod
    def _shift_down() -> bool:
        """Shift 状态优先读引擎 InputState；ImGui 注入场景作为回退。"""
        try:
            if IsShiftPressed():
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            return bool(imgui.get_io().key_shift)
        except Exception:  # noqa: BLE001
            return False

    def _reset_box_state(self) -> None:
        self._box_selecting = False
        self._box_select_released = False
        self._box_settle = 0
        self._box_drag_seen = False
        self._box_start_screen = None

    def _mouse_screen_pos(self) -> tuple[float, float]:
        """当前鼠标的屏幕坐标。

        imgui-node-editor 把画布内 ImGui 鼠标坐标变成画布空间，直接与
        _node_screen_rects / _canvas_rect（屏幕坐标）比较会把框选拖到
        错误位置。优先用面板绘制帧缓存的转换值。
        """
        cached = getattr(self, "_mouse_screen", None)
        if cached is not None:
            return cached
        mouse = imgui.get_mouse_pos()
        return (float(mouse.x), float(mouse.y))

    def _update_box_selection_state(self, canvas: NodeCanvas, ne) -> None:
        """记录“从空白背景开始拖拽”的框选。"""
        # 焦点丢失/面板外 release 可能让状态卡在“按住中”；下一帧鼠标已
        # 不在按下时立即清理，避免下一次点击复用旧矩形误选节点。
        if self._box_selecting and not imgui.is_mouse_down(0) \
                and not imgui.is_mouse_released(0):
            self._reset_box_state()
        if self._box_selecting and self._box_start_screen is not None \
                and imgui.is_mouse_down(0):
            mouse_now = self._mouse_screen_pos()
            if (abs(mouse_now[0] - self._box_start_screen[0]) > 6.0
                    or abs(mouse_now[1] - self._box_start_screen[1]) > 6.0):
                self._box_drag_seen = True
        if imgui.is_mouse_clicked(0):
            mouse = self._mouse_screen_pos()
            rect = getattr(self, "_canvas_rect", None)
            inside_canvas = bool(
                rect is not None
                and rect[0] <= mouse[0] <= rect[2]
                and rect[1] <= mouse[1] <= rect[3]
            )
            if not inside_canvas:
                # 工具栏、面板标题、左侧 3D 视口或其它面板的点击绝不能
                # 成为框选起点；否则下一次画布点击会用旧起点拉出巨大矩形。
                self._reset_box_state()
                return
        if imgui.is_mouse_clicked(0) and self._hovered_node_id == 0:
            # 组框 hovered 不可靠，额外做矩形命中；点组框不启动框选。
            if not self._group_at_screen(canvas, ne):
                mouse = self._mouse_screen_pos()
                self._box_selecting = True
                self._box_select_released = False
                self._box_settle = 0
                self._box_drag_seen = False
                self._box_start_screen = (float(mouse[0]), float(mouse[1]))
        elif imgui.is_mouse_clicked(0):
            # 点击节点/组框时清掉上一轮框选残留。
            self._reset_box_state()
        if imgui.is_mouse_released(0) and self._box_selecting:
            self._box_selecting = False
            self._box_select_released = True

    def _handle_shift_click_selection(self, canvas: NodeCanvas, ne) -> None:
        """Shift + 左键点击：记录追加选择；实际提交等 ne.end() 之后。"""
        if not imgui.is_mouse_clicked(0) or not self._shift_down():
            return
        hid = int(self._hovered_node_id)
        if hid not in canvas.nodes:
            return
        selected = set(self._selection_snapshot)
        selected.update(self._selected_real_nodes(canvas, ne))
        selected.add(hid)
        self._shift_pending = {nid for nid in selected if nid in canvas.nodes}
        self._shift_settle = 0

    def _apply_shift_pending(self, ne) -> None:
        """在节点编辑器提交原生选择后，重新应用 Shift 追加集合。"""
        if not self._shift_pending:
            return
        # release 丢失时不要无限保留旧 Shift 集合。
        if not imgui.is_mouse_down(0) and not imgui.is_mouse_released(0) \
                and not self._shift_settle:
            self._shift_pending = set()
            return
        try:
            ne.clear_selection()
            for nid in sorted(self._shift_pending):
                ne.select_node(ne.NodeId(nid), True)
        except Exception as e:  # noqa: BLE001
            print(f"[Select] Shift+click apply failed: {e}")
            self._shift_pending = set()
            return
        # 原生选择在 release 后还会晚一帧提交；保持一帧 settle 再清空。
        if self._shift_settle > 0:
            self._shift_settle -= 1
            if self._shift_settle == 0:
                self._shift_pending = set()
        elif imgui.is_mouse_released(0):
            self._shift_settle = 1

    def _apply_box_selection(self, canvas: NodeCanvas, ne) -> None:
        """按屏幕矩形选择真实节点；完全不把组框纳入选择。

        原生 imgui-node-editor 的框选会优先命中组框（大矩形），导致“框选
        选不到节点”。这里用 canvas→screen 转换自己做命中，并用 release
        后一帧 settle 抵消原生选择的延迟提交。
        """
        if not (self._box_selecting or self._box_select_released or self._box_settle):
            return
        start = self._box_start_screen
        if start is None:
            return
        try:
            mouse = self._mouse_screen_pos()
            x0, x1 = sorted((start[0], mouse[0]))
            y0, y1 = sorted((start[1], mouse[1]))
        except Exception:  # noqa: BLE001
            return
        # 点击会带 1–3 px 抖动；低于 6 px 不当作框选，避免“点一下却选中
        # 旁边节点”的误触。即使矩形很大，只要本次按下期间没有真正拖动，
        # 也绝不应用（旧起点/焦点丢失后残留的矩形就是这么误选远处节点的）。
        if x1 - x0 < 6.0 and y1 - y0 < 6.0:
            if self._box_select_released:
                self._reset_box_state()
            return
        if not self._box_drag_seen:
            if self._box_select_released:
                self._reset_box_state()
            return

        # canvas_to_screen 必须在 ne.begin/end 内调用；end() 之后调用会按
        # 当前 ImGui 窗口（如 Node Groups 浮窗）的视口解析，导致框选命中
        # 到错误节点。这里只读绘制帧内缓存的真实屏幕矩形。
        hits: list[int] = []
        for nid in canvas.nodes:
            rect = self._node_screen_rects.get(int(nid))
            if rect is None:
                continue
            rtl_x, rtl_y, rbr_x, rbr_y = rect
            if rbr_x < x0 or rtl_x > x1 or rbr_y < y0 or rtl_y > y1:
                continue
            hits.append(int(nid))

        self._last_box_apply = {
            "start": [round(start[0], 1), round(start[1], 1)],
            "end": [round(x1, 1), round(y1, 1)],
            "hits": sorted(int(n) for n in hits),
        }
        try:
            ne.clear_selection()
            for nid in sorted(hits):
                ne.select_node(ne.NodeId(nid), True)
        except Exception as e:  # noqa: BLE001
            print(f"[Box] apply failed: {e}")

        if self._box_select_released:
            self._box_select_released = False
            self._box_settle = 1
            self._box_drag_seen = False
        elif self._box_settle > 0:
            self._box_settle -= 1
            if self._box_settle == 0:
                self._box_start_screen = None

    def _prune_group_selection(self, canvas: NodeCanvas, ne) -> None:
        """防御：任何组框 NodeId 混入选择时立即取消。"""
        if not (self._box_selecting or self._box_select_released or self._box_settle):
            return
        for eid in self._selected_node_ids(ne):
            if eid in canvas.nodes:
                continue
            try:
                ne.deselect_node(ne.NodeId(eid))
            except Exception:  # noqa: BLE001
                pass

    def _remember_selection(self, canvas: NodeCanvas, ne) -> None:
        """保存上一帧真实节点选择，供下一帧 Shift+click 做加法。"""
        self._selection_snapshot = set(self._selected_real_nodes(canvas, ne))
