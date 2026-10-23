"""
EntityManager — 实体生命周期管理。

职责:
  - 实体创建 / 删除 (AddEntity / DeleteEntity)
  - 父子层级 (SetParent / GetParent / GetChildren / GetRoots)
  - 实体命名 (SetName / GetName)
  - 基础查询 (Exists / GetAllInfos / GetAllWithComponent / GetComponent)

组合模式:
  EntityManager 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import esper

from Application.Core.Scene.BasicComponents import Transform, MeshRenderer, Camera
from Application.Core.Renderer.RenderCommand import (
    EntityRegistrationCommand, EntityVisibilityCommand, EntityRenderVisibleCommand,
)
from Application.Core.Events.SceneEvent import NewComponentEvent

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class EntityManager:
    """实体 CRUD + 层级 + 命名。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    # ════════════════════════════════════════════════════════════
    # 实体创建 / 删除
    # ════════════════════════════════════════════════════════════

    def add(self, name: str = "", *components) -> int:
        """创建新实体（可选初始组件），返回 entity_id。"""
        st = self._mgr
        if components:
            entity_id = esper.create_entity(*components)
        else:
            entity_id = esper.create_entity(Transform())
        # 以下操作不依赖 esper（仅使用 SceneManager 追踪数据）
        with st._entities_lock:
            st.entities[f'{entity_id}'] = 1
            st._editor_visible.add(entity_id)
            st._entity_names[entity_id] = name if name else f"Entity_{entity_id}"
        # 注册 MeshRenderer 到渲染器
        for comp in components:
            if isinstance(comp, MeshRenderer):
                _renderer = getattr(st.app, 'renderer', None)
                if _renderer is not None:
                    _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
                    _renderer.enqueue(EntityRenderVisibleCommand(entity_id, visible=comp.visible))
                    _renderer.enqueue(EntityVisibilityCommand(entity_id, visible=True))
        return entity_id

    def delete(self, entity_id: int) -> bool:
        """删除实体及其所有子实体。返回是否成功删除。线程安全。"""
        st = self._mgr
        with st._entities_lock:
            if f'{entity_id}' not in st.entities:
                return False

            # 递归删除子实体（RLock: 子实体 delete 可重入）
            children = self.get_children(entity_id)
            for child_id in children:
                self.delete(child_id)

            # 从父实体解除关系
            st._entity_parent.pop(entity_id, None)

            # 清理追踪数据
            st.entities.pop(f'{entity_id}', None)
            st._entity_names.pop(entity_id, None)
            st._editor_visible.discard(entity_id)

        # 通知渲染器注销 GPU 资源
        _renderer = getattr(st.app, 'renderer', None)
        if _renderer is not None:
            _renderer.enqueue(EntityRegistrationCommand(entity_id, register=False))

        # 从 ECS 世界删除
        try:
            esper.delete_entity(entity_id)
        except KeyError:
            pass

        return True

    # ════════════════════════════════════════════════════════════
    # 父子层级
    # ════════════════════════════════════════════════════════════

    def set_parent(self, child_id: int, parent_id: int) -> None:
        st = self._mgr
        if parent_id and parent_id != 0:
            st._entity_parent[child_id] = parent_id
        else:
            st._entity_parent.pop(child_id, None)

    def get_parent(self, entity_id: int) -> int | None:
        return self._mgr._entity_parent.get(entity_id)

    def get_children(self, entity_id: int) -> list[int]:
        st = self._mgr
        with st._entities_lock:
            return [cid for cid, pid in st._entity_parent.items() if pid == entity_id]

    def get_roots(self) -> list[int]:
        st = self._mgr
        with st._entities_lock:
            return [eid for eid in st.entity_ids_snapshot()
                    if eid not in st._entity_parent]

    # ════════════════════════════════════════════════════════════
    # 命名
    # ════════════════════════════════════════════════════════════

    def set_name(self, entity_id: int, name: str) -> None:
        st = self._mgr
        if name.strip():
            st._entity_names[entity_id] = name.strip()
        else:
            st._entity_names.pop(entity_id, None)

    def get_name(self, entity_id: int) -> str:
        return self._mgr._entity_names.get(entity_id, "")

    def get_id_by_name(self, name: str) -> int:
        """按名称查找实体 ID。未找到返回 -1。"""
        mgr = self._mgr
        with mgr._entities_lock:
            for eid, ename in mgr._entity_names.items():
                if ename == name:
                    return eid
        return -1

    # ════════════════════════════════════════════════════════════
    # 基础查询
    # ════════════════════════════════════════════════════════════

    def exists(self, entity_id: int) -> bool:
        st = self._mgr
        with st._entities_lock:
            return f'{entity_id}' in st.entities

    def get_all_infos(self) -> list[dict]:
        """返回所有实体的基本信息列表（供 ScenePanel 树使用）。"""
        st = self._mgr
        result = []
        all_ids = st.entity_ids_snapshot()
        for entity_id in all_ids:
            info: dict = {
                'entity_id': entity_id,
                'name': self.get_name(entity_id),
                'has_camera': False,
                'has_mesh': False,
                'visible': entity_id in st._editor_visible,
                'render_visible': False,
                'mesh_id': -1,
                'material_id': -1,
            }
            try:
                if esper.has_component(entity_id, Camera):
                    info['has_camera'] = True
            except KeyError:
                pass
            try:
                if esper.has_component(entity_id, MeshRenderer):
                    mr = esper.component_for_entity(entity_id, MeshRenderer)
                    info['has_mesh'] = True
                    info['mesh_id'] = mr.mesh_id
                    info['material_id'] = mr.material_id
                    info['render_visible'] = mr.visible
            except KeyError:
                pass
            result.append(info)
        return result

    def get_all_with_component(self, component_type: type) -> list[tuple[int, object]]:
        """返回拥有指定组件的所有 (entity_id, component_instance) 列表。"""
        result = []
        st = self._mgr
        for eid in st.entity_ids_snapshot():
            try:
                if esper.has_component(eid, component_type):
                    result.append((eid, esper.component_for_entity(eid, component_type)))
            except KeyError:
                pass
        return result

    def get_component(self, entity_id: int, component_type: type):
        """获取实体的指定组件，不存在则抛出 KeyError。"""
        return esper.component_for_entity(entity_id, component_type)

    def add_component(self, entity_id: int, component_instance) -> None:
        """给实体添加组件实例。"""
        st = self._mgr
        esper.add_component(entity_id, component_instance)
        NewComponentEvent.Pack(entity_id, component_instance, engine=st.app)
        # 注册 MeshRenderer 到渲染器
        if isinstance(component_instance, MeshRenderer):
            _renderer = getattr(st.app, 'renderer', None)
            if _renderer is not None:
                _renderer.enqueue(EntityRegistrationCommand(entity_id, register=True))
                _renderer.enqueue(EntityRenderVisibleCommand(
                    entity_id, visible=component_instance.visible))
                _renderer.enqueue(EntityVisibilityCommand(
                    entity_id, visible=(entity_id in st._editor_visible)))
                _renderer.enqueue(
                    EntityVisibilityCommand(entity_id, visible=(entity_id in st._editor_visible)))
