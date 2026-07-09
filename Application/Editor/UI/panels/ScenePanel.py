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


class ScenePanel(BasePanel):
    """场景管理器面板 — 五区域布局:
      0. 场景管理 (新建/切换)
      1. 运行控制
      2. 2D / 3D / Overlay 视口模式
      3. Entity 树
      4. 选中 Entity 的组件检视
    """

    name = "Scene"
    flags = imgui.WindowFlags_.none

    # ── Scene 数据管理 (类变量, 跨实例共享) ────────────────
    _scene_initialized: bool = False
    _scene_names: list[str] = []
    _active_scene_name: str = ""

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
        self._transform_local: bool = True
        # ── 新建场景输入缓冲 ──
        self._new_scene_name: str = ""

    # ============================================================
    # Scene 数据管理 (类方法)
    # ============================================================

    @classmethod
    def _ensure_scene_initialized(cls) -> None:
        """确保 Scene 数据对象已创建并设为 EditorHost 活跃场景。"""
        if cls._scene_initialized:
            return
        cls._scene_initialized = True

        from Application.Core.Scene.Scene import Scene, GameType
        from Application.Editor.EditorHost import EditorHost

        scene = Scene("Default", game_type=GameType.GAME_3D)
        cls._sync_ecs_to_scene(scene)
        EditorHost.set_active_scene(scene)
        cls._active_scene_name = scene.name
        cls._scene_names = [scene.name]
        print(f"[ScenePanel] Initialized scene '{scene.name}' "
              f"with {len(scene.entities)} templates, game_type={scene.game_type.value}")

    @classmethod
    def _sync_ecs_to_scene(cls, scene) -> None:
        """将 ECS 世界中的非系统实体同步到 Scene.entities 注册表。

        使用 ECS entity ID 作为 Scene.entities 的 key，
        便于编辑器侧改名/删改等操作的直接查找。
        """
        from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer
        from Application.Core.Scene.SceneManager import SceneManager
        from Application.Core.Scene.Scene import EntityData
        import esper, copy

        _sys_ids = {SceneManager.get_main_camera_id(),
                     SceneManager.get_main_camera_2d_id()}

        for eid, (xform,) in esper.get_components(Transform):
            if eid in _sys_ids:
                continue
            name = SceneManager.GetEntityName(eid)
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
            scene.entities[eid] = EntityData(name=name, components=comps)

    @classmethod
    def _on_entity_added(cls, eid: int, name: str = "") -> None:
        """ECS 新增实体 → 同步到 Scene.entities (以 ECS ID 为 key)。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is None:
            return
        from Application.Core.Scene.Scene import EntityData
        from Application.Core.Scene.BasicComponents import Transform
        import esper, copy
        try:
            xform = esper.component_for_entity(eid, Transform)
            scene.entities[eid] = EntityData(
                name=name or f"Entity #{eid}",
                components={"Transform": copy.deepcopy(xform)},
            )
        except Exception as e:
            print(f"[ScenePanel] _on_entity_added failed eid={eid}: {e}")

    @classmethod
    def _on_entity_renamed(cls, eid: int, new_name: str) -> None:
        """ECS 实体改名 → 同步 Scene.entities 中的名称。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is None:
            return
        ed = scene.entities.get(eid)
        if ed is not None:
            ed.name = new_name

    @classmethod
    def _on_entity_deleted(cls, eid: int) -> None:
        """ECS 删除实体 → 同步从 Scene.entities 移除。"""
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is not None:
            scene.entities.pop(eid, None)

    @classmethod
    def _create_new_scene(cls, name: str) -> None:
        """创建新 Scene 对象并设为活跃。"""
        from Application.Core.Scene.Scene import Scene, GameType
        from Application.Editor.EditorHost import EditorHost
        scene = Scene(name, game_type=GameType.GAME_3D)
        EditorHost.set_active_scene(scene)
        cls._active_scene_name = name
        if name not in cls._scene_names:
            cls._scene_names.append(name)
        cls._scene_names.sort(key=lambda n: n.lower())

    @classmethod
    def _sync_game_type(cls, mode: str) -> None:
        """同步 2D/3D/Overlay 模式到 Scene.game_type。"""
        from Application.Core.Scene.Scene import GameType
        from Application.Editor.EditorHost import EditorHost
        scene = EditorHost.get_active_scene()
        if scene is None:
            return
        gt_map = {"3d": GameType.GAME_3D, "2d": GameType.GAME_2D,
                   "overlay": GameType.OVERLAY}
        new_gt = gt_map.get(mode, GameType.GAME_3D)
        if scene.game_type != new_gt:
            scene.game_type = new_gt

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(self) -> None:
        cls = type(self)
        cls._ensure_scene_initialized()
        self._draw_scene_manager()
        self._draw_controls()
        self._draw_viewport_mode()
        imgui.separator()
        self._draw_entity_tree()
        selected = self._selection_ctrl.get_selected()
        if selected is not None:
            imgui.separator()
            self._draw_entity_summary(selected)

    # ============================================================
    # 区域 0: 场景管理
    # ============================================================

    def _draw_scene_manager(self) -> None:
        cls = type(self)
        imgui.push_item_width(imgui.get_content_region_avail().x - 90)
        try:
            idx = cls._scene_names.index(cls._active_scene_name)
        except ValueError:
            idx = 0
        changed, new_idx = imgui.combo("##scene_select", idx, cls._scene_names)
        if changed and 0 <= new_idx < len(cls._scene_names):
            cls._active_scene_name = cls._scene_names[new_idx]
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_PLUS} New"):
            imgui.open_popup("New Scene")
        self._draw_new_scene_popup()
        imgui.separator()

    def _draw_new_scene_popup(self) -> None:
        cls = type(self)
        if not imgui.begin_popup_modal("New Scene", None,
                                        imgui.WindowFlags_.always_auto_resize)[0]:
            return
        imgui.text("Scene name:")
        imgui.push_item_width(250)
        changed, self._new_scene_name = imgui.input_text(
            "##new_scene_name", self._new_scene_name)
        imgui.pop_item_width()
        imgui.spacing()
        name = self._new_scene_name.strip()
        if not name:
            imgui.begin_disabled(True)
        if imgui.button("Create", imgui.ImVec2(100, 0)):
            cls._create_new_scene(name)
            self._new_scene_name = ""
            imgui.close_current_popup()
        if not name:
            imgui.end_disabled()
        imgui.same_line()
        if imgui.button("Cancel", imgui.ImVec2(100, 0)):
            self._new_scene_name = ""
            imgui.close_current_popup()
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
            type(self)._sync_game_type("3d")
        if not is_2d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # 2D 按钮
        if is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("2D", (btn_w, 0)):
            self._viewport_ctrl.switch_to_2d()
            type(self)._sync_game_type("2d")
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
        imgui.separator()

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

        # ── 树底部空白: 拖放到此处解除父子关系 ──
        imgui.dummy(imgui.ImVec2(imgui.get_content_region_avail().x, 20))
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

        # ── 构建标签: 图标标记 ──
        #     每个 entity 默认显示立方体图标; Camera 额外显示摄像机图标
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
        imgui.separator()
        self._draw_add_component(entity_id)

    def _draw_mesh_renderer_editor(self, entity_id: int, summary) -> None:
        """绘制 MeshRenderer 编辑区域 — Mesh 下拉 + Material 子区域。"""
        mesh_options = self._resource_ctrl.get_mesh_options()
        mat_options = self._resource_ctrl.get_material_options()

        # ── Mesh 下拉 ──
        current_mesh_id = summary.mesh_id or 0
        mesh_names = {mid: name for mid, name in mesh_options}
        current_mesh_name = mesh_names.get(current_mesh_id, f"Mesh #{current_mesh_id}")

        if imgui.begin_combo("Mesh", current_mesh_name):
            for mid, mname in mesh_options:
                selected = (mid == current_mesh_id)
                if imgui.selectable(f"{mname}##mesh_{mid}", selected)[0]:
                    self._browser_ctrl.set_entity_mesh(entity_id, mid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── Material 区域（tree node，始终可见） ──
        has_mat = summary.material_id is not None and summary.material_id != 0
        if imgui.tree_node_ex("Material##mat_tree", imgui.TreeNodeFlags_.default_open if has_mat else 0):
            self._draw_material_section(entity_id, summary)
            imgui.tree_pop()

    def _draw_material_section(self, entity_id: int, summary) -> None:
        """绘制 Material 子区域 — 材质选择 + Shader/Textures/Uniforms 编辑。"""
        from Application.Resource.ResourceManager import ResourceManager
        mat_options = self._resource_ctrl.get_material_options()
        shader_options = self._resource_ctrl.get_shader_options()
        tex_options = self._resource_ctrl.get_texture_options()

        current_mat_id = summary.material_id or 0
        mat_names = {mid: name for mid, name in mat_options}
        current_mat_name = mat_names.get(current_mat_id, "(none)")

        # ── Material 选择 ──
        if imgui.begin_combo("Material##mat_select", current_mat_name):
            if imgui.selectable("(none)##mat_none", current_mat_id == 0)[0]:
                self._browser_ctrl.set_entity_material(entity_id, 0)
            for mid, mname in mat_options:
                selected = (mid == current_mat_id)
                if imgui.selectable(f"{mname}##mat_{mid}", selected)[0]:
                    self._browser_ctrl.set_entity_material(entity_id, mid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()
        imgui.same_line()
        if imgui.small_button(f"{fa.ICON_FA_PLUS}##new_mat_{entity_id}"):
            self._browser_ctrl.create_material_for_entity(entity_id)
        if imgui.is_item_hovered():
            imgui.set_tooltip("New Material (Basic)")

        # ── 无材质时仅显示提示 ──
        if current_mat_id == 0:
            imgui.text_disabled("(no material assigned)")
            return

        info = self._browser_ctrl.get_entity_material_info(entity_id)
        if info is None:
            imgui.text_disabled("(material info unavailable)")
            return

        # ── Shader 下拉 ──
        shader_names = {sid: name for sid, name in shader_options}
        current_shader_name = shader_names.get(info['shader_id'], info.get('shader_name', f"#{info['shader_id']}"))
        if imgui.begin_combo("Shader##mat_shader", current_shader_name):
            for sid, sname in shader_options:
                selected = (sid == info['shader_id'])
                if imgui.selectable(f"{sname}##shader_{sid}", selected)[0]:
                    self._browser_ctrl.set_material_shader(entity_id, sid)
                if selected:
                    imgui.set_item_default_focus()
            imgui.end_combo()

        # ── ★ Basic Shader 专属: 颜色调色盘 ──
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
            imgui.text("Add Component:")
            imgui.separator()
            for comp_name in addable:
                if imgui.menu_item(comp_name, "", False, True)[0]:
                    self._browser_ctrl.add_component(entity_id, comp_name)
            imgui.end_popup()
