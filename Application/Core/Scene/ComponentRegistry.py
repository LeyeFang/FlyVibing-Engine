"""
ComponentRegistry — 组件类型注册表。

职责:
  - 组件类型注册 / 查询
  - 按名称给实体添加组件

组合模式:
  ComponentRegistry 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import esper

from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Camera
from Application.Core.Renderer.RenderCommand import (
    EntityRegistrationCommand, EntityRenderVisibleCommand, EntityVisibilityCommand,
)
from Application.Core.Events.SceneEvent import NewComponentEvent

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class ComponentRegistry:
    """组件类型注册与管理。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    def register(self, name: str, component_cls: type) -> None:
        """注册一个可用的 Component 类型。"""
        self._mgr._component_registry[name] = component_cls

    def get_all(self) -> dict[str, type]:
        """获取所有已注册的 Component 类型。"""
        return dict(self._mgr._component_registry)

    def add_by_name(self, entity_id: int, component_name: str) -> bool:
        """按名称给实体添加 Component。线程安全。"""
        comp_cls = self._mgr._component_registry.get(component_name)
        if comp_cls is None:
            return False
        if esper.has_component(entity_id, comp_cls):
            return False
        instance = comp_cls()
        # ★ MeshRenderer 默认 mesh 设为 Cube 而非 Square
        if isinstance(instance, MeshRenderer):
            from Application.Resource.ResourceManager import ResourceManager
            try:
                instance.mesh_id = ResourceManager.GetDefaultMesh('Cube')
            except Exception:
                pass  # fallback to default mesh_id=1
        self._mgr.entity_mgr.add_component(entity_id, instance)
        return True

    def ensure_defaults(self) -> None:
        """确保内置组件已注册。"""
        reg = self._mgr._component_registry
        if "Camera" not in reg:
            reg["Camera"] = Camera
        if "MeshRenderer" not in reg:
            reg["MeshRenderer"] = MeshRenderer
        if "Transform" not in reg:
            reg["Transform"] = Transform
