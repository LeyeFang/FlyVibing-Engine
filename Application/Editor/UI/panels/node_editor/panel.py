"""
节点编辑器 — 画布 Panel。

负责:
  - 节点/连线/交互的渲染
  - Add 弹出菜单
  - Pin 拖拽创建连线
  - Delete 键删除
  - 位置同步
  - Import / Export
"""

from __future__ import annotations

import json
import os
import zlib
from pathlib import Path

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import ERROR_RED
from Application.Editor.I18n import t

from Application.Core.NodeGraph import (
    NodeCanvas,
    _TYPES,
    _gen_id,
)
from Application.Core.NodeGraph.node_packs import NodePackRegistry
from Application.Core.NodeGraph.graph_constraints import (
    device_cascade_deletes,
)
from Application.Core.NodeGraph.group_geometry import (
    GROUP_IO_TYPES,
    expand_group_to_rect,
    fit_group,
    group_at_point,
    init_boxes,
    scale_group_to_box,
    set_member,
    translate_group,
)
from Application.Core.NodeGraph.group_nodes import (
    all_io_node_ids,
    ensure_all_group_io_nodes,
    group_io_owner,
    io_pin_ids,
)
from Application.Core.NodeGraph.group_ops import (
    rename_group,
    set_group_description,
)
from .styling import (
    _col,
    _apply_ne_style,
    _HDR_COLOR,
    LINK_COLORS,
    _LINK_COLOR_FALLBACK,
    MENU_SECTIONS,
    TEXT_DISABLED,
    GROUP_BG,
    GROUP_BG_ACTIVE,
    GROUP_BORDER,
    GROUP_BORDER_ACTIVE,
    GROUP_TITLE,
    GROUP_DESC,
)
from .widgets import draw_node_widgets
from .labels import group_label, node_label
from .visible_pins import get_visible_pins
from .group_layout import (
    GroupLayoutEngine,
    descendant_group_ids,
    group_bounds,
    group_depth,
    group_member_ids,
    group_order,
)
from .selection import SelectionMixin
from .group_context import GroupContextMixin
from .groups_window import GroupsWindowMixin
from .io import IOMixin
from .find_window import FindWindowMixin
from .validate import ValidateMixin


# ═══════════════════════════════════════════════════════════════
# Add 菜单辅助 (鼠标悬停展开级联子菜单)
# ═══════════════════════════════════════════════════════════════

_SUB_HDR_COLOR = imgui.ImVec4(0.500, 0.500, 0.500, 0.60)


def _free_node_position(
    canvas: NodeCanvas,
    target: tuple[float, float],
    step: float = 36.0,
) -> tuple[float, float]:
    """从画布中心开始找一个不与现有节点完全重合的落点。

    画布中心是固定屏幕点，连续 Add 时若所有新节点都落在同一坐标，
    imgui-node-editor 会把它们完全叠在一起（看起来像 Add 只成功了一次）。
    这里做一个小步长右下滑移；不试图做完整碰撞检测（节点高度由控件动态
    决定），只保证每次 Add 都能看到新节点。
    """
    occupied = [(inst.pos[0], inst.pos[1]) for inst in canvas.nodes.values()]
    x, y = target
    for _ in range(32):
        if not any(abs(x - ox) < step * 0.5 and abs(y - oy) < step * 0.5
                   for ox, oy in occupied):
            return x, y
        x += step
        y += step
    return target


def _draw_add_menu_section(
    title: str,
    items: list,
    canvas: NodeCanvas,
    node_pos: imgui.ImVec2,
) -> None:
    """在 Add 弹出菜单中绘制一个顶级分类（悬停展开子菜单）。"""
    if imgui.begin_menu(group_label(title)):
        for item in items:
            _draw_menu_item(item[0], item[1], canvas, node_pos)
        imgui.end_menu()


def _draw_menu_item(
    label: str,
    target,
    canvas: NodeCanvas,
    node_pos: imgui.ImVec2,
) -> None:
    """绘制菜单项:
      target 为 list → 子分组标题 + 展平子项
      target 为 str  → 可点击菜单项 (创建节点)
    """
    if isinstance(target, list):
        imgui.spacing()
        imgui.text_colored(_SUB_HDR_COLOR, f"  {group_label(label)}")
        imgui.separator()
        for sub_label, sub_value in target:
            _draw_menu_item(sub_label, sub_value, canvas, node_pos)
    else:
        display_label = node_label(target, label)
        # Hidden stable id: two extensions may legitimately use the same label.
        changed, _selected = imgui.menu_item(
            f"{display_label}##add_{target}", "", False, True)
        if changed:
            n_before = len(canvas.nodes)
            drop = _free_node_position(
                canvas, (float(node_pos.x), float(node_pos.y)))
            nid = canvas.add_node(target, drop)
            if nid < 0:
                print(f"[AddNode] FAILED: type '{target}' not registered")
            else:
                inst = canvas.nodes.get(nid)
                print(f"[AddNode] nid={nid} type='{target}' "
                      f"pos=({inst.pos[0]:.1f},{inst.pos[1]:.1f}) "
                      f"total_nodes={n_before}→{len(canvas.nodes)}")
            imgui.close_current_popup()
            imgui.close_current_popup()


# ═══════════════════════════════════════════════════════════════
# NodeEditorPanel
# ═══════════════════════════════════════════════════════════════

class NodeEditorPanel(SelectionMixin, GroupContextMixin, GroupsWindowMixin,
                      IOMixin, FindWindowMixin, ValidateMixin, BasePanel):
    """节点编辑器画布 — Runtime 生命周期节点编辑"""

    name = "Node Editor"
    title_key = "panel.node_editor"
    flags = imgui.WindowFlags_.none

    _CONFIG_FILE: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "Config", "NodeEditor.json",
    )

    _canvas: NodeCanvas | None = None

    def __init__(self) -> None:
        super().__init__()
        self.visible = True
        self._editor_context: node_ed.EditorContext | None = None
        self._editor_initialized: bool = False
        self._canvas_initialized: bool = False
        self._add_popup_pos: imgui.ImVec2 = imgui.ImVec2(0, 0)
        # Add 菜单打开的屏幕中心 → 在 ne.begin 后解析成画布坐标（新节点落点）
        self._add_screen_center: imgui.ImVec2 = imgui.ImVec2(0, 0)
        self._add_node_pos: imgui.ImVec2 = imgui.ImVec2(80, 40)
        self._add_target_pending: bool = False
        # ── Import / Export 状态 ──
        self._import_path: str = ""
        self._export_path: str = ""
        self._import_error: str = ""
        self._export_error: str = ""
        self._import_validate_first: bool = False  # GUI 默认关（便于导入待修图）; agent ops 默认开
        self._last_io_dir: str = str(Path.home())  # 上次 I/O 目录
        # ── Validate 状态（引擎内校验服务 — 与 MCP 共用同一实例）──
        self._validate_task_id: int | None = None
        self._validate_opts: dict = {"frames": 360, "verbose": True, "seed": 0}
        self._validate_seen_report: int | None = None   # 已取回的 task_id（防重复）
        self._report: dict | None = None                # 最近一次报告（UI 缓存）
        self._report_open: bool = False
        self._report_note: str = ""
        self._fit_requested: bool = False              # 下一帧把视图 fit 到全部节点
        self._desc_open: set[int] = set()               # 已展开描述的节点 id
        # ── 节点查询窗口 ──
        self._find_open: bool = False
        self._find_query: str = ""
        self._find_selected: int | None = None
        self._find_focus: bool = False
        self._last_focused_node: int | None = None
        # ── 节点组编辑窗口 / 拖拽状态 ──
        self._groups_open: bool = False
        self._active_group: str = ""
        self._fit_group_pending: str = ""
        # ── 多选 / 右键菜单 / 框选 ──
        self._selection_snapshot: set[int] = set()
        self._shift_pending: set[int] = set()
        self._shift_settle: int = 0
        self._hovered_node_id: int = 0
        self._box_selecting: bool = False
        self._box_select_released: bool = False
        self._box_settle: int = 0
        self._box_drag_seen: bool = False
        self._box_start_screen: tuple[float, float] | None = None
        self._group_context_kind: str = ""       # node / group / background
        self._group_context_gid: str = ""
        self._group_context_selection: set[int] = set()
        self._group_action_error: str = ""
        # 节点编辑器只在 begin/end 内提供可靠的 canvas→screen 映射。
        # 框选/组框命中在 end() 之后执行，必须使用绘制帧内缓存的屏幕矩形。
        self._node_screen_rects: dict[int, tuple[float, float, float, float]] = {}
        # 节点实际尺寸（画布坐标）— 组框自适应/比例缩放使用。
        self._node_canvas_rects: dict[int, tuple[float, float, float, float]] = {}
        self._group_screen_rects: dict[str, tuple[float, float, float, float]] = {}
        # 组标题的屏幕矩形（最近一帧绘制结果；GUI 回归验证标题在组框内）。
        self._group_title_rects: dict[str, tuple[float, float, float, float]] = {}
        self._group_description_rects: dict[str, tuple[float, float, float, float]] = {}
        self._group_desc_button_rects: dict[str, tuple[float, float, float, float]] = {}
        self._group_io_rects: dict[str, dict[str, tuple[float, float, float, float]]] = {}
        self._group_title_texts: dict[str, str] = {}
        self._group_description_texts: dict[str, str] = {}
        # 组描述默认展开（首次打开即可见），按钮可折叠；与普通节点一致。
        self._group_desc_closed: set[str] = set()
        # 组标题/描述双击内联编辑（不依赖 Groups 窗口）。
        self._group_inline_edit_gid: str = ""
        self._group_inline_field: str = ""       # name / description
        self._group_inline_name: str = ""
        self._group_inline_desc: str = ""
        self._group_inline_error: str = ""
        self._group_inline_focus: bool = False
        # Group(size) 的 Dummy 矩形 = 真正的组背景/边框区域。
        self._group_frame_rects: dict[str, tuple[float, float, float, float]] = {}
        self._last_canvas_width: float = 0.0
        self._last_zoom: float = 0.0
        self._last_box_apply: dict = {}
        self._canvas_rect: tuple[float, float, float, float] | None = None
        # ★ 节点编辑器内 imgui.get_mouse_pos() 返回画布坐标；自定义
        #   命中/框选拿它和屏幕矩形（_node_screen_rects 等）比较会错位。
        #   每帧绘制时缓存一次屏幕坐标，所有混合比较统一用它。
        self._mouse_screen: tuple[float, float] | None = None
        self._mouse_canvas: tuple[float, float] | None = None
        # 上一帧 node-editor 命中的引脚（诊断/真实鼠标回归用）。
        self._hovered_pin_id: int = 0
        # 仅 GUI 测试使用：跳过鼠标状态前置条件（真实交互仍走下面的守卫）。
        self._debug_force_group_drag: bool = False
        # ── 组框几何 / 成员进入离开 ──
        self._drag_node_id: int | None = None
        self._drag_node_start_pos: tuple[float, float] | None = None
        # 上一帧提交给 node-editor 的组框位置/尺寸；用于区分用户拖动/缩放
        # 与代码里的 box 自动调整（自动调整不能反过来触发缩放）。
        self._group_last_pos: dict[str, tuple[float, float]] = {}
        self._group_last_size: dict[str, tuple[float, float]] = {}
        self._group_resize_gid: str = ""
        self._group_resize_start_mouse: tuple[float, float] | None = None
        self._group_resize_start_box: tuple[float, float, float, float] | None = None
        self._group_resize_cooldown: dict[str, int] = {}
        self._group_drag_gid: str = ""
        self._group_drag_last_mouse: tuple[float, float] | None = None
        self._group_drag_cooldown: dict[str, int] = {}
        # ── 组内部 GroupStart/GroupEnd 诊断快照 ──
        self._group_io: dict[str, dict] = {}
        # ── Groups 窗口的命名/描述编辑缓冲 ──
        self._group_alias_gid: str = ""
        self._group_alias_buf: str = ""
        self._group_alias_error: str = ""
        self._group_desc_gid: str = ""
        self._group_desc_buf: str = ""
        self._group_fit_pending: bool = False

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(self) -> None:
        if not self._editor_initialized:
            try:
                os.makedirs(os.path.dirname(self._CONFIG_FILE), exist_ok=True)
                self._reset_degenerate_view()
                config = node_ed.Config()
                config.settings_file = self._CONFIG_FILE
                # 面板横向拉伸/停靠变化时只平移视图，不按新宽高重新缩放；
                # 否则节点卡片会随窗口变宽而“向右长大”（FitVerticalView
                # 会按新的宽高比调整 zoom）。
                config.canvas_size_mode = node_ed.CanvasSizeMode.center_only
                self._editor_context = node_ed.create_editor(config)
                self._editor_initialized = True
            except Exception:
                self._editor_context = None

    def _reset_degenerate_view(self) -> None:
        """丢弃持久化中过小的缩放视图。

        imgui-node-editor 会把上次的 view.zoom/scroll 写进 settings_file。
        如果用户曾在 157 节点的大图上 Fit All 后关闭，下一次启动仍会以
        ~0.28 的缩放打开；节点文字被压成几像素，看起来像“乱码”。
        只在启动时处理，且只删除 view，不动节点位置/分组。
        """
        try:
            if not os.path.isfile(self._CONFIG_FILE):
                return
            with open(self._CONFIG_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            view = data.get("view")
            if not isinstance(view, dict):
                return
            try:
                zoom = float(view.get("zoom", 1.0))
            except (TypeError, ValueError):
                zoom = 1.0
            if zoom >= 0.55:
                return
            data.pop("view", None)
            with open(self._CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            print(f"[NodeEditor] reset tiny persisted view (zoom={zoom:.3f})")
        except (OSError, ValueError, TypeError):
            # 配置损坏不应阻止编辑器启动；node editor 会重新生成。
            pass

    def on_detach(self) -> None:
        if self._editor_context is not None:
            try:
                node_ed.destroy_editor(self._editor_context)
            except Exception:
                pass
            self._editor_context = None
            self._editor_initialized = False

    # ============================================================
    # 绘制入口
    # ============================================================

    def draw(self) -> None:
        if self._editor_context is None:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                t("node_editor.unavailable")
            )
            imgui.text_disabled(
                t("node_editor.unavailable_hint")
            )
            return

        if not self._canvas_initialized:
            self._canvas = NodeCanvas()
            self._canvas.create_default_nodes()
            self._canvas_initialized = True

        # ── 确保默认 Scene 存在（饥渴创建，不等 EntitySpawn 下拉触发） ──
        self._ensure_default_scene()

        canvas = self._canvas
        avail = imgui.get_content_region_avail()
        if avail.x <= 0 or avail.y <= 0:
            return

        ne = node_ed
        ne.set_current_editor(self._editor_context)

        # ── 当前场景信息 ──
        self._draw_scene_info()

        # ── 工具栏: Add / Find / Groups / Import / Export ──
        if imgui.small_button(t("node_editor.add_node")):
            rect_min = imgui.get_item_rect_min()
            rect_max = imgui.get_item_rect_max()
            self._add_popup_pos = imgui.ImVec2(rect_min.x, rect_max.y)
            # 新节点落在画布可见区域中心（不是整个面板中心：工具栏占高度，
            # 面板中心会偏上/偏下）。屏幕中心在 ne.begin 之前计算，坐标转换
            # 必须在 ne.begin 之后进行，见下方 _add_target_pending。
            self._add_target_pending = True
            self._add_node_pos = imgui.ImVec2(80, 40)  # 解析失败时的回退
            imgui.open_popup("###create_node")

        imgui.same_line()
        if imgui.small_button(t("node_editor.find_node")):
            self._find_open = True
            self._find_focus = True

        imgui.same_line()
        if imgui.small_button(t("node_editor.groups")):
            self._groups_open = True

        imgui.same_line()
        if imgui.small_button(t("node_editor.import")):
            self._import_error = ""
            imgui.open_popup("###import_graph")

        imgui.same_line()
        if imgui.small_button(t("node_editor.export")):
            self._export_error = ""
            imgui.open_popup("###export_graph")

        imgui.same_line()
        self._draw_validate_button()

        imgui.same_line()
        if imgui.small_button(t("node_editor.rearrange")):
            self._auto_layout(canvas)

        imgui.same_line()
        if imgui.small_button(t("node_editor.fit")):
            self._fit_requested = True
        if imgui.is_item_hovered():
            imgui.set_tooltip(t("node_editor.fit_tip"))

        # ── 节点查询 / 节点组窗口（非 modal; 与画布并行）──
        self._draw_find_window(canvas)
        self._draw_groups_window(canvas)

        # ── Import 弹出窗口 ──
        self._draw_import_popup(canvas)

        # ── Export 弹出窗口 ──
        self._draw_export_popup(canvas)

        # ── Validate 弹出菜单 / 自动取回报告 / 报告窗口 ──
        self._draw_validate_popup(canvas)
        self._draw_report_window()

        # ── 画布背景色 & 网格 ──
        s = ne.get_style()
        s.set_color_(ne.StyleColor.bg,   _col((0.090, 0.090, 0.090), 1.00))
        s.set_color_(ne.StyleColor.grid, _col((0.180, 0.180, 0.180), 0.50))

        # ★ 工具栏已经占用了窗口顶部；画布必须使用“剩余内容区”而不是
        #   draw() 开头的完整 avail。否则独立标签页/高窗口下画布高度多出
        #   一条工具栏高度，底部溢出，工具栏和画布点击区域会错位。
        canvas_avail = imgui.get_content_region_avail()
        if canvas_avail.x <= 0 or canvas_avail.y <= 0:
            # 面板过小/刚被折叠：丢弃本次 Add 目标，避免下一帧用旧屏幕坐标
            # 解析到完全不同的画布位置。
            self._add_target_pending = False
            return
        self._last_canvas_width = float(canvas_avail.x)
        canvas_origin = imgui.get_cursor_screen_pos()
        self._canvas_rect = (
            float(canvas_origin.x), float(canvas_origin.y),
            float(canvas_origin.x + canvas_avail.x),
            float(canvas_origin.y + canvas_avail.y),
        )
        if self._add_target_pending:
            # 工具栏/弹窗都已经画完，此时光标位置就是画布左上角。
            self._add_screen_center = imgui.ImVec2(
                canvas_origin.x + canvas_avail.x * 0.5,
                canvas_origin.y + canvas_avail.y * 0.5,
            )
        ne.begin("NodeEditor", canvas_avail)
        try:
            self._draw_canvas_contents(canvas, ne, canvas_avail)
        finally:
            # begin/end 必须严格配对：即使节点、控件或用户交互抛异常，
            # 也不能把 imgui-node-editor 的原生栈留成未闭合状态。
            ne.end()

        # 原生节点编辑器在 End() 里提交点击/框选结果；Shift 追加选择与
        # “框选不选组”必须在 End() 之后修正，否则会被原生选择覆盖。
        self._apply_shift_pending(ne)
        self._apply_box_selection(canvas, ne)
        self._prune_group_selection(canvas, ne)
        self._remember_selection(canvas, ne)

        try:
            self._last_zoom = float(ne.get_current_zoom())
        except Exception:  # noqa: BLE001
            pass

        self._draw_add_popup(canvas)
        self._sync_positions(canvas, ne)
        self._draw_group_context_menu(canvas, ne)

    def _draw_canvas_contents(self, canvas: NodeCanvas, ne, canvas_avail) -> None:
        """ne.begin 与 ne.end 之间的画布内容（异常由外层 finally 兜底）。"""
        # ★ 必须在 ne.begin 之后做屏幕→画布转换；否则节点编辑器还没有
        #   当前视口/滚动信息，坐标会按旧状态解析，新节点可能落到视口外。
        #   转换只做一次（点击 Add 的当帧），之后菜单悬停/点击期间视口即使
        #   被拖动，也保持用户打开菜单时看到的落点。
        if self._add_target_pending:
            try:
                self._add_node_pos = ne.screen_to_canvas(self._add_screen_center)
            except Exception:
                self._add_node_pos = imgui.ImVec2(80, 40)
            self._add_target_pending = False

        # ★ 节点编辑器内 ImGui 鼠标位置是画布坐标；先转成屏幕坐标缓存，
        #   后面与 _node_screen_rects / _group_screen_rects / _canvas_rect
        #   的比较全部使用同一坐标系。需要 begin/end 内才可靠。
        try:
            mpos = imgui.get_mouse_pos()
            self._mouse_canvas = (float(mpos.x), float(mpos.y))
            smpos = ne.canvas_to_screen(mpos)
            self._mouse_screen = (float(smpos.x), float(smpos.y))
        except Exception:  # noqa: BLE001
            try:
                mpos = imgui.get_mouse_pos()
                self._mouse_canvas = (float(mpos.x), float(mpos.y))
                self._mouse_screen = (float(mpos.x), float(mpos.y))
            except Exception:  # noqa: BLE001
                self._mouse_canvas = None
                self._mouse_screen = None

        # 右键/Shift 点击都依赖本帧的 hovered node；在节点绘制前取样。
        try:
            self._hovered_node_id = int(ne.get_hovered_node().id())
        except Exception:  # noqa: BLE001 — API 可选
            self._hovered_node_id = 0
        try:
            self._hovered_pin_id = int(ne.get_hovered_pin().id())
        except Exception:  # noqa: BLE001 — API 可选
            self._hovered_pin_id = 0
        self._update_box_selection_state(canvas, ne)
        self._handle_shift_click_selection(canvas, ne)
        self._track_node_drag(canvas, ne)

        if self._fit_group_pending:
            gid = self._fit_group_pending
            self._fit_group_pending = ""
            ids = group_member_ids(canvas, gid)
            if ids:
                try:
                    ne.clear_selection()
                    for nid in ids:
                        if nid in canvas.nodes:
                            ne.select_node(ne.NodeId(nid), True)
                    ne.navigate_to_selection(True)
                    ne.clear_selection()
                except Exception as e:  # noqa: BLE001
                    print(f"[GroupFit] {gid} failed: {e}")

        self._draw_nodes(canvas, ne)
        # Fit 必须在节点/组框绘制之后：新导入组的原生 Group(size) 要到
        # 本帧 _draw_group_hints 才写入，提前 NavigateToContent 会用旧尺寸
        # 把视图缩到极小（组框还在，但卡片和端口几乎不可见）。
        if self._fit_requested:
            ne.navigate_to_content()
            self._fit_requested = False
        self._draw_links(canvas, ne)
        self._handle_link_creation(canvas, ne)
        self._handle_deletion(canvas, ne)

        # ── 空画布提示 ──
        ne.suspend()
        try:
            if not canvas.nodes:
                canvas_pos = imgui.get_cursor_screen_pos()
                imgui.set_cursor_screen_pos((
                    canvas_pos.x + canvas_avail.x / 2 - 80,
                    canvas_pos.y + canvas_avail.y / 2 - 10,
                ))
                imgui.text_colored(
                    imgui.ImVec4(0.400, 0.400, 0.400, 1.00),
                    t("node_editor.empty_hint"),
                )
        finally:
            ne.resume()

    # ============================================================
    # Scene 管理
    # ============================================================

    @staticmethod
    def _ensure_default_scene() -> None:
        """确保 EditorHost 的活跃 Scene 始终与 ECS 世界同步。

        使用 st.entities 字典（与 ScenePanel 的 GetRootEntities 同源），
        避免 esper.get_component() 的世界切换时序问题。
        """
        from Application.Editor.EditorHost import EditorHost
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer
        import copy

        try:
            st = SceneManager._state_for("EditorHost")
        except Exception as e:
            print(f"[NodeEditor] _ensure_default_scene: SceneManager unavailable ({e})")
            return

        scene = EditorHost.get_active_scene()
        if scene is None:
            # ★ 走 create_scene 确保加入 _scenes 字典
            scene = EditorHost.create_scene("Default")
            if scene is None:
                return

        _sys_ids = {
            st.get_main_camera_id(),
            st.get_main_camera_2d_id(),
            st.get_main_camera_overlay_id(),
        }
        scene.entities.clear()

        # ★ 改用 st.entities 字典迭代（与 ScenePanel 同源），不再依赖 esper.get_component
        for eid_str in list(st.entities.keys()):
            eid = int(eid_str)
            if eid in _sys_ids:
                continue
            # 只同步有 Transform 的实体
            try:
                xform = st.GetComponent(eid, Transform)
            except Exception:
                continue
            name = st.GetEntityName(eid) or f"Entity_{eid}"
            comps = {"Transform": copy.deepcopy(xform)}
            try:
                cam = st.GetComponent(eid, Camera)
                comps["Camera"] = copy.deepcopy(cam)
            except Exception:
                pass
            try:
                mr = st.GetComponent(eid, MeshRenderer)
                comps["MeshRenderer"] = copy.deepcopy(mr)
            except Exception:
                pass
            scene.add_entity(name=name, **comps)

    def _draw_scene_info(self) -> None:
        """绘制 Scene 选择器 combo — 显示当前场景名 + GameType。"""
        from Application.Editor.EditorHost import EditorHost
        from Application.Core.Scene.SceneManager import SceneManager

        scene = EditorHost.get_active_scene()
        if scene is None:
            imgui.text_colored(
                imgui.ImVec4(0.55, 0.55, 0.55, 1.00),
                t("node_editor.scene_none"),
            )
            return

        scene_names = [scene.name]  # 未来扩展: 列出所有已加载的 Scene
        current_name = scene.name
        try:
            idx = scene_names.index(current_name)
        except ValueError:
            idx = 0

        gt = scene.game_type.value

        # ── GameType 颜色 ──
        if gt == "2d":
            gt_color = imgui.ImVec4(0.35, 1.0, 0.55, 0.85)
        elif gt == "overlay":
            gt_color = imgui.ImVec4(0.55, 0.65, 1.0, 0.85)
        else:
            gt_color = imgui.ImVec4(1.0, 1.0, 1.0, 0.70)

        # ── 标签 ──
        imgui.text_colored(
            imgui.ImVec4(0.55, 0.55, 0.55, 1.00),
            t("scene.header"),
        )
        imgui.same_line()

        # ── Combo: 场景名 + GameType 后缀 ──
        display_labels = [f"{n}  ({EditorHost.scene.GetGameType().value.upper()})" for n in scene_names]
        imgui.push_item_width(180)
        changed, new_idx = imgui.combo(
            f"##scene_selector_{id(self)}", idx, display_labels,
        )
        imgui.pop_item_width()

        if changed:
            # 未来: 切换到 scene_names[new_idx]
            pass

    # ============================================================
    # 子步骤: 节点渲染
    # ============================================================

    # 组框使用独立的 NodeId 空间（与真实节点 id 不冲突）
    _GROUP_NODE_BASE = 60_000_000

    def _group_editor_id(self, gid: str) -> int:
        """Stable NodeId for a group frame (separate from real node ids)."""
        raw = str(gid)
        if raw.startswith("g") and raw[1:].isdigit():
            return self._GROUP_NODE_BASE + int(raw[1:])
        return self._GROUP_NODE_BASE + (zlib.crc32(raw.encode("utf-8")) % 10_000_000)

    def _group_for_editor_id(self, canvas: NodeCanvas, editor_id: int) -> str:
        """组框 NodeId → gid；真实节点/背景返回空串。"""
        for gid in (getattr(canvas, "node_groups", None) or {}):
            if self._group_editor_id(gid) == int(editor_id):
                return str(gid)
        return ""

    def _move_group(self, canvas: NodeCanvas, gid: str, dx: float, dy: float) -> int:
        """平移组框 + 整棵成员子树（box 与节点一起移动）。"""
        return translate_group(canvas, gid, dx, dy)

    # ── 组框自适应 / 成员进入离开 ──────────────────────────

    def _node_size_for_group(self, nid: int, inst) -> tuple[float, float]:
        rect = self._node_canvas_rects.get(int(nid))
        if rect is not None:
            return (max(1.0, float(rect[2])), max(1.0, float(rect[3])))
        from .group_layout import node_size
        return node_size(inst)

    def _node_rect(self, canvas: NodeCanvas, nid: int):
        inst = canvas.nodes.get(int(nid))
        if inst is None:
            return None
        w, h = self._node_size_for_group(nid, inst)
        return (float(inst.pos[0]), float(inst.pos[1]), w, h)

    def _prepare_group_boxes(self, canvas: NodeCanvas) -> None:
        groups = getattr(canvas, "node_groups", None) or {}
        if not groups:
            return
        # 每个组拥有自己的 GroupStart/GroupEnd 普通节点；首次打开旧场景
        # 或组刚创建时补齐。它们不隐藏/不改写任何成员 Pin。
        ensure_all_group_io_nodes(canvas, self._node_size_for_group)
        # GroupStart/GroupEnd 不按普通卡片绘制，也不会进入 _node_canvas_rects；
        # 判断“真实尺寸已就绪”时必须排除它们，否则永远等不到 fit。
        drawable = [
            nid for nid, inst in canvas.nodes.items()
            if inst.node_type not in GROUP_IO_TYPES
        ]
        ready = all(nid in self._node_canvas_rects for nid in drawable)
        # 节点真实尺寸在首次绘制后才可用；Rearrange 发生在首帧前时
        # 先延迟 fit 一帧，避免用估计尺寸把组框撑大。
        if self._group_fit_pending and ready:
            for gid in sorted(groups, key=lambda g: group_depth(canvas, g),
                              reverse=True):
                fit_group(canvas, gid, self._node_size_for_group, shrink=True)
            self._group_fit_pending = False
        # 子组先算，父组用子组 box 作为内容矩形。
        # 节点真实尺寸尚未采样完时传 None：初始化会带 box_auto 标记，
        # 下一帧拿到真实尺寸后自动校正一次。
        size_of = self._node_size_for_group if ready else None
        init_boxes(canvas, size_of)

    def _refresh_group_io(self, canvas: NodeCanvas) -> None:
        """缓存组内部 GroupStart/GroupEnd 的真实 PinId（只读诊断）。"""
        groups = getattr(canvas, "node_groups", None) or {}
        snapshot: dict[str, dict] = {}
        for gid in groups:
            info = io_pin_ids(canvas, str(gid))
            if info.get("start_node") is not None or info.get("end_node") is not None:
                snapshot[str(gid)] = info
        self._group_io = snapshot

    def _apply_node_drop(self, canvas: NodeCanvas, nid: int,
                         point: tuple[float, float]) -> None:
        """节点拖拽松开：根据鼠标点更新成员关系并自适应组框。"""
        groups = getattr(canvas, "node_groups", None) or {}
        if not groups or nid not in canvas.nodes:
            return
        owner = group_io_owner(canvas, nid)
        if owner:
            # GroupStart/GroupEnd 与组同生命周期；拖出时夹回组框，不改变归属。
            box = group_bounds(canvas, owner)
            rect = self._node_rect(canvas, nid)
            if box is not None and rect is not None:
                max_x = box[0] + box[2] - rect[2] - 12.0
                max_y = box[1] + box[3] - rect[3] - 12.0
                inst = canvas.nodes[nid]
                inst.pos = (
                    min(max(float(inst.pos[0]), box[0] + 12.0),
                        max(box[0] + 12.0, max_x)),
                    min(max(float(inst.pos[1]), box[1] + 12.0),
                        max(box[1] + 12.0, max_y)),
                )
            self._active_group = owner
            return
        from Application.Core.NodeGraph.group_geometry import direct_members

        old_gids = {gid for gid in groups if nid in direct_members(canvas, gid)}
        target = group_at_point(canvas, point, self._node_size_for_group)
        set_member(canvas, nid, target)
        rect = self._node_rect(canvas, nid)

        # 旧组：成员离开后收紧；父组递归收紧。
        for gid in sorted(old_gids, key=lambda g: group_depth(canvas, g),
                          reverse=True):
            if gid in groups:
                fit_group(canvas, gid, self._node_size_for_group, shrink=True)

        # 目标组：只扩不缩，确保拖入节点被覆盖；父组随之覆盖子组。
        if target and target in groups and rect is not None:
            expand_group_to_rect(canvas, target, rect,
                                 self._node_size_for_group)
        self._active_group = target or ""
        if target is None or target not in old_gids:
            print(f"[GroupMembership] node {nid} → {target or '<outside>'}")

    def _track_node_drag(self, canvas: NodeCanvas, ne) -> None:
        """记录真实节点拖拽，并在松开时触发成员进入/离开。"""
        if imgui.is_mouse_clicked(0):
            hid = int(self._hovered_node_id)
            if hid in canvas.nodes:
                inst = canvas.nodes[hid]
                self._drag_node_id = hid
                self._drag_node_start_pos = (float(inst.pos[0]),
                                             float(inst.pos[1]))
            else:
                self._drag_node_id = None
                self._drag_node_start_pos = None
        if not imgui.is_mouse_released(0):
            return
        nid = self._drag_node_id
        start = self._drag_node_start_pos
        self._drag_node_id = None
        self._drag_node_start_pos = None
        if nid is None or start is None or nid not in canvas.nodes:
            return
        inst = canvas.nodes[nid]
        moved = (abs(float(inst.pos[0]) - start[0]) > 0.5
                 or abs(float(inst.pos[1]) - start[1]) > 0.5)
        if moved and self._mouse_canvas is not None:
            self._apply_node_drop(canvas, nid, self._mouse_canvas)

    def _group_title_text(self, text: str, max_w: float) -> str:
        if max_w <= 8.0:
            return ""
        if imgui.calc_text_size(text).x <= max_w:
            return text
        suffix = "..."
        for cut in range(len(text) - 1, 0, -1):
            candidate = text[:cut] + suffix
            if imgui.calc_text_size(candidate).x <= max_w:
                return candidate
        return suffix

    @staticmethod
    def _point_in_rect(rect, point) -> bool:
        return bool(
            rect is not None and point is not None
            and float(rect[0]) <= float(point[0]) <= float(rect[2])
            and float(rect[1]) <= float(point[1]) <= float(rect[3])
        )

    def _start_group_inline_edit(self, gid: str, field: str, grp: dict) -> None:
        self._group_inline_edit_gid = str(gid)
        self._group_inline_field = str(field)
        self._group_inline_name = str(grp.get("alias") or gid)
        self._group_inline_desc = str(grp.get("description") or "")
        self._group_inline_error = ""
        self._group_inline_focus = True
        # 双击时第一下可能已启动组拖动；编辑期间禁止继续平移。
        self._group_drag_gid = ""
        self._group_drag_last_mouse = None
        self._group_resize_gid = ""
        self._group_resize_start_mouse = None
        self._group_resize_start_box = None

    def _clear_group_inline_edit(self) -> None:
        self._group_inline_edit_gid = ""
        self._group_inline_field = ""
        self._group_inline_name = ""
        self._group_inline_desc = ""
        self._group_inline_error = ""
        self._group_inline_focus = False

    def _draw_group_edge_io(self, canvas: NodeCanvas, gid: str,
                            bounds, ne) -> None:
        """把 GroupStart/GroupEnd 绘制成组框边缘的接口（真实 Pin）。

        节点本身仍在 canvas.nodes 中（参与连线/求值/序列化），但以紧凑
        pill 形式贴在组框左上/右下边缘；不隐藏成员 Pin，也不把接口绑定
        到 first/last 成员。
        """
        info = self._group_io.get(gid) or {}
        nodes = canvas.nodes
        x, y, w, h = (float(v) for v in bounds)
        specs = (
            ("start_node", "out_pin", ne.PinKind.output,
             x + 8.0, y + 58.0),
            ("end_node", "in_pin", ne.PinKind.input,
             x + max(8.0, w - 112.0), y + max(58.0, h - 42.0)),
        )
        for key, pin_key, kind, px, py in specs:
            nid = info.get(key)
            pin_id = info.get(pin_key)
            inst = nodes.get(int(nid)) if nid is not None else None
            if inst is None or pin_id is None:
                continue
            inst.pos = (float(px), float(py))
            ne.set_node_position(ne.NodeId(int(nid)), imgui.ImVec2(px, py))
            try:
                ne.set_node_z_position(ne.NodeId(int(nid)), 1.0)
            except Exception:  # noqa: BLE001 — API optional
                pass
            hovered = int(getattr(self, "_hovered_pin_id", 0) or 0) == int(pin_id)
            node_border = ((0.60, 0.90, 0.64, 1.00) if not hovered
                           else (0.98, 0.82, 0.36, 1.00))
            pin_fill = ((0.48, 0.76, 0.52, 0.22) if not hovered
                        else (1.00, 0.84, 0.34, 0.38))
            pin_border = ((0.60, 0.90, 0.64, 0.90) if not hovered
                          else (1.00, 0.84, 0.34, 1.00))
            ne.push_style_color(ne.StyleColor.node_bg,
                                imgui.ImVec4(0.10, 0.11, 0.10, 0.92))
            ne.push_style_color(ne.StyleColor.node_border,
                                imgui.ImVec4(*node_border))
            ne.push_style_color(ne.StyleColor.hov_node_border,
                                imgui.ImVec4(0.60, 0.90, 0.64, 1.00))
            ne.push_style_color(ne.StyleColor.sel_node_border,
                                imgui.ImVec4(0.95, 0.78, 0.32, 1.00))
            ne.push_style_color(ne.StyleColor.pin_rect,
                                imgui.ImVec4(*pin_fill))
            ne.push_style_color(ne.StyleColor.pin_rect_border,
                                imgui.ImVec4(*pin_border))
            ne.push_style_var(ne.StyleVar.node_padding,
                              imgui.ImVec4(5.0, 3.0, 5.0, 3.0))
            rect = None
            try:
                ne.begin_node(ne.NodeId(int(nid)))
                ne.begin_pin(ne.PinId(int(pin_id)), kind)
                try:
                    # exec 引脚本身没有圆形图标；把圆点画进 pin 内容里，
                    # 既明确提示“这里可以拖线”，也自然成为命中区域。
                    # pivot 对齐到 pill 外缘，连线端点不会跑到 pill 底部中心。
                    try:
                        ne.pin_pivot_alignment(
                            imgui.ImVec2(1.0 if key == "start_node" else 0.0,
                                         0.5))
                    except Exception:  # noqa: BLE001
                        pass
                    dot_col = (imgui.ImVec4(1.00, 0.84, 0.34, 1.00)
                               if hovered else
                               imgui.ImVec4(0.48, 0.76, 0.52, 1.00))
                    if key == "start_node":
                        imgui.text(t("node_editor.group_entry"))
                        imgui.same_line(0.0, 5.0)
                        imgui.text_colored(dot_col, "●")
                    else:
                        imgui.text_colored(dot_col, "●")
                        imgui.same_line(0.0, 5.0)
                        imgui.text(t("node_editor.group_exit"))
                finally:
                    ne.end_pin()
                ne.end_node()
                try:
                    imin = imgui.get_item_rect_min()
                    imax = imgui.get_item_rect_max()
                    stl = ne.canvas_to_screen(imin)
                    sbr = ne.canvas_to_screen(imax)
                    rect = (float(stl.x), float(stl.y),
                            float(sbr.x), float(sbr.y))
                    self._group_io_rects.setdefault(gid, {})[key] = rect
                except Exception:  # noqa: BLE001
                    pass
            finally:
                ne.pop_style_var(1)
                ne.pop_style_color(6)

    def _draw_group_hints(self, canvas: NodeCanvas, ne) -> None:
        """绘制可拖拽 / 可缩放的节点组框。

        - 位置/尺寸来自持久化的 ``node_groups[gid]["box"]``；
        - 用户拖标题/边框 = 平移组框 + 整棵成员子树；
        - 用户拖边缘 = 按比例平移成员，受 ``min_box`` 限制；
        - 标题与描述画在组框内部；exec 接口由组内 GroupStart/GroupEnd 节点承载。
        """
        groups = getattr(canvas, "node_groups", None) or {}
        prev_group_screen = self._group_screen_rects
        prev_title_rects = self._group_title_rects
        prev_desc_rects = self._group_description_rects
        prev_desc_buttons = self._group_desc_button_rects
        self._group_screen_rects = {}
        self._group_title_rects = {}
        self._group_description_rects = {}
        self._group_desc_button_rects = {}
        self._group_io_rects = {}
        self._group_title_texts.clear()
        self._group_description_texts.clear()
        self._group_frame_rects.clear()
        self._group_desc_closed.intersection_update(groups)
        prev_pos = self._group_last_pos
        prev_size = self._group_last_size
        next_pos: dict[str, tuple[float, float]] = {}
        next_size: dict[str, tuple[float, float]] = {}
        if not groups:
            self._group_last_pos = {}
            self._group_last_size = {}
            self._clear_group_inline_edit()
            return
        if (self._group_inline_edit_gid
                and self._group_inline_edit_gid not in groups):
            self._clear_group_inline_edit()
        suppressed: set[str] = set()
        for gid in group_order(canvas):
            skip_drag = gid in suppressed
            bounds = group_bounds(canvas, gid)
            if bounds is None:
                continue
            grp = groups.get(gid) or {}
            editor_id = self._group_editor_id(gid)
            selected = False
            try:
                selected = bool(ne.is_node_selected(ne.NodeId(editor_id)))
            except Exception:  # noqa: BLE001 — node not created yet
                selected = False

            # 上一帧 node-editor 中的位置/尺寸，用于区分用户拖动/缩放与
            # 代码对 box 的自动调整（自动调整不能反过来触发缩放）。
            cur_pos = cur_size = None
            try:
                cur_pos = ne.get_node_position(ne.NodeId(editor_id))
                cur_size = ne.get_node_size(ne.NodeId(editor_id))
            except Exception:  # noqa: BLE001
                pass
            valid_cur = bool(
                cur_pos is not None and cur_size is not None
                and abs(float(cur_pos.x)) < 1e9 and abs(float(cur_pos.y)) < 1e9
                and float(cur_size.x) > 0.0 and float(cur_size.y) > 0.0)
            last_pos = prev_pos.get(gid)
            last_size = prev_size.get(gid)
            size_changed = bool(
                valid_cur and last_size is not None
                and (abs(float(cur_size.x) - last_size[0]) > 0.5
                     or abs(float(cur_size.y) - last_size[1]) > 0.5))
            pos_changed = bool(
                valid_cur and last_pos is not None
                and (abs(float(cur_pos.x) - last_pos[0]) > 0.5
                     or abs(float(cur_pos.y) - last_pos[1]) > 0.5))

            mouse = self._mouse_screen
            gscreen = prev_group_screen.get(gid)
            pointer_on_group = bool(
                mouse is not None and gscreen is not None
                and self._group_hit_point(gscreen, mouse))
            handle_hit = bool(
                mouse is not None and gscreen is not None
                and gscreen[2] - 18.0 <= mouse[0] <= gscreen[2] + 2.0
                and gscreen[3] - 18.0 <= mouse[1] <= gscreen[3] + 2.0)
            # 组标题行的 Description/Hide 按钮不能触发整组拖动。
            desc_button_hit = bool(
                mouse is not None
                and self._point_in_rect(prev_desc_buttons.get(gid), mouse))
            force_drag = bool(getattr(self, "_debug_force_group_drag", False))
            interacting = (force_drag or (
                pointer_on_group
                and (imgui.is_mouse_down(0) or imgui.is_mouse_released(0))))

            # 自定义右下角缩放手柄（优先于原生 group size）。
            if (imgui.is_mouse_clicked(0) and handle_hit
                    and not self._group_resize_gid):
                self._group_resize_gid = gid
                self._group_resize_start_mouse = self._mouse_canvas
                self._group_resize_start_box = (
                    float(bounds[0]), float(bounds[1]),
                    float(bounds[2]), float(bounds[3]))
                self._reset_box_state()
                self._active_group = gid
                try:
                    ne.select_node(ne.NodeId(editor_id))
                except Exception:  # noqa: BLE001
                    pass
            custom_resize = (self._group_resize_gid == gid
                             and self._group_resize_start_box is not None
                             and self._group_resize_start_mouse is not None
                             and self._mouse_canvas is not None)
            if (self._group_resize_gid == gid and custom_resize
                    and not imgui.is_mouse_down(0)
                    and not imgui.is_mouse_released(0)):
                # 焦点丢失/在窗口外松开：清掉挂起的手柄拖拽。
                self._group_resize_gid = ""
                self._group_resize_start_mouse = None
                self._group_resize_start_box = None
                self._group_resize_cooldown[gid] = 3
                custom_resize = False
            if custom_resize:
                sx, sy, sw, sh = self._group_resize_start_box
                dmx = self._mouse_canvas[0] - self._group_resize_start_mouse[0]
                dmy = self._mouse_canvas[1] - self._group_resize_start_mouse[1]
                applied = scale_group_to_box(
                    canvas, gid, (sx, sy, sw + dmx, sh + dmy),
                    self._node_size_for_group)
                if applied is not None:
                    bounds = applied
                    suppressed.update(descendant_group_ids(canvas, gid))
                if imgui.is_mouse_released(0):
                    self._group_resize_gid = ""
                    self._group_resize_start_mouse = None
                    self._group_resize_start_box = None
                    self._group_resize_cooldown[gid] = 3

            cooldown = self._group_resize_cooldown.get(gid, 0)
            if cooldown > 0:
                self._group_resize_cooldown[gid] = cooldown - 1

            # 自定义组框拖动：标题栏/边框按下后按鼠标增量平移。
            drag_cooldown = self._group_drag_cooldown.get(gid, 0)
            if drag_cooldown > 0:
                self._group_drag_cooldown[gid] = drag_cooldown - 1
            hovered_editor = int(self._hovered_node_id)
            hovered_real = hovered_editor in canvas.nodes
            if (imgui.is_mouse_clicked(0) and pointer_on_group
                    and not handle_hit and not desc_button_hit
                    and not hovered_real
                    and not self._group_drag_gid
                    and not self._group_resize_gid):
                self._group_drag_gid = gid
                self._group_drag_last_mouse = self._mouse_canvas
                self._reset_box_state()
                self._active_group = gid
                try:
                    ne.select_node(ne.NodeId(editor_id))
                except Exception:  # noqa: BLE001
                    pass
            custom_drag = (self._group_drag_gid == gid
                           and self._group_drag_last_mouse is not None
                           and self._mouse_canvas is not None)
            if (self._group_drag_gid == gid and custom_drag
                    and not imgui.is_mouse_down(0)
                    and not imgui.is_mouse_released(0)):
                self._group_drag_gid = ""
                self._group_drag_last_mouse = None
                self._group_drag_cooldown[gid] = 3
                custom_drag = False
            if custom_drag:
                dmx = self._mouse_canvas[0] - self._group_drag_last_mouse[0]
                dmy = self._mouse_canvas[1] - self._group_drag_last_mouse[1]
                if abs(dmx) > 0.01 or abs(dmy) > 0.01:
                    self._move_group(canvas, gid, dmx, dmy)
                    bounds = group_bounds(canvas, gid) or bounds
                self._group_drag_last_mouse = self._mouse_canvas
                suppressed.update(descendant_group_ids(canvas, gid))
                if imgui.is_mouse_released(0):
                    self._group_drag_gid = ""
                    self._group_drag_last_mouse = None
                    self._group_drag_cooldown[gid] = 3

            if (not custom_resize and not custom_drag
                    and cooldown <= 0 and drag_cooldown <= 0 and not skip_drag
                    and selected and size_changed and interacting):
                applied = scale_group_to_box(
                    canvas, gid,
                    (float(cur_pos.x), float(cur_pos.y),
                     float(cur_size.x), float(cur_size.y)),
                    self._node_size_for_group)
                if applied is not None:
                    bounds = applied
                    suppressed.update(descendant_group_ids(canvas, gid))
                    print(f"[GroupResize] {gid}: "
                          f"{bounds[2]:.1f} x {bounds[3]:.1f}")
            elif (not custom_resize and not custom_drag
                  and cooldown <= 0 and drag_cooldown <= 0 and not skip_drag
                  and selected and pos_changed and interacting):
                dx = float(cur_pos.x) - float(last_pos[0])
                dy = float(cur_pos.y) - float(last_pos[1])
                moved = self._move_group(canvas, gid, dx, dy)
                suppressed.update(descendant_group_ids(canvas, gid))
                bounds = group_bounds(canvas, gid) or bounds
                print(f"[GroupDrag] {gid}: moved {moved} node(s) "
                      f"by ({dx:.1f}, {dy:.1f})")

            expected = (float(bounds[0]), float(bounds[1]))
            next_pos[gid] = expected
            next_size[gid] = (float(bounds[2]), float(bounds[3]))
            if selected:
                self._active_group = gid
            ne.set_node_position(ne.NodeId(editor_id), imgui.ImVec2(*expected))
            try:
                ne.set_node_z_position(ne.NodeId(editor_id), -1.0)
            except Exception:  # noqa: BLE001 — API optional
                pass
            active = (gid == self._active_group)
            ne.push_style_color(
                ne.StyleColor.group_bg,
                imgui.ImVec4(*(GROUP_BG_ACTIVE if active else GROUP_BG)))
            ne.push_style_color(
                ne.StyleColor.group_border,
                imgui.ImVec4(*(GROUP_BORDER_ACTIVE if active else GROUP_BORDER)))
            # Group(size) 只在首次创建时使用 size；之后必须 SetGroupSize，
            # 否则持久化 box / 手柄缩放 / 成员自适应都不会改变可视组框。
            try:
                ne.set_group_size(ne.NodeId(editor_id),
                                  imgui.ImVec2(bounds[2], bounds[3]))
            except Exception:  # noqa: BLE001 — API optional
                pass
            ne.begin_node(ne.NodeId(editor_id))
            ne.group(imgui.ImVec2(bounds[2], bounds[3]))
            try:
                fmin = imgui.get_item_rect_min()
                fmax = imgui.get_item_rect_max()
                fstl = ne.canvas_to_screen(fmin)
                fsbr = ne.canvas_to_screen(fmax)
                self._group_frame_rects[gid] = (
                    float(fstl.x), float(fstl.y),
                    float(fsbr.x), float(fsbr.y))
            except Exception:  # noqa: BLE001
                fmin = imgui.ImVec2(expected[0], expected[1])
                fmax = imgui.ImVec2(expected[0] + bounds[2],
                                    expected[1] + bounds[3])

            # 标题画在框内左上角；文本宽度超出时截断，避免撑大节点 bounds。
            label = str(grp.get("alias") or gid)
            gtype = str(grp.get("type") or "group")
            io_ids = all_io_node_ids(canvas, gid)
            count = len([nid for nid in group_member_ids(canvas, gid)
                         if nid not in io_ids])
            indent = 8.0 + 12.0 * group_depth(canvas, gid)
            desc_open = gid not in self._group_desc_closed
            desc_btn_label = (t("node_editor.description_hide")
                              if desc_open else
                              t("node_editor.description"))
            desc_btn_w = max(48.0,
                             imgui.calc_text_size(desc_btn_label).x + 18.0)
            text_w = max(80.0, float(fmax.x - fmin.x) - indent - 12.0
                         - desc_btn_w - 6.0)
            field_w = min(320.0, max(120.0, text_w))

            # 双击标题/描述进入内联编辑（Groups 窗口之外的直接入口）。
            mouse = self._mouse_screen
            if imgui.is_mouse_double_clicked(0) and mouse is not None:
                title_hit = self._point_in_rect(prev_title_rects.get(gid), mouse)
                desc_hit = self._point_in_rect(prev_desc_rects.get(gid), mouse)
                if title_hit:
                    self._start_group_inline_edit(gid, "name", grp)
                elif desc_hit:
                    self._start_group_inline_edit(gid, "description", grp)

            editing_name = (self._group_inline_edit_gid == gid
                            and self._group_inline_field == "name")
            if editing_name:
                imgui.set_cursor_screen_pos(
                    imgui.ImVec2(fmin.x + 6.0 + indent, fmin.y + 3.0))
                imgui.set_next_item_width(field_w)
                if self._group_inline_focus:
                    imgui.set_keyboard_focus_here()
                    self._group_inline_focus = False
                _changed, _value = imgui.input_text(
                    f"##group_inline_name_{gid}", self._group_inline_name,
                    imgui.InputTextFlags_.enter_returns_true)
                if _changed:
                    self._group_inline_name = _value
                _apply = (imgui.is_item_deactivated_after_edit()
                          or imgui.is_key_pressed(imgui.Key.enter))
                if imgui.is_key_pressed(imgui.Key.escape):
                    self._clear_group_inline_edit()
                elif _apply:
                    _res = rename_group(canvas, gid, self._group_inline_name)
                    if _res.get("ok"):
                        self._group_inline_name = str(_res.get("alias") or "")
                        self._group_inline_error = ""
                        self._clear_group_inline_edit()
                    else:
                        self._group_inline_error = "; ".join(
                            _res.get("errors") or ["rename failed"])
                try:
                    tmin = imgui.get_item_rect_min()
                    tmax = imgui.get_item_rect_max()
                    tstl = ne.canvas_to_screen(tmin)
                    tsbr = ne.canvas_to_screen(tmax)
                    self._group_title_rects[gid] = (
                        float(tstl.x), float(tstl.y),
                        float(tsbr.x), float(tsbr.y))
                except Exception:  # noqa: BLE001
                    pass
            else:
                full_title = f"@{label}   [{gtype}]   ({count})"
                title = self._group_title_text(full_title, text_w)
                imgui.set_cursor_screen_pos(
                    imgui.ImVec2(fmin.x + 6.0 + indent, fmin.y + 4.0))
                imgui.push_style_color(imgui.Col_.text,
                                       imgui.ImVec4(*GROUP_TITLE))
                imgui.text(title)
                self._group_title_texts[gid] = title
                try:
                    tmin = imgui.get_item_rect_min()
                    tmax = imgui.get_item_rect_max()
                    tstl = ne.canvas_to_screen(tmin)
                    tsbr = ne.canvas_to_screen(tmax)
                    self._group_title_rects[gid] = (
                        float(tstl.x), float(tstl.y),
                        float(tsbr.x), float(tsbr.y))
                except Exception:  # noqa: BLE001
                    pass
                imgui.pop_style_color(1)

            # 与普通节点一致：标题行右侧提供 Description/Hide 按钮，
            # 默认展开（首次打开即可见描述），用户可主动折叠。
            imgui.set_cursor_screen_pos(
                imgui.ImVec2(fmax.x - desc_btn_w - 4.0, fmin.y + 2.0))
            if imgui.small_button(
                    f"{desc_btn_label}##group_desc_toggle_{gid}"):
                if desc_open:
                    self._group_desc_closed.add(gid)
                else:
                    self._group_desc_closed.discard(gid)
                desc_open = not desc_open
                if not desc_open and (self._group_inline_edit_gid == gid
                                      and self._group_inline_field == "description"):
                    self._clear_group_inline_edit()
                # 这一帧组拖动判定已读过上一帧按钮矩形；把冷却置高，
                # 避免按钮点击后紧接着的鼠标移动把整组拖走。
                self._group_drag_gid = ""
                self._group_drag_last_mouse = None
                self._group_drag_cooldown[gid] = 2
            try:
                bmin = imgui.get_item_rect_min()
                bmax = imgui.get_item_rect_max()
                bstl = ne.canvas_to_screen(bmin)
                bsbr = ne.canvas_to_screen(bmax)
                self._group_desc_button_rects[gid] = (
                    float(bstl.x), float(bstl.y),
                    float(bsbr.x), float(bsbr.y))
            except Exception:  # noqa: BLE001
                pass

            # 组也是节点：标题下方显示描述（默认展开；空时显示浅色占位）。
            raw_desc = str(grp.get("description") or "")
            desc = " ".join(raw_desc.split())
            editing_desc = bool(
                desc_open
                and self._group_inline_edit_gid == gid
                and self._group_inline_field == "description")
            if editing_desc:
                imgui.set_cursor_screen_pos(
                    imgui.ImVec2(fmin.x + 6.0 + indent, fmin.y + 20.0))
                imgui.set_next_item_width(field_w)
                if self._group_inline_focus:
                    imgui.set_keyboard_focus_here()
                    self._group_inline_focus = False
                _changed, _value = imgui.input_text(
                    f"##group_inline_desc_{gid}", self._group_inline_desc,
                    imgui.InputTextFlags_.enter_returns_true)
                if _changed:
                    self._group_inline_desc = _value
                _apply = (imgui.is_item_deactivated_after_edit()
                          or imgui.is_key_pressed(imgui.Key.enter))
                if imgui.is_key_pressed(imgui.Key.escape):
                    self._clear_group_inline_edit()
                elif _apply:
                    _res = set_group_description(canvas, gid,
                                                 self._group_inline_desc)
                    if _res.get("ok"):
                        self._clear_group_inline_edit()
                desc_text = self._group_title_text(
                    " ".join(self._group_inline_desc.split()), text_w)
                self._group_description_texts[gid] = desc_text
            else:
                if desc_open:
                    desc_text = (self._group_title_text(desc, text_w)
                                 if desc else "")
                    self._group_description_texts[gid] = desc_text
                    shown = (desc_text
                             or t("node_editor.groups_description_placeholder"))
                    imgui.set_cursor_screen_pos(
                        imgui.ImVec2(fmin.x + 6.0 + indent, fmin.y + 21.0))
                    if desc_text:
                        imgui.text_colored(imgui.ImVec4(*GROUP_DESC), shown)
                    else:
                        imgui.text_disabled(shown)
                else:
                    self._group_description_texts[gid] = ""
            if desc_open:
                try:
                    dmin = imgui.get_item_rect_min()
                    dmax = imgui.get_item_rect_max()
                    dstl = ne.canvas_to_screen(dmin)
                    dsbr = ne.canvas_to_screen(dmax)
                    self._group_description_rects[gid] = (
                        float(dstl.x), float(dstl.y),
                        float(dsbr.x), float(dsbr.y))
                except Exception:  # noqa: BLE001
                    pass
            if self._group_inline_edit_gid == gid and self._group_inline_error:
                imgui.set_cursor_screen_pos(
                    imgui.ImVec2(fmin.x + 6.0 + indent, fmin.y + 37.0))
                imgui.text_colored(
                    imgui.ImVec4(ERROR_RED[0], ERROR_RED[1], ERROR_RED[2], 1.0),
                    self._group_inline_error)

            # 右下角缩放手柄（可视提示；命中使用上一帧屏幕矩形）。
            try:
                hw = imgui.calc_text_size("+").x
                imgui.set_cursor_screen_pos(
                    imgui.ImVec2(fmax.x - hw - 6.0, fmax.y - 18.0))
                imgui.text_colored(imgui.ImVec4(*GROUP_TITLE), "+")
            except Exception:  # noqa: BLE001
                pass

            ne.pop_style_color(2)
            ne.end_node()
            self._draw_group_edge_io(canvas, gid, bounds, ne)
            # 组框命中/框选都在 end() 之后，抓取本帧有效屏幕矩形。
            try:
                gpos = ne.get_node_position(ne.NodeId(editor_id))
                gsize = ne.get_node_size(ne.NodeId(editor_id))
                gtl = ne.canvas_to_screen(gpos)
                gbr = ne.canvas_to_screen(
                    imgui.ImVec2(gpos.x + gsize.x, gpos.y + gsize.y))
                self._group_screen_rects[gid] = (
                    float(gtl.x), float(gtl.y), float(gbr.x), float(gbr.y))
            except Exception:  # noqa: BLE001
                pass
        self._group_last_pos = next_pos
        self._group_last_size = next_size

    def _draw_nodes(self, canvas: NodeCanvas, ne) -> None:
        n_drawn = 0
        self._rendered_nids: set[int] = set()
        self._node_screen_rects.clear()
        self._prepare_group_boxes(canvas)
        self._refresh_group_io(canvas)
        self._draw_group_hints(canvas, ne)
        drawable_total = 0
        for _inst in canvas.nodes.values():
            if _inst.node_type not in GROUP_IO_TYPES:
                drawable_total += 1
        for nid, inst in list(canvas.nodes.items()):
            # GroupStart/GroupEnd 由 _draw_group_hints 作为组框边缘接口绘制，
            # 不作为普通节点卡片重复渲染。
            if inst.node_type in GROUP_IO_TYPES:
                continue
            nd = _TYPES.get(inst.node_type)
            if nd is None:
                print(f"[DrawNodes] SKIP nid={nid}: type '{inst.node_type}' not in _TYPES")
                continue

            ne.set_node_position(
                ne.NodeId(nid),
                imgui.ImVec2(inst.pos[0], inst.pos[1]),
            )
            ne.begin_node(ne.NodeId(nid))
            _apply_ne_style(nd.accent_color)

            # 标题栏（别名 — tools/agent 侧可读名; 运行时忽略）
            imgui.push_style_color(imgui.Col_.text, _col(nd.accent_color, 1.00))
            imgui.text(node_label(nd.type_name, nd.label))
            imgui.pop_style_color(1)
            alias = str(getattr(inst, "alias", "") or "")
            if alias:
                imgui.same_line()
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                imgui.text(f"@{alias}")
                imgui.pop_style_color(1)
            else:
                # 未命名节点: 显示稳定 nid, 便于在画布/查询列表间对应
                imgui.same_line()
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                imgui.text(f"#{nid}")
                imgui.pop_style_color(1)

            # 静态说明文字不再占卡片高度；NodeCanvas 已将其作为默认
            # description 写入实例，需要时在 Description 展开区查看。
            self._draw_description(nid, inst)

            # ── 节点专用内联控件（注册表驱动，按 node_type 分发） ──
            draw_node_widgets(nid, inst, canvas)

            self._draw_pins(canvas, ne, nid, inst, nd)
            ne.end_node()
            try:
                npos = ne.get_node_position(ne.NodeId(nid))
                nsize = ne.get_node_size(ne.NodeId(nid))
                self._node_canvas_rects[nid] = (
                    float(npos.x), float(npos.y),
                    float(nsize.x), float(nsize.y))
                ntl = ne.canvas_to_screen(npos)
                nbr = ne.canvas_to_screen(
                    imgui.ImVec2(npos.x + nsize.x, npos.y + nsize.y))
                self._node_screen_rects[nid] = (
                    float(ntl.x), float(ntl.y), float(nbr.x), float(nbr.y))
            except Exception:  # noqa: BLE001
                pass
            self._rendered_nids.add(nid)
            n_drawn += 1
        if n_drawn != drawable_total:
            print(f"[DrawNodes] drawn={n_drawn}/{drawable_total} nodes "
                  f"({drawable_total-n_drawn} skipped)")
        for nid in list(self._node_canvas_rects):
            if nid not in canvas.nodes:
                self._node_canvas_rects.pop(nid, None)

    # ============================================================
    # 子步骤: 节点描述
    # ============================================================

    def _draw_description(self, nid: int, inst) -> None:
        """描述区: 折叠时显示首行; 展开后可直接编辑（持久化到节点实例）。"""
        desc = str(getattr(inst, "description", "") or "")
        is_open = nid in self._desc_open
        label = t("node_editor.description_hide") if is_open else t("node_editor.description")
        if imgui.small_button(f"{label}##desc_toggle_{nid}"):
            if is_open:
                self._desc_open.discard(nid)
            else:
                self._desc_open.add(nid)
            is_open = not is_open
        if is_open:
            imgui.set_next_item_width(240)
            changed, value = imgui.input_text_multiline(
                f"##desc_edit_{nid}", desc, imgui.ImVec2(240, 56),
            )
            if changed:
                inst.description = value
            if not desc:
                imgui.text_disabled(t("node_editor.description_tip"))
        # 折叠时不显示 description 预览：默认 props_text 已移入描述区，
        # 不再让浅色小字占用卡片高度。

    # ============================================================
    # 子步骤: 引脚渲染
    # ============================================================

    def _draw_pins(self, canvas: NodeCanvas, ne, nid: int, inst, nd) -> None:
        """绘制节点的所有引脚 + 分隔线。"""
        pins = get_visible_pins(inst, nd, canvas)

        # ── 第 1 步: 计算节点宽度（基于标题 + 所有 pin 原始文字） ──
        _title_w = imgui.calc_text_size(f"  {node_label(nd.type_name, nd.label)}  ").x
        _max_pin_text_w = max(
            (imgui.calc_text_size(f"> {p.name}").x for p in pins),
            default=0,
        )
        _node_w = max(_title_w, _max_pin_text_w, 80.0)

        # ── 第 2 步: 输出 pin 右对齐 → padding = 节点宽 - 输出文字宽 - 边距 ──
        _max_out_w = max(
            (imgui.calc_text_size(f"{p.name} >").x
             for p in pins if p.direction == "output"),
            default=0,
        )
        _min_pad = imgui.calc_text_size("> ").x * 4
        _margin = imgui.calc_text_size("  ").x
        _out_pad = max(_node_w - _max_out_w - _margin, _min_pad)

        # 手动画分隔线
        _cursor = imgui.get_cursor_screen_pos()
        _dl = imgui.get_window_draw_list()
        _dl.add_line(
            imgui.ImVec2(_cursor.x, _cursor.y + 3),
            imgui.ImVec2(_cursor.x + _node_w, _cursor.y + 3),
            imgui.get_color_u32(imgui.Col_.border),
            1.0,
        )
        imgui.dummy(imgui.ImVec2(0, 6))

        for pin in pins:
            pin_id = inst.pin_ids.get(pin.name)
            if pin_id is None:
                continue  # 版本兼容 pin 尚未补齐（加载时 heal; 防御性跳过）
            kind = ne.PinKind.input if pin.direction == "input" else ne.PinKind.output
            ne.begin_pin(ne.PinId(pin_id), kind)
            if pin.direction == "output":
                imgui.dummy(imgui.ImVec2(_out_pad, 1))
                imgui.same_line()
                imgui.text(f"{pin.name} >")
            else:
                imgui.text(f"> {pin.name}")
            ne.end_pin()

    # ============================================================
    # 子步骤: 连线渲染
    # ============================================================

    def _draw_links(self, canvas: NodeCanvas, ne) -> None:
        for lk in canvas.links.values():
            # ── 按 from_pin 的 data_type 决定连线颜色 ──
            dtype = canvas.find_pin_data_type(lk.from_pin)
            color = LINK_COLORS.get(dtype, _LINK_COLOR_FALLBACK)
            ne.link(
                ne.LinkId(lk.id),
                ne.PinId(lk.from_pin),
                ne.PinId(lk.to_pin),
                _col(color, 0.75),
                2.0,
            )

    # ============================================================
    # 子步骤: Pin 拖拽创建连线
    # ============================================================

    def _handle_link_creation(self, canvas: NodeCanvas, ne) -> None:
        if ne.begin_create():
            sp = ne.PinId(0)
            ep = ne.PinId(0)
            if ne.query_new_link(sp, ep):
                if sp.id() != 0 and ep.id() != 0:
                    sd = canvas.find_pin_dir(sp.id())
                    ed = canvas.find_pin_dir(ep.id())
                    sn = canvas.find_pin_node(sp.id())
                    en = canvas.find_pin_node(ep.id())
                    if (sd and ed and sd != ed and sn and en and sn != en):
                        out_pin = sp.id() if sd == "output" else ep.id()
                        in_pin = ep.id() if sd == "output" else sp.id()
                        if (canvas.find_pin_dir(out_pin) == "output"
                                and canvas.find_pin_dir(in_pin) == "input"):
                            if ne.accept_new_item():
                                lid = canvas.add_link(out_pin, in_pin)
                                if lid != -1:
                                    print(
                                        f"[Link] Created: "
                                        f"{canvas.find_pin_name(out_pin)} → "
                                        f"{canvas.find_pin_name(in_pin)}"
                                    )
                                else:
                                    print("[Link] Duplicate — skipped")
            ne.end_create()

    # ============================================================
    # 子步骤: Delete 键删除
    # ============================================================

    def _delete_nodes(self, canvas: NodeCanvas, nids) -> int:
        """删除节点（含设备配对级联），同步清理组成员并收紧组框。"""
        selected = [int(nid) for nid in nids if int(nid) in canvas.nodes]
        if not selected:
            return 0
        # ── 设备 Init ⇄ Kill 强制配对: 删除级联 (SigGen 等) ──
        expand = device_cascade_deletes(canvas, selected)
        # 删除节点也是“离开组”；删除后按剩余成员收紧相关组框。
        affected_gids = {
            gid for gid in (getattr(canvas, "node_groups", None) or {})
            if any(nid in group_member_ids(canvas, gid) for nid in expand)
        }
        for extra in sorted(expand - set(selected)):
            inst = canvas.nodes.get(extra)
            if inst is not None:
                print(f"[Delete] Cascade (device Init/Kill pairing): "
                      f"{inst.node_type} (id={extra})")

        count = 0
        for nid in sorted(expand):
            inst = canvas.nodes.get(nid)
            if inst is None:
                continue
            print(f"[Delete] Node: {inst.node_type} (id={nid})")
            canvas.remove_node(nid)
            count += 1

        groups = getattr(canvas, "node_groups", None) or {}
        for gid in sorted(affected_gids, key=lambda g: group_depth(canvas, g),
                          reverse=True):
            grp = groups.get(gid)
            if not isinstance(grp, dict):
                continue
            keep: list[int] = []
            for raw in grp.get("members") or []:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value not in expand and value not in keep:
                    keep.append(value)
            grp["members"] = keep
            io = grp.get("io_nodes") if isinstance(grp.get("io_nodes"), dict) else {}
            for key in ("start", "end"):
                try:
                    value = int(io.get(key))
                except (TypeError, ValueError):
                    continue
                if value in expand:
                    io.pop(key, None)
            fit_group(canvas, gid, self._node_size_for_group, shrink=True)
        return count

    def _delete_selected_nodes(self, canvas: NodeCanvas, ne) -> int:
        # 组入口/出口是组的生命周期组件；Delete 键不应单独删掉它们。
        nids = [n.id() for n in ne.get_selected_nodes()
                if n.id() in canvas.nodes
                and group_io_owner(canvas, n.id()) is None]
        count = self._delete_nodes(canvas, nids)
        ne.clear_selection()
        return count

    def _handle_deletion(self, canvas: NodeCanvas, ne) -> None:
        if not imgui.is_key_pressed(imgui.Key.delete, False):
            return
        sel_links = ne.get_selected_links()
        node_count = self._delete_selected_nodes(canvas, ne)
        link_count = 0
        for sl in sel_links:
            lid = sl.id()
            if lid in canvas.links:
                print(f"[Delete] Link: {lid}")
                canvas.remove_link(lid)
                link_count += 1
        if node_count == 0 and link_count == 0:
            print("[Delete] No selection — click a node first, then press Delete")

    def _draw_add_popup(self, canvas: NodeCanvas) -> None:
        imgui.set_next_window_pos(self._add_popup_pos)
        _bpop = imgui.begin_popup(t("node_editor.create_node") + "###create_node")
        if _bpop:
            for title, items in [*MENU_SECTIONS, *NodePackRegistry.menu_sections()]:
                _draw_add_menu_section(title, items, canvas, self._add_node_pos)
            imgui.end_popup()

    # ============================================================
    # 子步骤: 自动布局
    # ============================================================

    def _auto_layout(self, canvas: NodeCanvas) -> None:
        """Group-aware topological layout.

        A group is one block in its parent layout; nested groups are laid out
        recursively before the parent allocates space for them.  This prevents
        the old node-only pass from squeezing a group between its neighbours.
        """
        if not canvas.nodes:
            return
        positions = GroupLayoutEngine(canvas).layout_all()
        for nid, pos in positions.items():
            inst = canvas.nodes.get(nid)
            if inst is not None:
                inst.pos = (float(pos[0]), float(pos[1]))
        groups = getattr(canvas, "node_groups", None) or {}
        if len(self._node_canvas_rects) >= len(canvas.nodes):
            for gid in sorted(groups, key=lambda g: group_depth(canvas, g),
                              reverse=True):
                fit_group(canvas, gid, self._node_size_for_group, shrink=True)
        else:
            self._group_fit_pending = True
        print(f"[Rearrange] {len(canvas.nodes)} nodes / {len(groups)} groups laid out")
    def _auto_layout_group(self, canvas: NodeCanvas, gid: str) -> None:
        """Rearrange one group's contents, then reflow its ancestors.

        The group keeps its current top-left; its frame size follows the new
        member bounds.  Ancestors are re-laid out so a resized child cannot
        overlap its siblings.
        """
        groups = getattr(canvas, "node_groups", None) or {}
        if gid not in groups:
            return
        engine = GroupLayoutEngine(canvas)
        origin = group_bounds(canvas, gid)
        positions = engine.layout_group(gid)
        if origin is None or not positions:
            return
        for nid, (x, y) in positions.items():
            inst = canvas.nodes.get(nid)
            if inst is not None:
                inst.pos = (origin[0] + float(x), origin[1] + float(y))
        fit_group(canvas, gid, self._node_size_for_group, shrink=True)
        print(f"[Rearrange] group {gid}: {len(positions)} nodes")

        parent = str((groups.get(gid) or {}).get("parent") or "")
        while parent and parent in groups:
            p_origin = group_bounds(canvas, parent)
            p_positions = engine.layout_group(parent)
            if p_origin is None or not p_positions:
                break
            for nid, (x, y) in p_positions.items():
                inst = canvas.nodes.get(nid)
                if inst is not None:
                    inst.pos = (p_origin[0] + float(x), p_origin[1] + float(y))
            fit_group(canvas, parent, self._node_size_for_group, shrink=True)
            print(f"[Rearrange] parent group {parent}: "
                  f"{len(p_positions)} nodes")
            parent = str((groups.get(parent) or {}).get("parent") or "")

    # ============================================================
    # 子步骤: 位置同步
    # ============================================================

    def _sync_positions(self, canvas: NodeCanvas, ne) -> None:
        rendered = getattr(self, '_rendered_nids', set())
        for nid in list(canvas.nodes.keys()):
            # ★ 跳过本帧未渲染的节点（新增节点编辑器还不认识，get_node_position 会返回垃圾值）
            if nid not in rendered:
                continue
            np = ne.get_node_position(ne.NodeId(nid))
            inst = canvas.nodes[nid]
            inst.pos = (np.x, np.y)
