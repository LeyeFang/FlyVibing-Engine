"""
CameraManager — 摄像机生命周期管理。

职责:
  - 默认摄像机创建 (3D + 2D)
  - GameType 摄像机切换
  - 主摄像机 ID 访问

组合模式:
  CameraManager 由 SceneManager 实例化，通过 self._mgr 访问其他子管理器。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

import math
import esper

from Application.Core.Scene.BasicComponents import Transform, Camera, ProjectionType
from Application.Core.Scene.Scene import GameType

if TYPE_CHECKING:
    from Application.Core.Scene.SceneManager import SceneManager


class CameraManager:
    """摄像机生命周期管理。"""

    def __init__(self, scene_mgr: SceneManager) -> None:
        self._mgr = scene_mgr

    def create_defaults(self, st: SceneManager) -> None:
        """在指定 SceneManager 的 esper 世界中创建默认摄像机 (3D + 2D + Overlay)。"""
        # ── 3D 透视摄像机 ──
        st.main_camera_id = esper.create_entity(
            Transform(position_x=0.0, position_y=0.0, position_z=10.0),
            Camera(is_primary=True),
        )
        st.scene_camera_id = st.main_camera_id
        st.scene_camera = esper.component_for_entity(st.scene_camera_id, Camera)
        st.entities[f'{st.main_camera_id}'] = 1
        st._entity_names[st.main_camera_id] = "DefaultCamera3D"
        st._editor_visible.add(st.main_camera_id)

        # ── 2D 正交俯视摄像机 ──
        st.main_camera_2d_id = esper.create_entity(
            Transform(
                position_x=0.0, position_y=0.0, position_z=10.0,
                rotation_x=math.pi / 2.0,
            ),
            Camera(is_primary=False),
        )
        cam_2d = esper.component_for_entity(st.main_camera_2d_id, Camera)
        cam_2d.projection_type = ProjectionType.ORTHOGRAPHIC
        cam_2d.ortho_size = 10.0
        cam_2d.near_plane = 0.1
        cam_2d.far_plane = 100.0
        st.entities[f'{st.main_camera_2d_id}'] = 1
        st._entity_names[st.main_camera_2d_id] = "DefaultCamera2D"
        st._editor_visible.add(st.main_camera_2d_id)

        # ── Overlay 正交摄像机 (屏幕空间, 原点在中心) ──
        st.main_camera_overlay_id = esper.create_entity(
            Transform(
                position_x=0.0, position_y=0.0, position_z=5.0,
                rotation_x=math.pi / 2.0,  # 俯视 GL XZ 平面
            ),
            Camera(is_primary=False),
        )
        cam_overlay = esper.component_for_entity(st.main_camera_overlay_id, Camera)
        cam_overlay.projection_type = ProjectionType.ORTHOGRAPHIC
        cam_overlay.ortho_size = 5.0     # 屏幕半高 (NDC 对应 [-5,5])
        cam_overlay.near_plane = 0.01
        cam_overlay.far_plane = 100.0
        st.entities[f'{st.main_camera_overlay_id}'] = 1
        st._entity_names[st.main_camera_overlay_id] = "DefaultCameraOverlay"
        st._editor_visible.add(st.main_camera_overlay_id)

    def get_main_id(self) -> int | None:
        return self._mgr.main_camera_id

    def get_main_2d_id(self) -> int | None:
        return self._mgr.main_camera_2d_id

    def get_main_overlay_id(self) -> int | None:
        return self._mgr.main_camera_overlay_id

    def set_game_type(self, game_type) -> None:
        """设置场景游戏类型并自动切换默认摄像机。"""
        if isinstance(game_type, str):
            game_type = GameType(game_type)
        st = self._mgr
        if st.game_type == game_type:
            return
        st.game_type = game_type
        self._apply(st)

    def get_game_type(self):
        return self._mgr.game_type

    def _apply(self, st: SceneManager) -> None:
        """根据 game_type 选择默认摄像机 (更新 scene_camera_id + scene_camera 引用)。"""
        if st.game_type == GameType.GAME_2D and st.main_camera_2d_id is not None:
            st.scene_camera_id = st.main_camera_2d_id
        elif st.game_type == GameType.OVERLAY and st.main_camera_overlay_id is not None:
            st.scene_camera_id = st.main_camera_overlay_id
        else:
            st.scene_camera_id = st.main_camera_id

        # ★ 同步 scene_camera 组件引用
        if st.scene_camera_id is not None:
            try:
                st.scene_camera = esper.component_for_entity(st.scene_camera_id, Camera)
            except KeyError:
                st.scene_camera = None
