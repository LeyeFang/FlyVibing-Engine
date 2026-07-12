"""
SceneSync — Scene ↔ ECS 双向同步。

职责:
  - SyncToScene: 将 esper 世界中的实体序列化到 Scene dataclass（保存前）
  - SyncFromScene: 从 Scene dataclass 恢复实体到 esper 世界（加载后）

组合模式:
  SceneSync 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import esper

from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer
from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class SceneSync:
    """Scene ↔ ECS 双向同步器。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    # ════════════════════════════════════════════════════════════
    # esper → Scene (保存)
    # ════════════════════════════════════════════════════════════

    def sync_to_scene(self, scene: object) -> None:
        """将当前 esper 世界中的实体同步到 Scene 数据容器。"""
        import dataclasses
        st = self._mgr

        # 安全兜底: 确保组件注册表已初始化
        if not st._component_registry:
            st._component_registry["Camera"] = Camera
            st._component_registry["MeshRenderer"] = MeshRenderer
            st._component_registry["Transform"] = Transform

        scene.entities.clear()
        max_eid = 0

        for entity_id_str in list(st.entities.keys()):
            eid = int(entity_id_str)
            max_eid = max(max_eid, eid)

            name = st._entity_names.get(eid, f"Entity_{eid}")

            # 直接从 esper 获取实体所有组件 (不依赖 registry 发现)
            comps: dict[str, object] = {}
            try:
                all_comps = esper.components_for_entity(eid)
            except KeyError:
                all_comps = ()

            for comp_instance in all_comps:
                comp_type = type(comp_instance).__name__
                if hasattr(comp_instance, '__dataclass_fields__'):
                    comps[comp_type] = dataclasses.asdict(comp_instance)
                elif hasattr(comp_instance, 'to_dict'):
                    comps[comp_type] = comp_instance.to_dict()

            if comps:
                from Application.Core.Scene.Scene import EntityData
                scene.entities[eid] = EntityData(name=name, components=comps)
            else:
                print(f"[SyncToScene] WARNING: entity {eid} ('{name}') has NO serializable components")

        scene._next_eid = max_eid + 1 if max_eid > 0 else 1
        scene.main_camera_entity_id = st.main_camera_id
        print(f"[SyncToScene] Synced {len(scene.entities)} entities to Scene '{scene.name}'")

    # ════════════════════════════════════════════════════════════
    # Scene → esper (加载)
    # ════════════════════════════════════════════════════════════

    def sync_from_scene(self, scene: object, clear_existing: bool = True) -> None:
        """从 Scene 数据容器恢复实体到 esper 世界。"""
        st = self._mgr

        # 安全兜底: 确保组件注册表已初始化
        if not st._component_registry:
            st._component_registry["Camera"] = Camera
            st._component_registry["MeshRenderer"] = MeshRenderer
            st._component_registry["Transform"] = Transform

        # ── 清空现有实体 ──
        if clear_existing:
            for entity_id_str in list(st.entities.keys()):
                eid = int(entity_id_str)
                self._mgr.entity_mgr.delete(eid)
            esper.clear_database()
            st.entities.clear()
            st._entity_names.clear()
            st._entity_parent.clear()
            st._editor_visible.clear()
            st.main_camera_id = None
            st.scene_camera = None
            st.scene_camera_id = None
            st.main_camera_2d_id = None

        # ── 重建实体 ──
        id_map: dict[int, int] = {}

        for old_eid, ed in scene.entities.items():
            comp_instances = []
            for comp_name, comp_dict in ed.components.items():
                comp_cls = st._component_registry.get(comp_name)
                if comp_cls is None:
                    continue
                if isinstance(comp_dict, comp_cls):
                    comp_instances.append(comp_dict)
                    continue
                if isinstance(comp_dict, dict) and hasattr(comp_cls, '__dataclass_fields__'):
                    try:
                        comp_instances.append(comp_cls(**comp_dict))
                    except TypeError:
                        pass

            if comp_instances:
                new_eid = esper.create_entity(*comp_instances)
            else:
                new_eid = esper.create_entity(Transform())

            id_map[old_eid] = new_eid
            st.entities[f'{new_eid}'] = 1
            st._entity_names[new_eid] = ed.name
            st._editor_visible.add(new_eid)

            # 仅 MeshRenderer 实体注册到渲染器
            has_mesh = any(isinstance(ci, MeshRenderer) for ci in comp_instances)
            if has_mesh:
                _renderer = getattr(st.app, 'renderer', None)
                if _renderer is not None:
                    _renderer.enqueue(EntityRegistrationCommand(new_eid, register=True))

        # ── ID 重映射 ──
        from Application.Core.Scene.Scene import EntityData
        remapped: dict[int, object] = {}
        for old_eid, new_eid in id_map.items():
            ed = scene.entities[old_eid]
            remapped[new_eid] = EntityData(name=ed.name, components=dict(ed.components))
        scene.entities.clear()
        scene.entities.update(remapped)
        scene._next_eid = max(id_map.values()) + 1 if id_map else 1

        if scene.main_camera_entity_id is not None:
            scene.main_camera_entity_id = id_map.get(
                scene.main_camera_entity_id, scene.main_camera_entity_id)

        # ── 恢复主摄像机 ──
        if scene.main_camera_entity_id is not None:
            try:
                st.main_camera_id = scene.main_camera_entity_id
                st.scene_camera = esper.component_for_entity(
                    scene.main_camera_entity_id, Camera)
                st.scene_camera_id = scene.main_camera_entity_id
            except KeyError:
                st.main_camera_id = None
                st.scene_camera = None
                st.scene_camera_id = None

        # ── 兜底: 若无摄像机，创建默认 ──
        has_camera = False
        for entity_id_str in st.entities:
            try:
                if esper.has_component(int(entity_id_str), Camera):
                    has_camera = True
                    break
            except KeyError:
                pass
        if not has_camera:
            self._mgr._create_default_cameras(st)

        st.game_type = scene.game_type
        print(f"[SyncFromScene] Restored {len(st.entities)} entities from Scene '{scene.name}'")
