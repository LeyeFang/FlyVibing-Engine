from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.UI.PanelStyle import (
    BLENDER_ORANGE,
    SUCCESS_GREEN,
    WARNING_AMBER,
    ERROR_RED,
)
from Application.Editor.UI.controllers.SimulationController import (
    SimulationController,
)
from Application.Editor.UI.controllers.SceneBrowserController import (
    SceneBrowserController,
)
from Application.Editor.UI.controllers.ResourceBrowserController import (
    ResourceBrowserController,
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
            SimulationController.play()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ⏸ Pause（仅在运行时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*WARNING_AMBER, 1.00))
        imgui.begin_disabled(not SimulationController.is_running())
        if imgui.button("⏸ Pause", (btn_w, 0)):
            SimulationController.pause()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        imgui.same_line()

        # ■ Stop（仅在未停止时可用）
        imgui.push_style_color(
            imgui.Col_.text, imgui.ImVec4(*ERROR_RED, 1.00))
        imgui.begin_disabled(SimulationController.is_stopped())
        if imgui.button("■ Stop", (btn_w, 0)):
            SimulationController.stop()
        imgui.end_disabled()
        imgui.pop_style_color(1)

        # 状态提示
        imgui.text_disabled(SimulationController.get_state_label())

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
    # Entities 标签页
    # ============================================================

    def _draw_entities_tab(
        self
    ) -> None:
        """列出场景中所有可渲染实体"""
        entity_ids = SceneBrowserController.get_renderable_entities()

        if not entity_ids:
            imgui.text_colored(
                imgui.ImVec4(0.400, 0.400, 0.400, 1.00), "(empty scene)"
            )
            return

        # 遍历当前帧的可渲染实体
        selected = SceneBrowserController.get_selected()
        for eid in entity_ids:
            clicked, _ = imgui.selectable(
                f"Entity #{eid}", selected == eid
            )
            if clicked:
                SceneBrowserController.select(eid)

        # 底部显示选中实体的组件摘要
        selected = SceneBrowserController.get_selected()
        if selected is not None:
            imgui.separator()
            self._draw_entity_summary(selected)

    def _draw_entity_summary(
        self,
        entity_id: int
    ) -> None:
        """显示选中实体的 Transform / Mesh / Material 信息"""
        summary = SceneBrowserController.get_summary(entity_id)
        if summary is None:
            imgui.text_disabled("(failed to load entity info)")
            return

        imgui.text_colored(
            imgui.ImVec4(*BLENDER_ORANGE, 1.00),
            f"Entity #{summary.entity_id}",
        )
        imgui.text(
            f"Position: ({summary.position[0]:.1f}, "
            f"{summary.position[1]:.1f}, {summary.position[2]:.1f})"
        )
        if summary.mesh_id is not None:
            imgui.text(f"Mesh ID: {summary.mesh_id}")
        else:
            imgui.text("(no Mesh)")
        if summary.material_id is not None:
            imgui.text(f"Material ID: {summary.material_id}")
        else:
            imgui.text("(no Material)")

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
            for id_str, mesh in ResourceBrowserController.get_meshes().items():
                imgui.bullet_text(
                    f"[{id_str}] {ResourceBrowserController.get_resource_name(mesh)}"
                )

        # Shader 列表
        if imgui.collapsing_header(
            "Shaders", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, shader in ResourceBrowserController.get_shaders().items():
                imgui.bullet_text(
                    f"[{id_str}] {ResourceBrowserController.get_resource_name(shader)}"
                )

        # Texture 列表
        if imgui.collapsing_header(
            "Textures", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, tex in ResourceBrowserController.get_textures().items():
                imgui.bullet_text(
                    f"[{id_str}] {ResourceBrowserController.get_resource_name(tex)}"
                )

        # Material 列表
        if imgui.collapsing_header(
            "Materials", imgui.TreeNodeFlags_.default_open
        ):
            for id_str, mat in ResourceBrowserController.get_materials().items():
                imgui.bullet_text(f"[{id_str}] {mat}")
