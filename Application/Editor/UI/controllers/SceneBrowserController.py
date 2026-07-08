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
    def get_summary(cls, entity_id: int, use_local: bool = False) -> Optional[EntitySummary]:
        """获取实体组件摘要。use_local=True 时返回本地 Transform。"""
        try:
            if use_local:
                t = SceneManager.GetEntityLocalTransformEditor(entity_id)
            else:
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
    def set_position(cls, entity_id: int, position: tuple[float, float, float],
                     use_local: bool = False) -> None:
        """设置实体位置（编辑器坐标系）。use_local=True 写本地坐标。"""
        if use_local:
            SceneManager.SetEntityLocalTransformEditor(entity_id, position_xyz=position)
        else:
            SceneManager.SetEntityTransformEditor(entity_id, position_xyz=position)

    @classmethod
    def set_rotation(cls, entity_id: int, rotation: tuple[float, float, float],
                     use_local: bool = False) -> None:
        """设置实体旋转（欧拉角，角度制）。
        
        UI 层使用角度 (degrees)，内部存储为弧度 (radians)。
        """
        rot_rad = tuple(math.radians(r) for r in rotation)
        if use_local:
            SceneManager.SetEntityLocalTransformEditor(entity_id, rotation_xyz=rot_rad)
        else:
            SceneManager.SetEntityTransformEditor(entity_id, rotation_xyz=rot_rad)

    @classmethod
    def set_scale(cls, entity_id: int, scale: tuple[float, float, float],
                  use_local: bool = False) -> None:
        """设置实体缩放。"""
        if use_local:
            SceneManager.SetEntityLocalTransformEditor(entity_id, scale_xyz=scale)
        else:
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
                'is_perspective': cam.projection_type.value == 'perspective'
                    if hasattr(cam.projection_type, 'value') else True,
                'fov': cam.fov,
                'ortho_size': cam.ortho_size,
                'aspect_ratio': cam.aspect_ratio,
                'near': cam.near_plane,
                'far': cam.far_plane,
                'is_primary': cam.is_primary,
            }
        except Exception:
            return None

    @classmethod
    def set_camera_fov(cls, entity_id: int, fov: float) -> None:
        import esper
        cam = esper.component_for_entity(entity_id, Camera)
        cam.fov = max(1.0, min(179.0, fov))

    @classmethod
    def set_camera_ortho_size(cls, entity_id: int, size: float) -> None:
        import esper
        cam = esper.component_for_entity(entity_id, Camera)
        cam.ortho_size = max(0.01, size)

    @classmethod
    def set_camera_clip(cls, entity_id: int, near: float, far: float) -> None:
        import esper
        cam = esper.component_for_entity(entity_id, Camera)
        cam.near_plane = max(0.001, near)
        cam.far_plane = max(cam.near_plane + 0.01, far)

    @classmethod
    def set_camera_projection(cls, entity_id: int, is_perspective: bool) -> None:
        import esper
        from Application.Core.Scene.BasicComponents import ProjectionType
        cam = esper.component_for_entity(entity_id, Camera)
        cam.projection_type = (
            ProjectionType.PERSPECTIVE if is_perspective else ProjectionType.ORTHOGRAPHIC)

    # ── 实体层级 / Entity Hierarchy ───────────────────────────

    @classmethod
    def get_root_entities(cls) -> list[int]:
        """获取所有根实体（无父实体的）。"""
        return SceneManager.GetRootEntities()

    @classmethod
    def get_entity_children(cls, entity_id: int) -> list[int]:
        """获取实体的直接子实体 ID 列表。"""
        return SceneManager.GetEntityChildren(entity_id)

    @classmethod
    def get_entity_parent(cls, entity_id: int) -> int | None:
        """获取实体的父实体 ID。"""
        return SceneManager.GetEntityParent(entity_id)

    @classmethod
    def set_entity_parent(cls, child_id: int, parent_id: int) -> None:
        """设置父子关系。"""
        SceneManager.SetEntityParent(child_id, parent_id)

    @classmethod
    def get_entity_info(cls, entity_id: int) -> dict | None:
        """获取单个实体的摘要信息。"""
        infos = SceneManager.GetAllEntityInfos()
        for info in infos:
            if info['entity_id'] == entity_id:
                return info
        return None


# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_SCENE_BROWSER
register(NAME_SCENE_BROWSER, SceneBrowserController)
