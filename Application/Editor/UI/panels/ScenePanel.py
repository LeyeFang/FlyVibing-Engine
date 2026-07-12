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
    NAME_RESOURCE_BROWSER,
    NAME_VIEWPORT,
    NAME_SELECTION,
)

# ── Font Awesome 6 图标 (imgui_bundle 内置矢量图标方案) ─────
from imgui_bundle import icons_fontawesome_6 as fa

from Application.Editor.UI.FileDialog import FileDialog


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
        self._resource_ctrl = get_ctrl(NAME_RESOURCE_BROWSER)
        self._viewport_ctrl = get_ctrl(NAME_VIEWPORT)
        self._selection_ctrl = get_ctrl(NAME_SELECTION)
        # ── Transform 空间模式: True=Local, False=Global ──
        self._transform_local: bool = False  # 默认 Global
        # ── 新建场景输入缓冲 ──
        self._new_scene_name: str = ""

    # ============================================================
    # Material I/O 回调
    # ============================================================

    @staticmethod
    def _on_mat_save(entity_id: int, file_path: str) -> None:
        """FileDialog 回调: 保存 material 到 .mat 文件。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
        if file_path:
            SceneBrowserController.save_material_to_file(entity_id, file_path)

    @staticmethod
    def _on_mat_load(entity_id: int, file_path: str) -> None:
        """FileDialog 回调: 从 .mat 文件加载 material。"""
        from Application.Editor.UI.controllers.SceneBrowserController import SceneBrowserController
        if file_path:
            SceneBrowserController.load_material_from_file(entity_id, file_path)

    # ============================================================
    # Scene I/O 回调
    # ============================================================

    def _on_save_scene(self) -> None:
        """打开保存场景对话框 → 选择路径 → 执行保存。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        default_name = f"{scene.name}.scene" if scene else "Untitled.scene"
        FileDialog.save_scene(
            callback=lambda p: self._do_save_scene(p),
            default_name=default_name,
        )

    @staticmethod
    def _do_save_scene(path: str) -> None:
        """执行场景保存到 .scene 文件。"""
        if not path:
            return
        from Application.Editor.EditorHost import EditorHost
        ok = EditorHost.save_active_scene_to_file(path)
        if ok:
            print(f"[ScenePanel] Scene saved to: {path}")
        else:
            print(f"[ScenePanel] ERROR: Failed to save scene to: {path}")

    def _on_load_scene(self) -> None:
        """打开加载场景对话框 → 选择文件 → 执行加载。"""
        FileDialog.open_scene(
            callback=lambda p: self._do_load_scene(p),
        )

    @staticmethod
    def _do_load_scene(path: str) -> None:
        """执行从 .scene 文件加载场景。"""
        if not path:
            return
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.load_scene_from_file(path)
        if scene is not None:
            print(f"[ScenePanel] Scene loaded from: {path}")
            print(f"  Name: {scene.name}")
            print(f"  Entities: {len(scene.entities)}")
            print(f"  Node Graph: {'present' if scene.node_graph else 'none'}")
        else:
            print(f"[ScenePanel] ERROR: Failed to load scene from: {path}")

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(
        self
    ) -> None:
        """四区域布局 — 橙色标题 + separator 分隔，区域内无线条。"""
        # ── 区域 1: Scene Information ──
        self._draw_section_title("Scene Information")
        self._draw_header()
        self._draw_controls()

        # ── 区域 2: Scene Type ──
        imgui.spacing()
        imgui.separator()
        self._draw_section_title("Scene Type")
        self._draw_viewport_mode()

        # ── 区域 3: Entities ──
        imgui.spacing()
        imgui.separator()
        self._draw_section_title("Entities")
        self._draw_entity_tree()

        # ── 区域 4: Inspector (含实体名) ──
        selected = self._selection_ctrl.get_selected()
        if selected is not None:
            info = self._browser_ctrl.get_entity_info(selected)
            entity_name = (info.get('name', '') if info else '') or f"Entity #{selected}"
            imgui.spacing()
            imgui.separator()
            self._draw_section_title(f"Inspector  —  \"{entity_name}\"")
            self._draw_entity_summary(selected)

    # ============================================================
    # 区域 1: 场景名 + 运行控制
    # ============================================================

    def _draw_header(
        self
    ) -> None:
        """场景下拉选择器 — Scene: [▼列表] [+] [💾保存] [📂加载]。"""
        scene_names = self._browser_ctrl.get_scene_names()
        current_name = self._browser_ctrl.get_active_scene_name()

        imgui.text("Scene:")
        imgui.same_line()
        # 为 [+] [💾] [📂] 三个按钮预留宽度
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 120)
        if imgui.begin_combo("##scene_select", current_name):
            for sname in scene_names:
                is_sel = (sname == current_name)
                if imgui.selectable(sname, is_sel)[0]:
                    self._browser_ctrl.switch_scene(sname)
                if is_sel:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_PLUS}##new_scene_btn"):
            imgui.open_popup("new_scene_popup")

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_FLOPPY_DISK}##save_scene_btn"):
            self._on_save_scene()

        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_FOLDER_OPEN}##load_scene_btn"):
            self._on_load_scene()

        if imgui.begin_popup("new_scene_popup"):
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 0.90), "New Scene")
            imgui.spacing()
            imgui.push_item_width(180)
            changed, self._new_scene_name = imgui.input_text_with_hint(
                "##new_scene_input", "name...", self._new_scene_name, 64,
            )
            imgui.pop_item_width()
            imgui.same_line()
            name_ok = bool(self._new_scene_name.strip()) and (
                self._new_scene_name.strip() not in scene_names
            )
            if not name_ok:
                imgui.begin_disabled(True)
            if imgui.button("Create") or (
                name_ok and imgui.is_key_pressed(imgui.Key.enter)
            ):
                name = self._new_scene_name.strip()
                self._browser_ctrl.create_scene(name)
                self._new_scene_name = ""
                imgui.close_current_popup()
            if not name_ok:
                imgui.end_disabled()
            imgui.end_popup()

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

    # ============================================================
    # 通用: 区域标题
    # ============================================================

    @staticmethod
    def _draw_section_title(title: str) -> None:
        """统一的区域标题 — 橙色文字，上下留白。"""
        imgui.spacing()
        imgui.spacing()
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00), title)
        imgui.spacing()

    # ============================================================
    # 区域 2: Scene Type (GameType + 视口模式联动)
    # ============================================================

    def _draw_viewport_mode(
        self
    ) -> None:
        """绘制 Scene Type 切换按钮 — 同时控制 Scene.game_type 和编辑器视口模式。

        点击 2D / 3D 会:
          1. 更新 SceneManager.game_type → 切换默认活跃摄像机
          2. 更新 ViewportController → 切换 EditorCamera 正交/透视
        """
        av = imgui.get_content_region_avail().x
        btn_w = (av - imgui.get_style().item_spacing.x * 2) / 3.0

        # ── 从 SceneManager 读取当前 game_type 作为信源 ──
        current_gt = self._browser_ctrl.get_game_type()
        is_3d = (current_gt == "3d")
        is_2d = (current_gt == "2d")

        # ── 3D 按钮 ──
        if is_3d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("3D", (btn_w, 0)):
            self._browser_ctrl.set_game_type("3d")
            self._viewport_ctrl.switch_to_3d()
        if is_3d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # ── 2D 按钮 ──
        if is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("2D", (btn_w, 0)):
            self._browser_ctrl.set_game_type("2d")
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
        """绘制 Entity 层级树 + 工具栏按钮。"""
        # ── 工具栏: Add / Delete ──
        self._draw_entity_toolbar()
        imgui.spacing()

        root_ids = self._browser_ctrl.get_root_entities()
        if not root_ids:
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00), "(empty scene)"
            )
            if imgui.begin_drag_drop_target():
                payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
                if payload is not None:
                    self._browser_ctrl.set_entity_parent(payload.data_id, 0)
                imgui.end_drag_drop_target()
            return

        selected = self._selection_ctrl.get_selected()
        for entity_id in root_ids:
            self._draw_entity_node(entity_id, selected)

        # ── 树底部空白: 拖放到此处解除父子关系 / 点击空白取消选中 ──
        imgui.dummy(imgui.ImVec2(imgui.get_content_region_avail().x, 20))
        if imgui.is_item_clicked():
            self._selection_ctrl.clear()
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("ENTITY")
            if payload is not None:
                self._browser_ctrl.set_entity_parent(payload.data_id, 0)
            imgui.end_drag_drop_target()

    def _draw_entity_toolbar(self) -> None:
        """绘制实体工具栏: Add Entity / Delete。"""
        av = imgui.get_content_region_avail().x
        spacing = imgui.get_style().item_spacing.x
        btn_w = (av - spacing) / 2.0

        # ➕ Add Entity
        if imgui.button(f"{fa.ICON_FA_PLUS}  Add Entity", (btn_w, 0)):
            self._browser_ctrl.add_entity()
        imgui.same_line()

        # 🗑 Delete — 仅选中时可用
        selected = self._selection_ctrl.get_selected()
        if selected is None:
            imgui.begin_disabled(True)
        if imgui.button(f"{fa.ICON_FA_TRASH}  Delete", (btn_w, 0)):
            self._browser_ctrl.delete_selected()
            self._selection_ctrl.clear()
        if selected is None:
            imgui.end_disabled()

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

        # ── 眼图标: 在 entity label 左侧 ──
        eye_visible = self._browser_ctrl.is_editor_visible(entity_id)
        eye_icon = fa.ICON_FA_EYE if eye_visible else fa.ICON_FA_EYE_SLASH
        if not eye_visible:
            imgui.push_style_color(imgui.Col_.text, imgui.ImVec4(0.35, 0.35, 0.35, 1.00))
        if imgui.small_button(f"{eye_icon}##eye_{entity_id}"):
            self._browser_ctrl.set_editor_visible(entity_id, not eye_visible)
        if not eye_visible:
            imgui.pop_style_color(1)
        if imgui.is_item_hovered():
            imgui.set_tooltip(f"Toggle editor visibility of '{name}'")
        imgui.same_line()

        # ── 构建标签: 图标标记 ──
        flags_parts = [f"{fa.ICON_FA_CUBE} "]
        if info.get('has_camera'):
            flags_parts.append(f"{fa.ICON_FA_CAMERA} ")
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

        # ── 点击选中 ──
        if imgui.is_item_clicked():
            self._selection_ctrl.select(entity_id)

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

        # ── 实体名称（可编辑）+ ID（灰色） ──
        name_buf = summary.name or ""
        changed, new_name = imgui.input_text(
            "##entity_name", name_buf, 256,
        )
        if changed:
            self._browser_ctrl.set_name(entity_id, new_name)
        if not summary.name:
            imgui.same_line()
            imgui.text_disabled("(click to name)")
        imgui.same_line()
        imgui.text_disabled("—")
        imgui.same_line()
        imgui.text_disabled(f"Entity #{summary.entity_id}")

        # ── Transform ──
        if imgui.collapsing_header("Transform", imgui.TreeNodeFlags_.default_open):
            # ── Local / Global 切换 ──
            av = imgui.get_content_region_avail().x
            btn_w = (av - imgui.get_style().item_spacing.x) / 2.0

            if not use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Global", (btn_w, 0)):
                self._transform_local = False
            if not use_local:
                imgui.pop_style_color(1)
            imgui.same_line()
            if use_local:
                imgui.push_style_color(
                    imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.50))
            if imgui.button("Local", (btn_w, 0)):
                self._transform_local = True
            if use_local:
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
                self._draw_mesh_renderer_editor(entity_id, summary)

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

                    # ── Aspect Ratio 预设 (联动 Camera Gizmo 2D 边界框) ──
                    _ASPECT_PRESETS = [
                        ("16:9",   16.0 / 9.0),
                        ("16:10",  16.0 / 10.0),
                        ("4:3",    4.0 / 3.0),
                        ("21:9",   21.0 / 9.0),
                        ("1:1",    1.0),
                    ]
                    current_ar = float(cam.get('aspect_ratio', 16.0 / 9.0))
                    preset_idx = min(
                        range(len(_ASPECT_PRESETS)),
                        key=lambda i: abs(_ASPECT_PRESETS[i][1] - current_ar)
                    )
                    changed_ar, new_idx = imgui.combo(
                        "Aspect Ratio", preset_idx,
                        [p[0] for p in _ASPECT_PRESETS]
                    )
                    if changed_ar:
                        self._browser_ctrl.set_camera_aspect_ratio(
                            entity_id, _ASPECT_PRESETS[new_idx][1])
                        cam['aspect_ratio'] = _ASPECT_PRESETS[new_idx][1]

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

        # ── Add Component ──
        imgui.spacing()
        self._draw_add_component(entity_id)

    def _draw_mesh_renderer_editor(self, entity_id: int, summary) -> None:
        """绘制 MeshRenderer 编辑区域 — Visible / Mesh / Material。"""
        # ── Visible 勾选框 ──
        changed, vis = imgui.checkbox("Visible", summary.render_visible)
        if changed:
            self._browser_ctrl.set_entity_render_visible(entity_id, vis)
            summary.render_visible = vis

        mesh_options = self._resource_ctrl.get_mesh_options()

        # ── Mesh 子节点 ──
        if imgui.tree_node_ex("Mesh##mesh_tree", imgui.TreeNodeFlags_.default_open):
            current_mesh_id = summary.mesh_id or 0
            mesh_names = {mid: name for mid, name in mesh_options}
            current_mesh_name = mesh_names.get(current_mesh_id, f"Mesh #{current_mesh_id}")

            if imgui.begin_combo("Mesh##mesh_select", current_mesh_name):
                for mid, mname in mesh_options:
                    selected = (mid == current_mesh_id)
                    if imgui.selectable(f"{mname}##mesh_{mid}", selected)[0]:
                        self._browser_ctrl.set_entity_mesh(entity_id, mid)
                    if selected:
                        imgui.set_item_default_focus()
                imgui.end_combo()
            imgui.tree_pop()

        # ── Material 子节点 ──
        has_mat = summary.material_id is not None and summary.material_id != 0
        if imgui.tree_node_ex("Material##mat_tree",
                               imgui.TreeNodeFlags_.default_open if has_mat else 0):
            self._draw_material_section(entity_id, summary)
            imgui.tree_pop()

    def _draw_material_section(self, entity_id: int, summary) -> None:
        """绘制 Material 子区域。

        层级:
          Material Name: *MyMat   [Save] [Load]   ← 只读标签 + 按钮
          Name:  [MyMat          ]                ← 可编辑
          Shader / Textures / Uniforms
        """
        from Application.Resource.ResourceManager import ResourceManager
        shader_options = self._resource_ctrl.get_shader_options()
        tex_options = self._resource_ctrl.get_texture_options()

        current_mat_id = summary.material_id or 0
        info = self._browser_ctrl.get_entity_material_info(entity_id)
        if current_mat_id == 0 or info is None:
            imgui.text_disabled("(no material)")
            return

        is_saved = info.get('is_saved', False)
        display_name = info.get('display_name', '*Untitled')
        current_name = info.get('material_name', 'Untitled')
        file_path = info.get('file_path', '')

        # ── Material Name 只读行 + Save / Load ──
        imgui.text("Material Name:")
        imgui.same_line()
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00), display_name)
        imgui.same_line()

        _btn_w = 55
        can_save = not is_saved
        if not can_save:
            imgui.begin_disabled(True)
        save_label = "Save As" if (not is_saved and file_path == "") else "Save"
        if imgui.button(f"{save_label}##mat_save_{entity_id}", (_btn_w, 0)):
            default_name = f"{current_name}.mat" if current_name else "material.mat"
            FileDialog.save_mat(
                callback=lambda p: self._on_mat_save(entity_id, p),
                default_name=default_name,
            )
        if not can_save:
            imgui.end_disabled()

        imgui.same_line()
        if imgui.button(f"Load##mat_load_{entity_id}", (_btn_w, 0)):
            FileDialog.open_mat(
                callback=lambda p: self._on_mat_load(entity_id, p),
            )

        # ── Name 可编辑 ──
        changed, new_name = imgui.input_text("Name##mat_name", current_name, 64)
        if changed and new_name.strip():
            self._browser_ctrl.set_material_name(entity_id, new_name.strip())

        # ── Shader ──
        shader_names = {sid: name for sid, name in shader_options}
        current_shader_name = shader_names.get(
            info['shader_id'], info.get('shader_name', f"#{info['shader_id']}"))
        if imgui.begin_combo("Shader##mat_shader", current_shader_name):
            for sid, sname in shader_options:
                selected = (sid == info['shader_id'])
                if imgui.selectable(f"{sname}##shader_{sid}", selected)[0]:
                    self._browser_ctrl.set_material_shader(entity_id, sid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── Basic Shader 颜色 ──
        if info.get('shader_name') == 'Basic':
            self._draw_color_picker(entity_id, info)

        # ── Textures ──
        tex_names = {tid: name for tid, name in tex_options}
        if imgui.tree_node("Textures##mat_tex"):
            for i, tid in enumerate(info['texture_ids']):
                tname = tex_names.get(tid, f"Texture #{tid}")
                imgui.bullet_text(f"[{i}] {tname}")
                imgui.same_line()
                if imgui.small_button(f"x##tex_{entity_id}_{i}"):
                    self._browser_ctrl.remove_material_texture(entity_id, i)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Remove texture")
            imgui.spacing()
            if imgui.small_button(f"{fa.ICON_FA_PLUS}  Add Texture##add_tex_{entity_id}"):
                imgui.open_popup(f"add_tex_popup_{entity_id}")
            if imgui.begin_popup(f"add_tex_popup_{entity_id}"):
                used_tex_ids = set(info['texture_ids'])
                available = [(tid, name) for tid, name in tex_options if tid not in used_tex_ids]
                if available:
                    for tid, tname in available:
                        if imgui.menu_item(tname, "", False, True)[0]:
                            self._browser_ctrl.add_material_texture(entity_id, tid)
                else:
                    imgui.text_disabled("(all textures in use)")
                imgui.end_popup()
            imgui.tree_pop()

        # ── Uniforms ──
        uniforms = info.get('uniforms', {})
        if uniforms and imgui.tree_node("Uniforms##mat_uniforms"):
            for u_name, u_value in uniforms.items():
                if u_name == 'uColor' and info.get('shader_name') == 'Basic':
                    continue
                val = u_value
                if hasattr(val, 'shape'):
                    if val.shape == ():
                        changed, new_v = imgui.drag_float(
                            f"{u_name}##mat_{entity_id}", float(val), 0.1, format="%.3f")
                        if changed:
                            self._browser_ctrl.set_material_uniform(entity_id, u_name, float(new_v))
                    elif val.shape == (4, 4):
                        imgui.text_disabled(f"{u_name}: mat4")
                    elif val.shape == (4,):
                        changed, new_v = imgui.drag_float4(
                            f"{u_name}##mat_{entity_id}", list(val), 0.01, format="%.3f")
                        if changed:
                            self._browser_ctrl.set_material_uniform(entity_id, u_name, tuple(new_v))
                    else:
                        imgui.text_disabled(f"{u_name}: shape {val.shape}")
                elif isinstance(val, (int, float)):
                    changed, new_v = imgui.drag_float(
                        f"{u_name}##mat_{entity_id}", float(val), 0.1, format="%.3f")
                    if changed:
                        self._browser_ctrl.set_material_uniform(entity_id, u_name, float(new_v))
                else:
                    imgui.text_disabled(f"{u_name}: {type(val).__name__}")
            imgui.tree_pop()

    def _draw_color_picker(self, entity_id: int, info: dict) -> None:
        """Basic Shader 专属颜色调色盘 — 预设按钮 + ColorEdit4。"""
        from Application.Resource.ResourceManager import ResourceManager, COLOR_PRESETS

        u_color = info['uniforms'].get('uColor')
        if u_color is None:
            return
        current_color = tuple(float(c) for c in u_color)  # (r, g, b, a)

        # ── 预设颜色按钮 ──
        imgui.text("Presets:")
        preset_names = list(COLOR_PRESETS.keys())
        # 每行 5 个
        cols = 5
        for idx, name in enumerate(preset_names):
            rgba = COLOR_PRESETS[name]
            # 用彩色小按钮
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(*rgba))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(
                min(rgba[0]*1.2, 1.0), min(rgba[1]*1.2, 1.0),
                min(rgba[2]*1.2, 1.0), 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(*rgba))
            if imgui.button(f"##preset_{name}", (16, 16)):
                ResourceManager.SetMaterialColor(
                    info['material_id'], *rgba)
            imgui.pop_style_color(3)
            # tooltip on hover
            if imgui.is_item_hovered():
                imgui.set_tooltip(name)
            if (idx + 1) % cols != 0:
                imgui.same_line()

        imgui.spacing()

        # ── ColorEdit4 调色盘 ──
        changed, new_color = imgui.color_edit4(
            f"Color##mat_{entity_id}", current_color,
            flags=imgui.ColorEditFlags_.display_hsv | imgui.ColorEditFlags_.float,
        )
        if changed:
            ResourceManager.SetMaterialColor(info['material_id'], *new_color)

    def _draw_add_component(self, entity_id: int) -> None:
        """绘制 'Add Component' 下拉按钮 — 列出所有已注册但未添加的 Component。"""
        available = self._browser_ctrl.get_available_components()
        existing = self._browser_ctrl.get_entity_components(entity_id)

        # 过滤掉已存在的
        addable = {k: v for k, v in available.items() if k not in existing}
        if not addable:
            imgui.text_disabled("(all available components added)")
            return

        if imgui.button(f"{fa.ICON_FA_PLUS}  Add Component##add_comp"):
            imgui.open_popup("add_component_popup")

        if imgui.begin_popup("add_component_popup"):
            imgui.text_colored(
                imgui.ImVec4(*BLENDER_ORANGE, 0.90), "Add Component:")
            for comp_name in addable:
                if imgui.menu_item(comp_name, "", False, True)[0]:
                    self._browser_ctrl.add_component(entity_id, comp_name)
            imgui.end_popup()
