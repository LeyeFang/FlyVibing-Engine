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
        """在指定 SceneManager 的 esper 世界中创建默认摄像机 (通过 Prefab 实例化)。"""
        from Application.Resource.ResourceManager import ResourceManager
        from Application.Core.Scene.PrefabManager import PrefabManager

        def _instantiate_named_prefab(name: str) -> int | None:
            """查找已加载的内置 prefab 并实例化到场景。返回 root entity ID。"""
            for pid_str, pdata in ResourceManager.loaded_prefab.items():
                if pdata.get('name') == name and pdata.get('prefab_data') is not None:
                    eids = PrefabManager.instantiate_to_scene(pdata['prefab_data'], st)
                    return eids[0] if eids else None
            return None

        # ── 3D 透视摄像机 ──
        eid_3d = _instantiate_named_prefab('DefaultCamera3D')
        if eid_3d is not None:
            st.main_camera_id = eid_3d
            st.scene_camera_id = eid_3d
            import esper
            st.scene_camera = esper.component_for_entity(eid_3d, Camera)

        # ── 2D 正交俯视摄像机 ──
        eid_2d = _instantiate_named_prefab('DefaultCamera2D')
        if eid_2d is not None:
            st.main_camera_2d_id = eid_2d

        # ── Overlay 正交摄像机 ──
        eid_ov = _instantiate_named_prefab('DefaultCameraOverlay')
        if eid_ov is not None:
            st.main_camera_overlay_id = eid_ov

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
