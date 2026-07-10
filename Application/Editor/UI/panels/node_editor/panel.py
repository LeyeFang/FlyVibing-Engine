"""
节点编辑器 — 画布 Panel。

负责:
  - 节点/连线/交互的渲染
  - Add 弹出菜单
  - Pin 拖拽创建连线
  - Delete 键删除
  - 位置同步
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from imgui_bundle import imgui
from imgui_bundle import imgui_node_editor as node_ed

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import ERROR_RED
from Application.Editor.UI.FileDialog import FileDialog

from Application.Editor.UI.controllers.node_editor import (
    NodeCanvas,
    _TYPES,
    _gen_id,
)
from .styling import (
    _col,
    _apply_ne_style,
    _HDR_COLOR,
    MENU_SECTIONS,
    TEXT_DISABLED,
)


# ═══════════════════════════════════════════════════════════════
# 辅助: combo 弹窗位置修正 (节点编辑器坐标系下 ImGui 自动定位偏移)
# ═══════════════════════════════════════════════════════════════

def _ne_combo(label: str, idx: int, items: list[str]) -> tuple[bool, int]:
    """imgui.combo() 包装 — 修正 node editor 内弹窗位置。"""
    pos = imgui.get_cursor_screen_pos()
    imgui.set_next_window_pos(imgui.ImVec2(pos.x, pos.y + imgui.get_text_line_height_with_spacing()))
    return imgui.combo(label, idx, items)


# ═══════════════════════════════════════════════════════════════
# Add 菜单辅助 (鼠标悬停展开级联子菜单)
# ═══════════════════════════════════════════════════════════════

_SUB_HDR_COLOR = imgui.ImVec4(0.500, 0.500, 0.500, 0.60)


def _draw_add_menu_section(
    title: str,
    items: list,
    canvas: NodeCanvas,
    avail: imgui.ImVec2,
) -> None:
    """在 Add 弹出菜单中绘制一个顶级分类（悬停展开子菜单）。"""
    if imgui.begin_menu(title):
        for item in items:
            _draw_menu_item(item[0], item[1], canvas)
        imgui.end_menu()


def _draw_menu_item(
    label: str,
    target,
    canvas: NodeCanvas,
) -> None:
    """绘制菜单项:
      target 为 list → 子分组标题 + 展平子项
      target 为 str  → 可点击菜单项 (创建节点)
    """
    if isinstance(target, list):
        imgui.spacing()
        imgui.text_colored(_SUB_HDR_COLOR, f"  {label}")
        imgui.separator()
        for sub_label, sub_value in target:
            _draw_menu_item(sub_label, sub_value, canvas)
    else:
        changed, _selected = imgui.menu_item(label, "", False, True)
        if changed:
            max_y = max((inst.pos[1] for inst in canvas.nodes.values()), default=40)
            canvas.add_node(target, (80, max_y + 200))
            imgui.close_current_popup()
            imgui.close_current_popup()


# ═══════════════════════════════════════════════════════════════
# NodeEditorPanel
# ═══════════════════════════════════════════════════════════════

class NodeEditorPanel(BasePanel):
    """节点编辑器画布 — Runtime 生命周期节点编辑"""

    name = "Node Editor"
    flags = imgui.WindowFlags_.none

    _CONFIG_FILE: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "config", "NodeEditor.json",
    )

    _canvas: NodeCanvas | None = None

    def __init__(self) -> None:
        super().__init__()
        self.visible = True
        self._editor_context: node_ed.EditorContext | None = None
        self._editor_initialized: bool = False
        self._canvas_initialized: bool = False
        self._add_popup_pos: imgui.ImVec2 = imgui.ImVec2(0, 0)
        # ── Import / Export 状态 ──
        self._import_path: str = ""
        self._export_path: str = ""
        self._import_error: str = ""
        self._export_error: str = ""
        self._last_io_dir: str = str(Path.home())  # 上次 I/O 目录

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
                "Node Editor not available"
            )
            imgui.text_disabled(
                "Ensure imgui_bundle is compiled with node editor support."
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
        if imgui.small_button("Add Node"):
            rect_min = imgui.get_item_rect_min()
            rect_max = imgui.get_item_rect_max()
            self._add_popup_pos = imgui.ImVec2(rect_min.x, rect_max.y)
            imgui.open_popup("Create Node")

        imgui.same_line()
        if imgui.small_button("Import"):
            self._import_error = ""
            imgui.open_popup("Import Graph")

        imgui.same_line()
        if imgui.small_button("Export"):
            self._export_error = ""
            imgui.open_popup("Export Graph")

        # ── Import 弹出窗口 ──
        self._draw_import_popup(canvas)

        # ── Export 弹出窗口 ──
        self._draw_export_popup(canvas)

        # ── 画布背景色 & 网格 ──
        s = ne.get_style()
        s.set_color_(ne.StyleColor.bg,   _col((0.090, 0.090, 0.090), 1.00))
        s.set_color_(ne.StyleColor.grid, _col((0.180, 0.180, 0.180), 0.50))

        ne.begin("NodeEditor", avail)

        self._draw_nodes(canvas, ne)
        self._draw_links(canvas, ne)
        self._handle_link_creation(canvas, ne)
        self._handle_deletion(canvas, ne)

        # ── 空画布提示 ──
        ne.suspend()
        if not canvas.nodes:
            canvas_pos = imgui.get_cursor_screen_pos()
            imgui.set_cursor_screen_pos((
                canvas_pos.x + avail.x / 2 - 80,
                canvas_pos.y + avail.y / 2 - 10,
            ))
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00),
                'Click "Add" button to create nodes',
            )
        ne.resume()
        ne.end()

        self._draw_add_popup(canvas, avail)
        self._sync_positions(canvas, ne)

    # ============================================================
    # Scene 管理
    # ============================================================

    @staticmethod
    def _ensure_default_scene() -> None:
        """确保 EditorHost 的活跃 Scene 始终与 ECS 世界同步。"""
        from Application.Editor.EditorHost import EditorHost
        from Application.Core.Scene.Scene import Scene
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer
        import esper, copy

        # ★ 显式切到 EditorHost 的 ECS 世界（避免主线程被 GameRuntime 绑定覆盖）
        try:
            ed_st = SceneManager._state_for("EditorHost")
            esper.switch_world(ed_st.world_name)
        except Exception as e:
            print(f"[NodeEditor] _ensure_default_scene: EditorHost not ready ({e})")
            return

        scene = EditorHost.get_active_scene()
        if scene is None:
            scene = Scene("Default", game_type=SceneManager.GetGameType())
            EditorHost.set_active_scene(scene)

        _sys_ids = {SceneManager.get_main_camera_id(), SceneManager.get_main_camera_2d_id()}
        scene.entities.clear()
        count = 0
        for eid, (xform,) in esper.get_components(Transform):
            if eid in _sys_ids:
                continue
            name = SceneManager.GetEntityName(eid) or f"Entity_{eid}"
            comps = {"Transform": copy.deepcopy(xform)}
            try:
                cam = esper.component_for_entity(eid, Camera)
                comps["Camera"] = copy.deepcopy(cam)
            except Exception:
                pass
            try:
                mr = esper.component_for_entity(eid, MeshRenderer)
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
                "Scene: (none)",
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
            "Scene:",
        )
        imgui.same_line()

        # ── Combo: 场景名 + GameType 后缀 ──
        display_labels = [f"{n}  ({SceneManager.GetGameType().value.upper()})" for n in scene_names]
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

    def _draw_nodes(self, canvas: NodeCanvas, ne) -> None:
        for nid, inst in list(canvas.nodes.items()):
            nd = _TYPES.get(inst.node_type)
            if nd is None:
                continue

            ne.set_node_position(
                ne.NodeId(nid),
                imgui.ImVec2(inst.pos[0], inst.pos[1]),
            )
            ne.begin_node(ne.NodeId(nid))
            _apply_ne_style(nd.accent_color)

            # 标题栏
            imgui.push_style_color(imgui.Col_.text, _col(nd.accent_color, 1.00))
            imgui.text(nd.label)
            imgui.pop_style_color(1)

            # 属性文字
            if nd.props_text:
                imgui.dummy(imgui.ImVec2(0, 2))
                imgui.push_style_color(imgui.Col_.text, _col(TEXT_DISABLED))
                for line in nd.props_text.split("\n"):
                    imgui.text(f"  {line}")
                imgui.pop_style_color(1)
                imgui.dummy(imgui.ImVec2(0, 2))

            # PrintString 文本框
            if inst.node_type == "PrintString":
                imgui.dummy(imgui.ImVec2(0, 2))
                imgui.push_item_width(110)
                msg = inst.props.get("message", "")
                changed, new_msg = imgui.input_text(
                    f"##print_msg_{nid}", msg,
                )
                if changed:
                    inst.props["message"] = new_msg
                imgui.pop_item_width()
                imgui.dummy(imgui.ImVec2(0, 2))

            # Random 节点 UI 控件
            if inst.node_type == "Random":
                self._draw_random_widgets(nid, inst)

            # ScalarMath 节点 UI 控件
            if inst.node_type == "ScalarMath":
                self._draw_scalar_math_widgets(nid, inst)

            # Compare 节点 UI 控件
            if inst.node_type == "Compare":
                self._draw_compare_widgets(nid, inst)

            # TimeTrigger 节点 UI 控件
            if inst.node_type == "TimeTrigger":
                self._draw_time_trigger_widgets(nid, inst)

            # VarSet 节点 UI 控件
            if inst.node_type == "VarSet":
                self._draw_var_set_widgets(nid, inst)

            # VarGet 节点 UI 控件
            if inst.node_type == "VarGet":
                self._draw_var_get_widgets(nid, inst)

            # Constant 节点 UI 控件
            if inst.node_type == "Constant":
                self._draw_constant_widgets(nid, inst)

            # EntitySpawn 节点 UI 控件
            if inst.node_type == "EntitySpawn":
                self._draw_entity_spawn_widgets(nid, inst)

            # CameraConfigure 节点 UI 控件
            if inst.node_type == "CameraConfigure":
                self._draw_camera_configure_widgets(nid, inst)

            # ComponentAdd / ComponentRemove / ComponentSetProperty UI 控件
            if inst.node_type in ("ComponentAdd", "ComponentRemove"):
                self._draw_component_select_widgets(nid, inst)
            if inst.node_type == "ComponentSetProperty":
                self._draw_component_set_property_widgets(nid, inst)

            # VecMath 节点 UI 控件
            if inst.node_type == "VecMath":
                self._draw_vec_math_widgets(nid, inst)

            self._draw_pins(canvas, ne, nid, inst, nd)
            ne.end_node()

    # ── Random 节点专用控件 ────────────────────────────────

    def _draw_random_widgets(self, nid: int, inst) -> None:
        """在 Random 节点体内绘制分布选择、模式切换、种子和参数输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(105)

        # ── 分布下拉 ──
        dist = inst.props.get("distribution", "uniform")
        dist_labels = ["Uniform", "Gaussian"]
        dist_idx = 0 if dist == "uniform" else 1
        changed, new_idx = _ne_combo(
            f"##rand_dist_{nid}", dist_idx, dist_labels,
        )
        if changed:
            inst.props["distribution"] = "uniform" if new_idx == 0 else "gaussian"

        # ── 模式切换 ──
        mode = inst.props.get("mode", "manual")
        if imgui.radio_button(f"Manual##rand_mode_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(f"Pin##rand_mode_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        # ── 种子 ──
        seed = inst.props.get("seed", 0)
        changed, new_seed = imgui.input_int(f"Seed##rand_seed_{nid}", seed)
        if changed:
            inst.props["seed"] = new_seed

        # ── Manual 模式参数输入 ──
        if mode == "manual":
            if dist == "uniform":
                v = inst.props.get("min", 0.0)
                changed, nv = imgui.input_float(f"Min##rand_min_{nid}", v)
                if changed:
                    inst.props["min"] = nv
                v = inst.props.get("max", 1.0)
                changed, nv = imgui.input_float(f"Max##rand_max_{nid}", v)
                if changed:
                    inst.props["max"] = nv
            else:
                v = inst.props.get("mean", 0.0)
                changed, nv = imgui.input_float(f"Mean##rand_mean_{nid}", v)
                if changed:
                    inst.props["mean"] = nv
                v = inst.props.get("stddev", 1.0)
                changed, nv = imgui.input_float(f"StdDev##rand_std_{nid}", v)
                if changed:
                    inst.props["stddev"] = nv

        imgui.pop_item_width()

    # ── ScalarMath 节点专用控件 ────────────────────────────

    def _draw_scalar_math_widgets(self, nid: int, inst) -> None:
        """在 ScalarMath 节点体内绘制操作下拉框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(100)

        op = inst.props.get("operation", "sum")
        ops = ["Sum", "Subtract", "Multiply", "Divide"]
        try:
            idx = next(i for i, o in enumerate(ops) if o.lower() == op)
        except StopIteration:
            idx = 0
        changed, new_idx = _ne_combo(
            f"##scalar_op_{nid}", idx, ops,
        )
        if changed:
            inst.props["operation"] = ops[new_idx].lower()

        imgui.same_line()
        imgui.text_disabled("Op")
        imgui.pop_item_width()

    # ── Compare 节点专用控件 ───────────────────────────────

    def _draw_compare_widgets(self, nid: int, inst) -> None:
        """在 Compare 节点体内绘制比较运算符下拉框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(80)

        op = inst.props.get("operation", "gt")
        labels = [">", "<", "==", "!=", ">=", "<="]
        keys = ["gt", "lt", "eq", "neq", "gte", "lte"]
        try:
            idx = keys.index(op)
        except ValueError:
            idx = 0
        changed, new_idx = _ne_combo(f"##cmp_op_{nid}", idx, labels)
        if changed:
            inst.props["operation"] = keys[new_idx]

        imgui.same_line()
        imgui.text_disabled("Op")
        imgui.pop_item_width()

    # ── TimeTrigger 节点专用控件 ───────────────────────────

    def _draw_time_trigger_widgets(self, nid: int, inst) -> None:
        """在 TimeTrigger 节点体内绘制模式切换和时间输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(90)

        mode = inst.props.get("mode", "manual")
        if imgui.radio_button(f"Manual##tt_mode_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(f"Pin##tt_mode_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        if mode == "manual":
            v = inst.props.get("time", 0.0)
            changed, nv = imgui.input_float(f"Time (s)##tt_time_{nid}", v, format="%.2f")
            if changed:
                inst.props["time"] = nv

        imgui.pop_item_width()

    # ── 变量名辅助 ────────────────────────────────────────

    def _collect_var_names(self, exclude_nid: int | None = None) -> list[str]:
        """收集画布上所有 VarSet/VarGet 已使用的变量名，去重排序。"""
        names: set[str] = set()
        for nid, inst in self._canvas.nodes.items():
            if nid == exclude_nid:
                continue
            if inst.node_type in ("VarSet", "VarGet"):
                n = inst.props.get("var_name", "")
                if n:
                    names.add(n)
        return sorted(names)

    def _draw_var_name_combo(self, label: str, nid: int, inst) -> None:
        """绘制变量名选择下拉框：已有名称列表 + 可自定义输入。"""
        existing = self._collect_var_names(nid)
        current = inst.props.get("var_name", "")

        # 构建选项列表: 已有名称在前，"Custom..." 在最后
        items = existing + ["+ New..."]
        try:
            idx = existing.index(current)
        except ValueError:
            idx = len(existing)  # "Custom..." 位置

        changed, new_idx = _ne_combo(f"##var_{label}_{nid}", idx, items)
        if changed:
            if new_idx < len(existing):
                inst.props["var_name"] = existing[new_idx]
            else:
                # 选 "+ New..." → 保持当前文本，下面用 input_text 编辑
                pass

        # 自定义输入（当选中 "Custom..." 或名称不在列表中时）
        if idx >= len(existing) or not existing:
            imgui.push_item_width(90)
            changed, txt = imgui.input_text(
                f"##var_{label}_txt_{nid}", current,
            )
            if changed:
                inst.props["var_name"] = txt
            imgui.pop_item_width()

    # ── VarSet 节点专用控件 ────────────────────────────────

    def _draw_var_set_widgets(self, nid: int, inst) -> None:
        """在 VarSet 节点体内绘制变量名、模式切换和值输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(90)

        # 变量名（下拉+自定义）
        self._draw_var_name_combo("vs", nid, inst)

        mode = inst.props.get("mode", "manual")
        if imgui.radio_button(f"Manual##vs_mode_man_{nid}", mode == "manual"):
            inst.props["mode"] = "manual"
        imgui.same_line()
        if imgui.radio_button(f"Pin##vs_mode_pin_{nid}", mode == "pin"):
            inst.props["mode"] = "pin"

        if mode == "manual":
            v = inst.props.get("value", 0.0)
            changed, nv = imgui.input_float(f"Value##vs_val_{nid}", v, format="%.4f")
            if changed:
                inst.props["value"] = nv

        imgui.pop_item_width()

    # ── VarGet 节点专用控件 ────────────────────────────────

    def _draw_var_get_widgets(self, nid: int, inst) -> None:
        """在 VarGet 节点体内绘制变量名输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(90)

        # 变量名（下拉+自定义）
        self._draw_var_name_combo("vg", nid, inst)

        imgui.pop_item_width()

    # ── Constant 节点专用控件 ──────────────────────────────

    def _draw_constant_widgets(self, nid: int, inst) -> None:
        """在 Constant 节点体内绘制值输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(90)
        v = inst.props.get("value", 0.0)
        changed, nv = imgui.input_float(f"Value##const_val_{nid}", v, format="%.4f")
        if changed:
            inst.props["value"] = nv
        imgui.pop_item_width()

    # ── EntitySpawn 节点专用控件 ───────────────────────────

    def _draw_entity_spawn_widgets(self, nid: int, inst) -> None:
        """在 EntitySpawn 节点体内绘制 Template 下拉框。

        Template 列表来自 Scene.entities 注册表中的实体定义名称。
        若 Scene 不可用则回退到内置占位列表。
        """
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(120)

        template = inst.props.get("template", "")

        # ── 从 Scene.entities 获取可用模板名 ──
        labels = self._get_scene_template_names()
        if not labels:
            labels = ["(no scene)"]

        try:
            idx = labels.index(template) if template in labels else 0
        except ValueError:
            idx = 0

        changed, new_idx = _ne_combo(
            f"##spawn_tpl_{nid}", idx, labels,
        )
        if changed:
            inst.props["template"] = labels[new_idx]

        imgui.same_line()
        imgui.text_disabled("Template")
        imgui.pop_item_width()

    @staticmethod
    def _get_scene_template_names() -> list[str]:
        """从 EditorHost 获取当前 Scene 的实体模板名列表。

        Scene 由 _ensure_default_scene() 饥渴创建，此处不再含 fallback。
        """
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is None:
            return []
        return scene.get_entity_names()

    # ── CameraConfigure 节点专用控件 ────────────────────────

    def _draw_camera_configure_widgets(self, nid: int, inst) -> None:
        """在 CameraConfigure 节点体内绘制投影类型下拉框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(130)

        proj = inst.props.get("projection", "perspective")
        labels = ["Perspective", "Orthographic"]
        try:
            idx = 0 if proj == "perspective" else 1
        except (ValueError, IndexError):
            idx = 0
        changed, new_idx = _ne_combo(
            f"##cam_proj_{nid}", idx, labels,
        )
        if changed:
            inst.props["projection"] = "perspective" if new_idx == 0 else "orthographic"

        imgui.same_line()
        imgui.text_disabled("Projection")
        imgui.pop_item_width()

    # ── Component 节点通用控件 ─────────────────────────────

    @staticmethod
    def _get_component_type_names() -> list[str]:
        """获取已注册的组件类型名列表（排除 Transform — 每个实体自带）。"""
        try:
            from Application.Core.Scene.SceneManager import SceneManager
            reg = SceneManager.GetRegisteredComponents()
            return sorted([n for n in reg if n != "Transform"], key=lambda n: n.lower())
        except Exception:
            return ["Camera", "MeshRenderer"]

    def _draw_component_select_widgets(self, nid: int, inst) -> None:
        """ComponentAdd / ComponentRemove: 组件类型下拉选择。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(130)

        comp_name = inst.props.get("component", "")
        labels = self._get_component_type_names()
        if not labels:
            labels = ["(none)"]
        try:
            idx = labels.index(comp_name) if comp_name in labels else 0
        except ValueError:
            idx = 0

        changed, new_idx = _ne_combo(f"##comp_type_{nid}", idx, labels)
        if changed:
            inst.props["component"] = labels[new_idx]

        imgui.same_line()
        imgui.text_disabled("Type")
        imgui.pop_item_width()

    def _draw_component_set_property_widgets(self, nid: int, inst) -> None:
        """ComponentSetProperty: 组件类型下拉 + 属性名输入框。"""
        imgui.dummy(imgui.ImVec2(0, 2))

        # ── 组件类型 ──
        imgui.push_item_width(130)
        comp_name = inst.props.get("component", "")
        labels = self._get_component_type_names()
        if not labels:
            labels = ["(none)"]
        try:
            idx = labels.index(comp_name) if comp_name in labels else 0
        except ValueError:
            idx = 0
        changed, new_idx = _ne_combo(f"##csp_comp_{nid}", idx, labels)
        if changed:
            inst.props["component"] = labels[new_idx]
        imgui.same_line()
        imgui.text_disabled("Comp")
        imgui.pop_item_width()

        # ── 属性名 ──
        imgui.push_item_width(130)
        prop = inst.props.get("property", "")
        changed, new_prop = imgui.input_text(f"##csp_prop_{nid}", prop, 64)
        if changed:
            inst.props["property"] = new_prop
        imgui.same_line()
        imgui.text_disabled("Prop")
        imgui.pop_item_width()

    # ── VecMath 节点专用控件 ───────────────────────────────

    def _draw_vec_math_widgets(self, nid: int, inst) -> None:
        """在 VecMath 节点体内绘制操作下拉框。"""
        imgui.dummy(imgui.ImVec2(0, 2))
        imgui.push_item_width(105)

        op = inst.props.get("operation", "add")
        ops = ["Add", "Subtract", "Multiply", "Divide",
               "Dot", "Cross", "Normalize", "Length"]
        try:
            idx = ops.index(op.capitalize()) if op.capitalize() in ops else ops.index(
                next(o for o in ops if o.lower() == op))
        except (ValueError, StopIteration):
            idx = 0
        changed, new_idx = _ne_combo(
            f"##vec_op_{nid}", idx, ops,
        )
        if changed:
            inst.props["operation"] = ops[new_idx].lower()

        imgui.same_line()
        imgui.text_disabled("Op")
        imgui.pop_item_width()

    # ── 可见引脚过滤 ───────────────────────────────────────

    @staticmethod
    def _visible_pins(inst, nd, canvas=None) -> list:
        """返回当前模式下应显示的引脚列表。"""
        # ── VarSet: Manual 模式隐藏 Value/Name pin ──
        if inst.node_type == "VarSet":
            mode = inst.props.get("mode", "manual")
            return [p for p in nd.pins
                    if p.name not in ("Name",)  # Name 用文本框
                    and not (p.name == "Value" and mode == "manual")]
        # ── VarGet: 隐藏 Name pin ──
        if inst.node_type == "VarGet":
            return [p for p in nd.pins if p.name != "Name"]
        # ── VecMath: 一元操作隐藏 B pin ──
        if inst.node_type == "VecMath":
            op = inst.props.get("operation", "add")
            if op in ("normalize", "length"):
                return [p for p in nd.pins if p.name != "B"]
        # ── CameraConfigure: 按投影类型过滤 FOV / OrthoSize pin ──
        if inst.node_type == "CameraConfigure":
            proj = inst.props.get("projection", "perspective")
            if proj == "perspective":
                return [p for p in nd.pins if p.name != "OrthoSize"]
            else:
                return [p for p in nd.pins if p.name != "FOV"]
        # ── ScalarMath: 自增输入 pin（有连线才显示） ──
        if inst.node_type == "ScalarMath":
            if canvas is not None:
                max_connected = -1
                for i in range(8):
                    pin_name = f"In_{i}"
                    pid = inst.pin_ids.get(pin_name)
                    if pid is not None:
                        if any(lk.to_pin == pid for lk in canvas.links.values()):
                            max_connected = i
                show_up_to = max(max_connected + 2, 2)  # 至少 2 个
                visible = []
                for p in nd.pins:
                    if p.name.startswith("In_"):
                        idx = int(p.name.split("_")[1])
                        if idx < show_up_to:
                            visible.append(p)
                    else:
                        visible.append(p)
                return visible
        # ── Random: 按模式/分布过滤 ──
        if inst.node_type == "Random":
            mode = inst.props.get("mode", "manual")
            dist = inst.props.get("distribution", "uniform")
            visible = []
            for p in nd.pins:
                if p.name == "Result":
                    visible.append(p)
                elif mode == "pin":
                    if dist == "uniform" and p.name in ("Min", "Max"):
                        visible.append(p)
                    elif dist == "gaussian" and p.name in ("Mean", "StdDev"):
                        visible.append(p)
            return visible

        # ── TimeTrigger: 动态 exec_out 引脚 ──
        if inst.node_type == "TimeTrigger":
            mode = inst.props.get("mode", "manual")
            visible = []

            # 静态引脚
            for p in nd.pins:
                if p.name == "exec_in":
                    visible.append(p)
                elif p.name == "Elapsed":
                    visible.append(p)
                elif p.name == "Time" and mode == "pin":
                    visible.append(p)

            # 动态 exec_out: 有连线的全显示 + 一个空余
            if canvas is not None:
                max_connected = -1
                for i in range(8):
                    pin_name = f"out_{i}"
                    pin_id = inst.pin_ids.get(pin_name)
                    if pin_id is not None:
                        has_link = any(
                            lk.from_pin == pin_id
                            for lk in canvas.links.values()
                        )
                        if has_link:
                            max_connected = i
                show_up_to = max(max_connected + 2, 1)  # 至少显示 1 个
                for p in nd.pins:
                    if p.name.startswith("out_"):
                        idx = int(p.name.split("_")[1])
                        if idx < show_up_to:
                            visible.append(p)
            else:
                # 无 canvas 引用时显示 1 个
                for p in nd.pins:
                    if p.name == "out_0":
                        visible.append(p)
                        break
            return visible

        return list(nd.pins)

    def _draw_pins(self, canvas: NodeCanvas, ne, nid: int, inst, nd) -> None:
        """绘制节点的所有引脚 + 分隔线。"""
        pins = self._visible_pins(inst, nd, canvas)

        # ── 第 1 步: 计算节点宽度（基于标题 + 所有 pin 原始文字） ──
        _title_w = imgui.calc_text_size(f"  {nd.label}  ").x
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
            pin_id = inst.pin_ids[pin.name]
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
            ne.link(
                ne.LinkId(lk.id),
                ne.PinId(lk.from_pin),
                ne.PinId(lk.to_pin),
                _col((0.7, 0.7, 0.7, 0.7)),
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
            for sn in _sel_nodes:
                nid = sn.id()
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
        if not imgui.begin_popup_modal("Import Graph", None, imgui.WindowFlags_.always_auto_resize)[0]:
            return

        imgui.text("Import node graph from JSON file:")
        imgui.spacing()

        # ── 文件路径输入 ──
        imgui.push_item_width(400)
        changed, self._import_path = imgui.input_text(
            "##import_path", self._import_path,
        )
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.small_button("Browse##import"):
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

        imgui.spacing()

        # ── Import / Cancel ──
        if imgui.button("Import", imgui.ImVec2(100, 0)):
            self._do_import(canvas)

        imgui.same_line()
        if imgui.button("Cancel", imgui.ImVec2(100, 0)):
            self._import_path = ""
            self._import_error = ""
            imgui.close_current_popup()

        imgui.end_popup()

    def _draw_export_popup(self, canvas: NodeCanvas) -> None:
        """绘制 Export Graph 弹出窗口。"""
        if not imgui.begin_popup_modal("Export Graph", None, imgui.WindowFlags_.always_auto_resize)[0]:
            return

        imgui.text("Export node graph to JSON file:")
        imgui.spacing()

        # ── 文件路径输入 ──
        imgui.push_item_width(400)
        changed, self._export_path = imgui.input_text(
            "##export_path", self._export_path,
        )
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.small_button("Browse##export"):
            FileDialog.save_json(
                callback=lambda p: setattr(self, '_export_path', p),
                start_dir=self._last_io_dir,
            )

        imgui.spacing()

        # ── 节点/连线统计 ──
        n_count = len(canvas.nodes)
        l_count = len(canvas.links)
        imgui.text_disabled(f"  {n_count} nodes, {l_count} links")

        imgui.spacing()

        # ── 错误提示 ──
        if self._export_error:
            imgui.text_colored(
                imgui.ImVec4(*ERROR_RED, 1.00),
                self._export_error,
            )

        imgui.spacing()

        # ── Export / Cancel ──
        if imgui.button("Export", imgui.ImVec2(100, 0)):
            self._do_export(canvas)

        imgui.same_line()
        if imgui.button("Cancel", imgui.ImVec2(100, 0)):
            self._export_path = ""
            self._export_error = ""
            imgui.close_current_popup()

        imgui.end_popup()

    def _do_import(self, canvas: NodeCanvas) -> None:
        """执行导入：从 JSON 文件加载节点图。"""
        fp = self._import_path.strip()
        if not fp:
            self._import_error = "Please select a file."
            return

        if not os.path.isfile(fp):
            self._import_error = f"File not found:\n{fp}"
            return

        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            self._import_error = f"Invalid JSON:\n{e}"
            return
        except Exception as e:
            self._import_error = f"Failed to read file:\n{e}"
            return

        if "nodes" not in data:
            self._import_error = "Not a valid node graph file (missing 'nodes')."
            return

        try:
            new_canvas = NodeCanvas.from_dict(data)
        except Exception as e:
            self._import_error = f"Failed to parse graph:\n{e}"
            return

        # ── 替换画布内容 ──
        canvas.clear()
        for nid, inst in new_canvas.nodes.items():
            canvas._nodes[nid] = inst
        for lid, lk in new_canvas.links.items():
            canvas._links[lid] = lk

        self._last_io_dir = os.path.dirname(fp)
        print(f"[Import] Loaded {len(canvas.nodes)} nodes, {len(canvas.links)} links from {fp}")
        self._import_path = ""
        self._import_error = ""
        imgui.close_current_popup()

    def _do_export(self, canvas: NodeCanvas) -> None:
        """执行导出：将节点图保存为 JSON 文件。"""
        fp = self._export_path.strip()
        if not fp:
            self._export_error = "Please specify a file path."
            return

        # 自动补 .json
        if not fp.lower().endswith(".json"):
            fp += ".json"

        try:
            os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
            data = canvas.to_dict()
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._export_error = f"Failed to write file:\n{e}"
            return

        self._last_io_dir = os.path.dirname(fp)
        print(f"[Export] Saved {len(canvas.nodes)} nodes, {len(canvas.links)} links to {fp}")
        self._export_path = ""
        self._export_error = ""
        imgui.close_current_popup()

    # ============================================================
    # 子步骤: Import / Export 弹出窗口（END）
    # ============================================================

    def _draw_add_popup(self, canvas: NodeCanvas, avail) -> None:
        imgui.set_next_window_pos(self._add_popup_pos)
        _bpop = imgui.begin_popup("Create Node")
        if _bpop:
            for title, items in MENU_SECTIONS:
                _draw_add_menu_section(title, items, canvas, avail)
            imgui.end_popup()

    # ============================================================
    # 子步骤: 位置同步
    # ============================================================

    def _sync_positions(self, canvas: NodeCanvas, ne) -> None:
        for nid in list(canvas.nodes.keys()):
            np = ne.get_node_position(ne.NodeId(nid))
            inst = canvas.nodes[nid]
            if -1e6 < np.x < 1e6 and -1e6 < np.y < 1e6:
                if (np.x, np.y) != inst.pos:
                    inst.pos = (np.x, np.y)
