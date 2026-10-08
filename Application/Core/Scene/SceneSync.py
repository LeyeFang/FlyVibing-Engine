"""
SceneSync — Scene ↔ ECS 双向同步。

职责:
  - SyncToScene: 将 esper 世界中的实体序列化到 Scene dataclass（保存前）
  - SyncFromScene: 从 Scene dataclass 恢复实体到 esper 世界（加载后）

组合模式:
  SceneSync 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING

import dataclasses
import esper

from Application.Core.Scene.BasicComponents import Transform, Camera, MeshRenderer
from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand
from Application.Core.Scene.DataContract import DataContract, format_value

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager

# 旧场景/prefab 组件名 → 新组件名 (加载时迁移)
_COMP_NAME_MIGRATIONS = {
    "DirectionalLight": "Light",
}


class SceneSync:
    """Scene ↔ ECS 双向同步器。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    # ════════════════════════════════════════════════════════════
    # esper → Scene (保存)
    # ════════════════════════════════════════════════════════════

    def sync_to_scene(self, scene: object) -> None:
        """将当前 esper 世界中的实体同步到 Scene 数据容器。

        使用 scene-local stable ID (sid) 作为 entities 的 key,
        esper eid → sid 映射从 SceneManager._eid_to_sid 读取。
        """
        st = self._mgr

        # ★ 单一注册源（幂等）: 防止 sync 先于 Init 的路径缺少内置组件
        st.comp_mgr.ensure_defaults()

        scene.entities.clear()
        max_sid = 0

        for entity_id_str in list(st.entities.keys()):
            eid = int(entity_id_str)
            # ★ 跳过摄像机实体 — 相机由 prefab 管理，不写入场景文件
            try:
                if esper.has_component(eid, Camera):
                    continue
            except KeyError:
                pass
            # ★ 使用 stable ID 而非 esper ID
            sid = st._eid_to_sid.get(eid)
            if sid is None:
                sid = max_sid + 1 if max_sid == 0 else max_sid + 1
                st._eid_to_sid[eid] = sid
                st._sid_map[sid] = eid
            max_sid = max(max_sid, sid)

            name = st._entity_names.get(eid, f"Entity_{eid}")
            # ★ 父实体 ID 也转为 sid
            parent_eid = st._entity_parent.get(eid)
            parent_sid = st._eid_to_sid.get(parent_eid) if parent_eid is not None else None

            comps: dict[str, object] = {}
            try:
                all_comps = esper.components_for_entity(eid)
            except KeyError:
                all_comps = ()

            for comp_instance in all_comps:
                comp_type = type(comp_instance).__name__
                comps[comp_type] = format_value(comp_instance)

            if comps:
                from Application.Core.Scene.Scene import EntityData
                scene.entities[sid] = EntityData(name=name, components=comps, parent_id=parent_sid)

        scene._next_sid = max_sid + 1 if max_sid > 0 else 1
        scene.main_camera_entity_id = st._eid_to_sid.get(st.main_camera_id)
        scene.game_type = st.game_type
        scene.ambient_color = tuple(getattr(st, 'ambient_color', (0.5, 0.5, 0.5)))
        scene.lighting_fallback = bool(getattr(st, 'lighting_fallback', True))

    # ════════════════════════════════════════════════════════════
    # Scene → esper (加载)
    # ════════════════════════════════════════════════════════════

    def sync_from_scene(self, scene: object, clear_existing: bool = True) -> None:
        """从 Scene 数据容器恢复实体到 esper 世界。

        Scene.entities 的 key 是 scene-local stable ID (sid)。
        创建 esper 实体后建立 sid↔eid 双向映射。
        """
        st = self._mgr

        # ★ 单一注册源（幂等）: 防止 sync 先于 Init 的路径缺少内置组件
        st.comp_mgr.ensure_defaults()

        # ── 恢复场景环境光 (光照帧状态来源) ──
        try:
            amb = getattr(scene, 'ambient_color', (0.5, 0.5, 0.5))
            st.ambient_color = tuple(float(v) for v in amb[:3])
        except Exception:
            st.ambient_color = (0.5, 0.5, 0.5)
        try:
            st.lighting_fallback = bool(getattr(scene, 'lighting_fallback', True))
        except Exception:
            st.lighting_fallback = True

        # ── 清空现有实体 + 映射表 ──
        if clear_existing:
            for entity_id_str in list(st.entities.keys()):
                eid = int(entity_id_str)
                self._mgr.entity_mgr.delete(eid)
            esper.clear_database()
            st.entities.clear()
            st._entity_names.clear()
            st._entity_parent.clear()
            st._editor_visible.clear()
            st._sid_map.clear()
            st._eid_to_sid.clear()
            st.main_camera_id = None
            st.scene_camera = None
            st.scene_camera_id = None
            st.main_camera_2d_id = None
            st.main_camera_overlay_id = None
            # ★ 安全验证: esper 世界确实被清空
            try:
                remaining = list(esper.get_component(Transform))
                if remaining:
                    for eid, _ in remaining:
                        esper.delete_entity(eid)
                    print(f"[SceneSync] WARNING: {len(remaining)} entities survived clear_database, force-deleted")
            except Exception:
                pass

        # ── 重建实体 (sid → esper eid) ──
        _pending_parents: dict[int, int] = {}  # new_eid → parent_sid

        for sid, ed in scene.entities.items():
            comp_instances = []
            for comp_name, comp_value in ed.components.items():
                # 组件名迁移 (旧场景文件兼容)
                comp_name = _COMP_NAME_MIGRATIONS.get(comp_name, comp_name)
                comp_cls = st._component_registry.get(comp_name)
                if comp_cls is None:
                    continue

                # 1. 已是组件实例 → 直接使用
                if isinstance(comp_value, comp_cls):
                    comp_instances.append(comp_value)
                    continue

                # 2. dict → 通过 DataContract 反序列化
                if isinstance(comp_value, dict):
                    if issubclass(comp_cls, DataContract):
                        obj = comp_cls.deserialize(comp_value)
                        if obj is not None:
                            comp_instances.append(obj)
                            continue
                    # 兜底: dict → **kwargs
                    comp_instances.append(comp_cls(**comp_value))

            if comp_instances:
                new_eid = esper.create_entity(*comp_instances)
            else:
                new_eid = esper.create_entity(Transform())

            # ★ 建立 sid ↔ eid 双向映射
            st._sid_map[sid] = new_eid
            st._eid_to_sid[new_eid] = sid
            st.entities[f'{new_eid}'] = 1
            st._entity_names[new_eid] = ed.name
            st._editor_visible.add(new_eid)

            if ed.parent_id is not None:
                _pending_parents[new_eid] = ed.parent_id  # parent_sid

            has_mesh = any(isinstance(ci, MeshRenderer) for ci in comp_instances)
            if has_mesh:
                _renderer = getattr(st.app, 'renderer', None)
                if _renderer is not None:
                    _renderer.enqueue(EntityRegistrationCommand(new_eid, register=True))

        # ── 恢复父子关系 (parent_sid → parent_eid) ──
        for child_eid, parent_sid in _pending_parents.items():
            parent_eid = st._sid_map.get(parent_sid)
            if parent_eid is not None:
                st._entity_parent[child_eid] = parent_eid

        # ── 恢复主摄像机 (main_camera_entity_id 是 sid) ──
        if scene.main_camera_entity_id is not None:
            cam_eid = st._sid_map.get(scene.main_camera_entity_id)
            if cam_eid is not None:
                try:
                    st.main_camera_id = cam_eid
                    st.scene_camera = esper.component_for_entity(cam_eid, Camera)
                    st.scene_camera_id = cam_eid
                except KeyError:
                    st.main_camera_id = None
                    st.scene_camera = None
                    st.scene_camera_id = None

        # ── 恢复 2D 摄像机 ──
        st.main_camera_2d_id = None
        for entity_id_str in st.entities:
            eid = int(entity_id_str)
            try:
                if esper.has_component(eid, Camera):
                    cam = esper.component_for_entity(eid, Camera)
                    pt = getattr(cam, 'projection_type', None)
                    if pt is not None:
                        from Application.Core.Scene.BasicComponents import ProjectionType
                        if pt == ProjectionType.ORTHOGRAPHIC or str(pt) == 'orthographic':
                            st.main_camera_2d_id = eid
                            break
            except KeyError:
                pass

        # ── 兜底: 无摄像机 → 创建默认 ──
        has_camera = any(
            esper.has_component(int(eid_str), Camera)
            for eid_str in st.entities
        )
        if not has_camera:
            self._mgr.cam_mgr.create_defaults(st)

        st.game_type = scene.game_type
