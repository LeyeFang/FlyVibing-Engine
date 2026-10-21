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
from Application.Editor.UI.FileDialog import FileDialog
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
from .styling import (
    _col,
    _apply_ne_style,
    _HDR_COLOR,
    LINK_COLORS,
    _LINK_COLOR_FALLBACK,
    MENU_SECTIONS,
    TEXT_DISABLED,
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
        changed, _selected = imgui.menu_item(display_label, "", False, True)
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

class NodeEditorPanel(BasePanel):
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
        self._group_prev_pos: dict[str, tuple[float, float]] = {}
        self._fit_group_pending: str = ""

    # ============================================================
    # 生命周期
    # ============================================================

    def on_attach(self) -> None:
        if not self._editor_initialized:
            try:
                os.makedirs(os.path.dirname(self._CONFIG_FILE), exist_ok=True)
                config = node_ed.Config()
                config.settings_file = self._CONFIG_FILE
                self._editor_context = node_ed.create_editor(config)
                self._editor_initialized = True
            except Exception:
                self._editor_context = None

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
        if self._add_target_pending:
            # 工具栏/弹窗都已经画完，此时光标位置就是画布左上角。
            canvas_origin = imgui.get_cursor_screen_pos()
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

        self._draw_add_popup(canvas)
        self._sync_positions(canvas, ne)

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

        if self._fit_requested:
            ne.navigate_to_content()
            self._fit_requested = False

        if self._fit_group_pending:
            gid = self._fit_group_pending
            self._fit_group_pending = ""
            ids = group_member_ids(canvas, gid)
            if ids:
                try:
                    ne.clear_selection()
                    for nid in ids:
                        if nid in canvas.nodes:
                            ne.select_node(ne.NodeId(nid))
                    ne.navigate_to_selection(True)
                    ne.clear_selection()
                except Exception as e:  # noqa: BLE001
                    print(f"[GroupFit] {gid} failed: {e}")

        self._draw_nodes(canvas, ne)
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

    def _move_group(self, canvas: NodeCanvas, gid: str, dx: float, dy: float) -> int:
        """Translate every node in a group subtree by (dx, dy)."""
        ids = group_member_ids(canvas, gid)
        for nid in ids:
            inst = canvas.nodes.get(nid)
            if inst is not None:
                inst.pos = (float(inst.pos[0]) + dx, float(inst.pos[1]) + dy)
        return len(ids)

    def _draw_group_hints(self, canvas: NodeCanvas, ne) -> None:
        """绘制可拖拽的节点组框（父子组按深度排序，父框在底层）。

        组框位置由成员节点的包围盒推导；拖动组框时把整棵成员子树平移。
        这使 group 成为 Rearrange / 外部节点的真实布局单元，而不是纯装饰。
        """
        groups = getattr(canvas, "node_groups", None) or {}
        if not groups:
            self._group_prev_pos.clear()
            return
        suppressed: set[str] = set()
        for gid in group_order(canvas):
            skip_drag = gid in suppressed
            bounds = group_bounds(canvas, gid)
            if bounds is None:
                self._group_prev_pos.pop(gid, None)
                continue
            grp = groups.get(gid) or {}
            editor_id = self._group_editor_id(gid)
            expected = (float(bounds[0]), float(bounds[1]))
            prev = self._group_prev_pos.get(gid)
            selected = False
            try:
                selected = bool(ne.is_node_selected(ne.NodeId(editor_id)))
            except Exception:  # noqa: BLE001 — node not created yet
                selected = False

            # A selected group that moved in the node editor is a user drag.
            # Recompute bounds first because other nodes may have changed size.
            # Descendants of a dragged parent are drawn but never drag twice.
            if prev is not None and selected and not skip_drag:
                try:
                    cur = ne.get_node_position(ne.NodeId(editor_id))
                    dx = float(cur.x) - prev[0]
                    dy = float(cur.y) - prev[1]
                except Exception:  # noqa: BLE001
                    dx = dy = 0.0
                if abs(dx) > 0.75 or abs(dy) > 0.75:
                    moved = self._move_group(canvas, gid, dx, dy)
                    suppressed.update(descendant_group_ids(canvas, gid))
                    bounds = group_bounds(canvas, gid)
                    if bounds is None:
                        continue
                    expected = (float(bounds[0]), float(bounds[1]))
                    print(f"[GroupDrag] {gid}: moved {moved} node(s) "
                          f"by ({dx:.1f}, {dy:.1f})")

            self._group_prev_pos[gid] = expected
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
                imgui.ImVec4(0.18, 0.34, 0.50, 0.70) if not active
                else imgui.ImVec4(0.24, 0.44, 0.62, 0.78))
            ne.push_style_color(
                ne.StyleColor.node_border,
                imgui.ImVec4(0.45, 0.72, 0.95, 1.00) if not active
                else imgui.ImVec4(0.95, 0.78, 0.32, 1.00))
            ne.begin_node(ne.NodeId(editor_id))
            ne.group(imgui.ImVec2(bounds[2], bounds[3]))
            # Group() 会把光标推进到框底 — 拉回左上角画标题
            indent = 8.0 + 12.0 * group_depth(canvas, gid)
            imgui.set_cursor_pos(imgui.ImVec2(indent, 6.0))
            label = str(grp.get("alias") or gid)
            gtype = str(grp.get("type") or "group")
            count = len(group_member_ids(canvas, gid))
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(0.70, 0.86, 0.98, 1.0))
            imgui.text(f"@{label}   [{gtype}]   ({count})")
            imgui.pop_style_color(1)
            ne.pop_style_color(2)
            ne.end_node()

    def _draw_nodes(self, canvas: NodeCanvas, ne) -> None:
        n_drawn = 0
        self._rendered_nids: set[int] = set()
        self._draw_group_hints(canvas, ne)
        for nid, inst in list(canvas.nodes.items()):
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

            # 属性文字
            if nd.props_text:
                imgui.dummy(imgui.ImVec2(0, 2))
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                for line in nd.props_text.split("\n"):
                    imgui.text(f"  {line}")
                imgui.pop_style_color(1)
                imgui.dummy(imgui.ImVec2(0, 2))

            self._draw_description(nid, inst)

            # ── 节点专用内联控件（注册表驱动，按 node_type 分发） ──
            draw_node_widgets(nid, inst, canvas)

            self._draw_pins(canvas, ne, nid, inst, nd)
            ne.end_node()
            self._rendered_nids.add(nid)
            n_drawn += 1
        if n_drawn != len(canvas.nodes):
            print(f"[DrawNodes] drawn={n_drawn}/{len(canvas.nodes)} nodes "
                  f"({len(canvas.nodes)-n_drawn} skipped)")

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
        elif desc:
            first = desc.splitlines()[0].strip()
            if len(first) > 46:
                first = first[:43] + "..."
            imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
            imgui.text(first)
            imgui.pop_style_color(1)

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

    def _handle_deletion(self, canvas: NodeCanvas, ne) -> None:
        _del_pressed = imgui.is_key_pressed(imgui.Key.delete, False)
        if _del_pressed:
            _sel_nodes = ne.get_selected_nodes()
            _sel_links = ne.get_selected_links()
            _del_node_count = 0
            _del_link_count = 0

            # ── 设备 Init ⇄ Kill 强制配对: 删除级联 (SigGen 等) ──
            _sel_nids = [sn.id() for sn in _sel_nodes if sn.id() in canvas.nodes]
            _expand = device_cascade_deletes(canvas, _sel_nids)
            for _extra in sorted(_expand - set(_sel_nids)):
                _inst = canvas.nodes.get(_extra)
                if _inst is not None:
                    print(f"[Delete] Cascade (device Init/Kill pairing): "
                          f"{_inst.node_type} (id={_extra})")

            for nid in sorted(_expand):
                if nid in canvas.nodes:
                    print(f"[Delete] Node: {canvas.nodes[nid].node_type} (id={nid})")
                    canvas.remove_node(nid)
                    _del_node_count += 1
            for sl in _sel_links:
                lid = sl.id()
                if lid in canvas.links:
                    print(f"[Delete] Link: {lid}")
                    canvas.remove_link(lid)
                    _del_link_count += 1
            if _del_node_count == 0 and _del_link_count == 0:
                print("[Delete] No selection — click a node first, then press Delete")
            ne.clear_selection()

    # ============================================================
    # 子步骤: Import / Export 弹出窗口
    # ============================================================

    def _draw_import_popup(self, canvas: NodeCanvas) -> None:
        """绘制 Import Graph 弹出窗口。"""
        if not imgui.begin_popup_modal(t("node_editor.import_title") + "###import_graph", None, imgui.WindowFlags_.always_auto_resize)[0]:
            return

        imgui.text(t("node_editor.import_prompt"))
        imgui.spacing()

        # ── 文件路径输入 ──
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

        # ── 错误提示 ──
        if self._import_error:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                self._import_error,
            )

        # ── 静态检查开关（agent 导入默认拒绝静态错误; GUI 默认关 — 便于导入待修图）──
        _, self._import_validate_first = imgui.checkbox(
            t("node_editor.import_validate_first"), self._import_validate_first)

        imgui.spacing()

        # ── Import / Cancel ──
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

        # ── 文件路径输入 ──
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

        # ── 节点/连线统计（组 = tools 层宏元数据）──
        n_count = len(canvas.nodes)
        l_count = len(canvas.links)
        groups = getattr(canvas, "node_groups", None) or {}
        imgui.text_disabled(t("node_editor.export_count", nodes=n_count, links=l_count,
                              groups=len(groups)))

        imgui.spacing()

        # ── 错误提示 ──
        if self._export_error:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                self._export_error,
            )

        imgui.spacing()

        # ── Export / Cancel ──
        if imgui.button(t("node_editor.export"), imgui.ImVec2(100, 0)):
            self._do_export(canvas)

        imgui.same_line()
        if imgui.button(t("node_editor.cancel"), imgui.ImVec2(100, 0)):
            self._export_path = ""
            self._export_error = ""
            imgui.close_current_popup()

        imgui.end_popup()

    def _do_import(self, canvas: NodeCanvas) -> None:
        """执行导入：读取 + （可选）静态检查 → 替换画布内容。

        实现与 agent ops（LiveCommandServer graph.import）共用 graph_io.prepare_import/apply_to_canvas;
        validate_first 由弹窗复选框控制（GUI 默认关 — 便于导入待修图; agent 默认开）。
        """
        fp = self._import_path.strip()
        if not fp:
            self._import_error = "Please select a file."
            return

        from Application.Core.NodeGraph import graph_io

        try:
            data, refused = graph_io.prepare_import(path=fp, validate_first=self._import_validate_first)
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
        imgui.close_current_popup()

    def _do_export(self, canvas: NodeCanvas) -> None:
        """执行导出：序列化画布（含 _rules）→ JSON 文件。实现与 agent ops 同源（graph_io）。"""
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

    # ============================================================
    # 子步骤: Validate（引擎内校验服务 — 与 MCP graph.validate.* 同源）
    # ============================================================

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
            self._report_note = str(result.get("note") or "a validation task is already running")
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
                for ent in entries:
                    if isinstance(ent, dict):
                        msg = str(ent.get("message", ent))
                        nid = ent.get("node_id")
                    else:
                        msg, nid = str(ent), None
                    label = f"  [{nid}] {msg}" if nid is not None else f"  {msg}"
                    if imgui.selectable(label, False)[0] and nid is not None:
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

    # ============================================================
    # 子步骤: Import / Export 弹出窗口（END）
    # ============================================================

    # ============================================================
    # 子步骤: 节点查询窗口（按 alias / type / label / description）
    # ============================================================

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
                        text = f"{shown}   [{inst.node_type}]   {label}"
                        if imgui.selectable(text, nid == self._find_selected)[0]:
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

    # ============================================================
    # 子步骤: 节点组编辑窗口（嵌套树 + 组内重排 / 适配）
    # ============================================================

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
                    "##node_group_tree", imgui.ImVec2(0, -38), True)
                try:
                    if child_visible:
                        for gid in group_order(canvas):
                            grp = groups.get(gid) or {}
                            depth = group_depth(canvas, gid)
                            alias = str(grp.get("alias") or gid)
                            gtype = str(grp.get("type") or "group")
                            count = len(group_member_ids(canvas, gid))
                            label = f"{'  ' * depth}{alias} [{gtype}] ({count})"
                            if imgui.selectable(
                                    label, gid == self._active_group)[0]:
                                self._active_group = gid
                finally:
                    imgui.end_child()
                active = self._active_group
                valid = active in groups
                imgui.begin_disabled(not valid)
                if imgui.button(t("node_editor.groups_rearrange"),
                                imgui.ImVec2(180, 0)):
                    self._auto_layout_group(canvas, active)
                imgui.same_line()
                if imgui.button(t("node_editor.groups_fit"), imgui.ImVec2(150, 0)):
                    self._fit_group_pending = active
                imgui.end_disabled()
                if imgui.button(t("node_editor.groups_all"), imgui.ImVec2(0, 0)):
                    self._auto_layout(canvas)
        finally:
            imgui.end()

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

    @staticmethod
    def _auto_layout(canvas: NodeCanvas) -> None:
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
