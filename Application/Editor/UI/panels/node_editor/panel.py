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
from collections import defaultdict, deque
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

        # ── 工具栏: Add / Import / Export ──
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

    def _draw_group_hints(self, canvas: NodeCanvas, ne) -> None:
        """绘制节点组框（tools 层 node_groups 元数据 → 画布背景区）。

        组只是宏的记账：成员节点仍按普通节点绘制；这里按成员位置算包围盒，
        画一个 imgui-node-editor group 节点作视觉分区（不参与求值/删除）。
        """
        groups = getattr(canvas, "node_groups", None) or {}
        if not groups:
            return
        for gid, grp in groups.items():
            members = [int(m) for m in (grp.get("members") or [])
                       if str(m).isdigit() and int(m) in canvas.nodes]
            if not members:
                continue
            xs = [canvas.nodes[m].pos[0] for m in members]
            ys = [canvas.nodes[m].pos[1] for m in members]
            min_x, min_y = min(xs) - 40.0, min(ys) - 58.0
            max_x, max_y = max(xs) + 300.0, max(ys) + 220.0
            if str(gid).startswith("g") and str(gid)[1:].isdigit():
                node_id = self._GROUP_NODE_BASE + int(str(gid)[1:])
            else:
                node_id = self._GROUP_NODE_BASE + (zlib.crc32(str(gid).encode("utf-8")) % 10_000_000)
            ne.set_node_position(ne.NodeId(node_id), imgui.ImVec2(min_x, min_y))
            ne.push_style_color(ne.StyleColor.group_bg, imgui.ImVec4(0.18, 0.34, 0.50, 0.70))
            ne.push_style_color(ne.StyleColor.node_border, imgui.ImVec4(0.45, 0.72, 0.95, 1.00))
            ne.begin_node(ne.NodeId(node_id))
            ne.group(imgui.ImVec2(max_x - min_x, max_y - min_y))
            # Group() 会把光标推进到框底 — 拉回左上角画标题
            imgui.set_cursor_pos(imgui.ImVec2(8.0, 6.0))
            label = str(grp.get("alias") or gid)
            gtype = str(grp.get("type") or "group")
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(0.70, 0.86, 0.98, 1.0))
            imgui.text(f"@{label}   [{gtype}]")
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
        """报告条目点击 → 选中并居中到对应节点（API 缺失时静默降级）。"""
        if self._editor_context is None:
            return
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
        """拓扑分层自动布局 — 沿 exec 链路 BFS 分配层级。

        纯数据节点 (无 exec pin) 放在消费它们的 exec 节点左侧一层。
        同层节点按类型分组排序以减少连线交叉。

        层间距 320px, 节点间距 100px, 高度根据 pin 数量估算。
        """
        if not canvas.nodes:
            return

        H_SPACING = 320
        V_PADDING = 32
        V_HEADER = 44
        V_PER_PIN = 24
        V_WIDGET_EXTRA = 40  # 有关联控件的节点额外高度 (VarGet/VarSet/Constant 等)

        # ── 1. 分类连线 (exec vs data) ──
        exec_down: dict[int, list[int]] = defaultdict(list)
        data_down: dict[int, list[int]] = defaultdict(list)
        data_up: dict[int, list[int]] = defaultdict(list)

        for link in canvas.links.values():
            src_nid = canvas.find_pin_node(link.from_pin)
            dst_nid = canvas.find_pin_node(link.to_pin)
            if src_nid is None or dst_nid is None:
                continue

            pin_name = canvas.find_pin_name(link.from_pin)
            src_inst = canvas.nodes.get(src_nid)
            if src_inst and pin_name:
                ndef = _TYPES.get(src_inst.node_type)
                if ndef:
                    pdef = next((p for p in ndef.pins if p.name == pin_name), None)
                    if pdef and pdef.kind == "exec":
                        exec_down[src_nid].append(dst_nid)
                        continue
            data_down[src_nid].append(dst_nid)
            data_up[dst_nid].append(src_nid)

        # ── 2. 找根节点 ──
        event_types = {"OnGameStart", "OnFrameUpdate", "OnGameStop"}
        roots = [nid for nid, inst in canvas.nodes.items()
                 if inst.node_type in event_types]

        # ── 3. BFS 沿 exec 边分配 layer ──
        layer: dict[int, int] = {}
        queue = deque()
        for r in roots:
            layer[r] = 0
            queue.append(r)

        while queue:
            nid = queue.popleft()
            for dn in exec_down.get(nid, []):
                if dn not in layer:
                    layer[dn] = layer[nid] + 1
                    queue.append(dn)

        # 未被 BFS 到达的 exec 节点: 从其 exec 前驱推算 layer
        for nid in canvas.nodes:
            if nid in layer:
                continue
            pred_layers = [layer[s] for s, ds in exec_down.items()
                           if nid in ds and s in layer]
            layer[nid] = (max(pred_layers) + 1) if pred_layers else len(roots)

        # ── 4. 将节点按 layer 分组 ──
        layer_nodes: dict[int, list[int]] = defaultdict(list)
        max_exec_layer = max(layer.values()) if layer else 0

        for nid, inst in canvas.nodes.items():
            ndef = _TYPES.get(inst.node_type)
            has_exec = ndef and any(p.kind == "exec" for p in ndef.pins)

            if not has_exec:
                # 纯数据节点: 放在消费者的左侧一层
                consumers = data_down.get(nid, [])
                if consumers:
                    cons_layers = [layer.get(c, 0) for c in consumers]
                    dl = max(cons_layers) - 1
                    layer_nodes[max(0, dl)].append(nid)
                else:
                    # 孤立数据节点 → 最右侧
                    layer_nodes[max_exec_layer + 1].append(nid)
            else:
                layer_nodes[layer.get(nid, 0)].append(nid)

        # ── 5. 层内排序: barycenter 扫掠降交叉 ──
        #     数据边也参与重心计算, 纯数据节点按其消费者的 Y 排序
        #     然后左→右、右→左各扫一次, 按前后继重心重排
        _temp_y: dict[int, float] = {}
        for lyr in sorted(layer_nodes.keys()):
            _ty = 0.0
            for nid in layer_nodes[lyr]:
                _temp_y[nid] = _ty
                _ty += 1.0

        for _pass in range(2):
            # 左→右: 按前驱的平均 Y 排序 (exec 前驱为主, 数据前驱为 fallback)
            for lyr in sorted(layer_nodes.keys()):
                nids = layer_nodes[lyr]
                bary: dict[int, float] = {}
                for nid in nids:
                    preds = [s for s, ds in exec_down.items() if nid in ds]
                    if not preds:
                        preds = data_up.get(nid, [])
                    if preds:
                        bary[nid] = sum(_temp_y.get(p, 0.0) for p in preds) / len(preds)
                    else:
                        bary[nid] = float(nid % 1000)
                nids.sort(key=lambda n: (bary.get(n, 0.0), n))
                for i, nid in enumerate(nids):
                    _temp_y[nid] = float(i)

            # 右→左: 按后继的平均 Y 排序 (exec 后继为主, 数据消费者为 fallback)
            for lyr in reversed(sorted(layer_nodes.keys())):
                nids = layer_nodes[lyr]
                bary = {}
                for nid in nids:
                    succs = exec_down.get(nid, [])
                    if not succs:
                        succs = data_down.get(nid, [])
                    if succs:
                        bary[nid] = sum(_temp_y.get(s, 0.0) for s in succs) / len(succs)
                    else:
                        bary[nid] = float(nid % 1000)
                nids.sort(key=lambda n: (bary.get(n, 0.0), n))
                for i, nid in enumerate(nids):
                    _temp_y[nid] = float(i)

        # ── 6. 分配坐标 (按每节点实际估算高度累加 Y, 避免重叠) ──
        # 带内联控件的节点类型 (VarGet/VarSet/Constant 等) 渲染时额外高
        _WIDGET_NODES = {
            "VarGet", "VarSet", "Constant", "StringConst",
            "EntitySpawn", "EntityGet", "EntitySetRenderVisible", "EntityGroupSetVisible",
            "ComponentAdd", "SetComponent", "GetComponent", "ComponentRemove",
            "ParallelSend", "SerialSend", "PathVar", "TextFileWrite",
            "TimeGetDate",
            "InitSigGenDevice", "StartSigGenRecord", "StopSigGenRecord",
            "KillSigGenDevice", "GetSigGenData",
            "ShowMedia", "SetText",
        }
        for lyr in sorted(layer_nodes.keys()):
            current_y: float = 80.0
            for nid in layer_nodes[lyr]:
                inst = canvas.nodes[nid]
                ndef = _TYPES.get(inst.node_type)
                pin_count = len(ndef.pins) if ndef else 2
                est_h = V_HEADER + pin_count * V_PER_PIN
                if inst.node_type in _WIDGET_NODES:
                    est_h += V_WIDGET_EXTRA
                x = 80 + lyr * H_SPACING
                inst.pos = (float(x), float(current_y))
                current_y += est_h + V_PADDING

        # ── 6b. 纯数据节点 1:1 snap 到消费者 Y ──
        for nid, inst in canvas.nodes.items():
            ndef = _TYPES.get(inst.node_type)
            has_exec = ndef and any(p.kind == "exec" for p in ndef.pins)
            if has_exec:
                continue
            consumers = data_down.get(nid, [])
            if len(consumers) == 1:
                consumer_inst = canvas.nodes.get(consumers[0])
                if consumer_inst:
                    inst.pos = (inst.pos[0], consumer_inst.pos[1])

        print(f"[Rearrange] {len(canvas.nodes)} nodes laid out "
              f"in {len(layer_nodes)} layers")

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
