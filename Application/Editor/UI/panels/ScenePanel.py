from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import (
    BLENDER_ORANGE,
    SUCCESS_GREEN,
    WARNING_AMBER,
    ERROR_RED,
)
from Application.Editor.Services.ControllerRegistry import (
    get_ctrl,
    NAME_SIMULATION,
    NAME_SCENE_BROWSER,
    NAME_VIEWPORT,
    NAME_SELECTION,
)

# ── Font Awesome 6 图标 (imgui_bundle 内置矢量图标方案) ─────
from imgui_bundle import icons_fontawesome_6 as fa


class ScenePanel(BasePanel):
    """场景管理器面板 — 四区域布局:
      1. 场景信息 + 运行控制
      2. 2D / 3D / Overlay 视口模式
      3. Entity 树 (可展开，父子层级)
      4. 选中 Entity 的组件检视
    """

    name = "Scene"
    flags = imgui.WindowFlags_.none

    def __init__(
        self
    ) -> None:
        super().__init__()
        self.visible = True
        # ── 从 ControllerRegistry 获取控制器 ──
        self._sim_ctrl = get_ctrl(NAME_SIMULATION)
        self._browser_ctrl = get_ctrl(NAME_SCENE_BROWSER)
        self._viewport_ctrl = get_ctrl(NAME_VIEWPORT)
        self._selection_ctrl = get_ctrl(NAME_SELECTION)
        # ── Transform 空间模式: True=Local, False=Global ──
        self._transform_local: bool = True

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(
        self
    ) -> None:
        """四区域布局绘制。"""
        # ── 区域 1: 场景信息 + 运行控制 ──
        self._draw_header()
        self._draw_controls()

        # ── 区域 2: 2D / 3D / Overlay 视口模式 ──
        self._draw_viewport_mode()
        imgui.separator()

        # ── 区域 3: Entity 树 (可展开父子层级) ──
        self._draw_entity_tree()

        # ── 区域 4: 选中 Entity 的组件检视 ──
        selected = self._selection_ctrl.get_selected()
        if selected is not None:
            imgui.separator()
            self._draw_entity_summary(selected)

    # ============================================================
    # 区域 1: 场景名 + 运行控制
    # ============================================================

    def _draw_header(
        self
    ) -> None:
        """显示当前场景名称。"""
        imgui.text("Scene: ")
        imgui.same_line()
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00), "default"
        )
        imgui.separator()

    def _draw_controls(
        self
    ) -> None:
        """绘制播放控制按钮组（使用 Font Awesome 6 矢量图标）。"""
        av = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        btn_w = (av - spacing * 2) / 3.0

        # ▶ Run — 绿色
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*SUCCESS_GREEN, 1.00))
        if imgui.button(f"{fa.ICON_FA_PLAY}  Run", (btn_w, 0)):
            self._sim_ctrl.play()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ⏸ Pause — 琥珀色（仅在运行时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*WARNING_AMBER, 1.00))
        imgui.begin_disabled(not self._sim_ctrl.is_running())
        if imgui.button(f"{fa.ICON_FA_PAUSE}  Pause", (btn_w, 0)):
            self._sim_ctrl.pause()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ■ Stop — 红色（仅在未停止时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*ERROR_RED, 1.00))
        imgui.begin_disabled(self._sim_ctrl.is_stopped())
        if imgui.button(f"{fa.ICON_FA_STOP}  Stop", (btn_w, 0)):
            self._sim_ctrl.stop()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        # 状态提示
        imgui.text_disabled(self._sim_ctrl.get_state_label())

        imgui.separator()

    # ============================================================
    # 区域 2: 2D / 3D / Overlay 视口模式
    # ============================================================

    def _draw_viewport_mode(
        self
    ) -> None:
        """绘制 2D | 3D | Overlay 视口模式切换按钮。"""
        av = imgui.get_content_region_avail().x
        btn_w = (av - imgui.get_style().item_spacing.x * 2) / 3.0

        is_2d = self._viewport_ctrl.is_2d()

        # 3D 按钮
        if not is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("3D", (btn_w, 0)):
            self._viewport_ctrl.switch_to_3d()
        if not is_2d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # 2D 按钮
        if is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("2D", (btn_w, 0)):
            self._viewport_ctrl.switch_to_2d()
        if is_2d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # Overlay 按钮 (未来实现)
        imgui.begin_disabled(True)
        imgui.button("Overlay", (btn_w, 0))
        imgui.end_disabled()

    # ============================================================
    # 区域 3: Entity 树 (可展开父子层级, 支持拖拽建立父子关系)
    # ============================================================

    def _draw_entity_tree(
        self
    ) -> None:
        """绘制可展开的 Entity 层级树。拖拽实体到另一实体可建立父子关系。"""
        root_ids = self._browser_ctrl.get_root_entities()
        if not root_ids:
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00), "(empty scene)"
            )
            # 空区域也可以作为 drop target (解除父子关系)
            if imgui.begin_drag_drop_target():
                payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
                if payload is not None:
                    self._browser_ctrl.set_entity_parent(payload.data_id, 0)
                imgui.end_drag_drop_target()
            return

        selected = self._selection_ctrl.get_selected()
        for entity_id in root_ids:
            self._draw_entity_node(entity_id, selected)

        # ── 树底部的空白区域: 拖放到此处解除父子关系 ──
        imgui.dummy(imgui.ImVec2(imgui.get_content_region_avail().x, 20))
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
            if payload is not None:
                self._browser_ctrl.set_entity_parent(payload.data_id, 0)
            imgui.end_drag_drop_target()

    def _draw_entity_node(
        self,
        entity_id: int,
        selected_id: int | None,
    ) -> None:
        """递归绘制单个实体节点及其子节点。支持拖拽重设父子关系。"""
        info = self._browser_ctrl.get_entity_info(entity_id)
        if info is None:
            return
        name = info.get('name', '') or f"Entity #{entity_id}"

        # ── 构建标签: 图标标记 ──
        flags_parts = []
        if info.get('has_camera'):
            flags_parts.append(f"{fa.ICON_FA_CAMERA} ")
        if info.get('has_mesh'):
            flags_parts.append(f"{fa.ICON_FA_CUBE} ")
        flags_str = "".join(flags_parts)

        label = f"{flags_str}{name}##{entity_id}"

        # ── 子节点 ──
        children = self._browser_ctrl.get_entity_children(entity_id)
        has_children = len(children) > 0

        if has_children:
            node_flags = imgui.TreeNodeFlags_.open_on_arrow
            if selected_id == entity_id:
                node_flags |= imgui.TreeNodeFlags_.selected
            opened = imgui.tree_node_ex(label, node_flags)
        else:
            # 叶子节点
            node_flags = imgui.TreeNodeFlags_.leaf | imgui.TreeNodeFlags_.no_tree_push_on_open
            if selected_id == entity_id:
                node_flags |= imgui.TreeNodeFlags_.selected
            opened = imgui.tree_node_ex(label, node_flags)

        # ── 拖拽源: 可以将此实体拖到其他实体上 ──
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("ENTITY", entity_id)
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 1.00), f"Entity #{entity_id}"
            )
            imgui.end_drag_drop_source()

        # ── 拖拽目标: 接受其他实体作为子实体 ──
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
            if payload is not None and payload.data_id != entity_id:
                self._browser_ctrl.set_entity_parent(payload.data_id, entity_id)
            imgui.end_drag_drop_target()

        # ── 点击选中 ──
        if imgui.is_item_clicked():
            self._selection_ctrl.select(entity_id)

        if opened and has_children:
            for child_id in children:
                self._draw_entity_node(child_id, selected_id)
            imgui.tree_pop()
        elif opened:
            # 叶子节点不需要 tree_pop
            pass

    # ============================================================
    # 区域 4: 选中 Entity 的组件检视
    # ============================================================

    def _draw_entity_summary(
        self,
        entity_id: int
    ) -> None:
        """显示选中实体的所有组件（可展开、可编辑）。"""
        use_local = self._transform_local
        summary = self._browser_ctrl.get_summary(entity_id, use_local=use_local)
        if summary is None:
            imgui.text_disabled("(failed to load entity info)")
            return

        # ── 实体名称（可编辑） ──
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00),
            f"Entity #{summary.entity_id}",
        )
        imgui.same_line()
        imgui.text_disabled("—")
        imgui.same_line()
        name_buf = summary.name or ""
        changed, new_name = imgui.input_text(
            "##entity_name", name_buf, 256,
        )
        if changed:
            self._browser_ctrl.set_name(entity_id, new_name)
        if not summary.name:
            imgui.same_line()
            imgui.text_disabled("(click to name)")

        imgui.separator()

        # ── Transform（可展开、可编辑） ──
        if imgui.collapsing_header("Transform", imgui.TreeNodeFlags_.default_open):
            # ── Local / Global 切换 ──
            av = imgui.get_content_region_avail().x
            btn_w = (av - imgui.get_style().item_spacing.x) / 2.0

            if use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Local", (btn_w, 0)):
                self._transform_local = True
            if use_local:
                imgui.pop_style_color(1)
            imgui.same_line()
            if not use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Global", (btn_w, 0)):
                self._transform_local = False
            if not use_local:
                imgui.pop_style_color(1)

            imgui.spacing()

            pos = list(summary.position)
            changed, new_pos = imgui.drag_float3("Position", pos, 0.1, format="%.2f")
            if changed:
                self._browser_ctrl.set_position(entity_id, tuple(new_pos), use_local=use_local)

            rot = list(summary.rotation)
            changed, new_rot = imgui.drag_float3("Rotation", rot, 1.0, format="%.1f")
            if changed:
                self._browser_ctrl.set_rotation(entity_id, tuple(new_rot), use_local=use_local)

            scl = list(summary.scale)
            changed, new_scl = imgui.drag_float3("Scale", scl, 0.05, format="%.2f")
            if changed:
                self._browser_ctrl.set_scale(entity_id, tuple(new_scl), use_local=use_local)

        # ── MeshRenderer（有 mesh 才显示） ──
        if summary.mesh_id is not None:
            if imgui.collapsing_header("MeshRenderer", imgui.TreeNodeFlags_.default_open):
                imgui.text(f"Mesh ID: {summary.mesh_id}")
                if summary.material_id is not None:
                    imgui.text(f"Material ID: {summary.material_id}")
                else:
                    imgui.text_disabled("(no Material)")

        # ── Camera（有 camera 才显示，可编辑） ──
        if summary.has_camera:
            if imgui.collapsing_header("Camera", imgui.TreeNodeFlags_.default_open):
                try:
                    cam = self._browser_ctrl.get_camera_info(entity_id)
                except Exception:
                    cam = None
                if cam:
                    # ── 投影类型 ──
                    is_persp = cam.get('is_perspective', True)
                    changed, new_persp = imgui.checkbox("Perspective", is_persp)
                    if changed:
                        self._browser_ctrl.set_camera_projection(entity_id, new_persp)
                        cam['is_perspective'] = new_persp

                    # ── 透视: FOV / 正交: ortho_size ──
                    if cam.get('is_perspective', True):
                        fov_val = float(cam.get('fov', 45.0))
                        changed, new_fov = imgui.drag_float("FOV", fov_val, 0.5, 1.0, 179.0, "%.1f")
                        if changed:
                            self._browser_ctrl.set_camera_fov(entity_id, new_fov)
                    else:
                        size_val = float(cam.get('ortho_size', 5.0))
                        changed, new_size = imgui.drag_float("Ortho Size", size_val, 0.1, 0.01, 1000.0, "%.2f")
                        if changed:
                            self._browser_ctrl.set_camera_ortho_size(entity_id, new_size)

                    # ── 裁剪平面 ──
                    near_val = float(cam.get('near', 0.1))
                    far_val = float(cam.get('far', 1000.0))
                    changed_n, new_near = imgui.drag_float("Near", near_val, 0.01, 0.001, 1000.0, "%.3f")
                    changed_f, new_far = imgui.drag_float("Far", far_val, 1.0, 0.01, 10000.0, "%.1f")
                    if changed_n:
                        self._browser_ctrl.set_camera_clip(entity_id, new_near, far_val)
                    if changed_f:
                        self._browser_ctrl.set_camera_clip(entity_id, near_val, new_far)

                    if cam.get('is_primary'):
                        imgui.text_colored(imgui.ImVec4(*WARNING_AMBER, 1.00), "(Primary Camera)")
                else:
                    imgui.text_disabled("(camera info unavailable)")
