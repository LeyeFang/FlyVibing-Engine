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


class ScenePanel(BasePanel):
    """场景管理器面板 — 只负责绘制，业务逻辑委托给 Controller"""

    name = "Scene"
    flags = imgui.WindowFlags_.none

    def __init__(
        self
    ) -> None:
        super().__init__()
        self.visible = True
        # 0=Entities, 1=Resources — 纯 UI 状态，留在面板
        self._active_tab: int = 0
        # ── 从 ControllerRegistry 获取控制器（支持测试时 Mock 注入） ──
        self._sim_ctrl = get_ctrl(NAME_SIMULATION)
        self._browser_ctrl = get_ctrl(NAME_SCENE_BROWSER)
        self._resource_ctrl = get_ctrl(NAME_RESOURCE_BROWSER)
        self._viewport_ctrl = get_ctrl(NAME_VIEWPORT)
        self._selection_ctrl = get_ctrl(NAME_SELECTION)

    # ============================================================
    # 主绘制入口
    # ============================================================

    def draw(
        self
    ) -> None:
        """绘制整个 Scene 面板"""
        self._draw_header()
        self._draw_controls()
        self._draw_tabs()

    # ============================================================
    # 顶部：场景名
    # ============================================================

    def _draw_header(
        self
    ) -> None:
        """显示当前场景名称"""
        imgui.text("Scene: ")
        imgui.same_line()
        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00), "default"
        )
        imgui.separator()

    # ============================================================
    # 运行控制：Run / Pause / Stop
    # ============================================================

    def _draw_controls(
        self
    ) -> None:
        """绘制播放控制按钮组"""
        av = imgui.get_content_region_avail().x
        btn_w = (av - imgui.get_style().item_spacing.x * 2) / 3.0

        # ▶ Run
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*SUCCESS_GREEN, 1.00))
        if imgui.button("▶ Run", (btn_w, 0)):
            self._sim_ctrl.play()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ⏸ Pause（仅在运行时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*WARNING_AMBER, 1.00))
        imgui.begin_disabled(not self._sim_ctrl.is_running())
        if imgui.button("⏸ Pause", (btn_w, 0)):
            self._sim_ctrl.pause()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ■ Stop（仅在未停止时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*ERROR_RED, 1.00))
        imgui.begin_disabled(self._sim_ctrl.is_stopped())
        if imgui.button("■ Stop", (btn_w, 0)):
            self._sim_ctrl.stop()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        # 状态提示
        imgui.text_disabled(self._sim_ctrl.get_state_label())

        imgui.separator()

    # ============================================================
    # 标签页：Entities / Resources
    # ============================================================

    def _draw_tabs(
        self
    ) -> None:
        """绘制 Entities / Resources 标签页切换按钮及内容"""
        tab_w = (
            imgui.get_content_region_avail().x
            - imgui.get_style().item_spacing.x
        ) / 2.0

        if imgui.button("Entities", (tab_w, 0)):
            self._active_tab = 0
        imgui.same_line()
        if imgui.button("Resources", (tab_w, 0)):
            self._active_tab = 1

        imgui.separator()

        if self._active_tab == 0:
            self._draw_entities_tab()
        else:
            self._draw_resources_tab()

    # ============================================================
    # 视口模式: 2D / 3D 切换 (在 entity 列表上方)
    # ============================================================

    def _draw_viewport_mode(
        self
    ) -> None:
        """绘制 2D | 3D 视口模式切换按钮，委托 ViewportController"""
        av = imgui.get_content_region_avail().x
        btn_w = (av - imgui.get_style().item_spacing.x) / 2.0

        is_2d = self._viewport_ctrl.is_2d()

        # 3D 按钮
        if not is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("3D (Persp)", (btn_w, 0)):
            self._viewport_ctrl.switch_to_3d()
        if not is_2d:
            imgui.pop_style_color(1)

        imgui.same_line()

        # 2D 按钮
        if is_2d:
            imgui.push_style_color(
                imgui.Col_.button, imgui.ImVec4(*BLENDER_ORANGE, 0.60))
        if imgui.button("2D (Ortho)", (btn_w, 0)):
            self._viewport_ctrl.switch_to_2d()
        if is_2d:
            imgui.pop_style_color(1)

    # ============================================================
    # Entities 标签页
    # ============================================================

    def _draw_entities_tab(
        self
    ) -> None:
        """列出场景中所有实体 → 名称可点选，选中后在下方编辑"""
        # ── 2D / 3D 视口模式切换 ──
        self._draw_viewport_mode()
        imgui.separator()

        entity_infos = self._browser_ctrl.get_all_entity_infos()

        if not entity_infos:
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00), "(empty scene)"
            )
            return

        selected = self._selection_ctrl.get_selected()
        for info in entity_infos:
            eid = info['entity_id']
            name = info.get('name', '')
            label = name if name else f"Entity #{eid}"

            # 组件标记（小图标）
            flags_str = ""
            if info.get('has_camera'):
                flags_str += " 📷"
            if info.get('has_mesh'):
                flags_str += " ◼"

            clicked, _ = imgui.selectable(
                f"{label}{flags_str}##{eid}", selected == eid
            )
            if clicked:
                self._selection_ctrl.select(eid)

        # 底部：选中实体的检视面板
        selected = self._selection_ctrl.get_selected()
        if selected is not None:
            imgui.separator()
            self._draw_entity_summary(selected)

    def _draw_entity_summary(
        self,
        entity_id: int
    ) -> None:
        """显示选中实体的所有组件（可展开、可编辑）。"""
        summary = self._browser_ctrl.get_summary(entity_id)
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
            pos = list(summary.position)
            changed, new_pos = imgui.drag_float3("Position", pos, 0.1, format="%.2f")
            if changed:
                self._browser_ctrl.set_position(entity_id, tuple(new_pos))

            rot = list(summary.rotation)
            changed, new_rot = imgui.drag_float3("Rotation", rot, 1.0, format="%.1f")
            if changed:
                self._browser_ctrl.set_rotation(entity_id, tuple(new_rot))

            scl = list(summary.scale)
            changed, new_scl = imgui.drag_float3("Scale", scl, 0.05, format="%.2f")
            if changed:
                self._browser_ctrl.set_scale(entity_id, tuple(new_scl))

        # ── MeshRenderer（有 mesh 才显示） ──
        if summary.mesh_id is not None:
            if imgui.collapsing_header("MeshRenderer", imgui.TreeNodeFlags_.default_open):
                imgui.text(f"Mesh ID: {summary.mesh_id}")
                if summary.material_id is not None:
                    imgui.text(f"Material ID: {summary.material_id}")
                else:
                    imgui.text_disabled("(no Material)")

        # ── Camera（有 camera 才显示） ──
        if summary.has_camera:
            if imgui.collapsing_header("Camera", imgui.TreeNodeFlags_.default_open):
                try:
                    cam = self._browser_ctrl.get_camera_info(entity_id)
                except Exception:
                    cam = None
                if cam:
                    imgui.text(f"Projection: {cam.get('projection', 'perspective')}")
                    imgui.text(f"FOV: {cam.get('fov', 45.0):.1f}")
                    imgui.text(f"Near: {cam.get('near', 0.1):.2f}  Far: {cam.get('far', 1000.0):.1f}")
                    if cam.get('is_primary'):
                        imgui.text_colored(imgui.ImVec4(*WARNING_AMBER, 1.00), "(Primary Camera)")
                else:
                    imgui.text_disabled("(camera info unavailable)")

    # ============================================================
    # Resources 标签页
    # ============================================================

    def _draw_resources_tab(
        self
    ) -> None:
        """列出已加载的 Mesh / Shader / Texture / Material"""
        # Mesh 列表
        if imgui.collapsing_header(
            "Meshes", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, mesh in self._resource_ctrl.get_meshes().items():
                imgui.bullet_text(
                    f"[{id_str}] {self._resource_ctrl.get_resource_name(mesh)}"
                )

        # Shader 列表
        if imgui.collapsing_header(
            "Shaders", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, shader in self._resource_ctrl.get_shaders().items():
                imgui.bullet_text(
                    f"[{id_str}] {self._resource_ctrl.get_resource_name(shader)}"
                )

        # Texture 列表
        if imgui.collapsing_header(
            "Textures", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, tex in self._resource_ctrl.get_textures().items():
                imgui.bullet_text(
                    f"[{id_str}] {self._resource_ctrl.get_resource_name(tex)}"
                )

        # Material 列表
        if imgui.collapsing_header(
            "Materials", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, mat in self._resource_ctrl.get_materials().items():
                imgui.bullet_text(f"[{id_str}] {mat}")
