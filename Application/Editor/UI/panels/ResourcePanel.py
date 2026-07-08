"""ResourcePanel — 已加载资源浏览器（独立面板）。"""

from imgui_bundle import imgui

from Application.Editor.UI.BasePanel import BasePanel
from Application.Editor.Services.ControllerRegistry import (
    get_ctrl,
    NAME_RESOURCE_BROWSER,
)


class ResourcePanel(BasePanel):
    """资源管理器面板 — 列出已加载的 Mesh / Shader / Texture / Material"""

    name = "Resources"
    flags = imgui.WindowFlags_.none

    def __init__(self) -> None:
        super().__init__()
        self.visible = False
        self._resource_ctrl = get_ctrl(NAME_RESOURCE_BROWSER)

    def draw(self) -> None:
        self._draw_header()
        self._draw_content()

    def _draw_header(self) -> None:
        imgui.text("Resource Browser")
        imgui.separator()

    def _draw_content(self) -> None:
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
