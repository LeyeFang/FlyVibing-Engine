"""资源浏览器 — 已加载资源列表查询"""
from typing import Any

from Application.Resource.ResourceManager import ResourceManager


class ResourceBrowserController:
    """查询已加载的 Mesh / Shader / Texture / Material — 纯数据层"""

    # ── 分类查询 ────────────────────────────────────────────

    @classmethod
    def get_meshes(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_mesh)

    @classmethod
    def get_shaders(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_shader)

    @classmethod
    def get_textures(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_texture)

    @classmethod
    def get_materials(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_material)

    # ── 便捷方法 ────────────────────────────────────────────

    @classmethod
    def get_resource_name(cls, resource: dict[str, Any]) -> str:
        return resource.get("name", "unnamed")


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_RESOURCE_BROWSER
register(NAME_RESOURCE_BROWSER, ResourceBrowserController)
