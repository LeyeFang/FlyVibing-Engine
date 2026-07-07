"""场景浏览器 — 实体列表选择 & 检视逻辑"""

import math
from dataclasses import dataclass
from typing import Optional

from Application.Core.Scene.SceneManager import SceneManager
from Application.Core.Scene.BasicComponents import Camera


@dataclass
class EntitySummary:
    entity_id: int
    name: str = ""
    position: tuple[float, float, float] = (0, 0, 0)       # 编辑器坐标 (世界单位)
    rotation: tuple[float, float, float] = (0, 0, 0)       # 欧拉角 (角度制/degrees)
    scale: tuple[float, float, float] = (1, 1, 1)          # 缩放因子
    mesh_id: Optional[int] = None
    material_id: Optional[int] = None
    has_camera: bool = False


class SceneBrowserController:
    """实体选择与检视 — 纯数据层，不 import imgui"""

    selected_entity_id: Optional[int] = None

    # ── Spawn 模板 ─────────────────────────────────────────
    ENTITY_TEMPLATES: dict[str, list[str]] = {
        "Empty":  ["Transform"],
        "Cube":   ["Transform", "MeshRenderer"],
        "Camera": ["Transform", "Camera"],
    }

    # ── 实体列表 ────────────────────────────────────────────

    @classmethod
    def get_renderable_entities(cls) -> list[int]:
        return SceneManager.GetRenderableEntities()

    @classmethod
    def get_all_entity_infos(cls) -> list[dict]:
        """返回所有实体的摘要信息列表（含名称、组件标记）。"""
        return SceneManager.GetAllEntityInfos()

    # ── 实体选择 ────────────────────────────────────────────

    @classmethod
    def select(cls, entity_id: int) -> None:
        cls.selected_entity_id = entity_id

    @classmethod
    def get_selected(cls) -> Optional[int]:
        return cls.selected_entity_id

    @classmethod
    def clear_selection(cls) -> None:
        cls.selected_entity_id = None

    # ── 实体检视 ────────────────────────────────────────────

    @classmethod
    def get_summary(cls, entity_id: int) -> Optional[EntitySummary]:
        try:
            t = SceneManager.GetEntityTransformEditor(entity_id)
            # Transform 组件存储弧度为内部约定，UI 层转为角度显示
            rot_rad = t['rotation']
            rot_deg = tuple(math.degrees(r) for r in rot_rad)
            summary = EntitySummary(
                entity_id=entity_id,
                name=SceneManager.GetEntityName(entity_id),
                position=t['position'],
                rotation=rot_deg,
                scale=t['scale'],
            )
            try:
                summary.mesh_id = SceneManager.GetEntityMesh(entity_id)
            except Exception:
                pass
            try:
                summary.material_id = SceneManager.GetEntityMaterial(entity_id)
            except Exception:
                pass
            try:
                import esper
                summary.has_camera = esper.has_component(entity_id, Camera)
            except Exception:
                pass
            return summary
        except Exception:
            return None

    # ── 实体属性编辑 ────────────────────────────────────────

    @classmethod
    def set_position(cls, entity_id: int, position: tuple[float, float, float]) -> None:
        """设置实体位置（编辑器坐标系）。"""
        SceneManager.SetEntityTransformEditor(entity_id, position_xyz=position)

    @classmethod
    def set_rotation(cls, entity_id: int, rotation: tuple[float, float, float]) -> None:
        """设置实体旋转（欧拉角，角度制）。
        
        UI 层使用角度 (degrees)，内部存储为弧度 (radians)。
        """
        rot_rad = tuple(math.radians(r) for r in rotation)
        SceneManager.SetEntityTransformEditor(entity_id, rotation_xyz=rot_rad)

    @classmethod
    def set_scale(cls, entity_id: int, scale: tuple[float, float, float]) -> None:
        """设置实体缩放。"""
        SceneManager.SetEntityTransformEditor(entity_id, scale_xyz=scale)

    @classmethod
    def set_name(cls, entity_id: int, name: str) -> None:
        """设置实体名称。"""
        SceneManager.SetEntityName(entity_id, name)

    @classmethod
    def get_camera_info(cls, entity_id: int) -> Optional[dict]:
        """获取实体的 Camera 组件信息（用于检视面板）。"""
        try:
            import esper
            cam = esper.component_for_entity(entity_id, Camera)
            return {
                'projection': cam.projection_type.value
                    if hasattr(cam.projection_type, 'value') else str(cam.projection_type),
                'fov': cam.fov,
                'near': cam.near_plane,
                'far': cam.far_plane,
                'is_primary': cam.is_primary,
            }
        except Exception:
            return None


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SCENE_BROWSER
register(NAME_SCENE_BROWSER, SceneBrowserController)
