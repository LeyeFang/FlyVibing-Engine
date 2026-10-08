"""
EditorGizmoLayer — 摄像机 Entity Gizmo 可视化与预览模式（从 EditorLayer 拆分）。

职责:
  - Camera entity 的 gizmo 注册/刷新/注销 (frustum / 2D boundary / icon)
  - SPACE 摄像机预览切换 (_toggle_preview_camera)
  - 选中变化 → gizmo 失效回调

依赖:
  - cls.renderer      — EditorLayer 在 OnAttach 前注入
  - cls._editor_layer — EditorLayer 在 OnAttach 前注入 (调用 _sync_camera_to_renderer)
"""

from __future__ import annotations

import numpy as np

from Application.Core.Layers.Layer import Layer
from Application.Core.Events.Event import Event
from Application.Editor.EditorHost import EditorHost
from Application.Editor.EditorCamera import EditorCamera
from Application.Editor.Gizmos.CameraFrustum import CameraFrustum
from Application.Editor.Gizmos.Camera2DBoundary import Camera2DBoundary
from Application.Editor.Gizmos.CameraIconGizmo import CameraIconGizmo


class EditorGizmoLayer(Layer):
    """摄像机 Gizmo 层 — 管理 ECS Camera entity 的可视化表示。"""

    renderer = None       # EditorLayer 注入
    _editor_layer = None  # EditorLayer 注入

    _camera_gizmo_keys: set[str] = set()
    _camera_gizmo_state_hash: int = -1
    _preview_entity_id: int | None = None
    _camera_gizmo_frame_skip: int = 0

    _CAM_GIZMO_REFRESH_INTERVAL: int = 10

    # ── Light 图标 (与 camera 图标同范式/同可见性规则) ──
    _light_gizmo_keys: set[str] = set()
    _light_gizmo_state_hash: int = -1
    _light_gizmo_frame_skip: int = 0

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    @classmethod
    def OnAttach(cls):
        super().OnAttach()
        cls._refresh_camera_gizmos(force=True)
        cls._refresh_light_gizmos(force=True)
        from Application.Editor.UI.controllers.SelectionController import SelectionController
        SelectionController.register_selection_callback(cls.invalidate_camera_gizmos)
        SelectionController.register_selection_callback(cls.invalidate_light_gizmos)

    @classmethod
    def OnDetach(cls):
        cls._unregister_all_camera_gizmos()
        cls._unregister_all_light_gizmos()
        cls._camera_gizmo_state_hash = -1
        cls._light_gizmo_state_hash = -1
        cls._preview_entity_id = None

    @classmethod
    def OnUpdate(cls):
        cls._refresh_camera_gizmos()
        cls._refresh_light_gizmos()

    @classmethod
    def OnEvent(cls, event: Event) -> None:
        pass

    # ════════════════════════════════════════════════════════════
    # 预览切换
    # ════════════════════════════════════════════════════════════

    @classmethod
    def _toggle_preview_camera(cls) -> None:
        """SPACE: 切换编辑器摄像机 / entity 摄像机预览。

        Overlay 模式使用专属 overlay 摄像机, 2D 模式使用 2D 摄像机,
        3D 模式使用 3D 透视摄像机。
        """
        from Application.Editor.UI.controllers.ViewportController import ViewportController
        from Application.Core.Scene.Scene import GameType
        if cls._preview_entity_id is not None:
            cls._preview_entity_id = None
            print("[EditorGizmoLayer] Preview: OFF (editor camera)")
        else:
            is_2d = ViewportController.is_2d()
            is_overlay = (EditorHost.scene is not None
                          and EditorHost.scene.game_type == GameType.OVERLAY)
            if is_overlay:
                cls._preview_entity_id = EditorHost.scene.get_main_camera_overlay_id()
            elif is_2d:
                cls._preview_entity_id = EditorHost.scene.get_main_camera_2d_id()
            else:
                cls._preview_entity_id = EditorHost.scene.get_main_camera_id()
            print(f"[EditorGizmoLayer] Preview: ON (entity {cls._preview_entity_id})")
        cls.invalidate_camera_gizmos()
        if cls._editor_layer is not None:
            cls._editor_layer._sync_camera_to_renderer()

    @classmethod
    def invalidate_camera_gizmos(cls) -> None:
        """标记 camera gizmo 需要重建。"""
        cls._camera_gizmo_state_hash = -1
        cls._camera_gizmo_frame_skip = 0

    @classmethod
    def _refresh_camera_gizmos(cls, force: bool = False) -> None:
        """遍历 ECS 中所有 Camera entity，注册/更新对应的 gizmo overlay。"""
        if cls.renderer is None:
            return

        if not force and cls._camera_gizmo_state_hash >= 0:
            cls._camera_gizmo_frame_skip += 1
            if cls._camera_gizmo_frame_skip < cls._CAM_GIZMO_REFRESH_INTERVAL:
                return
            cls._camera_gizmo_frame_skip = 0

        from Application.Core.Scene.GizmoQuery import GizmoQuery
        from Application.Editor.UI.controllers.SelectionController import SelectionController
        from Application.Core.Renderer.RenderCommand import (
            OverlayRegistrationCommand, OverlayUnregistrationCommand)

        try:
            selected_id = SelectionController.get_selected()
            selected_ids = {selected_id} if selected_id is not None else set()
        except Exception:
            selected_ids = set()

        try:
            cam_list = GizmoQuery.get_camera_gizmos(selected_ids=selected_ids)
        except Exception:
            import traceback
            traceback.print_exc()
            return

        if not cam_list:
            if cls._camera_gizmo_state_hash != -2:
                pass
            cls._camera_gizmo_state_hash = -2
            return

        state_parts: list[tuple] = []
        for cd in cam_list:
            pos = tuple(round(v, 4) for v in cd.position)
            rot = tuple(round(r, 4) for r in cd.rotation)
            scl = tuple(round(s, 4) for s in cd.scale)
            state_parts.append((cd.entity_id, pos, rot, scl,
                                cd.is_perspective, cd.is_selected,
                                cd.is_editor_visible,
                                round(cd.aspect_ratio, 4),
                                round(cd.fov, 2),
                                round(cd.ortho_size, 2)))
        new_hash = hash(frozenset(state_parts))

        if not force and new_hash == cls._camera_gizmo_state_hash:
            cls._camera_gizmo_frame_skip = 0
            return
        cls._camera_gizmo_state_hash = new_hash

        from Application.Core.Math.Transform import calculate_entity_model
        from Application.Editor.UI.controllers.ViewportController import ViewportController
        is_2d = ViewportController.is_2d()
        preview_eid = cls._preview_entity_id
        cls._unregister_all_camera_gizmos()
        for cam_data in cam_list:
            if preview_eid is not None and cam_data.entity_id == preview_eid:
                continue
            if not cam_data.is_editor_visible:
                continue
            if is_2d and cam_data.is_perspective:
                continue
            if not is_2d and not cam_data.is_perspective:
                continue

            if cam_data.is_perspective:
                overlay = CameraFrustum.build_overlay(cam_data)
                cls.renderer.enqueue(OverlayRegistrationCommand(overlay))
                cls._camera_gizmo_keys.add(overlay.key)

                model = calculate_entity_model(
                    position=cam_data.position, rotation=cam_data.rotation,
                    scale=cam_data.scale)
                world_pos = (float(model[3, 0]), float(model[3, 1]), float(model[3, 2]))
                icon = CameraIconGizmo.build_icon_overlay(cam_data.entity_id, world_pos)
                cls.renderer.enqueue(OverlayRegistrationCommand(icon))
                cls._camera_gizmo_keys.add(icon.key)
            else:
                overlay = Camera2DBoundary.build_overlay(cam_data)
                cls.renderer.enqueue(OverlayRegistrationCommand(overlay))
                cls._camera_gizmo_keys.add(overlay.key)

    @classmethod
    def _unregister_all_camera_gizmos(cls) -> None:
        """注销所有已注册的 camera gizmo overlay。"""
        from Application.Core.Renderer.RenderCommand import OverlayUnregistrationCommand
        for key in list(cls._camera_gizmo_keys):
            if cls.renderer is not None:
                cls.renderer.enqueue(OverlayUnregistrationCommand(key))
        cls._camera_gizmo_keys.clear()

    # ════════════════════════════════════════════════════════
    # Light 图标 (与 camera 图标同范式/同可见性规则)
    # ════════════════════════════════════════════════════════

    @classmethod
    def invalidate_light_gizmos(cls) -> None:
        """标记 light gizmo 需要重建。"""
        cls._light_gizmo_state_hash = -1
        cls._light_gizmo_frame_skip = 0

    @classmethod
    def _refresh_light_gizmos(cls, force: bool = False) -> None:
        """遍历 ECS 中所有 Light entity，注册/更新光位图标。

        可见性规则与 camera 一致: `_editor_visible` (眼图标) 关闭 → 不注册。
        """
        if cls.renderer is None:
            return

        if not force and cls._light_gizmo_state_hash >= 0:
            cls._light_gizmo_frame_skip += 1
            if cls._light_gizmo_frame_skip < cls._CAM_GIZMO_REFRESH_INTERVAL:
                return
            cls._light_gizmo_frame_skip = 0

        from Application.Core.Scene.GizmoQuery import GizmoQuery
        from Application.Editor.UI.controllers.SelectionController import SelectionController
        from Application.Core.Renderer.RenderCommand import (
            OverlayRegistrationCommand, OverlayUnregistrationCommand)

        try:
            selected_id = SelectionController.get_selected()
            selected_ids = {selected_id} if selected_id is not None else set()
        except Exception:
            selected_ids = set()

        try:
            light_list = GizmoQuery.get_light_gizmos(selected_ids=selected_ids)
        except Exception:
            import traceback
            traceback.print_exc()
            return

        state_parts: list[tuple] = []
        for ld in light_list:
            pos = tuple(round(v, 4) for v in ld.position)
            rot = tuple(round(r, 4) for r in ld.rotation)
            scl = tuple(round(s, 4) for s in ld.scale)
            state_parts.append((ld.entity_id, pos, rot, scl,
                                ld.light_type, round(ld.range, 3),
                                ld.is_selected, ld.is_editor_visible,
                                round(ld.intensity, 3)))
        new_hash = hash(frozenset(state_parts))
        if not force and new_hash == cls._light_gizmo_state_hash:
            cls._light_gizmo_frame_skip = 0
            return
        cls._light_gizmo_state_hash = new_hash

        from Application.Core.Math.Transform import calculate_entity_model
        from Application.Editor.Gizmos.LightIconGizmo import LightIconGizmo

        cls._unregister_all_light_gizmos()
        for ld in light_list:
            if not ld.is_editor_visible:
                continue
            model = calculate_entity_model(
                position=ld.position, rotation=ld.rotation, scale=ld.scale)
            world_pos = (float(model[3, 0]), float(model[3, 1]), float(model[3, 2]))
            overlay = LightIconGizmo.build_icon_overlay(
                ld.entity_id, world_pos, is_selected=ld.is_selected)
            cls.renderer.enqueue(OverlayRegistrationCommand(overlay))
            cls._light_gizmo_keys.add(overlay.key)
            # ★ 方向射线 — 仅平面光 (点光无方向)
            if ld.light_type != 'point':
                ray = LightIconGizmo.build_ray_overlay(
                    ld.entity_id, world_pos, ld.direction, is_selected=ld.is_selected)
                cls.renderer.enqueue(OverlayRegistrationCommand(ray))
                cls._light_gizmo_keys.add(ray.key)

    @classmethod
    def _unregister_all_light_gizmos(cls) -> None:
        """注销所有已注册的 light gizmo overlay。"""
        from Application.Core.Renderer.RenderCommand import OverlayUnregistrationCommand
        for key in list(cls._light_gizmo_keys):
            if cls.renderer is not None:
                cls.renderer.enqueue(OverlayUnregistrationCommand(key))
        cls._light_gizmo_keys.clear()
